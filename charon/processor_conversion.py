from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from .conversion_cache import desired_prompt_path, write_conversion_cache
from .processor_prompt_cache import prompt_path_matches_hash


@dataclass(frozen=True)
class CachedPromptResolution:
    payload: Optional[Dict[str, Any]]
    path: str
    workflow_hash: str


def resolve_existing_folder(path_value: str) -> str:
    if not path_value:
        return ""
    folder = path_value if os.path.isdir(path_value) else os.path.dirname(path_value)
    return folder if folder and os.path.isdir(folder) else ""


def resolve_cached_prompt(
    workflow_data: Dict[str, Any],
    *,
    workflow_hash: Optional[str],
    cached_path: str,
    cached_hash: str,
    is_api_prompt,
    validate_prompt=None,
    store_cache,
    log_debug,
) -> CachedPromptResolution:
    """Resolve a valid node prompt cache or fall back to an API workflow payload."""
    normalized_path = cached_path.strip() if isinstance(cached_path, str) else ""
    normalized_hash = cached_hash.strip() if isinstance(cached_hash, str) else ""
    current_hash = str(workflow_hash or "")

    if (
        current_hash
        and normalized_path
        and not normalized_hash
        and prompt_path_matches_hash(normalized_path, current_hash)
    ):
        normalized_hash = current_hash
        store_cache(normalized_path, normalized_hash)

    if normalized_path and normalized_hash and current_hash and normalized_hash != current_hash:
        log_debug("Cached prompt hash differs from workflow hash; clearing stored prompt")
        store_cache("", "")
        normalized_path = ""
        normalized_hash = ""

    payload = None
    if current_hash and normalized_path and normalized_hash == current_hash:
        if os.path.exists(normalized_path):
            try:
                with open(normalized_path, "r", encoding="utf-8") as cached_handle:
                    candidate = json.load(cached_handle)
                if is_api_prompt(candidate):
                    if validate_prompt is not None:
                        validate_prompt(workflow_data, candidate)
                    payload = candidate
                    log_debug(f"Loaded cached API prompt from {normalized_path}")
                else:
                    log_debug("Cached prompt is not API formatted; ignoring stored prompt", "WARNING")
            except Exception as exc:
                log_debug(f"Failed to read cached prompt: {exc}", "WARNING")
                store_cache("", "")
                normalized_path = ""
                normalized_hash = ""
        else:
            log_debug(f"Cached prompt path missing: {normalized_path}", "WARNING")
            store_cache("", "")
            normalized_path = ""
            normalized_hash = ""

    if is_api_prompt(workflow_data) and payload is None:
        payload = workflow_data
    return CachedPromptResolution(payload, normalized_path, normalized_hash)


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
