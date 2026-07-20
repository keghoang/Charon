"""Headless timeout and filesystem-recovery policy for processor runs."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional

from .background_jobs import run_blocking_with_timeout
from .conversion_cache import compute_workflow_hash
from .processor_output import collect_output_artifacts


@dataclass(frozen=True)
class DownloadResult:
    success: bool
    timed_out: bool = False
    error: str = ""


@dataclass(frozen=True)
class HistoryRecoveryResult:
    artifacts: List[Dict[str, Any]]
    prompt_id: str = ""
    error: str = ""


def _completion_timestamp(entry: Dict[str, Any]) -> int:
    messages = entry.get("status", {}).get("messages") or []
    for _name, payload in reversed(messages):
        if isinstance(payload, dict) and "timestamp" in payload:
            try:
                return int(payload["timestamp"])
            except (TypeError, ValueError):
                continue
    return 0


def _history_prompt(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    prompt_field = entry.get("prompt")
    if isinstance(prompt_field, list) and len(prompt_field) >= 3:
        prompt_field = prompt_field[2]
    return prompt_field if isinstance(prompt_field, dict) else None


def _sorted_history(history_map: Dict[str, Any]):
    return sorted(
        history_map.items(),
        key=lambda item: (
            _completion_timestamp(item[1]) if isinstance(item[1], dict) else 0
        ),
        reverse=True,
    )


def _collect_history_outputs(
    entry: Dict[str, Any],
    prompt: Dict[str, Any],
    *,
    ignored_output: Callable[[Optional[str]], bool],
    camera_extensions: Iterable[str],
    model_extensions: Iterable[str],
) -> List[Dict[str, Any]]:
    return collect_output_artifacts(
        entry.get("outputs") or {},
        prompt,
        ignored_output=ignored_output,
        camera_extensions=camera_extensions,
        model_extensions=model_extensions,
    )


def recover_matching_history_artifacts(
    comfy_client: Any,
    prompt_payload: Dict[str, Any],
    current_prompt_id: Optional[str],
    *,
    ignored_output: Callable[[Optional[str]], bool],
    camera_extensions: Iterable[str],
    model_extensions: Iterable[str],
) -> HistoryRecoveryResult:
    """Reuse the newest history output whose prompt matches the current prompt."""
    try:
        prompt_hash = compute_workflow_hash(prompt_payload)
    except Exception as exc:
        return HistoryRecoveryResult([], error=f"Could not hash prompt: {exc}")
    try:
        history_map = comfy_client.get_full_history()
    except Exception as exc:
        return HistoryRecoveryResult([], error=f"Could not read history: {exc}")
    if not isinstance(history_map, dict):
        return HistoryRecoveryResult([])

    for candidate_id, entry in _sorted_history(history_map):
        if candidate_id == current_prompt_id or not isinstance(entry, dict):
            continue
        candidate_prompt = _history_prompt(entry)
        if candidate_prompt is None:
            continue
        try:
            candidate_hash = compute_workflow_hash(candidate_prompt)
        except Exception:
            continue
        if candidate_hash != prompt_hash:
            continue
        artifacts = _collect_history_outputs(
            entry,
            candidate_prompt,
            ignored_output=ignored_output,
            camera_extensions=camera_extensions,
            model_extensions=model_extensions,
        )
        if artifacts:
            return HistoryRecoveryResult(artifacts, prompt_id=str(candidate_id))
    return HistoryRecoveryResult([])


def recover_prefixed_history_artifacts(
    comfy_client: Any,
    expected_prefixes: Iterable[str],
    *,
    ignored_output: Callable[[Optional[str]], bool],
    camera_extensions: Iterable[str],
    model_extensions: Iterable[str],
) -> HistoryRecoveryResult:
    """Reuse recent history outputs matching an expected SaveImage prefix."""
    prefixes = [prefix.lower() for prefix in expected_prefixes if prefix]
    if not prefixes:
        return HistoryRecoveryResult([])
    try:
        history_map = comfy_client.get_full_history()
    except Exception as exc:
        return HistoryRecoveryResult([], error=f"Could not read history: {exc}")
    if not isinstance(history_map, dict):
        return HistoryRecoveryResult([])

    for candidate_id, entry in _sorted_history(history_map):
        if not isinstance(entry, dict):
            continue
        candidate_prompt = _history_prompt(entry) or {}
        artifacts = _collect_history_outputs(
            entry,
            candidate_prompt,
            ignored_output=ignored_output,
            camera_extensions=camera_extensions,
            model_extensions=model_extensions,
        )
        if any(
            str(artifact.get("filename") or "").lower().startswith(prefix)
            for artifact in artifacts
            for prefix in prefixes
        ):
            return HistoryRecoveryResult(artifacts, prompt_id=str(candidate_id))
    return HistoryRecoveryResult([])


def download_with_timeout(
    comfy_client: Any,
    *,
    filename: str,
    destination_path: str,
    subfolder: str,
    file_type: str,
    retries: int,
    retry_delay: float,
    min_bytes: int,
    hard_timeout: float,
) -> DownloadResult:
    """Download one ComfyUI artifact through the shared bounded-job policy."""

    def operation() -> bool:
        return bool(
            comfy_client.download_file(
                filename,
                destination_path,
                subfolder=subfolder,
                file_type=file_type,
                retries=retries,
                retry_delay=retry_delay,
                min_bytes=min_bytes,
            )
        )

    outcome = run_blocking_with_timeout(
        operation,
        timeout=max(1.0, hard_timeout),
        thread_name="charon-download",
    )
    if outcome.timed_out:
        return DownloadResult(success=False, timed_out=True)
    if outcome.error is not None:
        return DownloadResult(success=False, error=str(outcome.error))
    return DownloadResult(success=bool(outcome.value))


def resolve_batch_timeout(
    comfy_client: Any,
    *,
    base_timeout: float,
    grace_per_job: float,
) -> float:
    """Extend a batch timeout by the active and pending ComfyUI queue depth."""
    try:
        queue_data = comfy_client.get_queue_status()
    except Exception:
        queue_data = None
    queued_jobs = 0
    if isinstance(queue_data, dict):
        queued_jobs += len(queue_data.get("queue_pending", []) or [])
        queued_jobs += len(queue_data.get("queue_running", []) or [])
    return float(base_timeout) + float(queued_jobs) * float(grace_per_job)


def resolve_result_watch_timeout(
    batch_count: int,
    *,
    base_timeout: float,
    grace: float,
) -> float:
    """Return the maximum result-watcher lifetime for an execution batch."""
    return float(base_timeout) * max(1, int(batch_count)) + float(grace)


def find_output_by_basename(
    output_root: str,
    filename: str,
    since_time: float,
    *,
    scan_limit: int,
) -> str:
    """Find the newest matching ComfyUI output produced after ``since_time``."""
    if not output_root or not filename or not os.path.isdir(output_root):
        return ""
    target = os.path.basename(filename).lower()
    best_path = ""
    best_mtime = 0.0
    scanned = 0
    for root_dir, _dirs, files in os.walk(output_root):
        for candidate_name in files:
            scanned += 1
            if scan_limit > 0 and scanned > scan_limit:
                return best_path
            if candidate_name.lower() != target:
                continue
            candidate_path = os.path.join(root_dir, candidate_name)
            try:
                modified_at = os.path.getmtime(candidate_path)
            except OSError:
                modified_at = 0.0
            if since_time and modified_at < since_time:
                continue
            if modified_at >= best_mtime:
                best_mtime = modified_at
                best_path = candidate_path
    return best_path


def recover_artifacts_from_output_dir(
    expected_prefixes: Iterable[str],
    output_root: str,
    since_time: float,
    *,
    scan_limit: int,
    image_extensions: Iterable[str],
    camera_extensions: Iterable[str],
    model_extensions: Iterable[str],
) -> List[Dict[str, Any]]:
    """Recover output artifacts when ComfyUI history has no usable entries."""
    if not output_root or not os.path.isdir(output_root):
        return []
    prefixes = [prefix.lower() for prefix in expected_prefixes if prefix]
    if not prefixes:
        return []

    image_exts = set(image_extensions)
    camera_exts = set(camera_extensions)
    model_exts = set(model_extensions)
    found: List[Dict[str, Any]] = []
    scanned = 0
    for root_dir, _dirs, files in os.walk(output_root):
        for candidate_name in files:
            scanned += 1
            if scanned > scan_limit:
                return found
            if not candidate_name or candidate_name.startswith("."):
                continue
            lowered = candidate_name.lower()
            if not any(lowered.startswith(prefix) for prefix in prefixes):
                continue
            candidate_path = os.path.join(root_dir, candidate_name)
            try:
                if since_time and os.path.getmtime(candidate_path) < since_time:
                    continue
            except OSError:
                pass
            extension = os.path.splitext(candidate_name)[1].lower()
            kind = "files"
            if extension in image_exts:
                kind = "images"
            elif extension in camera_exts:
                kind = "camera"
            elif extension in model_exts:
                kind = "meshes"
            found.append(
                {
                    "filename": candidate_path,
                    "subfolder": "",
                    "type": "output",
                    "extension": extension,
                    "node_id": None,
                    "class_type": "",
                    "kind": kind,
                }
            )
    return found
