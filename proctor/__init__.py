"""
Proctor configuration for mock exam mode.
Loads settings from proctor/config.json or PROCTOR_ENABLED env var.
"""
import json
import os
from pathlib import Path

_PROCTOR_DIR = Path(__file__).resolve().parent
_CONFIG_PATH = _PROCTOR_DIR / "config.json"
_CACHE = None


def _load():
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    enabled = os.environ.get("PROCTOR_ENABLED", "").strip().lower() in ("1", "true", "yes")
    name = os.environ.get("PROCTOR_NAME", "").strip() or "Proctor"
    config = {"enabled": enabled, "name": name}
    if _CONFIG_PATH.exists():
        try:
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                config["enabled"] = data.get("enabled", config["enabled"])
                if data.get("name"):
                    config["name"] = str(data["name"]).strip()
                for k, v in data.items():
                    if k not in ("enabled", "name"):
                        config[k] = v
        except (json.JSONDecodeError, OSError):
            pass
    _CACHE = config
    return config


def is_configured():
    """Return True if proctor is enabled (mock exam is available)."""
    return _load()["enabled"]


def get_config():
    """Return full proctor config dict (enabled, name, and any extra keys)."""
    return dict(_load())
