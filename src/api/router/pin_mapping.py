"""
Pin Mapping Router
Read-only operations for pin mapping configs
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependency import get_pin_mapping_service
from api.model.pin_mapping import PinMappingListResponse, PinMappingModelInfo
from api.service.pin_mapping_service import PinMappingService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "",
    response_model=PinMappingListResponse,
    summary="List all available pin mapping models",
)
async def list_pin_mappings(
    service: PinMappingService = Depends(get_pin_mapping_service),
) -> PinMappingListResponse:
    models = service.list_available_models()
    result = []
    for model in models:
        try:
            _, source = service.get_pin_mapping(model)
            result.append(
                PinMappingModelInfo(
                    model=model,
                    has_override=(source == "override"),
                    source=source,
                )
            )
        except FileNotFoundError:
            pass
    return PinMappingListResponse(models=result)


@router.get(
    "/{model}",
    summary="Get effective pin mapping for a model (override → template)",
)
async def get_pin_mapping(
    model: str,
    service: PinMappingService = Depends(get_pin_mapping_service),
) -> dict:
    try:
        config, source = service.get_pin_mapping(model)
        return {
            "model": model,
            "source": source,
            "config": config.model_dump(exclude_none=True),
        }
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No pin mapping found for model: {model}",
        ) from exc


@router.get(
    "/{model}/template",
    summary="Get template pin mapping for a model",
)
async def get_pin_mapping_template(
    model: str,
    service: PinMappingService = Depends(get_pin_mapping_service),
) -> dict:
    try:
        config = service.get_template(model)
        return {
            "model": model,
            "source": "template",
            "config": config.model_dump(exclude_none=True),
        }
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No template found for model: {model}",
        ) from exc
