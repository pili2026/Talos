from pydantic import BaseModel, Field

from core.model.enum.alert_enum import AlertSeverity


class AlertEvaluationResult(BaseModel):
    """
    Alert evaluation result with all necessary information for notification.

    This model serves as an intermediate data structure between AlertEvaluator
    and notification systems, containing all fields needed to construct
    localized notification messages.
    """

    alert_code: str = Field(description="Unique identifier for this alert type (e.g., 'FOREPART_TEMP_AVG_OVERHEAT')")
    name: str = Field(description="Human-readable alert name (e.g., 'Forepart Temperature Avg High')")
    device_name: str = Field(description="Display name for the device")
    condition: str = Field(description="Condition operator: 'gt', 'lt', 'eq', 'gte', 'lte', 'neq', or 'schedule'")
    threshold: float = Field(description="Threshold value or expected state for comparison")
    current_value: float = Field(description="Current sensor reading or device state")
    severity: AlertSeverity = Field(description="Alert severity level (INFO, WARNING, ERROR, CRITICAL)")
    notification_type: str = Field(description="Notification type: 'TRIGGERED' or 'RESOLVED'")
    message: str = Field(description="Fallback message in English (for debugging or default locale)")

    model_config = {
        "frozen": True,  # Make immutable like dataclass with frozen=True
    }
