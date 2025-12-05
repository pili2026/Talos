from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    model_config = ConfigDict(extra="allow")

    global_defaults: DeviceConfig | None = None
    # Use a dictionary to hold device configurations with device model as the key
    devices: dict[str, DeviceConfig] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def split_global_and_devices(cls, data: dict):
        if not isinstance(data, dict):
            return data

        global_defaults = data.pop("global_defaults", None)

        devices: dict[str, dict] = {}

        for key, value in list(data.items()):
            if isinstance(value, dict):
                devices[key] = value

        return {
            "global_defaults": global_defaults,
            "devices": devices,
        }
