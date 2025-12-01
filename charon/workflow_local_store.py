from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from . import config, preferences
from .charon_logger import system_debug, system_warning
from .conversion_cache import clear_conversion_cache, compute_workflow_hash

LOCAL_REPO_DIR = "Charon_repo_local"
LOCAL_WORKFLOW_DIR = "workflow"
VALIDATED_FILENAME = "workflow_validated.json"
STATE_FILENAME = "workflow_state.json"
CACHE_DIR_NAME = ".charon_cache"
LEGACY_VALIDATION_CACHE_DIR = "validation_cache"
LEGACY_WORKFLOW_CACHE_DIR = "workflow_cache"
LEGACY_CACHE_SUBDIR = ".charon_cache"
VALIDATION_LOG_FILENAME = "validation_log.json"
RESOLVE_STATUS_FILENAME = "validation_resolve_status.json"


class WorkflowState(Dict[str, Any]):
    """Typed alias for local workflow state dictionaries."""


def _preferences_root(ensure: bool = True) -> str:
    return preferences.get_preferences_root(ensure_dir=ensure)


def get_workflow_cache_dir(remote_folder: str, *, ensure: bool = True) -> Path:
    folder = Path(get_local_workflow_folder(remote_folder, ensure=ensure))
    cache_dir = folder / CACHE_DIR_NAME
    if ensure:
        cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def validation_cache_has_artifacts(remote_folder: str) -> bool:
    cache_root = get_validation_cache_root(remote_folder, ensure=False)
    if not cache_root.exists():
        return False
    try:
        return any(cache_root.iterdir())
    except Exception:
        return False


def _legacy_ui_validation_cache_dir(remote_folder: str) -> Path:
    root = Path(preferences.get_preferences_root(ensure_dir=True)) / LEGACY_VALIDATION_CACHE_DIR
    normalized = os.path.normpath(remote_folder or "").lower()
    workflow_name = os.path.basename(remote_folder.rstrip(os.sep)) if remote_folder else "workflow"
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", workflow_name or "workflow") or "workflow"
    digest = hashlib.sha1(normalized.encode("utf-8", errors="ignore")).hexdigest()[:10]
    return root / f"{safe_name}_{digest}"


def _legacy_validation_cache_dir(remote_folder: str) -> Path:
    root = Path(preferences.get_preferences_root(ensure_dir=True)) / LEGACY_WORKFLOW_CACHE_DIR
    normalized = os.path.normpath(remote_folder or "").lower()
    workflow_name = os.path.basename(remote_folder.rstrip(os.sep)) if remote_folder else "workflow"
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", workflow_name or "workflow") or "workflow"
    digest = hashlib.sha1(normalized.encode("utf-8", errors="ignore")).hexdigest()[:12]
    return root / f"{safe_name}_{digest}" / LEGACY_CACHE_SUBDIR


def workflow_validation_log_path(remote_folder: str, *, ensure_parent: bool = False) -> Path:
    cache_root = get_validation_cache_root(remote_folder, ensure=ensure_parent)
    return cache_root / VALIDATION_LOG_FILENAME


def _legacy_validation_log_path(remote_folder: str) -> Path:
    return _legacy_validation_cache_dir(remote_folder) / VALIDATION_LOG_FILENAME


def migrate_validation_log(remote_folder: str) -> None:
    if not remote_folder:
        return
    new_path = workflow_validation_log_path(remote_folder, ensure_parent=False)
    if new_path.exists():
        return
    legacy_path = _legacy_validation_log_path(remote_folder)
    if not legacy_path.exists():
        return
    try:
        new_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(legacy_path), str(new_path))
        legacy_dir = legacy_path.parent
        try:
            if legacy_dir.exists() and not any(legacy_dir.iterdir()):
                legacy_dir.rmdir()
            parent = legacy_dir.parent
            if parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
        except Exception:
            pass
    except Exception as exc:
        system_warning(f"Failed to migrate validation log for '{remote_folder}': {exc}")


def _local_repo_root(ensure: bool = True) -> str:
    repo_root = os.path.join(_preferences_root(ensure), LOCAL_REPO_DIR)
    if ensure:
        os.makedirs(repo_root, exist_ok=True)
    return repo_root


def get_local_repository_root(ensure: bool = True) -> str:
    """Return the root directory for the per-user Charon repository mirror."""
    return _local_repo_root(ensure)


def get_local_workflow_root(ensure: bool = True) -> str:
    root = os.path.join(_local_repo_root(ensure), LOCAL_WORKFLOW_DIR)
    if ensure:
        os.makedirs(root, exist_ok=True)
    return root


def _relative_workflow_path(remote_folder: str) -> str:
    if not remote_folder:
        raise ValueError("Remote workflow folder is required.")

    source_root = os.path.abspath(config.WORKFLOW_REPOSITORY_ROOT)
    folder_path = os.path.abspath(remote_folder)
    if not folder_path.lower().startswith(source_root.lower()):
        raise ValueError(
            f"Workflow folder '{remote_folder}' is outside the configured repository root."
        )
    rel_path = os.path.relpath(folder_path, source_root)
    return rel_path.strip(".\\/")


def get_local_workflow_folder(remote_folder: str, *, ensure: bool = True) -> str:
    relative = _relative_workflow_path(remote_folder)
    candidate = os.path.join(get_local_workflow_root(ensure=ensure), relative)
    if ensure:
        os.makedirs(candidate, exist_ok=True)
    return candidate


def get_validated_workflow_path(remote_folder: str, *, ensure: bool = True) -> str:
    folder = get_local_workflow_folder(remote_folder, ensure=ensure)
    return os.path.join(folder, VALIDATED_FILENAME)


def _state_path(remote_folder: str, *, ensure: bool = True) -> Path:
    cache_dir = get_workflow_cache_dir(remote_folder, ensure=ensure)
    return cache_dir / STATE_FILENAME


def _legacy_state_path(remote_folder: str) -> Path:
    folder = Path(get_local_workflow_folder(remote_folder, ensure=False))
    return folder / STATE_FILENAME


def load_workflow_state(remote_folder: str) -> WorkflowState:
    path = _state_path(remote_folder, ensure=False)
    if not path.exists():
        legacy = _legacy_state_path(remote_folder)
        if legacy.exists():
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(legacy), str(path))
            except Exception as exc:
                system_warning(f"Failed to migrate workflow state for '{remote_folder}': {exc}")
                path = legacy
    if not path.exists():
        return WorkflowState()
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, dict):
            return WorkflowState(payload)
    except Exception as exc:
        system_warning(f"Failed to read workflow state for '{remote_folder}': {exc}")
    return WorkflowState()


def _write_workflow_state(remote_folder: str, state: WorkflowState) -> WorkflowState:
    path = _state_path(remote_folder, ensure=True)
    try:
        with path.open("w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2)
    except Exception as exc:
        system_warning(f"Failed to persist workflow state for '{remote_folder}': {exc}")
    else:
        legacy = _legacy_state_path(remote_folder)
        if legacy.exists():
            try:
                legacy.unlink()
            except Exception:
                pass
    return state


def _clear_validation_cache(remote_folder: str) -> None:
    log_path = workflow_validation_log_path(remote_folder, ensure_parent=False)
    try:
        if log_path.exists():
            log_path.unlink()
    except Exception as exc:
        system_warning(f"Failed to remove validation log for '{remote_folder}': {exc}")
    legacy_log = _legacy_validation_log_path(remote_folder)
    if legacy_log.exists():
        try:
            legacy_log.unlink()
        except Exception as exc:
            system_warning(f"Failed to remove legacy validation log for '{remote_folder}': {exc}")

    cache_root = get_validation_cache_root(remote_folder, ensure=False)
    resolve_log = cache_root / "validation_resolve_log.json"
    resolve_status = cache_root / RESOLVE_STATUS_FILENAME
    raw_log = cache_root / "validation_result_raw.json"
    for artifact in (resolve_log, resolve_status, raw_log):
        try:
            if artifact.exists():
                artifact.unlink()
        except Exception as exc:
            system_warning(f"Failed to remove validation artifact {artifact}: {exc}")
    try:
        if cache_root.exists() and not any(cache_root.iterdir()):
            cache_root.rmdir()
    except Exception:
        pass

    legacy_dir = _legacy_validation_cache_dir(remote_folder)
    if legacy_dir.exists():
        try:
            shutil.rmtree(legacy_dir)
        except OSError as exc:
            system_warning(f"Failed to clear legacy validation cache at {legacy_dir}: {exc}")


def _clear_local_cache_folder(local_folder: str) -> None:
    cache_dir = Path(local_folder) / CACHE_DIR_NAME
    if not cache_dir.exists():
        return
    try:
        shutil.rmtree(cache_dir)
    except OSError as exc:
        system_warning(f"Failed to clear cache folder {cache_dir}: {exc}")


def purge_local_artifacts(remote_folder: str) -> None:
    local_folder = get_local_workflow_folder(remote_folder, ensure=False)
    if local_folder and os.path.isdir(local_folder):
        _clear_local_cache_folder(local_folder)
        clear_conversion_cache(local_folder)
    _clear_validation_cache(remote_folder)


def clear_validation_artifacts(remote_folder: str) -> None:
    """
    Remove all cached validation artifacts for the given workflow.
    """
    if not remote_folder:
        return
    _clear_validation_cache(remote_folder)
    try:
        validated_path = Path(get_validated_workflow_path(remote_folder, ensure=False))
    except Exception:
        validated_path = None
    if validated_path and validated_path.exists():
        try:
            validated_path.unlink()
        except Exception:
            pass
    state = load_workflow_state(remote_folder)
    if state:
        state['validated'] = False
        state['validated_hash'] = None
        state['validated_at'] = None
        state['local_path'] = state.get('source_path') or ''
        _write_workflow_state(remote_folder, state)


def synchronize_remote_payload(
    remote_folder: str,
    workflow_payload: Dict[str, Any],
    *,
    workflow_path: Optional[str] = None,
) -> Tuple[str, WorkflowState]:
    """
    Ensure the local mirror exists for the provided workflow and refresh state.
    Returns the validated workflow path along with the updated state dictionary.
    """
    if not isinstance(workflow_payload, dict):
        raise ValueError("workflow_payload must be a dictionary.")

    local_path = get_validated_workflow_path(remote_folder, ensure=True)
    state = load_workflow_state(remote_folder)
    new_source_hash = compute_workflow_hash(workflow_payload)
    cache_present = validation_cache_has_artifacts(remote_folder)
    source_hash = state.get("source_hash")
    if source_hash is None:
        source_changed = not cache_present
    else:
        source_changed = source_hash != new_source_hash
    if source_changed:
        system_debug(
            f"[WorkflowSync] Source workflow changed for '{remote_folder}'; "
            "invalidating local cache."
        )
        state["validated"] = False
        state["validated_hash"] = None
        state["validated_at"] = None
        purge_local_artifacts(remote_folder)
        _write_json(local_path, workflow_payload)
    else:
        if not os.path.exists(local_path):
            _write_json(local_path, workflow_payload)

    state["source_hash"] = new_source_hash
    state["source_path"] = workflow_path or state.get("source_path") or ""
    state["local_path"] = local_path
    state["last_synced_at"] = time.time()
    _write_workflow_state(remote_folder, state)
    return local_path, state


def mark_validated_workflow(
    remote_folder: str,
    workflow_payload: Dict[str, Any],
) -> str:
    """
    Persist the validated workflow payload to the local mirror and update state.
    Returns the path to the validated workflow file.
    """
    if not isinstance(workflow_payload, dict):
        raise ValueError("workflow_payload must be a dictionary.")

    local_path = get_validated_workflow_path(remote_folder, ensure=True)
    _write_json(local_path, workflow_payload)
    clear_conversion_cache(os.path.dirname(local_path))

    state = load_workflow_state(remote_folder)
    state["validated"] = True
    state["validated_hash"] = compute_workflow_hash(workflow_payload)
    state["validated_at"] = time.time()
    state["local_path"] = local_path
    _write_workflow_state(remote_folder, state)
    return local_path


def _write_json(path: str, payload: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def write_validation_raw(remote_folder: str, payload: Dict[str, Any], *, overwrite: bool = False) -> None:
    if not remote_folder or not isinstance(payload, dict):
        return
    raw_path = validation_raw_path(remote_folder, ensure_parent=True)
    if raw_path.exists() and not overwrite:
        return
    wrapped = {"payload": _normalize_validation_payload(payload, remote_folder)}
    try:
        with raw_path.open("w", encoding="utf-8") as handle:
            json.dump(wrapped, handle, indent=2)
    except Exception as exc:
        system_warning(f"Failed to write validation raw payload for '{remote_folder}': {exc}")


def append_validation_resolve_entry(remote_folder: str, entry: Dict[str, Any]) -> None:
    if not remote_folder or not isinstance(entry, dict):
        return
    log_path = validation_resolve_log_path(remote_folder, ensure_parent=True)
    try:
        if log_path.exists():
            with log_path.open("r", encoding="utf-8") as handle:
                existing = json.load(handle)
            if not isinstance(existing, list):
                existing = []
        else:
            existing = []
    except Exception:
        existing = []

    entry_payload = dict(entry)
    entry_payload.setdefault("timestamp", time.time())
    existing.append(entry_payload)

    try:
        with log_path.open("w", encoding="utf-8") as handle:
            json.dump(existing, handle, indent=2)
    except Exception as exc:
        system_warning(f"Failed to append validation resolve log for '{remote_folder}': {exc}")


def get_validation_cache_root(remote_folder: str, *, ensure: bool = True) -> Path:
    folder = Path(get_local_workflow_folder(remote_folder, ensure=ensure))
    cache_root = folder / CACHE_DIR_NAME / "validation"
    if ensure:
        cache_root.mkdir(parents=True, exist_ok=True)
    return cache_root


def validation_raw_path(remote_folder: str, *, ensure_parent: bool = False) -> Path:
    cache_root = get_validation_cache_root(remote_folder, ensure=ensure_parent)
    return cache_root / "validation_result_raw.json"


def validation_resolve_status_path(remote_folder: str, *, ensure_parent: bool = False) -> Path:
    cache_root = get_validation_cache_root(remote_folder, ensure=ensure_parent)
    return cache_root / RESOLVE_STATUS_FILENAME


def validation_resolve_log_path(remote_folder: str, *, ensure_parent: bool = False) -> Path:
    cache_root = get_validation_cache_root(remote_folder, ensure=ensure_parent)
    return cache_root / "validation_resolve_log.json"


def _normalize_custom_node_missing_entry(pack: Dict[str, Any], *, include_resolve: bool = False) -> Dict[str, Any]:
    normalized = dict(pack or {})
    if not include_resolve:
        normalized.pop("resolve_status", None)
        normalized.pop("resolve_method", None)
        normalized.pop("resolve_failed", None)
    status_from_nodes = {"resolve_status": "", "resolve_method": "", "resolve_failed": ""}
    nodes = []
    for node in normalized.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        if not include_resolve:
            node = {k: v for k, v in node.items() if k not in {"resolve_status", "resolve_method", "resolve_failed"}}
        node_status = str(node.get("resolve_status") or "").strip()
        node_method = str(node.get("resolve_method") or "").strip()
        node_failed = str(node.get("resolve_failed") or "").strip()
        if node_status and not status_from_nodes["resolve_status"]:
            status_from_nodes = {
                "resolve_status": node_status,
                "resolve_method": node_method if node_status == "success" else "",
                "resolve_failed": node_failed if node_status == "failed" else "",
            }
        entry = {
            "class_type": node.get("class_type"),
            "id": node.get("id"),
        }
        nodes.append(entry)
    normalized_status = str(normalized.get("resolve_status") or status_from_nodes["resolve_status"] or "").strip()
    if include_resolve:
        normalized["resolve_status"] = normalized_status
        normalized["resolve_method"] = (
            str(normalized.get("resolve_method") or status_from_nodes["resolve_method"] or "").strip()
            if normalized_status == "success"
            else ""
        )
        normalized["resolve_failed"] = (
            str(normalized.get("resolve_failed") or status_from_nodes["resolve_failed"] or "").strip()
            if normalized_status == "failed"
            else ""
        )
    else:
        normalized.pop("resolve_status", None)
        normalized.pop("resolve_method", None)
        normalized.pop("resolve_failed", None)
    normalized["nodes"] = nodes
    return normalized


def _normalize_model_missing_entry(entry: Dict[str, Any], models_root: str, *, include_resolve: bool = False) -> Dict[str, Any]:
    normalized = dict(entry or {})
    if not include_resolve:
        normalized.pop("resolve_status", None)
        normalized.pop("resolve_method", None)
        normalized.pop("resolve_failed", None)
    dirs: list[str] = []
    for path in normalized.get("attempted_directories") or []:
        if not isinstance(path, str):
            continue
        abs_path = os.path.abspath(path if os.path.isabs(path) else os.path.join(models_root, path))
        dirs.append(abs_path)
    if dirs:
        normalized["attempted_directories"] = dirs
    if include_resolve:
        normalized_status = str(normalized.get("resolve_status") or "").strip()
        normalized["resolve_status"] = normalized_status
        normalized["resolve_method"] = (
            str(normalized.get("resolve_method") or "").strip() if normalized_status == "success" else ""
        )
        normalized["resolve_failed"] = (
            str(normalized.get("resolve_failed") or "").strip() if normalized_status == "failed" else ""
        )
    else:
        normalized.pop("resolve_status", None)
        normalized.pop("resolve_method", None)
        normalized.pop("resolve_failed", None)
    return normalized


def _build_resolve_status_payload(raw_payload: Dict[str, Any], remote_folder: str) -> Dict[str, Any]:
    payload = _normalize_validation_payload(raw_payload, remote_folder, include_resolve=True)
    issues = payload.get("issues") if isinstance(payload, dict) else None
    if isinstance(issues, list):
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            key = issue.get("key")
            data = issue.get("data") or {}
            if not isinstance(data, dict):
                continue
            if key == "custom_nodes":
                missing = data.get("missing_packs") or []
                data.pop("raw_missing", None)
                data.pop("missing", None)
                normalized_packs = []
                if isinstance(missing, list):
                    for pack in missing:
                        if not isinstance(pack, dict) or "nodes" not in pack:
                            continue
                        normalized_packs.append(_normalize_custom_node_missing_entry(pack, include_resolve=True))
                if normalized_packs:
                    data["missing_packs"] = normalized_packs
            if key == "models":
                models_root = data.get("models_root") or ""
                if not isinstance(models_root, str):
                    models_root = ""
                missing_models = data.get("missing") or []
                normalized_missing = []
                for entry in missing_models:
                    if not isinstance(entry, dict):
                        continue
                    normalized_missing.append(_normalize_model_missing_entry(entry, models_root, include_resolve=True))
                if normalized_missing:
                    data["missing"] = normalized_missing
                else:
                    data.pop("missing", None)
    return {"payload": payload}


EXPECTED_MODEL_CATEGORIES = [
    "audio_encoders",
    "checkpoints",
    "classifiers",
    "clip_vision",
    "configs",
    "controlnet",
    "diffusers",
    "diffusion_models",
    "embeddings",
    "gligen",
    "hypernetworks",
    "latent_upscale_models",
    "loras",
    "model_patches",
    "photomaker",
    "style_models",
    "text_encoders",
    "upscale_models",
    "vae",
    "vae_approx",
]


def _normalize_validation_payload(
    payload: Dict[str, Any], remote_folder: str, *, include_resolve: bool = False
) -> Dict[str, Any]:
    """
    Enforce the agreed validation schema for raw payloads before writing to disk.
    """
    comfy_path = ""
    comfy_dir = ""
    try:
        comfy_dir = payload.get("comfy_path") or ""
        comfy_path = comfy_dir
    except Exception:
        comfy_dir = ""
    if not comfy_path and comfy_dir:
        comfy_path = comfy_dir

    issues = payload.get("issues") if isinstance(payload, dict) else []
    normalized_issues: list[dict] = []
    for issue in issues or []:
        if not isinstance(issue, dict):
            continue
        key = issue.get("key")
        if key not in {"custom_nodes", "models"}:
            continue
        data = issue.get("data") or {}
        if not isinstance(data, dict):
            data = {}
        if key == "custom_nodes":
            missing_packs: list[dict] = []
            missing_source = data.get("missing_packs") or data.get("missing") or []
            for pack in missing_source:
                if not isinstance(pack, dict):
                    continue
                normalized_pack = _normalize_custom_node_missing_entry(
                    pack, include_resolve=include_resolve
                )
                missing_packs.append(normalized_pack)
            norm_data = {
                "missing_packs": missing_packs,
            }
            total_nodes = sum(len(p.get("nodes") or []) for p in missing_packs)
            summary = f"Missing {len(missing_packs)} custom node pack(s) ({total_nodes} nodes total)." if missing_packs else "All custom nodes registered in the active ComfyUI session."
            normalized_issues.append(
                {
                    "key": "custom_nodes",
                    "label": issue.get("label") or "Custom nodes loaded",
                    "ok": bool(not missing_packs),
                    "summary": summary,
                    "details": issue.get("details") or [],
                    "data": norm_data,
                }
            )
        elif key == "models":
            models_root = data.get("models_root") or ""
            if not isinstance(models_root, str):
                models_root = ""
            if not comfy_path and models_root:
                comfy_path = os.path.dirname(models_root)
            model_paths = {}
            raw_paths = data.get("model_paths") if isinstance(data, dict) else {}
            if isinstance(raw_paths, dict):
                for cat, paths in raw_paths.items():
                    if cat not in EXPECTED_MODEL_CATEGORIES and not cat.startswith("custom_nodes"):
                        continue
                    if isinstance(paths, (list, tuple, set)):
                        cleaned = []
                        for path in paths:
                            if not isinstance(path, str):
                                continue
                            if models_root and not os.path.isabs(path):
                                cleaned.append(path.replace("\\", "/"))
                            else:
                                cleaned.append(os.path.abspath(path))
                        if cleaned:
                            model_paths[cat] = cleaned
            # If no paths populated, scan models_root for immediate subdirectories.
            if models_root and os.path.isdir(models_root):
                try:
                    for entry in os.scandir(models_root):
                        if entry.is_dir():
                            rel = entry.name
                            if rel in EXPECTED_MODEL_CATEGORIES and not model_paths.get(rel):
                                model_paths[rel] = [rel]
                except Exception:
                    pass
            # Ensure expected categories exist even if empty lists are omitted by source.
            for cat in EXPECTED_MODEL_CATEGORIES:
                model_paths.setdefault(cat, [])
            # Preserve custom_nodes-related paths if present.
            for cat in list(raw_paths.keys()) if isinstance(raw_paths, dict) else []:
                if cat.startswith("custom_nodes") and cat not in model_paths:
                    model_paths[cat] = raw_paths.get(cat) if isinstance(raw_paths.get(cat), list) else []
            missing_entries = []
            for entry in data.get("missing") or []:
                if isinstance(entry, dict):
                    missing_entries.append(
                        _normalize_model_missing_entry(entry, models_root, include_resolve=include_resolve)
                    )
            found = data.get("found") if isinstance(data, dict) else []
            ok_flag = len(missing_entries) == 0
            summary = (
                "All required model files reported by ComfyUI."
                if ok_flag
                else f"Missing {len(missing_entries)} model file(s)."
            )
            norm_data = {
                "models_root": models_root,
                "model_paths": model_paths,
                "found": found if isinstance(found, list) else [],
            }
            if missing_entries:
                norm_data["missing"] = missing_entries
            normalized_issues.append(
                {
                    "key": "models",
                    "label": issue.get("label") or "Models available",
                    "ok": ok_flag,
                    "summary": summary,
                    "details": [],
                    "data": norm_data,
                }
            )

    normalized_payload = dict(payload)
    normalized_payload["comfy_path"] = comfy_path
    normalized_payload["issues"] = normalized_issues
    # Ensure workflow metadata is well-formed.
    workflow_info = normalized_payload.get("workflow") if isinstance(normalized_payload, dict) else {}
    if not isinstance(workflow_info, dict):
        workflow_info = {}
    folder = workflow_info.get("folder") or remote_folder
    folder_name = os.path.basename(folder.rstrip(os.sep)) if folder else ""
    normalized_payload["workflow"] = {"folder": folder or "", "name": folder_name}
    return normalized_payload


def write_validation_resolve_status(remote_folder: str, payload: Dict[str, Any], *, overwrite: bool = True) -> None:
    if not remote_folder or not isinstance(payload, dict):
        return
    status_path = validation_resolve_status_path(remote_folder, ensure_parent=True)
    if status_path.exists() and not overwrite:
        return
    wrapped = _build_resolve_status_payload(payload, remote_folder)
    try:
        with status_path.open("w", encoding="utf-8") as handle:
            json.dump(wrapped, handle, indent=2)
    except Exception as exc:
        system_warning(f"Failed to write validation resolve status for '{remote_folder}': {exc}")


def load_validation_resolve_status(remote_folder: str) -> Optional[Dict[str, Any]]:
    if not remote_folder:
        return None
    status_path = validation_resolve_status_path(remote_folder, ensure_parent=False)
    if not status_path.exists():
        return None
    try:
        with status_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            payload = data.get("payload")
            if isinstance(payload, dict):
                return payload
            return data
    except Exception as exc:
        system_warning(f"Failed to read validation resolve status for '{remote_folder}': {exc}")
    return None


def reset_local_repository() -> bool:
    """
    Remove and recreate the per-user Charon_repo_local mirror.

    Returns True on success, False when the directory could not be cleared.
    """
    repo_root = Path(_local_repo_root(ensure=False))
    if not repo_root.exists():
        try:
            repo_root.mkdir(parents=True, exist_ok=True)
            (repo_root / LOCAL_WORKFLOW_DIR).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            system_warning(f"Failed to initialize local repository at {repo_root}: {exc}")
            return False
        return True

    try:
        shutil.rmtree(repo_root)
    except OSError as exc:
        system_warning(f"Failed to remove local repository at {repo_root}: {exc}")
        return False

    try:
        repo_root.mkdir(parents=True, exist_ok=True)
        (repo_root / LOCAL_WORKFLOW_DIR).mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        system_warning(f"Failed to recreate local repository at {repo_root}: {exc}")
        return False

    system_debug(f"Reset local repository cache at {repo_root}")
    return True

