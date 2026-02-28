"""
Load proctor configuration from an external proctor directory (e.g. ../proctor or /wrk/proctor).
Falls back to the local proctor/ package if the external dir is not found.
"""
import json
import os
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parent
_CACHE = None

# Possible config file names in the external proctor root (FCE-facing settings)
_EXTERNAL_CONFIG_NAMES = ("config.json", "fce_config.json")


def _resolve_external_proctor_root():
    """Resolve the external proctor directory. Returns Path or None."""
    raw = os.environ.get("PROCTOR_DIR", "").strip()
    if raw:
        p = Path(raw)
        if not p.is_absolute():
            p = (_APP_ROOT / p).resolve()
        return p if p.is_dir() else None
    # Default: sibling directory ../proctor (i.e. wrk/proctor when app is wrk/fce_treining)
    sibling = (_APP_ROOT.parent / "proctor").resolve()
    return sibling if sibling.is_dir() else None


def _external_config_path(root: Path):
    """First existing config file in the external proctor root."""
    for name in _EXTERNAL_CONFIG_NAMES:
        p = root / name
        if p.exists():
            return p
    return None


def _external_is_configured(root: Path) -> bool:
    """True if external proctor root looks configured (has backend or config)."""
    if (root / "backend").is_dir():
        return True
    if _external_config_path(root) is not None:
        return True
    return False


def _load_external(root: Path) -> dict:
    """Load config from external proctor root."""
    enabled = True  # directory exists and has backend → consider enabled
    name = "Proctor"
    backend_url = os.environ.get("PROCTOR_BACKEND_URL", "").strip() or "http://localhost:8000"
    frontend_url = os.environ.get("PROCTOR_FRONTEND_URL", "").strip() or "http://localhost:5173"
    exam_code = os.environ.get("PROCTOR_EXAM_CODE", "").strip() or "DEMO"
    config = {
        "enabled": enabled,
        "name": name,
        "root": str(root),
        "backend_url": backend_url.rstrip("/"),
        "frontend_url": frontend_url.rstrip("/"),
        "exam_code": exam_code,
    }
    config_path = _external_config_path(root)
    if config_path:
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                if "enabled" in data:
                    config["enabled"] = bool(data["enabled"])
                if data.get("name"):
                    config["name"] = str(data["name"]).strip()
                if data.get("backend_url"):
                    config["backend_url"] = str(data["backend_url"]).strip().rstrip("/")
                if data.get("frontend_url"):
                    config["frontend_url"] = str(data["frontend_url"]).strip().rstrip("/")
                if data.get("exam_code"):
                    config["exam_code"] = str(data["exam_code"]).strip()
                for k, v in data.items():
                    if k not in ("enabled", "name", "root", "backend_url", "frontend_url", "exam_code"):
                        config[k] = v
        except (json.JSONDecodeError, OSError):
            pass
    # Env overrides
    if os.environ.get("PROCTOR_ENABLED", "").strip().lower() in ("0", "false", "no"):
        config["enabled"] = False
    if os.environ.get("PROCTOR_ENABLED", "").strip().lower() in ("1", "true", "yes"):
        config["enabled"] = True
    if os.environ.get("PROCTOR_NAME", "").strip():
        config["name"] = os.environ.get("PROCTOR_NAME", "").strip()
    if os.environ.get("PROCTOR_BACKEND_URL", "").strip():
        config["backend_url"] = os.environ.get("PROCTOR_BACKEND_URL", "").strip().rstrip("/")
    if os.environ.get("PROCTOR_FRONTEND_URL", "").strip():
        config["frontend_url"] = os.environ.get("PROCTOR_FRONTEND_URL", "").strip().rstrip("/")
    if os.environ.get("PROCTOR_EXAM_CODE", "").strip():
        config["exam_code"] = os.environ.get("PROCTOR_EXAM_CODE", "").strip()
    return config


def _load():
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    external_root = _resolve_external_proctor_root()
    if external_root and _external_is_configured(external_root):
        _CACHE = _load_external(external_root)
        return _CACHE
    # Fallback: local proctor package (same repo)
    try:
        from proctor import get_config as _local_get_config
        _CACHE = _local_get_config()
        _CACHE["root"] = str(_APP_ROOT / "proctor")
        return _CACHE
    except ImportError:
        _CACHE = {"enabled": False, "name": "Proctor", "root": None}
        return _CACHE


def is_configured():
    """Return True if proctor is enabled (mock exam is available)."""
    return _load()["enabled"]


def get_config():
    """Return full proctor config dict (enabled, name, root, and any extra keys)."""
    return dict(_load())
