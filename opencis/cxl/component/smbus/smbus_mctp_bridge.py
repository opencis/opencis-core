"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.

SmbusToMctpBridge — Host-side adapter: QEMU SMBus ↔ FM MCTP CCI port 8300
===========================================================================

Topology
--------

  QEMU Host
  ┌─────────────────────────────────────────────────────────────┐
  │  SMBus Slave                         SMBus Master           │
  │  (sends raw MCTP CciPayloadPackets)  (receives CCI response)│
  └──────────┬───────────────────────────────────────┬──────────┘
             │  Unix domain socket (full-duplex)      │
             ▼                                        ▲
  ┌──────────────────────────────────────────────────────────────┐
  │              SmbusToMctpBridge  (this module)                │
  │                                                              │
  │  asyncio.start_unix_server()                                 │
  │    └─ _session_handler(reader, writer)                       │
  │         ├─ MctpPacketReader → reads CciPayloadPacket         │
  │         ├─ auto-assigns message_tag (0-255 cyclic)           │
  │         ├─ opens TCP connection to FM :8300                  │
  │         ├─ forwards CciPayloadPacket bytes → FM              │
  │         ├─ reads CciPayloadPacket response from FM           │
  │         └─ writes response bytes → Unix socket (Master)      │
  └─────────────────────────┬────────────────────────────────────┘
                            │ TCP :8300
                            ▼
            ┌──────────────────────────────────┐
            │  Docker FM  (unchanged)           │
            │  FmMctpCciServer  :8300           │
            │    → send_raw_cci()               │
            │    → MctpCciApiClient  :8100      │
            │    → CxlSwitch / PbrSwitchManager │
            └──────────────────────────────────┘

Wire format
-----------
Both sides (QEMU socket and FM TCP) use the same CciPayloadPacket framing that
the rest of the opencis MCTP stack uses — no translation layer is needed.

The bridge only touches one field: cci_msg_header.message_tag.
Tags are auto-assigned (0–255 cyclic, per session) so each forwarded request
carries a unique tag.  The corresponding response is read from the FM, the tag
is preserved as-is from the FM response, and the full packet is relayed back
to the Unix socket.

Usage
-----
Standalone:
  python -m opencis.cxl.component.smbus.smbus_mctp_bridge \\
      --unix-path /tmp/smbus_mctp.sock \\
      --fm-host 127.0.0.1 \\
      --fm-port 8300

Integrated into run_pbr_env.py via --smbus-bridge flag.
"""

import asyncio
import os
import sys
from asyncio import StreamReader, StreamWriter, create_task, gather
from typing import Optional

from opencis.util.component import RunnableComponent
from opencis.util.logger import logger
from opencis.cxl.component.mctp.mctp_packet_reader import MctpPacketReader
from opencis.cxl.transport.cci_packets import CciMessagePacket, CciPayloadPacket
from opencis.cxl.transport.packet_constants import CCI_MCTP_MESSAGE_CATEGORY
from opencis.cxl.transport.common import BasePacket
from opencis.cxl.transport.packet_structs import SystemHeader
from opencis.cxl.cci.common import get_opcode_string


# ---------------------------------------------------------------------------
# Internal helper — reads a CciPayloadPacket from a TCP StreamReader
# (same logic as MctpPacketReader but returns the raw bytes too so we can
# relay them verbatim after patching the tag field)
# ---------------------------------------------------------------------------

async def _read_cci_payload_packet(reader: StreamReader) -> bytes:
    """
    Read exactly one CciPayloadPacket from *reader* and return its raw bytes.

    Raises EOFError if the connection is closed mid-read.
    """
    hdr_size = SystemHeader.get_size()
    header_bytes = await reader.readexactly(hdr_size)
    base = BasePacket(bytearray(header_bytes))
    remaining = base.system_header.payload_length - len(base)
    if remaining < 0:
        raise ValueError(f"Negative remaining length: {remaining}")
    rest = await reader.readexactly(remaining) if remaining else b""
    return header_bytes + rest


# ---------------------------------------------------------------------------
# SmbusToMctpBridge
# ---------------------------------------------------------------------------

class SmbusToMctpBridge(RunnableComponent):
    """
    Host-side adapter that bridges QEMU SMBus Unix-socket clients to the
    Fabric Manager's MCTP CCI TCP server (port 8300).

    Parameters
    ----------
    unix_socket_path : str
        Path of the Unix domain socket to create.  E.g. ``/tmp/smbus_mctp.sock``.
        Any pre-existing socket file at this path is removed before binding.
    fm_host : str
        Hostname/IP of the Fabric Manager container.  Default: ``"127.0.0.1"``.
    fm_port : int
        TCP port of FmMctpCciServer on the FM.  Default: ``8300``.
    label : str, optional
        Label for logger messages.
    """

    def __init__(
        self,
        unix_socket_path: str,
        fm_host: str = "127.0.0.1",
        fm_port: int = 8300,
        label: Optional[str] = None,
    ) -> None:
        super().__init__(label or "SmbusToMctpBridge")
        self._unix_path = unix_socket_path
        self._fm_host = fm_host
        self._fm_port = fm_port
        self._server: Optional[asyncio.AbstractServer] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _run(self) -> None:
        # Remove stale socket file if present
        if os.path.exists(self._unix_path):
            os.remove(self._unix_path)

        self._server = await asyncio.start_unix_server(
            self._session_handler,
            path=self._unix_path,
        )

        logger.info(self._create_message(
            f"Listening on Unix socket {self._unix_path!r} "
            f"→ FM {self._fm_host}:{self._fm_port}"
        ))
        await self._change_status_to_running()

        async with self._server:
            await self._server.serve_forever()

    async def _stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
        # Clean up socket file
        if os.path.exists(self._unix_path):
            try:
                os.remove(self._unix_path)
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Per-connection session
    # ------------------------------------------------------------------

    async def _session_handler(
        self, reader: StreamReader, writer: StreamWriter
    ) -> None:
        """
        Handle one full-duplex Unix socket connection from QEMU.

        Opens a dedicated TCP connection to FM :8300 for the lifetime of
        this session.  QEMU can issue multiple sequential CCI commands;
        each gets a freshly auto-sequenced message_tag.
        """
        peer = writer.get_extra_info("peername") or self._unix_path
        logger.info(self._create_message(f"SMBus client connected: {peer}"))

        try:
            fm_reader, fm_writer = await asyncio.open_connection(
                self._fm_host, self._fm_port
            )
        except OSError as exc:
            logger.error(self._create_message(
                f"Cannot connect to FM {self._fm_host}:{self._fm_port}: {exc}"
            ))
            writer.close()
            return

        logger.info(self._create_message(
            f"FM TCP connection established → {self._fm_host}:{self._fm_port}"
        ))

        tag_counter = 0  # auto-sequence: 0-255 cyclic per session

        try:
            while True:
                # ── Step 1: read CciPayloadPacket from QEMU Unix socket ──
                try:
                    raw_bytes = await _read_cci_payload_packet(reader)
                except asyncio.IncompleteReadError:
                    logger.info(self._create_message(
                        f"SMBus client disconnected: {peer}"
                    ))
                    break
                except Exception as exc:
                    logger.warning(self._create_message(
                        f"Read error from {peer}: {exc}"
                    ))
                    break

                # ── Step 2: patch message_tag with auto-sequence ──────────
                raw_bytes = bytearray(raw_bytes)
                pkt = CciPayloadPacket(raw_bytes)
                cci_msg: CciMessagePacket = pkt.get_cci_message()
                opcode     = cci_msg.cci_msg_header.command_opcode
                orig_tag   = cci_msg.cci_msg_header.message_tag
                opcode_str = get_opcode_string(opcode)

                # Build a new CciMessagePacket with the auto-sequenced tag
                payload_bytes = cci_msg.get_payload() or b""
                new_cci_msg = CciMessagePacket.create(
                    message_category=CCI_MCTP_MESSAGE_CATEGORY.REQUEST,
                    opcode=opcode,
                    data=payload_bytes,
                    message_tag=tag_counter,
                )
                new_pkt = CciPayloadPacket.create(new_cci_msg)
                forwarded_bytes = bytes(new_pkt)

                logger.debug(self._create_message(
                    f"→ FM  opcode={opcode_str}({opcode:#06x}) "
                    f"orig_tag={orig_tag} new_tag={tag_counter} "
                    f"payload_len={len(payload_bytes)}"
                ))

                # ── Step 3: forward to FM TCP :8300 ──────────────────────
                fm_writer.write(forwarded_bytes)
                await fm_writer.drain()

                # ── Step 4: read CCI response from FM ────────────────────
                try:
                    resp_bytes = await _read_cci_payload_packet(fm_reader)
                except asyncio.IncompleteReadError:
                    logger.warning(self._create_message(
                        "FM disconnected before sending response"
                    ))
                    break
                except Exception as exc:
                    logger.warning(self._create_message(
                        f"FM read error: {exc}"
                    ))
                    break

                resp_pkt   = CciPayloadPacket(bytearray(resp_bytes))
                resp_msg   = resp_pkt.get_cci_message()
                rc         = resp_msg.cci_msg_header.return_code
                is_bg      = bool(resp_msg.cci_msg_header.background_operation)

                logger.debug(self._create_message(
                    f"← FM  opcode={opcode_str}({opcode:#06x}) "
                    f"tag={tag_counter} rc={rc} background={is_bg}"
                ))

                # ── Step 5: relay response to QEMU Unix socket ────────────
                writer.write(resp_bytes)
                await writer.drain()

                # Advance tag counter (0-255 cyclic)
                tag_counter = (tag_counter + 1) & 0xFF

        finally:
            fm_writer.close()
            try:
                await fm_writer.wait_closed()
            except Exception:
                pass
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            logger.info(self._create_message(f"Session closed: {peer}"))


# ---------------------------------------------------------------------------
# __main__ — standalone runner
# ---------------------------------------------------------------------------

def _parse_args():
    import argparse
    p = argparse.ArgumentParser(
        description="SMBus ↔ MCTP bridge — relay QEMU Unix socket to FM :8300"
    )
    p.add_argument(
        "--unix-path", default="/tmp/smbus_mctp.sock",
        help="Unix domain socket path (default: /tmp/smbus_mctp.sock)"
    )
    p.add_argument(
        "--fm-host", default="127.0.0.1",
        help="FM host (default: 127.0.0.1)"
    )
    p.add_argument(
        "--fm-port", type=int, default=8300,
        help="FM MCTP CCI port (default: 8300)"
    )
    return p.parse_args()


async def _main():
    args = _parse_args()
    bridge = SmbusToMctpBridge(
        unix_socket_path=args.unix_path,
        fm_host=args.fm_host,
        fm_port=args.fm_port,
    )
    print(f"[bridge] Unix socket : {args.unix_path}")
    print(f"[bridge] FM target   : {args.fm_host}:{args.fm_port}")
    print("[bridge] Press Ctrl+C to stop.\n")
    await bridge.run()


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        print("\n[bridge] Stopped.")
