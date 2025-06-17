"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from asyncio import StreamReader, create_task
from typing import Optional

from opencis.cxl.transport.cci_packets import CciMessagePacket, CciPayloadPacket
from opencis.util.logger import logger
from opencis.util.component import LabeledComponent
from opencis.cxl.transport.packet_structs import SystemHeader
from opencis.cxl.transport.common import BasePacket

# pylint: disable=duplicate-code


class MctpPacketReader(LabeledComponent):
    def __init__(
        self,
        reader: StreamReader,
        label: Optional[str] = None,
        parent_name: Optional[str] = None,
    ):
        label_prefix = parent_name + ":" if parent_name else ""
        super().__init__(lambda class_name: f"{label_prefix}{class_name}")
        self._reader = reader
        self._aborted = False
        self._task = None

    async def get_packet(self) -> CciMessagePacket:
        if self._aborted:
            raise Exception("PacketReader is already aborted")
        try:
            self._task = create_task(self._get_packet_in_task())
            packet = await self._task
        except Exception as e:
            logger.debug(self._create_message("Aborted"))
            raise Exception("PacketReader is aborted") from e
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

    async def _get_packet_in_task(self):
        base_packet, payload = await self._get_payload()
        payload = bytearray(payload)
        if base_packet.is_cci() is not True:
            raise ValueError(f"Must be CCI packet {type(base_packet)}")

        # Wrap the payload with CciPayloadPacket
        packet = CciPayloadPacket(payload)
        return packet

    async def _get_payload(self):
        logger.debug(self._create_message("Waiting Packet"))
        header_bytes = await self._read_payload(SystemHeader.get_size())
        base_packet = BasePacket(bytearray(header_bytes))
        remaining_length = base_packet.system_header.payload_length - len(base_packet)
        if remaining_length < 0:
            raise Exception("remaining length is less than 0")
        payload = header_bytes + await self._read_payload(remaining_length)
        logger.debug(self._create_message("Received Packet"))
        return base_packet, payload

    async def _get_cci_message_header(self) -> CciMessagePacket:
        logger.debug(self._create_message("Waiting for CCI Message Header"))
        payload = await self._read_payload(CciMessagePacket.get_size())
        message_header = CciMessagePacket(payload)
        logger.debug(self._create_message("Received CCI Message Header"))
        return message_header

    async def _read_payload(self, size: int) -> bytes:
        payload = await self._reader.read(size)
        if not payload:
            raise Exception("Connection disconnected")
        return payload
