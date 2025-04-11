"""
 Copyright (c) 2025, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

# pylint: disable=duplicate-code
from asyncio import gather, create_task
from typing import cast
import logging
import pytest

from opencis.cxl.component.cache_controller import CacheController, CacheControllerConfig
from opencis.cxl.component.cxl_mem_dcoh import CxlMemDcoh
from opencis.cxl.component.cxl_memory_device_component import (
    CxlMemoryDeviceComponent,
    MemoryDeviceIdentity,
)
from opencis.cxl.transport.cache_fifo import CacheFifoPair
from opencis.cxl.transport.common import BasePacket
from opencis.cxl.transport.transaction import (
    CXL_MEM_M2S_SNP_TYPE,
    CXL_MEM_M2SREQ_OPCODE,
    CXL_MEM_M2SRWD_OPCODE,
    CXL_MEM_META_FIELD,
    CXL_MEM_META_VALUE,
    CxlMemBasePacket,
    CxlMemMemRdPacket,
    CxlMemMemWrPacket,
)
from opencis.pci.component.fifo_pair import FifoPair
from opencis.util.logger import logger
from opencis.util.number_const import MB


def create_cxl_mem_dcoh():
    memory_size = 256 * MB
    memory_file = "test_mem_dcoh.bin"
    cache_line_count = 32

    cache_to_coh_agent_fifo = CacheFifoPair()
    coh_agent_to_cache_fifo = CacheFifoPair()
    upstream_fifo = FifoPair()

    cxl_mem_dcoh = CxlMemDcoh(
        cache_to_coh_agent_fifo,
        coh_agent_to_cache_fifo,
        upstream_fifo,
        test_mode=True,
    )

    identity = MemoryDeviceIdentity()
    identity.fw_revision = MemoryDeviceIdentity.ascii_str_to_int("EEUM EMU 1.0", 16)
    identity.set_total_capacity(memory_size)
    identity.set_volatile_only_capacity(memory_size)
    cxl_memory_device_component = CxlMemoryDeviceComponent(
        identity,
        decoder_count=1,
        memory_file=memory_file,
        memory_size=memory_size,
        cache_lines=cache_line_count,
    )

    cxl_mem_dcoh.set_memory_device_component(cxl_memory_device_component)

    cache_num_assoc = 4
    cache_controller_config = CacheControllerConfig(
        component_name="test",
        processor_to_cache_fifo=None,
        cache_to_coh_agent_fifo=cache_to_coh_agent_fifo,
        coh_agent_to_cache_fifo=coh_agent_to_cache_fifo,
        cache_num_assoc=cache_num_assoc,
        cache_num_set=cache_line_count // cache_num_assoc,
    )
    cache_controller = CacheController(cache_controller_config)

    return (cxl_mem_dcoh, upstream_fifo, cache_controller)


@pytest.mark.asyncio
async def test_cxl_mem_dcoh_run_stop():
    cxl_mem_dcoh, _1, _2 = create_cxl_mem_dcoh()

    async def wait_and_stop():
        await cxl_mem_dcoh.wait_for_ready()
        await cxl_mem_dcoh.stop()

    tasks = [create_task(cxl_mem_dcoh.run()), create_task(wait_and_stop())]
    await gather(*tasks)


@pytest.mark.asyncio
async def test_cxl_mem_dcoh_read():
    cxl_mem_dcoh, upstream_fifo, cache_controller = create_cxl_mem_dcoh()

    tasks = [
        create_task(cxl_mem_dcoh.run()),
        create_task(cache_controller.run()),
    ]
    await cxl_mem_dcoh.wait_for_ready()
    await cache_controller.wait_for_ready()

    # Reference: home_agent.py

    # Test target address
    addr = 0x1000

    # HDM-H Normal Read
    opcode = CXL_MEM_M2SREQ_OPCODE.MEM_RD
    meta_field = CXL_MEM_META_FIELD.NO_OP
    meta_value = CXL_MEM_META_VALUE.ANY
    snp_type = CXL_MEM_M2S_SNP_TYPE.NO_OP

    packet = CxlMemMemRdPacket.create(addr, opcode, meta_field, meta_value, snp_type)
    await upstream_fifo.host_to_target.put(packet)

    packet = await upstream_fifo.target_to_host.get()

    base_packet = cast(BasePacket, packet)
    if not base_packet.is_cxl_mem():
        raise Exception(f"Received unexpected packet: {base_packet.get_type()}")
    resp_packet = cast(CxlMemBasePacket, packet)
    if not resp_packet.is_s2mdrs():
        raise Exception(f"Received unexpected response packet: {resp_packet.get_type()}")

    # HDM-DB Device Shared Read (Cmp-S: S/S, Cmp-E: A/I)
    opcode = CXL_MEM_M2SREQ_OPCODE.MEM_RD
    meta_field = CXL_MEM_META_FIELD.META0_STATE
    meta_value = CXL_MEM_META_VALUE.SHARED
    snp_type = CXL_MEM_M2S_SNP_TYPE.SNP_DATA

    packet = CxlMemMemRdPacket.create(addr, opcode, meta_field, meta_value, snp_type)
    await upstream_fifo.host_to_target.put(packet)

    packet = await upstream_fifo.target_to_host.get()

    base_packet = cast(BasePacket, packet)
    if not base_packet.is_cxl_mem():
        raise Exception(f"Received unexpected packet: {base_packet.get_type()}")
    resp_packet = cast(CxlMemBasePacket, packet)
    if not resp_packet.is_s2mndr():
        raise Exception(f"Received unexpected response packet: {resp_packet.get_type()}")

    # HDM-DB Non-Data, Host Ownership Device Invalidation (Cmp-E: A/I)
    opcode = CXL_MEM_M2SREQ_OPCODE.MEM_INV
    meta_field = CXL_MEM_META_FIELD.META0_STATE
    meta_value = CXL_MEM_META_VALUE.ANY
    snp_type = CXL_MEM_M2S_SNP_TYPE.SNP_INV

    packet = CxlMemMemRdPacket.create(addr, opcode, meta_field, meta_value, snp_type)
    await upstream_fifo.host_to_target.put(packet)

    packet = await upstream_fifo.target_to_host.get()

    base_packet = cast(BasePacket, packet)
    if not base_packet.is_cxl_mem():
        raise Exception(f"Received unexpected packet: {base_packet.get_type()}")
    resp_packet = cast(CxlMemBasePacket, packet)
    if not resp_packet.is_s2mdrs():
        raise Exception(f"Received unexpected response packet: {resp_packet.get_type()}")

    # HDM-DB Non-Cacheable Read, Leaving Device Cache (Cmp: I/A)
    opcode = CXL_MEM_M2SREQ_OPCODE.MEM_RD
    meta_field = CXL_MEM_META_FIELD.META0_STATE
    meta_value = CXL_MEM_META_VALUE.ANY
    snp_type = CXL_MEM_M2S_SNP_TYPE.SNP_CUR

    packet = CxlMemMemRdPacket.create(addr, opcode, meta_field, meta_value, snp_type)
    await upstream_fifo.host_to_target.put(packet)

    packet = await upstream_fifo.target_to_host.get()

    base_packet = cast(BasePacket, packet)
    if not base_packet.is_cxl_mem():
        raise Exception(f"Received unexpected packet: {base_packet.get_type()}")
    resp_packet = cast(CxlMemBasePacket, packet)
    if not resp_packet.is_s2mndr():
        raise Exception(f"Received unexpected response packet: {resp_packet.get_type()}")

    await cxl_mem_dcoh.stop()
    await cache_controller.stop()
    await gather(*tasks)


@pytest.mark.asyncio
async def test_cxl_mem_dcoh_write():
    logger.setLevel(logging.DEBUG)

    cxl_mem_dcoh, upstream_fifo, cache_controller = create_cxl_mem_dcoh()

    tasks = [
        create_task(cxl_mem_dcoh.run()),
        create_task(cache_controller.run()),
    ]
    await cxl_mem_dcoh.wait_for_ready()
    await cache_controller.wait_for_ready()

    # Reference: home_agent.py

    # Test target address
    addr = 0x1000
    data = 0xDEADBEEF

    # HDM-H Normal Write, HDM Uncached Write
    opcode = CXL_MEM_M2SRWD_OPCODE.MEM_WR
    meta_field = CXL_MEM_META_FIELD.NO_OP
    meta_value = CXL_MEM_META_VALUE.ANY
    snp_type = CXL_MEM_M2S_SNP_TYPE.NO_OP

    packet = CxlMemMemWrPacket.create(addr, data, opcode, meta_field, meta_value, snp_type)
    await upstream_fifo.host_to_target.put(packet)

    packet = await upstream_fifo.target_to_host.get()

    base_packet = cast(BasePacket, packet)
    if not base_packet.is_cxl_mem():
        raise Exception(f"Received unexpected packet: {base_packet.get_type()}")
    resp_packet = cast(CxlMemBasePacket, packet)
    if not resp_packet.is_s2mndr():
        raise Exception(f"Received unexpected response packet: {resp_packet.get_type()}")

    # HDM-H Normal Write, HDM Uncached Write
    opcode = CXL_MEM_M2SRWD_OPCODE.MEM_WR
    meta_field = CXL_MEM_META_FIELD.META0_STATE
    meta_value = CXL_MEM_META_VALUE.INVALID
    snp_type = CXL_MEM_M2S_SNP_TYPE.NO_OP

    packet = CxlMemMemWrPacket.create(addr, data, opcode, meta_field, meta_value, snp_type)
    await upstream_fifo.host_to_target.put(packet)

    packet = await upstream_fifo.target_to_host.get()

    base_packet = cast(BasePacket, packet)
    if not base_packet.is_cxl_mem():
        raise Exception(f"Received unexpected packet: {base_packet.get_type()}")
    resp_packet = cast(CxlMemBasePacket, packet)
    if not resp_packet.is_s2mndr():
        raise Exception(f"Received unexpected response packet: {resp_packet.get_type()}")

    await cxl_mem_dcoh.stop()
    await cache_controller.stop()
    await gather(*tasks)
