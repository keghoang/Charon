from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from . import preferences
from .charon_logger import system_error, system_info
from .dependency_check import PREF_DEPENDENCIES_VERIFIED, _module_available
from .paths import resolve_comfy_environment, get_default_comfy_launch_path
from .qt_compat import QtWidgets

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


# --- Dependency probing + logging (charon_log.json) ---

def _requirements_modules() -> list[str]:
    """
    Read top-level requirements (one per line, ignores comments/empties).
    """
    modules: list[str] = []
    try:
        req_path = Path(__file__).resolve().parents[1] / "requirements.txt"
        for line in req_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            modules.append(stripped)
    except Exception as exc:  # pragma: no cover - defensive
        system_error(f"Failed to read requirements.txt: {exc}")
    return modules


def _probe_requirements(python_exe: str | None, modules: list[str]) -> tuple[list[str], list[dict]]:
    """
    Probe required modules inside the ComfyUI embedded Python.
    Returns (missing_modules, probe_results).
    """
    results: list[dict] = []
    missing: list[str] = []
    if not python_exe:
        for name in modules:
            results.append({"name": name, "ok": False, "error": "python_exe missing"})
        missing.extend(modules)
        return missing, results

    for name in modules:
        ok = _module_available(python_exe, name)
        entry: dict = {"name": name, "ok": ok}
        if not ok:
            missing.append(name)
        results.append(entry)
    return missing, results


def _probe_custom_nodes(comfy_dir: str | None) -> tuple[list[str], list[dict]]:
    """
    Check presence of expected custom nodes and manager security level.
    """
    expected_nodes = {
        "ComfyUI-Manager": ("user/default/ComfyUI-Manager",),
        "ComfyUI-KJNodes": ("custom_nodes/ComfyUI-KJNodes",),
        "ComfyUI-Charon": ("custom_nodes/ComfyUI-Charon",),
    }
    results: list[dict] = []
    missing: list[str] = []
    base = Path(comfy_dir) if comfy_dir else None
    for name, rels in expected_nodes.items():
        ok = False
        path = ""
        if base:
            for rel in rels:
                candidate = base / rel
                if candidate.exists():
                    ok = True
                    path = str(candidate)
                    break
        entry = {"name": name, "ok": ok}
        if path:
            entry["path"] = path
        if not ok:
            missing.append(name)
        results.append(entry)

    # Manager security level check
    sec_entry = {"name": "ComfyUI-Manager security_level", "ok": False, "expected": "weak"}
    if base:
        import configparser

        candidates = [
            base / "user" / "default" / "ComfyUI-Manager" / "config.ini",
            base / "user" / "__manager" / "config.ini",
        ]
        for cfg in candidates:
            if cfg.exists():
                try:
                    parser = configparser.ConfigParser()
                    parser.read(cfg, encoding="utf-8")
                    current = parser.get("default", "security_level", fallback="")
                    sec_entry["found"] = current
                    sec_entry["ok"] = current.lower() == "weak"
                    sec_entry["path"] = str(cfg)
                    break
                except Exception as exc:  # pragma: no cover - defensive
                    sec_entry["error"] = str(exc)
    results.append(sec_entry)
    if not sec_entry.get("ok"):
        missing.append("manager_security_level")
    return missing, results


def _charon_log_path(comfy_dir: str | None) -> Path | None:
    if not comfy_dir:
        return None
    return Path(comfy_dir) / "user" / "default" / "charon_log.json"


def _write_charon_log(
    log_path: Path | None,
    results: list[dict],
    custom_nodes: list[dict],
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
            "requirements": results,
            "custom_nodes": custom_nodes,
            "missing": missing,
            "setup_ran": setup_ran,
            "ok": ok,
        }
        log_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception as exc:  # pragma: no cover - defensive
        system_error(f"Failed to write charon_log.json: {exc}")


def ensure_requirements_with_log(parent=None) -> bool:
    """
    Always probe requirements in the embedded Python.
    - If charon_log.json is missing OR any probe fails -> run First-Time Setup (forced), then re-probe.
    - Write charon_log.json with the probe results.
    """
    # Resolve Comfy environment
    prefs = preferences.load_preferences()
    comfy_path = prefs.get("comfyui_launch_path") or get_default_comfy_launch_path()
    env = resolve_comfy_environment(comfy_path)
    comfy_dir = env.get("comfy_dir")
    python_exe = env.get("python_exe")
    log_path = _charon_log_path(comfy_dir)

    modules = _requirements_modules()
    missing_req, results_req = _probe_requirements(python_exe, modules)
    missing_nodes, results_nodes = _probe_custom_nodes(comfy_dir)
    missing = missing_req + missing_nodes

    log_missing = log_path is None or not log_path.exists()
    need_setup = log_missing or bool(missing)

    setup_ran = False
    setup_ok = True

    if need_setup:
        setup_ran = True
        setup_ok = run_first_time_setup_if_needed(parent=parent, force=True)
        # Refresh env in case setup updated paths
        env = resolve_comfy_environment(comfy_path)
        comfy_dir = env.get("comfy_dir")
        python_exe = env.get("python_exe")
        log_path = _charon_log_path(comfy_dir)
        missing_req, results_req = _probe_requirements(python_exe, modules)
        missing_nodes, results_nodes = _probe_custom_nodes(comfy_dir)
        missing = missing_req + missing_nodes

    ok = setup_ok and not missing
    _write_charon_log(log_path, results_req, results_nodes, missing, setup_ran, ok)
    return ok
