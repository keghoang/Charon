"""
Keybind Settings UI

Provides a dialog for managing both local and global keybinds,
viewing conflicts, and customizing keybind behavior.
"""

from typing import Dict, Optional
from ...qt_compat import QtWidgets, QtCore, QtGui, WindowContextHelpButtonHint, WindowCloseButtonHint
from ...settings import user_settings_db
from ... import config
from .keybind_manager import KeybindManager
from .local_handler import LocalKeybindHandler
from ..dialogs import HotkeyDialog
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
        
        # Create tabs - Global first, then Charon
        self._create_global_tab()
        self._create_local_tab()
        if self._host_allows_settings:
            self._create_settings_tab()
        # Conflicts tab removed - Charon handles conflicts automatically
        
    
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

        # Startup mode row (dropdown)
        row = table.rowCount()
        table.insertRow(row)
        table.setItem(row, 0, QtWidgets.QTableWidgetItem("Startup mode"))
        mode_combo = QtWidgets.QComboBox()
        _setup_combo(mode_combo, "startup_mode")
        mode_combo.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToContents)
        container = QtWidgets.QWidget()
        container_layout = QtWidgets.QHBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setAlignment(QtCore.Qt.AlignCenter)
        container_layout.addWidget(mode_combo)
        container.setFixedWidth(VALUE_COLUMN_WIDTH)
        mode_combo.setFixedWidth(VALUE_COLUMN_WIDTH)
        if mode_combo.view():
            mode_combo.view().setMinimumWidth(VALUE_COLUMN_WIDTH)
        mode_combo.currentIndexChanged.connect(
            lambda idx, combo=mode_combo: self._on_combo_changed("startup_mode", combo.itemData(idx))
        )
        table.setCellWidget(row, 1, container)
        self._settings_widgets["startup_mode"] = mode_combo

        # Run at App Startup row (checkbox)
        row = table.rowCount()
        table.insertRow(row)
        table.setItem(row, 0, QtWidgets.QTableWidgetItem("Run at App Startup"))
        run_checkbox = QtWidgets.QCheckBox()
        run_checkbox.setChecked(app_settings.get("run_at_startup", "off") == "on")
        run_checkbox.stateChanged.connect(
            lambda state, box=run_checkbox: self._on_checkbox_changed("run_at_startup", box.isChecked())
        )
        container = QtWidgets.QWidget()
        container_layout = QtWidgets.QHBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setAlignment(QtCore.Qt.AlignCenter)
        container_layout.addWidget(run_checkbox)
        container.setFixedWidth(VALUE_COLUMN_WIDTH)
        table.setCellWidget(row, 1, container)
        self._settings_widgets["run_at_startup"] = run_checkbox


        # Advanced User Mode row (checkbox)
        row = table.rowCount()
        table.insertRow(row)
        table.setItem(row, 0, QtWidgets.QTableWidgetItem("Advanced User Mode"))
        advanced_checkbox = QtWidgets.QCheckBox()
        advanced_checkbox.setChecked(app_settings.get("advanced_user_mode", "off") == "on")
        advanced_checkbox.stateChanged.connect(
            lambda state, box=advanced_checkbox: self._on_checkbox_changed("advanced_user_mode", box.isChecked())
        )
        container = QtWidgets.QWidget()
        container_layout = QtWidgets.QHBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setAlignment(QtCore.Qt.AlignCenter)
        container_layout.addWidget(advanced_checkbox)
        container.setFixedWidth(VALUE_COLUMN_WIDTH)
        table.setCellWidget(row, 1, container)
        self._settings_widgets["advanced_user_mode"] = advanced_checkbox


        # Always on Top row (checkbox)
        row = table.rowCount()
        table.insertRow(row)
        table.setItem(row, 0, QtWidgets.QTableWidgetItem("Tiny Mode Always on Top"))
        top_checkbox = QtWidgets.QCheckBox()
        top_checkbox.setChecked(app_settings.get("always_on_top", "off") == "on")
        top_checkbox.stateChanged.connect(
            lambda state, box=top_checkbox: self._on_checkbox_changed("always_on_top", box.isChecked())
        )
        container = QtWidgets.QWidget()
        container_layout = QtWidgets.QHBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setAlignment(QtCore.Qt.AlignCenter)
        container_layout.addWidget(top_checkbox)
        container.setFixedWidth(VALUE_COLUMN_WIDTH)
        table.setCellWidget(row, 1, container)
        self._settings_widgets["always_on_top"] = top_checkbox

        # Tiny Mode Window Offset row (dual spin boxes + capture button)
        row = table.rowCount()
        table.insertRow(row)
        table.setItem(row, 0, QtWidgets.QTableWidgetItem("Tiny Mode Window Offset"))

        offset_container = QtWidgets.QWidget()
        outer_layout = QtWidgets.QVBoxLayout(offset_container)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(4)

        coord_widget = QtWidgets.QWidget()
        coord_layout = QtWidgets.QHBoxLayout(coord_widget)
        coord_layout.setContentsMargins(0, 0, 0, 0)
        coord_layout.setSpacing(6)
        coord_layout.setAlignment(QtCore.Qt.AlignCenter)

        x_label = QtWidgets.QLabel("X")
        x_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        coord_layout.addWidget(x_label)
        coord_layout.addWidget(_create_offset_spin("tiny_offset_x"))

        coord_layout.addSpacing(8)

        y_label = QtWidgets.QLabel("Y")
        y_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        coord_layout.addWidget(y_label)
        coord_layout.addWidget(_create_offset_spin("tiny_offset_y"))

        outer_layout.addWidget(coord_widget, alignment=QtCore.Qt.AlignCenter)

        set_button = QtWidgets.QPushButton("Set Current")
        set_button.setFixedHeight(22)
        set_button.clicked.connect(self._set_offset_from_current)
        outer_layout.addWidget(set_button, alignment=QtCore.Qt.AlignCenter)

        offset_container.setFixedWidth(VALUE_COLUMN_WIDTH)
        table.setCellWidget(row, 1, offset_container)
        table.setRowHeight(row, 70)

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
            elif isinstance(widget, QtWidgets.QSpinBox):
                desired = values.get(key, meta.get("default", "0"))
                try:
                    widget.setValue(int(float(desired)))
                except (TypeError, ValueError):
                    widget.setValue(0)
            widget.blockSignals(False)

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
    
    def _create_global_tab(self):
        """Create the global keybinds tab."""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        
        # Info label
        info_label = QtWidgets.QLabel(
            "These keybinds are always active, even when Charon is not focused.\n"
            "They allow quick script execution from anywhere."
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        
        
        # Table for global keybinds
        self.global_table = QtWidgets.QTableWidget()
        self.global_table.setColumnCount(4)
        self.global_table.setHorizontalHeaderLabels(["Action", "Keybind", "Edit", "Remove"])
        self.global_table.horizontalHeader().setStretchLastSection(False)
        self.global_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self.global_table.setAlternatingRowColors(True)
        self.global_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        
        # Set column widths to match local table
        self.global_table.setColumnWidth(1, 150)  # Keybind column
        self.global_table.setColumnWidth(2, 60)   # Edit column
        self.global_table.setColumnWidth(3, 80)   # Remove column
        
        layout.addWidget(self.global_table)
        
        self.tab_widget.addTab(widget, "Global Keybinds")
    
    # Conflicts tab removed - Charon handles conflicts automatically
    '''
    def _create_conflicts_tab(self):
        """Create the conflicts tab."""
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        
        # Info label
        info_label = QtWidgets.QLabel(
            "When global and local keybinds conflict, you can choose which takes priority.\n"
            "By default, global keybinds override local ones."
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        
        # Table for conflicts
        self.conflicts_table = QtWidgets.QTableWidget()
        self.conflicts_table.setColumnCount(5)
        self.conflicts_table.setHorizontalHeaderLabels([
            "Key", "Local Action", "Global Script", "Priority", "Actions"
        ])
        self.conflicts_table.horizontalHeader().setStretchLastSection(False)
        self.conflicts_table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Stretch)
        self.conflicts_table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)
        self.conflicts_table.setAlternatingRowColors(True)
        self.conflicts_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        layout.addWidget(self.conflicts_table)
        
        self.tab_widget.addTab(widget, "Conflicts")
    '''
    
    def _load_keybinds(self):
        """Load all keybind data into the tables."""
        self._load_local_keybinds()
        self._load_global_keybinds()
        self._load_app_settings()
        # Conflicts loading removed - Charon handles conflicts automatically
    
    def _load_local_keybinds(self):
        """Load local keybinds into the table."""
        # Get full keybind info from handler
        keybind_info = self.keybind_manager.local_handler.get_full_keybind_info()
        
        # Action display names
        action_names = {
            'quick_search': 'Quick Search',
            'run_script': 'Run Script',
            'refresh': 'Refresh',
            'open_folder': 'Open Folder',
            'settings': 'Open Settings',
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
    
    def _load_global_keybinds(self):
        """Load global keybinds into the table."""
        global_keybinds = self.keybind_manager.global_handler.get_keybind_definitions()
        
        # Sort by script name alphabetically
        sorted_keybinds = sorted(global_keybinds.items(), key=lambda x: os.path.basename(x[0]).lower())
        
        self.global_table.setRowCount(len(sorted_keybinds))
        
        # Process global keybinds
        for row, (script_path, key_sequence) in enumerate(sorted_keybinds):
            
            # Action name (use folder name since script_path points to folder)
            script_name = os.path.basename(script_path)
            script_item = QtWidgets.QTableWidgetItem(script_name)
            script_item.setFlags(script_item.flags() & ~QtCore.Qt.ItemIsEditable)
            script_item.setData(QtCore.Qt.UserRole, script_path)  # Store full path
            script_item.setToolTip(script_path)
            self.global_table.setItem(row, 0, script_item)
            
            # Keybind
            key_item = QtWidgets.QTableWidgetItem(key_sequence)
            key_item.setFlags(key_item.flags() & ~QtCore.Qt.ItemIsEditable)
            key_item.setFont(QtGui.QFont(key_item.font().family(), -1, QtGui.QFont.Bold))
            self.global_table.setItem(row, 1, key_item)
            
            # Edit button column
            edit_widget = QtWidgets.QWidget()
            edit_layout = QtWidgets.QHBoxLayout(edit_widget)
            edit_layout.setContentsMargins(0, 0, 0, 0)
            edit_layout.setAlignment(QtCore.Qt.AlignCenter)
            
            edit_button = QtWidgets.QPushButton("Edit")
            edit_button.clicked.connect(lambda checked=False, r=row: self._edit_global_keybind(r))
            edit_layout.addWidget(edit_button)
            
            self.global_table.setCellWidget(row, 2, edit_widget)
            
            # Remove button column
            remove_widget = QtWidgets.QWidget()
            remove_layout = QtWidgets.QHBoxLayout(remove_widget)
            remove_layout.setContentsMargins(0, 0, 0, 0)
            remove_layout.setAlignment(QtCore.Qt.AlignCenter)
            
            remove_button = QtWidgets.QPushButton("Remove")
            remove_button.clicked.connect(lambda checked=False, sp=script_path: self._remove_single_global_keybind(sp))
            remove_layout.addWidget(remove_button)
            
            self.global_table.setCellWidget(row, 3, remove_widget)
    
    # Conflicts loading removed - Charon handles conflicts automatically
    '''
    def _load_conflicts(self):
        """Load keybind conflicts into the table."""
        conflicts = self.keybind_manager.get_conflicts()
        
        self.conflicts_table.setRowCount(len(conflicts))
        
        for row, conflict in enumerate(conflicts):
            # Key sequence
            key_item = QtWidgets.QTableWidgetItem(conflict['key_sequence'])
            key_item.setFlags(key_item.flags() & ~QtCore.Qt.ItemIsEditable)
            self.conflicts_table.setItem(row, 0, key_item)
            
            # Local action
            local_item = QtWidgets.QTableWidgetItem(
                self._format_action_name(conflict['local_action'])
            )
            local_item.setFlags(local_item.flags() & ~QtCore.Qt.ItemIsEditable)
            self.conflicts_table.setItem(row, 1, local_item)
            
            # Global script (use folder name since path points to folder)
            script_name = os.path.basename(conflict['global_script'])
            global_item = QtWidgets.QTableWidgetItem(script_name)
            global_item.setFlags(global_item.flags() & ~QtCore.Qt.ItemIsEditable)
            global_item.setToolTip(conflict['global_script'])
            self.conflicts_table.setItem(row, 2, global_item)
            
            # Priority combo
            priority_combo = QtWidgets.QComboBox()
            priority_combo.addItems(["Global Priority", "Local Priority", "Disabled"])
            
            # Set current selection
            resolution = conflict['resolution']
            if resolution == 'global':
                priority_combo.setCurrentIndex(0)
            elif resolution == 'local':
                priority_combo.setCurrentIndex(1)
            else:
                priority_combo.setCurrentIndex(2)
            
            # Store conflict data
            priority_combo.setProperty('conflict_data', conflict)
            
            self.conflicts_table.setCellWidget(row, 3, priority_combo)
            
            # Actions
            action_widget = QtWidgets.QWidget()
            action_layout = QtWidgets.QHBoxLayout(action_widget)
            action_layout.setContentsMargins(0, 0, 0, 0)
            
            resolve_button = QtWidgets.QPushButton("Auto-Resolve")
            resolve_button.clicked.connect(lambda checked, c=conflict: self._auto_resolve_conflict(c))
            action_layout.addWidget(resolve_button)
            
            action_layout.addStretch()
            self.conflicts_table.setCellWidget(row, 4, action_widget)
    '''
    
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
            
            # Import ConflictType for centralized handling
            from .conflict_resolver import ConflictType
            
            # Action display names
            action_names = {
                'quick_search': 'Quick Search',
                'run_script': 'Run Script',
                'refresh': 'Refresh',
                'open_folder': 'Open Folder',
                'settings': 'Open Settings',
                'tiny_mode': 'Tiny Mode'
            }
            
            # Initialize conflict tracking variables
            conflicting_script = None
            conflicting_action = None
            
            # Check for conflicts with global keybinds
            global_defs = self.keybind_manager.global_handler.get_keybind_definitions()
            
            # Find if any global keybind uses this key
            for script_path, key_seq in global_defs.items():
                if key_seq == new_key:
                    conflicting_script = script_path
                    break
            
            if conflicting_script:
                # When assigning to local, global keybind gets unassigned
                script_name = os.path.basename(conflicting_script)
                current_name = script_name
                new_name = action_names.get(action, action)
                
                # Use unified dialog
                from .conflict_resolver import KeybindConflictDialog
                dialog = KeybindConflictDialog(self, new_key, current_name, new_name)
                
                if dialog.exec_() != QtWidgets.QDialog.Accepted:
                    return  # User cancelled
                
                # Remove the global keybind
                user_settings_db.remove_hotkey_for_script_software(
                    conflicting_script, self.keybind_manager.host
                )
                
                # Process events to ensure database operation completes
                QtWidgets.QApplication.processEvents()
            else:
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
    
    def _edit_global_keybind(self, row: int):
        """Edit a global keybind."""
        script_item = self.global_table.item(row, 0)
        if not script_item:
            return
            
        script_path = script_item.data(QtCore.Qt.UserRole)
        
        
        dialog = HotkeyDialog(self)
        dialog.resize(300, 100)
        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            new_key = dialog.hotkey
            
            # Import ConflictType for centralized handling
            from .conflict_resolver import ConflictType
            
            # Check for conflicts with local keybinds
            local_defs = self.keybind_manager.local_handler.get_keybind_definitions()
            local_by_key = {seq: action for action, seq in local_defs.items()}
            
            if new_key in local_by_key:
                local_action = local_by_key[new_key]
                
                # Allow overwriting Charon keybind
                action_names = {
                    'quick_search': 'Quick Search',
                    'run_script': 'Run Script',
                    'refresh': 'Refresh',
                    'open_folder': 'Open Folder',
                    'settings': 'Open Settings',
                    'tiny_mode': 'Tiny Mode'
                }
                
                current_name = action_names.get(local_action, local_action)
                new_name = os.path.basename(script_path)
                
                # Use unified dialog
                from .conflict_resolver import KeybindConflictDialog
                dialog = KeybindConflictDialog(self, new_key, current_name, new_name)
                
                if dialog.exec_() != QtWidgets.QDialog.Accepted:
                    return  # User cancelled
                
                # Find and clear the local keybind
                for i in range(self.local_table.rowCount()):
                    item = self.local_table.item(i, 0)
                    if item and item.data(QtCore.Qt.UserRole) == local_action:
                        # Clear the keybind
                        hotkey_item = self.local_table.item(i, 1)
                        if hotkey_item:
                            hotkey_item.setText("")
                            hotkey_item.setData(QtCore.Qt.UserRole, "")
                        
                        # Disable remove button
                        remove_widget = self.local_table.cellWidget(i, 3)
                        if remove_widget:
                            remove_button = remove_widget.findChild(QtWidgets.QPushButton)
                            if remove_button:
                                remove_button.setEnabled(False)
                        break
            else:
                # Check for conflicts with other global keybinds
                global_defs = self.keybind_manager.global_handler.get_keybind_definitions()
                
                # Find if any other global keybind uses this key
                conflicting_script = None
                for other_script_path, key_seq in global_defs.items():
                    if key_seq == new_key and other_script_path != script_path:
                        conflicting_script = other_script_path
                        break
                
                if conflicting_script:
                    # Use centralized conflict handler for global vs global
                    should_proceed = self.keybind_manager.conflict_resolver.handle_keybind_conflict(
                        self,
                        new_key,
                        script_path,  # new target
                        ConflictType.GLOBAL_VS_GLOBAL,
                        conflicting_script  # existing target
                    )
                    
                    if not should_proceed:
                        return  # User cancelled
            
            # Update the table
            key_item = self.global_table.item(row, 1)
            if key_item:
                key_item.setText(new_key)
                # Mark as changed
                key_item.setBackground(QtGui.QColor(255, 255, 200))
            
            # Save immediately
            user_settings_db.set_hotkey(new_key, script_path, self.keybind_manager.host)
            
            # If we cleared a local keybind, save that too
            if new_key in local_by_key:
                local_action = local_by_key[new_key]
                user_settings_db.set_local_keybind(local_action, "", True)
            
            # Process events to ensure all database operations complete
            QtWidgets.QApplication.processEvents()
            
            # Refresh keybinds
            self._refresh_keybinds()
    
    def _remove_single_global_keybind(self, script_path: str):
        """Remove a single global keybind."""
        script_name = os.path.basename(script_path)
        reply = QtWidgets.QMessageBox.question(
            self, "Remove Keybind",
            f"Remove keybind for {script_name}?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )
        
        if reply == QtWidgets.QMessageBox.Yes:
            # Remove from database immediately
            user_settings_db.remove_hotkey_for_script_software(
                script_path, self.keybind_manager.host
            )
            
            # Process events to ensure database operation completes
            QtWidgets.QApplication.processEvents()
            
            # Refresh keybinds - this will also update the table
            self._refresh_keybinds()
    
    
    def _reset_local_keybinds(self):
        """Reset all local keybinds to defaults."""
        # Check which global keybinds will be overwritten
        defaults = LocalKeybindHandler.DEFAULT_KEYBINDS
        global_defs = self.keybind_manager.global_handler.get_keybind_definitions()
        
        # Find conflicts
        conflicting_globals = []
        for action, default_key in defaults.items():
            for script_path, global_key in global_defs.items():
                if default_key == global_key:
                    conflicting_globals.append((script_path, global_key))
        
        # Build confirmation message
        message = "Reset all Charon keybinds to their default values?"
        if conflicting_globals:
            message += "\n\nThe following global keybinds will be removed:"
            for script_path, key in conflicting_globals:
                script_name = os.path.basename(script_path)
                message += f"\nâ€¢ {script_name} ({key})"
        
        reply = QtWidgets.QMessageBox.question(
            self, "Reset Keybinds",
            message,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )
        
        if reply == QtWidgets.QMessageBox.Yes:
            # Remove conflicting global keybinds
            for script_path, _ in conflicting_globals:
                user_settings_db.remove_hotkey_for_script_software(
                    script_path, self.keybind_manager.host
                )
            
            # Reset all local keybinds to defaults by removing custom overrides
            for action, default_key in defaults.items():
                user_settings_db.reset_local_keybind(action)
            
            # Refresh keybinds - this will update the table
            self._refresh_keybinds()
    
    # Conflict resolution removed - Charon handles conflicts automatically
    '''
    def _auto_resolve_conflict(self, conflict: Dict):
        """Auto-resolve a conflict by changing one of the keybinds."""
        # For now, just show a message
        QtWidgets.QMessageBox.information(
            self, "Auto-Resolve",
            "Auto-resolve feature coming soon!\n\n"
            "This will suggest alternative keybinds to resolve the conflict."
        )
    '''
    
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
    
    

