"""
Driver Schema Definition for Talos
Defines pure hardware-layer driver configuration schema
"""

from pydantic import BaseModel, Field


class DriverPinDefinition(BaseModel):
    """Pin definition in driver (pure hardware description)"""

    offset: int = Field(..., ge=0, description="Modbus register address")
    format: str = Field(..., description="Data format (u16, i16, u32_le, f32_be, etc.)")
    readable: bool = Field(default=True, description="Whether the pin is readable")
    writable: bool = Field(default=False, description="Whether the pin is writable")
    description: str | None = Field(None, description="Hardware function description")


class DriverConfig(BaseModel):
    """Complete driver configuration"""

    model: str = Field(..., description="Device model")
    register_type: str = Field(..., description="Register type (holding, input, coil, discrete_input)")
    type: str = Field(..., description="Device type (ai_module, vfd, inverter, etc.)")
    description: str | None = Field(None, description="Driver description")
    register_map: dict[str, DriverPinDefinition] = Field(
        ..., description="Pin definition mapping (pure hardware layer)"
    )
