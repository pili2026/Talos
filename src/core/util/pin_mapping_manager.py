"""
Pin Mapping Manager for Talos
Responsible for loading and managing pin mapping configurations
"""

from pathlib import Path

from core.schema.pin_mapping_schema import PinMappingConfig
from core.util.config_manager import ConfigManager


class PinMappingManager:
    """Manages loading and access of pin mapping configurations"""

    def __init__(self, base_path: str = "./res/pin_mapping"):
        """
        Initialize PinMappingManager

        Args:
            base_path: Base path for pin mapping configuration files
        """
        self.base_path = Path(base_path)
        self._cache: dict[str, PinMappingConfig] = {}

    def load_pin_mapping(self, driver_model: str, mapping_name: str = "default") -> PinMappingConfig:
        """
        Load the specified pin mapping configuration

        Args:
            driver_model: Driver model (e.g., 'bat08', 'adam4117')
            mapping_name: Mapping name (default is 'default')

        Returns:
            PinMappingConfig: Loaded pin mapping configuration

        Raises:
            FileNotFoundError: Configuration file not found
            ValueError: Invalid configuration file format
        """
        cache_key = f"{driver_model}_{mapping_name}"

        # Check cache
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Build file path: {model}_{mapping_name}.yml
        file_path: Path = self.base_path / f"{driver_model}_{mapping_name}.yml"

        if not file_path.exists():
            raise FileNotFoundError(
                f"Pin mapping file not found: {file_path}\n"
                f"Expected: {self.base_path}/{driver_model}_{mapping_name}.yml"
            )

        # Load YAML
        try:
            pin_mapping_raw: dict = ConfigManager().load_yaml_file(str(file_path))
        except Exception as e:
            raise ValueError(f"Failed to load pin mapping from {file_path}: {e}") from e

        # Validate and build PinMappingConfig
        try:
            pin_mapping_config = PinMappingConfig(**pin_mapping_raw)
        except Exception as e:
            raise ValueError(f"Invalid pin mapping config in {file_path}: {e}") from e

        # Cache result
        self._cache[cache_key] = pin_mapping_config

        return pin_mapping_config

    def clear_cache(self):
        """Clear the cache"""
        self._cache.clear()

    def reload_mapping(self, driver_model: str, mapping_name: str = "default") -> PinMappingConfig:
        """
        Reload the specified pin mapping (force cache refresh)

        Args:
            driver_model: Driver model
            mapping_name: Mapping name

        Returns:
            PinMappingConfig: Reloaded configuration
        """
        cache_key = f"{driver_model}_{mapping_name}"
        if cache_key in self._cache:
            del self._cache[cache_key]

        return self.load_pin_mapping(driver_model, mapping_name)
