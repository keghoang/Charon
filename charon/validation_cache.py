from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Optional

from . import preferences

CACHE_ROOT_DIR = "workflow_cache"
CACHE_SUBDIR = ".charon_cache"
VALIDATION_LOG_NAME = "validation_log.json"


def _workflow_cache_dir(workflow_folder: str, *, ensure: bool = False) -> Path:
    """
    Return the per-workflow cache directory inside the user preferences tree.
    """
    root = Path(preferences.get_preferences_root(ensure_dir=True))
    safe_name = Path(workflow_folder).name or "workflow"
    digest = hashlib.sha1(workflow_folder.encode("utf-8", "ignore")).hexdigest()[:12]
    cache_dir = root / CACHE_ROOT_DIR / f"{safe_name}_{digest}" / CACHE_SUBDIR
    if ensure:
        cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def get_validation_log_path(workflow_folder: str, *, ensure_parent: bool = False) -> Path:
    """
    Return the filesystem path for the validation log.
    """
    cache_dir = _workflow_cache_dir(workflow_folder, ensure=ensure_parent)
    return cache_dir / VALIDATION_LOG_NAME


def load_validation_log(workflow_folder: Optional[str]) -> Dict[str, Any]:
    """
    Load cached validation data for the given workflow folder.
    """
    if not workflow_folder:
        return {}
    log_path = get_validation_log_path(workflow_folder, ensure_parent=False)
    if not log_path.exists():
        return {}
    try:
        with log_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            return data
    except Exception:
        return {}
    return {}


def save_validation_log(workflow_folder: Optional[str], payload: Dict[str, Any]) -> None:
    """
    Persist validation data for the given workflow folder.
    """
    if not workflow_folder:
        return
    log_path = get_validation_log_path(workflow_folder, ensure_parent=True)
    try:
        with log_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
    except Exception:
        # Silently ignore cache persistence errors; they should not impact runtime.
        return
