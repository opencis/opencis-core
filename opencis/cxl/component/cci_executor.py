"""
Copyright (c) 2024-2025, Eeum, Inc.

This software is licensed under the terms of the Revised BSD License.
See LICENSE for details.
"""

from abc import abstractmethod
from asyncio import Condition
from dataclasses import dataclass, field
import traceback
from typing import Dict, Optional, Callable, Awaitable, cast

from opencis.cxl.cci.common import CCI_RETURN_CODE, get_opcode_string
from opencis.util.component import LabeledComponent, RunnableComponent
from opencis.util.logger import logger


@dataclass
class CciRequest:
    opcode: int = 0
    payload: bytes = field(default_factory=bytes)


@dataclass
class CciResponse:
    bo_flag: bool = False
    return_code: CCI_RETURN_CODE = CCI_RETURN_CODE.SUCCESS
    vendor_specific_status: int = 0
    payload: bytes = field(default_factory=bytes)


@dataclass
class CciBackgroundStatus:
    opcode: int = 0
    percentage_complete: int = 0
    return_code: int = 0
    vendor_specific_status: int = 0


ProgressCallback = Callable[[int], Awaitable[None]]


class CciCommand(LabeledComponent):
    def __init__(self, opcode: int, is_background: bool, label: Optional[str] = None):
        super().__init__(label)
        self._opcode = opcode
        self._is_background = is_background

    def is_background(self) -> bool:
        return self._is_background

    def get_opcode(self) -> int:
        return self._opcode


class CciForegroundCommand(CciCommand):
    def __init__(self, opcode: int, label: Optional[str] = None):
        super().__init__(opcode, is_background=False, label=label)

    async def execute(self, request: CciRequest) -> CciResponse:
        try:
            return await self._execute(request)
        except Exception as e:
            logger.error(
                self._create_message(
                    f"{self.__class__.__name__} error: {str(e)}, {traceback.format_exc()}"
                )
            )
            response = CciResponse(bo_flag=False, return_code=CCI_RETURN_CODE.INTERNAL_ERROR)
            return response

    @abstractmethod
    async def _execute(self, request: CciRequest) -> CciResponse:
        """This must be implemented in the child class"""


class CciBackgroundCommand(CciCommand):
    def __init__(self, opcode: int, label: Optional[str] = None):
        super().__init__(opcode, is_background=True, label=label)

    async def execute(self, request: CciRequest, callback: ProgressCallback) -> CciResponse:
        try:
            return await self._execute(request, callback)
        except Exception as e:
            logger.error(
                self._create_message(
                    f"{self.__class__.__name__} error: {str(e)}, {traceback.format_exc()}"
                )
            )
            await callback(100)
            response = CciResponse(return_code=CCI_RETURN_CODE.INTERNAL_ERROR)
            return response

    @abstractmethod
    async def _execute(self, request: CciRequest, callback: ProgressCallback) -> CciResponse:
        """This must be implemented in the child class"""


@dataclass
class CciCommandSlot:
    command: Optional[CciBackgroundCommand] = None
    request: CciRequest = field(default_factory=CciRequest)
    response: CciResponse = field(default_factory=CciResponse)
    percentage_complete: int = 0


class CciExecutor(RunnableComponent):
    def __init__(self, label: Optional[str] = None) -> None:
        super().__init__(label)
        self._commands: Dict[int, CciCommand] = {}
        self._background_command_slot = CciCommandSlot()
        self._background_command_condition = Condition()
        self._running = True

    def register_command(self, opcode: int, command_instance: CciCommand) -> None:
        self._commands[opcode] = command_instance

    async def execute_command(self, request: CciRequest) -> CciResponse:
        command = self._commands.get(request.opcode)
        opcode_string = get_opcode_string(request.opcode)
        if not command:
            logger.debug(self._create_message(f"Received unsupported command {opcode_string}"))
            return CciResponse(return_code=CCI_RETURN_CODE.UNSUPPORTED)

        if command.is_background():
            logger.debug(self._create_message(f"Received background command {opcode_string}"))
            background_command = cast(CciBackgroundCommand, command)
            response = await self._submit_background_command(background_command, request)
        else:
            logger.debug(self._create_message(f"Received command {opcode_string}"))
            foreground_command = cast(CciForegroundCommand, command)
            response = await foreground_command.execute(request)
            return_code_str = CCI_RETURN_CODE(response.return_code).name
            logger.debug(self._create_message(f"Command Return Status: {return_code_str}"))
        return response

    async def _submit_background_command(
        self, command: CciBackgroundCommand, request: CciRequest
    ) -> CciResponse:
        await self._condition.acquire()
        if self._background_command_slot.command is not None:
            self._condition.release()
            return CciResponse(bo_flag=True, return_code=CCI_RETURN_CODE.BUSY)
        self._background_command_slot.command = command
        self._background_command_slot.request = request
        self._background_command_slot.response = CciResponse()
        self._background_command_slot.percentage_complete = 0
        self._condition.notify_all()
        self._condition.release()
        return CciResponse(bo_flag=True, return_code=CCI_RETURN_CODE.BACKGROUND_COMMAND_STARTED)

    async def get_background_command_status(self) -> CciBackgroundStatus:
        await self._condition.acquire()
        opcode = self._background_command_slot.request.opcode
        percentage_complete = self._background_command_slot.percentage_complete
        return_code = self._background_command_slot.response.return_code
        vendor_specific_status = self._background_command_slot.response.vendor_specific_status
        self._condition.release()
        return CciBackgroundStatus(opcode, percentage_complete, return_code, vendor_specific_status)

    async def _process_background_command(self):
        while self._running:
            await self._condition.acquire()
            while self._background_command_slot.command is None:
                await self._condition.wait()

            command = self._background_command_slot.command
            request = self._background_command_slot.request
            self._condition.release()

            async def update_progress(progress: int):
                await self._condition.acquire()
                self._background_command_slot.percentage_complete = progress
                self._condition.release()

            response = await command.execute(request, update_progress)
            await self._condition.acquire()
            self._background_command_slot.percentage_complete = 100
            self._background_command_slot.response = response
            self._background_command_slot.command = None
            self._condition.release()

    async def _run(self):
        await self._change_status_to_running()
        await self._process_background_command()

    async def _stop(self):
        self._running = False
