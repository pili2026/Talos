from enum import StrEnum

from pydantic import BaseModel


class PinMappingSource(StrEnum):
    OVERRIDE = "override"
    TEMPLATE = "template"


class PinMappingModelInfo(BaseModel):
    model: str
    has_override: bool
    source: PinMappingSource


class PinMappingListResponse(BaseModel):
    models: list[PinMappingModelInfo]
