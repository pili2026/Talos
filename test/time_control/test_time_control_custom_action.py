"""
Unit tests for the on_action / off_action custom-action feature in the Talos
time control system.

Coverage:
  AC6  — Schema: on_action / off_action are optional fields on DeviceSchedule
  AC1  — Evaluator: get_custom_actions returns the right list for TURN_ON / TURN_OFF
  AC2  — Evaluator: get_custom_actions returns None when nothing is configured
  AC3  — Handler: falls back to standard TURN_ON / TURN_OFF when no custom action
  AC4  — Executor: send_custom_actions publishes with correct metadata
  AC5  — Executor/Handler: offline path defers custom actions; flushed on recovery
"""

from __future__ import annotations

from datetime import time
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from core.evaluator.time_evalutor import TimeControlEvaluator
from core.executor.time_control_executor import TimeControlExecutor
from core.handler.time_control_handler import TimeControlHandler
from core.schema.control_condition_schema import ControlActionSchema, ControlActionType
from core.schema.time_control_schema import DeviceSchedule, TimeControlConfig, TimeInterval


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_action(action_type: ControlActionType = ControlActionType.TURN_ON) -> ControlActionSchema:
    return ControlActionSchema(model="INV", slave_id="1", type=action_type)


def _make_evaluator_with_custom(on_actions=None, off_actions=None) -> TimeControlEvaluator:
    """Return a real evaluator whose DEVICE_1 schedule has optional custom actions."""
    cfg = TimeControlConfig(
        timezone="Asia/Taipei",
        work_hours={
            "DEVICE_1": DeviceSchedule(
                weekdays={1, 2, 3, 4, 5},
                intervals=[TimeInterval(start=time.fromisoformat("08:00"), end=time.fromisoformat("18:00"))],
                on_action=on_actions,
                off_action=off_actions,
            ),
        },
    )
    return TimeControlEvaluator(cfg)


def _make_handler(evaluator=None, executor=None, pubsub=None):
    """Return a TimeControlHandler wired with mocks or provided objects."""
    pubsub = pubsub or MagicMock()
    pubsub.publish = AsyncMock()
    evaluator = evaluator or MagicMock()
    executor = executor or MagicMock()
    handler = TimeControlHandler(
        pubsub=pubsub,
        time_control_evaluator=evaluator,
        executor=executor,
    )
    return handler, evaluator, executor, pubsub


def _make_executor() -> tuple[TimeControlExecutor, MagicMock]:
    """Return a real executor wired with a mock pubsub."""
    pubsub = MagicMock()
    pubsub.publish = AsyncMock()
    cap = MagicMock()
    cap.supports_on_off.return_value = True
    executor = TimeControlExecutor(pubsub=pubsub, capability_resolver=cap)
    return executor, pubsub


# ---------------------------------------------------------------------------
# Schema tests (AC6)
# ---------------------------------------------------------------------------

class TestDeviceScheduleCustomActionFields:

    def test_device_schedule_on_action_is_optional(self):
        schedule = DeviceSchedule(
            weekdays={1},
            intervals=[TimeInterval(start=time.fromisoformat("09:00"), end=time.fromisoformat("17:00"))],
        )
        assert schedule.on_action is None

    def test_device_schedule_off_action_is_optional(self):
        schedule = DeviceSchedule(
            weekdays={1},
            intervals=[TimeInterval(start=time.fromisoformat("09:00"), end=time.fromisoformat("17:00"))],
        )
        assert schedule.off_action is None

    def test_device_schedule_on_action_validates_as_control_action_schema(self):
        action = _make_action(ControlActionType.TURN_ON)
        schedule = DeviceSchedule(
            weekdays={1},
            intervals=[TimeInterval(start=time.fromisoformat("09:00"), end=time.fromisoformat("17:00"))],
            on_action=[action],
        )
        assert len(schedule.on_action) == 1
        assert schedule.on_action[0].type == ControlActionType.TURN_ON


# ---------------------------------------------------------------------------
# Evaluator tests (AC1, AC2)
# ---------------------------------------------------------------------------

class TestGetCustomActions:

    def test_get_custom_actions_returns_on_action_when_turn_on(self):
        action = _make_action(ControlActionType.TURN_ON)
        evaluator = _make_evaluator_with_custom(on_actions=[action])
        result = evaluator.get_custom_actions("DEVICE_1", ControlActionType.TURN_ON)
        assert result == [action]

    def test_get_custom_actions_returns_off_action_when_turn_off(self):
        action = _make_action(ControlActionType.TURN_OFF)
        evaluator = _make_evaluator_with_custom(off_actions=[action])
        result = evaluator.get_custom_actions("DEVICE_1", ControlActionType.TURN_OFF)
        assert result == [action]

    def test_get_custom_actions_returns_none_when_not_configured(self):
        evaluator = _make_evaluator_with_custom()  # no on_action / off_action
        assert evaluator.get_custom_actions("DEVICE_1", ControlActionType.TURN_ON) is None
        assert evaluator.get_custom_actions("DEVICE_1", ControlActionType.TURN_OFF) is None

    def test_get_custom_actions_returns_none_for_unknown_device(self):
        evaluator = _make_evaluator_with_custom(on_actions=[_make_action()])
        # "UNKNOWN" is not in work_hours and there is no "default" key → schedule is None
        result = evaluator.get_custom_actions("UNKNOWN", ControlActionType.TURN_ON)
        assert result is None


# ---------------------------------------------------------------------------
# Executor tests (AC4, AC5)
# ---------------------------------------------------------------------------

class TestSendCustomActions:

    @pytest.mark.asyncio
    async def test_send_custom_actions_publishes_all_actions(self):
        executor, pubsub = _make_executor()
        actions = [_make_action(ControlActionType.TURN_ON), _make_action(ControlActionType.TURN_ON)]
        await executor.send_custom_actions("DEV_1", actions, "test reason")
        assert pubsub.publish.call_count == 2

    @pytest.mark.asyncio
    async def test_send_custom_actions_sets_action_origin_and_reason(self):
        executor, pubsub = _make_executor()
        action = _make_action(ControlActionType.TURN_ON)
        await executor.send_custom_actions("DEV_1", [action], "my reason")
        assert action.action_origin == "TimeControl"
        assert action.reason == "my reason"


class TestDeferCustomActions:

    @pytest.mark.asyncio
    async def test_defer_custom_actions_stores_pending(self):
        executor, _ = _make_executor()
        actions = [_make_action()]
        await executor.defer_custom_actions("DEV_1", actions, "offline")
        assert "DEV_1" in executor._pending
        assert "custom" in executor._pending["DEV_1"]
        assert executor._pending["DEV_1"]["custom"].custom_actions == actions

    @pytest.mark.asyncio
    async def test_on_device_recovered_flushes_custom_actions(self):
        executor, pubsub = _make_executor()
        action = _make_action(ControlActionType.TURN_ON)
        await executor.defer_custom_actions("DEV_1", [action], "offline")
        await executor.on_device_recovered("DEV_1")
        # The custom action should have been published
        assert pubsub.publish.call_count == 1
        # Pending should be cleared
        assert "DEV_1" not in executor._pending

    @pytest.mark.asyncio
    async def test_on_device_recovered_falls_back_to_send_control_when_no_custom_actions(self):
        executor, pubsub = _make_executor()
        await executor.defer_control("DEV_1", "INV", 1, ControlActionType.TURN_ON, "offline")
        await executor.on_device_recovered("DEV_1")
        # send_control ultimately publishes via pubsub
        assert pubsub.publish.call_count == 1
        assert "DEV_1" not in executor._pending


# ---------------------------------------------------------------------------
# Handler tests (AC1, AC2, AC3, AC5)
# ---------------------------------------------------------------------------

def _online_snapshot(device_type: str = "inverter") -> dict:
    return {"device_id": "INV_1", "slave_id": "1", "is_online": True, "type": device_type}


def _offline_snapshot(device_type: str = "inverter") -> dict:
    return {"device_id": "INV_1", "slave_id": "1", "is_online": False, "type": device_type}


class TestHandleSnapshotCustomActions:

    @pytest.mark.asyncio
    async def test_handle_snapshot_executes_on_action_on_turn_on(self):
        custom_action = _make_action(ControlActionType.TURN_ON)
        evaluator = MagicMock()
        evaluator.evaluate_action.return_value = ControlActionType.TURN_ON
        evaluator.get_custom_actions.return_value = [custom_action]
        evaluator.allow.return_value = True
        executor = MagicMock()
        executor.send_custom_actions = AsyncMock()
        executor.on_device_recovered = AsyncMock()
        handler, _, _, _ = _make_handler(evaluator=evaluator, executor=executor)

        await handler.handle_snapshot(_online_snapshot())

        executor.send_custom_actions.assert_awaited_once_with("INV_1", [custom_action], "On timezone auto startup")

    @pytest.mark.asyncio
    async def test_handle_snapshot_executes_off_action_on_turn_off(self):
        custom_action = _make_action(ControlActionType.TURN_OFF)
        evaluator = MagicMock()
        evaluator.evaluate_action.return_value = ControlActionType.TURN_OFF
        evaluator.get_custom_actions.return_value = [custom_action]
        evaluator.allow.return_value = False
        executor = MagicMock()
        executor.send_custom_actions = AsyncMock()
        executor.on_device_recovered = AsyncMock()
        handler, _, _, pubsub = _make_handler(evaluator=evaluator, executor=executor)

        await handler.handle_snapshot(_online_snapshot())

        executor.send_custom_actions.assert_awaited_once_with("INV_1", [custom_action], "Off timezone auto shutdown")
        # TURN_OFF with custom actions → should return early (no snapshot publish)
        pubsub.publish.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_handle_snapshot_skips_supports_switch_when_custom_action_configured(self):
        """Custom action path must not call _supports_switch (i.e. device type is irrelevant)."""
        custom_action = _make_action(ControlActionType.TURN_ON)
        evaluator = MagicMock()
        evaluator.evaluate_action.return_value = ControlActionType.TURN_ON
        evaluator.get_custom_actions.return_value = [custom_action]
        evaluator.allow.return_value = True
        executor = MagicMock()
        executor.send_custom_actions = AsyncMock()
        executor.on_device_recovered = AsyncMock()
        handler, _, _, _ = _make_handler(evaluator=evaluator, executor=executor)

        # Use a device type that would normally be rejected by _supports_switch
        await handler.handle_snapshot({
            "device_id": "INV_1", "slave_id": "1", "is_online": True, "type": "unknown_type"
        })

        # Custom action should still be sent despite unknown device type
        executor.send_custom_actions.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_snapshot_falls_back_to_turn_on_when_no_on_action(self):
        """AC3: no on_action → standard send_control(TURN_ON) path."""
        evaluator = MagicMock()
        evaluator.evaluate_action.return_value = ControlActionType.TURN_ON
        evaluator.get_custom_actions.return_value = None
        evaluator.allow.return_value = True
        executor = MagicMock()
        executor.send_control = AsyncMock()
        executor.on_device_recovered = AsyncMock()
        handler, _, _, _ = _make_handler(evaluator=evaluator, executor=executor)

        await handler.handle_snapshot(_online_snapshot())

        executor.send_control.assert_awaited_once_with(
            "INV_1", "INV", 1, ControlActionType.TURN_ON, "On timezone auto startup"
        )

    @pytest.mark.asyncio
    async def test_handle_snapshot_falls_back_to_turn_off_when_no_off_action(self):
        """AC3: no off_action → standard send_control(TURN_OFF) path."""
        evaluator = MagicMock()
        evaluator.evaluate_action.return_value = ControlActionType.TURN_OFF
        evaluator.get_custom_actions.return_value = None
        evaluator.allow.return_value = False
        executor = MagicMock()
        executor.send_control = AsyncMock()
        executor.on_device_recovered = AsyncMock()
        handler, _, _, _ = _make_handler(evaluator=evaluator, executor=executor)

        await handler.handle_snapshot(_online_snapshot())

        executor.send_control.assert_awaited_once_with(
            "INV_1", "INV", 1, ControlActionType.TURN_OFF, "Off timezone auto shutdown"
        )

    @pytest.mark.asyncio
    async def test_handle_snapshot_defers_custom_action_when_offline(self):
        """AC5: offline device with custom action → defer_custom_actions called."""
        custom_action = _make_action(ControlActionType.TURN_ON)
        evaluator = MagicMock()
        evaluator.evaluate_action.return_value = ControlActionType.TURN_ON
        evaluator.get_custom_actions.return_value = [custom_action]
        evaluator.allow.return_value = False
        executor = MagicMock()
        executor.defer_custom_actions = AsyncMock()
        executor.on_device_recovered = AsyncMock()
        handler, _, _, _ = _make_handler(evaluator=evaluator, executor=executor)

        await handler.handle_snapshot(_offline_snapshot())

        executor.defer_custom_actions.assert_awaited_once_with(
            "INV_1", [custom_action], "On timezone auto startup"
        )
