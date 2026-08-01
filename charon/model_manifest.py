"""Versioned workflow model manifests for portable shared-model installs."""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, Iterable, List, Optional

from .json_io import atomic_write_json
from .path_safety import ensure_path_inside


MODEL_MANIFEST_FILENAME = ".charon.models.json"
MODEL_MANIFEST_SCHEMA = 1


def model_manifest_path(workflow_folder: str) -> str:
    return os.path.join(os.path.abspath(workflow_folder), MODEL_MANIFEST_FILENAME)


def load_model_manifest(workflow_folder: Optional[str]) -> Dict[str, Any]:
    if not workflow_folder:
        return {"schema": MODEL_MANIFEST_SCHEMA, "models": []}
    path = model_manifest_path(workflow_folder)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError, TypeError):
        return {"schema": MODEL_MANIFEST_SCHEMA, "models": []}
    if not isinstance(payload, dict) or payload.get("schema") != MODEL_MANIFEST_SCHEMA:
        return {"schema": MODEL_MANIFEST_SCHEMA, "models": []}
    models = payload.get("models")
    if not isinstance(models, list):
        models = []
    return {
        "schema": MODEL_MANIFEST_SCHEMA,
        "models": [dict(entry) for entry in models if isinstance(entry, dict)],
    }


def write_model_manifest(
    workflow_folder: str,
    entries: Iterable[Dict[str, Any]],
) -> str:
    normalized: List[Dict[str, Any]] = []
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = os.path.basename(str(entry.get("name") or "").strip())
        category = _safe_category(entry.get("category"))
        shared_path = str(entry.get("shared_path") or "").replace("\\", "/").strip("/")
        if not name or not category or not shared_path:
            continue
        key = (name.lower(), category.lower(), shared_path.lower())
        if key in seen:
            continue
        seen.add(key)
        item: Dict[str, Any] = {
            "name": name,
            "category": category,
            "shared_path": shared_path,
        }
        size = entry.get("size")
        if isinstance(size, int) and size >= 0:
            item["size"] = size
        normalized.append(item)
    normalized.sort(
        key=lambda item: (
            str(item.get("name") or "").lower(),
            str(item.get("category") or "").lower(),
        )
    )
    path = model_manifest_path(workflow_folder)
    ensure_path_inside(path, workflow_folder, label="Model manifest")
    atomic_write_json(
        path,
        {"schema": MODEL_MANIFEST_SCHEMA, "models": normalized},
    )
    return path


def manifest_entry_for_name(
    manifest: Dict[str, Any],
    model_name: str,
    category: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    basename = os.path.basename(str(model_name or "")).lower()
    if not basename:
        return None
    matches = []
    for entry in manifest.get("models") or []:
        if not isinstance(entry, dict):
            continue
        if os.path.basename(str(entry.get("name") or "")).lower() == basename:
            matches.append(dict(entry))
    category_lower = str(category or "").lower()
    if category_lower:
        for entry in matches:
            if str(entry.get("category") or "").lower() == category_lower:
                return entry
    return matches[0] if len(matches) == 1 else None


def shared_relative_path(path: str, shared_root: str) -> Optional[str]:
    if not path or not shared_root:
        return None
    try:
        relative = os.path.relpath(os.path.abspath(path), os.path.abspath(shared_root))
    except ValueError:
        return None
    if relative == os.pardir or relative.startswith(os.pardir + os.sep):
        return None
    return relative.replace("\\", "/")


def category_from_shared_path(path: str, shared_root: str) -> Optional[str]:
    relative = shared_relative_path(path, shared_root)
    if not relative or "/" not in relative:
        # A file directly at the shared root has no category folder; without
        # this guard the file name itself would become the category.
        return None
    category = relative.split("/", 1)[0]
    return _safe_category(category) or None


def model_manifest_hash(workflow_folder: str) -> str:
    path = model_manifest_path(workflow_folder)
    try:
        with open(path, "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()
    except OSError:
        return ""


def _safe_category(value: Any) -> str:
    category = str(value or "").strip().replace("\\", "/").strip("/")
    if not category or "/" in category or category in {".", ".."}:
        return ""
    return category
