#!/usr/bin/env python3

from typing import Dict, List
import pyshark, time
from pyshark.packet.packet import Packet
from opencis.cxl.transport.transaction import CXL_CACHE_D2HREQ_OPCODE, CXL_CACHE_D2HRSP_OPCODE, CXL_CACHE_H2DREQ_OPCODE, CXL_CACHE_H2DRSP_CACHE_STATE, CXL_CACHE_H2DRSP_OPCODE, CXL_CACHE_MSG_CLASS

# Path to your Lua script
# lua_script_path = 'my_script.lua'

# Path to your pcap file
pcap_file_path = '/home/zhxq/100000-pr-filtered.pcap'

# Define custom parameters to load the Lua script
# custom_params = {'-X': f'lua_script:{lua_script_path}'}

# Open the pcap file with custom parameters
# cap = pyshark.FileCapture(input_file=pcap_file_path, custom_parameters=custom_params)
cap = pyshark.FileCapture(input_file=pcap_file_path, display_filter='opencis.cache')

# Set this up for all switches
# enter the port number of all switches
switches = [22500]

# Allow unhandled requests
tolerate_unhandled_req = False





# Allowed State Transitions
# --------------------------------------


D2H_REQ_SEMANTICS_DATA_REQUIRED = {
    "Read": True,
    "Read0": False,
    "Write": False,
}

H2D_RSP_SEMANTICS_DATA_REQUIRED = {
    "Read": False,
    "Read0": False,
    "Write": True,
    "Read0-Write": True
}

# Table 3-22
# We only implemented the set of opcodes we implemented in OpenCIS
D2H_REQ_BEHAVIOR = {
    CXL_CACHE_D2HREQ_OPCODE.CACHE_RD_CURR: "Read",
    CXL_CACHE_D2HREQ_OPCODE.CACHE_RD_OWN: "Read",
    CXL_CACHE_D2HREQ_OPCODE.CACHE_RD_SHARED: "Read",
    CXL_CACHE_D2HREQ_OPCODE.CACHE_RD_OWN_NO_DATA: "Read0",
    CXL_CACHE_D2HREQ_OPCODE.CACHE_CLEAN_EVICT: "Write",
    CXL_CACHE_D2HREQ_OPCODE.CACHE_DIRTY_EVICT: "Write",
    CXL_CACHE_D2HREQ_OPCODE.CACHE_CLEAN_EVICT_NO_DATA: "Write"
}

D2H_REQ_LEGAL_RSP_OPCODE: Dict[CXL_CACHE_D2HREQ_OPCODE, List[CXL_CACHE_H2DRSP_OPCODE]] = {
    CXL_CACHE_D2HREQ_OPCODE.CACHE_RD_CURR: [],
    CXL_CACHE_D2HREQ_OPCODE.CACHE_RD_OWN: [CXL_CACHE_H2DRSP_OPCODE.GO],
    CXL_CACHE_D2HREQ_OPCODE.CACHE_RD_SHARED: [CXL_CACHE_H2DRSP_OPCODE.GO],
    CXL_CACHE_D2HREQ_OPCODE.CACHE_RD_OWN_NO_DATA: [CXL_CACHE_H2DRSP_OPCODE.GO],
    CXL_CACHE_D2HREQ_OPCODE.CACHE_CLEAN_EVICT: [CXL_CACHE_H2DRSP_OPCODE.GO_WRITE_PULL,CXL_CACHE_H2DRSP_OPCODE.GO_WRITE_PULL_DROP],
    CXL_CACHE_D2HREQ_OPCODE.CACHE_DIRTY_EVICT: [CXL_CACHE_H2DRSP_OPCODE.GO_WRITE_PULL, CXL_CACHE_H2DRSP_OPCODE.GO_ERR_WRITE_PUL],
    CXL_CACHE_D2HREQ_OPCODE.CACHE_CLEAN_EVICT_NO_DATA: [CXL_CACHE_H2DRSP_OPCODE.GO]
}

D2H_REQ_LEGAL_RSP_MESI: Dict[CXL_CACHE_D2HREQ_OPCODE, List[CXL_CACHE_H2DRSP_CACHE_STATE]] = {
    CXL_CACHE_D2HREQ_OPCODE.CACHE_RD_OWN: [CXL_CACHE_H2DRSP_CACHE_STATE.INVALID, CXL_CACHE_H2DRSP_CACHE_STATE.EXCLUSIVE, CXL_CACHE_H2DRSP_CACHE_STATE.MODIFIED, CXL_CACHE_H2DRSP_CACHE_STATE.ERROR],
    CXL_CACHE_D2HREQ_OPCODE.CACHE_RD_SHARED: [CXL_CACHE_H2DRSP_CACHE_STATE.INVALID, CXL_CACHE_H2DRSP_CACHE_STATE.SHARED, CXL_CACHE_H2DRSP_CACHE_STATE.ERROR],
    CXL_CACHE_D2HREQ_OPCODE.CACHE_RD_ANY: [CXL_CACHE_H2DRSP_CACHE_STATE.INVALID, CXL_CACHE_H2DRSP_CACHE_STATE.SHARED, CXL_CACHE_H2DRSP_CACHE_STATE.EXCLUSIVE, CXL_CACHE_H2DRSP_CACHE_STATE.MODIFIED, CXL_CACHE_H2DRSP_CACHE_STATE.ERROR],
    CXL_CACHE_D2HREQ_OPCODE.CACHE_RD_OWN_NO_DATA: [CXL_CACHE_H2DRSP_CACHE_STATE.EXCLUSIVE, CXL_CACHE_H2DRSP_CACHE_STATE.ERROR],
    CXL_CACHE_D2HREQ_OPCODE.CACHE_CLEAN_EVICT_NO_DATA: [CXL_CACHE_H2DRSP_CACHE_STATE.INVALID]
}

H2D_REQ_SEMANTICS_DATA_REQUIRED = [CXL_CACHE_D2HRSP_OPCODE.RSP_S_FWD_M, CXL_CACHE_D2HRSP_OPCODE.RSP_I_FWD_M, CXL_CACHE_D2HRSP_OPCODE.RSP_V_FWD_V]

H2D_REQ_LEGAL_RSP_OPCODE: Dict[CXL_CACHE_H2DREQ_OPCODE, List[CXL_CACHE_D2HRSP_OPCODE]] = {
    CXL_CACHE_H2DREQ_OPCODE.SNP_DATA: [CXL_CACHE_D2HRSP_OPCODE.RSP_I_HIT_I, CXL_CACHE_D2HRSP_OPCODE.RSP_S_HIT_SE, CXL_CACHE_D2HRSP_OPCODE.RSP_S_FWD_M, CXL_CACHE_D2HRSP_OPCODE.RSP_I_FWD_M],
    CXL_CACHE_H2DREQ_OPCODE.SNP_INV: [CXL_CACHE_D2HRSP_OPCODE.RSP_I_HIT_I, CXL_CACHE_D2HRSP_OPCODE.RSP_I_HIT_SE, CXL_CACHE_D2HRSP_OPCODE.RSP_I_FWD_M],
    CXL_CACHE_H2DREQ_OPCODE.SNP_CUR: [CXL_CACHE_D2HRSP_OPCODE.RSP_I_HIT_I, CXL_CACHE_D2HRSP_OPCODE.RSP_V_HIT_V, CXL_CACHE_D2HRSP_OPCODE.RSP_S_HIT_SE, CXL_CACHE_D2HRSP_OPCODE.RSP_S_FWD_M, CXL_CACHE_D2HRSP_OPCODE.RSP_I_FWD_M, CXL_CACHE_D2HRSP_OPCODE.RSP_V_FWD_V]
}

H2D_RSP_OPCODE_WITH_UQID: List[CXL_CACHE_H2DRSP_OPCODE] = [CXL_CACHE_H2DRSP_OPCODE.WRITE_PULL, CXL_CACHE_H2DRSP_OPCODE.GO_WRITE_PULL, CXL_CACHE_H2DRSP_OPCODE.GO_WRITE_PULL_DROP, CXL_CACHE_H2DRSP_OPCODE.FAST_GO_WRITE_PULL, CXL_CACHE_H2DRSP_OPCODE.GO_ERR_WRITE_PUL]

# Main Code
# ------------------------------------------

hosts: List[int] = []
devices: Dict[int, int] = {}

unhandled_h2d_rsp: Dict[int, Dict[int, int]] = {}

class ReqTracker():
    def __init__(self, packet: Packet, rsp_required: bool = True, data_required: bool = False, second_rsp_required: bool = False):
        self._packet = packet
        self._rsp_required = rsp_required
        self._data_required = data_required
        self._second_rsp_required = second_rsp_required
        self._rsp_done = False
        self._second_rsp_done = False
        self._data_done = False
    def set_rsp_done(self):
        if self._rsp_required:
            self._rsp_done = True
        else:
            if self._second_rsp_required:
                self._second_rsp_done = True
            else:
                raise Exception("This packet does not require rsp!")
    def set_data_required(self):
        self._data_required = True
    def set_data_done(self):
        if self._data_required:
            self._data_done = True
        else:
            raise Exception("This packet does not require data!")
    def all_done(self):
        first_rsp_state = self._rsp_done if self._rsp_required else True
        second_rsp_state = self._second_rsp_done if self._second_rsp_required else True
        data_state = self._data_done if self._data_required else True
        return first_rsp_state and second_rsp_state and data_state
    def get_packet(self):
        return self._packet
    def print_states(self):
        first_rsp_state = self._rsp_done if self._rsp_required else True
        second_rsp_state = self._second_rsp_done if self._second_rsp_required else True
        data_state = self._data_done if self._data_required else True
        print("-------------")
        print((self._rsp_required, self._second_rsp_required, self._data_required))
        print((self._rsp_done, self._second_rsp_done, self._data_done))
        print((first_rsp_state, second_rsp_state, data_state))
        print("-------------")

# Index: device port number
# Value: key: CQID
cqid_req: Dict[int, Dict[int, ReqTracker]] = {}

def add_cqid_req(dev_port: int, cqid: int, tracker: ReqTracker):
    if dev_port not in cqid_req:
        cqid_req[dev_port] = {}
    if cqid in cqid_req[dev_port]:
        add_to_orphan(cqid_req[dev_port][cqid])
    cqid_req[dev_port][cqid] = tracker

def get_cqid_req(dev_port: int, cqid: int):
    if dev_port not in cqid_req:
        raise Exception(f"Port {dev_port} does not exist in cqid_req!")
    if cqid not in cqid_req[dev_port]:
        raise Exception(f"CQID {cqid} does not exist in cqid_req[{dev_port}]!")
    return cqid_req[dev_port][cqid]

def mark_cqid_req_finished(dev_port: int, cqid: int):
    # print(f"Dev port {dev_port}, CQID {cqid} DONE!")
    if dev_port not in cqid_req:
        raise Exception(f"Port {dev_port} does not exist in cqid_req!")
    if cqid not in cqid_req[dev_port]:
        raise Exception(f"CQID {cqid} does not exist in cqid_req[{dev_port}]!")
    del(cqid_req[dev_port][cqid])

# Index: host port number
# Value: key: UQID
uqid_req: Dict[int, Dict[int, ReqTracker]] = {}
def add_uqid_req(host_port: int, uqid: int, tracker: ReqTracker):
    if host_port not in uqid_req:
        uqid_req[host_port] = {}
    if uqid in uqid_req[host_port]:
        add_to_orphan(uqid_req[host_port][uqid])
    uqid_req[host_port][uqid] = tracker

def get_uqid_req(host_port: int, uqid: int):
    if host_port not in uqid_req:
        raise Exception(f"Port {host_port} does not exist in uqid_req!")
    if uqid not in uqid_req[host_port]:
        raise Exception(f"UQID {uqid} does not exist in uqid_req[{host_port}]!")
    return uqid_req[host_port][uqid]

def mark_uqid_req_finished(host_port: int, uqid: int):
    # print(f"Host port {host_port}, UQID {uqid} DONE!")
    if host_port not in uqid_req:
        raise Exception(f"Port {host_port} does not exist in uqid_req!")
    if uqid not in uqid_req[host_port]:
        raise Exception(f"UQID {uqid} does not exist in uqid_req[{host_port}]!")
    del(uqid_req[host_port][uqid])


# Orphan requests
unprocessed_req: List[ReqTracker] = []

def add_to_orphan(req: ReqTracker):
    if not tolerate_unhandled_req:
        print(req.get_packet())
        raise Exception(f"Packet above (packet number: {req.get_packet().number}) was not handled before a new packet with the same CQID/UQID coming in!")
    unprocessed_req.append(req)

# Integrity checks
def d2h_check(src_port: int, dst_port: int, cache_id: int = None):
    if src_port in switches and dst_port in switches:
        # switch to switch
        if (src_port in hosts or src_port in devices):
            raise Exception(f"Source port {src_port} is a switch, but it is also in the list of hosts/devices!")
        if (dst_port in hosts or dst_port in devices):
            raise Exception(f"Destination port {dst_port} is a switch, but it is also in the list of hosts/devices!")
    elif src_port in switches:
        # to host
        if dst_port in devices:
            raise Exception(f"Destination port {dst_port} is a device, but the packet is a D2H Req!")
        if dst_port not in hosts:
            hosts.append(dst_port)
    elif dst_port in switches:
        # from device
        if src_port in hosts:
            raise Exception(f"Source port {src_port} is a host, but the packet is a D2H Req!")
        if cache_id is not None:
            if src_port not in devices:
                devices[src_port] = cache_id
            else:
                if devices[src_port] != cache_id:
                    raise Exception(f"Cache ID mismatch for this packet and prior packets from this CXL.cache device!")
    else:
        # direct D2H
        if (src_port in hosts or src_port in switches):
            raise Exception(f"Source port {src_port} is a device, but it is also in the list of hosts/switches!")
        if (dst_port in devices or dst_port in switches):
            raise Exception(f"Destination port {dst_port} is a device, but it is also in the list of devices/switches!")
        if cache_id is not None:
            if src_port not in devices:
                devices[src_port] = cache_id
            else:
                if devices[src_port] != cache_id:
                    raise Exception(f"Cache ID mismatch for this packet and prior packets from this CXL.cache device!")

def h2d_check(src_port: int, dst_port: int, cache_id: int = None):
    if src_port in switches and dst_port in switches:
        # switch to switch
        if (src_port in hosts or src_port in devices):
            raise Exception(f"Source port {src_port} is a switch, but it is also in the list of hosts/devices!")
        if (dst_port in hosts or dst_port in devices):
            raise Exception(f"Destination port {dst_port} is a switch, but it is also in the list of hosts/devices!")
    elif src_port in switches:
        # to device
        if dst_port in hosts:
            raise Exception(f"Destination port {dst_port} is a host, but the packet is a H2D Rsp!")
        if dst_port not in devices:
            raise Exception(f"Destination port {dst_port} came out of nowhere!")
        else:
            if cache_id is not None:
                if devices[dst_port] != cache_id:
                    raise Exception(f"Cache ID mismatch for this packet and prior packets from this CXL.cache device!")
    elif dst_port in switches:
        # from host
        if src_port in devices:
            raise Exception(f"Source port {src_port} is a device, but the packet is a H2D Rsp!")
        if src_port not in hosts:
            hosts.append(src_port)
    else:
        # direct H2D
        if (src_port in devices or src_port in switches):
            raise Exception(f"Source port {src_port} is a host, but it is also in the list of devices/switches!")
        if (dst_port in hosts or dst_port in switches):
            raise Exception(f"Destination port {dst_port} is a device, but it is also in the list of hosts/switches!")
        if dst_port not in devices:
            raise Exception(f"Destination port {dst_port} came out of nowhere!")
        else:
            if cache_id is not None:
                if devices[dst_port] != cache_id:
                    raise Exception(f"Cache ID mismatch for this packet and prior packets from this CXL.cache device!")

# Process or iterate through packets (this will trigger the Lua script execution)
# TODO: may need to handle H2D RSP after D2H Data (e.g., Figure 3-14/3-15)
# Which is required for WrInv and WOWrInv/F with FastGO/ExtCmp


start_time = time.perf_counter()
processed_count = 0
packet: Packet
for packet in cap:
    if processed_count % 10000 == 0:
        print(f"{processed_count} packets processed...")
    packet_num: int = packet.number
    src_port: int = packet.tcp.srcport.hex_value
    dst_port: int = packet.tcp.dstport.hex_value
    # print(dir(packet.tcp))
    packet_type = packet.opencis.cache_channel_t.hex_value
    if packet_type == CXL_CACHE_MSG_CLASS.D2H_REQ:
        cache_id = packet.opencis.cache_d2h_req_cache_id.hex_value
        cqid = packet.opencis.cache_d2h_req_cqid.hex_value
        opcode = packet.opencis.cache_d2h_req_cache_opcode.hex_value
        d2h_check(src_port, dst_port, cache_id)
        if opcode not in D2H_REQ_BEHAVIOR:
            raise Exception(f"{CXL_CACHE_D2HREQ_OPCODE(opcode).name} is not supported by D2H_REQ_BEHAVIOR for now!")
        rsp_required = True
        if opcode == CXL_CACHE_D2HREQ_OPCODE.CACHE_RD_CURR:
            rsp_required = False
        opcode_semantics = D2H_REQ_BEHAVIOR[opcode]
        data_required = D2H_REQ_SEMANTICS_DATA_REQUIRED[opcode_semantics]
        
        if src_port in devices:
            tracker = ReqTracker(packet, rsp_required, data_required)
            add_cqid_req(src_port, cqid, tracker)
    elif packet_type == CXL_CACHE_MSG_CLASS.D2H_RSP:
        uqid = packet.opencis.cache_d2h_rsp_uqid.hex_value
        rsp_opcode = packet.opencis.cache_d2h_rsp_cache_opcode.hex_value
        d2h_check(src_port, dst_port)
        if dst_port in hosts:
            tracker = get_uqid_req(dst_port, uqid)
            req_opcode = tracker.get_packet().opencis.cache_h2d_req_cache_opcode.hex_value
            if rsp_opcode not in H2D_REQ_LEGAL_RSP_OPCODE[req_opcode]:
                raise Exception(f"{CXL_CACHE_D2HRSP_OPCODE(rsp_opcode).name} is not a valid response for {CXL_CACHE_H2DREQ_OPCODE(req_opcode).name} H2D Request!")
            tracker.set_rsp_done()
            if rsp_opcode in H2D_REQ_SEMANTICS_DATA_REQUIRED:
                tracker.set_data_required()
            if tracker.all_done():
                mark_uqid_req_finished(dst_port, uqid)
    elif packet_type == CXL_CACHE_MSG_CLASS.D2H_DATA:
        uqid = packet.opencis.cache_d2h_data_uqid.hex_value
        d2h_check(src_port, dst_port)
        if dst_port in hosts:
            tracker = get_uqid_req(dst_port, uqid)
            tracker.set_data_done()
            if tracker.all_done():
                mark_uqid_req_finished(dst_port, uqid)
    elif packet_type == CXL_CACHE_MSG_CLASS.H2D_REQ:
        # Check cache_id
        cache_id = packet.opencis.cache_h2d_req_cache_id.hex_value
        uqid = packet.opencis.cache_h2d_req_uqid.hex_value
        opcode = packet.opencis.cache_h2d_req_cache_opcode.hex_value
        h2d_check(src_port, dst_port, cache_id)
        rsp_required = True
        
        if src_port in hosts:
            tracker = ReqTracker(packet, rsp_required, False)
            add_uqid_req(src_port, uqid, tracker)
    elif packet_type == CXL_CACHE_MSG_CLASS.H2D_RSP:
        # Check cache_id
        cache_id = packet.opencis.cache_h2d_rsp_cache_id.hex_value
        cqid = packet.opencis.cache_h2d_rsp_cqid.hex_value
        rsp_opcode = packet.opencis.cache_h2d_rsp_cache_opcode.hex_value
        h2d_check(src_port, dst_port, cache_id)

        # Check returned opcode and check MESI (if applicable)
        if dst_port in devices:
            tracker = get_cqid_req(dst_port, cqid)
            req_opcode = tracker.get_packet().opencis.cache_d2h_req_cache_opcode.hex_value
            if rsp_opcode not in D2H_REQ_LEGAL_RSP_OPCODE[req_opcode]:
                raise Exception(f"{CXL_CACHE_H2DRSP_OPCODE(rsp_opcode).name} is not a legal opcode for {CXL_CACHE_D2HREQ_OPCODE(req_opcode).name}!")
            if rsp_opcode == CXL_CACHE_H2DRSP_OPCODE.GO:
                # Check MESI validity for GO
                mesi_state = packet.opencis.cache_h2d_rsp_rsp_data.hex_value
                if mesi_state not in D2H_REQ_LEGAL_RSP_MESI[req_opcode]:
                    raise Exception(f"MESI state {CXL_CACHE_H2DRSP_CACHE_STATE(mesi_state).name} is illegal for {CXL_CACHE_D2HREQ_OPCODE(req_opcode).name}!")
            elif rsp_opcode in H2D_RSP_OPCODE_WITH_UQID:
                # Read0-Write or Write requires data sent from D2H after H2D Rsp (Figure 3-14 ~ 3-16)
                uqid = packet.opencis.cache_h2d_rsp_rsp_data.hex_value
                if req_opcode in D2H_REQ_BEHAVIOR:
                    req_behavior = D2H_REQ_BEHAVIOR[req_opcode]
                    d2h_data_required = H2D_RSP_SEMANTICS_DATA_REQUIRED[req_behavior]
                    rsp_required = False
                    if rsp_required or d2h_data_required:
                        host_port = unhandled_h2d_rsp[uqid][cqid]
                        del(unhandled_h2d_rsp[uqid][cqid])
                        new_tracker = ReqTracker(packet, rsp_required, d2h_data_required)
                        add_uqid_req(host_port, uqid, new_tracker)
            tracker.set_rsp_done()
            if tracker.all_done():
                mark_cqid_req_finished(dst_port, cqid)
        if src_port in hosts:
            if rsp_opcode in H2D_RSP_OPCODE_WITH_UQID:
                # This H2D_RSP has a UQID and waits for device data
                cqid = packet.opencis.cache_h2d_rsp_cqid.hex_value
                uqid = packet.opencis.cache_h2d_rsp_rsp_data.hex_value
                
                if uqid not in unhandled_h2d_rsp:
                    unhandled_h2d_rsp[uqid] = {}
                
                if cqid in unhandled_h2d_rsp[uqid]:
                    raise Exception(f"Prior UQID {uqid}/CQID {cqid} pair was not handled promptly!")

                unhandled_h2d_rsp[uqid][cqid] = src_port
                # Will be further handled when the device receives the packet
                # Because we need to use that CQID
                
    elif packet_type == CXL_CACHE_MSG_CLASS.H2D_DATA:
        # Check cache_id
        cache_id = packet.opencis.cache_h2d_data_cache_id.hex_value
        cqid = packet.opencis.cache_h2d_data_cqid.hex_value
        h2d_check(src_port, dst_port, cache_id)
        if dst_port in devices:
            tracker = get_cqid_req(dst_port, cqid)
            tracker.set_data_done()
            if tracker.all_done():
                mark_cqid_req_finished(dst_port, cqid)
    # print(type(packet.tcp.port.showname_value))
    # print(packet.opencis.cache_channel_t.showname_value)
    # print(dir(packet.opencis))
    # print(packet.opencis.system_payload_type.raw_value)
    # print(dir(packet.opencis.system_payload_type))
    processed_count += 1

# Check unhandled packets
cqid_unhandled_packet_num = 0
for items in cqid_req.values():
    cqid_unhandled_packet_num += len(items)

uqid_unhandled_packet_num = 0
for items in uqid_req.values():
    uqid_unhandled_packet_num += len(items)

unhandled_h2d_rsp_packet_num = 0
for items in unhandled_h2d_rsp.values():
    unhandled_h2d_rsp_packet_num += len(items)

print(f"{cqid_unhandled_packet_num} unhandled packets with CQID")
print(f"{uqid_unhandled_packet_num} unhandled packets with UQID")
print(f"{unhandled_h2d_rsp_packet_num} unhandled H2D Rsp packets waiting to be added to the UQID handle queue")


print("")
# Close the capture
cap.close()
end_time = time.perf_counter()
elapsed_time = end_time - start_time
print(f"Elapsed time: {elapsed_time:.6f} seconds")
print(f"Average: {(processed_count / elapsed_time):.6f} packets/s")