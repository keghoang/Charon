from ..qt_compat import QtWidgets, QtCore, QtGui, Qt, exec_dialog
from .. import workflow_model
from ..script_table_model import ScriptTableModel
from .metadata_panel import MetadataPanel
from .dialogs import CharonMetadataDialog
from ..settings import user_settings_db
from .custom_table_widgets import ScriptTableView
from ..charon_metadata import write_charon_metadata
from ..workflow_runtime import load_workflow_bundle, spawn_charon_node
from ..utilities import get_current_user_slug
from ..charon_logger import system_debug
from ..cache_manager import get_cache_manager
from ..metadata_manager import invalidate_metadata_path
from .. import config, preferences
from ..comfy_validation import validate_comfy_environment
from ..paths import get_default_comfy_launch_path
from .validation_dialog import ValidationResolveDialog
from ..workflow_local_store import (
    clear_ui_validation_status,
    clear_validation_artifacts,
    load_ui_validation_status,
    save_ui_validation_status,
    write_validation_raw,
)
import os
import shutil
import re
import json
from pathlib import Path
from datetime import datetime
import time


class _ValidationWorker(QtCore.QObject):
    finished = QtCore.Signal(str, bool, dict)
    failed = QtCore.Signal(str, str)
    canceled = QtCore.Signal(str)

    def __init__(self, script_path: str, comfy_path: str, workflow_bundle: dict):
        super().__init__()
        self._script_path = script_path
        self._comfy_path = comfy_path
        self._workflow_bundle = workflow_bundle
        self._cancelled = False

    @QtCore.Slot()
    def run(self) -> None:
        try:
            if self._should_abort():
                self.canceled.emit(self._script_path)
                return
            result = validate_comfy_environment(
                self._comfy_path,
                workflow_bundle=self._workflow_bundle,
                use_cache=False,
                force=True,
            )
            if self._should_abort():
                self.canceled.emit(self._script_path)
                return
            payload = result.to_dict()
            self.finished.emit(self._script_path, bool(result.ok), payload)
        except Exception as exc:  # pragma: no cover - defensive path
            if self._should_abort():
                self.canceled.emit(self._script_path)
                return
            self.failed.emit(self._script_path, str(exc))

    def cancel(self) -> None:
        self._cancelled = True

    def _should_abort(self) -> bool:
        if self._cancelled:
            return True
        thread = QtCore.QThread.currentThread()
        if thread and thread.isInterruptionRequested():
            return True
        return False


class ScriptPanel(QtWidgets.QWidget):
    script_selected = QtCore.Signal(str)
    script_deselected = QtCore.Signal()
    script_run = QtCore.Signal(str)
    navigate_left = QtCore.Signal()
    bookmark_requested = QtCore.Signal(str)  # Signal for bookmark requests
    assign_hotkey_requested = QtCore.Signal(str)
    create_metadata_requested = QtCore.Signal(str)  # Signal for creating metadata
    edit_metadata_requested = QtCore.Signal(str)  # Signal for editing metadata
    manage_tags_requested = QtCore.Signal(str)  # Signal for managing tags
    open_folders_panel_requested = QtCore.Signal()  # Signal to open folders panel
    open_history_panel_requested = QtCore.Signal()  # Signal to open history panel

    def __init__(self, parent=None):
        super(ScriptPanel, self).__init__(parent)
        self.host = None  # We'll set this separately
        self.current_script = None
        self._loading = False
        self._selection_timer = QtCore.QTimer()
        self._selection_timer.setSingleShot(True)
        self._selection_timer.timeout.connect(self._process_selection_change)
        self._pending_selection = None
        self._is_mouse_pressed = False
        self._last_selection_path = None
        self._is_deselecting = False  # Track explicit deselection
        self._active_tags = []  # Track active tag filters
        self._all_scripts = []  # Store all scripts before filtering
        self._user_slug = get_current_user_slug()
        self._last_workflow_data = None  # Cache last loaded workflow payload
        self._validation_threads = {}
        self._validation_workers = {}
        self._validation_timer = QtCore.QTimer(self)
        self._validation_timer.setInterval(300)
        self._validation_timer.timeout.connect(self._on_validation_timer_tick)
        self._validation_cache = {}
        self._comfy_connected = False
        self._closing = False
        
        # Setup the UI
        self.layout = QtWidgets.QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(4)
        
        # Create title layout with New Workflow button and collapse indicators
        title_container = QtWidgets.QWidget()
        title_container.setFixedHeight(config.UI_PANEL_HEADER_HEIGHT)
        self.indicator_container = title_container
        title_layout = QtWidgets.QHBoxLayout(title_container)
        title_layout.setContentsMargins(0, 0, 0, 0)
        
        # Add >> indicator for collapsed folders panel
        self.folders_indicator = QtWidgets.QPushButton(">>")
        self.folders_indicator.setFlat(True)
        self.folders_indicator.setCursor(Qt.CursorShape.PointingHandCursor)
        self.folders_indicator.setStyleSheet("""
            QPushButton {
                color: palette(mid);
                background-color: transparent;
                border: none;
                padding: 0px 4px;
            }
            QPushButton:hover {
                background-color: palette(midlight);
                border-radius: 2px;
            }
        """)
        self.folders_indicator.setVisible(False)  # Hidden by default
        self.folders_indicator.clicked.connect(self._on_folders_indicator_clicked)
        title_layout.addWidget(self.folders_indicator)
        
        # Add New Workflow button - size it to fit within header
        self.new_script_button = QtWidgets.QPushButton("New Workflow +")
        self.new_script_button.setToolTip("Create New Workflow")
        self.new_script_button.setCursor(Qt.CursorShape.PointingHandCursor)
        
        # Make button fit within the standardized header height
        button_height = config.UI_PANEL_HEADER_HEIGHT - 6
        self.new_script_button.setFixedHeight(button_height)
        
        # Lighten the button so it reads as idle rather than pressed
        self.new_script_button.setStyleSheet(
            """
            QPushButton {
                padding: 0px 16px;
                margin: 0px;
                border: 1px solid palette(mid);
                border-radius: 4px;
                background-color: palette(button);
                font-weight: normal;
                text-shadow: none;
                box-shadow: none;
            }
            QPushButton:hover {
                background-color: palette(button).lighter(115);
            }
            QPushButton:pressed {
                background-color: palette(midlight);
            }
            """
        )
        self.new_script_button.clicked.connect(self._on_create_script_clicked)
        self.new_script_button.setVisible(True)
        
        title_layout.addStretch()  # Push control buttons to the right
        
        # Add << indicator for collapsed history panel
        self.history_indicator = QtWidgets.QPushButton("<<")
        self.history_indicator.setFlat(True)
        self.history_indicator.setCursor(Qt.CursorShape.PointingHandCursor)
        self.history_indicator.setStyleSheet("""
            QPushButton {
                color: palette(mid);
                background-color: transparent;
                border: none;
                padding: 0px 4px;
            }
            QPushButton:hover {
                background-color: palette(midlight);
                border-radius: 2px;
            }
        """)
        self.history_indicator.setVisible(False)  # Hidden by default
        self.history_indicator.clicked.connect(self._on_history_indicator_clicked)
        title_layout.addWidget(self.history_indicator)

        self.layout.addWidget(title_container)
        self._update_indicator_container_visibility()
        
        # Create the script table model
        self.script_model = ScriptTableModel()
        
        # Create the script table view with deselection behavior
        self.script_view = ScriptTableView()
        self.script_view.setFrameShape(QtWidgets.QFrame.NoFrame)
        
        # Connect view to model
        self.script_view.setModel(self.script_model)
        
        # Create the metadata panel - will be added to layout later
        from .metadata_panel import MetadataPanel
        self.metadata_panel = MetadataPanel(host=None)
        self.metadata_panel.setVisible(False)  # Hidden by default
        
        # Now that the model is set, we can safely connect to the selection model
        self.script_view.selectionModel().selectionChanged.connect(self.on_view_selection_changed)
        
        # Don't connect clicked signal - selection changes are handled by selectionChanged
        self.script_view.doubleClicked.connect(self.on_script_run)
        self.script_view.deselected.connect(self.on_script_deselected)
        self.script_view.navigateLeft.connect(self.navigate_left)
        self.script_view.bookmarkRequested.connect(self.bookmark_requested)
        self.script_view.assignHotkeyRequested.connect(self.assign_hotkey_requested)
        
        # Connect the script_run signal from the table view
        self.script_view.script_run.connect(self._handle_script_run_request)
        self.script_view.script_validate.connect(self._handle_script_validate_request)
        self.script_view.script_show_validation_payload.connect(self._handle_script_show_payload_request)
        self.script_view.script_show_raw_validation_payload.connect(self._handle_script_show_raw_payload_request)
        self.script_view.script_override_validation.connect(self._handle_override_validation)
        
        # Connect the new metadata signals
        self.script_view.createMetadataRequested.connect(self.create_metadata_requested)
        self.script_view.editMetadataRequested.connect(self.edit_metadata_requested)
        self.script_view.manageTagsRequested.connect(self.manage_tags_requested)
        
        # Connect mouse signals for drag tracking
        self.script_view.mousePressed.connect(self._on_mouse_pressed)
        self.script_view.mouseReleased.connect(self._on_mouse_released)
        
        # Connect empty space context menu signals
        self.script_view.createScriptInCurrentFolder.connect(self._on_create_script_clicked)
        self.script_view.openCurrentFolder.connect(self._on_open_current_folder)
        self.script_view.script_revalidate.connect(self._handle_script_revalidate_request)
        self.script_view.set_advanced_mode_provider(self._is_advanced_mode_enabled)
        self.script_view.workflowFileDropped.connect(self._on_workflow_files_dropped)
        
        # Store reference for parent folder updates
        self.parent_folder = None
        
        # Wrap script view in rounded container
        script_container = QtWidgets.QFrame()
        script_container.setObjectName("ScriptFrame")
        script_container.setStyleSheet("""
            QFrame#ScriptFrame {
                border: 1px solid #171a1f;
                border-radius: 8px;
                background: #262a2e;
            }
        """)
        script_container.setFrameShape(QtWidgets.QFrame.StyledPanel)
        script_container_layout = QtWidgets.QVBoxLayout(script_container)
        script_container_layout.setContentsMargins(0, 0, 0, 0)
        script_container_layout.setSpacing(0)
        script_container_layout.addWidget(self.script_view)
        
        # Add script view directly to layout
        self.layout.addWidget(script_container, 1)  # Give script view stretch priority
        
        # Add metadata panel directly without extra container
        self.layout.addWidget(self.metadata_panel, 0)  # No stretch for metadata panel
        
        # Create the background loader
        self.folder_loader = workflow_model.FolderLoader(self)
        self.folder_loader.scripts_loaded.connect(self.on_scripts_loaded)
    
    def _normalize_script_path(self, script_path: str) -> str:
        return os.path.normpath(script_path or "").lower()

    def _read_validation_cache(self, script_path: str):
        cached = load_ui_validation_status(script_path or "")
        if isinstance(cached, dict) and isinstance(cached.get("state"), str):
            return cached
        return None

    def _write_validation_cache(self, script_path: str, state: str, payload) -> None:
        save_ui_validation_status(script_path or "", state, payload)
        data = {"state": state, "payload": payload}
        normalized = self._normalize_script_path(script_path)
        self._validation_cache[normalized] = data

    def _clear_validation_cache(self, script_path: str) -> None:
        clear_ui_validation_status(script_path or "")
        normalized = self._normalize_script_path(script_path)
        self._validation_cache.pop(normalized, None)

    def update_comfy_connection_status(self, connected: bool) -> None:
        """Receive connection state updates from the ComfyUI footer widget."""
        self._comfy_connected = bool(connected)

    def _apply_cached_validation_states(self, scripts) -> None:
        for script in scripts:
            cached = self._read_validation_cache(script.path)
            if not cached:
                continue
            state = cached.get("state")
            payload = cached.get("payload")
            if isinstance(state, str):
                self.script_model.set_validation_state(script.path, state, payload)
                normalized = self._normalize_script_path(script.path)
                self._validation_cache[normalized] = cached

    def set_host(self, host):
        """Set the host software after initialization"""
        self.host = host
        if hasattr(self.script_model, 'set_host'):
            self.script_model.set_host(host)
        if hasattr(self.script_view, 'set_host'):
            self.script_view.set_host(host)
        # Also update the metadata panel's host
        self.metadata_panel.host = host
        # Clear cache when host changes
        if hasattr(self, '_cached_hotkeys'):
            del self._cached_hotkeys
        if hasattr(self, '_cached_bookmarks'):
            del self._cached_bookmarks
    
    def _refresh_user_data_cache(self):
        """Refresh cached user data (hotkeys and bookmarks) from database"""
        # Cache these expensive database operations
        self._cached_hotkeys = user_settings_db.get_all_hotkeys(self.host or "None")
        self._cached_bookmarks = set(user_settings_db.get_bookmarks())
    
    def invalidate_user_data_cache(self):
        """Invalidate the cached user data (call when bookmarks/hotkeys change)"""
        if hasattr(self, '_cached_hotkeys'):
            del self._cached_hotkeys
        if hasattr(self, '_cached_bookmarks'):
            del self._cached_bookmarks

    def load_scripts_for_folder(self, folder_path):
        """Load scripts from a folder using background thread"""
        if self._loading:
            self.folder_loader.stop_loading()
        
        # Check if we're in navigation context (from parent main window)
        main_window = self.window()
        is_navigating = hasattr(main_window, '_is_navigating') and main_window._is_navigating
        
        # Clear current selection when loading new folder (unless navigating)
        if not is_navigating and self.current_script:
            self.on_script_deselected()
        
        # Store the parent folder for create script functionality
        self.parent_folder = folder_path

        # Guard against browsing outside the Charon workflow repository
        if folder_path:
            try:
                root = os.path.abspath(config.WORKFLOW_REPOSITORY_ROOT)
                target = os.path.abspath(folder_path)
                if not target.lower().startswith(root.lower()):
                    QtWidgets.QMessageBox.warning(
                        self,
                        "Unsupported Location",
                        "Only folders inside the Charon workflow repository can be browsed."
                    )
                    self.parent_folder = root
                    folder_path = root
            except Exception:
                pass
        
        # Always allow creating workflows; they are saved into the user's folder.
        self.new_script_button.setVisible(True)
        
        # Clear delegate caches when loading new folder (to pick up icon changes)
        self.script_view.clear_delegate_caches()
        
        # Don't refresh metadata during normal loading - this was causing slowdown
        # Metadata will be loaded from cache as needed
        
        self._loading = True
        # Show loading state
        self.script_view.setEnabled(False)
        
        # Start background loading
        self.folder_loader.load_folder(folder_path, self.host or "None")
    
    def on_scripts_loaded(self, scripts):
        """Handle when scripts are loaded into the model"""
        # Cache hotkeys and bookmarks to avoid repeated DB queries
        if not hasattr(self, '_cached_hotkeys') or not hasattr(self, '_cached_bookmarks'):
            self._refresh_user_data_cache()
        
        # Use cached data
        all_hotkeys = self._cached_hotkeys
        bookmarked_scripts = self._cached_bookmarks
        
        # Filter hotkeys to only include those within the current base path
        if hasattr(self, 'parent_folder') and self.parent_folder:
            # Get the base path from parent folder (go up one level from folder path)
            base_path = os.path.dirname(self.parent_folder)
            # Normalize base path for comparison
            normalized_base = os.path.normpath(base_path).lower()
            # Filter hotkeys to only include scripts in current base
            filtered_hotkeys = {}
            for hotkey, script_path in all_hotkeys.items():
                # Normalize the script path for comparison
                normalized_script = os.path.normpath(script_path).lower()
                if normalized_script.startswith(normalized_base):
                    filtered_hotkeys[hotkey] = script_path
        else:
            filtered_hotkeys = all_hotkeys
            
        # Reverse the mapping to get script_path -> hotkey
        # Also normalize the paths in the mapping for consistent lookups
        hotkey_by_script = {}
        for hotkey, script_path in filtered_hotkeys.items():
            # Store both original and normalized paths for compatibility
            hotkey_by_script[script_path] = hotkey
            normalized = os.path.normpath(script_path)
            if normalized != script_path:
                hotkey_by_script[normalized] = hotkey
        
        # Debug logging
        from ..charon_logger import system_debug
        system_debug(f"Script panel: Processing {len(scripts)} scripts")
        system_debug(f"Script panel: Found {len(hotkey_by_script)} hotkeys after filtering")
        
        for script in scripts:
            # Normalize script path for comparisons
            normalized_script_path = os.path.normpath(script.path)
            script.is_bookmarked = normalized_script_path in bookmarked_scripts
            
            # Still set the hotkey for display purposes (but not for sorting)
            if normalized_script_path in hotkey_by_script:
                script.hotkey = hotkey_by_script[normalized_script_path]
                system_debug(f"Script panel: Set hotkey '{script.hotkey}' for script: {script.path}")
            elif script.path in hotkey_by_script:
                # Try original path as fallback
                script.hotkey = hotkey_by_script[script.path]
                system_debug(f"Script panel: Set hotkey '{script.hotkey}' for script: {script.path} (original path)")
            else:
                # Debug why hotkey not found
                if len(all_hotkeys) > 0:
                    system_debug(f"Script panel: No hotkey found for script: {script.path}")
                    system_debug(f"Script panel: Normalized path: {normalized_script_path}")
                    system_debug(f"Script panel: Available paths in hotkeys: {list(hotkey_by_script.keys())[:3]}...")

        # Store all scripts before filtering
        self._all_scripts = scripts
        
        # Apply tag filter if any
        self._apply_tag_filter()

        # Apply cached validation states after model refresh
        self._apply_cached_validation_states(self._all_scripts)
        
        # Force a visual refresh to ensure colors are applied
        self.script_view.viewport().update()
        self._loading = False
        self.script_view.setEnabled(True)

    def on_view_selection_changed(self, selected, deselected):
        """Handle selection changes and force a repaint of items."""
        # If we're in the middle of an explicit deselection, ignore this signal
        if self._is_deselecting:
            return
        
        # Check if we're in navigation context (from parent main window)
        main_window = self.window()
        is_navigating = hasattr(main_window, '_is_navigating') and main_window._is_navigating
            
        for index in deselected.indexes():
            self.script_view.update(index)
        for index in selected.indexes():
            self.script_view.update(index)
            
        # Get current selection
        current = self.script_view.selectionModel().currentIndex()
        
        if current.isValid() and current.column() == 0:  # Only process name column
            # If mouse is pressed (dragging), use timer to reduce updates
            if self._is_mouse_pressed:
                self._pending_selection = current
                self._selection_timer.stop()
                self._selection_timer.start(config.UI_SCRIPT_SELECTION_DELAY_MS)
            else:
                # For keyboard navigation, update immediately
                self.on_script_selected(current)
        elif not selected.indexes() and not is_navigating:
            # No selection - clear immediately (unless we're navigating)
            self._pending_selection = None
            self._selection_timer.stop()
            self.on_script_deselected()
    
    def _process_selection_change(self):
        """Process the pending selection change after delay."""
        if self._pending_selection and self._pending_selection.isValid():
            self.on_script_selected(self._pending_selection)
            self._pending_selection = None
            
    def update_scripts(self, scripts):
        """Legacy method - now redirects to threaded loading"""
        # For backwards compatibility, we'll assume this is called with a folder path
        # In practice, this method signature should be updated to take a folder path
        # But for now, we'll work with the existing pattern
        
        # Get all hotkey assignments
        all_hotkeys = user_settings_db.get_all_hotkeys(self.host or "None")
        
        # Filter hotkeys to only include those within the current base path
        if hasattr(self, 'parent_folder') and self.parent_folder:
            # Get the base path from parent folder (go up one level from folder path)
            base_path = os.path.dirname(self.parent_folder)
            # Normalize base path for comparison
            normalized_base = os.path.normpath(base_path).lower()
            # Filter hotkeys to only include scripts in current base
            filtered_hotkeys = {}
            for hotkey, script_path in all_hotkeys.items():
                # Normalize the script path for comparison
                normalized_script = os.path.normpath(script_path).lower()
                if normalized_script.startswith(normalized_base):
                    filtered_hotkeys[hotkey] = script_path
        else:
            filtered_hotkeys = all_hotkeys
            
        # Reverse the mapping to get script_path -> hotkey
        # Also normalize the paths in the mapping for consistent lookups
        hotkey_by_script = {}
        for hotkey, script_path in filtered_hotkeys.items():
            # Store both original and normalized paths for compatibility
            hotkey_by_script[script_path] = hotkey
            normalized = os.path.normpath(script_path)
            if normalized != script_path:
                hotkey_by_script[normalized] = hotkey
        
        # Get all bookmarked scripts for current user
        bookmarked_scripts = set(user_settings_db.get_bookmarks())
        
        # Set flags on each script
        for script in scripts:
            # Normalize script path for bookmark comparison
            normalized_script_path = os.path.normpath(script.path)
            script.is_bookmarked = normalized_script_path in bookmarked_scripts
            
            # Still set the hotkey for display purposes (but not for sorting)
            if script.path in hotkey_by_script:
                script.hotkey = hotkey_by_script[script.path]
        
        # Store all scripts before filtering
        self._all_scripts = scripts
        
        # Apply tag filter if any
        self._apply_tag_filter()

    def clear_scripts(self):
        if self._loading:
            self.folder_loader.stop_loading()
            self._loading = False
        self._all_scripts = []  # Clear stored scripts
        self.script_model.updateItems([], sort=False)  # No need to sort empty list
        # Clear the view selection
        self.script_view.clearSelection()
        self.script_view.setCurrentIndex(QtCore.QModelIndex())
        # Also hide metadata panel when clearing scripts
        self.metadata_panel.setVisible(False)
        self.metadata_panel.show_default_message()
        # Always keep the New Workflow button available
        self.new_script_button.setVisible(True)
        # Clear parent folder reference
        self.parent_folder = None



    def _get_corrected_script_path(self, script):
        """Get the corrected script path based on current parent folder."""
        if hasattr(self, 'parent_folder') and self.parent_folder:
            # Extract just the script name (last part of path)
            script_name = os.path.basename(script.path)
            
            # Reconstruct using current parent folder
            corrected_path = os.path.join(self.parent_folder, script_name)
            
            # Log if path changed
            if corrected_path != script.path:
                from ..charon_logger import system_debug
                system_debug(f"Script panel corrected path: {script.path} -> {corrected_path}")
            
            return corrected_path
        else:
            # Fallback to original path
            return script.path

    def on_script_selected(self, index):
        if not index.isValid():
            return
        
        row = index.row()
        
        script = self.script_model.get_script_at_row(row)
        if script:
            # Get the corrected path based on current parent folder
            corrected_path = self._get_corrected_script_path(script)
            
            # Only emit if this is actually a different script
            if not self.current_script or script.path != self.current_script.path:
                self.current_script = script
                # Update metadata panel with corrected path
                self.metadata_panel.update_metadata(corrected_path)
                self.metadata_panel.setVisible(True)
                self.script_selected.emit(script.path)  # Keep original for compatibility
            else:
                # Same script selected - ensure metadata panel is visible
                self.metadata_panel.setVisible(True)
            
    def on_script_deselected(self):
        """Handle when the user clicks empty space to deselect."""
        # Set the flag to prevent selection changed from interfering
        self._is_deselecting = True
        
        # Clear any pending selections
        self._pending_selection = None
        self._selection_timer.stop()
        
        self.current_script = None
        # Hide metadata panel when no script selected
        self.metadata_panel.setVisible(False)
        self.metadata_panel.show_default_message()
        self.script_deselected.emit()
        
        # Reset the flag after a short delay to allow all signals to settle
        QtCore.QTimer.singleShot(50, lambda: setattr(self, '_is_deselecting', False))

    def get_selected_script(self):
        current = self.script_view.currentIndex()
        if current.isValid():
            row = current.row()
            return self.script_model.get_script_at_row(row)
        return None

    def _handle_script_run_request(self, script_path: str):
        """Load workflow data and spawn a CharonOp node in Nuke."""
        if not script_path:
            return

        try:
            self._last_workflow_data = load_workflow_bundle(script_path)
        except FileNotFoundError as exc:
            QtWidgets.QMessageBox.critical(self, "Workflow Missing", str(exc))
            return
        except ValueError as exc:
            QtWidgets.QMessageBox.critical(self, "Workflow Invalid", str(exc))
            return
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Workflow Error", str(exc))
            return

        try:
            import nuke  # type: ignore
        except ImportError:
            QtWidgets.QMessageBox.warning(
                self,
                "Nuke Required",
                "Spawning a CharonOp requires Nuke to be running."
            )
            return

        try:
            spawn_charon_node(self._last_workflow_data, nuke_module=nuke)
        except RuntimeError as exc:
            QtWidgets.QMessageBox.warning(self, "Spawn Failed", str(exc))
            return
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "CharonOp Error", str(exc))
            return

        if hasattr(self, 'flash_script_execution'):
            self.flash_script_execution(script_path)

    def _handle_script_validate_request(self, script_path: str):
        """Trigger or inspect validation for the selected workflow."""
        if not script_path:
            return

        state = self.script_model.get_validation_state(script_path)
        if state == "validating":
            return

        if state == "needs_resolve":
            revalidate = self._show_validation_payload(script_path)
            if revalidate:
                bundle = self._load_workflow_bundle_safe(script_path)
                if bundle:
                    self._start_validation(script_path, bundle)
            return
        if state == "validated":
            return

        bundle = self._load_workflow_bundle_safe(script_path)
        if not bundle:
            return

        self._start_validation(script_path, bundle)

    def _handle_override_validation(self, script_path: str):
        """Force validation state to passed for a workflow."""
        if not script_path:
            return
        payload = {
            "state": "validated",
            "message": "Validation overridden",
            "timestamp": time.time(),
            "overridden": True,
            "issues": [],
            "comfy_path": self._resolve_comfy_path(),
        }
        try:
            self.script_model.set_validation_state(script_path, "validated", payload=payload)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Override Failed", str(exc))
            return
        try:
            save_ui_validation_status(script_path, "validated", payload)
        except Exception:
            pass
        system_debug(f"[Validation] Override set to Passed for {script_path}")

    def _load_workflow_bundle_safe(self, script_path: str):
        try:
            return load_workflow_bundle(script_path)
        except FileNotFoundError as exc:
            QtWidgets.QMessageBox.critical(self, "Workflow Missing", str(exc))
        except ValueError as exc:
            QtWidgets.QMessageBox.critical(self, "Workflow Invalid", str(exc))
        except Exception as exc:  # pragma: no cover - defensive path
            QtWidgets.QMessageBox.critical(self, "Workflow Error", str(exc))
        return None

    def _resolve_comfy_path(self) -> str:
        comfy_path = preferences.get_preference("comfyui_launch_path", "")
        comfy_path = (comfy_path or "").strip()
        if not comfy_path:
            comfy_path = get_default_comfy_launch_path()
        return (comfy_path or "").strip()

    def _is_advanced_mode_enabled(self) -> bool:
        """Check whether advanced user mode is enabled for the current host."""
        host = getattr(self, "host", None)
        try:
            value = user_settings_db.get_app_setting_for_host(
                "advanced_user_mode", host, default="off"
            )
        except Exception:
            return False
        normalized = str(value or "off").strip().lower()
        return normalized in {"on", "true", "1", "yes"}

    def _start_validation(self, script_path: str, workflow_bundle: dict) -> None:
        comfy_path = self._resolve_comfy_path()
        if not comfy_path:
            QtWidgets.QMessageBox.warning(
                self,
                "ComfyUI Path Required",
                "Set the ComfyUI launch path in preferences before validating.",
            )
            return
        if not os.path.exists(comfy_path):
            QtWidgets.QMessageBox.warning(
                self,
                "ComfyUI Path Missing",
                f"The configured ComfyUI launch path does not exist:\n{comfy_path}",
            )
            return

        if not self._comfy_connected:
            QtWidgets.QMessageBox.information(
                self,
                "ComfyUI Offline",
                (
                    "ComfyUI is not currently running. Launch it from the footer and wait "
                    "for the status to turn green before validating."
                ),
            )
            return

        # Avoid launching duplicate validators for the same workflow
        if self.script_model.get_validation_state(script_path) == "validating":
            return

        self.script_model.set_validation_state(script_path, "validating")
        if not self._validation_timer.isActive():
            self._validation_timer.start()

        worker = _ValidationWorker(script_path, comfy_path, workflow_bundle)
        thread = QtCore.QThread()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_validation_finished)
        worker.failed.connect(self._on_validation_failed)
        worker.canceled.connect(self._on_validation_canceled)
        worker.finished.connect(lambda *_: thread.quit())
        worker.failed.connect(lambda *_: thread.quit())
        worker.canceled.connect(lambda *_: thread.quit())
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._validation_workers[script_path] = worker
        self._validation_threads[script_path] = thread
        thread.start()

    @QtCore.Slot(str, bool, dict)
    def _on_validation_finished(self, script_path: str, ok: bool, payload: dict) -> None:
        self._cleanup_validation_worker(script_path)
        if self._closing:
            return
        remote_folder = ""
        if isinstance(payload, dict):
            workflow_info = payload.get("workflow") or {}
            if isinstance(workflow_info, dict):
                remote_folder = workflow_info.get("folder") or ""
        if remote_folder:
            write_validation_raw(remote_folder, payload)
        state = "validated" if ok else "needs_resolve"
        self.script_model.set_validation_state(script_path, state, payload)
        self._write_validation_cache(script_path, state, payload)
        if not self.script_model.has_active_validation():
            self._validation_timer.stop()

    @QtCore.Slot(str, str)
    def _on_validation_failed(self, script_path: str, error_message: str) -> None:
        self._cleanup_validation_worker(script_path)
        if self._closing:
            return
        self.script_model.set_validation_state(script_path, "idle")
        self._clear_validation_cache(script_path)
        if not self.script_model.has_active_validation():
            self._validation_timer.stop()
        QtWidgets.QMessageBox.critical(self, "Validation Failed", error_message)

    @QtCore.Slot(str)
    def _on_validation_canceled(self, script_path: str) -> None:
        self._cleanup_validation_worker(script_path)
        if self._closing:
            return
        self.script_model.set_validation_state(script_path, "idle")
        if not self.script_model.has_active_validation():
            self._validation_timer.stop()

    def _cleanup_validation_worker(self, script_path: str) -> None:
        thread = self._validation_threads.pop(script_path, None)
        self._validation_workers.pop(script_path, None)
        if thread is not None and thread.isRunning():
            thread.quit()
            thread.wait()

    def _stop_all_validations(self) -> None:
        for script_path in list(self._validation_workers.keys()):
            worker = self._validation_workers.get(script_path)
            if worker is not None:
                try:
                    worker.cancel()
                except Exception:
                    pass
        for script_path in list(self._validation_threads.keys()):
            thread = self._validation_threads.pop(script_path, None)
            if thread is None:
                continue
            if thread.isRunning():
                thread.requestInterruption()
                thread.quit()
                thread.wait()
        self._validation_workers.clear()
        self._validation_threads.clear()
        self._validation_timer.stop()

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        self._closing = False
        super().showEvent(event)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self._closing = True
        self._stop_all_validations()
        super().closeEvent(event)

    def _on_validation_timer_tick(self) -> None:
        updated = self.script_model.advance_validation_animation()
        if not updated and not self.script_model.has_active_validation():
            self._validation_timer.stop()

    def _show_validation_payload(self, script_path: str) -> bool:
        payload = self.script_model.get_validation_payload(script_path)
        if not isinstance(payload, dict):
            cached = self._read_validation_cache(script_path)
            if isinstance(cached, dict):
                payload = cached.get("payload")
                if isinstance(payload, dict):
                    state = cached.get("state") or self.script_model.get_validation_state(script_path)
                    self.script_model.set_validation_state(script_path, state or "idle", payload)
            if not isinstance(payload, dict):
                QtWidgets.QMessageBox.information(
                    self,
                    "Validation",
                    "No structured validation details are available yet for this workflow.",
                )
                return False

        workflow_name = os.path.basename(script_path.rstrip(os.sep)) or "Workflow"
        comfy_path = self._resolve_comfy_path()
        bundle = self._load_workflow_bundle_safe(script_path)
        dialog = ValidationResolveDialog(
            payload,
            workflow_name=workflow_name,
            comfy_path=comfy_path,
            workflow_bundle=bundle,
            parent=self,
        )
        main_window = self.window()
        connection_widget = getattr(main_window, "comfy_connection_widget", None)
        if connection_widget is not None:
            if hasattr(dialog, "attach_connection_widget"):
                dialog.attach_connection_widget(connection_widget)
            dialog.comfy_restart_requested.connect(connection_widget.handle_external_restart_request)
        exec_dialog(dialog)

        new_state = "needs_resolve"
        if isinstance(payload, dict):
            issues = payload.get("issues") or []
            all_ok = True
            for issue in issues:
                if not isinstance(issue, dict):
                    continue
                if issue.get("key") == "models":
                    data = issue.get("data") or {}
                    missing = data.get("missing") or []
                    if missing:
                        issue["ok"] = False
                    else:
                        issue["ok"] = True
                if not issue.get("ok", False):
                    all_ok = False
            new_state = "validated" if all_ok else "needs_resolve"
        self.script_model.set_validation_state(script_path, new_state, payload)
        self._write_validation_cache(script_path, new_state, payload)

        return dialog.result() == 1

    def _show_raw_validation_payload(self, script_path: str) -> bool:
        """Display the raw validation payload for advanced users."""
        payload = self.script_model.get_validation_payload(script_path)
        if payload is None:
            cached = self._read_validation_cache(script_path)
            if isinstance(cached, dict):
                payload = cached.get("payload")
                if payload is not None:
                    state = cached.get("state") or self.script_model.get_validation_state(script_path)
                    self.script_model.set_validation_state(script_path, state or "idle", payload)
        if payload is None:
            QtWidgets.QMessageBox.information(
                self,
                "Validation",
                "No validation details are available yet for this workflow.",
            )
            return False

        if isinstance(payload, str):
            payload_text = payload
        else:
            try:
                payload_text = json.dumps(payload, indent=2, sort_keys=True)
            except TypeError:
                payload_text = str(payload)

        dialog = QtWidgets.QDialog(self)
        workflow_name = os.path.basename(script_path.rstrip(os.sep)) or "Workflow"
        dialog.setWindowTitle(f"Validation Payload - {workflow_name}")
        dialog_layout = QtWidgets.QVBoxLayout(dialog)

        text_widget = QtWidgets.QPlainTextEdit(dialog)
        text_widget.setReadOnly(True)
        text_widget.setPlainText(payload_text)
        dialog_layout.addWidget(text_widget)

        button_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close, parent=dialog)
        revalidate_button = button_box.addButton("Revalidate", QtWidgets.QDialogButtonBox.ActionRole)
        revalidate_button.clicked.connect(lambda: dialog.done(1))
        button_box.rejected.connect(dialog.reject)
        dialog_layout.addWidget(button_box)

        dialog.resize(720, 540)
        exec_dialog(dialog)
        return dialog.result() == 1

    def _handle_script_revalidate_request(self, script_path: str) -> None:
        """Force a revalidation run for the given workflow."""
        if not script_path:
            return
        if self.script_model.get_validation_state(script_path) == "validating":
            return
        bundle = self._load_workflow_bundle_safe(script_path)
        if not bundle:
            return
        remote_folder = ''
        if isinstance(bundle, dict):
            remote_folder = bundle.get('folder') or ''
        if remote_folder:
            try:
                clear_validation_artifacts(remote_folder)
            except Exception:
                pass
        self._clear_validation_cache(script_path)
        if isinstance(bundle, dict):
            bundle.pop('local_state', None)
            bundle.pop('validated', None)
        bundle = self._load_workflow_bundle_safe(script_path)
        if not bundle:
            return
        if isinstance(bundle, dict):
            bundle.pop('local_state', None)
            bundle.pop('validated', None)
        self._start_validation(script_path, bundle)

    def _handle_script_show_payload_request(self, script_path: str) -> None:
        """Show the validation result dialog with options to inspect raw data."""
        if not script_path:
            return
        if self._show_validation_payload(script_path):
            self._handle_script_revalidate_request(script_path)

    def _handle_script_show_raw_payload_request(self, script_path: str) -> None:
        """Show the raw validation payload."""
        if not script_path:
            return
        if self._show_raw_validation_payload(script_path):
            self._handle_script_revalidate_request(script_path)

    def on_script_run(self, index):
        if not index.isValid():
            return
        
        # Check if script can run using centralized logic
        can_run = self.script_model.data(index, ScriptTableModel.CanRunRole)
        if not can_run:
            return  # Don't run scripts that can't run
        
        row = index.row()
        script = self.script_model.get_script_at_row(row)
        if script:
            self._handle_script_run_request(script.path)

    def focus_first_script(self):
        """Focus the first script in the list. Returns True if successful"""
        if self.script_model.rowCount() == 0:
            return False
        
        # Work with model directly
        index = self.script_model.index(0, 0)
        self.script_view.setCurrentIndex(index)
        self.script_view.setFocus()
        
        # Get the actual script
        if index.isValid():
            first_script = self.script_model.get_script_at_row(index.row())
            if first_script:
                self.current_script = first_script
                # Get the corrected path based on current parent folder
                corrected_path = self._get_corrected_script_path(first_script)
                # Update metadata panel when focusing first script
                self.metadata_panel.update_metadata(corrected_path)
                self.metadata_panel.setVisible(True)
                self.script_selected.emit(first_script.path)
        
        return True

    def select_script(self, script_path):
        """Select the script that matches the given path. Returns True if found."""
        # Normalize the path for comparison
        normalized_target = os.path.normpath(script_path)
        
        # If the path is a directory (folder path from quick search), we need to match by folder name
        if os.path.isdir(script_path):
            # Extract the script name from the path
            script_name = os.path.basename(script_path)
            from ..charon_logger import system_debug
            system_debug(f"select_script: Looking for script named '{script_name}'")
            
            # Search through model rows by name
            for row in range(self.script_model.rowCount()):
                index = self.script_model.index(row, 0)
                if index.isValid():
                    script = self.script_model.get_script_at_row(index.row())
                    if script:
                        system_debug(f"  Checking script: {script.name} at {script.path}")
                        if script.name == script_name:
                            system_debug(f"  Found match!")
                            self.script_view.setCurrentIndex(index)
                            self.script_view.setFocus()
                            self.script_selected.emit(script.path)
                            return True
            
            system_debug(f"  No match found for '{script_name}', selecting first")
            return self.focus_first_script()
        
        # Search through model rows by full path
        for row in range(self.script_model.rowCount()):
            index = self.script_model.index(row, 0)
            if index.isValid():
                script = self.script_model.get_script_at_row(index.row())
                if script:
                    normalized_script = os.path.normpath(script.path)
                    if normalized_script == normalized_target:
                        self.script_view.setCurrentIndex(index)
                        self.script_view.setFocus()
                        self.script_selected.emit(script_path)
                        return True
        return False
        
    def _on_mouse_pressed(self):
        """Handle mouse press - start immediate selection updates"""
        self._is_mouse_pressed = True
        self._selection_timer.stop()  # Cancel any pending timer
        self._pending_selection = None  # Clear any stale pending selection
        
    def _on_mouse_released(self):
        """Handle mouse release - return to normal selection behavior"""
        self._is_mouse_pressed = False
        self._selection_timer.stop()  # Stop any pending timer
        
        # Get the CURRENT selection, not the pending one
        current = self.script_view.selectionModel().currentIndex()
        if current.isValid() and current.column() == 0:
            # Process the current selection immediately
            self.on_script_selected(current)
        
        # Clear pending selection
        self._pending_selection = None
    
    def set_tag_filter(self, active_tags):
        """Set tag filter and update the display."""
        self._active_tags = active_tags
        self._apply_tag_filter()
    
    def _apply_tag_filter(self):
        """Apply tag filtering to the current scripts."""
        if not self._active_tags:
            # No tags selected, show all scripts
            filtered_scripts = self._all_scripts
        else:
            # Filter scripts that have ANY of the active tags (OR logic)
            filtered_scripts = []
            for script in self._all_scripts:
                if hasattr(script, 'metadata') and script.metadata:
                    script_tags = script.metadata.get('tags', [])
                    # Check if script has any of the active tags
                    if any(tag in script_tags for tag in self._active_tags):
                        filtered_scripts.append(script)
        
        # Update the model with filtered scripts (sorting is done inside updateItems)
        self.script_model.updateItems(filtered_scripts)
    
    def _get_user_folder_context(self):
        """Resolve the active base path and user workflow folder."""
        main_window = self.window() if hasattr(self, "window") else None
        base_path = getattr(main_window, "current_base", None) if main_window else None
        if not base_path:
            base_path = config.WORKFLOW_REPOSITORY_ROOT

        if not base_path or not os.path.isdir(base_path):
            QtWidgets.QMessageBox.critical(
                self,
                "Workflow Repository Unavailable",
                f"The workflow repository is not accessible:\n{base_path}"
            )
            return None, None

        user_folder = os.path.join(base_path, self._user_slug)
        if not os.path.isdir(user_folder):
            try:
                os.makedirs(user_folder, exist_ok=True)
            except Exception as exc:
                QtWidgets.QMessageBox.critical(
                    self,
                    "Create Failed",
                    f"Could not prepare your workflow folder:\n{exc}"
                )
                return None, None

        return main_window, user_folder

    def _import_workflow_json(self, workflow_path: str, main_window, user_folder):
        """Copy a workflow JSON into the repository and collect metadata."""
        if not workflow_path or not os.path.isfile(workflow_path):
            QtWidgets.QMessageBox.warning(
                self,
                "Invalid Workflow",
                "The selected workflow file could not be found."
            )
            return False

        suggested_name = Path(workflow_path).stem or "workflow"
        name, ok = QtWidgets.QInputDialog.getText(
            self,
            "Workflow Name",
            "Workflow folder name:",
            QtWidgets.QLineEdit.Normal,
            suggested_name
        )
        if not ok:
            return None

        workflow_name = name.strip()
        if not workflow_name:
            QtWidgets.QMessageBox.warning(self, "Invalid Name", "Workflow name cannot be empty.")
            return False

        safe_name = re.sub(r'[\\\\/:*?"<>|]', "_", workflow_name)
        if not safe_name:
            safe_name = "workflow"
        target_folder = os.path.join(user_folder, safe_name)
        if os.path.exists(target_folder):
            QtWidgets.QMessageBox.warning(
                self,
                "Folder Exists",
                f"A workflow named '{workflow_name}' already exists."
            )
            return False

        try:
            os.makedirs(target_folder)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(
                self,
                "Error",
                f"Failed to create workflow folder: {exc}"
            )
            return False

        dest_json = os.path.join(target_folder, "workflow.json")
        try:
            shutil.copyfile(workflow_path, dest_json)
        except Exception as exc:
            shutil.rmtree(target_folder, ignore_errors=True)
            QtWidgets.QMessageBox.critical(
                self,
                "Error",
                f"Failed to copy workflow JSON: {exc}"
            )
            return False

        default_meta = {
            "workflow_file": "workflow.json",
            "description": "",
            "dependencies": [],
            "last_changed": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tags": [],
            "parameters": [],
        }

        dialog = CharonMetadataDialog(default_meta, workflow_path=dest_json, parent=self)
        if exec_dialog(dialog) != QtWidgets.QDialog.Accepted:
            shutil.rmtree(target_folder, ignore_errors=True)
            return None

        updated_meta = default_meta.copy()
        updated_meta.update(dialog.get_metadata())
        updated_meta["last_changed"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

        try:
            if write_charon_metadata(target_folder, updated_meta) is None:
                raise RuntimeError("Metadata writer returned False")
        except Exception as exc:
            shutil.rmtree(target_folder, ignore_errors=True)
            QtWidgets.QMessageBox.critical(
                self,
                "Error",
                f"Failed to save workflow metadata: {exc}"
            )
            return False

        # Invalidate caches so the new workflow appears immediately
        try:
            invalidate_metadata_path(target_folder)
            cache_manager = get_cache_manager()
            cache_manager.invalidate_folder(user_folder)
            cache_manager.invalidate_folder(target_folder)
        except Exception:
            pass

        if hasattr(self.metadata_panel, 'script_created'):
            self.metadata_panel.script_created.emit(target_folder)

        if main_window and hasattr(main_window, "refresh_folder_panel"):
            main_window.refresh_folder_panel()
            QtCore.QTimer.singleShot(
                0, lambda: main_window.folder_panel.select_folder(self._user_slug)
            )
        elif main_window and hasattr(main_window, "folder_panel"):
            main_window.folder_panel.select_folder(self._user_slug)

        self.load_scripts_for_folder(user_folder)
        return True

    def _on_workflow_files_dropped(self, file_paths):
        """Handle drag-and-drop import of workflow JSON files."""
        main_window, user_folder = self._get_user_folder_context()
        if not user_folder:
            return

        valid_paths = []
        for path in file_paths or []:
            if isinstance(path, str) and path.lower().endswith(".json"):
                valid_paths.append(path)

        if not valid_paths:
            QtWidgets.QMessageBox.information(
                self,
                "Unsupported Drop",
                "Only .json workflow files can be dropped onto the workflow table."
            )
            return

        for workflow_path in valid_paths:
            result = self._import_workflow_json(workflow_path, main_window, user_folder)
            if result is None:
                break
    
    def _on_create_script_clicked(self):
        """Handle create new workflow button click."""
        main_window, user_folder = self._get_user_folder_context()
        if not user_folder:
            return

        workflow_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select Workflow JSON",
            user_folder,
            "Workflow Files (*.json);;All Files (*.*)"
        )
        if not workflow_path:
            return

        self._import_workflow_json(workflow_path, main_window, user_folder)

    def trigger_new_workflow(self):
        """Public helper to start new workflow creation from external buttons."""
        self._on_create_script_clicked()
    
    def _on_open_current_folder(self):
        """Handle open folder request from context menu."""
        if self.parent_folder and os.path.exists(self.parent_folder):
            import subprocess
            import platform
            
            system = platform.system()
            if system == "Windows":
                subprocess.Popen(f'explorer "{self.parent_folder}"')
            elif system == "Darwin":  # macOS
                subprocess.Popen(["open", self.parent_folder])
            elif system == "Linux":
                subprocess.Popen(["xdg-open", self.parent_folder])
    
    def set_history_collapsed_indicator(self, collapsed):
        """Show/hide the >> indicator based on history panel collapsed state."""
        self.history_indicator.setVisible(collapsed)
        self._update_indicator_container_visibility()
    
    def set_folders_collapsed_indicator(self, collapsed):
        """Show/hide the << indicator based on folders panel collapsed state."""
        self.folders_indicator.setVisible(collapsed)
        self._update_indicator_container_visibility()

    def _update_indicator_container_visibility(self):
        """Only show the indicator row when at least one toggle is visible."""
        container = getattr(self, "indicator_container", None)
        if container is None:
            return
        show = self.history_indicator.isVisible() or self.folders_indicator.isVisible()
        container.setVisible(show)
    
    def _on_folders_indicator_clicked(self):
        """Handle click on folders collapse indicator."""
        self.open_folders_panel_requested.emit()
    
    def _on_history_indicator_clicked(self):
        """Handle click on history collapse indicator."""
        self.open_history_panel_requested.emit()

    def _on_refresh_clicked(self):
        main_window, _ = self._get_user_folder_context()
        if main_window and hasattr(main_window, "on_refresh_clicked"):
            try:
                main_window.on_refresh_clicked()
            except Exception:
                pass

    def _on_settings_clicked(self):
        main_window, _ = self._get_user_folder_context()
        if main_window and hasattr(main_window, "open_settings"):
            try:
                main_window.open_settings()
            except Exception:
                pass
    
    def flash_script_execution(self, script_path):
        """Flash the script row to indicate execution."""
        # Import the centralized flash function
        from .flash_utils import flash_table_row
        
        # Find the script in the model
        for row in range(self.script_model.rowCount()):
            script = self.script_model.get_script_at_row(row)
            if script and script.path == script_path:
                flash_table_row(self.script_view, row)
                break


