"""
Integration Tests for Time-Elapsed Control Conditions

Tests complete flow: Config → Evaluator → Executor → Device
Uses real SQLite database for persistence testing
"""

import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from core.evaluator.composite_evaluator import CompositeEvaluator
from core.model.control_composite import CompositeNode
from core.model.enum.condition_enum import ConditionType
from repository.control_execution_store import ControlExecutionStore


class TestTimeElapsedControlIntegration:
    """Integration tests for time_elapsed control with real database"""

    @pytest.fixture
    def temp_db(self):
        """Create temporary database for testing"""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        yield db_path
        # Cleanup
        Path(db_path).unlink(missing_ok=True)

    @pytest.fixture
    def execution_store(self, temp_db):
        """Create real ControlExecutionStore with temp database"""
        return ControlExecutionStore(temp_db, timezone="Asia/Taipei")

    @pytest.fixture
    def evaluator_with_real_store(self, execution_store):
        """Create CompositeEvaluator with real execution store"""
        return CompositeEvaluator(execution_store=execution_store, timezone="Asia/Taipei")

    @pytest.fixture
    def time_elapsed_node(self):
        """Create real CompositeNode with time_elapsed type"""
        return CompositeNode(type=ConditionType.TIME_ELAPSED, interval_hours=4.0)

    # ========================================
    # Test: End-to-End First Execution
    # ========================================

    def test_when_first_run_then_triggers_and_persists(
        self, evaluator_with_real_store, time_elapsed_node, execution_store
    ):
        """Test that first execution triggers and persists to database"""
        # Arrange
        rule_code = "FREQ_STEPDOWN_4H"
        device_model = "TECO_VFD"
        device_slave_id = "4"

        evaluator_with_real_store.set_evaluation_context(rule_code, device_model, device_slave_id)

        # Act
        result = evaluator_with_real_store.evaluate_composite_node(time_elapsed_node, lambda x: None)

        # Assert: Should trigger
        assert result is True

        # Assert: Should persist to database
        last_exec = execution_store.get_last_execution(rule_code)
        assert last_exec is not None
        assert isinstance(last_exec, datetime)

        # Assert: Should have timezone
        assert last_exec.tzinfo is not None

    # ========================================
    # Test: Database Persistence Across Restarts
    # ========================================

    def test_when_system_restarts_then_loads_from_database(self, temp_db):
        """Test that execution history survives system restart"""
        # Phase 1: Initial run
        store1 = ControlExecutionStore(temp_db, timezone="Asia/Taipei")
        evaluator1 = CompositeEvaluator(execution_store=store1, timezone="Asia/Taipei")

        rule_code = "FREQ_STEPDOWN_4H"
        evaluator1.set_evaluation_context(rule_code, "TECO_VFD", "4")

        node = CompositeNode(type=ConditionType.TIME_ELAPSED, interval_hours=4.0)
        result1 = evaluator1.evaluate_composite_node(node, lambda x: None)
        assert result1 is True  # First execution

        # Get timestamp from Phase 1
        last_exec_phase1 = store1.get_last_execution(rule_code)

        # Simulate system restart (destroy evaluator and store)
        del evaluator1
        del store1

        # Phase 2: After restart (new objects, same database)
        store2 = ControlExecutionStore(temp_db, timezone="Asia/Taipei")
        evaluator2 = CompositeEvaluator(execution_store=store2, timezone="Asia/Taipei")
        evaluator2.set_evaluation_context(rule_code, "TECO_VFD", "4")

        # Should not trigger yet (interval not elapsed)
        result2 = evaluator2.evaluate_composite_node(node, lambda x: None)
        assert result2 is False

        # Verify same timestamp
        last_exec_phase2 = store2.get_last_execution(rule_code)
        assert last_exec_phase1 == last_exec_phase2

    # ========================================
    # Test: Multiple Cycles
    # ========================================

    def test_when_multiple_cycles_then_tracks_each_execution(self, evaluator_with_real_store, execution_store):
        """Test multiple execution cycles with proper interval tracking"""
        rule_code = "FREQ_STEPDOWN_4H"
        evaluator_with_real_store.set_evaluation_context(rule_code, "TECO_VFD", "4")

        node = CompositeNode(type=ConditionType.TIME_ELAPSED, interval_hours=4.0)

        # Cycle 1: First execution
        result1 = evaluator_with_real_store.evaluate_composite_node(node, lambda x: None)
        assert result1 is True
        time1 = execution_store.get_last_execution(rule_code)

        # Cycle 2: Immediately after (should not trigger)
        result2 = evaluator_with_real_store.evaluate_composite_node(node, lambda x: None)
        assert result2 is False

        # Cycle 3: Manually advance time (simulate 4+ hours later)
        tz = ZoneInfo("Asia/Taipei")
        future_time = datetime.now(tz) + timedelta(hours=5)
        execution_store.update_execution(rule_code, future_time, "TECO_VFD", "4")

        # Verify the timestamp was updated
        time3 = execution_store.get_last_execution(rule_code)
        assert time3 > time1

    # ========================================
    # Test: Database Operations
    # ========================================

    def test_when_clearing_specific_rule_then_only_that_rule_cleared(self, execution_store):
        """Test clearing specific rule from execution history"""
        # Arrange
        tz = ZoneInfo("Asia/Taipei")
        now = datetime.now(tz)

        execution_store.update_execution("RULE_1", now, "TECO_VFD", "1")
        execution_store.update_execution("RULE_2", now, "TECO_VFD", "2")

        # Act
        execution_store.clear_history("RULE_1")

        # Assert
        assert execution_store.get_last_execution("RULE_1") is None
        assert execution_store.get_last_execution("RULE_2") is not None

    def test_when_clearing_all_then_all_rules_cleared(self, execution_store):
        """Test clearing all execution history"""
        # Arrange
        tz = ZoneInfo("Asia/Taipei")
        now = datetime.now(tz)

        execution_store.update_execution("RULE_1", now, "TECO_VFD", "1")
        execution_store.update_execution("RULE_2", now, "TECO_VFD", "2")

        # Act
        execution_store.clear_history()

        # Assert
        assert execution_store.get_last_execution("RULE_1") is None
        assert execution_store.get_last_execution("RULE_2") is None

    def test_when_get_all_executions_then_returns_all_records(self, execution_store):
        """Test retrieving all execution records"""
        # Arrange
        tz = ZoneInfo("Asia/Taipei")
        now = datetime.now(tz)

        execution_store.update_execution("RULE_1", now, "TECO_VFD", "1")
        execution_store.update_execution("RULE_2", now, "LITEON_EVO6800", "2")

        # Act
        all_execs = execution_store.get_all_executions()

        # Assert
        assert len(all_execs) == 2
        assert "RULE_1" in all_execs
        assert "RULE_2" in all_execs
        assert all_execs["RULE_1"]["device_model"] == "TECO_VFD"
        assert all_execs["RULE_2"]["device_model"] == "LITEON_EVO6800"

    # ========================================
    # Test: Timezone Handling
    # ========================================

    def test_when_different_timezones_then_handles_correctly(self, temp_db):
        """Test timezone handling across different timezone settings"""
        # Create store with different timezone
        store_taipei = ControlExecutionStore(temp_db, timezone="Asia/Taipei")
        store_utc = ControlExecutionStore(temp_db, timezone="UTC")

        # Update with Taipei timezone
        tz_taipei = ZoneInfo("Asia/Taipei")
        now_taipei = datetime.now(tz_taipei)
        store_taipei.update_execution("RULE_1", now_taipei, "TECO_VFD", "1")

        # Read with UTC timezone
        last_exec_utc = store_utc.get_last_execution("RULE_1")

        # Assert: Should be able to read regardless of timezone
        assert last_exec_utc is not None
        assert isinstance(last_exec_utc, datetime)
        assert last_exec_utc.tzinfo is not None


class TestCompositeNodeValidation:
    """Test CompositeNode validation for time_elapsed type"""

    def test_when_valid_time_elapsed_node_then_no_errors(self):
        """Test that valid time_elapsed node validates successfully"""
        # Act
        node = CompositeNode(type=ConditionType.TIME_ELAPSED, interval_hours=4.0)

        # Assert
        assert node.invalid is False

    def test_when_missing_interval_hours_then_validation_fails(self):
        """Test that missing interval_hours marks node as invalid"""
        # Act
        node = CompositeNode(type=ConditionType.TIME_ELAPSED, interval_hours=None)

        # Assert
        assert node.invalid is True

    def test_when_negative_interval_hours_then_validation_fails(self):
        """Test that negative interval_hours marks node as invalid"""
        # Act
        node = CompositeNode(type=ConditionType.TIME_ELAPSED, interval_hours=-1.0)

        # Assert
        assert node.invalid is True

    def test_when_time_elapsed_with_operator_then_validation_fails(self):
        """Test that time_elapsed should not have operator"""
        # Act
        from core.model.enum.condition_enum import ConditionOperator

        node = CompositeNode(
            type=ConditionType.TIME_ELAPSED,
            interval_hours=4.0,
            operator=ConditionOperator.GREATER_THAN,  # Should not have this
        )

        # Assert
        assert node.invalid is True

    def test_when_time_elapsed_with_sources_then_validation_fails(self):
        """Test that time_elapsed should not have sources"""
        # Act
        node = CompositeNode(
            type=ConditionType.TIME_ELAPSED, interval_hours=4.0, sources=["AIn01"]  # Should not have this
        )

        # Assert
        assert node.invalid is True


class TestBuildCompositReasonSummary:
    """Test build_composite_reason_summary for time_elapsed"""

    def test_when_time_elapsed_node_then_returns_correct_summary(self):
        """Test that summary string is formatted correctly"""
        # Arrange
        evaluator = CompositeEvaluator()
        node = CompositeNode(type=ConditionType.TIME_ELAPSED, interval_hours=4.5)

        # Act
        summary = evaluator.build_composite_reason_summary(node)

        # Assert
        assert summary == "time_elapsed(interval=4.5h)"

    def test_when_time_elapsed_in_composite_any_then_includes_in_summary(self):
        """Test that time_elapsed appears correctly in composite conditions"""
        # Arrange
        evaluator = CompositeEvaluator()

        from core.model.enum.condition_enum import ConditionOperator

        # Create composite with time_elapsed OR threshold
        node = CompositeNode(
            any=[
                CompositeNode(type=ConditionType.TIME_ELAPSED, interval_hours=4.0),
                CompositeNode(
                    type=ConditionType.THRESHOLD,
                    sources=["AIn01"],
                    operator=ConditionOperator.GREATER_THAN,
                    threshold=30.0,
                ),
            ]
        )

        # Act
        summary = evaluator.build_composite_reason_summary(node)

        # Assert
        assert "time_elapsed(interval=4.0h)" in summary
        assert "OR" in summary
        assert "threshold" in summary
