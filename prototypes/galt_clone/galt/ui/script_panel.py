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
from ..cache_manager import get_cache_manager
from ..metadata_manager import invalidate_metadata_path
from .. import config
import os
import shutil
import re
from datetime import datetime


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
        
        # Setup the UI
        self.layout = QtWidgets.QVBoxLayout(self)
        self.layout.setContentsMargins(4, 4, 4, 4)
        
        # Create title layout with Workflows label, New button, and collapse indicators
        title_container = QtWidgets.QWidget()
        title_container.setFixedHeight(config.UI_PANEL_HEADER_HEIGHT)
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
        
        title_label = QtWidgets.QLabel("Workflows")
        title_layout.addWidget(title_label)
        
        # Add New Workflow button - size it to fit within header
        self.new_script_button = QtWidgets.QToolButton()
        self.new_script_button.setText("+")
        self.new_script_button.setToolTip("Create New Workflow")
        self.new_script_button.setAutoRaise(True)
        
        # Make button fit within the standardized header height
        button_size = config.UI_PANEL_HEADER_HEIGHT - 8  # Leave 4px padding on each side
        self.new_script_button.setFixedSize(button_size, button_size)
        
        self.new_script_button.setStyleSheet(f"""
            QToolButton {{
                padding: 0px;
                margin: 0px;
                border: 1px solid palette(mid);
                border-radius: 2px;
                font-size: {button_size - 6}px;
            }}
            QToolButton:hover {{
                background-color: palette(midlight);
            }}
        """)
        self.new_script_button.clicked.connect(self._on_create_script_clicked)
        self.new_script_button.setVisible(True)
        title_layout.addWidget(self.new_script_button)
        
        title_layout.addStretch()  # Push indicator to the right
        
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
        
        # Create the script table model
        self.script_model = ScriptTableModel()
        
        # Create the script table view with deselection behavior
        self.script_view = ScriptTableView()
        
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
        
        # Store reference for parent folder updates
        self.parent_folder = None
        
        # Add script view directly to layout
        self.layout.addWidget(self.script_view, 1)  # Give script view stretch priority
        
        # Add metadata panel directly without extra container
        self.layout.addWidget(self.metadata_panel, 0)  # No stretch for metadata panel
        
        # Create the background loader
        self.folder_loader = workflow_model.FolderLoader(self)
        self.folder_loader.scripts_loaded.connect(self.on_scripts_loaded)
    
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
        
        # Clear delegate caches when loading new folder (to pick up icon/readme changes)
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
        from ..galt_logger import system_debug
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
        # Hide the New Script button when clearing scripts
        self.new_script_button.setVisible(False)
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
                from ..galt_logger import system_debug
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
            from ..galt_logger import system_debug
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
    
    def _on_create_script_clicked(self):
        """Handle create new workflow button click."""
        from pathlib import Path

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
            return

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
                return

        start_dir = user_folder
        workflow_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select Workflow JSON",
            start_dir,
            "Workflow Files (*.json);;All Files (*.*)"
        )
        if not workflow_path:
            return

        suggested_name = Path(workflow_path).stem or "workflow"
        name, ok = QtWidgets.QInputDialog.getText(
            self,
            "Workflow Name",
            "Workflow folder name:",
            QtWidgets.QLineEdit.Normal,
            suggested_name
        )
        if not ok:
            return

        workflow_name = name.strip()
        if not workflow_name:
            QtWidgets.QMessageBox.warning(self, "Invalid Name", "Workflow name cannot be empty.")
            return

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
            return

        try:
            os.makedirs(target_folder)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(
                self,
                "Error",
                f"Failed to create workflow folder: {exc}"
            )
            return

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
            return

        default_meta = {
            "workflow_file": "workflow.json",
            "description": "",
            "dependencies": [],
            "last_changed": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tags": []
        }

        dialog = CharonMetadataDialog(default_meta, parent=self)
        if exec_dialog(dialog) != QtWidgets.QDialog.Accepted:
            shutil.rmtree(target_folder, ignore_errors=True)
            return

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
            return

        # Invalidate caches so the new workflow appears immediately
        try:
            invalidate_metadata_path(target_folder)
            cache_manager = get_cache_manager()
            cache_manager.invalidate_folder(user_folder)
            cache_manager.invalidate_folder(target_folder)
        except Exception:
            pass

        # Optionally author a simple README if description was provided
        description = updated_meta.get("description", "").strip()
        readme_path = os.path.join(target_folder, "README.md")
        if description and not os.path.exists(readme_path):
            try:
                with open(readme_path, "w", encoding="utf-8") as handle:
                    handle.write(f"# {workflow_name}\n\n{description}\n")
            except Exception:
                pass  # Non-fatal

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
    
    def set_folders_collapsed_indicator(self, collapsed):
        """Show/hide the << indicator based on folders panel collapsed state."""
        self.folders_indicator.setVisible(collapsed)
    
    def _on_folders_indicator_clicked(self):
        """Handle click on folders collapse indicator."""
        self.open_folders_panel_requested.emit()
    
    def _on_history_indicator_clicked(self):
        """Handle click on history collapse indicator."""
        self.open_history_panel_requested.emit()
    
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
