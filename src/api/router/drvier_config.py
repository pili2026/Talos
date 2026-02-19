import logging
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException

router = APIRouter()
logger = logging.getLogger(__name__)

DRIVER_DIR = Path(__file__).resolve().parents[3] / "res" / "driver"
_MODEL_INDEX: dict[str, Path] | None = None


def _ensure_driver_dir() -> Path:
    if not DRIVER_DIR.exists() or not DRIVER_DIR.is_dir():
        raise HTTPException(status_code=500, detail="Driver directory not found")
    return DRIVER_DIR


def _safe_load_yaml(path: Path) -> dict[str, Any] | None:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            logger.warning(f"Driver YAML root is not a dict: {path}")
            return None
        return data
    except Exception as e:
        logger.warning(f"Error loading driver yaml: {path}, err={e}")
        return None


def _build_model_index() -> dict[str, Path]:
    driver_dir = _ensure_driver_dir()
    index: dict[str, Path] = {}

    for driver_path in driver_dir.glob("*.yml"):
        driver_data = _safe_load_yaml(driver_path)
        if not driver_data:
            continue

        model_raw = str(driver_data.get("model", "")).strip()
        if not model_raw:
            continue

        model_key = model_raw.lower()

        if model_key in index:
            logger.warning(
                f"Duplicate driver model '{model_raw}' detected: " f"{index[model_key].name} vs {driver_path.name}"
            )

        index[model_key] = driver_path

    return index


@router.get("")
async def list_drivers() -> dict[str, list[dict[str, Any]]]:
    driver_dir = _ensure_driver_dir()
    drivers: list[dict[str, Any]] = []

    for driver_file in sorted(driver_dir.glob("*.yml")):
        data = _safe_load_yaml(driver_file)
        if not data:
            continue

        model = str(data.get("model", "Unknown")).strip() or "Unknown"
        dtype = str(data.get("type", "other")).strip() or "other"
        desc = str(data.get("description", "")).strip()

        drivers.append(
            {
                "model": model,
                "type": dtype,
                "description": desc,
                "file_path": f"driver/{driver_file.name}",
            }
        )

    drivers.sort(key=lambda x: x["model"])
    return {"drivers": drivers}


@router.get("/{model}")
async def get_driver_detail(model: str) -> dict[str, Any]:
    global _MODEL_INDEX
    _ensure_driver_dir()

    if _MODEL_INDEX is None:
        _MODEL_INDEX = _build_model_index()

    model_key: str = model.strip().lower()

    path = _MODEL_INDEX.get(model_key)
    if not path:
        raise HTTPException(status_code=404, detail=f"Driver {model} not found")

    data: dict[str, Any] | None = _safe_load_yaml(path)
    if not data:
        raise HTTPException(status_code=500, detail=f"Driver {model} is invalid or cannot be loaded")

    return data
