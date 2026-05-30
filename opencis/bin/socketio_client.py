"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

import asyncio
import sys
import socketio
from yaml import dump

# Standard Python client setup for Socket.IO
sio = socketio.AsyncClient()


@sio.on("port:updated")
def handle_port_updated():
    print("[Notification]")
    print("port:updated")


@sio.on("vcs:updated")
def handle_vcs_updated():
    print("[Notification]")
    print("port:updated")


@sio.on("device:updated")
def handle_device_updated():
    print("[Notification]")
    print("device:updated")


class CustomSemaphore(asyncio.Semaphore):
    def __init__(self, value=0, custom_value=None):
        super().__init__(value)
        self.custom_value = custom_value

    def set_custom_value(self, value):
        self.custom_value = value


async def send(event, param=None):
    sema = CustomSemaphore()

    def callback_handler(result):
        sema.set_custom_value(result)
        sema.release()

    print("[Request]")
    print(event)
    await sio.emit(event, param, callback=callback_handler)
    await sema.acquire()
    result = sema.custom_value

    print("[Response]")
    print_result(result)
    return result


def print_result(data):
    print(dump(data, sort_keys=False, default_flow_style=False))


# Connect event handler
@sio.event
async def connect():
    print("Connected to the server")


# Disconnect event handler
@sio.event
def disconnect():
    print("Disconnected from server")


async def get_port():
    await sio.connect("http://0.0.0.0:8200")
    await send(
        "port:get",
    )
    await sio.disconnect()


async def get_vcs():
    await sio.connect("http://0.0.0.0:8200")
    await send(
        "vcs:get",
    )
    await sio.disconnect()


async def get_device():
    await sio.connect("http://0.0.0.0:8200")
    await send(
        "device:get",
    )
    await sio.disconnect()


# Bind & unbind
async def bind(vcs: int, vppb: int, physical_port: int, ld_id: int = 0):
    await sio.connect("http://0.0.0.0:8200")
    await send(
        "vcs:bind",
        {"virtualCxlSwitchId": vcs, "vppbId": vppb, "physicalPortId": physical_port, "ldId": ld_id},
    )
    await sio.disconnect()


async def unbind(vcs: int, vppb: int):
    await sio.connect("http://0.0.0.0:8200")
    await send(
        "vcs:unbind",
        {"virtualCxlSwitchId": vcs, "vppbId": vppb},
    )
    await sio.disconnect()


async def get_ld_info(port_index: int):
    await sio.connect("http://0.0.0.0:8200")
    await send(
        "mld:get",
        {"portIndex": port_index},
    )
    await sio.disconnect()


async def get_ld_allocation(port_index: int, start_ld_id: int, ld_allocation_list_limit: int):
    await sio.connect("http://0.0.0.0:8200")
    result = await send(
        "mld:getAllocation",
        {
            "portIndex": port_index,
            "startLdId": start_ld_id,
            "ldAllocationListLimit": ld_allocation_list_limit,
        },
    )
    await sio.disconnect()
    return result


async def set_ld_allocation(
    port_index: int, number_of_lds: int, start_ld_id: int, ld_allocation_list: list
):
    await sio.connect("http://0.0.0.0:8200")
    await send(
        "mld:setAllocation",
        {
            "portIndex": port_index,
            "numberOfLds": number_of_lds,
            "startLdId": start_ld_id,
            "ldAllocationList": ld_allocation_list,
        },
    )
    await sio.disconnect()


async def get_background_status():
    await sio.connect("http://0.0.0.0:8200")
    await send("background:getStatus", {})
    await sio.disconnect()


async def freeze(vcs: int, vppb: int):
    await sio.connect("http://0.0.0.0:8200")
    await send(
        "vcs:freeze",
        {"virtualCxlSwitchId": vcs, "vppbId": vppb},
    )
    await sio.disconnect()


async def unfreeze(vcs: int, vppb: int):
    await sio.connect("http://0.0.0.0:8200")
    await send(
        "vcs:unfreeze",
        {"virtualCxlSwitchId": vcs, "vppbId": vppb},
    )
    await sio.disconnect()


# ─────────────────────────────────────────────────────────────────────────────
# PBR Switch (GFD) commands — §7.7.13
# ─────────────────────────────────────────────────────────────────────────────

async def pbr_identify():
    """Identify PBR Switch (5700h) — returns num_drts, num_rgts, routing_caps."""
    await sio.connect("http://0.0.0.0:8200")
    await send("pbr:identify")
    await sio.disconnect()


async def pbr_configure_pid(
    pid: int,
    target_id: int,
    instance_id: int = 0,
    operation: int = 0,
):
    """Configure PID Assignment (5704h).
    operation: 0=Assign, 1=Clear
    """
    await sio.connect("http://0.0.0.0:8200")
    await send(
        "pbr:configurePid",
        {
            "operation": operation,
            "entries": [
                {"pid": pid, "targetId": target_id, "instanceId": instance_id}
            ],
        },
    )
    await sio.disconnect()


async def pbr_get_pid_binding(vcs_id: int, vppb_id: int):
    """Get PID Binding (5705h) — returns PID bound to (vcs, vppb)."""
    await sio.connect("http://0.0.0.0:8200")
    await send(
        "pbr:getPidBinding",
        {"vcsId": vcs_id, "vppbId": vppb_id},
    )
    await sio.disconnect()


async def pbr_configure_pid_binding(
    vcs_id: int,
    vppb_id: int,
    pid: int,
    operation: int = 0,
    latency_base: int = 0,
    latency_entry: int = 0,
    bw_base: int = 0,
    bw_entry: int = 0,
):
    """Configure PID Binding (5706h) — background command.
    operation: 0=Bind, 1=Unbind
    """
    await sio.connect("http://0.0.0.0:8200")
    await send(
        "pbr:configurePidBinding",
        {
            "operation": operation,
            "vcsId": vcs_id,
            "vppbId": vppb_id,
            "pid": pid,
            "latencyEntryBaseUnit": latency_base,
            "latencyEntry": latency_entry,
            "bwEntryBaseUnit": bw_base,
            "bwEntry": bw_entry,
        },
    )
    await sio.disconnect()


async def pbr_get_drt(
    drt_index: int = 0,
    start_entry: int = 0,
    num_entries: int = 16,
):
    """Get DRT (5708h) — reads DRT entries mapping DPID → egress port."""
    await sio.connect("http://0.0.0.0:8200")
    await send(
        "pbr:getDrt",
        {
            "drtIndex": drt_index,
            "startEntry": start_entry,
            "numEntries": num_entries,
        },
    )
    await sio.disconnect()


async def pbr_set_drt(
    drt_index: int,
    start_entry: int,
    entries: list,
):
    """Set DRT (5709h) — programs DPID→port routing entries.

    entries: list of dicts like:
      [{"entryType": "PHYSICAL_PORT", "routingTarget": 1}, ...]
    entryType values: "PHYSICAL_PORT", "RGT_INDEX", "INVALID"
    """
    await sio.connect("http://0.0.0.0:8200")
    await send(
        "pbr:setDrt",
        {
            "drtIndex": drt_index,
            "startEntry": start_entry,
            "entries": entries,
        },
    )
    await sio.disconnect()


async def pbr_fabric_crawl_out(
    target_port: int,
    gfd_opcode: int,
    gfd_payload: list = None,
):
    """Fabric Crawl Out (5701h) — tunnel a CCI command to a GFD via DSP port."""
    await sio.connect("http://0.0.0.0:8200")
    await send(
        "pbr:fabricCrawlOut",
        {
            "targetPort": target_port,
            "gfdOpcode": gfd_opcode,
            "gfdPayload": gfd_payload or [],
        },
    )
    await sio.disconnect()


# ─────────────────────────────────────────────────────────────────────────────
# GAE (Generic Access Endpoint) commands — §7.7.14
# ─────────────────────────────────────────────────────────────────────────────

async def gae_identify():
    """Identify GAE (5800h) — returns vPPB G-FAM support list."""
    await sio.connect("http://0.0.0.0:8200")
    await send("gae:identify")
    await sio.disconnect()


async def gae_get_pid_access_vectors(pid: int):
    """Get PID Access Vectors (5802h) — returns GMV and VTV bitmasks for a PID."""
    await sio.connect("http://0.0.0.0:8200")
    await send(
        "gae:getPidAccessVectors",
        {"pid": pid},
    )
    await sio.disconnect()


async def gae_proxy_gfd_mgmt(gfd_opcode: int, gfd_payload: list = None):
    """Proxy GFD Management Command (5809h) — forward CCI command to GFD via GAE.
    Returns thread_id for status polling.
    """
    await sio.connect("http://0.0.0.0:8200")
    await send(
        "gae:proxyGfdMgmt",
        {
            "gfdOpcode": gfd_opcode,
            "gfdPayload": gfd_payload or [],
        },
    )
    await sio.disconnect()


async def gae_get_proxy_status(thread_id: int):
    """Get Proxy Thread Status (580Ah) — poll completion of a proxy GFD command."""
    await sio.connect("http://0.0.0.0:8200")
    await send(
        "gae:getProxyStatus",
        {"threadId": thread_id},
    )
    await sio.disconnect()


async def gae_cancel_proxy(thread_id: int):
    """Cancel Proxy Thread (580Bh) — cancel an in-progress proxy GFD command."""
    await sio.connect("http://0.0.0.0:8200")
    await send(
        "gae:cancelProxy",
        {"threadId": thread_id},
    )
    await sio.disconnect()


# Main asynchronous function to start the client
async def start_client():
    await sio.connect("http://0.0.0.0:8200")
    await sio.wait()


# Stop the client gracefully
async def stop_client():
    await sio.disconnect()
    sys.exit()


# Run the client
if __name__ == "__main__":
    asyncio.run(start_client())
