"""
Utilities for loading Charon-style workflow metadata for the Charon panel.

The Charon panel stores lightweight metadata in `.charon.json` files with the
following schema:

{
    "workflow_file": "workflow.json",
    "description": "Short summary shown in the metadata pane.",
    "min_vram_gb": "24 GB",
    "dependencies": [
        {"name": "charon-core", "repo": "https://github.com/example/charon-core", "ref": "main"}
    ],
    "last_changed": "2025-10-18T16:32:00Z",
    "tags": ["comfy", "grading", "FLUX"]
}

This module parses the structure and produces a dictionary that the existing UI
can consume while keeping the raw Charon metadata available under `charon_meta`
for callers that need direct access.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from .charon_logger import system_debug

CHARON_METADATA_FILENAME = ".charon.json"

CHARON_DEFAULTS: Dict[str, Any] = {
    "workflow_file": "workflow.json",
    "description": "Describe this workflow.",
    "min_vram_gb": None,
    "dependencies": [],
    "last_changed": None,
    "tags": [],
    "parameters": [],
    "is_3d_texturing": False,
    "is_3d_texturing_step2": False,
}


def _normalize_dependency(dep) -> Optional[Dict[str, str]]:
    """Normalize a dependency entry into a dict with repo/name/ref keys."""
    repo = ""
    name = ""
    ref = ""

    if isinstance(dep, str):
        repo = dep.strip()
    elif isinstance(dep, dict):
        repo = (dep.get("repo") or dep.get("url") or "").strip()
        name = (dep.get("name") or "").strip()
        ref = (dep.get("ref") or "").strip()
    else:
        return None

    if not repo and not name:
        return None

    if not name:
        parsed = urlparse(repo)
        path = (parsed.path or "").rstrip("/")
        if path:
            name = path.split("/")[-1]
            if name.endswith(".git"):
                name = name[:-4]
    result: Dict[str, str] = {}
    if name:
        result["name"] = name
    if repo:
        result["repo"] = repo
    if ref:
        result["ref"] = ref
    return result or None


def _normalize_dependencies(values) -> List[Dict[str, str]]:
    """Return dependency entries as dictionaries."""
    normalized: List[Dict[str, str]] = []
    for dep in values or []:
        normalized_entry = _normalize_dependency(dep)
        if normalized_entry:
            normalized.append(normalized_entry)
    return normalized


def load_charon_metadata(script_path: str) -> Optional[Dict[str, Any]]:
    """
    Load `.charon.json` if present, producing a dict compatible with the
    downstream UI. Returns None when no Charon metadata exists.
    """
    charon_path = os.path.join(script_path, ".charon.json")
    if not os.path.exists(charon_path):
        return None

    try:
        with open(charon_path, "r", encoding="utf-8-sig") as handle:
            raw_meta = json.load(handle)
    except Exception:
        system_debug(f"Failed to read metadata at {charon_path}")
        return None

    if not isinstance(raw_meta, dict):
        return None

    normalized_dependencies = _normalize_dependencies(raw_meta.get("dependencies"))
    normalized_parameters = _normalize_parameters(raw_meta.get("parameters"))
    raw_vram = raw_meta.get("min_vram_gb")
    if isinstance(raw_vram, (int, float)):
        normalized_vram = f"{raw_vram}".strip()
    elif isinstance(raw_vram, str):
        normalized_vram = raw_vram.strip() or None
    else:
        normalized_vram = None
    stored_meta: Dict[str, Any] = {
        "workflow_file": raw_meta.get("workflow_file") or "workflow.json",
        "description": raw_meta.get("description") or "",
        "min_vram_gb": normalized_vram,
        "dependencies": normalized_dependencies,
        "last_changed": raw_meta.get("last_changed"),
        "tags": list(raw_meta.get("tags") or []),
        "parameters": normalized_parameters,
        "is_3d_texturing": bool(raw_meta.get("is_3d_texturing", False)),
        "is_3d_texturing_step2": bool(raw_meta.get("is_3d_texturing_step2", False)),
    }

    metadata: Dict[str, Any] = {
        "description": stored_meta["description"],
        "workflow_file": stored_meta["workflow_file"],
        "last_changed": stored_meta["last_changed"],
        "tags": stored_meta["tags"],
        "min_vram_gb": stored_meta["min_vram_gb"],
        "is_3d_texturing": stored_meta["is_3d_texturing"],
        "is_3d_texturing_step2": stored_meta["is_3d_texturing_step2"],
        "dependencies": normalized_dependencies,
        "parameters": normalized_parameters,
        "charon_meta": stored_meta,
        "run_on_main": bool(raw_meta.get("run_on_main", False)),
    }
    system_debug(f"Loaded metadata parameters: {normalized_parameters}")

    return metadata


def write_charon_metadata(script_path: str, data: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """
    Write `.charon.json` metadata, merging with defaults when necessary.
    Returns the normalized metadata dictionary (including legacy keys) or None
    if the write fails.
    """
    charon_path = os.path.join(script_path, CHARON_METADATA_FILENAME)
    payload: Dict[str, Any] = CHARON_DEFAULTS.copy()
    if data:
        filtered = {k: v for k, v in data.items() if v is not None}
        if "dependencies" in filtered:
            filtered["dependencies"] = _normalize_dependencies(filtered["dependencies"])
        if "tags" in filtered:
            filtered["tags"] = list(filtered.get("tags") or [])
        if "parameters" in filtered:
            filtered["parameters"] = _normalize_parameters(filtered["parameters"])
        for legacy_key in ("display_name", "entry", "run_on_main", "script_type", "mirror_prints"):
            filtered.pop(legacy_key, None)
        payload.update(filtered)

    try:
        with open(charon_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
    except Exception:
        system_debug(f"Failed to write metadata at {charon_path}")
        return None
    system_debug(f"Wrote metadata parameters: {payload.get('parameters')}")

    return load_charon_metadata(script_path)


def _normalize_parameters(values) -> List[Dict[str, Any]]:
    """Return sanitized parameter entries that can be stored on disk."""
    normalized: List[Dict[str, Any]] = []
    for entry in values or []:
        if not isinstance(entry, dict):
            continue
        node_id = str(entry.get("node_id") or "").strip()
        attribute = str(entry.get("attribute") or "").strip()
        if not node_id or not attribute:
            continue
        label = str(entry.get("label") or "").strip() or attribute
        value_type = str(entry.get("type") or "string").strip().lower() or "string"
        node_name = str(entry.get("node_name") or "").strip()
        spec = {
            "node_id": node_id,
            "node_name": node_name,
            "attribute": attribute,
            "label": label,
            "type": value_type,
            "default": entry.get("default"),
        }
        if "choices" in entry and isinstance(entry["choices"], (list, tuple)):
            spec["choices"] = list(entry["choices"])
        normalized.append(spec)
    return normalized
