"""
Config Builder API Models

Request/response models for the Config Builder API endpoints.
Reuses existing core Pydantic schemas where possible.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from core.schema.alert_schema import AlertConditionModel
from core.schema.control_condition_schema import ConditionSchema


# ============================================================================
# Shared / Response Models
# ============================================================================


class PinInfo(BaseModel):
    """Metadata for a single device register/pin."""

    name: str
    readable: bool
    writable: bool
    type: str | None = None
    unit: str | None = None
    description: str | None = None


class ConfigBuilderDeviceInfo(BaseModel):
    """Device summary for Config Builder (read from YAML, not runtime state)."""

    model: str
    slave_id: int
    type: str
    pins: list[str] = Field(description="All pin names defined in the driver")


class ConfigBuilderDeviceListResponse(BaseModel):
    devices: list[ConfigBuilderDeviceInfo]
    total: int


class DevicePinsResponse(BaseModel):
    model: str
    readable_pins: list[PinInfo]
    writable_pins: list[PinInfo]


# ============================================================================
# Validation Models
# ============================================================================


class FieldValidationError(BaseModel):
    """Single field-level validation error with location path."""

    location: str = Field(description="Dot-separated field path, e.g. 'TECO_VFD.instances.1.controls.0.code'")
    message: str


class ValidationResponse(BaseModel):
    valid: bool
    errors: list[FieldValidationError] = []


class ValidateRequest(BaseModel):
    yaml_content: str = Field(description="Raw YAML string to validate")


# ============================================================================
# Generate Request Models
# ============================================================================


class ControlGenerateRequest(BaseModel):
    """
    Form data for generating a control_condition YAML.

    One model + one instance per request; multiple controls supported.
    The resulting YAML follows the flat format used in res/control_condition.yml.
    """

    version: str = Field(default="2.0.0", description="Config file version")
    model: str = Field(description="Target device model, e.g. 'TECO_VFD'")
    slave_id: str = Field(description="Instance slave_id as string, e.g. '1'")
    use_default_controls: bool = False
    default_controls: list[ConditionSchema] = Field(
        default_factory=list,
        description="Default control rules applied to all instances of this model",
    )
    controls: Annotated[
        list[ConditionSchema],
        Field(min_length=1, description="Control rules for this specific instance"),
    ]


class AlertGenerateRequest(BaseModel):
    """
    Form data for generating an alert_condition YAML.

    One model + one instance per request; multiple alerts supported.
    The resulting YAML follows the flat format used in res/alert_condition.yml.
    """

    version: str = Field(default="1.1.0", description="Config file version")
    model: str = Field(description="Target device model, e.g. 'TECO_VFD'")
    slave_id: str = Field(description="Instance slave_id as string, e.g. '1'")
    use_default_alerts: bool = False
    default_alerts: list[AlertConditionModel] = Field(
        default_factory=list,
        description="Default alert rules applied to all instances of this model",
    )
    alerts: Annotated[
        list[AlertConditionModel],
        Field(min_length=1, description="Alert rules for this specific instance"),
    ]


# ============================================================================
# Generate Response Models
# ============================================================================


class GenerateResponse(BaseModel):
    yaml_content: str = Field(description="Generated YAML string ready to write to file")


# ============================================================================
# Diagram Models
# ============================================================================


class DiagramRequest(BaseModel):
    yaml_content: str = Field(description="Raw YAML string (control or alert config)")
    config_type: Literal["control", "alert"] = Field(description="Type of config to diagram")


class DiagramResponse(BaseModel):
    mermaid: str = Field(description="Mermaid flowchart DSL string")
