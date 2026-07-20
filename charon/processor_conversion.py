from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional, Tuple

from .conversion_cache import desired_prompt_path, write_conversion_cache


def load_cached_prompt_payload(cache_hit: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    """Load a converted API prompt from a conversion-cache entry."""
    prompt_path = str(cache_hit.get("prompt_path") or "")
    if not prompt_path:
        raise ValueError("Conversion cache entry is missing prompt_path.")
    with open(prompt_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Cached prompt payload is not a dictionary: {prompt_path}")
    return payload, prompt_path.replace("\\", "/")


def write_converted_prompt_payload(
    converted_prompt: Dict[str, Any],
    *,
    workflow_cache_folder: str,
    workflow_path: str,
    workflow_hash: Optional[str],
    temp_root: str,
    current_run_id: str,
) -> str:
    """Persist a converted prompt to the conversion cache or debug fallback."""
    if workflow_hash and workflow_cache_folder:
        target_path = desired_prompt_path(workflow_cache_folder, workflow_path or "", workflow_hash)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with open(target_path, "w", encoding="utf-8") as handle:
            json.dump(converted_prompt, handle, indent=2)
        stored_path = write_conversion_cache(
            workflow_cache_folder,
            workflow_path or "",
            workflow_hash,
            str(target_path),
        )
        return stored_path.replace("\\", "/")

    debug_dir = os.path.join(temp_root, "debug")
    os.makedirs(debug_dir, exist_ok=True)
    fallback_path = os.path.join(debug_dir, f"converted_{current_run_id}.json")
    with open(fallback_path, "w", encoding="utf-8") as handle:
        json.dump(converted_prompt, handle, indent=2)
    return fallback_path.replace("\\", "/")
