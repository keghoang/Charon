from __future__ import annotations

import json
from typing import Any, Dict, Optional

from .workflow_local_store import migrate_validation_log, workflow_validation_log_path


def load_validation_log(workflow_folder: Optional[str]) -> Dict[str, Any]:
    """
    Load cached validation data for the given workflow folder.
    """
    if not workflow_folder:
        return {}
    migrate_validation_log(workflow_folder)
    log_path = workflow_validation_log_path(workflow_folder, ensure_parent=False)
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
    log_path = workflow_validation_log_path(workflow_folder, ensure_parent=True)
    try:
        with log_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
    except Exception:
        # Silently ignore cache persistence errors; they should not impact runtime.
        return
