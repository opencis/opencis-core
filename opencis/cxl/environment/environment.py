"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from dataclasses import dataclass, field
from typing import List
import humanfriendly
import yaml

from opencis.apps.cxl_switch import (
    CxlSwitchConfig,
    VirtualSwitchConfig,
    PortConfig,
)
from opencis.cxl.component.cxl_component import PORT_TYPE
from opencis.cxl.device.config.logical_device import (
    LogicalDeviceConfig,
    SingleLogicalDeviceConfig,
    GenericFabricDeviceConfig,
    MultiLogicalDeviceConfig,
)


from opencis.cxl.component.hdm_decoder import (
    HDM_DECODER_COUNT,
    HDM_COUNT_TO_NUM,
)

def int_to_hdm_decoder_count(count: int) -> HDM_DECODER_COUNT:
    for enum_val in HDM_DECODER_COUNT:
        if HDM_COUNT_TO_NUM.calc(enum_val) == count:
            return enum_val
    raise ValueError(f"Invalid HDM decoder count: {count}")

@dataclass
class CxlEnvironment:
    switch_config: CxlSwitchConfig
    single_logical_device_configs: List[SingleLogicalDeviceConfig] = field(default_factory=list)
    generic_fabric_device_configs: List[GenericFabricDeviceConfig] = field(default_factory=list)
    multi_logical_device_configs: List[MultiLogicalDeviceConfig] = field(default_factory=list)
    logical_device_configs: List[LogicalDeviceConfig] = field(default_factory=list)


def parse_switch_config(config_data) -> CxlSwitchConfig:
    if "port_configs" not in config_data or not isinstance(config_data["port_configs"], list):
        raise ValueError("Missing or invalid 'port_configs' in configuration data.")

    switch_config = CxlSwitchConfig(
        host=config_data.get("host", "0.0.0.0"), port=config_data.get("port", 8000)
    )

    for port in config_data["port_configs"]:
        if "type" not in port:
            raise ValueError("Missing 'type' for 'port_config' entry.")
        if port["type"] not in ["USP", "DSP"]:
            raise ValueError(
                f"Invalid 'type' value for 'port_config': {port['type']}. Expected 'USP' or 'DSP'."
            )

        port_type = PORT_TYPE[port["type"]]
        switch_config.port_configs.append(PortConfig(type=port_type))

    if "virtual_switch_configs" not in config_data or not isinstance(
        config_data["virtual_switch_configs"], list
    ):
        raise ValueError("Missing or invalid 'virtual_switch_configs' in configuration data.")

    for vswitch in config_data["virtual_switch_configs"]:
        try:
            switch_config.virtual_switch_configs.append(
                VirtualSwitchConfig(
                    upstream_port_index=vswitch["upstream_port_index"],
                    vppb_counts=vswitch["vppb_counts"],
                    initial_bounds=vswitch["initial_bounds"],
                    irq_host="127.0.0.1",
                    irq_port=8500,
                )
            )
        except KeyError as e:
            raise ValueError(f"Missing {e.args[0]} for 'virtual_switch_config' entry.") from e

    if "hdm_decoder_capabilities" in config_data:
        raw_caps = config_data["hdm_decoder_capabilities"]
        try:
            # We must convert the integer count to the correct Enum
            decoder_count_enum = int_to_hdm_decoder_count(raw_caps.get("decoder_count", 1))
            
            # Map raw dictionary to HdmDecoderCapabilities TypedDict
            # Default missing fields to 0 or False
            hdm_caps = {
                "decoder_count": decoder_count_enum,
                "target_count": raw_caps.get("target_count", 1),
                "a11to8_interleave_capable": raw_caps.get("a11to8_interleave_capable", 0),
                "a14to12_interleave_capable": raw_caps.get("a14to12_interleave_capable", 0),
                "poison_on_decoder_error_capability": raw_caps.get("poison_on_decoder_error_capability", 0),
                "three_six_twelve_way_interleave_capable": raw_caps.get("three_six_twelve_way_interleave_capable", 0),
                "sixteen_way_interleave_capable": raw_caps.get("sixteen_way_interleave_capable", 0),
                "uio_capable": raw_caps.get("uio_capable", 0),
                "uio_capable_decoder_count": raw_caps.get("uio_capable_decoder_count", 0),
                "mem_data_nxm_capable": raw_caps.get("mem_data_nxm_capable", 0),
                "bi_capable": raw_caps.get("bi_capable", False),
            }
            switch_config.hdm_decoder_capabilities = hdm_caps
        except Exception as e:
            raise ValueError(f"Failed to parse 'hdm_decoder_capabilities': {e}") from e

    return switch_config


def parse_single_logical_device_configs(
    devices_data,
) -> List[SingleLogicalDeviceConfig]:
    if not isinstance(devices_data, list):
        raise ValueError("Invalid 'devices' configuration, expected a list.")

    single_logical_device_configs = []
    for device in devices_data:
        try:
            port_index = device["port_index"]
        except KeyError as exc:
            raise ValueError("Missing 'port_index' for 'device' entry.") from exc

        memory_file = device.get("memory_file", f"sld_mem{port_index}.bin")

        try:
            memory_size = humanfriendly.parse_size(device["memory_size"], binary=True)
        except KeyError as exc:
            raise ValueError("Missing 'memory_size' for 'device' entry.") from exc
        except humanfriendly.InvalidSize as exc:
            raise ValueError(f"Invalid 'memory_size' value: {device['memory_size']}") from exc

        try:
            serial_number = device["serial_number"]
        except KeyError as exc:
            raise ValueError("Missing 'serial_number' for 'device' entry.") from exc

        single_logical_device_configs.append(
            SingleLogicalDeviceConfig(
                port_index=port_index,
                serial_number=serial_number,
                memory_size=memory_size,
                memory_file=memory_file,
            )
        )
    return single_logical_device_configs


def parse_generic_fabric_device_configs(
    devices_data,
) -> List[GenericFabricDeviceConfig]:
    if not isinstance(devices_data, list):
        raise ValueError("Invalid 'devices' configuration, expected a list.")

    gfd_configs = []
    for device in devices_data:
        try:
            port_index = device["port_index"]
        except KeyError as exc:
            raise ValueError("Missing 'port_index' for 'device' entry.") from exc

        try:
            serial_number = device["serial_number"]
        except KeyError as exc:
            raise ValueError("Missing 'serial_number' for 'device' entry.") from exc

        gfd_configs.append(
            GenericFabricDeviceConfig(
                port_index=port_index,
                serial_number=serial_number,
            )
        )
    return gfd_configs


def parse_multi_logical_device_configs(
    devices_data,
) -> List[MultiLogicalDeviceConfig]:
    if not isinstance(devices_data, list):
        raise ValueError("Invalid 'devices' configuration, expected a list.")

    multi_logical_device_configs = []
    for device in devices_data:
        try:
            port_index = device["port_index"]
        except KeyError as exc:
            raise ValueError("Missing 'port_index' for 'device' entry.") from exc

        # Get memory sizes
        memory_sizes = []
        try:
            for item in device.get("logical_devices", []):
                memory_sizes.append(humanfriendly.parse_size(item["memory_size"], binary=True))
        except KeyError as exc:
            raise ValueError("Missing 'memory_size' for 'logical_devices' entry.") from exc
        except humanfriendly.InvalidSize as exc:
            raise ValueError("Invalid 'memory_size' value") from exc

        ld_list = []
        try:
            for item in device.get("logical_devices", []):
                ld_list.append(item["ld_id"])
        except KeyError as exc:
            raise ValueError("Missing 'ld_id' for 'logical_devices' entry.") from exc
        except humanfriendly.InvalidSize as exc:
            raise ValueError("Invalid 'ld_id' value") from exc

        # Get memory files (if not provided, default to "mld_mem{port_index}_{index}.bin")
        memory_files = []
        for index, item in enumerate(device.get("logical_devices", [])):
            memory_file = item.get("memory_file", f"mld_mem{port_index}_{index}.bin")
            memory_files.append(memory_file)

        assert len(memory_sizes) == len(
            memory_files
        ), "Mismatch between memory sizes and memory files."

        serial_numbers = []
        try:
            serial_numbers = [device["serial_number"]] * len(device.get("logical_devices", []))
        except KeyError as exc:
            raise ValueError("Missing 'serial_number' for 'device' entry.") from exc

        # Calculate total capacity - use provided value or sum of memory sizes
        total_capacity = 0
        if "total_capacity" in device:
            try:
                total_capacity = humanfriendly.parse_size(device["total_capacity"], binary=True)
            except humanfriendly.InvalidSize as exc:
                raise ValueError("Invalid 'total_capacity' value") from exc
        else:
            # Auto-calculate as sum of individual memory sizes
            if memory_sizes:
                total_capacity = sum(memory_sizes)
            else:
                # No logical devices configured - set a default total capacity for
                # dynamic allocation. This allows the MLD to be ready for dynamic LD creation
                total_capacity = 2 * 1024 * 1024 * 1024  # Default to 2GB

        # Get num_lds_supported from config, default to 16
        num_lds_supported = device.get("num_lds_supported", 16)

        multi_logical_device_configs.append(
            MultiLogicalDeviceConfig(
                port_index=port_index,
                ld_list=ld_list,
                serial_numbers=serial_numbers,
                ld_count=len(memory_sizes),
                memory_sizes=memory_sizes,
                memory_files=memory_files,
                total_capacity=total_capacity,
                num_lds_supported=num_lds_supported,
            )
        )
    return multi_logical_device_configs


def parse_cxl_environment(yaml_path: str) -> CxlEnvironment:
    with open(yaml_path, "r") as file:
        config_data = yaml.safe_load(file)

    if not config_data:
        raise ValueError("Configuration file is empty or has invalid content.")

    switch_config = parse_switch_config(config_data)
    single_logical_device_configs = parse_single_logical_device_configs(
        config_data.get("devices", {}).get("single_logical_devices", [])
    )
    generic_fabric_device_configs = parse_generic_fabric_device_configs(
        config_data.get("devices", {}).get("generic_fabric_devices", [])
    )
    multi_logical_device_configs = parse_multi_logical_device_configs(
        config_data.get("devices", {}).get("multi_logical_devices", [])
    )

    all_logical_devices = []
    all_logical_devices.extend(single_logical_device_configs)
    all_logical_devices.extend(generic_fabric_device_configs)
    all_logical_devices.extend(multi_logical_device_configs)

    return CxlEnvironment(
        switch_config=switch_config,
        single_logical_device_configs=single_logical_device_configs,
        generic_fabric_device_configs=generic_fabric_device_configs,
        multi_logical_device_configs=multi_logical_device_configs,
        logical_device_configs=all_logical_devices,
    )
