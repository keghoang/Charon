from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .charon_logger import system_debug, system_warning
from .workflow_local_store import (
    get_validated_workflow_path,
    load_validation_resolve_status,
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


_RESOLVED_MODEL_STATUSES = {"success", "resolved", "copied"}
_PATH_HINT_PATTERN = re.compile(
    r"([A-Za-z]:[\\/][^\\s]+|\\\\[^\\s]+|models/[^\s]+)", re.IGNORECASE
)


def collect_model_replacements_from_validation(remote_folder: str) -> List[Tuple[str, str]]:
    """
    Derive model path replacements from the cached validation resolve payload.
    """
    if not remote_folder:
        return []

    payload = load_validation_resolve_status(remote_folder)
    if not isinstance(payload, dict):
        return []

    issues = payload.get("issues")
    if not isinstance(issues, list):
        return []

    replacements: List[Tuple[str, str]] = []
    for issue in issues:
        if not isinstance(issue, dict) or issue.get("key") != "models":
            continue
        data = issue.get("data") or {}
        models_root = str(data.get("models_root") or "")
        found_paths = [path for path in data.get("found") or [] if isinstance(path, str)]
        missing_models = data.get("missing_models") or []
        for entry in missing_models:
            replacement = _replacement_for_missing_model(entry, models_root, found_paths)
            if replacement:
                replacements.append(replacement)

    seen: set[Tuple[str, str]] = set()
    unique: List[Tuple[str, str]] = []
    for original, resolved in replacements:
        key = (original.lower(), resolved)
        if key in seen:
            continue
        seen.add(key)
        unique.append((original, resolved))
    return unique


def apply_validation_model_overrides(
    workflow_payload: Any,
    workflow_folder: Optional[str],
) -> Tuple[bool, List[Tuple[str, str]]]:
    """
    Apply resolved model paths from validation cache into the workflow payload.
    """
    if not workflow_folder or not isinstance(workflow_payload, dict):
        return False, []

    replacements = collect_model_replacements_from_validation(workflow_folder)
    if not replacements:
        return False, []

    replaced = replace_workflow_model_paths(workflow_payload, replacements)
    return replaced, replacements


def _replacement_for_missing_model(
    entry: Any,
    models_root: str,
    found_paths: Sequence[str],
) -> Optional[Tuple[str, str]]:
    if not isinstance(entry, dict):
        return None
    status = str(entry.get("resolve_status") or "").strip().lower()
    if status and status not in _RESOLVED_MODEL_STATUSES:
        return None

    original = str(entry.get("name") or "").strip()
    if not original:
        return None

    category = str(entry.get("category") or "").strip()
    path_hint = _match_found_path(original, category, found_paths, models_root)
    if not path_hint:
        path_hint = _extract_path_from_text(entry.get("resolve_method"))
    if not path_hint:
        return None

    resolved_value = _normalize_resolved_value(path_hint, models_root, category)
    normalized_original = _normalize_path(original)
    if not resolved_value or resolved_value == normalized_original:
        return None

    return normalized_original, resolved_value


def _match_found_path(
    original_name: str,
    category: str,
    found_paths: Sequence[str],
    models_root: str,
) -> Optional[str]:
    target_base = os.path.basename(original_name).lower()
    target_category = (category or "").strip().lower()
    best: Optional[str] = None

    for path in found_paths:
        candidate = str(path or "").strip()
        if not candidate:
            continue
        try:
            abs_candidate = os.path.abspath(candidate)
        except Exception:
            abs_candidate = candidate
        if os.path.basename(abs_candidate).lower() != target_base:
            continue
        rel = _relativize_model_path(abs_candidate, models_root)
        rel_lower = rel.lower()
        if target_category and (
            rel_lower.startswith(f"{target_category}/")
            or rel_lower.startswith(f"models/{target_category}/")
        ):
            return abs_candidate
        if best is None:
            best = abs_candidate

    return best


def _normalize_resolved_value(path_value: str, models_root: str, category: str) -> str:
    normalized = _relativize_model_path(path_value, models_root)
    segments = [segment for segment in normalized.split("/") if segment]
    if category:
        cat_lower = category.lower()
        if segments and segments[0].lower() == cat_lower:
            normalized = "/".join(segments[1:]) if len(segments) > 1 else segments[0]
    return _format_for_api_path(normalized)


def _relativize_model_path(path_value: str, models_root: str) -> str:
    normalized = str(path_value or "").strip()
    if not normalized:
        return normalized
    models_root_abs = os.path.abspath(models_root) if models_root else ""

    candidate = normalized
    if models_root_abs:
        trimmed = normalized
        lowered = normalized.lower()
        if lowered.startswith("models/"):
            parts = normalized.split("/", 1)
            trimmed = parts[1] if len(parts) > 1 else ""
        if not os.path.isabs(normalized):
            candidate = os.path.join(models_root_abs, trimmed) if trimmed else models_root_abs
        candidate = os.path.abspath(candidate)
    try:
        abs_path = os.path.abspath(candidate)
    except Exception:
        abs_path = candidate

    if models_root_abs:
        try:
            rel = os.path.relpath(abs_path, models_root_abs)
            if not rel.startswith(".."):
                normalized = rel.replace("\\", "/")
            else:
                normalized = abs_path.replace("\\", "/")
        except Exception:
            normalized = abs_path.replace("\\", "/")
    else:
        normalized = abs_path.replace("\\", "/")

    if normalized.lower().startswith("models/"):
        parts = normalized.split("/", 1)
        normalized = parts[1] if len(parts) > 1 else normalized
    return normalized


def _extract_path_from_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    match = _PATH_HINT_PATTERN.search(text)
    if match:
        return match.group(1)
    if ":" in text:
        tail = text.split(":", 1)[1].strip()
        if tail:
            return tail
    return ""


def _format_for_api_path(value: str) -> str:
    """
    Format a model path for API workflows, using backslashes for relative paths.

    ComfyUI API prompts expect backslashes in some relative model references
    (e.g., ``qwen\qwen_image_vae.safetensors``). We only apply the conversion to
    relative paths; absolute/UNC paths are left untouched.
    """
    normalized = value.replace("\\", "/").strip()
    if not normalized:
        return normalized

    # Preserve UNC or absolute drive paths as-is.
    if normalized.startswith("//"):
        return normalized
    head = normalized.split("/", 1)[0]
    if ":" in head:
        return normalized

    # Use single backslashes between segments (JSON encoding will escape them).
    return normalized.replace("/", "\\")
