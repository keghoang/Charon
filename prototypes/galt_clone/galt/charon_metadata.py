"""
Utilities for loading Charon-style workflow metadata inside the Galt clone.

The Charon prototype stores lightweight metadata in `.charon.json` files with the
following schema:

{
    "workflow_file": "workflow.json",
    "description": "Short summary shown in the metadata pane.",
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

CHARON_METADATA_FILENAME = ".charon.json"

CHARON_DEFAULTS: Dict[str, Any] = {
    "workflow_file": "workflow.json",
    "description": "Describe this workflow.",
    "dependencies": [],
    "last_changed": None,
    "tags": [],
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
        return None

    if not isinstance(raw_meta, dict):
        return None

    normalized_dependencies = _normalize_dependencies(raw_meta.get("dependencies"))
    stored_meta: Dict[str, Any] = {
        "workflow_file": raw_meta.get("workflow_file") or "workflow.json",
        "description": raw_meta.get("description") or "",
        "dependencies": normalized_dependencies,
        "last_changed": raw_meta.get("last_changed"),
        "tags": list(raw_meta.get("tags") or []),
    }

    metadata: Dict[str, Any] = {
        "description": stored_meta["description"],
        "workflow_file": stored_meta["workflow_file"],
        "last_changed": stored_meta["last_changed"],
        "tags": stored_meta["tags"],
        "dependencies": normalized_dependencies,
        "charon_meta": stored_meta,
        "run_on_main": bool(raw_meta.get("run_on_main", False)),
    }

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
        for legacy_key in ("display_name", "entry", "run_on_main", "script_type", "mirror_prints"):
            filtered.pop(legacy_key, None)
        payload.update(filtered)

    try:
        with open(charon_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
    except Exception:
        return None

    return load_charon_metadata(script_path)
