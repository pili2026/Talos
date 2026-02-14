from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.schema.modbus_config_metadata import ConfigMetadata


class InitializationConfig(BaseModel):
    startup_frequency: float | None = Field(default=None, description="Device startup frequency in Hz")
    auto_turn_on: bool | None = Field(default=None, description="Turn on device on recovered (offline->online)")


class ConstraintConfig(BaseModel):
    min: float | None = Field(default=60, description="Minimum allowed value")
    max: float | None = Field(default=60, description="Maximum allowed value")


class InstanceConfig(BaseModel):
    initialization: InitializationConfig | None = None
    constraints: dict[str, ConstraintConfig] | None = None
    use_default_constraints: bool | None = Field(default=True)

    pins: dict[str, dict] | None = None
    model_config = ConfigDict(extra="allow")


class DeviceConfig(BaseModel):
    initialization: InitializationConfig | None = None
    default_constraints: dict[str, ConstraintConfig] | None = None
    instances: dict[str, InstanceConfig] | None = None

    pins: dict[str, dict] | None = None


class ConstraintConfigSchema(BaseModel):
    model_config = ConfigDict(extra="allow")

    metadata: ConfigMetadata = Field(
        default_factory=ConfigMetadata,
        validation_alias="_metadata",
        serialization_alias="_metadata",
        description="Configuration metadata for version tracking",
    )

    global_defaults: DeviceConfig | None = None
    # Use a dictionary to hold device configurations with device model as the key
    devices: dict[str, DeviceConfig] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def split_global_and_devices(cls, data: dict):
        """
        Handle two input formats:
        1. YAML format: devices at top level
           {"_metadata": {...}, "global_defaults": {...}, "TECO_VFD": {...}, "ADAM_4117": {...}}

        2. Direct construction: devices already in dict
           {"_metadata": {...}, "global_defaults": {...}, "devices": {"TECO_VFD": {...}}}

        3. Direct Python construction with metadata kwarg:
           ConstraintConfigSchema(metadata=..., global_defaults=..., devices={...})
        """
        if not isinstance(data, dict):
            return data

        # Extract metadata if present (for YAML loading)
        metadata = data.pop("_metadata", None)

        # Check if metadata was passed directly (Python construction)
        if "metadata" in data:
            # Convert ConfigMetadata object to dict if needed
            metadata_val = data.pop("metadata")
            if hasattr(metadata_val, "model_dump"):
                # It's a Pydantic model, convert to dict
                metadata = metadata_val.model_dump()
            else:
                metadata = metadata_val

        # Extract global_defaults
        global_defaults = data.pop("global_defaults", None)

        # Extract version (legacy field, if any)
        data.pop("version", None)

        # Check if devices already exists and is properly formatted
        if "devices" in data and isinstance(data.get("devices"), dict):
            # Format 2: devices already collected
            devices = data.pop("devices")
        else:
            # Format 1: collect devices from top level
            devices: dict[str, dict] = {}
            for key, value in list(data.items()):
                if isinstance(value, dict):
                    devices[key] = value

        result = {
            "global_defaults": global_defaults,
            "devices": devices,
        }

        # Re-add metadata with correct key
        if metadata is not None:
            result["_metadata"] = metadata

        return result
