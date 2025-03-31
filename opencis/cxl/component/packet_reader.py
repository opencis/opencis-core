"""
Copyright (c) 2024, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from asyncio import CancelledError, StreamReader, create_task
from enum import Enum, auto
import traceback
from typing import Optional, Tuple

from opencis.cxl.cci.common import CCI_FM_API_COMMAND_OPCODE
from opencis.cxl.transport.transaction import (
    BasePacket,
    BaseSidebandPacket,
    CxlCacheBasePacket,
    CxlCacheD2HDataPacket,
    CxlCacheD2HReqPacket,
    CxlCacheD2HRspPacket,
    CxlCacheH2DDataPacket,
    CxlCacheH2DReqPacket,
    CxlCacheH2DRspPacket,
    SidebandConnectionRequestPacket,
    CxlIoBasePacket,
    CxlIoCfgRdPacket,
    CxlIoCfgWrPacket,
    CxlIoMemRdPacket,
    CxlIoMemWrPacket,
    CxlIoCompletionPacket,
    CxlIoCompletionWithDataPacket,
    CxlMemBasePacket,
    CxlMemM2SReqPacket,
    CxlMemM2SRwDPacket,
    CxlMemM2SBIRspPacket,
    CxlMemS2MBISnpPacket,
    CxlMemS2MNDRPacket,
    CxlMemS2MDRSPacket,
    CciBasePacket,
    CciRequestPacket,
    CciResponsePacket,
    GetLdInfoRequestPacket,
    GetLdInfoResponsePacket,
    GetLdAllocationsRequestPacket,
    GetLdAllocationsResponsePacket,
    SetLdAllocationsRequestPacket,
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
        header_load = await self._read_payload(BasePacket.get_size())
        base_packet = BasePacket()
        base_packet.reset(header_load)
        remaining_length = base_packet.system_header.payload_length - len(base_packet)
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
        cxl_io_base_packet = CxlIoBasePacket()
        header_size = (
            len(cxl_io_base_packet.tlp_prefix)
            + len(cxl_io_base_packet.cxl_io_header)
            + BasePacket.get_size()
        )
        cxl_io_base_packet.reset(payload[:header_size])
        if cxl_io_base_packet.is_cfg_read():
            cxl_io_packet = CxlIoCfgRdPacket()
        elif cxl_io_base_packet.is_cfg_write():
            cxl_io_packet = CxlIoCfgWrPacket()
        elif cxl_io_base_packet.is_mem_read():
            cxl_io_packet = CxlIoMemRdPacket()
        elif cxl_io_base_packet.is_mem_write():
            cxl_io_packet = CxlIoMemWrPacket()
        elif cxl_io_base_packet.is_cpl():
            cxl_io_packet = CxlIoCompletionPacket()
        elif cxl_io_base_packet.is_cpld():
            cxl_io_packet = CxlIoCompletionWithDataPacket()

        if cxl_io_packet is None:
            protocol = cxl_io_base_packet.cxl_io_header.fmt_type
            raise Exception(f"Unsupported CXL.IO protocol {protocol}")
        cxl_io_packet.reset(payload)
        return cxl_io_packet

    def _get_cxl_mem_packet(self, payload: bytes) -> CxlMemBasePacket:
        cxl_mem_base_packet = CxlMemBasePacket()
        header_size = len(cxl_mem_base_packet.cxl_mem_header) + BasePacket.get_size()
        cxl_mem_base_packet.reset(payload[:header_size])
        if cxl_mem_base_packet.is_m2sreq():
            cxl_mem_packet = CxlMemM2SReqPacket()
        elif cxl_mem_base_packet.is_m2srwd():
            cxl_mem_packet = CxlMemM2SRwDPacket()
        elif cxl_mem_base_packet.is_m2sbirsp():
            cxl_mem_packet = CxlMemM2SBIRspPacket()
        elif cxl_mem_base_packet.is_s2mbisnp():
            cxl_mem_packet = CxlMemS2MBISnpPacket()
        elif cxl_mem_base_packet.is_s2mndr():
            cxl_mem_packet = CxlMemS2MNDRPacket()
        elif cxl_mem_base_packet.is_s2mdrs():
            cxl_mem_packet = CxlMemS2MDRSPacket()
        else:
            msg_class = cxl_mem_base_packet.cxl_mem_header.msg_class
            raise Exception(f"Unsupported CXL.MEM message class: {msg_class}")

        cxl_mem_packet.reset(payload)
        return cxl_mem_packet

    def _get_cxl_cache_packet(self, payload: bytes) -> CxlCacheBasePacket:
        cxl_cache_base_packet = CxlCacheBasePacket()
        header_size = len(cxl_cache_base_packet.cxl_cache_header) + BasePacket.get_size()
        cxl_cache_base_packet.reset(payload[:header_size])
        if cxl_cache_base_packet.is_d2hreq():
            cxl_cache_packet = CxlCacheD2HReqPacket()
        elif cxl_cache_base_packet.is_d2hrsp():
            cxl_cache_packet = CxlCacheD2HRspPacket()
        elif cxl_cache_base_packet.is_d2hdata():
            cxl_cache_packet = CxlCacheD2HDataPacket()
        elif cxl_cache_base_packet.is_h2dreq():
            cxl_cache_packet = CxlCacheH2DReqPacket()
        elif cxl_cache_base_packet.is_h2drsp():
            cxl_cache_packet = CxlCacheH2DRspPacket()
        elif cxl_cache_base_packet.is_h2ddata():
            cxl_cache_packet = CxlCacheH2DDataPacket()
        else:
            msg_class = cxl_cache_base_packet.cxl_cache_header.msg_class
            raise Exception(f"Unsupported CXL.CACHE message class: {msg_class}")

        cxl_cache_packet.reset(payload)
        return cxl_cache_packet

    def _get_cci_packet(self, payload: bytes) -> CciBasePacket:
        cci_base_packet = CciBasePacket()
        header_size = len(cci_base_packet.cci_header) + BasePacket.get_size()
        cci_base_packet.reset(payload[:header_size])

        if cci_base_packet.is_req():
            cci_packet = CciRequestPacket()
            cci_packet.reset(payload)
            if cci_packet.get_command_opcode() == CCI_FM_API_COMMAND_OPCODE.GET_LD_INFO:
                cci_packet = GetLdInfoRequestPacket()
                cci_packet.reset(payload)
            elif cci_packet.get_command_opcode() == CCI_FM_API_COMMAND_OPCODE.GET_LD_ALLOCATIONS:
                cci_packet = GetLdAllocationsRequestPacket()
                logger.debug(f"GetLdAllocationsRequestPacket created: {cci_packet}")
                cci_packet.reset(payload)
            elif cci_packet.get_command_opcode() == CCI_FM_API_COMMAND_OPCODE.SET_LD_ALLOCATIONS:
                cci_packet = SetLdAllocationsRequestPacket()
                cci_packet.reset(payload)
            else:
                raise Exception("Unsupported CCI packet")
        elif cci_base_packet.is_rsp():
            cci_packet = CciResponsePacket()
            cci_packet.reset(payload)
            if cci_packet.get_command_opcode() == CCI_FM_API_COMMAND_OPCODE.GET_LD_INFO:
                cci_packet = GetLdInfoResponsePacket()
                cci_packet.reset(payload)
            elif cci_packet.get_command_opcode() == CCI_FM_API_COMMAND_OPCODE.GET_LD_ALLOCATIONS:
                cci_packet = GetLdAllocationsResponsePacket()
                cci_packet.reset(payload)
            elif cci_packet.get_command_opcode() == CCI_FM_API_COMMAND_OPCODE.SET_LD_ALLOCATIONS:
                cci_packet = SetLdAllocationsResponsePacket()
                cci_packet.reset(payload)
            else:
                raise Exception("Unsupported CCI packet")
        else:
            raise Exception("Unsupported CCI packet")

        return cci_packet

    def _get_sideband_packet(self, payload: bytes) -> BaseSidebandPacket:
        base_sideband_packet = BaseSidebandPacket()
        header_size = len(base_sideband_packet.sideband_header) + BasePacket.get_size()
        base_sideband_packet.reset(payload[:header_size])
        if base_sideband_packet.is_connection_request():
            sideband_packet = SidebandConnectionRequestPacket()
            sideband_packet.reset(payload)
        elif (
            base_sideband_packet.is_connection_accept()
            or base_sideband_packet.is_connection_reject()
        ):
            sideband_packet = base_sideband_packet
        return sideband_packet

    async def _get_sideband_connection_request_packet(self, packets: bytes):
        remaining_packets_size = SidebandConnectionRequestPacket.get_size() - len(packets)
        remaining_packets = await self._reader.read(remaining_packets_size)
        if not remaining_packets:
            raise Exception("Connection disconnected")

        packets = packets + remaining_packets
        sideband = SidebandConnectionRequestPacket()
        sideband.reset(packets)

        return sideband
