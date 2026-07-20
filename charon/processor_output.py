from __future__ import annotations

import os
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple


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
