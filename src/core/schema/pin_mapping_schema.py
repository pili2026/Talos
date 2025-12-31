"""
Pin Mapping Schema Definition for Talos
Defines application-layer pin mapping configuration schema
"""

from pydantic import BaseModel, Field


class PinMapping(BaseModel):
    """Application-layer mapping definition for a single pin (overrides driver defaults)"""

    name: str | None = Field(None, description="Display name of the pin (overrides driver's description)")
    formula: list[float] | None = Field(
        None, description="Conversion formula [n1, n2, n3], calculated as (raw + n1) * n2 + n3"
    )
    type: str | None = Field(None, description="Sensor type (e.g., 'thermometer', 'pressure', 'analog')")
    unit: str | None = Field(None, description="Display unit (e.g., '°C', 'bar', 'V')")
    precision: int | None = Field(None, ge=0, description="Display precision (number of decimal places)")
    remark: str | None = Field(None, description="Additional notes or semantic label")


class PinMappingConfig(BaseModel):
    """Complete pin mapping configuration"""

    driver_model: str = Field(..., description="Associated driver model")
    mapping_name: str = Field(..., description="Mapping name (e.g., 'default')")
    description: str | None = Field(None, description="Mapping description")
    pin_mappings: dict[str, PinMapping] = Field(..., description="Pin mapping dictionary (keys are driver pin names)")
