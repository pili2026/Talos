from pathlib import Path
from util.config_manager import ConfigManager


class PathSelector:
    """Path Selector (reads from config file)"""

    @staticmethod
    def select_state_directory() -> Path:
        """
        Select state directory from system_config.yml (PATHS.STATE_DIR).

        Rules:
        - Absolute path: use directly
        - Relative path: always relative to the *project root* (the level containing src/)
        - Fallback on failure: <project_root>/logs/state
        """
        default_rel = Path("logs/state")

        try:
            project_root: Path = PathSelector._get_project_root()
            config_path: Path = project_root / "res" / "system_config.yml"

            config = ConfigManager.load_yaml_file(str(config_path))
            state_dir_str = config.get("PATHS", {}).get("STATE_DIR", str(default_rel))

            state_dir = Path(state_dir_str)
            if not state_dir.is_absolute():
                state_dir = project_root / state_dir

            return state_dir.resolve()
        except Exception:
            # Final fallback
            return (PathSelector._best_effort_root() / default_rel).resolve()

    @staticmethod
    def _get_project_root() -> Path:
        """
        Search upwards for the first directory containing a 'src/' subfolder
        and treat it as the project root.
        This ensures /home/.../talos is treated as root, not /home/.../talos/src.
        """
        here = Path(__file__).resolve()
        for parent in here.parents:
            if (parent / "src").is_dir():
                return parent
        # Alternative: if res/system_config.yml exists, use its parent
        for parent in here.parents:
            if (parent / "res" / "system_config.yml").is_file():
                return parent
        # Last resort: fall back to current working directory
        return Path.cwd()

    @staticmethod
    def _best_effort_root() -> Path:
        try:
            return PathSelector._get_project_root()
        except Exception:
            return Path.cwd()
