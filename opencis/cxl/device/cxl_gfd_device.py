"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.

CXL Generic Fabric Device (GFD)
--------------------------------
A CXL 4.0 Port-Based Routing (PBR) device that attaches to a PBR switch DSP
port and exposes a 4 KB MMIO BAR-0 for CXL.io read/write operations.

Key properties
  - CXL.io only: MMIO reads and writes via BAR-0 (no CXL.mem HDM decoder).
  - CCI Identify returns IdentifyComponentType.GFD (0x04) so the FM can
    recognise it, assign a PID, and program the switch DRT accordingly.
  - Config-space advertises cache_capable=0, mem_capable=0 (IO-only GFD).
  - BAR-0 is a 4 KB register map with scratchpad, status, and control regs.

Lifecycle
  1. Device connects to switch via SwitchConnectionClient (TCP).
  2. Switch DSP enumerates BAR-0 size via config-space probing.
  3. FM issues pbr:identify → pbr:configurePid → pbr:setDrt to route traffic.
  4. Host issues CXL.io reads/writes to BAR-0 which the device processes.
"""

from asyncio import create_task, gather
from typing import Optional

from opencis.util.logger import logger
from opencis.util.component import RunnableComponent
from opencis.cxl.component.cxl_connection import CxlConnection
from opencis.cxl.component.cxl_io_manager import CxlIoManager
from opencis.cxl.component.cxl_mem_manager import CxlMemManager
from opencis.cxl.component.cxl_io_callback_data import CxlIoCallbackData
from opencis.cxl.cci.generic.information_and_status.identify import (
    IdentifyCommand,
    IdentifyComponentType,
    IdentifyResponsePayload,
)
from opencis.cxl.component.cci_executor import CciExecutor
from opencis.cxl.mmio.gfd_mmio_registers import GfdMmioRegisters, GFD_BAR_SIZE
from opencis.cxl.config_space.dvsec import (
    CXL_DEVICE_TYPE,
    DvsecConfigSpaceOptions,
    DvsecRegisterLocatorOptions,
)
from opencis.cxl.config_space.dvsec.cxl_devices import (
    DvsecCxlCapabilityOptions,
    DvsecCxlCacheableRangeOptions,
)
from opencis.cxl.config_space.doe.doe import CxlDoeExtendedCapabilityOptions
from opencis.cxl.config_space.device import (
    CxlType3SldConfigSpace,
    CxlType3SldConfigSpaceOptions,
)
from opencis.cxl.config_space.serial_number.common import DeviceSNCapabilityOptions
from opencis.cxl.component.cxl_memory_device_component import (
    CxlMemoryDeviceComponent,
    MemoryDeviceIdentity,
)
from opencis.cxl.component.hdm_decoder import HDM_DECODER_COUNT
from opencis.pci.component.config_space_manager import PCI_DEVICE_TYPE
from opencis.pci.component.pci import (
    PciComponent,
    PciComponentIdentity,
    PCI_CLASS,
    PCI_DEVICE_PORT_TYPE,
    EEUM_VID,
    SW_GFD_DID,
)
from opencis.pci.component.mmio_manager import BarEntry, BarInfo, MEMORY_TYPE


class CxlGfdDevice(RunnableComponent):
    """
    CXL Generic Fabric Device (GFD).

    Parameters
    ----------
    transport_connection:
        ``CxlConnection`` provided by ``SwitchConnectionClient`` (or passed
        directly in test mode).
    port_index:
        PBR switch DSP port number this device is attached to.
    serial_number:
        16-hex-digit string, e.g. ``"0000000000000001"``.
    label:
        Optional log label.
    """

    def __init__(
        self,
        transport_connection: CxlConnection,
        port_index: int = 0,
        serial_number: str = "0000000000000001",
        label: Optional[str] = None,
    ):
        label = label or f"GFD:Port{port_index}"
        super().__init__(label)

        self._port_index = port_index
        self._serial_number = serial_number
        self._upstream_connection = transport_connection

        # ── Create registers and CCI executor BEFORE CxlIoManager ────────────
        # CxlIoManager calls _init_device synchronously in __init__, so anything
        # _init_device references must exist first.
        self._gfd_registers = GfdMmioRegisters()
        self._cci_executor = CciExecutor(label=label)

        # ── CxlIoManager wires MMIO and config-space FIFOs ───────────────────
        self._cxl_io_manager = CxlIoManager(
            mmio_upstream_fifo=transport_connection.mmio_fifo,
            mmio_downstream_fifo=None,
            cfg_upstream_fifo=transport_connection.cfg_fifo,
            cfg_downstream_fifo=None,
            device_type=PCI_DEVICE_TYPE.ENDPOINT,
            init_callback=self._init_device,
            label=label,
        )

        # ── CxlMemManager — idle stub (GFD has no CXL.mem HDM decoder) ───────
        self._cxl_mem_manager = CxlMemManager(
            upstream_fifo=transport_connection.cxl_mem_fifo,
            label=label,
        )

    # ── Init callback called by CxlIoManager during construction ──────────────

    def _init_device(self, cxl_io_callback_data: CxlIoCallbackData):
        """Configure the config-space and BAR-0 MMIO register block."""

        # ─ PCI identity ───────────────────────────────────────────────────────
        pci_identity = PciComponentIdentity(
            vendor_id=EEUM_VID,
            device_id=SW_GFD_DID,
            base_class_code=PCI_CLASS.MEMORY_CONTROLLER,
            sub_class_coce=0x00,   # no specific sub-class for GFD
            programming_interface=0x00,
            device_port_type=PCI_DEVICE_PORT_TYPE.PCI_EXPRESS_ENDPOINT,
        )
        pci_component = PciComponent(pci_identity, cxl_io_callback_data.mmio_manager)

        # ─ BAR-0: 4 KB GFD MMIO register block ───────────────────────────────
        cxl_io_callback_data.mmio_manager.set_bar_entries([
            BarEntry(
                register=self._gfd_registers,
                info=BarInfo(
                    prefetchable=False,
                    memory_type=MEMORY_TYPE.ADDRESS_64BIT,
                ),
            )
        ])

        # ─ Minimal CxlMemoryDeviceComponent stub ────────────────────────────
        # DvsecConfigSpace for CXL_DEVICE_TYPE.LD requires a non-None
        # memory_device_component even though GFD has mem_capable=0.
        # We create a zero-capacity stub with no backing file.
        _gfd_identity = MemoryDeviceIdentity()
        _gfd_identity.fw_revision = MemoryDeviceIdentity.ascii_str_to_int("GFD EMU 1.0", 16)
        _gfd_identity.set_total_capacity(0)
        _gfd_identity.set_volatile_only_capacity(0)
        _stub_mem_component = CxlMemoryDeviceComponent(
            _gfd_identity,
            decoder_count=HDM_DECODER_COUNT.DECODER_1,
            memory_file="",   # empty string → no file backing
            label=self._label,
        )

        # ─ CXL config-space (IO-only: mem_capable=0, cache_capable=0) ────────
        config_options = CxlType3SldConfigSpaceOptions(
            pci_component=pci_component,
            dvsec=DvsecConfigSpaceOptions(
                register_locator=DvsecRegisterLocatorOptions(registers=[]),
                device_type=CXL_DEVICE_TYPE.LD,
                memory_device_component=_stub_mem_component,
                capability_options=DvsecCxlCapabilityOptions(
                    cache_capable=0,
                    mem_capable=0,
                    hdm_count=0,
                    cache_writeback_and_invalidate_capable=0,
                    cache_size_unit=0,
                    cache_size=0,
                ),
                cacheable_address_range=DvsecCxlCacheableRangeOptions(0x0, 0x0),
            ),
            doe=CxlDoeExtendedCapabilityOptions(cdat_entries=[]),
            serial_number=DeviceSNCapabilityOptions(sn=self._serial_number),
        )
        config_space = CxlType3SldConfigSpace(
            options=config_options, parent_name="cfgspace"
        )
        cxl_io_callback_data.config_space_manager.set_register(config_space)

        # ─ CCI Identify — registers this device as GFD with the FM ────────────
        serial_int = int(self._serial_number, 16) if self._serial_number else 1
        identity = IdentifyResponsePayload(
            vendor_id=EEUM_VID,
            device_id=SW_GFD_DID,
            sub_system_vendor_id=EEUM_VID,
            sub_system_id=0,
            serial_number=serial_int,
            max_supported_msg_size=10,
            component_type=IdentifyComponentType.GFD,
        )
        self._cci_executor.register_command(
            IdentifyCommand.OPCODE,
            IdentifyCommand(identity, label=self._label),
        )

    # ── Public helpers ─────────────────────────────────────────────────────────

    def get_bar_size(self) -> int:
        """Return the size of BAR-0 in bytes."""
        return GFD_BAR_SIZE

    def get_registers(self) -> GfdMmioRegisters:
        """Direct access to the register block (useful in tests or FM callbacks)."""
        return self._gfd_registers

    # ── RunnableComponent lifecycle ────────────────────────────────────────────

    async def _run(self):
        logger.info(self._create_message("Starting"))
        run_tasks = [
            create_task(self._cxl_io_manager.run()),
            create_task(self._cxl_mem_manager.run()),
            create_task(self._cci_executor.run()),
        ]
        wait_tasks = [
            create_task(self._cxl_io_manager.wait_for_ready()),
            create_task(self._cxl_mem_manager.wait_for_ready()),
            create_task(self._cci_executor.wait_for_ready()),
        ]
        await gather(*wait_tasks)
        await self._change_status_to_running()
        logger.info(self._create_message("Ready — BAR-0 @ {} bytes".format(GFD_BAR_SIZE)))
        await gather(*run_tasks)
        logger.info(self._create_message("Stopped"))

    async def _stop(self):
        logger.info(self._create_message("Stopping"))
        tasks = [
            create_task(self._cxl_io_manager.stop()),
            create_task(self._cxl_mem_manager.stop()),
            create_task(self._cci_executor.stop()),
        ]
        await gather(*tasks)
