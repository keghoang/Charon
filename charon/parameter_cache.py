from __future__ import annotations

import hashlib
import os
from pathlib import Path

from . import preferences
from .workflow_local_store import get_workflow_cache_dir


PARAMETER_CACHE_DIR = "parameter_cache"
PARAMETER_CACHE_FILENAME = "input_mapping_cache.json"


def parameter_cache_directory(workflow_path: str, *, ensure: bool = False) -> str:
    """Return a per-user cache folder for parameter discovery artifacts."""
    absolute_path = os.path.abspath(workflow_path)
    workflow_folder = os.path.dirname(absolute_path)
    try:
        cache_dir = get_workflow_cache_dir(workflow_folder, ensure=ensure)
    except ValueError:
        digest = hashlib.sha1(absolute_path.lower().encode("utf-8")).hexdigest()[:16]
        cache_dir = (
            Path(preferences.get_preferences_root(ensure_dir=ensure))
            / PARAMETER_CACHE_DIR
            / digest
        )
        if ensure:
            cache_dir.mkdir(parents=True, exist_ok=True)
    return str(cache_dir)


def parameter_cache_path(workflow_path: str, *, ensure_parent: bool = False) -> str:
    return os.path.join(
        parameter_cache_directory(workflow_path, ensure=ensure_parent),
        PARAMETER_CACHE_FILENAME,
    )
