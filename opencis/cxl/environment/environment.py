"""
Copyright (c) 2024, Eeum, Inc.

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
    MultiLogicalDeviceConfig,
)


@dataclass
class CxlEnvironment:
    switch_config: CxlSwitchConfig
    single_logical_device_configs: List[SingleLogicalDeviceConfig] = field(default_factory=list)
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
        try:
            for index, item in enumerate(device.get("logical_devices", [])):
                if len(item) == 0:
                    memory_file = item["memory_file"]
                else:
                    memory_file = f"mld_mem{port_index}_{index}.bin"
                memory_files.append(memory_file)
        except KeyError as exc:
            raise ValueError("Missing 'memory_file' for 'logical_devices' entry.") from exc

        assert len(memory_sizes) == len(
            memory_files
        ), "Mismatch between memory sizes and memory files."

        serial_numbers = []
        try:
            serial_numbers = [device["serial_number"]] * len(device.get("logical_devices", []))
        except KeyError as exc:
            raise ValueError("Missing 'serial_number' for 'device' entry.") from exc

        multi_logical_device_configs.append(
            MultiLogicalDeviceConfig(
                port_index=port_index,
                ld_list=ld_list,
                serial_numbers=serial_numbers,
                ld_count=len(memory_sizes),
                memory_sizes=memory_sizes,
                memory_files=memory_files,
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
    multi_logical_device_configs = parse_multi_logical_device_configs(
        config_data.get("devices", {}).get("multi_logical_devices", [])
    )

    return CxlEnvironment(
        switch_config=switch_config,
        single_logical_device_configs=single_logical_device_configs,
        multi_logical_device_configs=multi_logical_device_configs,
        logical_device_configs=single_logical_device_configs + multi_logical_device_configs,
    )
