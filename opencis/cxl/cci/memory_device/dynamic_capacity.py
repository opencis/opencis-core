"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

from opencis.cxl.features.mailbox import (
    CxlMailboxContext,
    CxlMailboxCommandBase,
    MAILBOX_RETURN_CODE,
)
from opencis.util.unaligned_bit_structure import UnalignedBitStructure, ByteField, StructureField
from opencis.cxl.device.config.dynamic_capacity_device import (
    RegionConfiguration,
    RegionConfigStruct,
    DynamicCapacityExtentStruct,
)


#
#   GetDynamicCapacityConfig command (Opcode 4800h)
#

REGION_CONFIG_STRUCT_SIZE = 0x28


class GetDynamicCapacityConfigInput(UnalignedBitStructure):
    region_count: int
    starting_region_index: int

    _fields = [
        ByteField("region_count", 0x00, 0x00),
        ByteField("starting_region_index", 0x01, 0x01),
    ]


class GetDynamicCapacityConfigOutput(UnalignedBitStructure):
    num_available_regions: int
    regions_returned: int
    reserved: int
    region_config0: RegionConfigStruct
    region_config1: RegionConfigStruct
    region_config2: RegionConfigStruct
    region_config3: RegionConfigStruct
    region_config4: RegionConfigStruct
    region_config5: RegionConfigStruct
    region_config6: RegionConfigStruct
    region_config7: RegionConfigStruct
    total_supported_extents: int
    num_available_extents: int
    total_supported_tags: int
    num_available_tags: int

    def __init__(self, region_configs: list[RegionConfiguration]):
        self._fields = [
            ByteField("num_available_regions:", 0x00, 0x00),
            ByteField("regions_returned", 0x01, 0x01),
            ByteField("reserved", 0x02, 0x07),
        ]
        start_offset = 0x08
        entry_size = RegionConfigStruct.get_size()
        entry_index = 0
        for _ in region_configs:
            end_offset = start_offset + entry_size - 1
            self._fields.append(
                StructureField(
                    f"region_config_struct{entry_index}",
                    start_offset,
                    end_offset,
                    RegionConfigStruct,
                )
            )
            entry_index += 1
            start_offset += entry_size
        self._fields.append(ByteField("total_supported_extents:", start_offset, start_offset + 3))
        self._fields.append(ByteField("num_available_regions:", start_offset + 4, start_offset + 7))
        self._fields.append(ByteField("total_supported_tags:", start_offset + 8, start_offset + 11))
        self._fields.append(ByteField("num_available_tags:", start_offset + 12, start_offset + 15))

        super().__init__()
        self.num_available_regions = len(region_configs)
        self.regions_returned = len(region_configs)
        for i, config in enumerate(region_configs):
            setattr(self, f"region_config{i}.region_base", config.region_base)
            setattr(self, f"region_config{i}.region_decode_len", config.region_decode_len)
            setattr(self, f"region_config{i}.region_len", config.region_len)
            setattr(self, f"region_config{i}.region_block_size", config.region_block_size)
            setattr(self, f"region_config{i}.dsmad_handle", config.dsmad_handle)
            setattr(self, f"region_config{i}.flags", config.flags)

        # TODO: ACTUAL VALUES NEEDED. WILL NOT WORK WITHOUT IMPLEMENTATION
        self.total_supported_extents = 0
        self.num_available_extents = 0
        self.total_supported_tags = 0
        self.num_available_tags = 0

    @staticmethod
    def get_size(region_config_structs: list[RegionConfigStruct]):
        # pylint: disable=arguments-renamed
        return 8 + RegionConfigStruct.get_size() * len(region_config_structs) + 16


class GetDynamicCapacityConfig(CxlMailboxCommandBase):
    def __init__(self, region_config_structs: list[RegionConfigStruct]):
        super().__init__(0x4800)
        self._region_config_structs = region_config_structs

    def process(self, context: CxlMailboxContext) -> bool:
        payload_length = context.command["payload_length"]
        if payload_length != GetDynamicCapacityConfigInput.get_size():
            context.status["return_code"] = MAILBOX_RETURN_CODE.INVALID_INPUT
            return True

        input_buffer = context.payloads.create_shared(payload_length)
        input = GetDynamicCapacityConfigInput(input_buffer)

        if input.region_count + input.starting_region_index + 1 > len(self._region_config_structs):
            context.status["return_code"] = MAILBOX_RETURN_CODE.INVALID_INPUT
            return True

        # TODO: Implement getting region configurations
        # WILL NOT WORK WITHOUT IMPLEMENTATION
        region_configs = []

        output_bytes = bytes(GetDynamicCapacityConfigOutput(region_configs))
        context.payloads.copy_from(output_bytes)
        context.command["payload_length"] = len(output_bytes)
        return True


#
#   GetDynamicCapacityExtentList command (Opcode 4801h)
#
class GetDynamicCapacityExtentListInput(UnalignedBitStructure):
    extent_count: int
    starting_extent_index: int

    _fields = [
        ByteField("extent_count", 0x00, 0x03),
        ByteField("starting_extent_index", 0x04, 0x07),
    ]


class GetDynamicCapacityExtentListOutput(UnalignedBitStructure):
    returned_extent_count: int
    total_extent_count: int
    extent_list_generation_number: int
    reserved: int
    dc_extent0: DynamicCapacityExtentStruct
    dc_extent1: DynamicCapacityExtentStruct
    dc_extent2: DynamicCapacityExtentStruct
    dc_extent3: DynamicCapacityExtentStruct
    dc_extent4: DynamicCapacityExtentStruct
    dc_extent5: DynamicCapacityExtentStruct
    dc_extent6: DynamicCapacityExtentStruct
    dc_extent7: DynamicCapacityExtentStruct

    def __init__(self, dc_extent_list: list[DynamicCapacityExtentStruct]):
        self._fields = [
            ByteField("returned_extent_count:", 0x00, 0x03),
            ByteField("total_extent_count", 0x04, 0x07),
            ByteField("extent_list_generation_number", 0x08, 0x0B),
            ByteField("reserved", 0x0C, 0x0F),
        ]
        start_offset = 0x10
        entry_size = DynamicCapacityExtentStruct.get_size()
        entry_index = 0
        for _ in dc_extent_list:
            end_offset = start_offset + entry_size - 1
            self._fields.append(
                StructureField(
                    f"dc_extent_struct{entry_index}",
                    start_offset,
                    end_offset,
                    DynamicCapacityExtentStruct,
                )
            )
            entry_index += 1
            start_offset += entry_size

        super().__init__()
        self.returned_extent_count = len(dc_extent_list)
        self.total_extent_count = len(dc_extent_list)

        # TODO: ACTUAL VALUE NEEDED. WILL NOT WORK WITHOUT IMPLEMENTATION.
        self.extent_list_generation_number = 0

        for i, ext in enumerate(dc_extent_list):
            setattr(self, f"dc_extent{i}.start_dpa", ext.start_dpa)
            setattr(self, f"dc_extent{i}.length", ext.length)
            setattr(self, f"dc_extent{i}.tag", ext.tag)
            setattr(self, f"dc_extent{i}.shared_extent_seq", ext.shared_extent_seq)

    @staticmethod
    def get_size(dc_extent_list: list[DynamicCapacityExtentStruct]):
        # pylint: disable=arguments-renamed
        return 0x10 + DynamicCapacityExtentStruct.get_size() * len(dc_extent_list)


class GetDynamicCapacityExtentList(CxlMailboxCommandBase):
    def __init__(self, dc_extent_list: list[DynamicCapacityExtentStruct]):
        super().__init__(0x4801)
        self._dc_extent_list = dc_extent_list

    def process(self, context: CxlMailboxContext) -> bool:
        payload_length = context.command["payload_length"]
        if payload_length != GetDynamicCapacityExtentListInput.get_size():
            context.status["return_code"] = MAILBOX_RETURN_CODE.INVALID_INPUT
            return True

        input_buffer = context.payloads.create_shared(payload_length)
        input = GetDynamicCapacityExtentListInput(input_buffer)

        if input.extent_count + input.starting_extent_index + 1 > len(self._dc_extent_list):
            context.status["return_code"] = MAILBOX_RETURN_CODE.INVALID_INPUT
            return True

        # TODO: Implement getting region configurations
        # WILL NOT WORK WITHOUT IMPLEMENTATION
        extent_list = []

        output_bytes = bytes(GetDynamicCapacityExtentListOutput(extent_list))
        context.payloads.copy_from(output_bytes)
        context.command["payload_length"] = len(output_bytes)
        return True


#
#   AddDynamicCapacityResponse command (Opcode 4802h)
#

UPDATED_EXT_STRUCT_SIZE = 0x18


class UpdatedExtentStruct(UnalignedBitStructure):
    starting_dpa: int
    length: int
    reserved: int

    _fields = [
        ByteField("starting_dpa", 0x00, 0x07),
        ByteField("length", 0x08, 0x0F),
        ByteField("reserved", 0x10, 0x17),
    ]


class AddDynamicCapacityResponseInput(UnalignedBitStructure):
    updated_extent_list_size: int
    flags: int
    reserved: int
    updated_extent0: UpdatedExtentStruct
    updated_extent1: UpdatedExtentStruct
    updated_extent2: UpdatedExtentStruct
    updated_extent3: UpdatedExtentStruct
    updated_extent4: UpdatedExtentStruct
    updated_extent5: UpdatedExtentStruct
    updated_extent6: UpdatedExtentStruct
    updated_extent7: UpdatedExtentStruct

    def __init__(self, updated_ext_list: list[UpdatedExtentStruct]):
        self._fields = [
            ByteField("updated_extent_list_size", 0x00, 0x03),
            ByteField("flags", 0x04, 0x05),
            ByteField("reserved", 0x06, 0x07),
        ]
        start_offset = 0x08
        entry_size = UpdatedExtentStruct.get_size()
        entry_index = 0
        for _ in updated_ext_list:
            end_offset = start_offset + entry_size - 1
            self._fields.append(
                StructureField(
                    f"updated_extent{entry_index}",
                    start_offset,
                    end_offset,
                    UpdatedExtentStruct,
                )
            )
            entry_index += 1
            start_offset += entry_size
        super().__init__()

    @staticmethod
    def get_size(updated_extent_list: list[UpdatedExtentStruct]):
        # pylint: disable=arguments-renamed
        return 0x8 + UPDATED_EXT_STRUCT_SIZE * len(updated_extent_list)


class AddDynamicCapacityResponse(CxlMailboxCommandBase):
    def __init__(self, updated_extent_list: list[UpdatedExtentStruct]):
        super().__init__(0x4802)
        self._updated_extent_list = updated_extent_list

    def process(self, context: CxlMailboxContext) -> bool:
        # TODO: Implement setting updated extents. Unlike the other DCD command definitions,
        # this is a response to "AddCapacityEventRecord", a different command.
        # WILL NOT WORK WITHOUT IMPLEMENTATION
        context.status["return_code"] = MAILBOX_RETURN_CODE.SUCCESS
        return True


#
#   ReleaseDynamicCapacity command (Opcode 4803h)
#


class ReleaseDynamicCapacityInput(UnalignedBitStructure):
    updated_extent_list_size: int
    flags: int
    reserved: int

    _fields = [
        ByteField("updated_extent_list_size", 0x00, 0x03),
        ByteField("flags", 0x04, 0x04),
        ByteField("reserved", 0x05, 0x07),
    ]


class ReleaseDynamicCapacity(CxlMailboxCommandBase):
    def __init__(self, updated_extent_list: list[UpdatedExtentStruct]):
        super().__init__(0x4803)
        self._updated_extent_list = updated_extent_list

    def process(self, context: CxlMailboxContext) -> bool:
        # TODO: Implement setting updated extents. Unlike the other DCD command definitions,
        # this is a response to "Release "ReleaseCapacityEventRecord", a different command.
        # WILL NOT WORK WITHOUT IMPLEMENTATION
        context.status["return_code"] = MAILBOX_RETURN_CODE.SUCCESS
        return True
