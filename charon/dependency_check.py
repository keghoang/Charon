from __future__ import annotations

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


def check_and_prompt(parent=None) -> None:
    """
    Check for ComfyUI dependencies and prompt the user to install when missing.
    Installs occur in the ComfyUI embedded Python environment.
    """
    if preferences.get_preference(PREF_DEPENDENCIES_VERIFIED, False):
        system_debug("Dependency check skipped; previously verified.")
        return

    prefs = preferences.load_preferences()
    comfy_path = prefs.get("comfyui_launch_path") or get_default_comfy_launch_path()
    env = resolve_comfy_environment(comfy_path)
    comfy_python = env.get("python_exe")
    comfy_missing: List[str] = []
    if comfy_python and os.path.exists(comfy_python):
        needs_playwright = not _playwright_available(comfy_python)
        needs_trimesh = not _module_available(comfy_python, "trimesh")
        if needs_playwright:
            comfy_missing.append("playwright (ComfyUI embedded env)")
        if needs_trimesh:
            comfy_missing.append("trimesh (ComfyUI embedded env)")
    else:
        comfy_missing.append("ComfyUI embedded Python not found (set launch path)")

    if not comfy_missing:
        system_info("Dependency check: all optional dependencies already available (trimesh/playwright).")
        preferences.set_preference(PREF_DEPENDENCIES_VERIFIED, True)
        return

    prompt_lines = ["Optional dependencies are missing:", *[f"- {item}" for item in comfy_missing], "", "Install them now?"]
    message = "\n".join(prompt_lines)

    should_install = False
    parent_widget = None
    if QT_AVAILABLE and QtWidgets is not None:
        if parent and isinstance(parent, QtWidgets.QWidget):
            parent_widget = parent
        elif parent and hasattr(parent, "window") and callable(getattr(parent, "window")):
            try:
                candidate = parent.window()
                if isinstance(candidate, QtWidgets.QWidget):
                    parent_widget = candidate
            except Exception:
                parent_widget = None
        if parent_widget is None:
            try:
                app = QtWidgets.QApplication.instance()
                active = getattr(app, "activeWindow", lambda: None)()
                if isinstance(active, QtWidgets.QWidget):
                    parent_widget = active
            except Exception:
                parent_widget = None

        buttons = QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        reply = QtWidgets.QMessageBox.question(
            parent_widget,
            "Install Dependencies",
            message,
            buttons,
            QtWidgets.QMessageBox.Yes,
        )
        should_install = reply == QtWidgets.QMessageBox.Yes
    else:
        system_info(message)
        return

    if not should_install:
        system_info("Dependency check: user declined to install optional dependencies.")
        return

    results: List[str] = []

    if comfy_python and os.path.exists(comfy_python):
        if "playwright" in " ".join(comfy_missing).lower():
            ok, err = _install_playwright(comfy_python)
            if ok:
                system_info("Installed Playwright for ComfyUI.")
                results.append("Playwright: installed (ComfyUI embedded env)")
            else:
                system_error(err)
                results.append(f"Playwright: FAILED ({err})")
        if "trimesh" in " ".join(comfy_missing).lower():
            ok, err = _install_trimesh_comfy(comfy_python, parent_widget)
            if ok:
                system_info("Installed trimesh for ComfyUI.")
                results.append("trimesh: installed (ComfyUI embedded env)")
            else:
                system_error(err)
                results.append(f"trimesh: FAILED ({err})")
    else:
        system_error("ComfyUI embedded Python not found; cannot install dependencies.")
        results.append("Install skipped: ComfyUI embedded Python not found")

    if results:
        summary = "; ".join(results)
        system_info(f"Dependency check results: {summary}")
        if QT_AVAILABLE and QtWidgets is not None:
            try:
                QtWidgets.QMessageBox.information(
                    parent_widget,
                    "Dependency Installation",
                    "\n".join(results),
                )
            except Exception:
                pass

    # Mark verified only when nothing is missing or all installs succeeded.
    if comfy_missing and results:
        failed = any("FAILED" in entry.upper() or "skipped" in entry.lower() for entry in results)
        if not failed:
            preferences.set_preference(PREF_DEPENDENCIES_VERIFIED, True)
