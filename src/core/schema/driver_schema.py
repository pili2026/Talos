"""
Driver Schema Definition for Talos
Defines pure hardware-layer driver configuration schema
"""

from typing import Literal, Union

from pydantic import BaseModel, Field


class PhysicalPinDefinition(BaseModel):
    """Physical register definition (actual hardware register)"""

    offset: int = Field(..., ge=0, description="Modbus register address")
    format: str = Field(default="u16", description="Data format (u16, i16, u32_le, f32_be, etc.)")
    readable: bool = Field(default=True, description="Whether the pin is readable")
    writable: bool = Field(default=False, description="Whether the pin is writable")
    description: str | None = Field(None, description="Hardware function description")

    scale: float | None = Field(None, description="Scale factor (for fixed-spec devices)")
    type: str | None = Field(None, description="Data type (for fixed-spec devices)")
    unit: str | None = Field(None, description="Unit (for fixed-spec devices)")
    precision: int | None = Field(None, description="Decimal precision (for fixed-spec devices)")
    formula: list[float] | None = Field(None, description="Linear formula [offset, scale, constant]")


class ComputedPinDefinition(BaseModel):
    """Computed/virtual field definition (calculated from other registers)"""

    type: Literal["computed"] = Field(..., description="Must be 'computed'")
    formula: str = Field(..., description="Computation formula name")
    inputs: list[str] = Field(..., description="Input register names")
    output_format: str | None = Field(None, description="Output data format")
    description: str | None = Field(None, description="Computed field description")


class DriverConfig(BaseModel):
    """Complete driver configuration"""

    model: str = Field(..., description="Device model")
    register_type: str = Field(..., description="Register type (holding, input, coil, discrete_input)")
    type: str = Field(..., description="Device type (ai_module, vfd, inverter, etc.)")
    description: str | None = Field(None, description="Driver description")
    register_map: dict[str, Union[PhysicalPinDefinition, ComputedPinDefinition]] = Field(
        ..., description="Pin definition mapping (physical or computed)"
    )
