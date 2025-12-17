import os
import time
import subprocess
import threading
from typing import Optional

from ..qt_compat import QtWidgets, QtCore, QtGui
from ..charon_logger import system_info, system_warning, system_error
from .. import preferences
from ..comfy_client import ComfyUIClient
from ..paths import extend_sys_path_with_comfy

class ComfyConnectionWidget(QtWidgets.QWidget):
    """Compact footer widget that monitors and configures ComfyUI connectivity."""

    connection_status_changed = QtCore.Signal(bool)
    client_changed = QtCore.Signal(object)

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
        self._status_color = "#cccccc"
        self._popover: Optional["ConnectionSettingsPopover"] = None
        self._manual_cursor_override = False
        self._launch_in_progress = False
        self._launch_started_at = 0.0

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

        self.status_label = QtWidgets.QLabel()
        self.status_label.setTextFormat(QtCore.Qt.RichText)
        self.status_label.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
        self.status_label.setTextInteractionFlags(QtCore.Qt.NoTextInteraction)
        layout.addWidget(self.status_label)
        self.status_label.hide()
        self.status_label.setFixedWidth(0)

        self.status_caption = QtWidgets.QLabel("ComfyUI Status:")
        self.status_caption.setAlignment(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignRight)
        self.status_caption.setStyleSheet("color: #ffffff;")
        layout.addWidget(self.status_caption)

        self.launch_button = QtWidgets.QPushButton("Launch")
        self.launch_button.setCursor(QtCore.Qt.PointingHandCursor)
        self.launch_button.clicked.connect(self._launch_comfyui)
        self.launch_button.setMinimumWidth(64)
        layout.addWidget(self.launch_button)

        self.separator_label = QtWidgets.QLabel("|")
        self.separator_label.setStyleSheet("color: #666666;")
        layout.addWidget(self.separator_label)

        self.settings_button = QtWidgets.QToolButton()
        self.settings_button.setText("\u2699")
        self.settings_button.setAutoRaise(True)
        self.settings_button.setCursor(QtCore.Qt.PointingHandCursor)
        self.settings_button.setToolTip("ComfyUI connection settings")
        self.settings_button.setMinimumWidth(20)
        self.settings_button.installEventFilter(self)
        self.settings_button.clicked.connect(lambda: self._show_settings_popover(auto_focus=True))
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
        if not self._comfy_path or self._check_in_progress:
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

            self._connection_check_finished.emit(connected, client, manual)

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
                    self._set_status("offline", False)
                    if status_changed:
                        system_warning("ComfyUI connection lost (watcher)")
                else:
                    self._set_status("path_required", False)
            self.client_changed.emit(None)

    def _set_status(self, state: str, connected: bool) -> None:
        mapping = {
            "online": ("Running", "#51cf66"),
            "offline": ("Offline", "#ff6b6b"),
            "path_required": ("Path Required", "#ff6b6b"),
            "checking": ("Checking...", "#d0a23f"),
            "launching": ("Launching...", "#d0a23f"),
            "unavailable": ("Client Unavailable", "#ffa94d"),
        }
        label_text, color = mapping.get(state, (state, "#cccccc"))
        html = f"ComfyUI: <span style='color:{color}; font-weight:bold;'>{label_text}</span>"

        previous_connection = self._connected
        previous_text = self.status_label.text()

        self.status_label.setText(html)
        self.status_label.setStyleSheet("")
        self._status_color = color
        self._connected = connected

        if connected != previous_connection:
            self.connection_status_changed.emit(connected)
        elif html != previous_text:
            self.status_label.update()

        self._update_launch_button(state, connected)

    def _update_launch_button(self, state: str, connected: bool) -> None:
        button = getattr(self, "launch_button", None)
        if button is None:
            return

        if connected:
            self._stop_button_blink()
            button.setEnabled(False)
            button.setCursor(QtCore.Qt.ArrowCursor)
            button.setText("Running")
            self._apply_button_style(button, "#37b24d", "#2f9e44", disabled=True)
        elif self._launch_in_progress or state == "launching":
            self._stop_button_blink()
            button.setEnabled(False)
            button.setCursor(QtCore.Qt.ArrowCursor)
            button.setText("Launching...")
            self._apply_button_style(button, "#f08c00", "#d9480f", disabled=True)
        else:
            button.setEnabled(True)
            button.setCursor(QtCore.Qt.PointingHandCursor)
            if state == "checking":
                button.setText("Checking...")
            else:
                button.setText("Press to Launch")
            self._start_button_blink()

    def _apply_button_style(
        self,
        button: QtWidgets.QPushButton,
        background: str,
        border: str,
        *,
        text_color: str = "#ffffff; font-weight: bold",
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
        button.setStyleSheet(style)

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
        if self._popover and self._popover.isVisible():
            if auto_focus:
                self._popover.focus_path_edit()
            return

        active = ConnectionSettingsPopover.active_popover()
        if active and active is not self._popover:
            active.close()

        popover = ConnectionSettingsPopover(self, self._comfy_path)
        popover.path_selected.connect(self._update_path)
        popover.retest_requested.connect(lambda: self._check_connection(manual=True))
        popover.finished.connect(lambda _result: self._clear_popover())

        button_rect = self.settings_button.rect()
        global_pos = self.settings_button.mapToGlobal(button_rect.bottomLeft())
        popover.move(global_pos)
        popover.show()
        if auto_focus:
            popover.focus_path_edit()

        self._popover = popover
        ConnectionSettingsPopover.set_active_popover(popover)

    def _clear_popover(self) -> None:
        if self._popover is not None:
            ConnectionSettingsPopover.clear_active_popover(self._popover)
        self._popover = None

    # -------------------------------------------------------------- Actions
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

        try:
            lower_path = path.lower()
            disable_flag = "--disable-auto-launch"

            if lower_path.endswith(".bat"):
                python_exe = os.path.join(base_dir, "python_embeded", "python.exe")
                main_script = os.path.join(base_dir, "ComfyUI", "main.py")
                if os.path.exists(python_exe) and os.path.exists(main_script):
                    cmd_line = [
                        "cmd",
                        "/c",
                        "start",
                        "",
                        python_exe,
                        "-s",
                        main_script,
                        "--windows-standalone-build",
                        disable_flag,
                    ]
                    subprocess.Popen(cmd_line, cwd=base_dir, shell=False)
                else:
                    fallback_cmd = ["cmd", "/c", "start", "", path, disable_flag]
                    subprocess.Popen(fallback_cmd, cwd=base_dir, shell=False)
            elif lower_path.endswith(".py"):
                subprocess.Popen(["python", path, "--api", disable_flag], cwd=base_dir, shell=False)
            else:
                subprocess.Popen([path, disable_flag], cwd=base_dir, shell=True)
            self._launch_in_progress = True
            self._launch_started_at = time.time()
            self._set_status("launching", self._connected)
            system_info(f"Launched ComfyUI from {path}")
        except Exception as exc:  # pragma: no cover - subprocess errors
            QtWidgets.QMessageBox.critical(self, "Launch ComfyUI", f"Failed to launch ComfyUI:\n{exc}")
            system_error(f"Failed to launch ComfyUI from {path}: {exc}")

    # ------------------------------------------------------------ Qt Events
    def eventFilter(self, obj, event):
        if obj is self.settings_button:
            if event.type() == QtCore.QEvent.Enter:
                self._show_settings_popover()
            elif event.type() == QtCore.QEvent.MouseButtonPress:
                self._show_settings_popover(auto_focus=True)
                return True
            elif event.type() == QtCore.QEvent.Leave:
                if self._popover and self._popover.isVisible():
                    self._popover.start_dismiss_countdown()
        return super().eventFilter(obj, event)

    @property
    def client(self) -> Optional[ComfyUIClient]:
        return self._client

    def current_client(self) -> Optional[ComfyUIClient]:
        """
        Compatibility helper for processor scripts that need the active client.
        """
        return self._client

    def current_comfy_path(self) -> str:
        """
        Expose the configured ComfyUI launch path without breaking encapsulation.
        """
        return self._comfy_path


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
            self.path_edit.setText(file_path)
            self.path_selected.emit(file_path.strip())
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
        current = self.path_edit.text().strip()
        if current != self._initial_path:
            self.path_selected.emit(current)
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

