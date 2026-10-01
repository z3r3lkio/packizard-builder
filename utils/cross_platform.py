import os
import sys
from pathlib import Path


def _config_root() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))


def get_app_data_dir() -> Path:
    """Return Packizard Builder's cross-platform settings/cache directory."""
    name = "Packizard_Builder" if sys.platform in {"win32", "darwin"} else "packizard_builder"
    return _config_root() / name


def get_legacy_app_data_dir() -> Path:
    """Return the former Lazy_AMPR settings directory for one-time migration."""
    name = "Lazy_AMPR" if sys.platform in {"win32", "darwin"} else "lazy_ampr"
    return _config_root() / name


def normalize_path(path: str) -> Path:
    """Normalize path for cross-platform consistency."""
    return Path(path).expanduser().resolve()
