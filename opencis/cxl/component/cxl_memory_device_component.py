"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

from dataclasses import dataclass
from enum import IntEnum
import os
import time
from typing import TypedDict, List, Optional

from opencis.util.accessor import FileAccessor
from opencis.util.logger import logger
from opencis.util.number_const import KB
from opencis.util.unaligned_bit_structure import (
    UnalignedBitStructure,
    ByteField,
)
from opencis.cxl.features.event_manager import EventManager
from opencis.cxl.features.log_manager import LogManager
from opencis.cxl.features.mailbox import (
    CxlMailbox,
    MailboxCapabilities,
    MIN_PAYLOAD_SIZE,
    MAILBOX_TYPE,
    CxlMailboxCommandBase,
)
from opencis.cxl.cci.generic.events import (
    GetEventRecords,
    ClearEventRecords,
    GetEventInterruptPolicy,
    SetEventInterruptPolicy,
)
from opencis.cxl.cci.generic.logs import GetLog, GetSupportedLogs
from opencis.cxl.cci.memory_device.identify_memory_device import (
    IdentifyMemoryDevice,
)
from opencis.cxl.component.bi_decoder import (
    CxlBIDecoderCapabilityStructureOptions,
    CxlBIDecoderCapabilityRegisterOptions,
    CxlBIDecoderControlRegisterOptions,
    CxlBIDecoderStatusRegisterOptions,
    CxlBITimeoutScale,
)
from opencis.cxl.component.cxl_component import (
    CxlDeviceComponent,
    CXL_DEVICE_CAPABILITY_TYPE,
)
from opencis.cxl.component.common import CXL_COMPONENT_TYPE
from opencis.cxl.component.hdm_decoder import (
    DeviceHdmDecoderManager,
    HdmDecoderManagerBase,
    HdmDecoderCapabilities,
    HDM_DECODER_COUNT,
)
from opencis.cxl.config_space.doe.cdat import (
    CDAT_ENTRY,
    DeviceScopedMemoryAffinity,
    DeviceScropedLatencyBandwidthInformation,
    DeviceScopedEfiMemoryType,
    HMAT_SLLB_DATA_TYPE,
    HMAT_SLLB_FLAG,
)

SIZE_256MB = 256 * 1024 * 1024


class CharDriverAccessor:
    def __init__(self, filename: str, size: int):
        self.filename = filename
        self.size = size

    async def write(self, offset: int, data: int, size: int):
        # TODO: Check for OOB and use asyncio
        data_bytes = data.to_bytes(size, "little")
        fd = os.open(self.filename, os.O_WRONLY, 0o644)
        os.lseek(fd, offset, os.SEEK_SET)
        os.write(fd, data_bytes)
        os.close(fd)

    async def read(self, offset: int, size: int) -> int:
        # TODO: Check for OOB and use asyncio
        fd = os.open(self.filename, os.O_RDONLY)
        os.lseek(fd, offset, os.SEEK_SET)
        data = os.read(fd, size)
        os.close(fd)
        return int.from_bytes(data, "little")


class MemoryDeviceIdentity(UnalignedBitStructure):
    # TODO: Support str type for fw_revision
    fw_revision: int
    total_capacity: int
    volatile_only_capacity: int
    persistent_only_capacity: int
    partition_alignment: int
    information_event_log_size: int
    warning_event_log_size: int
    failure_event_log_size: int
    fatal_event_log_size: int
    lsa_size: int
    poison_list_maximum_media_error_records: int
    inject_poison_limit: int
    poison_handling_capabilities: int
    qos_telemetry_capabilities: int
    dynamic_capacity_event_log_size: int

    _fields = [
        ByteField("fw_revision", 0x00, 0x0F),
        ByteField("total_capacity", 0x10, 0x17),
        ByteField("volatile_only_capacity", 0x18, 0x1F),
        ByteField("persistent_only_capacity", 0x20, 0x27),
        ByteField("partition_alignment", 0x28, 0x2F),
        ByteField("information_event_log_size", 0x30, 0x31, default=1),
        ByteField("warning_event_log_size", 0x32, 0x33, default=1),
        ByteField("failure_event_log_size", 0x34, 0x35, default=1),
        ByteField("fatal_event_log_size", 0x36, 0x37, default=1),
        ByteField("lsa_size", 0x38, 0x3B),
        ByteField("poison_list_maximum_media_error_records", 0x3C, 0x3E),
        ByteField("inject_poison_limit", 0x3F, 0x40),
        ByteField("poison_handling_capabilities", 0x41, 0x41),
        ByteField("qos_telemetry_capabilities", 0x42, 0x42),
        ByteField("dynamic_capacity_event_log_size", 0x43, 0x44),
    ]

    def get_total_capacity(self) -> int:
        return self.total_capacity * SIZE_256MB

    def set_total_capacity(self, capacity: int):
        self.total_capacity = capacity // SIZE_256MB

    def set_volatile_only_capacity(self, capacity: int):
        self.volatile_only_capacity = capacity // SIZE_256MB


class MEDIA_STATUS(IntEnum):
    NOT_READY = 0b00
    READY = 0b01
    ERROR = 0b10
    DISABLED = 0b11


class RESET_REQUEST(IntEnum):
    NOT_NEEDED = 0b000
    COLD_RESET = 0b001
    WARM_RESET = 0b010
    HOT_RESET = 0b011
    CXL_RESET = 0b100


class MemoryDeviceStatus(TypedDict):
    device_fatal: int
    fw_halt: int
    media_status: MEDIA_STATUS
    mailbox_interfaces_ready: int
    reset_needed: RESET_REQUEST


@dataclass
class CXLCacheCacheLineInfo:
    cache_id: int
    last_access_time: float
    state: int = 0
    dirty: bool = False
    data: int = 0

    def write(self, data: int):
        self.data = data

    def read(self) -> int:
        return self.data


class CxlMemoryDeviceComponent(CxlDeviceComponent):
    def __init__(
        self,
        identity: MemoryDeviceIdentity,
        decoder_count: HDM_DECODER_COUNT = HDM_DECODER_COUNT.DECODER_1,
        memory_file: str = "mem.bin",
        label: Optional[str] = None,
        cache_lines: int = 0,
        cache_line_size: int = 64 * KB,
    ):
        super().__init__(label)
        self._event_manager = EventManager()
        self._log_manager = LogManager()
        self._identity = identity
        primary_mailbox_capabilities = MailboxCapabilities(
            payload_size=MIN_PAYLOAD_SIZE,
            mb_doorbell_interrupt_capable=0,
            background_command_complete_interrupt_capable=0,
            interrupt_message_number=0,
            mailbox_ready_time=0,
            type=MAILBOX_TYPE.MEMORY_DEVICE_COMMANDS,
        )
        primary_mailbox_commands: List[CxlMailboxCommandBase] = [
            GetEventRecords(self._event_manager),
            ClearEventRecords(self._event_manager),
            GetEventInterruptPolicy(self._event_manager),
            SetEventInterruptPolicy(self._event_manager),
            GetLog(self._log_manager),
            GetSupportedLogs(self._log_manager),
            IdentifyMemoryDevice(self._identity),
        ]
        self._primary_mailbox = CxlMailbox(
            capabilities=primary_mailbox_capabilities, commands=primary_mailbox_commands
        )
        self._log_manager.set_command_effects_log(primary_mailbox_commands)
        hdm_decoder_capabilities = HdmDecoderCapabilities(
            decoder_count=decoder_count,
            target_count=0,
            a11to8_interleave_capable=0,
            a14to12_interleave_capable=0,
            poison_on_decoder_error_capability=0,
            three_six_twelve_way_interleave_capable=0,
            sixteen_way_interleave_capable=0,
            uio_capable=0,
            uio_capable_decoder_count=0,
            mem_data_nxm_capable=0,
            bi_capable=True,
        )
        self._hdm_decoder_manager = DeviceHdmDecoderManager(hdm_decoder_capabilities, label=label)
        if "/dev" in memory_file:
            self._memory_accessor = CharDriverAccessor(
                memory_file, self._identity.get_total_capacity()
            )
        elif memory_file == "":
            self._memory_accessor = None
        else:
            self._memory_accessor = FileAccessor(
                memory_file, self._identity.get_total_capacity() // SIZE_256MB
            )

        self._cache_info: List[CXLCacheCacheLineInfo] = []
        self._cache_lines = cache_lines
        self._cache_line_size = cache_line_size
        for i in range(self._cache_lines):
            self._cache_info.append(
                CXLCacheCacheLineInfo(
                    cache_id=i,
                    last_access_time=time.time(),
                )
            )

    def get_primary_mailbox(self) -> Optional[CxlMailbox]:
        return self._primary_mailbox

    def get_hdm_decoder_manager(self) -> Optional[HdmDecoderManagerBase]:
        return self._hdm_decoder_manager

    def get_bi_decoder_options(self) -> Optional[CxlBIDecoderCapabilityStructureOptions]:
        # pylint: disable=duplicate-code
        options = CxlBIDecoderCapabilityStructureOptions()
        options["capability_options"] = CxlBIDecoderCapabilityRegisterOptions(hdm_d_compatible=0)
        options["control_options"] = CxlBIDecoderControlRegisterOptions(
            bi_enable=1,
            bi_decoder_commit=0,
        )
        options["status_options"] = CxlBIDecoderStatusRegisterOptions(
            bi_decoder_committed=0,
            bi_decoder_error_not_committed=0,
            bi_decoder_commit_timeout_base=CxlBITimeoutScale.hundred_ms,
            bi_decoder_commit_timeout_scale=1,
        )
        options["device_type"] = self.get_component_type()
        return options

    def get_cdat_entries(self) -> List[CDAT_ENTRY]:
        dsmas = DeviceScopedMemoryAffinity()
        dsmas.dpa_length = self._identity.get_total_capacity()

        dslbis0 = DeviceScropedLatencyBandwidthInformation()
        dslbis0.flags = HMAT_SLLB_FLAG.MEMORY
        dslbis0.data_type = HMAT_SLLB_DATA_TYPE.READ_LATENCY
        dslbis0.entry_base_unit = 10000
        dslbis0.entry0 = 15

        dslbis1 = DeviceScropedLatencyBandwidthInformation()
        dslbis1.flags = HMAT_SLLB_FLAG.MEMORY
        dslbis1.data_type = HMAT_SLLB_DATA_TYPE.WRITE_LATENCY
        dslbis1.entry_base_unit = 10000
        dslbis1.entry0 = 25

        dslbis2 = DeviceScropedLatencyBandwidthInformation()
        dslbis2.flags = HMAT_SLLB_FLAG.MEMORY
        dslbis2.data_type = HMAT_SLLB_DATA_TYPE.READ_BANDWIDTH
        dslbis2.entry_base_unit = 1000
        dslbis2.entry0 = 16

        dslbis3 = DeviceScropedLatencyBandwidthInformation()
        dslbis3.flags = HMAT_SLLB_FLAG.MEMORY
        dslbis3.data_type = HMAT_SLLB_DATA_TYPE.WRITE_BANDWIDTH
        dslbis3.entry_base_unit = 1000
        dslbis3.entry0 = 16

        dsemts = DeviceScopedEfiMemoryType()
        dsemts.dpa_length = self._identity.get_total_capacity()

        entries = [dsmas, dslbis0, dslbis1, dslbis2, dslbis3, dsemts]
        return entries

    def get_component_type(self) -> CXL_COMPONENT_TYPE:
        return CXL_COMPONENT_TYPE.D2

    def get_capability_type(self) -> CXL_DEVICE_CAPABILITY_TYPE:
        return CXL_DEVICE_CAPABILITY_TYPE.MEMORY_DEVICE

    def get_event_manager(self) -> EventManager:
        return self._event_manager

    def get_log_manager(self) -> LogManager:
        return self._log_manager

    def get_status(self) -> MemoryDeviceStatus:
        status = MemoryDeviceStatus(
            device_fatal=0,
            fw_halt=0,
            media_status=MEDIA_STATUS.READY,
            mailbox_interfaces_ready=1,
            reset_needed=RESET_REQUEST.NOT_NEEDED,
        )
        return status

    def get_identity(self) -> MemoryDeviceIdentity:
        return self._identity

    def get_dpa(self, hpa: int) -> int:
        dpa = self._hdm_decoder_manager.get_dpa(hpa)
        if dpa is None:
            logger.warning(self._create_message(f"[get_dpa] HPA {hex(hpa)} is not decodable"))
            return None
        return dpa

    def get_hpa(self, dpa: int) -> int:
        hpa = self._hdm_decoder_manager.get_hpa(dpa)
        if hpa is None:
            logger.warning(self._create_message(f"[get_hpa] DPA {hex(dpa)} is not decodable"))
            return None
        return hpa

    async def write_mem(self, hpa: int, data: int, size: int = 64):
        dpa = self._hdm_decoder_manager.get_dpa(hpa)
        if dpa is None:
            logger.warning(self._create_message(f"[write_mem] HPA {hex(hpa)} is not decodable"))
            return
        await self._memory_accessor.write(dpa, data, size)

    async def read_mem(self, hpa: int, size: int = 64) -> int:
        dpa = self._hdm_decoder_manager.get_dpa(hpa)
        if dpa is None:
            logger.warning(self._create_message(f"[read_mem] HPA {hex(hpa)} is not decodable"))
            return 0
        return await self._memory_accessor.read(dpa, size)

    async def read_mem_dpa(self, dpa: int, size: int = 64) -> int:
        return await self._memory_accessor.read(dpa, size)

    async def write_mem_dpa(self, dpa: int, data: int, size: int = 64):
        await self._memory_accessor.write(dpa, data, size)

    # TODO: check OOB write for cache (should <= self._cache_line_size)
    async def write_cache(self, cache_id: int, data: int):
        self._cache_info[cache_id].write(data)

    async def read_cache(self, cache_id: int) -> int:
        return self._cache_info[cache_id].read()
