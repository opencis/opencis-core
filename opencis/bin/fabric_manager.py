"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.

Fabric Manager CLI — opencis fm <command>
=========================================

Standard FM commands:
  fm start               Start the Fabric Manager daemon
  fm bind                Bind a vPPB to a physical port
  fm unbind              Unbind a vPPB
  fm freeze              Freeze a vPPB
  fm unfreeze            Unfreeze a vPPB
  fm get-ld-info         Get LD info for a port
  fm get-ld-allocations  Get LD allocation table
  fm set-ld-allocation   Set LD allocation
  fm background-status   Check background command status

GFD / PBR Switch commands (§7.7.13):
  fm pbr-identify           Identify PBR Switch (5700h)
  fm pbr-configure-pid      Configure PID Assignment (5704h)
  fm pbr-clear-pid          Clear a PID Assignment (5704h, operation=1)
  fm pbr-get-pid-binding    Get PID Binding (5705h)
  fm pbr-bind-pid           Bind a PID to a vPPB (5706h, background)
  fm pbr-unbind-pid         Unbind a PID from a vPPB (5706h, background)
  fm pbr-get-drt            Get DRT entries (5708h)
  fm pbr-set-drt            Set DRT entries (5709h)
  fm pbr-fabric-crawl-out   Tunnel CCI command to GFD device (5701h)

GAE commands (§7.7.14):
  fm gae-identify           Identify GAE (5800h)
  fm gae-get-pid-vectors    Get PID Access Vectors (5802h)
  fm gae-proxy-gfd          Proxy GFD Mgmt command via GAE (5809h)
  fm gae-proxy-status       Get Proxy Thread Status (580Ah)
  fm gae-cancel-proxy       Cancel Proxy Thread (580Bh)
"""

import asyncio
import click

from opencis.util.logger import logger
from opencis.apps.fabric_manager import CxlFabricManager
from opencis.bin import socketio_client
from opencis.bin.common import BASED_INT


# ─────────────────────────────────────────────────────────────────────────────
# Top-level group
# ─────────────────────────────────────────────────────────────────────────────

@click.group(name="fm")
def fabric_manager_group():
    """Fabric Manager CLI commands."""


# ─────────────────────────────────────────────────────────────────────────────
# Daemon
# ─────────────────────────────────────────────────────────────────────────────

@fabric_manager_group.command(name="start")
@click.option("--use-test-runner", is_flag=True, help="Run with the test runner.")
@click.option("--config-file", help="<Config File> input path.")
def start(use_test_runner, config_file):
    """Run the Fabric Manager."""
    logger.info("Starting CXL FabricManager")
    fabric_manager = CxlFabricManager(use_test_runner=use_test_runner, config_file=config_file)
    try:
        asyncio.run(fabric_manager.run())
    except SystemExit:
        pass
    except Exception as e:
        logger.error("Error while running CXL FabricManager", exc_info=e)
        try:
            asyncio.run(fabric_manager.stop())
        except Exception as stop_e:
            logger.error("Error while stopping CXL FabricManager", exc_info=stop_e)


# ─────────────────────────────────────────────────────────────────────────────
# Standard FM commands
# ─────────────────────────────────────────────────────────────────────────────

@fabric_manager_group.command(name="bind")
@click.argument("vcs",      nargs=1, type=BASED_INT)
@click.argument("vppb",     nargs=1, type=BASED_INT)
@click.argument("physical", nargs=1, type=BASED_INT)
@click.argument("ld_id",    nargs=1, type=BASED_INT, default=0)
def fm_bind(vcs: int, vppb: int, physical: int, ld_id: int):
    """Bind VPPB to a physical port.  Usage: fm bind <vcs> <vppb> <port> [ld_id]"""
    asyncio.run(socketio_client.bind(vcs, vppb, physical, ld_id))


@fabric_manager_group.command(name="unbind")
@click.argument("vcs",  nargs=1, type=BASED_INT)
@click.argument("vppb", nargs=1, type=BASED_INT)
def fm_unbind(vcs: int, vppb: int):
    """Unbind a vPPB.  Usage: fm unbind <vcs> <vppb>"""
    asyncio.run(socketio_client.unbind(vcs, vppb))


@fabric_manager_group.command(name="freeze")
@click.argument("vcs",  nargs=1, type=BASED_INT)
@click.argument("vppb", nargs=1, type=BASED_INT)
def fm_freeze(vcs: int, vppb: int):
    """Freeze a vPPB.  Usage: fm freeze <vcs> <vppb>"""
    asyncio.run(socketio_client.freeze(vcs, vppb))


@fabric_manager_group.command(name="unfreeze")
@click.argument("vcs",  nargs=1, type=BASED_INT)
@click.argument("vppb", nargs=1, type=BASED_INT)
def fm_unfreeze(vcs: int, vppb: int):
    """Unfreeze a vPPB.  Usage: fm unfreeze <vcs> <vppb>"""
    asyncio.run(socketio_client.unfreeze(vcs, vppb))


@fabric_manager_group.command(name="get-ld-info")
@click.argument("port_index", nargs=1, type=BASED_INT)
def get_ld_info(port_index: int):
    """Get LD info for a port.  Usage: fm get-ld-info <port_index>"""
    asyncio.run(socketio_client.get_ld_info(port_index))


@fabric_manager_group.command(name="get-ld-allocations")
@click.argument("port_index",               nargs=1, type=BASED_INT)
@click.argument("start_ld_id",              nargs=1, type=BASED_INT)
@click.argument("ld_allocation_list_limit", nargs=1, type=BASED_INT)
def get_ld_allocation(port_index: int, start_ld_id: int, ld_allocation_list_limit: int):
    """Get LD allocation table.  Usage: fm get-ld-allocations <port> <start_ld_id> <limit>"""
    asyncio.run(
        socketio_client.get_ld_allocation(port_index, start_ld_id, ld_allocation_list_limit)
    )


@fabric_manager_group.command(name="set-ld-allocation")
@click.argument("port_index",        nargs=1, type=BASED_INT)
@click.argument("number_of_lds",     nargs=1, type=BASED_INT)
@click.argument("start_ld_id",       nargs=1, type=BASED_INT)
@click.argument("ld_allocation_list",nargs=1, type=BASED_INT)
def set_ld_allocation(
    port_index: int, number_of_lds: int, start_ld_id: int, ld_allocation_list: int
):
    """Set LD allocation.  Usage: fm set-ld-allocation <port> <n_lds> <start_ld> <list>"""
    asyncio.run(
        socketio_client.set_ld_allocation(
            port_index, number_of_lds, start_ld_id, ld_allocation_list
        )
    )


@fabric_manager_group.command(name="background-status")
def background_status():
    """Check the status of background CCI commands."""
    asyncio.run(socketio_client.get_background_status())


# ─────────────────────────────────────────────────────────────────────────────
# GFD / PBR Switch commands  (CXL Spec Rev 4.0 §7.7.13)
# ─────────────────────────────────────────────────────────────────────────────

@fabric_manager_group.command(name="pbr-identify")
def pbr_identify():
    """Identify PBR Switch (opcode 5700h).

    Returns: num_drts, num_rgts, routing_caps, gae_support_map.

    Example:\b
        fm pbr-identify
    """
    asyncio.run(socketio_client.pbr_identify())


@fabric_manager_group.command(name="pbr-configure-pid")
@click.argument("pid",       type=BASED_INT)
@click.argument("target_id", type=BASED_INT)
@click.option("--instance-id", type=BASED_INT, default=0, show_default=True,
              help="Instance ID for multi-instance targets.")
def pbr_configure_pid(pid: int, target_id: int, instance_id: int):
    """Assign a PID to a target port (opcode 5704h, operation=Assign).

    PID: 12-bit port identifier (e.g. 0x010).
    TARGET_ID: physical port number on the switch.

    \b
    Example:
        fm pbr-configure-pid 0x010 1
        fm pbr-configure-pid 0x020 2 --instance-id 0
    """
    asyncio.run(
        socketio_client.pbr_configure_pid(
            pid=pid, target_id=target_id, instance_id=instance_id, operation=0
        )
    )


@fabric_manager_group.command(name="pbr-clear-pid")
@click.argument("pid",       type=BASED_INT)
@click.argument("target_id", type=BASED_INT)
@click.option("--instance-id", type=BASED_INT, default=0, show_default=True)
def pbr_clear_pid(pid: int, target_id: int, instance_id: int):
    """Clear a PID assignment (opcode 5704h, operation=Clear).

    \b
    Example:
        fm pbr-clear-pid 0x010 1
    """
    asyncio.run(
        socketio_client.pbr_configure_pid(
            pid=pid, target_id=target_id, instance_id=instance_id, operation=1
        )
    )


@fabric_manager_group.command(name="pbr-get-pid-binding")
@click.argument("vcs_id",  type=BASED_INT)
@click.argument("vppb_id", type=BASED_INT)
def pbr_get_pid_binding(vcs_id: int, vppb_id: int):
    """Get the PID bound to a (VCS, vPPB) slot (opcode 5705h).

    Returns PID=0xFFF when the slot is unbound.

    \b
    Example:
        fm pbr-get-pid-binding 0 0
    """
    asyncio.run(socketio_client.pbr_get_pid_binding(vcs_id, vppb_id))


@fabric_manager_group.command(name="pbr-bind-pid")
@click.argument("vcs_id",  type=BASED_INT)
@click.argument("vppb_id", type=BASED_INT)
@click.argument("pid",     type=BASED_INT)
@click.option("--latency-base",  type=BASED_INT, default=0, show_default=True,
              help="HMAT latency entry base unit (8-byte value).")
@click.option("--latency-entry", type=BASED_INT, default=0, show_default=True,
              help="HMAT latency entry value.")
@click.option("--bw-base",  type=BASED_INT, default=0, show_default=True,
              help="HMAT BW entry base unit (8-byte value).")
@click.option("--bw-entry", type=BASED_INT, default=0, show_default=True,
              help="HMAT BW entry value.")
def pbr_bind_pid(
    vcs_id: int, vppb_id: int, pid: int,
    latency_base: int, latency_entry: int,
    bw_base: int, bw_entry: int,
):
    """Bind a PID to a (VCS, vPPB) slot — background command (opcode 5706h).

    This triggers link-state transitions (Hot Reset → Detect → L0).
    Poll 'fm background-status' to check completion.

    \b
    Example:
        fm pbr-bind-pid 0 0 0x010
    """
    asyncio.run(
        socketio_client.pbr_configure_pid_binding(
            vcs_id=vcs_id, vppb_id=vppb_id, pid=pid, operation=0,
            latency_base=latency_base, latency_entry=latency_entry,
            bw_base=bw_base, bw_entry=bw_entry,
        )
    )


@fabric_manager_group.command(name="pbr-unbind-pid")
@click.argument("vcs_id",  type=BASED_INT)
@click.argument("vppb_id", type=BASED_INT)
@click.argument("pid",     type=BASED_INT)
def pbr_unbind_pid(vcs_id: int, vppb_id: int, pid: int):
    """Unbind a PID from a (VCS, vPPB) slot — background command (opcode 5706h).

    \b
    Example:
        fm pbr-unbind-pid 0 0 0x010
    """
    asyncio.run(
        socketio_client.pbr_configure_pid_binding(
            vcs_id=vcs_id, vppb_id=vppb_id, pid=pid, operation=1,
        )
    )


@fabric_manager_group.command(name="pbr-get-drt")
@click.option("--drt-index",   type=BASED_INT, default=0,  show_default=True,
              help="DRT table index.")
@click.option("--start-entry", type=BASED_INT, default=0,  show_default=True,
              help="Starting DPID index into the DRT (0=first entry).")
@click.option("--num-entries", type=BASED_INT, default=16, show_default=True,
              help="Number of DRT entries to read.")
def pbr_get_drt(drt_index: int, start_entry: int, num_entries: int):
    """Read DRT entries mapping DPID → egress port (opcode 5708h).

    The DRT (DPID Routing Table) tells the switch which physical port to
    use when a CXL TLP arrives with a given DPID in its PBR header.

    \b
    Example:
        fm pbr-get-drt
        fm pbr-get-drt --drt-index 0 --start-entry 0x010 --num-entries 4
    """
    asyncio.run(socketio_client.pbr_get_drt(drt_index, start_entry, num_entries))


@fabric_manager_group.command(name="pbr-set-drt")
@click.argument("drt_index",   type=BASED_INT)
@click.argument("pid",         type=BASED_INT)
@click.argument("target_port", type=BASED_INT)
@click.option("--entry-type",
              type=click.Choice(["PHYSICAL_PORT", "RGT_INDEX", "INVALID"], case_sensitive=False),
              default="PHYSICAL_PORT", show_default=True,
              help="DRT entry type.")
def pbr_set_drt(drt_index: int, pid: int, target_port: int, entry_type: str):
    """Write a DRT entry: PID → port (opcode 5709h).

    Must be called after 'pbr-configure-pid' — PID assignment does NOT
    auto-populate the DRT.

    \b
    Workflow:
        fm pbr-configure-pid 0x010 1        # Assign PID 0x010 to port 1
        fm pbr-set-drt 0 0x010 1            # DRT[0][0x010] = PHYSICAL_PORT 1
        fm pbr-bind-pid 0 0 0x010           # Bind PID to vPPB (background)

    Example:
        fm pbr-set-drt 0 0x010 1
        fm pbr-set-drt 0 0x020 2 --entry-type RGT_INDEX
    """
    entries = [{"entryType": entry_type.upper(), "routingTarget": target_port}]
    asyncio.run(socketio_client.pbr_set_drt(drt_index, pid, entries))


@fabric_manager_group.command(name="pbr-fabric-crawl-out")
@click.argument("target_port", type=BASED_INT)
@click.argument("gfd_opcode",  type=BASED_INT)
@click.option("--payload", "-p", multiple=True, type=BASED_INT,
              help="Bytes to include in the GFD CCI payload (repeat for multiple bytes).")
def pbr_fabric_crawl_out(target_port: int, gfd_opcode: int, payload: tuple):
    """Tunnel a CCI command to a GFD device via DSP port (opcode 5701h).

    TARGET_PORT: switch DSP port index where the GFD is connected.
    GFD_OPCODE:  CCI opcode to forward to the GFD.

    The GFD CCI response (return code + payload) is returned embedded in
    the FabricCrawlOut CCI response.

    \b
    Example:
        fm pbr-fabric-crawl-out 1 0x0001
        fm pbr-fabric-crawl-out 2 0x0001 -p 0xAA -p 0xBB
    """
    asyncio.run(
        socketio_client.pbr_fabric_crawl_out(
            target_port=target_port,
            gfd_opcode=gfd_opcode,
            gfd_payload=list(payload),
        )
    )


# ─────────────────────────────────────────────────────────────────────────────
# GAE (Generic Access Endpoint) commands  (CXL Spec Rev 4.0 §7.7.14)
# ─────────────────────────────────────────────────────────────────────────────

@fabric_manager_group.command(name="gae-identify")
def gae_identify():
    """Identify GAE — returns vPPB G-FAM support list (opcode 5800h).

    Shows which vPPBs on the Host-Edge USP have Global Memory support.

    \b
    Example:
        fm gae-identify
    """
    asyncio.run(socketio_client.gae_identify())


@fabric_manager_group.command(name="gae-get-pid-vectors")
@click.argument("pid", type=BASED_INT)
def gae_get_pid_access_vectors(pid: int):
    """Get PID Access Vectors for a PID (opcode 5802h).

    Returns GMV (Global Memory Vector) and VTV (Valid Target Vector)
    bitmasks showing which VCS IDs and vPPBs can reach the given PID.

    \b
    Example:
        fm gae-get-pid-vectors 0x010
    """
    asyncio.run(socketio_client.gae_get_pid_access_vectors(pid))


@fabric_manager_group.command(name="gae-proxy-gfd")
@click.argument("gfd_opcode", type=BASED_INT)
@click.option("--payload", "-p", multiple=True, type=BASED_INT,
              help="Bytes for the proxied GFD command payload.")
def gae_proxy_gfd_mgmt(gfd_opcode: int, payload: tuple):
    """Proxy a CCI command to a GFD through the GAE (opcode 5809h).

    Returns a thread_id. Poll 'fm gae-proxy-status <thread_id>' to get
    the GFD's response when the proxy operation completes.

    \b
    Example:
        fm gae-proxy-gfd 0x0001
        fm gae-proxy-gfd 0x0001 -p 0xAA -p 0xBB
    """
    asyncio.run(socketio_client.gae_proxy_gfd_mgmt(gfd_opcode, list(payload)))


@fabric_manager_group.command(name="gae-proxy-status")
@click.argument("thread_id", type=BASED_INT)
def gae_get_proxy_status(thread_id: int):
    """Poll completion of a proxied GFD command (opcode 580Ah).

    Returns completed flag, GFD return code, and GFD response payload
    when the proxy thread has finished.

    \b
    Example:
        fm gae-proxy-status 1
    """
    asyncio.run(socketio_client.gae_get_proxy_status(thread_id))


@fabric_manager_group.command(name="gae-cancel-proxy")
@click.argument("thread_id", type=BASED_INT)
def gae_cancel_proxy(thread_id: int):
    """Cancel an in-progress proxied GFD command (opcode 580Bh).

    \b
    Example:
        fm gae-cancel-proxy 1
    """
    asyncio.run(socketio_client.gae_cancel_proxy(thread_id))
