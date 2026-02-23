from pydantic import BaseModel, Field


class PinConfig(BaseModel):
    """Primarily for AI module pins; DI only uses remark"""

    remark: str | None = None
    formula: list[float] | None = None  # [N1, N2, N3]


class ConstraintConfigRequest(BaseModel):
    min: float
    max: float


class InstanceConfigRequest(BaseModel):
    initialization: dict | None = None
    constraints: dict[str, ConstraintConfigRequest] | None = None
    use_default_constraints: bool = True
    pins: dict[str, PinConfig] | None = None


class DeviceConfigRequest(BaseModel):
    initialization: dict | None = None
    default_constraints: dict[str, ConstraintConfigRequest] | None = None
    instances: dict[str, InstanceConfigRequest] = Field(default_factory=dict)


class UpdateDeviceConfigRequest(BaseModel):
    """PUT /api/config/instance/{model}"""

    config: DeviceConfigRequest


class InstanceConfigResponse(BaseModel):
    """GET /api/config/instance"""

    status: str
    global_defaults: dict | None = None
    devices: dict[str, DeviceConfigRequest]
    generation: int
    checksum: str | None = None
    modified_at: str | None = None
