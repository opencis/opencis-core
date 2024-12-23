"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

from dataclasses import dataclass
from struct import pack, unpack, calcsize
from typing import List, TypedDict
from yaml import dump

from opencis.cxl.component.cci_executor import (
    CciForegroundCommand,
    CciRequest,
    CciResponse,
)
from opencis.cxl.component.physical_port_manager import PhysicalPortManager
from opencis.cxl.cci.common import CCI_VENDOR_SPECIFIC_OPCODE


class DeviceInfoDict(TypedDict):
    pcie_vendor_id: int
    pcie_device_id: int
    pcie_subsystem_vendor_id: int
    pcie_subsystem_id: int
    device_serial_number: str
    bound_port_id: int
    total_capacity: int


@dataclass
class DeviceInfo:
    pcie_vendor_id: int
    pcie_device_id: int
    pcie_subsystem_vendor_id: int
    pcie_subsystem_id: int
    device_serial_number: str  # Hexadecimal serial number, Total of 16 characters (8 Bytes)
    bound_port_id: int
    total_capacity: int  # Expressed in multiples of 256MB

    # Class variable for struct format
    struct_format = ">H H H H 8s B I"

    def dump(self) -> bytes:
        # Convert total_capacity into 256MB units for packing
        total_capacity_in_256mb_units = self.total_capacity // (256 * 1024 * 1024)
        return pack(
            DeviceInfo.struct_format,
            self.pcie_vendor_id,
            self.pcie_device_id,
            self.pcie_subsystem_vendor_id,
            self.pcie_subsystem_id,
            bytes.fromhex(self.device_serial_number),
            self.bound_port_id,
            total_capacity_in_256mb_units,
        )

    @staticmethod
    def parse(data: bytes) -> "DeviceInfo":
        if len(data) != DeviceInfo.get_size():
            raise ValueError("Incorrect byte length for DeviceInfo")

        unpacked_data = unpack(DeviceInfo.struct_format, data)
        # Multiply total_capacity by 256MB after unpacking
        total_capacity_in_bytes = unpacked_data[6] * 256 * 1024 * 1024
        return DeviceInfo(
            pcie_vendor_id=unpacked_data[0],
            pcie_device_id=unpacked_data[1],
            pcie_subsystem_vendor_id=unpacked_data[2],
            pcie_subsystem_id=unpacked_data[3],
            device_serial_number=unpacked_data[4].hex().upper(),
            bound_port_id=unpacked_data[5],
            total_capacity=total_capacity_in_bytes,
        )

    def to_dict(self) -> DeviceInfoDict:
        total_capacity_in_256mb_units = self.total_capacity // (256 * 1024 * 1024)
        return {
            "pcieVendorId": self.pcie_vendor_id,
            "pcieDeviceId": self.pcie_device_id,
            "pcieSubsystemId": self.pcie_subsystem_id,
            "pcieSubsystemVendorId": self.pcie_subsystem_vendor_id,
            "deviceSerialNumber": self.device_serial_number,
            "boundPortId": self.bound_port_id,
            "totalCapacity": total_capacity_in_256mb_units,
        }

    @classmethod
    def get_size(cls) -> int:
        return calcsize(cls.struct_format)


class GetConnectedDevicesResponsePayloadDict(TypedDict):
    devices: List[DeviceInfoDict]


@dataclass
class GetConnectedDevicesResponsePayload:
    devices: List[DeviceInfo]

    def dump(self) -> bytes:
        # Pack the number of devices
        data = pack("B", len(self.devices))

        # Add each device's data
        for device in self.devices:
            data += device.dump()

        return data

    @staticmethod
    def parse(data: bytes) -> "GetConnectedDevicesResponsePayload":
        if len(data) < 1:
            raise ValueError("Data too short to contain device count")

        # The first byte is the count of devices
        device_count = unpack("B", data[0:1])[0]
        expected_length = 1 + device_count * DeviceInfo.get_size()

        if len(data) != expected_length:
            raise ValueError(
                "Incorrect byte length for GetConnectedDevicesResponsePayload: "
                f"Expected {expected_length}, got {len(data)}"
            )

        devices = []
        offset = 1

        for _ in range(device_count):
            device_data = data[offset : offset + DeviceInfo.get_size()]
            devices.append(DeviceInfo.parse(device_data))
            offset += DeviceInfo.get_size()

        return GetConnectedDevicesResponsePayload(devices=devices)

    def to_dict(self) -> GetConnectedDevicesResponsePayloadDict:
        return {"devices": [device.to_dict() for device in self.devices]}

    def get_pretty_print(self) -> str:
        return dump(self.to_dict(), sort_keys=False, default_flow_style=False)


class GetConnectedDevicesCommand(CciForegroundCommand):
    OPCODE = CCI_VENDOR_SPECIFIC_OPCODE.GET_CONNECTED_DEVICES

    def __init__(self, physical_port_manager: PhysicalPortManager):
        super().__init__(self.OPCODE)
        self._physical_port_manager = physical_port_manager

    async def _execute(self, _: CciRequest) -> CciResponse:
        connected_devices = self._physical_port_manager.get_connected_devices()
        device_info_list = []
        for device in connected_devices:
            device_info = DeviceInfo(
                pcie_device_id=device.vendor_id,
                pcie_vendor_id=device.device_id,
                pcie_subsystem_vendor_id=device.subsystem_vendor_id,
                pcie_subsystem_id=device.subsystem_id,
                device_serial_number=device.serial_number,
                bound_port_id=device.bound_port_id,
                total_capacity=device.total_capacity,
            )
            device_info_list.append(device_info)
        response_payload = GetConnectedDevicesResponsePayload(devices=device_info_list)
        response = self.create_cci_response(response_payload)
        return response

    @classmethod
    def create_cci_request(cls) -> CciRequest:
        cci_request = CciRequest()
        cci_request.opcode = cls.OPCODE
        return cci_request

    @staticmethod
    def create_cci_response(
        response: GetConnectedDevicesResponsePayload,
    ) -> CciResponse:
        cci_response = CciResponse()
        cci_response.payload = response.dump()
        return cci_response

    @staticmethod
    def parse_response_payload(
        payload: bytes,
    ) -> GetConnectedDevicesResponsePayload:
        return GetConnectedDevicesResponsePayload.parse(payload)
