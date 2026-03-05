"""
Tests for Pulse Mode Digital Output execution in ControlExecutor.

Covers:
- Group 1: Normal mode — backward compatibility
- Group 2: Pulse execution — happy path
- Group 3: Logging
- Group 4: PulseConfig schema validation
- Group 5: Concurrency — overlap prevention
- Group 6: Priority protection integration
"""
import asyncio
from unittest.mock import AsyncMock, Mock, call, patch

import pytest
from pydantic import ValidationError

from core.executor.control_executor import ControlExecutor
from core.schema.control_condition_schema import ControlActionSchema, ControlActionType, PulseConfig


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_pulse_action(
    start_value: int = 1,
    end_value: int = 0,
    duration_ms: int = 500,
    target: str = "DO_01",
    model: str = "DO_MODULE",
    slave_id: str = "3",
    priority: int = 10,
) -> ControlActionSchema:
    return ControlActionSchema(
        model=model,
        slave_id=slave_id,
        type=ControlActionType.WRITE_DO,
        target=target,
        value=start_value,
        priority=priority,
        switch_mode="pulse",
        pulse=PulseConfig(start_value=start_value, end_value=end_value, duration_ms=duration_ms),
    )


def _make_do_device(model: str = "DO_MODULE", slave_id: str = "3", targets: list[str] | None = None) -> Mock:
    device = Mock()
    device.model = model
    device.slave_id = slave_id
    targets = targets or ["DO_01", "DO_02"]
    device.register_map = {t: {"writable": True} for t in targets}
    device.write_value = AsyncMock()
    device.read_value = AsyncMock(return_value=0)
    return device


# ===========================================================================
# Group 1: Normal mode — backward compatibility
# ===========================================================================

class TestNormalModeBackwardCompatibility:

    @pytest.mark.asyncio
    async def test_when_switch_mode_omitted_then_single_write_no_sleep(
        self, control_executor, mock_device_manager
    ):
        """switch_mode not provided → normal path, asyncio.sleep never called"""
        device = _make_do_device()
        mock_device_manager.get_device_by_model_and_slave_id.return_value = device
        device.read_value.return_value = 0

        action = ControlActionSchema(
            model="DO_MODULE",
            slave_id="3",
            type=ControlActionType.WRITE_DO,
            target="DO_01",
            value=1,
        )

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await control_executor.execute([action])

        device.write_value.assert_called_once_with("DO_01", 1)
        mock_sleep.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_switch_mode_normal_then_single_write_no_sleep(
        self, control_executor, mock_device_manager
    ):
        """switch_mode='normal' → normal path, asyncio.sleep never called"""
        device = _make_do_device()
        mock_device_manager.get_device_by_model_and_slave_id.return_value = device
        device.read_value.return_value = 0

        action = ControlActionSchema(
            model="DO_MODULE",
            slave_id="3",
            type=ControlActionType.WRITE_DO,
            target="DO_01",
            value=1,
            switch_mode="normal",
        )

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await control_executor.execute([action])

        device.write_value.assert_called_once_with("DO_01", 1)
        mock_sleep.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_switch_mode_pulse_but_pulse_config_none_then_fallback_to_single_write(
        self, control_executor, mock_device_manager, caplog
    ):
        """switch_mode='pulse' but pulse=None → log warning + fallback to normal write"""
        device = _make_do_device()
        mock_device_manager.get_device_by_model_and_slave_id.return_value = device
        device.read_value.return_value = 0

        action = Mock(spec=ControlActionSchema)
        action.model = "DO_MODULE"
        action.slave_id = "3"
        action.type = ControlActionType.WRITE_DO
        action.target = "DO_01"
        action.value = 1
        action.priority = 10
        action.reason = "[TEST] reason"
        action.switch_mode = "pulse"
        action.pulse = None
        action.emergency_override = False

        import logging
        with caplog.at_level(logging.WARNING):
            await control_executor.execute([action])

        assert any("pulse config is None" in r.message or "falling back" in r.message for r in caplog.records)
        device.write_value.assert_called_once_with("DO_01", 1)


# ===========================================================================
# Group 2: Pulse execution — happy path
# ===========================================================================

class TestPulseExecutionHappyPath:

    @pytest.mark.asyncio
    async def test_when_valid_pulse_config_then_write_value_called_twice(
        self, control_executor, mock_device_manager
    ):
        """Valid pulse config → write_value called exactly twice"""
        device = _make_do_device()
        mock_device_manager.get_device_by_model_and_slave_id.return_value = device

        action = _make_pulse_action(start_value=1, end_value=0, duration_ms=500)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await control_executor.execute([action])

        assert device.write_value.call_count == 2

    @pytest.mark.asyncio
    async def test_when_duration_ms_500_then_sleep_called_with_0_5(
        self, control_executor, mock_device_manager
    ):
        """duration_ms=500 → asyncio.sleep(0.5)"""
        device = _make_do_device()
        mock_device_manager.get_device_by_model_and_slave_id.return_value = device

        action = _make_pulse_action(duration_ms=500)

        with patch("core.executor.control_executor.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await control_executor.execute([action])

        mock_sleep.assert_called_once_with(0.5)

    @pytest.mark.asyncio
    async def test_when_duration_ms_800_then_sleep_called_with_0_8(
        self, control_executor, mock_device_manager
    ):
        """duration_ms=800 → asyncio.sleep(0.8)"""
        device = _make_do_device()
        mock_device_manager.get_device_by_model_and_slave_id.return_value = device

        action = _make_pulse_action(duration_ms=800)

        with patch("core.executor.control_executor.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await control_executor.execute([action])

        mock_sleep.assert_called_once_with(0.8)

    @pytest.mark.asyncio
    async def test_when_start_1_end_0_then_writes_1_then_0(
        self, control_executor, mock_device_manager
    ):
        """start_value=1, end_value=0 → first write is 1, second write is 0"""
        device = _make_do_device()
        mock_device_manager.get_device_by_model_and_slave_id.return_value = device

        action = _make_pulse_action(start_value=1, end_value=0)

        with patch("core.executor.control_executor.asyncio.sleep", new_callable=AsyncMock):
            await control_executor.execute([action])

        assert device.write_value.call_args_list == [call("DO_01", 1), call("DO_01", 0)]

    @pytest.mark.asyncio
    async def test_when_start_0_end_1_then_writes_0_then_1(
        self, control_executor, mock_device_manager
    ):
        """start_value=0, end_value=1 → first write is 0, second write is 1"""
        device = _make_do_device()
        mock_device_manager.get_device_by_model_and_slave_id.return_value = device

        action = _make_pulse_action(start_value=0, end_value=1)

        with patch("core.executor.control_executor.asyncio.sleep", new_callable=AsyncMock):
            await control_executor.execute([action])

        assert device.write_value.call_args_list == [call("DO_01", 0), call("DO_01", 1)]


# ===========================================================================
# Group 3: Logging
# ===========================================================================

class TestPulseLogging:

    @pytest.mark.asyncio
    async def test_when_pulse_starts_then_log_contains_pulse_start_device_target_start_value(
        self, control_executor, mock_device_manager, caplog
    ):
        """Pulse start log must contain 'Pulse start', device model, target, start_value"""
        device = _make_do_device()
        mock_device_manager.get_device_by_model_and_slave_id.return_value = device

        action = _make_pulse_action(start_value=1, end_value=0, target="DO_01")

        import logging
        with patch("core.executor.control_executor.asyncio.sleep", new_callable=AsyncMock):
            with caplog.at_level(logging.INFO):
                await control_executor.execute([action])

        start_logs = [r.message for r in caplog.records if "Pulse start" in r.message]
        assert start_logs, "Expected at least one 'Pulse start' log message"
        log_msg = start_logs[0]
        assert "DO_MODULE" in log_msg
        assert "DO_01" in log_msg
        assert "1" in log_msg

    @pytest.mark.asyncio
    async def test_when_pulse_sleeping_then_log_contains_pulse_sleep_and_duration(
        self, control_executor, mock_device_manager, caplog
    ):
        """Pulse sleep log must contain 'Pulse sleep' and duration_ms value"""
        device = _make_do_device()
        mock_device_manager.get_device_by_model_and_slave_id.return_value = device

        action = _make_pulse_action(duration_ms=750)

        import logging
        with patch("core.executor.control_executor.asyncio.sleep", new_callable=AsyncMock):
            with caplog.at_level(logging.INFO):
                await control_executor.execute([action])

        sleep_logs = [r.message for r in caplog.records if "Pulse sleep" in r.message]
        assert sleep_logs, "Expected at least one 'Pulse sleep' log message"
        assert "750" in sleep_logs[0]

    @pytest.mark.asyncio
    async def test_when_pulse_ends_then_log_contains_pulse_end_device_target_end_value(
        self, control_executor, mock_device_manager, caplog
    ):
        """Pulse end log must contain 'Pulse end', device model, target, end_value"""
        device = _make_do_device()
        mock_device_manager.get_device_by_model_and_slave_id.return_value = device

        action = _make_pulse_action(start_value=1, end_value=0, target="DO_01")

        import logging
        with patch("core.executor.control_executor.asyncio.sleep", new_callable=AsyncMock):
            with caplog.at_level(logging.INFO):
                await control_executor.execute([action])

        end_logs = [r.message for r in caplog.records if "Pulse end" in r.message]
        assert end_logs, "Expected at least one 'Pulse end' log message"
        log_msg = end_logs[0]
        assert "DO_MODULE" in log_msg
        assert "DO_01" in log_msg
        assert "0" in log_msg


# ===========================================================================
# Group 4: PulseConfig schema validation
# ===========================================================================

class TestPulseConfigValidation:

    def test_when_duration_ms_49_then_validation_error(self):
        with pytest.raises(ValidationError):
            PulseConfig(start_value=1, end_value=0, duration_ms=49)

    def test_when_duration_ms_5001_then_validation_error(self):
        with pytest.raises(ValidationError):
            PulseConfig(start_value=1, end_value=0, duration_ms=5001)

    def test_when_duration_ms_50_then_valid_boundary(self):
        cfg = PulseConfig(start_value=1, end_value=0, duration_ms=50)
        assert cfg.duration_ms == 50

    def test_when_duration_ms_5000_then_valid_boundary(self):
        cfg = PulseConfig(start_value=1, end_value=0, duration_ms=5000)
        assert cfg.duration_ms == 5000

    def test_when_start_value_equals_end_value_1_then_validation_error(self):
        with pytest.raises(ValidationError):
            PulseConfig(start_value=1, end_value=1, duration_ms=500)

    def test_when_start_value_equals_end_value_0_then_validation_error(self):
        with pytest.raises(ValidationError):
            PulseConfig(start_value=0, end_value=0, duration_ms=500)

    def test_when_start_value_2_then_validation_error(self):
        with pytest.raises(ValidationError):
            PulseConfig(start_value=2, end_value=0, duration_ms=500)

    def test_when_end_value_negative_1_then_validation_error(self):
        with pytest.raises(ValidationError):
            PulseConfig(start_value=1, end_value=-1, duration_ms=500)


# ===========================================================================
# Group 5: Concurrency — overlap prevention
# ===========================================================================

class TestPulseConcurrency:

    @pytest.mark.asyncio
    async def test_when_same_device_target_receives_two_pulses_concurrently_then_second_waits_for_first(
        self, control_executor, mock_device_manager
    ):
        """Same device+target: two concurrent pulses → second waits for first (lock behavior)"""
        device = _make_do_device()
        mock_device_manager.get_device_by_model_and_slave_id.return_value = device

        call_order: list[str] = []

        async def fake_write(target, value):
            call_order.append(f"write_{target}_{value}")

        # Save real sleep before patching to avoid recursive mock calls
        _real_sleep = asyncio.sleep

        async def fake_sleep(seconds):
            call_order.append(f"sleep_{seconds}")
            await _real_sleep(0)  # yield control using real sleep

        device.write_value.side_effect = fake_write

        action1 = _make_pulse_action(start_value=1, end_value=0, duration_ms=100, target="DO_01")
        action2 = _make_pulse_action(start_value=1, end_value=0, duration_ms=100, target="DO_01")

        with patch.object(asyncio, "sleep", side_effect=fake_sleep):
            await asyncio.gather(
                control_executor._execute_pulse_do(action1, device, {}),
                control_executor._execute_pulse_do(action2, device, {}),
            )

        # Both pulses should complete: 4 writes and 2 sleeps total
        assert call_order.count("write_DO_01_1") == 2
        assert call_order.count("write_DO_01_0") == 2
        assert call_order.count("sleep_0.1") == 2

        # The lock ensures sequences don't interleave:
        # First pulse's end write must come before second pulse's start write
        first_start = call_order.index("write_DO_01_1")
        first_sleep = call_order.index("sleep_0.1")
        first_end = call_order.index("write_DO_01_0")
        assert first_start < first_sleep < first_end

    @pytest.mark.asyncio
    async def test_when_different_device_target_receives_pulses_concurrently_then_both_execute_independently(
        self, control_executor, mock_device_manager
    ):
        """Different device+target: concurrent pulses execute in parallel without blocking"""
        device1 = _make_do_device(model="DO_MODULE", slave_id="3", targets=["DO_01"])
        device2 = _make_do_device(model="DO_MODULE", slave_id="4", targets=["DO_02"])

        mock_device_manager.get_device_by_model_and_slave_id.side_effect = [device1, device2]

        action1 = _make_pulse_action(start_value=1, end_value=0, target="DO_01", model="DO_MODULE", slave_id="3")
        action2 = _make_pulse_action(start_value=1, end_value=0, target="DO_02", model="DO_MODULE", slave_id="4")

        with patch("core.executor.control_executor.asyncio.sleep", new_callable=AsyncMock):
            await asyncio.gather(
                control_executor._execute_pulse_do(action1, device1, {}),
                control_executor._execute_pulse_do(action2, device2, {}),
            )

        # Both devices should have received their writes independently
        assert device1.write_value.call_count == 2
        assert device2.write_value.call_count == 2
        device1.write_value.assert_any_call("DO_01", 1)
        device1.write_value.assert_any_call("DO_01", 0)
        device2.write_value.assert_any_call("DO_02", 1)
        device2.write_value.assert_any_call("DO_02", 0)


# ===========================================================================
# Group 6: Priority protection integration
# ===========================================================================

class TestPulsePriorityProtection:

    @pytest.mark.asyncio
    async def test_when_target_protected_by_higher_priority_then_pulse_skipped(
        self, control_executor, mock_device_manager
    ):
        """Higher priority written_target → pulse is entirely skipped (write_value never called)"""
        from core.model.control_execution import WrittenTarget

        device = _make_do_device()
        mock_device_manager.get_device_by_model_and_slave_id.return_value = device

        target_key = f"DO_MODULE_3_DO_01"
        written_targets = {
            target_key: WrittenTarget(value=0, priority=1, rule_code="HIGH_PRIO_RULE")
        }

        action = _make_pulse_action(start_value=1, end_value=0, priority=10)

        with patch("core.executor.control_executor.asyncio.sleep", new_callable=AsyncMock):
            await control_executor._execute_pulse_do(action, device, written_targets)

        device.write_value.assert_not_called()

    @pytest.mark.asyncio
    async def test_when_pulse_has_higher_priority_than_existing_target_then_pulse_proceeds(
        self, control_executor, mock_device_manager
    ):
        """Pulse action has higher priority → pulse proceeds and both writes execute"""
        from core.model.control_execution import WrittenTarget

        device = _make_do_device()
        mock_device_manager.get_device_by_model_and_slave_id.return_value = device

        target_key = f"DO_MODULE_3_DO_01"
        written_targets = {
            target_key: WrittenTarget(value=0, priority=50, rule_code="LOW_PRIO_RULE")
        }

        action = _make_pulse_action(start_value=1, end_value=0, priority=5)

        with patch("core.executor.control_executor.asyncio.sleep", new_callable=AsyncMock):
            await control_executor._execute_pulse_do(action, device, written_targets)

        assert device.write_value.call_count == 2
        assert device.write_value.call_args_list == [call("DO_01", 1), call("DO_01", 0)]
