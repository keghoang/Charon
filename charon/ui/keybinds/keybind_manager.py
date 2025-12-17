"""Central Keybind Manager (local keybinds only)."""

from typing import Any, Dict, Optional
from ...qt_compat import QtCore, QtWidgets
from .local_handler import LocalKeybindHandler
from ...settings import user_settings_db
from ... import config


class KeybindManager(QtCore.QObject):
    """
    Central manager for Charon keybind operations.

    Responsibilities:
    - Manage local keybind registration
    - Handle tiny-mode state and context switching
    - Manage user preferences
    """

    keybind_triggered = QtCore.Signal(str)  # action name

    def __init__(self, main_window: QtWidgets.QMainWindow, host: str):
        super().__init__(main_window)
        self.main_window = main_window
        self.host = host
        self.tiny_mode_active = False
        self.quick_search_shortcut = None

        self.local_handler = LocalKeybindHandler(main_window)
        self.app_settings = user_settings_db.get_app_settings_for_host(self.host)
        self._debug_logging_active: Optional[bool] = None
        self._apply_debug_logging_setting(initial=True)

        self.local_handler.keybind_triggered.connect(self._on_local_keybind)

        self.refresh_keybinds()

    def update_quick_search_context(self, tiny_mode: bool):
        """Update quick search keybind context based on tiny mode state."""
        if "quick_search" in self.local_handler.shortcuts:
            shortcut = self.local_handler.shortcuts["quick_search"]
            if tiny_mode:
                shortcut.setContext(QtCore.Qt.ApplicationShortcut)
            else:
                shortcut.setContext(QtCore.Qt.WindowShortcut)
            self.quick_search_shortcut = shortcut
        else:
            from ...charon_logger import system_warning

            system_warning("Quick search shortcut not found in local handler!")

    def set_tiny_mode(self, active: bool):
        """Set tiny mode state and update keybind contexts."""
        self.tiny_mode_active = active
        self.update_quick_search_context(active)

    def refresh_keybinds(self):
        """Refresh all local keybinds."""
        self._clear_all_keybinds()

        db_keybinds = user_settings_db.get_or_create_local_keybinds()
        self.local_handler.keybind_definitions = {}
        for action, data in db_keybinds.items():
            if data["enabled"]:
                self.local_handler.keybind_definitions[action] = data["key_sequence"]

        for action, key_seq in self.local_handler.get_keybind_definitions().items():
            self._register_local_keybind(action, key_seq)

        self.app_settings = user_settings_db.get_app_settings_for_host(self.host)
        if self.tiny_mode_active:
            QtCore.QTimer.singleShot(50, lambda: self.update_quick_search_context(True))

    def _register_local_keybind(self, action: str, key_sequence: str):
        """Register a local keybind."""
        self.local_handler.register_keybind(action, key_sequence)

    def _clear_all_keybinds(self):
        """Clear all registered keybinds."""
        self.local_handler.clear_all()
        QtWidgets.QApplication.processEvents()
        QtCore.QTimer.singleShot(10, lambda: None)

    def _on_local_keybind(self, action: str):
        """Handle local keybind trigger."""
        if action == "tiny_mode":
            self.set_tiny_mode(not self.tiny_mode_active)

        self.keybind_triggered.emit(action)

    def get_app_setting(self, key: str):
        """Return a stored application-level setting."""
        value = self.app_settings.get(key)
        if value is None:
            value = user_settings_db.get_app_setting_for_host(key, self.host)
            if value is not None:
                self.app_settings[key] = value
        return value

    def set_app_setting(self, key: str, value: Any) -> None:
        """Persist an application-level setting and refresh cache."""
        str_value = str(value)
        user_settings_db.set_app_setting_for_host(key, self.host, str_value)
        self.app_settings[key] = str_value
        if key == "debug_logging":
            self._apply_debug_logging_setting()
        elif key == "force_first_time_setup":
            # Keep raw preference (on/off) aligned with stored flag
            self.app_settings[key] = str_value

    def reset_app_settings_to_defaults(self) -> None:
        """Reset all application settings for the current host to defaults."""
        user_settings_db.reset_app_settings_for_host(self.host)
        self.app_settings = user_settings_db.get_app_settings_for_host(self.host)
        self._apply_debug_logging_setting()

    def get_all_app_settings(self) -> Dict[str, str]:
        """Return a copy of cached application settings."""
        return dict(self.app_settings)

    def _apply_debug_logging_setting(self, *, initial: bool = False) -> None:
        """Ensure config.DEBUG_MODE matches the stored preference."""
        value = self.app_settings.get("debug_logging", "off")
        enabled = str(value).lower() == "on"
        previous = self._debug_logging_active
        config.DEBUG_MODE = enabled
        self._debug_logging_active = enabled
        should_log = False
        if previous is None:
            should_log = enabled
        else:
            should_log = previous != enabled
        if should_log:
            from ...charon_logger import system_info
            state = "enabled" if enabled else "disabled"
            system_info(f"Debug logging {state} for host '{self.host}'.")

    def apply_debug_logging_setting(self) -> None:
        """Public wrapper so UI can re-apply after batch updates."""
        self._apply_debug_logging_setting()
