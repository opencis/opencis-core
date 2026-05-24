"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.

Fabric Crawl Out — Opcode 5701h
Section 7.7.13.2, CXL Specification Rev 4.0 Version 1.0

Allows the FM to tunnel a CCI command to any PBR component (e.g. GFD)
reachable through a PBR switch DSP port.  The switch forwards the embedded
CCI request over the cci_fifo to the downstream device and returns the
device's CCI response embedded inside the Fabric Crawl Out response.

This is the spec-correct mechanism for:
  - FM-to-GFD CCI (e.g. Identify 0001h, Claim FM Ownership 0701h,
    Read CDAT 0702h, Get Supported Logs 0400h, ...)
  - GAE Proxy GFD Mgmt Command (5809h) forwarding path

Input Payload (Table 7-116):
  Byte 0x00  len=1   Target Port Number (DSP port index)
  Byte 0x01  len=1   Reserved
  Byte 0x02  len=2   Embedded Command Size (bytes)
  Byte 0x04  varies  Embedded CCI Command (opcode + payload, Table 7-117)

Embedded CCI Command (Table 7-117):
  Byte 0x00  len=2   Command Opcode
  Byte 0x02  len=2   Payload Length
  Byte 0x04  varies  Command Payload

Output Payload (Table 7-118):
  Byte 0x00  len=2   Embedded Response Size (bytes)
  Byte 0x02  len=2   Reserved
  Byte 0x04  varies  Embedded CCI Response (return code + payload, Table 7-119)

Embedded CCI Response (Table 7-119):
  Byte 0x00  len=2   Return Code
  Byte 0x02  len=2   Reserved
  Byte 0x04  varies  Response Payload

Return codes: Success, Invalid Input, Internal Error, Retry Required
"""

from dataclasses import dataclass
from struct import pack, unpack_from
from typing import Optional

from opencis.cxl.cci.common import CCI_FM_API_COMMAND_OPCODE, CCI_RETURN_CODE
from opencis.cxl.component.cci_executor import CciRequest, CciResponse, CciForegroundCommand
from opencis.cxl.component.dsp_cci_tunnel import DspCciTunnel
from opencis.util.logger import logger


# ---------------------------------------------------------------------------
# Wire-format structures
# ---------------------------------------------------------------------------


@dataclass
class EmbeddedCciCommand:
    """Table 7-117 — the CCI command nested inside Fabric Crawl Out."""
    opcode: int = 0
    payload: bytes = b""

    HEADER_SIZE = 4

    def dump(self) -> bytes:
        hdr = bytearray(self.HEADER_SIZE)
        hdr[0:2] = pack("<H", self.opcode)
        hdr[2:4] = pack("<H", len(self.payload))
        return bytes(hdr) + self.payload

    @classmethod
    def parse(cls, data: bytes, offset: int = 0) -> "EmbeddedCciCommand":
        if len(data) - offset < cls.HEADER_SIZE:
            raise ValueError("EmbeddedCciCommand: not enough bytes")
        opcode = unpack_from("<H", data, offset)[0]
        payload_len = unpack_from("<H", data, offset + 2)[0]
        payload = bytes(data[offset + 4: offset + 4 + payload_len])
        return cls(opcode=opcode, payload=payload)

    def to_cci_request(self) -> CciRequest:
        return CciRequest(opcode=self.opcode, payload=self.payload)


@dataclass
class FabricCrawlOutRequestPayload:
    """Table 7-116 — Fabric Crawl Out input payload."""
    target_port: int = 0
    embedded_cmd: EmbeddedCciCommand = None  # type: ignore

    HEADER_SIZE = 4

    def __post_init__(self):
        if self.embedded_cmd is None:
            self.embedded_cmd = EmbeddedCciCommand()

    def dump(self) -> bytes:
        cmd_bytes = self.embedded_cmd.dump()
        hdr = bytearray(self.HEADER_SIZE)
        hdr[0] = self.target_port & 0xFF
        hdr[2:4] = pack("<H", len(cmd_bytes))
        return bytes(hdr) + cmd_bytes

    @classmethod
    def parse(cls, data: bytes) -> "FabricCrawlOutRequestPayload":
        if len(data) < cls.HEADER_SIZE:
            raise ValueError("FabricCrawlOutRequestPayload: need at least 4 bytes")
        target_port = data[0]
        embedded_size = unpack_from("<H", data, 2)[0]
        if len(data) < cls.HEADER_SIZE + embedded_size:
            raise ValueError("FabricCrawlOutRequestPayload: embedded command truncated")
        embedded_cmd = EmbeddedCciCommand.parse(data, cls.HEADER_SIZE)
        return cls(target_port=target_port, embedded_cmd=embedded_cmd)


@dataclass
class EmbeddedCciResponse:
    """Table 7-119 — the CCI response nested inside Fabric Crawl Out response."""
    return_code: int = 0
    payload: bytes = b""

    HEADER_SIZE = 4

    def dump(self) -> bytes:
        hdr = bytearray(self.HEADER_SIZE)
        hdr[0:2] = pack("<H", self.return_code)
        # 0x02-0x03 reserved
        return bytes(hdr) + self.payload

    @classmethod
    def parse(cls, data: bytes, offset: int = 0) -> "EmbeddedCciResponse":
        if len(data) - offset < cls.HEADER_SIZE:
            raise ValueError("EmbeddedCciResponse: not enough bytes")
        rc = unpack_from("<H", data, offset)[0]
        payload = bytes(data[offset + 4:])
        return cls(return_code=rc, payload=payload)

    @classmethod
    def from_cci_response(cls, resp: CciResponse) -> "EmbeddedCciResponse":
        return cls(
            return_code=int(resp.return_code),
            payload=resp.payload or b"",
        )


@dataclass
class FabricCrawlOutResponsePayload:
    """Table 7-118 — Fabric Crawl Out output payload."""
    embedded_resp: EmbeddedCciResponse = None  # type: ignore

    HEADER_SIZE = 4

    def __post_init__(self):
        if self.embedded_resp is None:
            self.embedded_resp = EmbeddedCciResponse()

    def dump(self) -> bytes:
        resp_bytes = self.embedded_resp.dump()
        hdr = bytearray(self.HEADER_SIZE)
        hdr[0:2] = pack("<H", len(resp_bytes))
        # 0x02-0x03 reserved
        return bytes(hdr) + resp_bytes

    @classmethod
    def parse(cls, data: bytes) -> "FabricCrawlOutResponsePayload":
        if len(data) < cls.HEADER_SIZE:
            raise ValueError("FabricCrawlOutResponsePayload: need at least 4 bytes")
        resp_size = unpack_from("<H", data, 0)[0]
        if len(data) < cls.HEADER_SIZE + resp_size:
            raise ValueError("FabricCrawlOutResponsePayload: embedded response truncated")
        embedded = EmbeddedCciResponse.parse(data, cls.HEADER_SIZE)
        return cls(embedded_resp=embedded)

    def get_pretty_print(self) -> str:
        rc = CCI_RETURN_CODE(self.embedded_resp.return_code)
        return (
            f"- Embedded RC:         {rc.name}\n"
            f"- Embedded Payload:    {len(self.embedded_resp.payload)} bytes"
        )


# ---------------------------------------------------------------------------
# DspTunnelRegistry — maps port_index → DspCciTunnel
# Shared singleton per MctpCciExecutor instance
# ---------------------------------------------------------------------------


class DspTunnelRegistry:
    """
    Simple dict-backed registry passed into FabricCrawlOutCommand so it can
    look up the correct DspCciTunnel for any target port.
    """

    def __init__(self):
        self._tunnels: dict = {}

    def register(self, port_index: int, tunnel: DspCciTunnel) -> None:
        self._tunnels[port_index] = tunnel

    def get(self, port_index: int) -> Optional[DspCciTunnel]:
        return self._tunnels.get(port_index)

    def port_indices(self):
        return list(self._tunnels.keys())


# ---------------------------------------------------------------------------
# Command handler
# ---------------------------------------------------------------------------


class FabricCrawlOutCommand(CciForegroundCommand):
    """
    CCI foreground command for Fabric Crawl Out (Opcode 5701h).

    Registered on the switch-side CciExecutor (via MctpCciExecutor).

    When the FM (or GAE proxy) sends this command, it:
    1. Parses the target DSP port and the embedded CCI command.
    2. Looks up the DspCciTunnel for that port.
    3. Sends the embedded CCI command over the tunnel (cci_fifo).
    4. Wraps the GFD's CCI response in the Fabric Crawl Out response.
    """

    OPCODE = CCI_FM_API_COMMAND_OPCODE.FABRIC_CRAWL_OUT

    def __init__(self, tunnel_registry: DspTunnelRegistry):
        super().__init__(self.OPCODE)
        self._registry = tunnel_registry

    async def _execute(self, request: CciRequest) -> CciResponse:
        if not request.payload or len(request.payload) < FabricCrawlOutRequestPayload.HEADER_SIZE:
            logger.error(self._create_message("payload too short"))
            return CciResponse(return_code=CCI_RETURN_CODE.INVALID_INPUT)

        try:
            req_payload = FabricCrawlOutRequestPayload.parse(request.payload)
        except ValueError as exc:
            logger.error(self._create_message(f"parse error: {exc}"))
            return CciResponse(return_code=CCI_RETURN_CODE.INVALID_INPUT)

        tunnel = self._registry.get(req_payload.target_port)
        if tunnel is None:
            logger.error(
                self._create_message(
                    f"no tunnel for DSP port {req_payload.target_port} "
                    f"(known: {self._registry.port_indices()})"
                )
            )
            return CciResponse(return_code=CCI_RETURN_CODE.INVALID_INPUT)

        cci_request = req_payload.embedded_cmd.to_cci_request()
        gfd_response = await tunnel.send_and_wait(cci_request)

        embedded = EmbeddedCciResponse.from_cci_response(gfd_response)
        resp_payload = FabricCrawlOutResponsePayload(embedded_resp=embedded)
        response = CciResponse()
        response.payload = resp_payload.dump()
        return response

    # ------------------------------------------------------------------
    # Client-side helpers (used by MctpCciApiClient to build requests)
    # ------------------------------------------------------------------

    @staticmethod
    def create_cci_request(
        target_port: int, gfd_opcode: int, gfd_payload: bytes = b""
    ) -> CciRequest:
        embedded = EmbeddedCciCommand(opcode=gfd_opcode, payload=gfd_payload)
        req_payload = FabricCrawlOutRequestPayload(
            target_port=target_port, embedded_cmd=embedded
        )
        req = CciRequest()
        req.opcode = FabricCrawlOutCommand.OPCODE
        req.payload = req_payload.dump()
        return req

    @staticmethod
    def parse_response_payload(data: bytes) -> FabricCrawlOutResponsePayload:
        return FabricCrawlOutResponsePayload.parse(data)
