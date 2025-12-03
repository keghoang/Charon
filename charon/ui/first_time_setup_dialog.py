from __future__ import annotations

import os
import shutil
import subprocess
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import List, Optional, Tuple

from ..qt_compat import QtWidgets, QtGui, QtCore
from ..charon_logger import system_error, system_info, system_warning
from .. import preferences
from ..comfy_client import ComfyUIClient
from ..comfy_restart import send_shutdown_signal
from ..dependency_check import (
    PREF_DEPENDENCIES_VERIFIED,
    _module_available,
    _playwright_available,
)
from ..paths import get_default_comfy_launch_path, resolve_comfy_environment, get_charon_temp_dir

COLORS = {
    "bg_main": "#212529",
    "bg_card": "#17191d",
    "bg_hover": "#3f3f46",
    "text_main": "#f4f4f5",
    "text_sub": "#a1a1aa",
    "danger": "#ef4444",
    "success": "#22c55e",
    "accent": "#3b82f6",
    "border": "#3f3f46",
    "btn_bg": "#27272a",
}

STYLESHEET = f"""
    QDialog {{
        background-color: {COLORS['bg_main']};
        font-family: 'Segoe UI', 'Inter', sans-serif;
    }}
    QLabel {{
        color: {COLORS['text_main']};
        font-size: 14px;
    }}
    QLabel#Heading {{
        font-size: 24px;
        font-weight: 700;
    }}
    QLabel#SubHeading {{
        font-size: 15px;
        color: {COLORS['text_sub']};
    }}
    QLabel#StepLabel {{
        font-size: 16px;
        font-weight: 600;
        margin-bottom: 10px;
    }}
    QLineEdit {{
        background-color: {COLORS['bg_card']};
        border: 1px solid {COLORS['border']};
        border-radius: 6px;
        color: {COLORS['text_sub']};
        padding: 8px 12px;
        font-size: 13px;
    }}
    QLineEdit:focus {{
        border: 1px solid {COLORS['accent']};
        color: {COLORS['text_main']};
    }}
    QProgressBar {{
        background-color: {COLORS['bg_card']};
        border: 1px solid {COLORS['border']};
        border-radius: 6px;
        text-align: center;
        color: transparent;
        height: 12px;
    }}
    QProgressBar::chunk {{
        background-color: {COLORS['success']};
        border-radius: 5px;
    }}
    QPushButton#BrowseBtn {{
        background-color: {COLORS['bg_card']};
        border: 1px solid {COLORS['border']};
        border-radius: 6px;
        color: {COLORS['text_main']};
        padding: 8px 15px;
        font-size: 13px;
    }}
    QPushButton#BrowseBtn:hover {{
        background-color: {COLORS['bg_hover']};
    }}
    QPushButton#FooterBtn {{
        background-color: {COLORS['btn_bg']};
        border: 1px solid {COLORS['border']};
        border-radius: 6px;
        padding: 10px 24px;
        font-size: 14px;
        font-weight: 500;
        color: {COLORS['text_main']};
    }}
    QPushButton#FooterBtn:hover {{
        background-color: {COLORS['bg_hover']};
        border-color: {COLORS['text_sub']};
    }}
    QPushButton#FooterBtn:disabled {{
        color: {COLORS['text_sub']};
        background-color: {COLORS['bg_main']};
        border-color: {COLORS['bg_card']};
    }}
"""


def _run_command_silent(cmd: List[str], timeout: int = 600) -> Tuple[bool, str]:
    try:
        subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
            timeout=timeout,
        )
        return True, ""
    except subprocess.CalledProcessError as exc:
        return False, f"Command failed: {' '.join(cmd)} ({exc.returncode})"
    except Exception as exc:
        return False, str(exc)


def _append_requirements_tasks(
    tasks: List[Tuple[str, List[str]]],
    python_exe: Optional[str],
    node_dir: str,
    label: str,
) -> None:
    """
    After cloning/copying a custom node, enqueue its requirements/install script (if present).
    """
    if not python_exe:
        return
    path = Path(node_dir)
    req_path = path / "requirements.txt"
    tasks.append(
        (
            f"Installing {label} dependencies...",
            [python_exe, "-m", "pip", "install", "-r", str(req_path)],
        )
    )
    install_script = path / "install.py"
    tasks.append(
        (
            f"Running {label} install.py...",
            [python_exe, str(install_script)],
        )
    )


def _has_kjnodes(custom_nodes_dir: str) -> bool:
    """Detect an existing ComfyUI-KJNodes install by folder name."""
    try:
        for entry in os.listdir(custom_nodes_dir):
            path = os.path.join(custom_nodes_dir, entry)
            if os.path.isdir(path) and entry.lower() == "comfyui-kjnodes":
                return True
    except OSError:
        return False
    return False


def _has_manager(custom_nodes_dir: str) -> bool:
    """Detect an existing ComfyUI-Manager install by folder name."""
    try:
        for entry in os.listdir(custom_nodes_dir):
            path = os.path.join(custom_nodes_dir, entry)
            if os.path.isdir(path) and entry.lower() == "comfyui-manager":
                return True
    except OSError:
        return False
    return False


def _download_and_extract_zip(repo_url: str, dest_dir: str, branch: str = "main") -> Tuple[bool, str]:
    """
    Fallback installer when git is unavailable: download a zip archive and unpack it into dest_dir.
    """
    try:
        url = f"{repo_url.rstrip('/')}/archive/refs/heads/{branch}.zip"
        download_root = Path(get_charon_temp_dir()) / "downloads"
        ts = int(time.time())
        download_root.mkdir(parents=True, exist_ok=True)
        zip_path = download_root / f"{Path(dest_dir).name}_{ts}.zip"
        extract_root = download_root / f"{Path(dest_dir).name}_{ts}"
        with urllib.request.urlopen(url) as resp:
            zip_path.write_bytes(resp.read())
        extract_root.mkdir(parents=True, exist_ok=True)
        shutil.unpack_archive(str(zip_path), str(extract_root))
        candidates = [p for p in extract_root.iterdir() if p.is_dir()]
        if not candidates:
            return False, "Downloaded archive missing expected folder."
        src_dir = candidates[0]
        shutil.rmtree(dest_dir, ignore_errors=True)
        shutil.copytree(src_dir, dest_dir)
        return True, ""
    except Exception as exc:
        return False, str(exc)


def _debug_log(message: str) -> None:
    """Append a debug message for setup wizard to the Charon debug folder."""
    try:
        base_dir = get_charon_temp_dir()
        debug_dir = os.path.join(base_dir, "debug")
        os.makedirs(debug_dir, exist_ok=True)
        log_path = os.path.join(debug_dir, "first_time_setup_debug.txt")
        path = Path(log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{message}\n")
    except Exception:
        pass


def _has_comfyui_charon(custom_nodes_dir: str) -> bool:
    """Detect an existing ComfyUI-Charon install by folder name."""
    try:
        for entry in os.listdir(custom_nodes_dir):
            path = os.path.join(custom_nodes_dir, entry)
            if os.path.isdir(path) and entry.lower() == "comfyui-charon":
                return True
    except OSError:
        return False
    return False


class FirstTimeSetupWorker(QtCore.QObject):
    progress_changed = QtCore.Signal(int, str)
    finished = QtCore.Signal(bool, list, str)

    def __init__(self, comfy_path: str):
        super().__init__()
        self.comfy_path = comfy_path

    @QtCore.Slot()
    def run(self) -> None:
        messages: List[str] = []
        error_message = ""

        try:
            _debug_log(f"[start] comfy_path={self.comfy_path}")
            self.progress_changed.emit(5, "Preparing environment...")
            env = resolve_comfy_environment(self.comfy_path)
            python_exe = env.get("python_exe")
            comfy_dir = env.get("comfy_dir")
            _debug_log(f"[env] python_exe={python_exe} comfy_dir={comfy_dir}")
            if not python_exe or not os.path.exists(python_exe):
                msg = "ComfyUI embedded Python not found. Please select the correct run_nvidia_gpu.bat."
                self.finished.emit(False, [], msg)
                return
            git_path = shutil.which("git")
            if not git_path:
                _debug_log("git executable not found; will use zip fallbacks for node installs.")

            custom_nodes_dir = os.path.join(comfy_dir or "", "custom_nodes")
            manager_dir = os.path.join(custom_nodes_dir, "ComfyUI-Manager")
            kjnodes_dir = os.path.join(custom_nodes_dir, "ComfyUI-KJNodes")
            charon_dir = os.path.join(custom_nodes_dir, "ComfyUI-Charon")
            charon_src = Path(__file__).resolve().parents[2] / "custom_nodes" / "comfyUI" / "ComfyUI-Charon"
            missing_manager = False
            missing_kjnodes = False
            missing_charon = False
            if comfy_dir:
                os.makedirs(custom_nodes_dir, exist_ok=True)
                missing_manager = not _has_manager(custom_nodes_dir)
                missing_kjnodes = not _has_kjnodes(custom_nodes_dir)
                missing_charon = not _has_comfyui_charon(custom_nodes_dir)

            needs_playwright = not _playwright_available(python_exe)
            needs_trimesh = not _module_available(python_exe, "trimesh")
            if not needs_playwright:
                messages.append("Playwright already installed (ComfyUI embedded env)")
            if not needs_trimesh:
                messages.append("trimesh already installed (ComfyUI embedded env)")

            statuses = {
                "playwright": "missing" if needs_playwright else "found",
                "trimesh": "missing" if needs_trimesh else "found",
                "manager": "missing" if missing_manager else "found",
                "kjnodes": "missing" if missing_kjnodes else "found",
                "charon": "missing" if missing_charon else "found",
            }

            def _status_lines() -> List[str]:
                return [
                    f"Check Playwright: {statuses['playwright']}",
                    f"Check trimesh: {statuses['trimesh']}",
                    f"Check ComfyUI-Manager: {statuses['manager']}",
                    f"Check KJNodes: {statuses['kjnodes']}",
                    f"Check ComfyUI-Charon: {statuses['charon']}",
                ]

            def _emit_status(progress: int, action: str) -> None:
                lines = _status_lines()
                status_block = "\n".join(lines)
                message = action or ""
                if status_block:
                    if message:
                        message = f"{message}\n{status_block}"
                    else:
                        message = status_block
                _debug_log(f"[progress {progress}] {message}")
                self.progress_changed.emit(progress, message)

            _emit_status(10, "Checking dependencies...")

            tasks: List[Tuple[str, List[str]]] = []

            # Order: Playwright -> trimesh -> ComfyUI-Manager -> KJNodes
            if needs_playwright:
                tasks.append(
                    (
                        "Installing Playwright...",
                        [python_exe, "-m", "pip", "install", "playwright"],
                    )
                )
                tasks.append(
                    (
                        "Installing Playwright Chromium...",
                        [python_exe, "-m", "playwright", "install", "chromium"],
                    )
                )
            if needs_trimesh:
                tasks.append(
                    (
                        "Installing trimesh...",
                        [python_exe, "-m", "pip", "install", "trimesh"],
                    )
                )
            if missing_manager:
                statuses["manager"] = "installing"
                if git_path:
                    tasks.append(
                        (
                            "Cloning ComfyUI-Manager...",
                            [
                                git_path,
                                "clone",
                                "https://github.com/Comfy-Org/ComfyUI-Manager",
                                manager_dir,
                            ],
                        )
                    )
                else:
                    _emit_status(27, "Downloading ComfyUI-Manager (zip)...")
                    ok, err = _download_and_extract_zip(
                        "https://github.com/Comfy-Org/ComfyUI-Manager", manager_dir, branch="main"
                    )
                    _debug_log(f"[download] manager ok={ok} err={err}")
                    if not ok:
                        messages.append(f"ComfyUI-Manager download failed ({err})")
                        statuses["manager"] = "failed"
                        self.finished.emit(False, messages, err or "Failed to download ComfyUI-Manager")
                        return
                    messages.append("Downloaded ComfyUI-Manager (zip)")
                _append_requirements_tasks(tasks, python_exe, manager_dir, "ComfyUI-Manager")
            else:
                messages.append("ComfyUI-Manager already installed")

            if missing_kjnodes:
                statuses["kjnodes"] = "installing"
                if git_path:
                    tasks.append(
                        (
                            "Cloning ComfyUI-KJNodes...",
                            [
                                git_path,
                                "clone",
                                "https://github.com/kijai/ComfyUI-KJNodes",
                                kjnodes_dir,
                            ],
                        )
                    )
                else:
                    _emit_status(33, "Downloading ComfyUI-KJNodes (zip)...")
                    ok, err = _download_and_extract_zip(
                        "https://github.com/kijai/ComfyUI-KJNodes", kjnodes_dir, branch="main"
                    )
                    _debug_log(f"[download] kjnodes ok={ok} err={err}")
                    if not ok:
                        messages.append(f"ComfyUI-KJNodes download failed ({err})")
                        statuses["kjnodes"] = "failed"
                        self.finished.emit(False, messages, err or "Failed to download ComfyUI-KJNodes")
                        return
                    messages.append("Downloaded ComfyUI-KJNodes (zip)")
                _append_requirements_tasks(tasks, python_exe, kjnodes_dir, "ComfyUI-KJNodes")
            else:
                messages.append("ComfyUI-KJNodes already installed")
            if missing_charon:
                if charon_src.exists():
                    statuses["charon"] = "installing"
                    tasks.append(
                        (
                            "Installing ComfyUI-Charon...",
                            None,  # handled inline without spawning a new interpreter
                        )
                    )
                    _append_requirements_tasks(tasks, python_exe, charon_dir, "ComfyUI-Charon")
                else:
                    messages.append("ComfyUI-Charon source missing in repo; skip install.")
            else:
                messages.append("ComfyUI-Charon already installed")

            if not tasks:
                _emit_status(60, "Dependencies already installed.")
                _emit_status(95, "Finalizing setup...")
                _debug_log("no tasks; finishing early")
                self.finished.emit(True, messages or ["Dependencies already available."], "")
                return

            start_progress = 10
            task_band = 70
            task_count = max(len(tasks), 1)
            step_size = task_band / float(task_count)
            success = True

            for idx, (label, cmd) in enumerate(tasks):
                _debug_log(f"[task-start] {label} cmd={cmd}")
                pre_progress = int(min(95, start_progress + idx * step_size))
                post_progress = int(min(95, start_progress + (idx + 1) * step_size))
                if "Playwright" in label:
                    statuses["playwright"] = "installing"
                elif "trimesh" in label:
                    statuses["trimesh"] = "installing"
                elif "ComfyUI-Manager" in label:
                    statuses["manager"] = "installing"
                elif "KJNodes" in label:
                    statuses["kjnodes"] = "installing"
                elif "ComfyUI-Charon" in label:
                    statuses["charon"] = "installing"
                _emit_status(pre_progress, label)
                ok = True
                err = ""
                should_run = True
                if cmd is None and "ComfyUI-Charon" in label:
                    try:
                        Path(charon_dir).parent.mkdir(parents=True, exist_ok=True)
                        shutil.rmtree(charon_dir, ignore_errors=True)
                        shutil.copytree(charon_src, charon_dir)
                    except Exception as exc:
                        ok = False
                        err = str(exc)
                    should_run = False
                elif cmd and "pip" in cmd and "-r" in cmd:
                    req_path = Path(cmd[-1])
                    if not req_path.exists():
                        ok = True
                        err = ""
                        messages.append(f"{label.replace('...', '').rstrip('.')} skipped (no requirements.txt)")
                        _debug_log(f"[task] {label} skipped; missing {req_path}")
                        if "ComfyUI-Manager" in label:
                            statuses["manager"] = "found"
                        elif "KJNodes" in label:
                            statuses["kjnodes"] = "found"
                        elif "ComfyUI-Charon" in label:
                            statuses["charon"] = "found"
                        _emit_status(post_progress, f"{label.replace('...', '').rstrip('.')} skipped")
                        continue
                elif cmd and len(cmd) == 2 and cmd[1].endswith("install.py"):
                    install_path = Path(cmd[1])
                    if not install_path.exists():
                        ok = True
                        err = ""
                        messages.append(f"{label.replace('...', '').rstrip('.')} skipped (no install.py)")
                        _debug_log(f"[task] {label} skipped; missing {install_path}")
                        if "ComfyUI-Manager" in label:
                            statuses["manager"] = "found"
                        elif "KJNodes" in label:
                            statuses["kjnodes"] = "found"
                        elif "ComfyUI-Charon" in label:
                            statuses["charon"] = "found"
                        _emit_status(post_progress, f"{label.replace('...', '').rstrip('.')} skipped")
                        continue
                if should_run:
                    ok, err = _run_command_silent(cmd)
                _debug_log(f"[task] {label} -> ok={ok} err={err}")
                if ok:
                    messages.append(label.replace("...", "").rstrip("."))
                    if "Playwright" in label:
                        statuses["playwright"] = "found"
                    elif "trimesh" in label:
                        statuses["trimesh"] = "found"
                    elif "ComfyUI-Manager" in label:
                        statuses["manager"] = "found"
                    elif "KJNodes" in label:
                        statuses["kjnodes"] = "found"
                    elif "ComfyUI-Charon" in label:
                        statuses["charon"] = "found"
                    _emit_status(post_progress, label.replace("...", "").rstrip(".") + " completed")
                    continue
                success = False
                error_message = err or "Unknown failure"
                messages.append(f"{label}: FAILED ({error_message})")
                if "Playwright" in label:
                    statuses["playwright"] = "failed"
                elif "trimesh" in label:
                    statuses["trimesh"] = "failed"
                elif "ComfyUI-Manager" in label:
                    statuses["manager"] = "failed"
                elif "KJNodes" in label:
                    statuses["kjnodes"] = "failed"
                elif "ComfyUI-Charon" in label:
                    statuses["charon"] = "failed"
                _emit_status(post_progress, f"{label}: FAILED")
                break

            _emit_status(95, "Finalizing setup...")
            self.finished.emit(success, messages, error_message)
        except Exception as exc:  # pragma: no cover - defensive
            error_message = str(exc)
            _debug_log(f"[fatal] setup crashed: {error_message}")
            _debug_log(f"[fatal] messages_so_far={messages}")
            self.finished.emit(False, messages, error_message)


def get_icon(name: str) -> QtGui.QIcon:
    size = 40 if "header" in name else 24
    pixmap = QtGui.QPixmap(size, size)
    pixmap.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)

    if name == "header_setup":
        painter.setBrush(QtGui.QColor(COLORS["accent"]))
        painter.setPen(QtCore.Qt.NoPen)
        painter.drawEllipse(0, 0, 40, 40)
        painter.setBrush(QtGui.QColor(COLORS["bg_main"]))
        painter.drawEllipse(12, 12, 16, 16)
    elif name == "header_success":
        painter.setBrush(QtGui.QColor(COLORS["success"]))
        painter.setPen(QtCore.Qt.NoPen)
        painter.drawEllipse(0, 0, 40, 40)
        pen = QtGui.QPen(QtCore.Qt.white, 3)
        painter.setPen(pen)
        path = QtGui.QPainterPath()
        path.moveTo(10, 20)
        path.lineTo(18, 28)
        path.lineTo(30, 12)
        painter.drawPath(path)
    elif name == "folder":
        painter.setBrush(QtGui.QColor(COLORS["text_sub"]))
        painter.setPen(QtCore.Qt.NoPen)
        path = QtGui.QPainterPath()
        path.moveTo(2, 6)
        path.lineTo(10, 6)
        path.lineTo(12, 4)
        path.lineTo(22, 4)
        path.lineTo(22, 20)
        path.lineTo(2, 20)
        path.closeSubpath()
        painter.drawPath(path)
        painter.setBrush(QtGui.QColor(COLORS["text_main"]))
        painter.drawRect(2, 8, 20, 12)

    painter.end()
    return QtGui.QIcon(pixmap)


class FirstTimeSetupDialog(QtWidgets.QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("First Time Setup")
        self.setMinimumWidth(500)
        self.setMinimumHeight(350)
        self.setStyleSheet(STYLESHEET)

        self.current_step = 1
        self.comfy_path = ""
        self.progress_val = 0
        self.progress_target = 0
        self.setup_completed = False
        self.worker_thread: Optional[QtCore.QThread] = None
        self.worker: Optional[FirstTimeSetupWorker] = None
        self.comfy_running_preinstall = False
        self.restart_armed = False
        self.restart_ready = False
        self.restart_seen_down = False
        self.restart_timer: Optional[QtCore.QTimer] = None

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)

        self.header_layout = QtWidgets.QHBoxLayout()
        self.header_icon = QtWidgets.QLabel()
        self.header_icon.setPixmap(get_icon("header_setup").pixmap(40, 40))

        header_text_layout = QtWidgets.QVBoxLayout()
        header_text_layout.setSpacing(2)
        self.header_title = QtWidgets.QLabel("Setup Wizard")
        self.header_title.setObjectName("Heading")
        self.header_sub = QtWidgets.QLabel("Step 1 of 3")
        self.header_sub.setObjectName("SubHeading")

        header_text_layout.addWidget(self.header_title)
        header_text_layout.addWidget(self.header_sub)
        self.header_layout.addWidget(self.header_icon)
        self.header_layout.addLayout(header_text_layout)
        self.header_layout.addStretch()
        layout.addLayout(self.header_layout)

        self.stack = QtWidgets.QStackedWidget()
        layout.addWidget(self.stack)

        self.setup_step1_browse()
        self.setup_step2_install()
        self.setup_step3_ready()

        footer_layout = QtWidgets.QHBoxLayout()
        footer_layout.addStretch()
        self.btn_next = QtWidgets.QPushButton("Next")
        self.btn_next.setObjectName("FooterBtn")
        self.btn_next.setCursor(QtCore.Qt.PointingHandCursor)
        self.btn_next.clicked.connect(self.go_next)
        self.btn_next.setEnabled(False)
        footer_layout.addWidget(self.btn_next)
        layout.addLayout(footer_layout)

        self.progress_timer = QtCore.QTimer()
        self.progress_timer.timeout.connect(self.update_progress)
        self.progress_timer.setInterval(80)

        self._prefill_path()

    def _prefill_path(self) -> None:
        stored = preferences.get_preference("comfyui_launch_path", "")
        default_path = get_default_comfy_launch_path()
        for candidate in (stored, default_path):
            candidate = (candidate or "").strip()
            if candidate and os.path.exists(candidate):
                self.comfy_path = candidate
                self.path_edit.setText(candidate)
                self.btn_next.setEnabled(True)
                break

    def setup_step1_browse(self) -> None:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(0, 20, 0, 20)

        lbl = QtWidgets.QLabel("Locate ComfyUI installation")
        lbl.setObjectName("StepLabel")
        layout.addWidget(lbl)

        desc = QtWidgets.QLabel("Please select your 'run_nvidia_gpu.bat' file.")
        desc.setStyleSheet(f"color: {COLORS['text_sub']}; margin-bottom: 10px;")
        layout.addWidget(desc)

        browse_layout = QtWidgets.QHBoxLayout()
        self.path_edit = QtWidgets.QLineEdit()
        self.path_edit.setPlaceholderText("C:/Path/to/ComfyUI/run_nvidia_gpu.bat")
        self.path_edit.setReadOnly(True)

        btn_browse = QtWidgets.QPushButton("Browse")
        btn_browse.setObjectName("BrowseBtn")
        btn_browse.setIcon(get_icon("folder"))
        btn_browse.setCursor(QtCore.Qt.PointingHandCursor)
        btn_browse.clicked.connect(self.open_file_dialog)

        browse_layout.addWidget(self.path_edit)
        browse_layout.addWidget(btn_browse)
        layout.addLayout(browse_layout)
        layout.addStretch()
        self.stack.addWidget(page)

    def open_file_dialog(self) -> None:
        fname, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select run_nvidia_gpu.bat",
            "c:\\",
            "Batch Files (*.bat)",
        )
        if not fname:
            return
        if os.path.basename(fname).lower() != "run_nvidia_gpu.bat":
            QtWidgets.QMessageBox.warning(
                self,
                "Invalid File",
                "Please select the 'run_nvidia_gpu.bat' file.",
            )
            return

        self.comfy_path = fname
        self.path_edit.setText(fname)
        self.btn_next.setEnabled(True)

    def setup_step2_install(self) -> None:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(0, 20, 0, 20)

        lbl = QtWidgets.QLabel("Installing dependencies")
        lbl.setObjectName("StepLabel")
        layout.addWidget(lbl)

        self.install_desc = QtWidgets.QLabel("Starting setup process...")
        self.install_desc.setStyleSheet(f"color: {COLORS['text_sub']}; margin-bottom: 15px;")
        layout.addWidget(self.install_desc)

        self.pbar = QtWidgets.QProgressBar()
        self.pbar.setValue(0)
        layout.addWidget(self.pbar)

        self.install_status_label = QtWidgets.QLabel("")
        self.install_status_label.setStyleSheet(f"color: {COLORS['text_sub']}; margin-top: 8px;")
        self.install_status_label.setWordWrap(True)
        self.install_status_label.setVisible(True)
        self.install_status_label.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        self.install_status_label.setSizePolicy(
            QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.MinimumExpanding
        )
        self.install_status_label.setMinimumHeight(120)
        layout.addWidget(self.install_status_label)

        self.install_ready_label = QtWidgets.QLabel("")
        self.install_ready_label.setStyleSheet(f"color: {COLORS['success']}; margin-top: 10px;")
        self.install_ready_label.setVisible(False)
        self.install_ready_label.setWordWrap(True)
        self.install_ready_label.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(self.install_ready_label)

        layout.addStretch()
        self.stack.addWidget(page)

    def update_progress(self) -> None:
        if self.progress_val < self.progress_target:
            self.progress_val += 2
            self.pbar.setValue(self.progress_val)

    def setup_step3_ready(self) -> None:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        layout.setAlignment(QtCore.Qt.AlignCenter)

        lbl_title = QtWidgets.QLabel("Ready to use")
        lbl_title.setObjectName("Heading")
        lbl_title.setAlignment(QtCore.Qt.AlignCenter)

        lbl_sub = QtWidgets.QLabel(
            "ComfyUI has been successfully linked.\nYou can now start using the integration."
        )
        lbl_sub.setObjectName("SubHeading")
        lbl_sub.setAlignment(QtCore.Qt.AlignCenter)
        lbl_sub.setWordWrap(True)

        layout.addStretch()
        layout.addWidget(lbl_title)
        layout.addWidget(lbl_sub)
        layout.addStretch()

        self.stack.addWidget(page)

    def go_next(self) -> None:
        if self.current_step == 1:
            self.current_step = 2
            self.stack.setCurrentIndex(1)
            self.header_sub.setText("Step 2 of 3")
            self.btn_next.setEnabled(False)
            self.btn_next.setText("Installing...")
            self.progress_val = 0
            self.progress_target = 5
            self.pbar.setValue(0)
            self.progress_timer.start()
            self._start_installation()
            return

        if self.current_step == 2:
            if not self.setup_completed:
                self.btn_next.setEnabled(False)
                self.btn_next.setText("Installing...")
                self.progress_val = 0
                self.progress_target = 0
                self.pbar.setValue(0)
                self.progress_timer.start(100)
                self._start_installation()
                return
            if self.comfy_running_preinstall and not self.restart_ready:
                # Skip auto-restart in the wizard to avoid host crashes; instruct manual restart.
                self.restart_ready = True
                self.comfy_running_preinstall = False
                self.install_ready_label.setText(
                    "Please restart ComfyUI manually, then click Next to finish."
                )
                self.install_ready_label.setVisible(True)
                self.btn_next.setEnabled(True)
                self.btn_next.setText("Next")
                return
            self.current_step = 3
            self.stack.setCurrentIndex(2)
            self.header_icon.setPixmap(get_icon("header_success").pixmap(40, 40))
            self.header_title.setText("Setup Complete!")
            self.header_sub.setText("")
            self.btn_next.setEnabled(True)
            self.btn_next.setText("Finish")
            return

        if self.current_step == 3:
            self.accept()

    def _start_installation(self) -> None:
        self.install_desc.setText("Starting setup process...")
        self.progress_val = 0
        self.progress_target = 5
        self.pbar.setValue(0)
        self.install_ready_label.setVisible(False)
        self.restart_armed = False
        self.restart_ready = False
        self.restart_seen_down = False
        self._stop_restart_timer()
        self.comfy_running_preinstall = self._is_comfy_running()

        if self.comfy_running_preinstall:
            self.progress_timer.stop()
            self.progress_val = 0
            self.progress_target = 0
            self.pbar.setValue(0)
            self.install_ready_label.setVisible(False)
            self.install_desc.setText("ComfyUI is currently running. Please close it before continuing setup.")
            self.install_status_label.setText(
                "Stop the running ComfyUI session, then click Retry to install dependencies safely."
            )
            self.install_status_label.setVisible(True)
            self.btn_next.setEnabled(True)
            self.btn_next.setText("Retry")
            _debug_log("blocked setup: ComfyUI detected running before installation")
            return

        if not self.comfy_path:
            QtWidgets.QMessageBox.warning(
                self,
                "ComfyUI Path Required",
                "Please select the 'run_nvidia_gpu.bat' file first.",
            )
            self.stack.setCurrentIndex(0)
            self.current_step = 1
            self.header_sub.setText("Step 1 of 3")
            self.btn_next.setEnabled(True)
            self.btn_next.setText("Next")
            self.progress_timer.stop()
            return
        if not os.path.exists(self.comfy_path):
            QtWidgets.QMessageBox.warning(
                self,
                "ComfyUI Path Missing",
                "The selected run_nvidia_gpu.bat was not found. Please browse again.",
            )
            self.stack.setCurrentIndex(0)
            self.current_step = 1
            self.header_sub.setText("Step 1 of 3")
            self.btn_next.setEnabled(True)
            self.btn_next.setText("Next")
            self.progress_timer.stop()
            return

        self.worker_thread = QtCore.QThread(self)
        self.worker = FirstTimeSetupWorker(self.comfy_path)
        self.worker.moveToThread(self.worker_thread)
        self.worker.progress_changed.connect(self._apply_worker_progress)
        self.worker.finished.connect(self._handle_worker_finished)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        self.worker_thread.finished.connect(lambda: setattr(self, "worker_thread", None))
        self.worker_thread.started.connect(self.worker.run)
        self.worker_thread.start()

    def _apply_worker_progress(self, target: int, message: str) -> None:
        self.progress_target = max(self.progress_target, target)
        if message:
            if "\n" in message:
                first, rest = message.split("\n", 1)
                self.install_desc.setText(first.strip())
                self.install_status_label.setText(rest.strip())
            else:
                self.install_desc.setText(message.strip())
            self.install_status_label.setVisible(True)
        if not self.progress_timer.isActive():
            self.progress_timer.start()
        if self.progress_val == 0 and self.progress_target > 0:
            self.progress_val = min(self.progress_target, 2)
            self.pbar.setValue(self.progress_val)

    def _handle_worker_finished(self, success: bool, messages: List[str], error: str) -> None:
        _debug_log(f"[finish-callback] success={success} error={error} messages={messages}")
        self.progress_target = 100
        self.progress_val = max(self.progress_val, 98)
        self.pbar.setValue(self.progress_val)
        self.progress_timer.stop()
        self.worker = None
        summary = "\n".join(messages) if messages else ""

        if not success:
            self.install_desc.setText(f"Setup failed: {error}")
            self.btn_next.setEnabled(True)
            self.install_ready_label.setVisible(False)
            self.btn_next.setText("Retry")
            if self.install_status_label.text():
                self.install_status_label.setVisible(True)
            if error:
                QtWidgets.QMessageBox.critical(
                    self,
                    "Setup Failed",
                    f"{error}\n\n{summary}".strip(),
                )
            return

        try:
            preferences.set_preference("comfyui_launch_path", self.comfy_path)
            preferences.set_preference(PREF_DEPENDENCIES_VERIFIED, True)
            system_info("First-time setup completed; dependencies verified.")
        except Exception as exc:  # pragma: no cover - defensive path
            system_error(f"Failed to persist first-time setup preferences: {exc}")

        self.install_desc.setText(summary or "Installation finished.")
        self.pbar.setValue(100)
        self.setup_completed = True
        if self.comfy_running_preinstall:
            self.install_ready_label.clear()
            self.install_ready_label.setVisible(False)
            self.btn_next.setEnabled(True)
            self.btn_next.setText("Restart ComfyUI")
            return
        self.install_ready_label.clear()
        self.install_ready_label.setVisible(False)
        self.btn_next.setEnabled(True)
        self.btn_next.setText("Next")

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # type: ignore[override]
        if self.worker_thread and self.worker_thread.isRunning():
            self.worker_thread.requestInterruption()
        if self.progress_timer.isActive():
            self.progress_timer.stop()
        self._stop_restart_timer()
        super().closeEvent(event)

    def _is_comfy_running(self) -> bool:
        try:
            client = ComfyUIClient()
            return bool(client.test_connection())
        except Exception:
            return False

    def _send_shutdown_signal(self) -> bool:
        return send_shutdown_signal("http://127.0.0.1:8188")

    def _trigger_restart_request(self) -> None:
        try:
            sent = self._send_shutdown_signal()
        except Exception as exc:  # pragma: no cover - defensive
            sent = False
            system_error(f"ComfyUI restart request crashed: {exc}")
            _debug_log(f"restart request crashed: {exc}")
        if sent:
            self.install_ready_label.clear()
            self.install_ready_label.setVisible(False)
        else:
            self.install_ready_label.setText(
                "Could not send shutdown to ComfyUI. Please restart it manually, then click Restart ComfyUI again."
            )
            self.install_ready_label.setVisible(True)
            self.btn_next.setEnabled(True)
            self.btn_next.setText("Restart ComfyUI")
            self.restart_armed = False
            self._stop_restart_timer()

    def _start_restart_monitor(self) -> None:
        try:
            self._stop_restart_timer()
            self.restart_timer = QtCore.QTimer(self)
            self.restart_timer.setInterval(1500)
            self.restart_timer.timeout.connect(self._poll_restart_monitor)
            self.restart_timer.start()
        except Exception as exc:  # pragma: no cover - defensive
            system_error(f"Failed to start restart monitor: {exc}")
            self.restart_timer = None
            _debug_log(f"restart monitor failed: {exc}")

    def _poll_restart_monitor(self) -> None:
        running = self._is_comfy_running()
        if not self.restart_seen_down and not running:
            self.restart_seen_down = True
            self.install_ready_label.clear()
            self.install_ready_label.setVisible(False)
            return
        if self.restart_seen_down and running:
            self.restart_ready = True
            self._stop_restart_timer()
            self.btn_next.setEnabled(True)
            self.btn_next.setText("Next")
            self.install_ready_label.clear()
            self.install_ready_label.setVisible(False)

    def _stop_restart_timer(self) -> None:
        if self.restart_timer is not None:
            try:
                self.restart_timer.stop()
            except Exception:
                pass
            self.restart_timer = None


def show_dialog() -> None:
    app = QtWidgets.QApplication.instance()
    parent = (
        next((w for w in app.topLevelWidgets() if w.inherits("QMainWindow")), None)
        if app
        else None
    )
    dialog = FirstTimeSetupDialog(parent)
    dialog.show()
