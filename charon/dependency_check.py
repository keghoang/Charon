from __future__ import annotations

import configparser
import os
import subprocess
import time
from typing import List, Tuple

from .charon_logger import system_debug, system_error, system_info
from .paths import get_default_comfy_launch_path, resolve_comfy_environment
from . import preferences

PREF_DEPENDENCIES_VERIFIED = "dependencies_verified"

QT_AVAILABLE = False
try:
    from PySide6 import QtWidgets, QtCore  # type: ignore

    QT_AVAILABLE = True
except Exception:
    try:
        from PySide2 import QtWidgets, QtCore  # type: ignore

        QT_AVAILABLE = True
    except Exception:
        QtWidgets = None  # type: ignore
        QtCore = None  # type: ignore


def _module_available(python_exe: str, module_name: str) -> bool:
    try:
        completed = subprocess.run(
            [python_exe, "-c", f"import {module_name}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=15,
        )
        return completed.returncode == 0
    except Exception:
        return False


def _playwright_available(python_exe: str | None) -> bool:
    if not python_exe or not os.path.exists(python_exe):
        return False
    try:
        completed = subprocess.run(
            [python_exe, "-m", "playwright", "--version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=15,
        )
        return completed.returncode == 0
    except Exception:
        return False


def _install_playwright(python_exe: str) -> Tuple[bool, str]:
    commands = [
        [python_exe, "-m", "pip", "install", "playwright"],
        [python_exe, "-m", "playwright", "install", "chromium"],
    ]
    for cmd in commands:
        try:
            label = (
                "Installing Playwright (ComfyUI embedded env)"
                if "pip" in cmd
                else "Installing Playwright Chromium (ComfyUI embedded env)"
            )
            ok, err = _run_command_with_progress(cmd, label, None)
            if not ok:
                raise RuntimeError(err or "Unknown failure")
        except Exception as exc:
            return False, f"Failed to install Playwright via {' '.join(cmd)}: {exc}"
    return True, ""


def _install_trimesh_comfy(python_exe: str, parent_widget=None) -> Tuple[bool, str]:
    try:
        ok, err = _run_command_with_progress(
            [python_exe, "-m", "pip", "install", "trimesh"],
            "Installing trimesh (ComfyUI embedded env)...",
            parent_widget,
        )
        if not ok:
            raise RuntimeError(err or "Unknown failure")
        return True, ""
    except Exception as exc:
        return False, f"Failed to install trimesh via {python_exe}: {exc}"


def _run_command_with_progress(cmd: List[str], label: str, parent_widget=None) -> Tuple[bool, str]:
    """
    Run a subprocess with a simple busy dialog when Qt is available.
    Returns (success, error_message).
    """
    dialog = None
    app = None
    if QT_AVAILABLE and QtWidgets:
        try:
            app = QtWidgets.QApplication.instance()
            dialog = QtWidgets.QProgressDialog(label, None, 0, 0, parent_widget)
            dialog.setWindowTitle("Installing Dependencies")
            dialog.setWindowModality(QtCore.Qt.ApplicationModal)
            dialog.setCancelButton(None)
            dialog.setMinimumDuration(0)
            dialog.show()
            if app:
                app.processEvents(QtCore.QEventLoop.AllEvents, 50)
        except Exception:
            dialog = None

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        while True:
            ret = proc.poll()
            if ret is not None:
                success = ret == 0
                return success, "" if success else f"Command failed: {' '.join(cmd)}"
            if dialog and app:
                try:
                    dialog.setLabelText(label)
                    app.processEvents(QtCore.QEventLoop.AllEvents, 50)
                except Exception:
                    pass
            time.sleep(0.1)
    except Exception as exc:
        return False, str(exc)
    finally:
        if dialog:
            try:
                dialog.close()
            except Exception:
                pass


def ensure_manager_security_level(
    desired_level: str = "weak",
    comfy_path_override: str | None = None,
) -> None:
    """
    Ensure ComfyUI-Manager runs with the configured security level.
    Creates/updates config.ini if the manager is present; no-op on failure.
    """
    try:
        prefs = preferences.load_preferences()
        comfy_path = (
            comfy_path_override
            or prefs.get("comfyui_launch_path")
            or get_default_comfy_launch_path()
        )
        comfy_path = (comfy_path or "").strip()
        if not comfy_path:
            system_debug("Manager security enforcement skipped: no ComfyUI path configured.")
            return

        env = resolve_comfy_environment(comfy_path)
        comfy_dir = env.get("comfy_dir")
        if not comfy_dir or not os.path.isdir(comfy_dir):
            system_debug(
                f"Manager security enforcement skipped: ComfyUI directory not found for {comfy_path}."
            )
            return

        manager_dirs = [
            os.path.join(comfy_dir, "user", "__manager"),
            os.path.join(comfy_dir, "user", "default", "ComfyUI-Manager"),
        ]
        manager_config = None
        for candidate_dir in manager_dirs:
            candidate_cfg = os.path.join(candidate_dir, "config.ini")
            if os.path.exists(candidate_cfg):
                manager_config = candidate_cfg
                break
        if manager_config is None:
            manager_config = os.path.join(manager_dirs[0], "config.ini")

        parser = configparser.ConfigParser()
        if os.path.exists(manager_config):
            parser.read(manager_config, encoding="utf-8")

        if not parser.has_section("default"):
            parser.add_section("default")

        current = parser.get("default", "security_level", fallback="")
        if current.lower() == desired_level.lower():
            system_debug(
                f"Manager security already set to {desired_level} at {manager_config}."
            )
            return

        parser.set("default", "security_level", desired_level)
        os.makedirs(os.path.dirname(manager_config), exist_ok=True)
        with open(manager_config, "w", encoding="utf-8") as handle:
            parser.write(handle)

        system_info(
            f"Enforced ComfyUI-Manager security_level={desired_level} in {manager_config}"
        )
    except Exception as exc:
        system_error(f"Failed to enforce manager security level: {exc}")



