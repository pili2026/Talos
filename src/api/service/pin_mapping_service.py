"""
Pin Mapping Service
Read + write operations for pin mapping configs
"""

import logging
from pathlib import Path

import yaml

from api.model.pin_mapping import PinMappingSource
from core.schema.config_metadata import ConfigSource
from core.schema.pin_mapping_schema import PinMappingConfig
from core.util.yaml_manager import YAMLManager

logger = logging.getLogger(__name__)


class PinMappingService:
    def __init__(
        self,
        yaml_manager: YAMLManager,
        template_dir: str | Path = "res/template/pin_mapping",
    ):
        self.yaml_manager = yaml_manager
        self.template_dir = Path(template_dir)

    def list_available_models(self) -> list[str]:
        model_set: set[str] = set()

        override_dir: Path = self.yaml_manager.config_dir / "pin_mapping"
        if override_dir.exists():
            for path in override_dir.glob("*_default.yml"):
                try:
                    config = self.yaml_manager.read_config("pin_mapping", model=path.stem.replace("_default", ""))
                    model_set.add(config.driver_model)
                except Exception as e:
                    logger.warning(f"[PinMappingService] Failed to read override for {path.stem}: {e}")
                    model_set.add(path.stem.replace("_default", ""))

        if self.template_dir.exists():
            for path in self.template_dir.glob("*_default.yml"):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        raw: dict = yaml.safe_load(f)
                    model_set.add(raw.get("driver_model", path.stem.replace("_default", "")))
                except Exception as e:
                    logger.warning(f"[PinMappingService] Failed to read template for {path.stem}: {e}")
                    model_set.add(path.stem.replace("_default", ""))

        return sorted(model_set)

    def get_pin_mapping(self, model: str) -> tuple[PinMappingConfig, str]:
        filename_model: str = self._model_to_filename(model)
        try:
            config = self.yaml_manager.read_config("pin_mapping", model=filename_model)
            return config, PinMappingSource.OVERRIDE
        except FileNotFoundError:
            pass
        return self.get_template(model), PinMappingSource.TEMPLATE

    def get_template(self, model: str) -> PinMappingConfig:
        filename_model: str = self._model_to_filename(model)
        template_path: Path = self.template_dir / f"{filename_model}_default.yml"
        if not template_path.exists():
            raise FileNotFoundError(f"No template found for model: {model}")
        with open(template_path, "r", encoding="utf-8") as f:
            raw: dict = yaml.safe_load(f)
        return PinMappingConfig(**raw)

    def save_pin_mapping(self, model: str, config: PinMappingConfig, modified_by: str = "system") -> PinMappingConfig:
        filename_model: str = self._model_to_filename(model)
        self.yaml_manager.update_config(
            "pin_mapping",
            config,
            config_source=ConfigSource.EDGE,
            modified_by=modified_by,
            model=filename_model,
        )
        return self.yaml_manager.read_config("pin_mapping", model=filename_model)

    def _model_to_filename(self, model: str) -> str:
        candidate = model.lower().replace("-", "_")

        # Check override directory first
        override_dir = self.yaml_manager.config_dir / "pin_mapping"
        if (override_dir / f"{candidate}_default.yml").exists():
            return candidate

        # Check template directory
        if (self.template_dir / f"{candidate}_default.yml").exists():
            return candidate

        # Search both directories for a matching model
        # in case of discrepancies between filename and driver_model field
        for search_dir in [override_dir, self.template_dir]:
            if not search_dir.exists():
                continue
            for path in search_dir.glob("*_default.yml"):
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        raw = yaml.safe_load(f)
                    if raw.get("driver_model") == model:
                        return path.stem.replace("_default", "")
                except Exception:
                    continue

        return candidate  # fallback
