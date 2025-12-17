"""
Keybind Settings UI for Charon (local keybinds and preferences)."""

from typing import Dict, Optional
from ...qt_compat import QtWidgets, QtCore, QtGui, WindowContextHelpButtonHint, WindowCloseButtonHint
from ...settings import user_settings_db
from ...charon_logger import system_info
from ... import config, workflow_local_store, preferences
from .keybind_manager import KeybindManager
from .local_handler import LocalKeybindHandler
from ..dialogs import HotkeyDialog
from ...first_time_setup import (
    is_force_first_time_setup_enabled,
    set_force_first_time_setup,
    run_first_time_setup_if_needed,
)
from ...setup_manager import SetupManager
import os

VALUE_COLUMN_WIDTH = 140  # Fixed width for Settings tab value column


class KeybindSettingsDialog(QtWidgets.QDialog):
    """Main dialog for keybind settings and management."""
    
    def __init__(self, keybind_manager: KeybindManager, parent=None):
        super().__init__(parent)
        self.keybind_manager = keybind_manager
        self._settings_widgets = {}
        self.settings_table = None

        host_key = (self.keybind_manager.host or "standalone").lower()
        self._host_config = config.SOFTWARE.get(host_key, {})
        self._host_allows_settings = bool(self._host_config.get("host_settings", False))

        self.setWindowTitle("Settings")
        self.setWindowFlag(WindowContextHelpButtonHint, False)
        self.setWindowFlag(WindowCloseButtonHint, True)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        
        # Create UI
        self._create_ui()
        
        # Load data
        self._load_keybinds()
    
    def _create_ui(self):
        """Create the UI layout."""
        layout = QtWidgets.QVBoxLayout(self)
        
        # Tab widget for different sections
        self.tab_widget = QtWidgets.QTabWidget()
        layout.addWidget(self.tab_widget)
        
        # Create tabs in requested order: ComfyUI, host settings, then Charon
        self._create_comfy_tab()
        if self._host_allows_settings:
            self._create_settings_tab()
        self._create_local_tab()
        # Conflicts tab removed - Charon handles conflicts automatically

    def _create_comfy_tab(self):
        """Create ComfyUI settings tab (launch path)."""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)

        info = QtWidgets.QLabel(
            "Set the ComfyUI launch path used for validation and launches."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        form.setFormAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)

        self.comfy_path_edit = QtWidgets.QLineEdit()
        self.comfy_path_edit.setPlaceholderText("Path to ComfyUI launch .bat or .py")
        current_path = preferences.get_preference("comfyui_launch_path", "").strip()
        self.comfy_path_edit.setText(current_path)

        path_buttons = QtWidgets.QHBoxLayout()
        browse_btn = QtWidgets.QPushButton("Browse")
        browse_btn.clicked.connect(self._browse_comfy_path)
        save_btn = QtWidgets.QPushButton("Save")
        save_btn.clicked.connect(self._save_comfy_path)
        path_buttons.addWidget(browse_btn)
        path_buttons.addWidget(save_btn)
        path_buttons.addStretch()

        path_row = QtWidgets.QHBoxLayout()
        path_row.setContentsMargins(0, 0, 0, 0)
        path_row.setSpacing(6)
        path_row.addWidget(self.comfy_path_edit)
        path_row.addLayout(path_buttons)

        path_container = QtWidgets.QWidget()
        path_container.setLayout(path_row)
        form.addRow("ComfyUI Path:", path_container)
        layout.addLayout(form)

        self.comfy_status_label = QtWidgets.QLabel("")
        self.comfy_status_label.setStyleSheet("color: palette(mid);")
        layout.addWidget(self.comfy_status_label)

        layout.addStretch()

        footer_layout = QtWidgets.QHBoxLayout()
        footer_layout.addStretch()

        dep_check_btn = QtWidgets.QPushButton("Check Dependencies")
        dep_check_btn.setToolTip("Verify python environment and required custom nodes")
        dep_check_btn.setCursor(QtCore.Qt.PointingHandCursor)
        dep_check_btn.setFixedWidth(140)
        dep_check_btn.clicked.connect(self._check_dependencies)
        
        footer_layout.addWidget(dep_check_btn)
        layout.addLayout(footer_layout)

        self.tab_widget.addTab(widget, "Settings ComfyUI")
    
    def _create_settings_tab(self):
        """Create the application settings tab."""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        host_label = (self.keybind_manager.host or "Standalone")
        host_label = host_label.title() if host_label else "Standalone"
        self._settings_host_label = host_label
        info = QtWidgets.QLabel(f"These Charon settings are only active when Charon is running inside of {host_label}.")
        info.setWordWrap(True)
        layout.addWidget(info)

        table = QtWidgets.QTableWidget()
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(["Setting", "Value"])
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        header = table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setDefaultAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.Fixed)
        table.setColumnWidth(1, VALUE_COLUMN_WIDTH)
        layout.addWidget(table)
        self.settings_table = table
        self._populate_settings_rows()

        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addStretch()
        self.reset_settings_button = QtWidgets.QPushButton("Reset to Defaults")
        self.reset_settings_button.clicked.connect(self._reset_host_settings)
        button_layout.addWidget(self.reset_settings_button)
        self.reset_local_cache_button = QtWidgets.QPushButton("Reset Local Cache")
        self.reset_local_cache_button.clicked.connect(self._reset_local_cache)
        button_layout.addWidget(self.reset_local_cache_button)
        self.open_settings_folder_button = QtWidgets.QPushButton("Open Settings Folder")
        self.open_settings_folder_button.clicked.connect(self._open_settings_folder)
        button_layout.addWidget(self.open_settings_folder_button)
        layout.addLayout(button_layout)

        self.tab_widget.addTab(widget, f"Settings {host_label}")

    def _populate_settings_rows(self):
        """Populate the settings table with controls."""
        table = getattr(self, "settings_table", None)
        if table is None:
            return
        table.setRowCount(0)
        self._settings_widgets.clear()
        app_settings = self.keybind_manager.get_all_app_settings()
        host_label = (self.keybind_manager.host or "Standalone")
        host_label = host_label.title() if host_label else "Standalone"

        def _setup_combo(combo: QtWidgets.QComboBox, key: str) -> None:
            options = config.APP_SETTING_CHOICES.get(key, [])
            combo.clear()
            for option in options:
                combo.addItem(option.title(), option)
                index = combo.count() - 1
                combo.setItemData(index, QtCore.Qt.AlignCenter, QtCore.Qt.TextAlignmentRole)
            current_value = app_settings.get(key)
            if current_value is None and options:
                current_value = options[0]
            if current_value is not None:
                idx = combo.findData(current_value)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
                elif options:
                    combo.setCurrentIndex(0)
            elif options:
                combo.setCurrentIndex(0)

        def _create_offset_spin(key: str) -> QtWidgets.QSpinBox:
            spin = QtWidgets.QSpinBox()
            spin.setRange(-5000, 5000)
            spin.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
            spin.setAlignment(QtCore.Qt.AlignCenter)
            spin.setFixedWidth(48)
            raw_value = app_settings.get(key, "0")
            try:
                spin.setValue(int(float(raw_value)))
            except (TypeError, ValueError):
                spin.setValue(0)
            spin.valueChanged.connect(
                lambda value, setting=key: self._on_spin_changed(setting, value)
            )
            self._settings_widgets[key] = spin
            return spin

        # Debug logging row (toggle button)
        row = table.rowCount()
        table.insertRow(row)
        table.setItem(row, 0, QtWidgets.QTableWidgetItem("Debug Logging"))
        debug_value = app_settings.get("debug_logging", "off") == "on"
        debug_button = QtWidgets.QPushButton()
        debug_button.setCheckable(True)
        debug_button.setFixedHeight(24)
        debug_button.setMinimumWidth(80)
        debug_button.setChecked(debug_value)
        self._apply_debug_button_style(debug_button, debug_value)
        debug_button.toggled.connect(
            lambda checked, button=debug_button: self._on_debug_toggle(button, checked)
        )
        container = QtWidgets.QWidget()
        container_layout = QtWidgets.QHBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setAlignment(QtCore.Qt.AlignCenter)
        container_layout.addWidget(debug_button)
        container.setFixedWidth(VALUE_COLUMN_WIDTH)
        table.setCellWidget(row, 1, container)
        self._settings_widgets["debug_logging"] = debug_button

        # Force first-time setup row (preference-driven)
        row = table.rowCount()
        table.insertRow(row)
        table.setItem(row, 0, QtWidgets.QTableWidgetItem("Force First Time Setup (next launch)"))
        force_button = QtWidgets.QPushButton()
        force_button.setCheckable(True)
        force_on = is_force_first_time_setup_enabled()
        force_button.setChecked(force_on)
        self._apply_debug_button_style(force_button, force_on)
        force_button.toggled.connect(
            lambda checked, button=force_button: self._on_force_first_time_toggle(button, checked)
        )
        container_force = QtWidgets.QWidget()
        container_force_layout = QtWidgets.QHBoxLayout(container_force)
        container_force_layout.setContentsMargins(0, 0, 0, 0)
        container_force_layout.setAlignment(QtCore.Qt.AlignCenter)
        container_force_layout.addWidget(force_button)
        container_force.setFixedWidth(VALUE_COLUMN_WIDTH)
        table.setCellWidget(row, 1, container_force)
        self._settings_widgets["force_first_time_setup"] = force_button


    def _load_app_settings(self):
        """Refresh widgets with current values."""
        if not self._settings_widgets:
            return
        values = self.keybind_manager.get_all_app_settings()
        definitions = getattr(config, "APP_SETTING_DEFINITIONS", {})
        for key, widget in self._settings_widgets.items():
            if widget is None:
                continue
            widget.blockSignals(True)
            meta = definitions.get(key, {})
            if isinstance(widget, QtWidgets.QComboBox):
                desired = values.get(key, meta.get("default"))
                if desired is not None:
                    index = widget.findData(desired)
                    if index >= 0:
                        widget.setCurrentIndex(index)
            elif isinstance(widget, QtWidgets.QCheckBox):
                desired = values.get(key, meta.get("default", "off"))
                widget.setChecked(desired == "on")
            elif isinstance(widget, QtWidgets.QPushButton) and widget.isCheckable():
                if key == "force_first_time_setup":
                    checked = is_force_first_time_setup_enabled()
                else:
                    desired = values.get(key, meta.get("default", "off"))
                    checked = str(desired).lower() == "on"
                widget.setChecked(checked)
                self._apply_debug_button_style(widget, checked)
            elif isinstance(widget, QtWidgets.QSpinBox):
                desired = values.get(key, meta.get("default", "0"))
                try:
                    widget.setValue(int(float(desired)))
                except (TypeError, ValueError):
                    widget.setValue(0)
            widget.blockSignals(False)
        self.keybind_manager.apply_debug_logging_setting()
        # Force-first-time checkbox is handled above to stay in sync with preference
        force_widget = self._settings_widgets.get("force_first_time_setup")
        if isinstance(force_widget, QtWidgets.QPushButton):
            force_widget.blockSignals(True)
            force_widget.setChecked(is_force_first_time_setup_enabled())
            self._apply_debug_button_style(force_widget, force_widget.isChecked())
            force_widget.blockSignals(False)

    def _on_combo_changed(self, key: str, value: Optional[str]) -> None:
        """Persist combo-box setting changes."""
        if value is None:
            return
        self.keybind_manager.set_app_setting(key, value)

    def _set_offset_from_current(self) -> None:
        """Capture the current tiny-mode window offset and persist it."""
        parent = self.parent()
        if not parent or not hasattr(parent, "get_current_tiny_mode_offset"):
            return
        offsets = parent.get_current_tiny_mode_offset()
        if offsets is None:
            QtWidgets.QMessageBox.information(
                self,
                "Set Tiny Offset",
                "Open Tiny Mode to capture its current window position."
            )
            return
        offset_x, offset_y = offsets
        for key, value in (("tiny_offset_x", offset_x), ("tiny_offset_y", offset_y)):
            widget = self._settings_widgets.get(key)
            if isinstance(widget, QtWidgets.QSpinBox):
                widget.blockSignals(True)
                widget.setValue(int(value))
                widget.blockSignals(False)
                self._on_spin_changed(key, widget.value())

    def _on_checkbox_changed(self, key: str, checked: bool) -> None:
        """Persist checkbox setting changes."""
        value = "on" if checked else "off"
        self.keybind_manager.set_app_setting(key, value)

        if key == "always_on_top":
            self._refresh_tiny_mode_if_needed()

    def _on_force_first_time_toggle(self, button: QtWidgets.QPushButton, enabled: bool) -> None:
        """Persist the force-first-time-setup toggle in preferences."""
        try:
            set_force_first_time_setup(enabled)
            # Mirror into host app settings cache so the checkbox stays sticky this session
            self.keybind_manager.set_app_setting("force_first_time_setup", "on" if enabled else "off")
            self._apply_debug_button_style(button, enabled)
            host_label = self.keybind_manager.host or "Standalone"
            state = "enabled" if enabled else "disabled"
            system_info(f"Force first-time setup {state} for host '{host_label}'.")
            if enabled:
                QtWidgets.QMessageBox.information(
                    self,
                    "First Time Setup",
                    "The first-time setup screen will appear on the next launch.",
                )
        except Exception as exc:
            QtWidgets.QMessageBox.warning(
                self,
                "First Time Setup",
                f"Could not update first-time setup preference: {exc}",
            )

    def _on_debug_toggle(self, button: QtWidgets.QPushButton, checked: bool) -> None:
        """Toggle debug logging preference."""
        self._apply_debug_button_style(button, checked)
        self.keybind_manager.set_app_setting("debug_logging", "on" if checked else "off")

    def _on_spin_changed(self, key: str, value: int) -> None:
        """Persist spin-box setting changes."""
        self.keybind_manager.set_app_setting(key, value)
        if key in {"tiny_offset_x", "tiny_offset_y"}:
            self._notify_tiny_offset_changed()

    def _notify_tiny_offset_changed(self) -> None:
        """Tell the parent window that default tiny offsets changed."""
        parent = self.parent()
        if parent and hasattr(parent, "mark_tiny_offset_dirty"):
            try:
                parent.mark_tiny_offset_dirty()
            except Exception:
                pass

    def _reset_host_settings(self):
        """Reset current host settings to defaults."""
        host_label = getattr(self, '_settings_host_label', (self.keybind_manager.host or 'Standalone'))
        reply = QtWidgets.QMessageBox.question(
            self,
            "Reset Settings",
            f"Reset Charon settings for {host_label}?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return
        try:
            self.keybind_manager.reset_app_settings_to_defaults()
        except Exception as exc:
            QtWidgets.QMessageBox.warning(
                self,
                "Reset Settings",
                f"Failed to reset settings: {exc}"
            )
            return
        self._load_app_settings()
        self._notify_tiny_offset_changed()
        self._refresh_tiny_mode_if_needed()
        self.keybind_manager.apply_debug_logging_setting()

    def _reset_local_cache(self) -> None:
        """Clear the per-user Charon_repo_local folder."""
        root_path = workflow_local_store.get_local_repository_root(ensure=False)
        if not root_path:
            root_path = workflow_local_store.get_local_repository_root(ensure=True)
        prompt = (
            "Delete the local workflow cache?\n\n"
            f"All cached workflows under:\n{root_path}\n\n"
            "will be removed. This does not touch the shared repository."
        )
        reply = QtWidgets.QMessageBox.question(
            self,
            "Reset Local Cache",
            prompt,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return

        self.reset_local_cache_button.setEnabled(False)
        QtWidgets.QApplication.processEvents()
        try:
            success = workflow_local_store.reset_local_repository()
        finally:
            self.reset_local_cache_button.setEnabled(True)

        if success:
            QtWidgets.QMessageBox.information(
                self,
                "Reset Local Cache",
                "Local cache cleared successfully.",
            )
        else:
            QtWidgets.QMessageBox.warning(
                self,
                "Reset Local Cache",
                "Unable to clear the local cache. Check the Charon console for details.",
            )

    def _refresh_tiny_mode_if_needed(self):
        parent = self.parent()
        if not parent:
            return
        if not getattr(self.keybind_manager, 'tiny_mode_active', False):
            return
        if hasattr(parent, '_apply_tiny_mode_flags'):
            parent._apply_tiny_mode_flags()
            if hasattr(parent, 'stacked_widget') and hasattr(parent, 'tiny_mode_widget'):
                try:
                    parent.stacked_widget.setCurrentWidget(parent.tiny_mode_widget)
                except Exception:
                    pass
            parent.raise_()
            parent.activateWindow()

    def _create_local_tab(self):
        """Create the local keybinds tab."""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        
        # Info label
        info_label = QtWidgets.QLabel(
            "These keybinds are only active when Charon window has focus.\n"
            "They control Charon's UI functions."
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        
        # Table for local keybinds
        self.local_table = QtWidgets.QTableWidget()
        self.local_table.setColumnCount(4)
        self.local_table.setHorizontalHeaderLabels(["Action", "Keybind", "Edit", "Remove"])
        self.local_table.horizontalHeader().setStretchLastSection(False)
        self.local_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self.local_table.setAlternatingRowColors(True)
        self.local_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        
        # Set column widths
        self.local_table.setColumnWidth(1, 150)  # Keybind column
        self.local_table.setColumnWidth(2, 60)   # Edit column
        self.local_table.setColumnWidth(3, 80)   # Remove column
        
        layout.addWidget(self.local_table)
        
        # Reset button at bottom right
        reset_layout = QtWidgets.QHBoxLayout()
        reset_layout.addStretch()
        self.reset_local_button = QtWidgets.QPushButton("Reset to Defaults")
        self.reset_local_button.clicked.connect(self._reset_local_keybinds)
        reset_layout.addWidget(self.reset_local_button)
        layout.addLayout(reset_layout)
        
        self.tab_widget.addTab(widget, "Charon Keybinds")

    def _apply_debug_button_style(self, button: QtWidgets.QPushButton, checked: bool) -> None:
        """Update the appearance/text of the debug toggle button."""
        button.setText("On" if checked else "Off")
        if checked:
            button.setStyleSheet(
                "QPushButton {"
                " background-color: #228B22;"
                " color: white;"
                " border: none;"
                " border-radius: 4px;"
                " padding: 2px 10px;"
                " }"
                "QPushButton:pressed {"
                " background-color: #196f1a;"
                " }"
            )
        else:
            button.setStyleSheet(
                "QPushButton {"
                " background-color: #2f3542;"
                " color: #f0f0f0;"
                " border-radius: 4px;"
                " padding: 2px 10px;"
                " }"
                "QPushButton:pressed {"
                " background-color: #3d4350;"
                " }"
            )
    def _load_keybinds(self):
        """Load all keybind data into the tables."""
        self._load_local_keybinds()
        self._load_app_settings()
        # Conflicts loading removed - Charon handles conflicts automatically
    
    def _load_local_keybinds(self):
        """Load local keybinds into the table."""
        # Get full keybind info from handler
        keybind_info = self.keybind_manager.local_handler.get_full_keybind_info()
        
        # Action display names
        action_names = {
            'quick_search': 'Quick Search',
            'refresh': 'Refresh',
            'open_folder': 'Open Folder',
            'tiny_mode': 'Tiny Mode'
        }
        
        # Ensure we show all default actions including tiny_mode
        all_actions = set(LocalKeybindHandler.DEFAULT_KEYBINDS.keys())
        all_actions.update(keybind_info.keys())
        
        self.local_table.setRowCount(len(all_actions))
        
        for row, action in enumerate(sorted(all_actions)):
            # Action name
            action_item = QtWidgets.QTableWidgetItem(action_names.get(action, action))
            action_item.setFlags(action_item.flags() & ~QtCore.Qt.ItemIsEditable)
            action_item.setData(QtCore.Qt.UserRole, action)  # Store actual action name
            self.local_table.setItem(row, 0, action_item)
            
            # Get keybind data
            data = keybind_info.get(action, {
                'key_sequence': LocalKeybindHandler.DEFAULT_KEYBINDS.get(action, ''),
                'enabled': True,
                'default': LocalKeybindHandler.DEFAULT_KEYBINDS.get(action, '')
            })
            
            # Keybind - show current keybind (whether default or custom)
            current_key = data['key_sequence']
            
            hotkey_item = QtWidgets.QTableWidgetItem(current_key)
            hotkey_item.setFlags(hotkey_item.flags() & ~QtCore.Qt.ItemIsEditable)
            hotkey_item.setFont(QtGui.QFont(hotkey_item.font().family(), -1, QtGui.QFont.Bold))
            self.local_table.setItem(row, 1, hotkey_item)
            
            # Edit button column
            edit_widget = QtWidgets.QWidget()
            edit_layout = QtWidgets.QHBoxLayout(edit_widget)
            edit_layout.setContentsMargins(0, 0, 0, 0)
            edit_layout.setAlignment(QtCore.Qt.AlignCenter)
            
            edit_button = QtWidgets.QPushButton("Edit")
            edit_button.clicked.connect(lambda checked=False, r=row: self._edit_local_keybind(r))
            edit_layout.addWidget(edit_button)
            
            self.local_table.setCellWidget(row, 2, edit_widget)
            
            # Remove button column
            remove_widget = QtWidgets.QWidget()
            remove_layout = QtWidgets.QHBoxLayout(remove_widget)
            remove_layout.setContentsMargins(0, 0, 0, 0)
            remove_layout.setAlignment(QtCore.Qt.AlignCenter)
            
            remove_button = QtWidgets.QPushButton("Remove")
            remove_button.clicked.connect(lambda checked=False, r=row: self._remove_local_keybind(r))
            remove_button.setEnabled(bool(current_key))  # Disable if no keybind
            remove_layout.addWidget(remove_button)
            
            self.local_table.setCellWidget(row, 3, remove_widget)
    
    def _remove_local_keybind(self, row: int):
        """Remove a local keybind."""
        action_item = self.local_table.item(row, 0)
        if not action_item:
            return
            
        action = action_item.data(QtCore.Qt.UserRole)
        
        # Clear the keybind in the table
        hotkey_item = self.local_table.item(row, 1)
        if hotkey_item:
            hotkey_item.setText("")
            hotkey_item.setData(QtCore.Qt.UserRole, "")  # Mark as removed
            
        # Disable the remove button
        remove_widget = self.local_table.cellWidget(row, 3)
        if remove_widget:
            remove_button = remove_widget.findChild(QtWidgets.QPushButton)
            if remove_button:
                remove_button.setEnabled(False)
        
        # Save immediately
        user_settings_db.set_local_keybind(action, "", True)
        
        # Process events to ensure database operation completes
        QtWidgets.QApplication.processEvents()
        
        # Refresh keybinds
        self._refresh_keybinds()
    
    def _edit_local_keybind(self, row: int):
        """Edit a local keybind."""
        action_item = self.local_table.item(row, 0)
        if not action_item:
            return
            
        action = action_item.data(QtCore.Qt.UserRole)
        
        dialog = HotkeyDialog(self)
        dialog.resize(300, 100)
        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            new_key = dialog.hotkey
            conflicting_action = None

            # Check for conflicts with other local keybinds
            local_defs = self.keybind_manager.local_handler.get_keybind_definitions()

            # Find if any other local keybind uses this key
            for other_action, key_seq in local_defs.items():
                if key_seq == new_key and other_action != action:
                    conflicting_action = other_action
                    break

            if conflicting_action:
                # For Charon vs Charon, just reassign without asking
                # Find the row with the conflicting action and clear its keybind
                for i in range(self.local_table.rowCount()):
                    item = self.local_table.item(i, 0)
                    if item and item.data(QtCore.Qt.UserRole) == conflicting_action:
                        # Clear the conflicting keybind
                        hotkey_item = self.local_table.item(i, 1)
                        if hotkey_item:
                            hotkey_item.setText("")
                            hotkey_item.setData(QtCore.Qt.UserRole, "")  # Mark as removed
                        
                        # Disable its remove button
                        remove_widget = self.local_table.cellWidget(i, 3)
                        if remove_widget:
                            remove_button = remove_widget.findChild(QtWidgets.QPushButton)
                            if remove_button:
                                remove_button.setEnabled(False)
                        break
            
            # Update the table
            hotkey_item = self.local_table.item(row, 1)
            if hotkey_item:
                hotkey_item.setText(new_key)
                hotkey_item.setData(QtCore.Qt.UserRole, new_key)
                hotkey_item.setBackground(QtGui.QColor(255, 255, 200))
                
            # Enable the remove button
            remove_widget = self.local_table.cellWidget(row, 3)
            if remove_widget:
                remove_button = remove_widget.findChild(QtWidgets.QPushButton)
                if remove_button:
                    remove_button.setEnabled(True)
            
            # Save the keybind immediately
            user_settings_db.set_local_keybind(action, new_key, True)
            
            # If we cleared another local keybind, save that too
            if conflicting_action:
                user_settings_db.set_local_keybind(conflicting_action, "", True)
            
            # Process events to ensure all database operations complete
            QtWidgets.QApplication.processEvents()
            
            # Refresh keybinds
            self._refresh_keybinds()
    
    def _reset_local_keybinds(self):
        """Reset all local keybinds to defaults."""
        defaults = LocalKeybindHandler.DEFAULT_KEYBINDS

        message = "Reset all Charon keybinds to their default values?"
        reply = QtWidgets.QMessageBox.question(
            self,
            "Reset Keybinds",
            message,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )

        if reply == QtWidgets.QMessageBox.Yes:
            for action, default_key in defaults.items():
                user_settings_db.reset_local_keybind(action)

            # Refresh keybinds - this will update the table
            self._refresh_keybinds()

    def _open_settings_folder(self):
        """Open the on-disk settings directory in the system file browser."""
        try:
            folder_path = user_settings_db.get_storage_directory()
        except RuntimeError as exc:
            QtWidgets.QMessageBox.warning(
                self,
                "Settings Folder",
                "Settings data is not available yet.\n\n{0}".format(exc),
            )
            return

        if not folder_path or not os.path.isdir(folder_path):
            QtWidgets.QMessageBox.warning(
                self,
                "Settings Folder",
                "Settings folder could not be located.",
            )
            return

        url = QtCore.QUrl.fromLocalFile(folder_path)
        if not QtGui.QDesktopServices.openUrl(url):
            QtWidgets.QMessageBox.warning(
                self,
                "Settings Folder",
                "Unable to open the settings folder.",
            )
            return

    # -------------------------------------------------- ComfyUI settings
    def _update_comfy_path(self, path: str) -> None:
        path = (path or "").strip()
        self.comfy_path_edit.setText(path)
        preferences.set_preference("comfyui_launch_path", path, parent=self)
        self.comfy_status_label.clear()

    def _save_comfy_path(self) -> None:
        new_path = self.comfy_path_edit.text().strip()
        old_path = preferences.get_preference("comfyui_launch_path", "").strip()
        
        self._update_comfy_path(new_path)
        
        if new_path and new_path != old_path:
            QtWidgets.QMessageBox.information(
                self,
                "Path Changed",
                "ComfyUI path has been updated.\n"
                "First-Time Setup will now run to verify the new environment."
            )
            self.accept()
            # Launch FTS using the parent window as the parent for the dialog
            run_first_time_setup_if_needed(parent=self.parent(), force=True)

    def _browse_comfy_path(self) -> None:
        start_dir = os.path.dirname(self.comfy_path_edit.text().strip()) or os.getcwd()
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select ComfyUI Launch Script",
            start_dir,
            "Scripts (*.bat *.py);;All Files (*)",
        )
        if file_path:
            self.comfy_path_edit.setText(file_path.strip())

    def _format_action_name(self, action: str) -> str:
        """Format action name for display."""
        return action.replace('_', ' ').title()
    
    def _refresh_keybinds(self):
        """Refresh keybinds and reload tables."""
        # Refresh the keybind manager
        self.keybind_manager.refresh_keybinds()
        
        # Trigger main window refresh to update UI
        if hasattr(self.parent(), 'on_metadata_changed'):
            self.parent().on_metadata_changed()
        
        # Reload the tables to show current state
        self._load_keybinds()

    def _check_dependencies(self):
        """Manually check dependencies and prompt for setup if missing."""
        path = self.comfy_path_edit.text().strip()
        if not path:
            QtWidgets.QMessageBox.warning(self, "Check Dependencies", "Please set a ComfyUI path first.")
            return

        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            manager = SetupManager(path)
            status_map = manager.check_dependencies()
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

        missing = [k for k, v in status_map.items() if v != "found"]
        
        if not missing:
            QtWidgets.QMessageBox.information(self, "Check Dependencies", "All dependencies verified successfully.")
            return

        msg = "The following dependencies are missing or incomplete:\n\n"
        for m in missing:
            msg += f"- {m}\n"
        msg += "\nWould you like to run the First-Time Setup wizard to attempt installation?"

        reply = QtWidgets.QMessageBox.question(
            self,
            "Missing Dependencies",
            msg,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )

        if reply == QtWidgets.QMessageBox.Yes:
            # Force run the setup dialog
            success = run_first_time_setup_if_needed(parent=self, force=True)
            if success:
                QtWidgets.QMessageBox.information(self, "Setup", "Setup completed successfully.")
    
    

