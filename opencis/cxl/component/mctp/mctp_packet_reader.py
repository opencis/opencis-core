"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

from asyncio import StreamReader, create_task
from typing import Optional

from opencis.cxl.transport.transaction import (
    CciMessageHeaderPacket,
    CciMessagePacket,
    CciHeaderPacket,
    CciPayloadPacket,
)
from opencis.util.logger import logger
from opencis.util.component import LabeledComponent
from opencis.cxl.transport.common import BasePacket

# pylint: disable=duplicate-code


class MctpPacketReader(LabeledComponent):
    def __init__(self, reader: StreamReader, label: Optional[str] = None):
        super().__init__(label)
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
        logger.debug(self._create_message("Waiting Packet"))
        header_load = await self._read_payload(BasePacket.get_size())
        base_packet = BasePacket()
        base_packet.reset(header_load)
        remaining_length = base_packet.system_header.payload_length - len(base_packet)
        if remaining_length < 0:
            raise Exception("remaining length is less than 0")
        payload = bytes(base_packet) + await self._read_payload(remaining_length)
        logger.debug(self._create_message("Received Packet"))

        # Wrap the payload with CciPayloadPacket
        packet = CciPayloadPacket()
        packet.reset(payload)
        return packet

    async def _get_cci_message_header(self) -> CciMessageHeaderPacket:
        logger.debug(self._create_message("Waiting for CCI Message Header"))
        payload = await self._read_payload(CciHeaderPacket.get_size())
        message_header = CciHeaderPacket()
        message_header.reset(payload)
        logger.debug(self._create_message("Received CCI Message Header"))
        return message_header

    async def _read_payload(self, size: int) -> bytes:
        payload = await self._reader.read(size)
        if not payload:
            raise Exception("Connection disconnected")
        return payload
