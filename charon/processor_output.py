from __future__ import annotations

import json
import os
import re
import time
import uuid
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple


_FRAME_SUFFIX_PATTERN = re.compile(r"\.(\d{4,})(\.[A-Za-z0-9]+)$")


def allocate_result_manifest_path(
    runtime_root: str,
    *,
    timestamp: Optional[int] = None,
    manifest_id: Optional[str] = None,
) -> str:
    """Allocate a unique processor result manifest under the runtime results root."""
    results_dir = os.path.join(runtime_root, "results")
    os.makedirs(results_dir, exist_ok=True)
    created_at = int(time.time()) if timestamp is None else int(timestamp)
    unique_id = (manifest_id or str(uuid.uuid4()))[:8]
    return os.path.join(results_dir, f"charon_result_{created_at}_{unique_id}.json")


def write_result_manifest(path: str, payload: Dict[str, Any]) -> None:
    """Atomically publish a result manifest so watchers never read partial JSON."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    temp_path = f"{path}.tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        os.replace(temp_path, path)
    finally:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception:
            pass


def read_result_manifest(path: str) -> Optional[Dict[str, Any]]:
    """Read a published processor result, or return ``None`` until it is ready."""
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return None
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("Processor result manifest must contain a JSON object.")
    return payload


def resolve_result_entries(payload: Dict[str, Any]) -> Tuple[List[Any], Any]:
    """Normalize legacy single-output and current batched result manifests."""
    entries = payload.get("outputs")
    if not isinstance(entries, list) or not entries:
        entries = [payload]
    total_batches = payload.get("batch_total") or len(entries)
    return entries, total_batches


def limit_output_entries(entries: Iterable[Any], maximum: int) -> Tuple[List[Any], int]:
    """Keep the newest import entries and report how many older entries were dropped."""
    limited = list(entries)
    if maximum <= 0 or len(limited) <= maximum:
        return limited, 0
    dropped = len(limited) - maximum
    return limited[-maximum:], dropped


def cleanup_result_handoff(
    result_path: str,
    rendered_paths: Iterable[str],
    log_debug: Callable,
) -> None:
    """Remove a consumed result manifest while retaining rendered debug inputs."""
    try:
        if os.path.exists(result_path):
            os.remove(result_path)
    except Exception as exc:
        log_debug(f"Could not remove result file: {exc}", "WARNING")
    try:
        for temp_path in list(rendered_paths):
            if os.path.exists(temp_path):
                log_debug(f"Preserved temp file for debugging: {temp_path}")
    except Exception as exc:
        log_debug(f"Could not clean up files: {exc}", "WARNING")


def run_auto_contact_sheet(
    source_node,
    entries: Iterable[Any],
    *,
    enabled: bool,
    write_metadata: Callable,
    create_contact_sheet: Callable,
    log_debug: Callable,
    trace_step: Callable,
) -> bool:
    """Persist batch outputs and optionally create their Nuke contact sheet."""
    trace_step("mainthread_contact_sheet_enter")
    if not enabled:
        log_debug("Auto contact-sheet creation is disabled; skipping.")
        trace_step("mainthread_contact_sheet_skipped")
        return False
    entry_list = list(entries)
    if entry_list:
        try:
            write_metadata("charon/batch_outputs", json.dumps(entry_list))
        except Exception as exc:
            log_debug(f"Failed to write batch outputs metadata: {exc}", "WARNING")
    try:
        create_contact_sheet(source_node)
    except Exception as exc:
        log_debug(f"Contact Sheet creation failed: {exc}", "WARNING")
        trace_step("mainthread_contact_sheet_error", error=str(exc))
        return False
    trace_step("mainthread_contact_sheet_completed")
    return True


def sanitize_output_name(value: str, default: str = "Workflow") -> str:
    text = (value or "").strip() or default
    sanitized = "".join(
        character if character.isalnum() or character in {"_", "-"} else "_"
        for character in text
    )
    return (sanitized.strip("_") or default)[:64]


def is_ignored_output_path(path: Optional[str], ignore_prefix: str) -> bool:
    """Return whether a generated file should be skipped by Charon output import."""
    if not path:
        return False
    base = os.path.basename(str(path)).strip().lower()
    return base.startswith((ignore_prefix or "").lower())


def normalize_download_target(filename: Optional[str], subfolder: Optional[str]) -> Tuple[str, str]:
    """Normalize a Comfy output name and preserve its relative subfolder hint."""
    if not filename:
        return "", (subfolder or "").strip().strip("/\\")
    name = str(filename)
    cleaned = name.replace("\\", "/")
    subfolder_value = (subfolder or "").strip().strip("/\\")
    if os.path.isabs(name):
        return name, subfolder_value
    if "/" in cleaned:
        if not subfolder_value:
            subfolder_value = os.path.dirname(cleaned).strip("/\\")
        return os.path.basename(cleaned), subfolder_value
    return name, subfolder_value


def resolve_local_output_candidate(output_root: str, filename: str, subfolder: str) -> str:
    """Return a local Comfy output candidate without touching the filesystem."""
    if not output_root or not filename:
        return ""
    parts = [output_root]
    if subfolder:
        parts.append(subfolder)
    parts.append(filename)
    return os.path.normpath(os.path.join(*parts))


def summarize_sequence_entries(entries: Iterable[Any]) -> Optional[Dict[str, Any]]:
    """Return frame-sequence info for a group of output entries, or ``None``.

    A group forms a sequence when every entry carries a ``frame`` value and its
    ``output_path`` ends with a ``.<frame>.<ext>`` suffix. The returned dict has
    ``pattern`` (path with the frame digits replaced by ``#`` padding),
    ``first``, ``last``, and ``count``. Groups with fewer than two distinct
    frames are treated as stills.
    """
    frames: List[int] = []
    sample_path = ""
    for entry in entries:
        if not isinstance(entry, dict):
            return None
        frame = entry.get("frame")
        path = entry.get("output_path")
        if frame is None or not path:
            return None
        try:
            frame_number = int(frame)
        except (TypeError, ValueError):
            return None
        frames.append(frame_number)
        if not sample_path or frame_number == min(frames):
            sample_path = str(path)
    unique_frames = sorted(set(frames))
    if len(unique_frames) < 2:
        return None
    normalized = sample_path.replace("\\", "/")
    match = _FRAME_SUFFIX_PATTERN.search(normalized)
    if not match:
        return None
    padding = "#" * len(match.group(1))
    pattern = (
        normalized[: match.start()] + f".{padding}{match.group(2)}"
    )
    return {
        "pattern": pattern,
        "first": unique_frames[0],
        "last": unique_frames[-1],
        "count": len(unique_frames),
    }


def progress_for_batch(batch_index: int, local_progress: float, per_batch_progress: float) -> float:
    """Map progress within one batch onto the overall execution range."""
    local_clamped = max(0.0, min(1.0, local_progress))
    base_value = 0.5 + per_batch_progress * batch_index
    return min(base_value + per_batch_progress * local_clamped, 1.0)


def collect_output_artifacts(
    outputs_map: Any,
    prompt_lookup: Dict[str, Any],
    *,
    ignored_output: Callable[[Optional[str]], bool],
    camera_extensions: Iterable[str],
    model_extensions: Iterable[str],
) -> List[Dict[str, Any]]:
    """Extract file-like artifacts from a ComfyUI history outputs payload."""
    artifacts: List[Dict[str, Any]] = []
    if not isinstance(outputs_map, dict):
        return artifacts
    if not isinstance(prompt_lookup, dict):
        prompt_lookup = {}
    camera_exts = set(camera_extensions)
    model_exts = set(model_extensions)
    for node_id, output_data in outputs_map.items():
        if not isinstance(output_data, dict):
            continue
        class_type = (prompt_lookup.get(node_id) or {}).get("class_type") or ""

        def _append_artifact(path: str, kind: str = "output") -> None:
            if not path:
                return
            extension = (os.path.splitext(path)[1] or "").lower()
            artifacts.append(
                {
                    "filename": path,
                    "subfolder": output_data.get("subfolder") or "",
                    "type": output_data.get("type") or "output",
                    "extension": extension,
                    "node_id": node_id,
                    "class_type": class_type,
                    "kind": kind,
                }
            )

        for key in ("images", "files", "meshes"):
            entries = output_data.get(key)
            if not isinstance(entries, list) or not entries:
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                filename = entry.get("filename")
                if not filename or ignored_output(filename):
                    continue
                artifacts.append(
                    {
                        "filename": filename,
                        "subfolder": entry.get("subfolder") or "",
                        "type": entry.get("type") or "output",
                        "extension": (entry.get("extension") or os.path.splitext(filename)[1] or "").lower(),
                        "node_id": node_id,
                        "class_type": class_type,
                        "kind": key,
                    }
                )
        for value in output_data.values():
            values = [value] if isinstance(value, str) else value if isinstance(value, list) else []
            for item in values:
                if not isinstance(item, str):
                    continue
                candidate = item.strip()
                if ignored_output(candidate):
                    continue
                extension = os.path.splitext(candidate)[1].lower()
                if extension in camera_exts:
                    _append_artifact(candidate, "camera")
                elif extension in model_exts:
                    _append_artifact(candidate, "meshes")
    return artifacts


def is_mesh_output_entry(
    entry: Dict[str, Any],
    *,
    camera_extensions: Iterable[str],
    model_extensions: Iterable[str],
) -> bool:
    """Return whether an imported output should use a geometry node."""
    output_kind = (entry.get("output_kind") or "").upper()
    kind = (entry.get("comfy_output_kind") or "").lower()
    extension = os.path.splitext(str(entry.get("output_path") or ""))[1].lower()
    if extension in set(camera_extensions):
        return False
    return output_kind == "3D" or kind == "meshes" or extension in set(model_extensions)


def is_image_output_entry(
    entry: Dict[str, Any],
    *,
    camera_extensions: Iterable[str],
    model_extensions: Iterable[str],
    image_extensions: Iterable[str],
) -> bool:
    """Return whether an imported output should use an image Read node."""
    if is_mesh_output_entry(
        entry,
        camera_extensions=camera_extensions,
        model_extensions=model_extensions,
    ):
        return False
    output_kind = (entry.get("output_kind") or "").upper()
    kind = (entry.get("comfy_output_kind") or "").lower()
    extension = os.path.splitext(str(entry.get("output_path") or ""))[1].lower()
    return output_kind == "2D" or kind == "images" or extension in set(image_extensions)


def is_camera_output_entry(entry: Dict[str, Any], *, camera_extensions: Iterable[str]) -> bool:
    """Return whether an imported output is a Nuke camera payload."""
    path = (
        entry.get("output_path")
        or entry.get("download_path")
        or entry.get("original_filename")
        or entry.get("extension")
        or ""
    )
    path_text = str(path)
    extension = os.path.splitext(path_text)[1].lower()
    if not extension and path_text.startswith("."):
        extension = path_text.lower()
    return extension in set(camera_extensions)


def output_entry_label(
    entry: Dict[str, Any],
    *,
    camera_extensions: Iterable[str],
    camera_label: str,
    sanitize_name: Callable[[str, str], str],
    default_prefix: str = "Output",
) -> str:
    """Build a stable label for a grouped imported output."""
    extension = os.path.splitext(
        entry.get("output_path")
        or entry.get("download_path")
        or entry.get("original_filename")
        or ""
    )[1].lower()
    if extension in set(camera_extensions):
        return camera_label
    label = (
        entry.get("comfy_node_class")
        or entry.get("class_type")
        or entry.get("original_filename")
        or default_prefix
    )
    node_id = entry.get("comfy_node_id") or entry.get("node_id")
    base = sanitize_name(str(label), default_prefix)
    if node_id:
        base = f"{base}_{sanitize_name(str(node_id), '')}"
    return base
