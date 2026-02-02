from datetime import datetime
from unittest.mock import patch

import pytest

from core.evaluator.control_evaluator import ControlEvaluator
from core.schema.constraint_schema import ConstraintConfigSchema
from core.schema.control_condition_schema import ConditionSchema, ControlActionSchema, TimeRange
from core.schema.control_config_schema import ControlConfig
from core.util.time_util import TIMEZONE_INFO


def _now(y, m, d, hh, mm, ss=0):
    return datetime(y, m, d, hh, mm, ss, tzinfo=TIMEZONE_INFO)


class TestTimeRangeCheck:
    """Tests for the _is_time_active() method"""

    @pytest.fixture
    def evaluator(self):
        """Create a minimal evaluator"""
        config = ControlConfig(version="1.0.0", root={})
        constraint = ConstraintConfigSchema(version="1.0.0", devices={})
        return ControlEvaluator(config, constraint)

    def _min_action(self):
        return ControlActionSchema(
            type="turn_off",
            model="TECO_VFD",
            slave_id="1",
        )

    def test_no_time_restriction_always_active(self, evaluator):
        """Test that rules without time restrictions are always active"""

        rule = ConditionSchema(
            name="Test",
            code="TEST",
            priority=0,
            actions=[self._min_action()],
        )

        # Should be active at any time
        now = datetime(2025, 1, 13, 10, 0, 0, tzinfo=TIMEZONE_INFO)
        assert evaluator._is_time_active(rule, now) is True

        now = datetime(2025, 1, 13, 23, 0, 0, tzinfo=TIMEZONE_INFO)
        assert evaluator._is_time_active(rule, now) is True

    def test_within_time_range(self, evaluator):
        """Test when current time is within the range"""

        rule = ConditionSchema(
            name="Morning",
            code="MORNING",
            priority=10,
            active_time_ranges=[TimeRange(start="09:00", end="12:00")],
            actions=[self._min_action()],
        )

        # 10:00 - within range
        datetime_now = datetime(2025, 1, 13, 10, 0, 0, tzinfo=TIMEZONE_INFO)
        assert evaluator._is_time_active(rule, datetime_now) is True

        # 09:00 - boundary (within range)
        datetime_now = datetime(2025, 1, 13, 9, 0, 0, tzinfo=TIMEZONE_INFO)
        assert evaluator._is_time_active(rule, datetime_now) is True

        # 12:00 - boundary (within range)
        datetime_now = datetime(2025, 1, 13, 12, 0, 0, tzinfo=TIMEZONE_INFO)
        assert evaluator._is_time_active(rule, datetime_now) is True

    def test_outside_time_range(self, evaluator):
        """Test when current time is outside the range"""

        rule = ConditionSchema(
            name="Morning",
            code="MORNING",
            priority=10,
            active_time_ranges=[TimeRange(start="09:00", end="12:00")],
            actions=[self._min_action()],
        )

        # 08:59 - outside range
        datetime_now = datetime(2025, 1, 13, 8, 59, 0, tzinfo=TIMEZONE_INFO)
        assert evaluator._is_time_active(rule, datetime_now) is False

        # 12:01 - outside range
        datetime_now = datetime(2025, 1, 13, 12, 1, 0, tzinfo=TIMEZONE_INFO)
        assert evaluator._is_time_active(rule, datetime_now) is False

        # 14:00 - outside range
        datetime_now = datetime(2025, 1, 13, 14, 0, 0, tzinfo=TIMEZONE_INFO)
        assert evaluator._is_time_active(rule, datetime_now) is False

    def test_overnight_range(self, evaluator):
        """Test an overnight time range (crossing midnight)"""

        rule = ConditionSchema(
            name="Night",
            code="NIGHT",
            priority=10,
            active_time_ranges=[TimeRange(start="22:00", end="06:00")],
            actions=[self._min_action()],
        )

        # 23:00 - within range (before midnight)
        datetime_now = datetime(2025, 1, 13, 23, 0, 0, tzinfo=TIMEZONE_INFO)
        assert evaluator._is_time_active(rule, datetime_now) is True

        # 03:00 - within range (after midnight)
        datetime_now = datetime(2025, 1, 14, 3, 0, 0, tzinfo=TIMEZONE_INFO)
        assert evaluator._is_time_active(rule, datetime_now) is True

        # 12:00 - outside range
        datetime_now = datetime(2025, 1, 13, 12, 0, 0, tzinfo=TIMEZONE_INFO)
        assert evaluator._is_time_active(rule, datetime_now) is False

    def test_multiple_time_ranges(self, evaluator):
        """Test multiple time ranges (OR logic)"""

        rule = ConditionSchema(
            name="Split Shift",
            code="SPLIT",
            priority=10,
            active_time_ranges=[
                TimeRange(start="08:00", end="12:00"),
                TimeRange(start="13:00", end="17:00"),
            ],
            actions=[self._min_action()],
        )

        # 10:00 - within the first range
        datetime_now = datetime(2025, 1, 13, 10, 0, 0, tzinfo=TIMEZONE_INFO)
        assert evaluator._is_time_active(rule, datetime_now) is True

        # 15:00 - within the second range
        datetime_now = datetime(2025, 1, 13, 15, 0, 0, tzinfo=TIMEZONE_INFO)
        assert evaluator._is_time_active(rule, datetime_now) is True

        # 12:30 - between the two ranges
        datetime_now = datetime(2025, 1, 13, 12, 30, 0, tzinfo=TIMEZONE_INFO)
        assert evaluator._is_time_active(rule, datetime_now) is False

        # 20:00 - outside both ranges
        datetime_now = datetime(2025, 1, 13, 20, 0, 0, tzinfo=TIMEZONE_INFO)
        assert evaluator._is_time_active(rule, datetime_now) is False


class TestEvaluateWithTimeRanges:
    """Tests interactions between evaluate() and time range conditions"""

    @pytest.fixture
    def test_config(self):
        """Build test configuration"""
        config_dict = {
            "version": "1.0.0",
            "root": {
                "TEST_DEVICE": {
                    "default_controls": [],
                    "instances": {
                        "1": {
                            "use_default_controls": False,
                            "controls": [
                                {
                                    "name": "Emergency Stop",
                                    "code": "EMERGENCY",
                                    "priority": 0,
                                    "composite": {
                                        "type": "threshold",
                                        "sources": [{"device": "TEST_DEVICE", "slave_id": "1", "pins": ["TEMP"]}],
                                        "operator": "gt",
                                        "threshold": 80.0,
                                    },
                                    "actions": [
                                        {
                                            "model": "TEST_DEVICE",
                                            "slave_id": "1",
                                            "type": "set_frequency",
                                            "target": "HZ",
                                            "value": 60.0,
                                            "emergency_override": True,
                                        }
                                    ],
                                },
                                {
                                    "name": "Morning Fixed",
                                    "code": "MORNING_FIXED",
                                    "priority": 10,
                                    "active_time_ranges": [{"start": "09:00", "end": "12:00"}],
                                    "composite": {
                                        "type": "threshold",
                                        "sources": [{"device": "TEST_DEVICE", "slave_id": "1", "pins": ["TEMP"]}],
                                        "operator": "gte",
                                        "threshold": 0.0,
                                    },
                                    "actions": [
                                        {
                                            "model": "TEST_DEVICE",
                                            "slave_id": "1",
                                            "type": "set_frequency",
                                            "target": "HZ",
                                            "value": 30.0,
                                        }
                                    ],
                                },
                                {
                                    "name": "Speed Up",
                                    "code": "SPEED_UP",
                                    "priority": 90,
                                    "composite": {
                                        "type": "threshold",
                                        "sources": [{"device": "TEST_DEVICE", "slave_id": "1", "pins": ["TEMP"]}],
                                        "operator": "gt",
                                        "threshold": 25.0,
                                    },
                                    "actions": [
                                        {
                                            "model": "TEST_DEVICE",
                                            "slave_id": "1",
                                            "type": "adjust_frequency",
                                            "target": "HZ",
                                            "value": 2.0,
                                        }
                                    ],
                                },
                            ],
                        }
                    },
                }
            },
        }
        return ControlConfig(**config_dict)

    @pytest.fixture
    def evaluator(self, test_config):
        """Create evaluator"""
        constraint = ConstraintConfigSchema(version="1.0.0", devices={})
        return ControlEvaluator(test_config, constraint)

    def test_time_based_rule_active_during_time_range(self, evaluator):
        """Test that a time-based rule triggers within its active time range"""
        snapshot = {"TEST_DEVICE_1": {"TEMP": 30.0}}

        # Mock time as 10:00 (within 09:00-12:00)
        mock_time = datetime(2025, 1, 13, 10, 0, 0, tzinfo=TIMEZONE_INFO)

        with patch("core.evaluator.control_evaluator.datetime") as mock_datetime:
            mock_datetime.now.return_value = mock_time
            mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

            actions = evaluator.evaluate("TEST_DEVICE", "1", snapshot)

        # Should trigger two rules: MORNING_FIXED (p=10) and SPEED_UP (p=90)
        assert len(actions) == 2

        # Verify order (sorted by priority)
        assert actions[0].priority == 10  # MORNING_FIXED
        assert actions[0].value == 30.0

        assert actions[1].priority == 90  # SPEED_UP
        assert actions[1].value == 2.0

    def test_time_based_rule_inactive_outside_time_range(self, evaluator):
        """Test that a time-based rule does not trigger outside its active time range"""
        snapshot = {"TEST_DEVICE_1": {"TEMP": 30.0}}

        # Mock time as 14:00 (outside 09:00-12:00)
        mock_time = datetime(2025, 1, 13, 14, 0, 0, tzinfo=TIMEZONE_INFO)

        with patch("core.evaluator.control_evaluator.datetime") as mock_datetime:
            mock_datetime.now.return_value = mock_time
            mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

            actions = evaluator.evaluate("TEST_DEVICE", "1", snapshot)

        # Only SPEED_UP should trigger
        assert len(actions) == 1
        assert actions[0].priority == 90  # SPEED_UP
        assert actions[0].value == 2.0

    def test_emergency_always_active_regardless_of_time(self, evaluator):
        """Test that emergency rules are not affected by time restrictions"""
        snapshot = {"TEST_DEVICE_1": {"TEMP": 85.0}}

        # Test different time points
        test_times = [
            datetime(2025, 1, 13, 10, 0, 0, tzinfo=TIMEZONE_INFO),  # 10:00 (within range)
            datetime(2025, 1, 13, 14, 0, 0, tzinfo=TIMEZONE_INFO),  # 14:00 (outside range)
            datetime(2025, 1, 13, 23, 0, 0, tzinfo=TIMEZONE_INFO),  # 23:00 (late night)
        ]

        for mock_time in test_times:
            with patch("core.evaluator.control_evaluator.datetime") as mock_datetime:
                mock_datetime.now.return_value = mock_time
                mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

                actions = evaluator.evaluate("TEST_DEVICE", "1", snapshot)

            # Emergency should always trigger
            assert len(actions) >= 1
            assert any(a.emergency_override for a in actions)

    def test_time_override_blocks_normal_control(self, evaluator):
        """Test that time override blocks normal control (via the priority protection mechanism)"""
        snapshot = {"TEST_DEVICE_1": {"TEMP": 30.0}}

        # Mock time as 10:00 (within range)
        mock_time = datetime(2025, 1, 13, 10, 0, 0, tzinfo=TIMEZONE_INFO)

        with patch("core.evaluator.control_evaluator.datetime") as mock_datetime:
            mock_datetime.now.return_value = mock_time
            mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)

            actions = evaluator.evaluate("TEST_DEVICE", "1", snapshot)

        # Should trigger two rules
        assert len(actions) == 2

        # MORNING_FIXED (p=10) first
        assert actions[0].priority == 10
        assert actions[0].value == 30.0

        # SPEED_UP (p=90) second
        assert actions[1].priority == 90
        assert actions[1].value == 2.0

        # In the executor, MORNING_FIXED protects the write,
        # and SPEED_UP will be skipped (verified in executor tests)

    def test_multiple_time_ranges_or_logic(self, evaluator):
        """Test OR logic across multiple time ranges"""
        # Modify config to include a multi-range rule
        config_dict = {
            "version": "1.0.0",
            "root": {
                "TEST_DEVICE": {
                    "default_controls": [],
                    "instances": {
                        "1": {
                            "use_default_controls": False,
                            "controls": [
                                {
                                    "name": "Split Shift Fixed",
                                    "code": "SPLIT_FIXED",
                                    "priority": 10,
                                    "active_time_ranges": [
                                        {"start": "08:00", "end": "12:00"},
                                        {"start": "13:00", "end": "17:00"},
                                    ],
                                    "composite": {
                                        "type": "threshold",
                                        "sources": [{"device": "TEST_DEVICE", "slave_id": "1", "pins": ["TEMP"]}],
                                        "operator": "gte",
                                        "threshold": 0.0,
                                    },
                                    "actions": [
                                        {
                                            "model": "TEST_DEVICE",
                                            "slave_id": "1",
                                            "type": "set_frequency",
                                            "target": "HZ",
                                            "value": 40.0,
                                        }
                                    ],
                                }
                            ],
                        }
                    },
                }
            },
        }

        config = ControlConfig(**config_dict)
        constraint = ConstraintConfigSchema(version="1.0.0", devices={})
        eval_test = ControlEvaluator(config, constraint)

        snapshot = {"TEST_DEVICE_1": {"TEMP": 25.0}}

        # 10:00 - within the first range
        mock_time = datetime(2025, 1, 13, 10, 0, 0, tzinfo=TIMEZONE_INFO)
        with patch("core.evaluator.control_evaluator.datetime") as mock_datetime:
            mock_datetime.now.return_value = mock_time
            mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
            actions = eval_test.evaluate("TEST_DEVICE", "1", snapshot)
        assert len(actions) == 1

        # 15:00 - within the second range
        mock_time = datetime(2025, 1, 13, 15, 0, 0, tzinfo=TIMEZONE_INFO)
        with patch("core.evaluator.control_evaluator.datetime") as mock_datetime:
            mock_datetime.now.return_value = mock_time
            mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
            actions = eval_test.evaluate("TEST_DEVICE", "1", snapshot)
        assert len(actions) == 1

        # 12:30 - between the two ranges
        mock_time = datetime(2025, 1, 13, 12, 30, 0, tzinfo=TIMEZONE_INFO)
        with patch("core.evaluator.control_evaluator.datetime") as mock_datetime:
            mock_datetime.now.return_value = mock_time
            mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
            actions = eval_test.evaluate("TEST_DEVICE", "1", snapshot)
        assert len(actions) == 0


class TestEdgeCases:

    @pytest.fixture
    def min_action(self):
        return ControlActionSchema(
            type="turn_off",
            model="TECO_VFD",
            slave_id="1",
        )

    @pytest.fixture
    def evaluator(self):
        config = ControlConfig(version="1.0.0", root={})
        constraint = ConstraintConfigSchema(version="1.0.0", devices={})
        return ControlEvaluator(config, constraint)

    def test_midnight_boundary(self, evaluator):
        rule = ConditionSchema(
            name="Overnight",
            code="OVERNIGHT",
            priority=10,
            active_time_ranges=[TimeRange(start="23:00", end="01:00")],
            actions=[
                ControlActionSchema(
                    type="turn_off",
                    model="TECO_VFD",
                    slave_id="1",
                )
            ],
        )

        assert evaluator._is_time_active(rule, _now(2025, 1, 13, 23, 30)) is True
        assert evaluator._is_time_active(rule, _now(2025, 1, 14, 0, 30)) is True
        assert evaluator._is_time_active(rule, _now(2025, 1, 14, 2, 0)) is False

    def test_all_day_range(self, evaluator, min_action):
        rule = ConditionSchema(
            name="All Day",
            code="ALL_DAY",
            priority=10,
            active_time_ranges=[TimeRange(start="00:00", end="23:59")],
            actions=[min_action],
        )

        assert evaluator._is_time_active(rule, _now(2025, 1, 13, 0, 0)) is True
        assert evaluator._is_time_active(rule, _now(2025, 1, 13, 23, 59)) is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
