"""
 Copyright (c) 2024, Eeum, Inc.

 This software is licensed under the terms of the Revised BSD License.
 See LICENSE for details.
"""

from typing import TypedDict


class EventStatus(TypedDict):
    # pylint: disable=duplicate-code
    informational_event_log: int
    warning_event_log: int
    failure_event_log: int
    fatal_event_log: int
    dynamic_capacity_event_log: int


class InterruptPolicy(TypedDict):
    # pylint: disable=duplicate-code
    informational_event_log_interrupt_settings: int
    warning_event_log_interrupt_settings: int
    failure_event_log_interrupt_settings: int
    fatal_event_log_interrupt_settings: int
    dynamic_capacity_event_log_interrupt_settings: int


class EventManager:
    def __init__(self) -> None:
        self._interrupt_policy = InterruptPolicy(
            informational_event_log_interrupt_settings=0,
            warning_event_log_interrupt_settings=0,
            failure_event_log_interrupt_settings=0,
            fatal_event_log_interrupt_settings=0,
            dynamic_capacity_event_log_interrupt_settings=0,
        )

    def get_status(self) -> EventStatus:
        status = EventStatus()
        return status

    def set_interrupt_policy(self, policy: InterruptPolicy):
        for key, value in policy.items():
            self._interrupt_policy[key] = value

    def get_interrupt_policy(self) -> InterruptPolicy:
        return self._interrupt_policy.copy()
