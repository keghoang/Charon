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
UI_STATUS_FILENAME = "validation_status.json"
LEGACY_UI_STATUS_FILENAME = "status.json"
VALIDATION_LOG_FILENAME = "validation_log.json"


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


def ui_validation_status_path(remote_folder: str, *, ensure_parent: bool = False) -> Path:
    cache_root = get_validation_cache_root(remote_folder, ensure=ensure_parent)
    return cache_root / UI_STATUS_FILENAME


def _legacy_ui_status_path(remote_folder: str) -> Path:
    return _legacy_ui_validation_cache_dir(remote_folder) / LEGACY_UI_STATUS_FILENAME


def _migrate_ui_validation_status(remote_folder: str) -> None:
    if not remote_folder:
        return
    new_path = ui_validation_status_path(remote_folder, ensure_parent=False)
    if new_path.exists():
        return
    legacy_path = _legacy_ui_status_path(remote_folder)
    if not legacy_path.exists():
        return
    try:
        new_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(legacy_path), str(new_path))
        # Remove emptied legacy directory if possible
        legacy_dir = legacy_path.parent
        if legacy_dir.exists() and not any(legacy_dir.iterdir()):
            legacy_dir.rmdir()
    except Exception as exc:
        system_warning(f"Failed to migrate validation status for '{remote_folder}': {exc}")


def load_ui_validation_status(remote_folder: str) -> Optional[Dict[str, Any]]:
    if not remote_folder:
        return None
    _migrate_ui_validation_status(remote_folder)
    status_path = ui_validation_status_path(remote_folder, ensure_parent=False)
    legacy_local_status = status_path.with_name(LEGACY_UI_STATUS_FILENAME)
    if not status_path.exists() and legacy_local_status.exists():
        try:
            legacy_local_status.rename(status_path)
        except Exception as exc:
            system_warning(
                f"Failed to rename legacy validation status for '{remote_folder}': {exc}"
            )
            status_path = legacy_local_status
    if not status_path.exists():
        return None
    try:
        with status_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, dict):
            state = payload.get("state")
            if isinstance(state, str):
                return payload
    except Exception as exc:
        system_warning(f"Failed to read validation status for '{remote_folder}': {exc}")
    return None


def save_ui_validation_status(remote_folder: str, state: str, payload: Any) -> None:
    if not remote_folder or not isinstance(state, str):
        return
    status_path = ui_validation_status_path(remote_folder, ensure_parent=True)
    data = {"state": state, "payload": payload}
    try:
        with status_path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
    except Exception as exc:
        system_warning(f"Failed to write validation status for '{remote_folder}': {exc}")
        return
    legacy_local_status = status_path.with_name(LEGACY_UI_STATUS_FILENAME)
    if legacy_local_status.exists():
        try:
            legacy_local_status.unlink()
        except Exception:
            pass
    legacy_path = _legacy_ui_status_path(remote_folder)
    if legacy_path.exists():
        try:
            legacy_path.unlink()
        except Exception:
            pass
        legacy_dir = legacy_path.parent
        try:
            if legacy_dir.exists() and not any(legacy_dir.iterdir()):
                legacy_dir.rmdir()
        except Exception:
            pass


def clear_ui_validation_status(remote_folder: str) -> None:
    if not remote_folder:
        return
    status_path = ui_validation_status_path(remote_folder, ensure_parent=False)
    try:
        if status_path.exists():
            status_path.unlink()
    except Exception as exc:
        system_warning(f"Failed to remove validation status for '{remote_folder}': {exc}")
    # Attempt to clean empty directory
    parent = status_path.parent
    try:
        if parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
    except Exception:
        pass
    # Remove legacy artifacts if they remain
    legacy_local_status = status_path.with_name(LEGACY_UI_STATUS_FILENAME)
    if legacy_local_status.exists():
        try:
            legacy_local_status.unlink()
        except Exception:
            pass
    legacy_dir = _legacy_ui_validation_cache_dir(remote_folder)
    if legacy_dir.exists():
        try:
            shutil.rmtree(legacy_dir)
        except OSError as exc:
            system_warning(f"Failed to clear legacy UI validation cache at {legacy_dir}: {exc}")


def _local_repo_root(ensure: bool = True) -> str:
    repo_root = os.path.join(_preferences_root(ensure), LOCAL_REPO_DIR)
    if ensure:
        os.makedirs(repo_root, exist_ok=True)
    return repo_root


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
    raw_log = cache_root / "validation_result_raw.json"
    for artifact in (resolve_log, raw_log):
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
    _clear_ui_validation_cache(remote_folder)


def clear_validation_artifacts(remote_folder: str) -> None:
    """
    Remove all cached validation artifacts for the given workflow.
    """
    if not remote_folder:
        return
    _clear_validation_cache(remote_folder)
    clear_ui_validation_status(remote_folder)
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


def _clear_ui_validation_cache(remote_folder: str) -> None:
    """
    Remove the UI validation cache (script panel) associated with the workflow.
    """
    clear_ui_validation_status(remote_folder)


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
    wrapped = {
        "recorded_at": time.time(),
        "payload": payload,
    }
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


def validation_resolve_log_path(remote_folder: str, *, ensure_parent: bool = False) -> Path:
    cache_root = get_validation_cache_root(remote_folder, ensure=ensure_parent)
    return cache_root / "validation_resolve_log.json"

