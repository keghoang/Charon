from __future__ import annotations

import json
import os
from typing import Any, Dict, Iterable, Optional, Tuple

from .charon_logger import system_debug, system_warning
from .workflow_local_store import (
    get_validated_workflow_path,
    mark_validated_workflow,
)


def workflow_override_path(
    folder_path: str,
    *,
    parent: Optional[object] = None,
    ensure_dir: bool = True,
) -> str:
    return get_validated_workflow_path(folder_path, ensure=ensure_dir)


def save_workflow_override(
    folder_path: str,
    workflow_payload: Dict[str, Any],
    *,
    parent: Optional[object] = None,
) -> str:
    try:
        path = mark_validated_workflow(folder_path, workflow_payload)
    except Exception as exc:
        system_warning(f"Failed to persist validated workflow for '{folder_path}': {exc}")
        raise
    system_debug(f"Wrote workflow override to {path}")
    return path


def load_workflow_override(
    folder_path: str,
    *,
    parent: Optional[object] = None,
) -> Optional[Dict[str, Any]]:
    path = workflow_override_path(folder_path, parent=parent, ensure_dir=False)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, dict):
            return payload
        system_warning(f"Workflow override is not a dict: {path}")
    except Exception as exc:  # pragma: no cover - defensive path
        system_warning(f"Failed to read workflow override {path}: {exc}")
    return None


def replace_workflow_model_paths(
    workflow_payload: Any,
    replacements: Iterable[Tuple[str, str]],
) -> bool:
    """
    Replace model references in the workflow payload.

    Returns True when at least one replacement was applied.
    """
    normalized = [(_normalize_path(src), dst) for src, dst in replacements if src and dst]
    if not normalized:
        return False

    replaced = False

    def _walk(value: Any) -> Any:
        nonlocal replaced
        if isinstance(value, dict):
            for key, entry in list(value.items()):
                value[key] = _walk(entry)
            return value
        if isinstance(value, list):
            for index, entry in enumerate(list(value)):
                value[index] = _walk(entry)
            return value
        if isinstance(value, str):
            candidate = _normalize_path(value)
            for original, replacement in normalized:
                if candidate == original:
                    replaced = True
                    return replacement
        return value

    _walk(workflow_payload)
    return replaced


def _normalize_path(value: str) -> str:
    return value.replace("\\", "/").strip()
