from pydantic import BaseModel, Field


class InitializationConfig(BaseModel):
    startup_frequency: float | None = Field(None, description="Device startup frequency in Hz")


class ConstraintConfig(BaseModel):
    min: float | None = Field(default=60, description="Minimum allowed value")
    max: float | None = Field(default=60, description="Maximum allowed value")


class InstanceConfig(BaseModel):
    initialization: InitializationConfig | None = None
    constraints: dict[str, ConstraintConfig] | None = None
    use_default_constraints: bool | None = Field(default=True)


class DeviceConfig(BaseModel):
    initialization: InitializationConfig | None = None
    default_constraints: dict[str, ConstraintConfig] | None = None
    instances: dict[str, InstanceConfig] | None = None


class ConstraintConfigSchema(BaseModel):
    global_defaults: DeviceConfig | None = None
    # Use a dictionary to hold device configurations with device model as the key
    devices: dict[str, DeviceConfig] = Field(default_factory=dict)

    class Config:
        extra = "allow"  # Allow extra fields for device models

    def __init__(self, **data):
        # Split global defaults and device configurations
        global_defaults = data.pop("global_defaults", None)
        devices = {}

        for key, value in data.items():
            if key != "global_defaults" and isinstance(value, dict):
                devices[key] = DeviceConfig(**value)

        super().__init__(global_defaults=DeviceConfig(**global_defaults) if global_defaults else None, devices=devices)
