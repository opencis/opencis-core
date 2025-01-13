"""
 Copyright (c) 2024, Eeum, Inc.
 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

# pylint: disable=unused-import
from asyncio import CancelledError, gather, create_task, Event, sleep
import glob
from io import BytesIO
import math
from typing import cast
import shutil
from pathlib import Path
import json
import os

import torch
from PIL import Image
from torch import nn
from torch.utils.data import DataLoader
from torchvision import transforms, datasets
from torchvision.models import efficientnet_v2_s, EfficientNet_V2_S_Weights
from torchinfo import summary
from tqdm.auto import tqdm

from opencis.util.logger import logger
from opencis.util.number import split_int
from opencis.cxl.device.cxl_type1_device import CxlType1Device, CxlType1DeviceConfig
from opencis.cxl.device.cxl_type2_device import (
    CxlType2Device,
    CxlType2DeviceConfig,
)
from opencis.cxl.component.irq_manager import Irq, IrqManager
from opencis.cxl.component.switch_connection_client import SwitchConnectionClient
from opencis.cxl.component.common import CXL_COMPONENT_TYPE
from opencis.util.component import RunnableComponent


class MyType1Accelerator(RunnableComponent):
    """
    This demo app uses CXL.cache to read metadata from the host memory, uses the
    metadata to train an image classification model, then finally uses CXL.cache
    to rewrite the training results to the host memory.
    The demo app also supports host "validation": the device can copy an image
    from some predefined address in host memory, run the trained model on the
    retrieved image, and write the class probabilities back to the host memory.
    """

    def __init__(
        self,
        port_index: int,
        host: str = "0.0.0.0",
        port: int = 8000,
        server_port: int = 9050,
        device_id: int = 0,
        host_mem_size: int = 0,
        train_data_path: str = "",
    ):
        label = f"Port{port_index}"
        super().__init__(label)

        if not os.path.exists(train_data_path) or not os.path.isdir(train_data_path):
            raise Exception(f"Path {train_data_path} does not exist, or is not a folder.")

        self._sw_conn_client = SwitchConnectionClient(
            port_index, CXL_COMPONENT_TYPE.T1, host=host, port=port
        )
        self._cxl_type1_device = CxlType1Device(
            CxlType1DeviceConfig(
                transport_connection=self._sw_conn_client.get_cxl_connection(),
                device_name=label,
                device_id=device_id,
                host_mem_size=host_mem_size,
            )
        )
        self._wait_tasks = []
        self._device_id = device_id
        self.original_base_folder = train_data_path
        self.accel_dirname = f"/tmp/T1Accel@{self._label}"
        if os.path.exists(self.accel_dirname) and os.path.isdir(self.accel_dirname):
            shutil.rmtree(self.accel_dirname)
        Path(self.accel_dirname).mkdir(parents=True, exist_ok=True)
        self._train_folder = os.path.abspath(os.path.join(self.accel_dirname, "train"))
        self._val_folder = os.path.abspath(os.path.join(self.accel_dirname, "val"))
        symlink_train_src = os.path.abspath(os.path.join(self.original_base_folder, "train"))
        symlink_val_src = os.path.abspath(os.path.join(self.original_base_folder, "val"))
        os.symlink(
            src=symlink_train_src,
            dst=self._train_folder,
            target_is_directory=True,
        )
        os.symlink(
            src=symlink_val_src,
            dst=self._val_folder,
            target_is_directory=True,
        )

        self._irq_manager = IrqManager(
            addr="127.0.0.1", port=server_port, device_name=label, device_id=device_id
        )

        self._stop_signal = Event()
        self._stop_flag = False

        self._irq_manager.register_interrupt_handler(Irq.HOST_READY, self._run_app)
        self._irq_manager.register_interrupt_handler(Irq.HOST_SENT, self._validate_model)
        self._torch_device = None

    def set_stop_flag(self):
        self._stop_flag = True

    def _train_one_epoch(
        self,
        train_dataloader: DataLoader,
        test_dataloader: DataLoader,
        device: torch.device,
        optimizer,
        loss_fn,
    ):
        # pylint: disable=unused-variable
        self._model.train()
        correct_count = 0
        running_train_loss = 0
        inputs: torch.Tensor
        labels: torch.Tensor
        for _, (inputs, labels) in tqdm(
            enumerate(train_dataloader),
            total=len(train_dataloader),
            desc=f"Dev {self._device_id} Training Progress",
            position=self._device_id,
            leave=False,
        ):
            if self._stop_flag:
                return
            inputs = inputs.to(device)
            labels = labels.to(device)

            # logits
            pred_logits = self._model(inputs)
            loss = loss_fn(pred_logits, labels)
            predicted_prob = torch.softmax(pred_logits, dim=1)
            pred_classes = torch.argmax(predicted_prob, dim=1)

            loss.backward()

            optimizer.step()

            is_correct = pred_classes == labels
            correct_count += is_correct.sum()
            running_train_loss += loss.item() * inputs.size(0)

        train_loss = running_train_loss / len(train_dataloader.sampler)
        train_accuracy = correct_count / len(train_dataloader.sampler)
        logger.debug(
            self._create_message(f"train_loss: {train_loss}, train_accuracy: {train_accuracy}")
        )

        if device == "cuda:0":
            torch.cuda.empty_cache()

        self._model.eval()
        with torch.no_grad():
            running_test_loss = 0
            correct_count = 0
            for _, (inputs, labels) in tqdm(
                enumerate(test_dataloader),
                total=len(test_dataloader),
                desc=f"Dev {self._device_id} Cross-validation Progress",
                position=self._device_id,
                leave=False,
            ):
                if self._stop_flag:
                    return
                inputs = inputs.to(device)
                labels = labels.to(device)

                pred_logit = self._model(inputs)
                loss = loss_fn(pred_logit, labels)
                running_test_loss += loss.item() * inputs.size(0)

                pred_classes = torch.argmax(pred_logit, dim=1)
                is_correct = pred_classes == labels

                correct_count += is_correct.sum()

                # logits to probs, placeholder
                pred_probs = torch.softmax(pred_logit, dim=1)

        test_loss = running_test_loss / len(test_dataloader.sampler)
        test_accuracy = correct_count / len(test_dataloader.sampler)

        logger.debug(f"test_loss: {test_loss}, test_accuracy: {test_accuracy}")

    async def _get_metadata(self):
        # When retrieving the metadata, the device does not know ahead of time where
        # the metadata is located, nor the size of the metadata. The host relays this
        # information by writing to hardcoded HPAs. Once the accelerator receives the
        # HOST_READY interrupt, it will read the address and size of the metadata from
        # the host memory using CXL.cache, then use CXL.cache again to appropriately
        # request the data from the host, one cacheline at a time.

        metadata_addr_mmio_addr = 0x1800
        metadata_size_mmio_addr = 0x1808
        metadata_addr = await self._cxl_type1_device.read_mmio(metadata_addr_mmio_addr, 8)
        metadata_size = await self._cxl_type1_device.read_mmio(metadata_size_mmio_addr, 8)

        metadata_rounded_size = ((metadata_size - 1) // 64 + 1) * 64
        metadata_end = metadata_addr + metadata_size

        logger.debug(self._create_message("Writing metadata"))
        with open(f"{self.accel_dirname}{os.path.sep}noisy_imagenette.csv", "wb") as md_file:
            logger.debug(self._create_message(f"addr: 0x{metadata_addr:x}"))
            logger.debug(self._create_message(f"end: 0x{metadata_end:x}"))

            start = metadata_addr
            end = metadata_addr + metadata_rounded_size
            data = b""
            with tqdm(
                total=metadata_size,
                desc=f"Dev {self._device_id} Reading Metadata",
                unit="iB",
                unit_scale=True,
                unit_divisor=1024,
                position=self._device_id,
                leave=False,
            ) as pbar:
                for cacheline_offset in range(start, end, 64):
                    cacheline = await self._cxl_type1_device.cxl_cache_readline(cacheline_offset)
                    chunk_size = min(64, (metadata_end - cacheline_offset))
                    chunk_data = cacheline.to_bytes(64, "little")
                    data = chunk_data[:chunk_size]
                    md_file.write(data)
                    pbar.update(chunk_size)

        logger.info(self._create_message(f"Dev {self._device_id} Finished writing file"))

    async def _get_test_image(self) -> bytes:

        image_addr = 0x00008000
        image_size = 0x00008000 + 64

        image_end = image_addr + image_size

        cacheline = await self._cxl_type1_device.cxl_cache_read(image_addr, image_end)

        return cacheline

    async def _validate_model(self, _):
        # pylint: disable=E1101
        # im = await self._get_test_image()

        json_asenc = b"2" * 64
        json_asint = int.from_bytes(json_asenc, "little")

        RESULTS_HPA = 0x00008000  # Arbitrarily chosen

        rounded_bytes_size = 64
        await self._cxl_type1_device.cxl_cache_write(RESULTS_HPA, rounded_bytes_size, json_asint)

        # Done with eval
        await self._irq_manager.send_irq_request(Irq.ACCEL_VALIDATION_FINISHED)

    async def _run_app(self, _):
        try:
            await self._irq_manager.send_irq_request(Irq.ACCEL_TRAINING_FINISHED)
        except CancelledError:
            print(self._create_message("Runapp Cancelled"))
            return

    async def _app_shutdown(self):
        logger.info(self._create_message("Removing accelerator directory"))
        shutil.rmtree(self.accel_dirname)

    async def _run(self):
        tasks = [
            create_task(self._sw_conn_client.run()),
            create_task(self._cxl_type1_device.run()),
            create_task(self._irq_manager.run()),
            create_task(self._stop_signal.wait()),
        ]

        self._wait_tasks = [
            create_task(self._sw_conn_client.wait_for_ready()),
            create_task(self._cxl_type1_device.wait_for_ready()),
            create_task(self._irq_manager.wait_for_ready()),
            create_task(self._irq_manager.start_connection()),
        ]
        await self._change_status_to_running()
        await gather(*tasks)

    async def _stop(self):
        self._stop_flag = True
        for task in self._wait_tasks:
            task.cancel()
        self._stop_signal.set()
        tasks = [
            create_task(self._sw_conn_client.stop()),
            create_task(self._cxl_type1_device.stop()),
            create_task(self._irq_manager.stop()),
        ]
        await gather(*tasks)
        await self._app_shutdown()


class MyType2Accelerator(RunnableComponent):
    """
    This demo app demonstrates the host's ability to write metadata to the
    device cached memory via CXL.mem; after the device uses this metadata to
    train an image classification model, the host can use CXL.mem to read
    the training results from the device memory.
    The demo app also supports host "validation": the host can copy an image into
    some predefined address in device memory, send an interrupt to the device to
    start training, and read the class probabilities after training concludes.
    """

    # pylint: disable=unused-argument
    def __init__(
        self,
        port_index: int,
        memory_size: int,
        memory_file: str,
        host: str = "0.0.0.0",
        port: int = 8000,
        server_port: int = 9050,
        device_id: int = 0,
        train_data_path: str = None,
    ):
        label = f"Port{port_index}"
        super().__init__(label)
        self._sw_conn_client = SwitchConnectionClient(
            port_index, CXL_COMPONENT_TYPE.T2, host=host, port=port
        )

        self._device_id = device_id
        self.accel_dirname = f"/tmp/T2Accel@{port_index}"
        self.train_data_path = train_data_path
        self._torch_device = None
        self._cxl_type2_device = None

        self._device_config = CxlType2DeviceConfig(
            device_name=label,
            transport_connection=self._sw_conn_client.get_cxl_connection(),
            memory_size=memory_size,
            memory_file=memory_file,
        )

        self._irq_manager = IrqManager(
            addr="localhost",
            port=server_port,
            device_name=label,
            device_id=device_id,
        )

        self._stop_signal = Event()

        self._irq_manager.register_interrupt_handler(Irq.HOST_READY, self._run_app)
        self._irq_manager.register_interrupt_handler(Irq.HOST_SENT, self._validate_model)

        self._model = None
        self._transform = None
        self._train_dataset = None
        self._test_dataloader = None
        self._wait_tasks = None
        self._train_dataloader = None
        self._test_dataset = None
        self._val_folder = None

    def _setup_test_env(self):
        if not os.path.isdir(self.accel_dirname):
            os.mkdir(self.accel_dirname)

        train_dir = os.path.join(self.train_data_path, "train")
        val_dir = os.path.join(self.train_data_path, "val")

        train_dir = os.path.abspath(train_dir)
        val_dir = os.path.abspath(val_dir)
        self._val_folder = val_dir

        logger.debug(
            self._create_message(f"Changing into accelerator directory: {self.accel_dirname}")
        )

        os.chdir(self.accel_dirname)

        self._cxl_type2_device = CxlType2Device(self._device_config)

        # Model setup
        self._model = efficientnet_v2_s(weights=EfficientNet_V2_S_Weights.DEFAULT)

        self._model.classifier[1] = nn.Linear(in_features=1280, out_features=10, bias=True)
        for p in self._model.features.parameters():
            p.requires_grad = False
        summary(self._model, input_size=(1, 3, 160, 160))

        self._transform = transforms.Compose(
            [
                transforms.Resize((160, 160)),
                transforms.ToTensor(),
            ]
        )

        self._train_dataset = datasets.ImageFolder(root=train_dir, transform=self._transform)
        self._train_dataloader = DataLoader(
            self._train_dataset, batch_size=32, shuffle=True, num_workers=4
        )

        self._test_dataset = datasets.ImageFolder(root=val_dir, transform=self._transform)
        self._test_dataloader = DataLoader(
            self._train_dataset, batch_size=10, shuffle=True, num_workers=4
        )

    def _train_one_epoch(
        self,
        train_dataloader: DataLoader,
        test_dataloader: DataLoader,
        device: torch.device,
        optimizer,
        loss_fn,
    ):
        # pylint: disable=unused-variable
        self._model.train()
        correct_count = 0
        running_train_loss = 0
        inputs: torch.Tensor
        labels: torch.Tensor
        for _, (inputs, labels) in tqdm(
            enumerate(train_dataloader),
            total=len(train_dataloader),
            desc=f"Dev {self._device_id} Training Progress",
            position=self._device_id,
            leave=False,
        ):
            inputs = inputs.to(device)
            labels = labels.to(device)

            # logits
            pred_logits = self._model(inputs)
            loss = loss_fn(pred_logits, labels)
            predicted_prob = torch.softmax(pred_logits, dim=1)
            pred_classes = torch.argmax(predicted_prob, dim=1)

            loss.backward()

            optimizer.step()

            is_correct = pred_classes == labels
            correct_count += is_correct.sum()
            running_train_loss += loss.item() * inputs.size(0)

        train_loss = running_train_loss / len(train_dataloader.sampler)
        train_accuracy = correct_count / len(train_dataloader.sampler)
        logger.debug(
            self._create_message(f"train_loss: {train_loss}, train_accuracy: {train_accuracy}")
        )

        if device == "cuda:0":
            torch.cuda.empty_cache()

        self._model.eval()
        with torch.no_grad():
            running_test_loss = 0
            correct_count = 0
            for _, (inputs, labels) in tqdm(
                enumerate(test_dataloader),
                total=len(test_dataloader),
                desc=f"Dev {self._device_id} Cross-validation Progress",
                position=self._device_id,
                leave=False,
            ):
                inputs = inputs.to(device)
                labels = labels.to(device)

                pred_logit = self._model(inputs)
                loss = loss_fn(pred_logit, labels)
                running_test_loss += loss.item() * inputs.size(0)

                pred_classes = torch.argmax(pred_logit, dim=1)
                is_correct = pred_classes == labels

                correct_count += is_correct.sum()

                # logits to probs, placeholder
                pred_probs = torch.softmax(pred_logit, dim=1)

        test_loss = running_test_loss / len(test_dataloader.sampler)
        test_accuracy = correct_count / len(test_dataloader.sampler)

        logger.debug(f"test_loss: {test_loss}, test_accuracy: {test_accuracy}")

    async def _get_metadata(self):
        metadata_addr_mmio_addr = 0x1800
        metadata_size_mmio_addr = 0x1808
        metadata_addr = await self._cxl_type2_device.read_mmio(metadata_addr_mmio_addr, 8)
        metadata_size = await self._cxl_type2_device.read_mmio(metadata_size_mmio_addr, 8)

        # round to 64
        metadata_size = ((metadata_size - 1) // 64 + 1) * 64

        metadata_end = metadata_addr + metadata_size

        with open("noisy_imagenette.csv", "wb") as md_file:
            logger.debug(self._create_message(f"addr: 0x{metadata_addr:x}"))
            logger.debug(self._create_message(f"end: 0x{metadata_end:x}"))
            curr_written = 0
            with tqdm(
                total=metadata_size,
                desc=f"Dev {self._device_id} Reading Metadata",
                unit="iB",
                unit_scale=True,
                unit_divisor=1024,
                position=self._device_id,
                leave=False,
            ) as pbar:
                for offset in range(0, metadata_size, 64):
                    data = await self._cxl_type2_device.read_mem_hpa(metadata_addr + offset, 64)
                    curr_written += 64
                    md_file.write(data.to_bytes(64, byteorder="little"))
                    pbar.update(64)

    async def _get_test_image(self) -> Image.Image:
        image_addr_mmio_addr = 0x1810
        image_size_mmio_addr = 0x1818
        image_addr = await self._cxl_type2_device.read_mmio(image_addr_mmio_addr, 8)
        image_size = await self._cxl_type2_device.read_mmio(image_size_mmio_addr, 8)

        im = None
        # for cacheline_offset in range(address, address + size, 64):
        #     cacheline = await self.cxl_cache_readline(cacheline_offset)
        #     chunk_size = min(64, (end - cacheline_offset))
        #     chunk_data = cacheline.to_bytes(64, "little")
        #     result += chunk_data[:chunk_size]
        end = image_addr + image_size
        with BytesIO() as imgbuf:
            for offset in range(image_addr, image_addr + image_size + 64, 64):
                data = await self._cxl_type2_device.read_mem_hpa(offset, 64)
                chunk_size = min(64, (end - offset))
                chunk_data = data.to_bytes(64, "little")
                chunk_data = chunk_data[:chunk_size]
                imgbuf.write(chunk_data)
            im = Image.open(imgbuf).convert("RGB")
        return im

    async def _validate_model(self, _):
        # pylint: disable=no-member
        # logger.debug(f"Getting test image for dev {self._device_id}")
        # im = await self._get_test_image()
        # logger.debug(f"Got test image for dev {self._device_id}")

        json_asenc = b"2" * 64
        json_asint = int.from_bytes(json_asenc, "little")
        RESULTS_HPA = 0x00008000  # Arbitrarily chosen
        rounded_bytes_size = 64

        await self._cxl_type2_device.write_mem_hpa(RESULTS_HPA, json_asint, rounded_bytes_size)

        await self._irq_manager.send_irq_request(Irq.ACCEL_VALIDATION_FINISHED)

    async def _run_app(self, _):
        # pylint: disable=unused-variable
        # pylint: disable=E1101

        # await self._get_metadata()

        # Done training
        logger.info(self._create_message("Done Model Training"))
        await self._irq_manager.send_irq_request(Irq.ACCEL_TRAINING_FINISHED)

    async def _app_shutdown(self):
        logger.info("Moving out of accelerator directory")
        os.chdir("..")

        # logger.info("Removing accelerator directory")
        # os.rmdir(self.accel_dirname)

    async def _run(self):
        self._setup_test_env()
        tasks = [
            create_task(self._sw_conn_client.run()),
            create_task(self._cxl_type2_device.run()),
            create_task(self._irq_manager.run()),
            create_task(self._stop_signal.wait()),
        ]
        self._wait_tasks = [
            create_task(self._sw_conn_client.wait_for_ready()),
            create_task(self._cxl_type2_device.wait_for_ready()),
            create_task(self._irq_manager.wait_for_ready()),
            create_task(self._irq_manager.start_connection()),
        ]
        await self._change_status_to_running()
        await gather(*tasks)

    async def _stop(self):
        for task in self._wait_tasks:
            task.cancel()
        self._stop_signal.set()
        tasks = [
            create_task(self._sw_conn_client.stop()),
            create_task(self._cxl_type2_device.stop()),
            create_task(self._irq_manager.stop()),
        ]
        await gather(*tasks)
        await self._app_shutdown()
