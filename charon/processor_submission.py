from __future__ import annotations

import copy
import json
from typing import Any, Callable, Dict, Iterable, Tuple


def build_batch_prompt(
    base_prompt: Dict[str, Any],
    *,
    seed_records: Iterable[Dict[str, Any]],
    seed_offset: int,
    apply_seed_offset: Callable[[Dict[str, Any], Iterable[Dict[str, Any]], int], None],
    normalize_model_paths: Callable[[Any], int],
) -> Tuple[Dict[str, Any], int, str]:
    """Create a per-batch prompt payload and its compact JSON representation."""
    prompt_payload = copy.deepcopy(base_prompt)
    records = list(seed_records or [])
    if records:
        apply_seed_offset(prompt_payload, records, seed_offset)
    normalized_paths = normalize_model_paths(prompt_payload)
    prompt_payload_str = json.dumps(prompt_payload, separators=(",", ":"), ensure_ascii=True)
    return prompt_payload, normalized_paths, prompt_payload_str


def submit_prompt_or_raise(
    comfy_client,
    prompt_payload: Dict[str, Any],
    *,
    converted_prompt_path: str = "",
) -> str:
    """Submit a prompt to ComfyUI and raise an actionable error on empty prompt id."""
    prompt_id = comfy_client.submit_workflow(prompt_payload)
    if prompt_id:
        return prompt_id
    save_hint = f" (converted prompt saved to {converted_prompt_path})" if converted_prompt_path else ""
    raise RuntimeError(f"Failed to submit workflow{save_hint}")
