from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from . import preferences
from .charon_logger import system_error, system_info
from .dependency_check import PREF_DEPENDENCIES_VERIFIED, ensure_manager_security_level
from .paths import resolve_comfy_environment, get_default_comfy_launch_path
from .qt_compat import QtWidgets
from .setup_manager import SetupManager

FIRST_TIME_SETUP_KEY = "first_time_setup_complete"
FORCE_FIRST_TIME_SETUP_KEY = "force_first_time_setup"


def is_force_first_time_setup_enabled() -> bool:
    return bool(preferences.get_preference(FORCE_FIRST_TIME_SETUP_KEY, False))


def set_force_first_time_setup(enabled: bool) -> None:
    preferences.set_preference(FORCE_FIRST_TIME_SETUP_KEY, bool(enabled))
    if enabled:
        system_info("First-time setup will be forced on next launch.")


def is_first_time_setup_complete() -> bool:
    if is_force_first_time_setup_enabled():
        return False
    return bool(preferences.get_preference(FIRST_TIME_SETUP_KEY, False))


def mark_first_time_setup_complete() -> None:
    preferences.set_preference(FIRST_TIME_SETUP_KEY, True)
    preferences.set_preference(FORCE_FIRST_TIME_SETUP_KEY, False)
    if not preferences.get_preference(PREF_DEPENDENCIES_VERIFIED, False):
        preferences.set_preference(PREF_DEPENDENCIES_VERIFIED, True)


def force_first_time_setup_next_run() -> None:
    set_force_first_time_setup(True)


def run_first_time_setup_if_needed(parent=None, force: bool = False) -> bool:
    force_flag = force or is_force_first_time_setup_enabled()
    if not force_flag and is_first_time_setup_complete():
        return True

    try:
        from .ui.first_time_setup_dialog import FirstTimeSetupDialog
    except Exception as exc:
        system_error(f"Could not load first-time setup dialog: {exc}")
        return False

    dialog = FirstTimeSetupDialog(parent)
    result = dialog.exec()

    if result == QtWidgets.QDialog.Accepted and dialog.setup_completed:
        mark_first_time_setup_complete()
        system_info("First-time setup completed and recorded.")
        return True

    system_info("First-time setup canceled or incomplete.")
    return False


def _charon_log_path(comfy_dir: str | None) -> Path | None:
    if not comfy_dir:
        return None
    return Path(comfy_dir) / "user" / "default" / "charon_log.json"


def _write_charon_log(
    log_path: Path | None,
    status_map: Dict[str, str],
    missing: list[str],
    setup_ran: bool,
    ok: bool,
) -> None:
    if not log_path:
        return
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "status_map": status_map,
            "missing": missing,
            "setup_ran": setup_ran,
            "ok": ok,
        }
        log_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception as exc:  # pragma: no cover - defensive
        system_error(f"Failed to write charon_log.json at {log_path}: {exc}")


def ensure_requirements_with_log(parent=None) -> bool:
    """
    Probes requirements using SetupManager.
    - If charon_log.json is missing OR any dependency is missing -> run First-Time Setup (forced).
    - Write charon_log.json with the probe results.
    """
    # OPTIMIZATION: Fast path if already verified
    if (preferences.get_preference(PREF_DEPENDENCIES_VERIFIED, False) and 
        preferences.get_preference(FIRST_TIME_SETUP_KEY, False) and 
        not is_force_first_time_setup_enabled()):
        return True

    # Resolve Comfy environment
    prefs = preferences.load_preferences()
    comfy_path = prefs.get("comfyui_launch_path") or get_default_comfy_launch_path()
    
    # 1. Initialize Manager
    manager = SetupManager(comfy_path)
    comfy_dir = manager.comfy_dir
    log_path = _charon_log_path(comfy_dir)

    # 2. Ensure Security Level (using existing util)
    ensure_manager_security_level("weak", comfy_path_override=comfy_path)

    # 3. Check Status
    status_map = manager.check_dependencies()
    missing = [k for k, v in status_map.items() if v != "found"]

    log_missing = log_path is None or not log_path.exists()
    need_setup = log_missing or bool(missing) or is_force_first_time_setup_enabled()

    setup_ran = False
    setup_ok = True

    if need_setup:
        setup_ran = True
        # If we need setup, we launch the UI which uses the same SetupManager logic to install
        setup_ok = run_first_time_setup_if_needed(parent=parent, force=True)
        
        # Refresh Manager and Status after setup
        prefs = preferences.load_preferences()
        comfy_path = prefs.get("comfyui_launch_path") or get_default_comfy_launch_path()
        manager = SetupManager(comfy_path)
        comfy_dir = manager.comfy_dir
        log_path = _charon_log_path(comfy_dir)
        
        ensure_manager_security_level("weak", comfy_path_override=comfy_path)
        
        status_map = manager.check_dependencies()
        missing = [k for k, v in status_map.items() if v != "found"]

    ok = setup_ok and not missing
    _write_charon_log(log_path, status_map, missing, setup_ran, ok)
    
    if ok:
        preferences.set_preference(PREF_DEPENDENCIES_VERIFIED, True)
        
    return ok