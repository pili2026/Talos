from core.evaluator.alert_state_manager import AlertState, AlertStateManager
from core.schema.alert_schema import AlertSeverity


class TestAlertStateManager:

    def test_when_first_violation_then_notify(self):
        """First violation should trigger notification"""
        # Arrange
        manager = AlertStateManager()

        # Act
        should_notify, notification_type = manager.should_notify(
            device_id="SD400_3",
            alert_code="AIN01_HIGH",
            is_triggered=True,
            severity=AlertSeverity.WARNING,
            current_value=50.0,
        )

        # Assert
        assert should_notify is True
        assert notification_type == "TRIGGERED"
        assert manager.get_state("SD400_3", "AIN01_HIGH") == AlertState.TRIGGERED

    def test_when_continuous_violation_then_no_notify(self):
        """Continuous violations should not trigger repeated notifications"""
        # Arrange
        manager = AlertStateManager()

        # Act
        # First violation
        manager.should_notify("SD400_3", "AIN01_HIGH", True, AlertSeverity.WARNING, 50.0)

        # Second violation (continuous)
        should_notify, notification_type = manager.should_notify(
            "SD400_3", "AIN01_HIGH", True, AlertSeverity.WARNING, 51.0
        )

        # Assert
        assert should_notify is False
        assert notification_type is None
        assert manager.get_state("SD400_3", "AIN01_HIGH") == AlertState.ACTIVE

    def test_when_condition_recovers_then_notify_resolved(self):
        """Recovery should trigger RESOLVED notification"""
        # Arrange
        manager = AlertStateManager()

        # Act
        # Trigger alert
        manager.should_notify("SD400_3", "AIN01_HIGH", True, AlertSeverity.WARNING, 50.0)
        manager.should_notify("SD400_3", "AIN01_HIGH", True, AlertSeverity.WARNING, 51.0)

        # Recover
        should_notify, notification_type = manager.should_notify(
            "SD400_3", "AIN01_HIGH", False, AlertSeverity.WARNING, 48.0
        )

        # Assert
        assert should_notify is True
        assert notification_type == "RESOLVED"
        assert manager.get_state("SD400_3", "AIN01_HIGH") == AlertState.RESOLVED

    def test_when_resolved_then_cleanup(self):
        """After RESOLVED, next normal check should cleanup state"""
        # Arrange
        manager = AlertStateManager()

        # Act
        # Trigger → Active → Resolved
        manager.should_notify("SD400_3", "AIN01_HIGH", True, AlertSeverity.WARNING, 50.0)
        manager.should_notify("SD400_3", "AIN01_HIGH", True, AlertSeverity.WARNING, 51.0)
        manager.should_notify("SD400_3", "AIN01_HIGH", False, AlertSeverity.WARNING, 48.0)

        # Cleanup
        should_notify, _ = manager.should_notify("SD400_3", "AIN01_HIGH", False, AlertSeverity.WARNING, 45.0)

        # Assert
        assert should_notify is False
        assert manager.get_state("SD400_3", "AIN01_HIGH") == AlertState.NORMAL

    def test_when_retriggered_after_resolved_then_notify(self):
        """Re-triggering after recovery should send new notification"""
        # Arrange
        manager = AlertStateManager()

        # Act
        # First cycle: Trigger → Resolved → Normal
        manager.should_notify("SD400_3", "AIN01_HIGH", True, AlertSeverity.WARNING, 50.0)
        manager.should_notify("SD400_3", "AIN01_HIGH", False, AlertSeverity.WARNING, 48.0)
        manager.should_notify("SD400_3", "AIN01_HIGH", False, AlertSeverity.WARNING, 45.0)

        # Re-trigger
        should_notify, notification_type = manager.should_notify(
            "SD400_3", "AIN01_HIGH", True, AlertSeverity.WARNING, 52.0
        )

        # Assert
        assert should_notify is True
        assert notification_type == "TRIGGERED"
        assert manager.get_state("SD400_3", "AIN01_HIGH") == AlertState.TRIGGERED

    def test_when_multiple_alerts_then_tracked_independently(self):
        """Multiple alerts on same device should be tracked independently"""
        # Arrange
        manager = AlertStateManager()

        # Act
        # Trigger alert 1
        manager.should_notify("SD400_3", "AIN01_HIGH", True, AlertSeverity.WARNING, 50.0)

        # Trigger alert 2
        should_notify, _ = manager.should_notify("SD400_3", "AIN02_LOW", True, AlertSeverity.ERROR, 5.0)

        # Assert
        assert should_notify is True
        assert manager.get_state("SD400_3", "AIN01_HIGH") == AlertState.TRIGGERED
        assert manager.get_state("SD400_3", "AIN02_LOW") == AlertState.TRIGGERED
