"""
Utilities for loading Charon-style workflow metadata inside the Galt clone.

The Charon prototype stores lightweight metadata in `.charon.json` files with the
following schema:

{
    "workflow_file": "workflow.json",
    "display_name": "Speed Grade Diffusion",
    "description": "Short summary shown in the metadata pane.",
    "dependencies": [
        {"name": "charon-core", "repo": "https://...", "ref": "main"},
        ...
    ],
    "last_changed": "2025-10-18T16:32:00Z",
    "tags": ["comfy", "grading", "FLUX"]
}

This module parses the new structure and produces a dictionary that matches the
legacy Galt expectations so that the existing UI continues to function without
a full rewrite. The raw Charon metadata is returned under the `charon_meta`
key for panels that want richer context.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

CHARON_METADATA_FILENAME = ".charon.json"

LEGACY_DEFAULTS: Dict[str, Any] = {
    "software": ["nuke"],
    "entry": None,
    "script_type": "python",
    "run_on_main": False,
    "mirror_prints": True,
    "tags": [],
}

CHARON_DEFAULTS: Dict[str, Any] = {
    "workflow_file": "workflow.json",
    "display_name": "Untitled Workflow",
    "description": "Describe this workflow.",
    "dependencies": [],
    "last_changed": None,
    "tags": [],
}


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

    metadata: Dict[str, Any] = LEGACY_DEFAULTS.copy()
    metadata["tags"] = list(raw_meta.get("tags") or [])
    metadata["charon_meta"] = raw_meta

    # Allow the metadata to opt into main-thread execution if required later.
    metadata["run_on_main"] = bool(raw_meta.get("run_on_main", metadata["run_on_main"]))

    # Preserve backwards compatibility for other parts of the UI.
    metadata["entry"] = raw_meta.get("entry")

    # Expose a friendly name used by the script panel.
    metadata["display_name"] = raw_meta.get("display_name")
    metadata["description"] = raw_meta.get("description")
    metadata["workflow_file"] = raw_meta.get("workflow_file")
    metadata["last_changed"] = raw_meta.get("last_changed")
    metadata["dependencies"] = raw_meta.get("dependencies", [])

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
        payload.update({k: v for k, v in data.items() if v is not None})

    try:
        with open(charon_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
    except Exception:
        return None

    return load_charon_metadata(script_path)
