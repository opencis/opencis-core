"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from asyncio import CancelledError, StreamReader, create_task
from enum import Enum, auto
import traceback
from typing import Optional, Tuple

from opencis.cxl.cci.common import CCI_FM_API_COMMAND_OPCODE
from opencis.cxl.transport.packet_structs import SystemHeader
from opencis.cxl.transport.common import BasePacket
from opencis.cxl.transport.sideband_packets import (
    BaseSidebandPacket,
    SidebandConnectionRequestPacket,
)
from opencis.cxl.transport.cxl_io_packets import (
    CxlIoBasePacket,
    CxlIoCfgRdPacket,
    CxlIoCfgWrPacket,
    CxlIoMemRdPacket,
    CxlIoMemWrPacket,
    CxlIoCompletionPacket,
    CxlIoCompletionWithDataPacket,
)
from opencis.cxl.transport.cxl_cache_packets import (
    CxlCacheBasePacket,
    CxlCacheCacheD2HDataPacket,
    CxlCacheCacheD2HReqPacket,
    CxlCacheCacheD2HRspPacket,
    CxlCacheCacheH2DDataPacket,
    CxlCacheCacheH2DReqPacket,
    CxlCacheCacheH2DRspPacket,
)
from opencis.cxl.transport.cxl_mem_packets import (
    CxlMemBasePacket,
    CxlMemM2SReqPacket,
    CxlMemM2SRwDPacket,
    CxlMemM2SBIRspPacket,
    CxlMemS2MBISnpPacket,
    CxlMemS2MNDRPacket,
    CxlMemS2MDRSPacket,
)
from opencis.cxl.transport.cci_packets import (
    CciBasePacket,
    CciRequestPacket,
    CciResponsePacket,
    GetLdInfoRequestPacket,
    GetLdAllocationsRequestPacket,
    SetLdAllocationsRequestPacket,
    GetLdInfoResponsePacket,
    GetLdAllocationsResponsePacket,
    SetLdAllocationsResponsePacket,
)
from opencis.util.logger import logger
from opencis.util.component import LabeledComponent


class PACKET_READ_STATUS(Enum):
    OK = auto()
    DISCONNECTED = auto()
    TIMED_OUT = auto()


class PacketReader(LabeledComponent):
    def __init__(
        self, reader: StreamReader, label: Optional[str] = None, parent_name: Optional[str] = None
    ):
        label_prefix = f"{parent_name}:" if parent_name else ""
        label_suffix = f":{label}" if label else ""
        super().__init__(lambda class_name: f"{label_prefix}{class_name}{label_suffix}")
        self._reader = reader
        self._aborted = False
        self._task = None

    async def get_packet(self) -> BasePacket:
        if self._aborted:
            raise Exception("PacketReader is already aborted")
        try:
            self._task = create_task(self._get_packet_in_task())
            packet = await self._task
        except Exception as e:
            if str(e) == "Connection disconnected":
                # can happen during teardown
                logger.info(self._create_message(str(e)))
            else:
                logger.error(
                    self._create_message(f"get_packet() error: {str(e)}, {traceback.format_exc()}")
                )
                raise Exception("PacketReader is aborted") from e
        except CancelledError as exc:
            logger.debug(self._create_message("Connection cancelled"))
            raise Exception("PacketReader is cancelled") from exc
        finally:
            self._task = None
        return packet

    def abort(self):
        if self._aborted:
            return
        logger.debug(self._create_message("Aborting"))
        self._aborted = True
        if self._task is not None:
            self._task.cancel()

    async def _get_packet_in_task(self) -> BasePacket:
        base_packet, payload = await self._get_payload()
        if base_packet.is_cxl_io():
            logger.debug(self._create_message("Received Packet is CXL.io"))
            return self._get_cxl_io_packet(payload)
        if base_packet.is_cxl_mem():
            logger.debug(self._create_message("Received Packet is CXL.mem"))
            return self._get_cxl_mem_packet(payload)
        if base_packet.is_cxl_cache():
            logger.debug(self._create_message("Received Packet is CXL.cache"))
            return self._get_cxl_cache_packet(payload)
        if base_packet.is_sideband():
            logger.debug(self._create_message("Received Packet is sideband"))
            return self._get_sideband_packet(payload)
        if base_packet.is_cci():
            return self._get_cci_packet(payload)
        raise Exception("Unsupported packet")

    async def _get_payload(self) -> Tuple[BasePacket, bytes]:
        logger.debug(self._create_message("Waiting Packet"))
        header_bytes = await self._read_payload(SystemHeader.get_size())
        # logger.info(f"header_bytes: {header_bytes}")
        base_packet = BasePacket(bytearray(header_bytes))
        remaining_length = base_packet.system_header.payload_length - len(base_packet)
        # logger.info(f"remaining_length: {remaining_length}")
        if remaining_length < 0:
            raise Exception("remaining length is less than 0")
        payload = bytes(base_packet) + await self._read_payload(remaining_length)
        logger.debug(self._create_message("Received Packet"))
        return base_packet, payload

    async def _read_payload(self, size: int) -> bytes:
        payload = await self._reader.read(size)
        if not payload:
            raise Exception("Connection disconnected")
        return payload

    def _get_cxl_io_packet(self, payload: bytes) -> CxlIoBasePacket:
        payload = bytearray(payload)
        cxl_io_base_packet = CxlIoBasePacket(payload)
        if cxl_io_base_packet.is_cfg_read():
            cxl_io_packet = CxlIoCfgRdPacket(payload)
        elif cxl_io_base_packet.is_cfg_write():
            cxl_io_packet = CxlIoCfgWrPacket(payload)
        elif cxl_io_base_packet.is_mem_read():
            cxl_io_packet = CxlIoMemRdPacket(payload)
        elif cxl_io_base_packet.is_mem_write():
            cxl_io_packet = CxlIoMemWrPacket(payload)
        elif cxl_io_base_packet.is_cpl():
            cxl_io_packet = CxlIoCompletionPacket(payload)
        elif cxl_io_base_packet.is_cpld():
            cxl_io_packet = CxlIoCompletionWithDataPacket(payload)

        if cxl_io_packet is None:
            protocol = cxl_io_base_packet.cxl_io_header.fmt_type
            raise Exception(f"Unsupported CXL.IO protocol {protocol}")
        return cxl_io_packet

    def _get_cxl_mem_packet(self, payload: bytes) -> CxlMemBasePacket:
        payload = bytearray(payload)
        cxl_mem_base_packet = CxlMemBasePacket(payload)
        if cxl_mem_base_packet.is_m2sreq():
            cxl_mem_packet = CxlMemM2SReqPacket(payload)
        elif cxl_mem_base_packet.is_m2srwd():
            cxl_mem_packet = CxlMemM2SRwDPacket(payload)
        elif cxl_mem_base_packet.is_m2sbirsp():
            cxl_mem_packet = CxlMemM2SBIRspPacket(payload)
        elif cxl_mem_base_packet.is_s2mbisnp():
            cxl_mem_packet = CxlMemS2MBISnpPacket(payload)
        elif cxl_mem_base_packet.is_s2mndr():
            cxl_mem_packet = CxlMemS2MNDRPacket(payload)
        elif cxl_mem_base_packet.is_s2mdrs():
            cxl_mem_packet = CxlMemS2MDRSPacket(payload)
        else:
            msg_class = cxl_mem_base_packet.cxl_mem_header.msg_class
            raise Exception(f"Unsupported CXL.MEM message class: {msg_class}")

        return cxl_mem_packet

    def _get_cxl_cache_packet(self, payload: bytes) -> CxlCacheBasePacket:
        payload = bytearray(payload)
        cxl_cache_base_packet = CxlCacheBasePacket(payload)
        if cxl_cache_base_packet.is_d2hreq():
            cxl_cache_packet = CxlCacheCacheD2HReqPacket(payload)
        elif cxl_cache_base_packet.is_d2hrsp():
            cxl_cache_packet = CxlCacheCacheD2HRspPacket(payload)
        elif cxl_cache_base_packet.is_d2hdata():
            cxl_cache_packet = CxlCacheCacheD2HDataPacket(payload)
        elif cxl_cache_base_packet.is_h2dreq():
            cxl_cache_packet = CxlCacheCacheH2DReqPacket(payload)
        elif cxl_cache_base_packet.is_h2drsp():
            cxl_cache_packet = CxlCacheCacheH2DRspPacket(payload)
        elif cxl_cache_base_packet.is_h2ddata():
            cxl_cache_packet = CxlCacheCacheH2DDataPacket(payload)
        else:
            msg_class = cxl_cache_base_packet.cxl_cache_header.msg_class
            raise Exception(f"Unsupported CXL.CACHE message class: {msg_class}")

        return cxl_cache_packet

    def _get_cci_packet(self, payload: bytes) -> CciBasePacket:
        payload = bytearray(payload)
        cci_base_packet = CciBasePacket(payload)

        if cci_base_packet.is_req():
            cci_packet = CciRequestPacket(payload)
            if cci_packet.get_command_opcode() == CCI_FM_API_COMMAND_OPCODE.GET_LD_INFO:
                cci_packet = GetLdInfoRequestPacket(payload)
            elif cci_packet.get_command_opcode() == CCI_FM_API_COMMAND_OPCODE.GET_LD_ALLOCATIONS:
                cci_packet = GetLdAllocationsRequestPacket(payload)
            elif cci_packet.get_command_opcode() == CCI_FM_API_COMMAND_OPCODE.SET_LD_ALLOCATIONS:
                cci_packet = SetLdAllocationsRequestPacket(payload)
            else:
                raise Exception("Unsupported CCI packet")
        elif cci_base_packet.is_rsp():
            cci_packet = CciResponsePacket(payload)
            if cci_packet.get_command_opcode() == CCI_FM_API_COMMAND_OPCODE.GET_LD_INFO:
                cci_packet = GetLdInfoResponsePacket(payload)
            elif cci_packet.get_command_opcode() == CCI_FM_API_COMMAND_OPCODE.GET_LD_ALLOCATIONS:
                cci_packet = GetLdAllocationsResponsePacket(payload)
            elif cci_packet.get_command_opcode() == CCI_FM_API_COMMAND_OPCODE.SET_LD_ALLOCATIONS:
                cci_packet = SetLdAllocationsResponsePacket(payload)
            else:
                raise Exception("Unsupported CCI packet")
        else:
            raise Exception("Unsupported CCI packet")

        return cci_packet

    def _get_sideband_packet(self, payload: bytes) -> BaseSidebandPacket:
        payload = bytearray(payload)
        base_sideband_packet = BaseSidebandPacket(payload)
        if base_sideband_packet.is_connection_request():
            sideband_packet = SidebandConnectionRequestPacket(payload)
        elif (
            base_sideband_packet.is_connection_accept()
            or base_sideband_packet.is_connection_reject()
        ):
            sideband_packet = base_sideband_packet
        return sideband_packet
