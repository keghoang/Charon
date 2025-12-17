import os
import time
import subprocess
import threading
import weakref
from typing import Optional

from ..qt_compat import QtWidgets, QtCore, QtGui
from ..charon_logger import system_info, system_warning, system_error, system_debug
from .. import preferences
from ..comfy_client import ComfyUIClient
from ..paths import extend_sys_path_with_comfy, resolve_comfy_environment
import urllib.request
import urllib.error
from urllib.parse import urlparse

from ..comfy_restart import send_shutdown_signal

try:  # PySide6 helper to check lifetime of wrapped objects
    from shiboken6 import isValid as _qt_is_valid  # type: ignore
except Exception:  # pragma: no cover - fallback
    def _qt_is_valid(obj) -> bool:
        return obj is not None

class ComfyConnectionWidget(QtWidgets.QWidget):
    """Compact footer widget that monitors and configures ComfyUI connectivity."""

    connection_status_changed = QtCore.Signal(bool)
    client_changed = QtCore.Signal(object)
    restart_state_changed = QtCore.Signal(bool)

    _connection_check_finished = QtCore.Signal(bool, object, bool)

    _PATH_SETTING_KEY = "comfyui_launch_path"
    _DEFAULT_URL = "http://127.0.0.1:8188"

    def __init__(self, parent=None):
        super().__init__(parent)

        self._client: Optional[ComfyUIClient] = None
        self._settings = self._load_settings()
        self._comfy_path = self._settings.get(self._PATH_SETTING_KEY, "").strip()
        self._check_in_progress = False
        self._connected = False
        self._popover: Optional["ConnectionSettingsPopover"] = None
        self._manual_cursor_override = False
        self._launch_in_progress = False
        self._launch_started_at = 0.0
        self._is_shutting_down = False
        self._compact_mode = False
        self._last_status_state = "path_required"
        self._managed_launch = False
        self._restart_pending = False
        self._managed_process: Optional[subprocess.Popen] = None
        self._launch_button_width: Optional[int] = None
        self._launch_button_height: Optional[int] = None
        self._launch_button_width: Optional[int] = None

        self._connection_check_finished.connect(self._apply_connection_result)

        self._build_ui()

        self._watch_timer = QtCore.QTimer(self)
        self._watch_timer.setInterval(2500)
        self._watch_timer.timeout.connect(self._check_connection)

        if self._comfy_path:
            extend_sys_path_with_comfy(self._comfy_path)
            self._watch_timer.start()
            self._set_status("checking", False)
            QtCore.QTimer.singleShot(0, self._check_connection)
        else:
            self._set_status("path_required", False)
            QtCore.QTimer.singleShot(0, self._prompt_for_path)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(3)

        self.status_caption = QtWidgets.QLabel("ComfyUI Status:")
        self.status_caption.setAlignment(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignRight)
        self.status_caption.setStyleSheet("color: #ffffff;")
        self.status_caption.setTextFormat(QtCore.Qt.RichText)
        self.status_caption.setContentsMargins(0, 0, 0, 5)
        layout.addWidget(self.status_caption)
        layout.setAlignment(self.status_caption, QtCore.Qt.AlignVCenter)
        layout.addSpacing(10)

        self._apply_caption_text()

        self.launch_button = QtWidgets.QPushButton("Start Server")
        self.launch_button.setCursor(QtCore.Qt.PointingHandCursor)
        self.launch_button.setFocusPolicy(QtCore.Qt.NoFocus)
        self.launch_button.clicked.connect(self._handle_launch_or_stop)
        self.launch_button.setSizePolicy(
            QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Preferred
        )
        self._ensure_launch_button_size()
        self.launch_button.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.launch_button.customContextMenuRequested.connect(self._show_launch_context_menu)
        self.launch_button.installEventFilter(self)
        layout.addWidget(self.launch_button)
        layout.setAlignment(self.launch_button, QtCore.Qt.AlignVCenter)

        self.separator_label = QtWidgets.QLabel("|")
        self.separator_label.setStyleSheet("color: #666666;")
        layout.addWidget(self.separator_label)

        self.settings_button = QtWidgets.QToolButton()
        self.settings_button.setText("")  # Hide gear icon; popover moved to main Settings button
        self.settings_button.setAutoRaise(True)
        self.settings_button.setCursor(QtCore.Qt.PointingHandCursor)
        self.settings_button.setFocusPolicy(QtCore.Qt.NoFocus)
        self.settings_button.setToolTip("")
        self.settings_button.setMinimumWidth(20)
        self.settings_button.installEventFilter(self)
        self.settings_button.clicked.connect(lambda: self._show_settings_popover(auto_focus=True))
        self.settings_button.setVisible(False)
        self.separator_label.setVisible(False)
        layout.addWidget(self.settings_button)

        self._blink_timer = QtCore.QTimer(self)
        self._blink_timer.setInterval(450)
        self._blink_timer.timeout.connect(self._toggle_button_blink)
        self._blink_state = False

        self._set_status("path_required", False)

    # ----------------------------------------------------------------- State
    def _load_settings(self) -> dict:
        return preferences.load_preferences(parent=self)

    def _store_setting(self, key: str, value: str) -> None:
        try:
            current = preferences.load_preferences(parent=self)
            current[key] = value or ""
            preferences.save_preferences(current, parent=self)
            self._settings = current
        except Exception as exc:  # pragma: no cover - defensive path
            system_warning(f"Could not store ComfyUI setting '{key}': {exc}")

    def _prompt_for_path(self) -> None:
        self._set_status("path_required", False)
        QtWidgets.QMessageBox.information(
            self,
            "ComfyUI Path Required",
            "Please browse to your ComfyUI launch script (.bat or .py).",
        )
        self._show_settings_popover(auto_focus=True)
        popover = ConnectionSettingsPopover.active_popover()
        if popover is not None:
            popover._browse_for_path()

    def _update_path(self, path: str) -> None:
        path = path.strip()
        if path == self._comfy_path:
            return

        if not path:
            self._comfy_path = ""
            self._store_setting(self._PATH_SETTING_KEY, "")
            self._watch_timer.stop()
            self._client = None
            self._set_status("path_required", False)
            self.client_changed.emit(None)
            return

        self._comfy_path = path
        self._store_setting(self._PATH_SETTING_KEY, path)

        extend_sys_path_with_comfy(path)
        if not self._watch_timer.isActive():
            self._watch_timer.start()
        self._check_connection(manual=True)

    # ----------------------------------------------------------- Connection
    def _check_connection(self, manual: bool = False) -> None:
        latest_path = preferences.get_preference(self._PATH_SETTING_KEY, "").strip()
        if latest_path != (self._comfy_path or ""):
            self._comfy_path = latest_path
            if self._comfy_path:
                extend_sys_path_with_comfy(self._comfy_path)
        if self._managed_process and self._managed_process.poll() is not None:
            self._managed_process = None
            self._managed_launch = False
        if not self._comfy_path or self._check_in_progress or self._is_shutting_down:
            return

        now = time.time()
        if self._launch_in_progress and now - self._launch_started_at > 600:
            self._launch_in_progress = False

        self._check_in_progress = True
        if manual:
            if self._launch_in_progress:
                self._set_status("launching", False)
            else:
                self._set_status("checking", False)
            QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
            self._manual_cursor_override = True

        target_ref = weakref.ref(self)

        def worker():
            connected = False
            client = None
            try:
                client = ComfyUIClient(self._DEFAULT_URL)
                connected = bool(client.test_connection())
                if not connected:
                    client = None
            except Exception:
                connected = False
                client = None

            widget = target_ref()
            if not widget:
                return
            if not _qt_is_valid(widget):
                return
            if getattr(widget, "_is_shutting_down", False):
                return
            widget._connection_check_finished.emit(connected, client, manual)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_connection_result(self, connected: bool, client: Optional[ComfyUIClient], manual: bool) -> None:
        self._check_in_progress = False

        if manual and self._manual_cursor_override:
            QtWidgets.QApplication.restoreOverrideCursor()
            self._manual_cursor_override = False

        if connected:
            status_changed = not self._connected
            self._client = client
            self._set_status("online", True)
            self._launch_in_progress = False
            self._restart_pending = False
            if status_changed:
                system_info("ComfyUI connection established (watcher)")
            self.client_changed.emit(self._client)
        else:
            status_changed = self._connected
            self._client = None
            if self._launch_in_progress:
                self._set_status("launching", False)
                return
            else:
                if self._comfy_path:
                    next_state = "restarting" if self._restart_pending else "offline"
                    self._set_status(next_state, False)
                    if status_changed:
                        system_warning("ComfyUI connection lost (watcher)")
                else:
                    self._set_status("path_required", False)
            self.client_changed.emit(None)

    def _set_status(self, state: str, connected: bool) -> None:
        previous_state = self._last_status_state
        self._last_status_state = state or self._last_status_state
        mapping = {
            "online": ("Running", "#51cf66"),
            "offline": ("Offline", "#ff6b6b"),
            "path_required": ("Path Required", "#ff6b6b"),
            "checking": ("Checking...", "#d0a23f"),
            "launching": ("Launching...", "#d0a23f"),
            "restarting": ("Restarting...", "#d89614"),
            "unavailable": ("Client Unavailable", "#ffa94d"),
        }
        label_text, color = mapping.get(state, (state, "#cccccc"))
        button_style = (
            "QPushButton {"
            f" color: {color};"
            " font-weight: bold;"
            " border: 1px solid #555555;"
            " border-radius: 3px;"
            " padding: 2px 10px;"
            " background-color: #1c1c1c;"
            "}"
        )
        previous_connection = self._connected
        previous_text = self.launch_button.text()

        self.launch_button.setText(label_text)
        self.launch_button.setStyleSheet(button_style)
        self._connected = connected
        self._apply_caption_text()

        if connected != previous_connection:
            self.connection_status_changed.emit(connected)
        elif label_text != previous_text:
            self.launch_button.update()

        if state == "restarting" and previous_state != "restarting":
            self.restart_state_changed.emit(True)
        elif previous_state == "restarting" and state != "restarting":
            self.restart_state_changed.emit(False)

        self._update_launch_button(state, connected)

    def _update_launch_button(self, state: str, connected: bool) -> None:
        button = getattr(self, "launch_button", None)
        if button is None:
            return
        self._ensure_launch_button_size()

        if connected:
            self._stop_button_blink()
            button.setEnabled(True)
            button.setCursor(QtCore.Qt.PointingHandCursor)
            button.setText("Stop Server")
            self._apply_outline_button_style(button, "#ff6b6b", hover="#ff8787", text_color="#ff6b6b")
        elif self._launch_in_progress or state in {"launching", "restarting"}:
            self._stop_button_blink()
            button.setEnabled(False)
            button.setCursor(QtCore.Qt.ArrowCursor)
            button.setText("Restarting..." if state == "restarting" else "Launching...")
            self._apply_button_style(button, "#f08c00", "#d9480f", disabled=True)
        else:
            button.setEnabled(True)
            button.setCursor(QtCore.Qt.PointingHandCursor)
            if state == "checking":
                button.setText("Checking...")
                self._stop_button_blink()
                self._apply_button_style(button, "#f08c00", "#d9480f", hover="#f59f00")
            else:
                button.setText("Start Server")
                self._stop_button_blink()
                self._apply_button_style(button, "#37b24d", "#2f9e44", hover="#40c057")

    def _apply_button_style(
        self,
        button: QtWidgets.QPushButton,
        background: str,
        border: str,
        *,
        text_color: str = "#ffffff",
        hover: Optional[str] = None,
        disabled: bool = False,
    ) -> None:
        style = (
            "QPushButton {"
            f" background-color: {background};"
            f" color: {text_color};"
            f" border: 1px solid {border};"
            " padding: 2px 10px;"
            " border-radius: 3px;"
            " margin: 0px;"
            " outline: none;"
            "}"
        )
        if hover and button.isEnabled():
            style += (
                " QPushButton:hover {"
                f" background-color: {hover};"
                "}"
            )
        if disabled:
            style += (
                " QPushButton:disabled {"
                f" background-color: {background};"
                f" color: {text_color};"
                "}"
            )
        style += (
            " QPushButton:focus {"
            f" background-color: {background};"
            " outline: none;"
            f" border: 1px solid {border};"
            "}"
        )
        button.setStyleSheet(style)

    def _apply_outline_button_style(
        self,
        button: QtWidgets.QPushButton,
        border: str,
        *,
        text_color: Optional[str] = "#ffffff",
        hover: Optional[str] = None,
    ) -> None:
        text_color = text_color or "#ffffff"
        style = (
            "QPushButton {"
            " background-color: transparent;"
            f" color: {text_color};"
            f" border: 1px solid {border};"
            " padding: 2px 10px;"
            " border-radius: 3px;"
            " margin: 0px;"
            " outline: none;"
            "}"
            " QPushButton:disabled {"
            " background-color: transparent;"
            f" color: {text_color};"
            f" border: 1px solid {border};"
            "}"
        )
        if hover and button.isEnabled():
            style += (
                " QPushButton:hover {"
                f" color: {text_color};"
                f" border-color: {hover};"
                "}"
            )
        style += (
            " QPushButton:focus {"
            " background-color: transparent;"
            " outline: none;"
            f" border: 1px solid {border};"
            "}"
        )
        button.setStyleSheet(style)

    def _compute_launch_button_min_width(self) -> int:
        button = getattr(self, "launch_button", None)
        if button is None:
            return 120
        metrics = button.fontMetrics()
        labels = [
            "Start Server",
            "Stop Server",
            "Restarting...",
            "Launching...",
            "Checking...",
        ]
        padding = 24
        return max(metrics.horizontalAdvance(text) + padding for text in labels)

    def _ensure_launch_button_size(self) -> None:
        button = getattr(self, "launch_button", None)
        if button is None:
            return
        width = self._compute_launch_button_min_width()
        self._launch_button_width = width
        button.setFixedWidth(width)
        base_height = button.sizeHint().height()
        if base_height <= 0:
            base_height = button.fontMetrics().height() + 8
        height = int(base_height * 1.2)
        self._launch_button_height = height
        button.setFixedHeight(height)

    def set_compact_mode(self, compact: bool) -> None:
        compact = bool(compact)
        if self._compact_mode == compact:
            return
        self._compact_mode = compact
        self._apply_caption_text()
        self._apply_settings_visibility(not compact)
        self._ensure_launch_button_size()
        # Re-emit the current status to update label/button text.
        self._set_status(self._last_status_state, self._connected)

    def _apply_caption_text(self) -> None:
        if not hasattr(self, "status_caption"):
            return
        online = bool(getattr(self, "_connected", False))
        caption = "Online" if self._compact_mode else "ComfyUI Online"
        offline_caption = "Offline" if self._compact_mode else "ComfyUI Offline"
        color = "#51cf66" if online else "#ff6b6b"
        label_font = self.status_caption.font()
        base_size = label_font.pointSizeF() if label_font.pointSizeF() > 0 else label_font.pixelSize()
        if base_size <= 0:
            base_size = 12
        dot_size = int(base_size * 1.6)
        dot = (
            f"<span style='color: {color}; font-size: {dot_size}px; line-height: 1; "
            "vertical-align: middle;'>&#9679;</span>"
        )
        text_body = f"{dot} {caption if online else offline_caption}"
        text = f"<span style='line-height: 1; vertical-align: middle;'>{text_body}</span>"
        self.status_caption.setText(text)
        self.status_caption.setStyleSheet(f"color: {color}; font-weight: normal;")

    def _apply_settings_visibility(self, visible: bool) -> None:
        """Show or hide the settings affordance based on the active mode."""
        # The footer settings affordance is disabled; configuration lives in the main Settings dialog.
        visible = False
        button = getattr(self, "settings_button", None)
        separator = getattr(self, "separator_label", None)
        for widget in (separator, button):
            if widget is not None:
                widget.setVisible(visible)
        if button is not None:
            button.setEnabled(visible)

    def _start_button_blink(self) -> None:
        button = getattr(self, "launch_button", None)
        if button is None:
            return
        if not self._blink_timer.isActive():
            self._blink_state = False
            self._blink_timer.start()
        self._apply_button_style(button, "#ff6b6b", "#c92a2a", hover="#ff8787")

    def _stop_button_blink(self) -> None:
        if self._blink_timer.isActive():
            self._blink_timer.stop()
        self._blink_state = False

    def _toggle_button_blink(self) -> None:
        button = getattr(self, "launch_button", None)
        if button is None or not button.isEnabled():
            self._stop_button_blink()
            return
        self._blink_state = not self._blink_state
        primary = "#ff6b6b" if self._blink_state else "#c92a2a"
        hover = "#ff8787" if self._blink_state else "#fa5252"
        self._apply_button_style(button, primary, "#c92a2a", hover=hover)
    # -------------------------------------------------------------- Popover
    def _show_settings_popover(self, auto_focus: bool = False) -> None:
        QtWidgets.QMessageBox.information(
            self,
            "ComfyUI Path",
            "Configure the ComfyUI launch path in Settings → Settings ComfyUI.",
        )

    def _clear_popover(self) -> None:
        if self._popover is not None:
            ConnectionSettingsPopover.clear_active_popover(self._popover)
        self._popover = None

    # -------------------------------------------------------------- Actions
    def _handle_launch_or_stop(self) -> None:
        if self._connected:
            self._terminate_comfyui(confirm=False)
        else:
            self._launch_comfyui()

    def _write_task_launcher_script(
        self, workdir: str, launch_line: str, disable_flag: str
    ) -> Optional[str]:
        """
        Write a short .cmd launcher to keep Task Scheduler /tr under length limits.
        """
        try:
            workdir = workdir or os.getcwd()
            root = preferences.get_preferences_root(parent=self, ensure_dir=True)
            script_path = os.path.join(root, "comfyui_task_launcher.cmd")
            lines = [
                "@echo off",
                f'cd /d "{workdir}"',
                f'set "COMMANDLINE_ARGS=%COMMANDLINE_ARGS% {disable_flag}"',
                launch_line,
                "",
            ]
            with open(script_path, "w", encoding="utf-8") as handle:
                handle.write("\r\n".join(lines))
            return script_path
        except Exception as exc:  # pragma: no cover - defensive path
            system_warning(f"Could not prepare ComfyUI launcher script: {exc}")
            return None

    def _launch_comfyui(self) -> None:
        if not self._comfy_path:
            QtWidgets.QMessageBox.warning(self, "Launch ComfyUI", "Please set the ComfyUI launch path first.")
            self._show_settings_popover(auto_focus=True)
            return

        path = self._comfy_path
        if not os.path.exists(path):
            QtWidgets.QMessageBox.critical(self, "Launch ComfyUI", f"File not found:\n{path}")
            return

        extend_sys_path_with_comfy(path)
        base_dir = path if os.path.isdir(path) else os.path.dirname(path)
        if not base_dir:
            base_dir = os.getcwd()
        task_name = f"Charon_ComfyUI_{int(time.time())}"
        disable_flag = "--disable-auto-launch"
        env_prefix = f'set "COMMANDLINE_ARGS=%COMMANDLINE_ARGS% {disable_flag}" && '
        comfy_env = resolve_comfy_environment(path)
        comfy_dir = comfy_env.get("comfy_dir") or base_dir
        python_exe = comfy_env.get("python_exe")
        main_py = os.path.join(comfy_dir, "main.py")

        use_embedded_python = bool(python_exe and os.path.exists(main_py))
        launcher_dir = comfy_dir if use_embedded_python else base_dir
        launch_line = (
            f'"{python_exe}" -u "{main_py}" {disable_flag}'
            if use_embedded_python
            else f'"{path}" {disable_flag}'
        )
        task_command = f'cmd /c cd /d "{launcher_dir}" && {env_prefix}{launch_line}'
        task_command_limit = 261
        used_task_script = False

        if len(task_command) > task_command_limit:
            script_path = self._write_task_launcher_script(launcher_dir, launch_line, disable_flag)
            if script_path:
                task_command = f'"{script_path}"'
                used_task_script = True
                system_debug(
                    "Task Scheduler /tr exceeded 261 characters; using cached launcher script."
                )
            else:
                system_warning("Task Scheduler /tr too long; fallback script unavailable.")

        def run_scheduler(command: str):
            create_cmd = [
                "schtasks",
                "/create",
                "/tn",
                task_name,
                "/tr",
                command,
                "/sc",
                "once",
                "/st",
                "00:00",
                "/f",
            ]
            run_cmd = ["schtasks", "/run", "/tn", task_name]
            delete_cmd = ["schtasks", "/delete", "/tn", task_name, "/f"]
            create_result = subprocess.run(create_cmd, check=True, capture_output=True, text=True)
            run_result = subprocess.run(run_cmd, check=True, capture_output=True, text=True)
            subprocess.run(delete_cmd, check=False, capture_output=True, text=True)
            return create_result, run_result

        def record_success(create_result, run_result) -> None:
            self._managed_process = None
            self._launch_in_progress = True
            self._launch_started_at = time.time()
            self._managed_launch = True
            self._restart_pending = False
            self._set_status("launching", self._connected)
            suffix = " (launcher script fallback)" if used_task_script else ""
            system_debug(
                f"Launched ComfyUI via Task Scheduler ({task_name}) from {path}: "
                f"{create_result.stdout} {run_result.stdout}{suffix}"
            )

        def is_tr_length_error(exc: subprocess.CalledProcessError) -> bool:
            text = f"{exc.stderr or ''} {exc.stdout or ''}".lower()
            return "261" in text and "/tr" in text

        try:
            create_result, run_result = run_scheduler(task_command)
            record_success(create_result, run_result)
        except subprocess.CalledProcessError as exc:
            if not used_task_script and is_tr_length_error(exc):
                script_path = self._write_task_launcher_script(launcher_dir, launch_line, disable_flag)
                if script_path:
                    try:
                        used_task_script = True
                        create_result, run_result = run_scheduler(f'"{script_path}"')
                        record_success(create_result, run_result)
                        return
                    except subprocess.CalledProcessError as fallback_exc:
                        exc = fallback_exc
            self._managed_process = None
            self._launch_in_progress = False
            QtWidgets.QMessageBox.critical(
                self,
                "Launch ComfyUI",
                f"Failed to launch ComfyUI via Task Scheduler.\n\nCommand: {' '.join(exc.cmd)}\nError: {exc.stderr or exc}",
            )
            system_error(f"Task Scheduler launch failed: {exc} / {exc.stderr}")
        except Exception as exc:  # pragma: no cover - defensive path
            self._managed_process = None
            self._launch_in_progress = False
            QtWidgets.QMessageBox.critical(self, "Launch ComfyUI", f"Failed to launch ComfyUI:\n{exc}")
            system_error(f"Failed to launch ComfyUI from {path}: {exc}")

    def _show_launch_context_menu(self, pos: QtCore.QPoint) -> None:
        button = getattr(self, "launch_button", None)
        if button is None:
            return

        menu = QtWidgets.QMenu(button)
        terminate_action = menu.addAction("Terminate ComfyUI")
        terminate_action.setEnabled(self._connected or self._launch_in_progress)
        restart_action = menu.addAction("Restart ComfyUI")
        restart_action.setEnabled(bool(self._comfy_path))
        terminate_action.triggered.connect(lambda: self._terminate_comfyui(confirm=True))
        restart_action.triggered.connect(self.handle_external_restart_request)
        menu.exec_(button.mapToGlobal(pos))

    def _terminate_comfyui(self, *, confirm: bool = True) -> None:
        if not (self._connected or self._launch_in_progress):
            return

        if confirm:
            reply = QtWidgets.QMessageBox.question(
                self,
                "Terminate ComfyUI",
                "Force terminate ComfyUI now?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No,
            )
            if reply != QtWidgets.QMessageBox.Yes:
                return

        if self._terminate_managed_process():
            self._launch_in_progress = False
            self._set_status("checking", False)
            QtCore.QTimer.singleShot(1500, lambda: self._check_connection(manual=False))
            return

        if self._connected:
            if self._send_shutdown_signal(allow_manager_reboot=False):
                system_info("Sent shutdown request to the running ComfyUI instance.")
                self._launch_in_progress = False
                self._set_status("checking", False)
                QtCore.QTimer.singleShot(2000, lambda: self._check_connection(manual=False))
                return
            system_warning("ComfyUI shutdown request did not respond; attempting force kill.")

        forced = self._force_kill_comfy_processes()
        if forced:
            system_info("Force-terminated ComfyUI processes.")
            self._launch_in_progress = False
            self._set_status("checking", False)
            QtCore.QTimer.singleShot(1500, lambda: self._check_connection(manual=False))
        else:
            QtWidgets.QMessageBox.warning(
                self,
                "Terminate ComfyUI",
                "No ComfyUI process was force-terminated.\n"
                "Please close the ComfyUI window or console manually.",
            )

    def handle_external_restart_request(self) -> None:
        if not self._comfy_path:
            QtWidgets.QMessageBox.warning(
                self,
                "Restart ComfyUI",
                "ComfyUI launch path is not configured. Open the settings and set the launch path first.",
            )
            return
        if self._restart_pending:
            return
        if self._managed_process and self._managed_process.poll() is None:
            self._restart_pending = True
            self._set_status("restarting", False)
            if self._terminate_managed_process():
                QtCore.QTimer.singleShot(2000, self._launch_comfyui)
                return
            self._restart_pending = False
            self._set_status("checking", False)
            return

        # Externally launched instance: try graceful shutdown over HTTP, then relaunch via configured path.
        self._restart_pending = True
        self._set_status("restarting", False)
        if self._send_shutdown_signal():
            # If the external instance rebooted itself, just poll for connectivity instead of spawning another instance.
            self._set_status("restarting", False)
            QtCore.QTimer.singleShot(3000, lambda: self._check_connection(manual=True))
        else:
            QtWidgets.QMessageBox.information(
                self,
                "Restart ComfyUI",
                "Could not send a shutdown request to the running ComfyUI instance.\n"
                "Close it manually, then click Restart again.",
            )
            self._restart_pending = False
            self._set_status("checking", False)

    def _send_shutdown_signal(self, *, allow_manager_reboot: bool = True) -> bool:
        return send_shutdown_signal(self._DEFAULT_URL, allow_manager_reboot=allow_manager_reboot)

    def _force_kill_comfy_processes(self) -> bool:
        comfy_env = resolve_comfy_environment(self._comfy_path)
        comfy_dir = comfy_env.get("comfy_dir") or ""
        base_dir = comfy_env.get("base_dir") or ""
        candidates = {os.path.normpath(p) for p in (comfy_dir, base_dir) if p}
        port_hint = urlparse(self._DEFAULT_URL).port or 8188
        name_hints = {"comfyui", "comfy_ui"}
        if not candidates:
            # Still try to find ComfyUI by name or listening port if paths are unknown.
            candidates = set()

        try:
            import psutil  # type: ignore
        except Exception as exc:  # pragma: no cover - optional dependency
            system_warning(f"Force kill skipped: psutil unavailable ({exc})")
            return False

        killed = False
        port_pids = set()
        try:
            port_pids = {
                conn.pid
                for conn in psutil.net_connections(kind="inet")
                if conn.pid and getattr(conn.laddr, "port", None) == port_hint
            }
        except Exception:
            # AccessDenied is common on Windows without elevation; fall back to per-process scan.
            port_pids = set()

        for proc in psutil.process_iter(["pid", "name", "exe", "cmdline"]):
            try:
                exe = (proc.info.get("exe") or "").lower()
                cmdline_list = proc.info.get("cmdline") or []
                cmdline = " ".join(cmdline_list).lower()
                haystack = (exe, cmdline)
                matches_path = any(
                    candidate.lower() in text for candidate in candidates for text in haystack
                )
                matches_name = any(hint in exe or hint in cmdline for hint in name_hints)
                matches_port = proc.info.get("pid") in port_pids
                if not matches_port:
                    try:
                        for conn in proc.connections(kind="inet"):
                            laddr = getattr(conn, "laddr", None)
                            if laddr and getattr(laddr, "port", None) == port_hint:
                                matches_port = True
                                break
                    except Exception:
                        # AccessDenied and zombie processes are expected occasionally.
                        pass

                # Match by install path, default port, or process name to catch external launches.
                if matches_path or matches_port or matches_name:
                    system_debug(
                        f"Force-killing ComfyUI candidate PID {proc.pid} "
                        f"(name={proc.info.get('name')}, exe={proc.info.get('exe')})"
                    )
                    proc.kill()
                    killed = True
            except Exception:
                continue
        return killed

    def _terminate_managed_process(self) -> bool:
        process = self._managed_process
        if process is None:
            return False
        if process.poll() is not None:
            self._managed_process = None
            self._managed_launch = False
            return False
        try:
            process.terminate()
            try:
                process.wait(timeout=10)
            except Exception:
                process.kill()
                process.wait(timeout=5)
            return True
        except Exception as exc:  # pragma: no cover - defensive
            system_warning(f"Failed to terminate managed ComfyUI process: {exc}")
            return False
        finally:
            self._managed_process = None
            self._managed_launch = False

    # ------------------------------------------------------------ Qt Events
    def eventFilter(self, obj, event):
        settings_btn = getattr(self, "settings_button", None)
        if settings_btn is not None and obj is settings_btn:
            if not settings_btn.isVisible() or not settings_btn.isEnabled():
                return super().eventFilter(obj, event)
            if event.type() == QtCore.QEvent.MouseButtonPress:
                self._show_settings_popover(auto_focus=True)
                return True
            elif event.type() == QtCore.QEvent.Leave:
                if self._popover and self._popover.isVisible():
                    self._popover.start_dismiss_countdown()
        launch_btn = getattr(self, "launch_button", None)
        if launch_btn is not None and obj is launch_btn:
            if event.type() == QtCore.QEvent.ContextMenu:
                self._show_launch_context_menu(event.pos())
                return True
            if (
                event.type() == QtCore.QEvent.MouseButtonPress
                and event.button() == QtCore.Qt.MouseButton.RightButton
            ):
                self._show_launch_context_menu(event.pos())
                return True
        return super().eventFilter(obj, event)

    @property
    def client(self) -> Optional[ComfyUIClient]:
        return self._client

    def current_client(self) -> Optional[ComfyUIClient]:
        """
        Compatibility helper for processor scripts that need the active client.
        """
        return self._client

    def is_connected(self) -> bool:
        """Return True when ComfyUI is currently online."""
        return bool(self._connected)

    def current_comfy_path(self) -> str:
        """
        Expose the configured ComfyUI launch path without breaking encapsulation.
        """
        return self._comfy_path

    def closeEvent(self, event) -> None:
        self._is_shutting_down = True
        try:
            self._watch_timer.stop()
        except Exception:
            pass
        try:
            self._blink_timer.stop()
        except Exception:
            pass
        if self._manual_cursor_override:
            try:
                QtWidgets.QApplication.restoreOverrideCursor()
            except Exception:
                pass
            self._manual_cursor_override = False
        try:
            self._connection_check_finished.disconnect(self._apply_connection_result)
        except Exception:
            pass
        super().closeEvent(event)


class ConnectionSettingsPopover(QtWidgets.QDialog):
    """Popup dialog for editing ComfyUI launcher details."""

    path_selected = QtCore.Signal(str)
    retest_requested = QtCore.Signal()

    _ACTIVE: Optional["ConnectionSettingsPopover"] = None

    def __init__(self, parent, comfy_path: str):
        flags = QtCore.Qt.Tool | QtCore.Qt.FramelessWindowHint
        super().__init__(parent, flags)

        self._initial_path = comfy_path or ""
        self.setWindowTitle("ComfyUI Settings")
        self.setModal(False)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating, True)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        layout.addWidget(QtWidgets.QLabel("ComfyUI Launch Path"))

        self.path_edit = QtWidgets.QLineEdit(self._initial_path)
        self.path_edit.setPlaceholderText("Select run_nvidia_gpu.bat or main.py")
        layout.addWidget(self.path_edit)

        button_row = QtWidgets.QHBoxLayout()
        browse_btn = QtWidgets.QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_for_path)
        button_row.addWidget(browse_btn)

        save_btn = QtWidgets.QPushButton("Save")
        save_btn.clicked.connect(self._apply_path)
        button_row.addWidget(save_btn)

        layout.addLayout(button_row)

        self._close_timer = QtCore.QTimer(self)
        self._close_timer.setSingleShot(True)
        self._close_timer.timeout.connect(self._close_if_outside)
        self._suspend_autoclose = False

    # ----------------------------------------------------------- Interactions
    def _browse_for_path(self) -> None:
        self._suspend_autoclose = True
        self._close_timer.stop()
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select ComfyUI Launch File",
            "",
            "Batch Files (*.bat);;Python Scripts (*.py);;All Files (*.*)",
        )
        self._suspend_autoclose = False
        if file_path:
            self.path_edit.setText(file_path.strip())
        self.show()
        self.raise_()
        self.activateWindow()
        self.path_edit.setFocus(QtCore.Qt.OtherFocusReason)

    def _apply_path(self) -> None:
        self._close_timer.stop()
        self.path_selected.emit(self.path_edit.text().strip())
        # keep popover open for additional actions

    def _request_retest(self) -> None:
        self._close_timer.stop()
        self.path_selected.emit(self.path_edit.text().strip())
        self.retest_requested.emit()

    def focus_path_edit(self) -> None:
        self.path_edit.setFocus(QtCore.Qt.OtherFocusReason)
        self.path_edit.selectAll()

    def closeEvent(self, event) -> None:
        super().closeEvent(event)
        ConnectionSettingsPopover.clear_active_popover(self)

    def enterEvent(self, event) -> None:
        self._close_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.start_dismiss_countdown()
        super().leaveEvent(event)

    def _close_if_outside(self) -> None:
        if self._suspend_autoclose:
            return
        cursor_pos = QtGui.QCursor.pos()
        local_pos = self.mapFromGlobal(cursor_pos)
        if self.rect().contains(local_pos):
            return

        parent_widget = self.parent()
        if parent_widget is not None and hasattr(parent_widget, "settings_button"):
            button = parent_widget.settings_button
            if button is not None:
                button_rect = button.rect()
                top_left = button.mapToGlobal(button_rect.topLeft())
                global_button_rect = QtCore.QRect(top_left, button_rect.size())
                if global_button_rect.contains(cursor_pos):
                    return

        self.close()

    # ----------------------------------------------------------- Class helpers
    def start_dismiss_countdown(self, delay: int = 150) -> None:
        if self._suspend_autoclose:
            return
        if delay <= 0:
            delay = 1
        self._close_timer.start(delay)

    @classmethod
    def active_popover(cls) -> Optional["ConnectionSettingsPopover"]:
        if cls._ACTIVE is not None and not cls._ACTIVE.isVisible():
            cls._ACTIVE = None
        return cls._ACTIVE

    @classmethod
    def set_active_popover(cls, popover: "ConnectionSettingsPopover") -> None:
        cls._ACTIVE = popover

    @classmethod
    def clear_active_popover(cls, popover: "ConnectionSettingsPopover") -> None:
        if cls._ACTIVE is popover:
            cls._ACTIVE = None

