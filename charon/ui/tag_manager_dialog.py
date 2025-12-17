"""Tag Manager Dialog for managing script tags."""

from ..qt_compat import QtWidgets, QtCore, QtGui, WindowContextHelpButtonHint, WindowCloseButtonHint
from typing import List, Set
import os

from ..metadata_manager import get_charon_config, update_charon_config, invalidate_metadata_path, get_folder_tags
from ..charon_logger import system_info, system_error, system_debug


class TagManagerDialog(QtWidgets.QDialog):
    """Dialog for managing tags on a script and across the folder."""
    
    tags_changed = QtCore.Signal()  # Emitted when tags are modified
    detailed_tags_changed = QtCore.Signal(list, list, list)  # added_tags, removed_tags, renamed_tags (old,new)
    
    def __init__(self, script_path: str, folder_path: str, parent=None):
        super().__init__(parent)
        self.script_path = script_path
        self.folder_path = folder_path
        self._tags_modified = False  # Track if any tags were modified
        
        # Debug: Log the paths we're working with
        system_debug(f"TagManagerDialog initialized with:")
        system_debug(f"  script_path: {script_path}")
        system_debug(f"  folder_path: {folder_path}")
        
        # Load metadata; initialize a Charon file if none exists
        self.script_metadata = get_charon_config(script_path)
        if self.script_metadata is None:
            if write_charon_metadata(script_path) is not None:
                invalidate_metadata_path(script_path)
                self.script_metadata = get_charon_config(script_path)
            else:
                self.script_metadata = {"charon_meta": {}, "tags": []}
        if 'tags' not in (self.script_metadata or {}):
            self.script_metadata['tags'] = []
        
        # Get current script tags
        self.script_tags = set(self.script_metadata.get('tags', []))
        
        # Track original tags and changes for detailed signal
        self.original_tags = self.script_tags.copy()
        self.added_tags = set()
        self.removed_tags = set()
        self.renamed_tags = []  # List of (old_name, new_name) tuples
        
        # Get all tags from folder
        self.all_folder_tags = self._get_all_folder_tags()
        
        # Get script and folder names for display
        self.script_name = os.path.basename(script_path)
        self.folder_name = os.path.basename(folder_path)
        
        self.setup_ui()
        self.setWindowTitle(f"Manage Tags - {self.script_name}")
        
        # Remove the '?' button from title bar
        self.setWindowFlag(WindowContextHelpButtonHint, False)
        self.setWindowFlag(WindowCloseButtonHint, True)
        
    def setup_ui(self):
        """Set up the dialog UI."""
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(10)
        
        # Header with HTML formatting for selective bold
        header = QtWidgets.QLabel(f"Managing <b>{self.script_name}</b> tags in <b>{self.folder_name}</b> folder")
        header.setWordWrap(True)
        layout.addWidget(header)
        
        # Add new tag section at the top
        add_layout = QtWidgets.QHBoxLayout()
        self.new_tag_input = QtWidgets.QLineEdit()
        self.new_tag_input.setPlaceholderText("Enter new tag...")
        self.new_tag_input.returnPressed.connect(self.add_new_tag)
        add_layout.addWidget(self.new_tag_input)
        
        self.add_button = QtWidgets.QPushButton("Add Tag")
        self.add_button.clicked.connect(self.add_new_tag)
        add_layout.addWidget(self.add_button)
        
        layout.addLayout(add_layout)
        
        # Tag table
        self.tag_table = QtWidgets.QTableWidget()
        self.tag_table.setColumnCount(3)
        self.tag_table.setHorizontalHeaderLabels(["", "", ""])  # Empty labels
        self.tag_table.horizontalHeader().hide()  # Hide the header
        self.tag_table.verticalHeader().hide()    # Hide row numbers
        self.tag_table.setShowGrid(False)         # Hide grid lines for cleaner look
        self.tag_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.tag_table.setAlternatingRowColors(True)
        
        # Set column widths
        self.tag_table.setColumnWidth(0, 30)  # Checkbox column
        self.tag_table.setColumnWidth(2, 30)  # Delete button column
        # Let the middle column (tag name) take remaining space
        self.tag_table.horizontalHeader().setStretchLastSection(False)
        self.tag_table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.Stretch)
        
        # Disable sorting by clicking headers (even though they're hidden)
        self.tag_table.setSortingEnabled(False)
        
        # Connect itemChanged signal for tag renaming
        self.tag_table.itemChanged.connect(self.on_tag_renamed)
        
        self.populate_tag_table()
        layout.addWidget(self.tag_table)
        
        # No OK/Cancel buttons - changes are applied immediately
        
    def populate_tag_table(self):
        """Populate the tag table with checkboxes and delete buttons."""
        self.tag_table.setRowCount(0)
        # Temporarily disconnect itemChanged to avoid triggering during population
        self.tag_table.itemChanged.disconnect()
        
        for tag in sorted(self.all_folder_tags):
            row = self.tag_table.rowCount()
            self.tag_table.insertRow(row)
            
            # Checkbox
            checkbox = QtWidgets.QCheckBox()
            checkbox.setChecked(tag in self.script_tags)
            # Connect to immediate save
            checkbox.toggled.connect(lambda checked, t=tag: self._toggle_tag(t, checked))
            # Center the checkbox
            checkbox_widget = QtWidgets.QWidget()
            checkbox_layout = QtWidgets.QHBoxLayout(checkbox_widget)
            checkbox_layout.setContentsMargins(0, 0, 0, 0)
            checkbox_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            checkbox_layout.addWidget(checkbox)
            self.tag_table.setCellWidget(row, 0, checkbox_widget)
            
            # Tag name (editable)
            tag_item = QtWidgets.QTableWidgetItem(tag)
            tag_item.setFlags(tag_item.flags() | QtCore.Qt.ItemFlag.ItemIsEditable)
            tag_item.setData(QtCore.Qt.ItemDataRole.UserRole, tag)  # Store original tag name
            self.tag_table.setItem(row, 1, tag_item)
            
            # Delete button
            delete_btn = QtWidgets.QPushButton("✕")
            delete_btn.setMaximumWidth(20)
            delete_btn.setMaximumHeight(20)
            delete_btn.setToolTip(f"Delete '{tag}' from all scripts")
            delete_btn.setStyleSheet("QPushButton { padding: 0px; font-weight: bold; }")
            # Use a closure to capture the tag value
            def make_delete_handler(tag_name):
                return lambda: self.delete_tag(tag_name)
            delete_btn.clicked.connect(make_delete_handler(tag))
            # Center the delete button
            delete_widget = QtWidgets.QWidget()
            delete_layout = QtWidgets.QHBoxLayout(delete_widget)
            delete_layout.setContentsMargins(0, 0, 0, 0)
            delete_layout.setAlignment(QtCore.Qt.AlignCenter)
            delete_layout.addWidget(delete_btn)
            self.tag_table.setCellWidget(row, 2, delete_widget)
            
        # Reconnect itemChanged signal
        self.tag_table.itemChanged.connect(self.on_tag_renamed)
            
    def _get_all_folder_tags(self) -> Set[str]:
        """Get all unique tags from all scripts in the folder."""
        from ..cache_manager import get_cache_manager
        
        cache_manager = get_cache_manager()
        
        # Check cache first
        cached_tags = cache_manager.get_folder_tags(self.folder_path)
        if cached_tags is not None:
            return cached_tags
        
        # Use the cached folder tags function for better performance
        tags_list = get_folder_tags(self.folder_path)
        tags_set = set(tags_list) if tags_list else set()
        
        # Cache the result
        cache_manager.cache_folder_tags(self.folder_path, tags_set)
        
        return tags_set
        
    def add_new_tag(self):
        """Add a new tag to the table and check it."""
        new_tag = self.new_tag_input.text().strip()
        if not new_tag:
            return
            
        # Check if tag already exists
        for row in range(self.tag_table.rowCount()):
            tag_item = self.tag_table.item(row, 1)
            if tag_item and tag_item.text() == new_tag:
                # Tag exists, just check it
                checkbox_widget = self.tag_table.cellWidget(row, 0)
                if checkbox_widget:
                    checkbox = checkbox_widget.findChild(QtWidgets.QCheckBox)
                    if checkbox and not checkbox.isChecked():
                        checkbox.setChecked(True)  # This will trigger _toggle_tag
                self.new_tag_input.clear()
                return
                
        # Add new tag to the table
        row = self.tag_table.rowCount()
        self.tag_table.insertRow(row)
        
        # Checkbox (checked by default for new tags)
        checkbox = QtWidgets.QCheckBox()
        checkbox.setChecked(True)
        # Connect to immediate save
        checkbox.toggled.connect(lambda checked, t=new_tag: self._toggle_tag(t, checked))
        checkbox_widget = QtWidgets.QWidget()
        checkbox_layout = QtWidgets.QHBoxLayout(checkbox_widget)
        checkbox_layout.setContentsMargins(0, 0, 0, 0)
        checkbox_layout.setAlignment(QtCore.Qt.AlignCenter)
        checkbox_layout.addWidget(checkbox)
        self.tag_table.setCellWidget(row, 0, checkbox_widget)
        
        # Tag name (editable)
        tag_item = QtWidgets.QTableWidgetItem(new_tag)
        tag_item.setFlags(tag_item.flags() | QtCore.Qt.ItemIsEditable)
        tag_item.setData(QtCore.Qt.UserRole, new_tag)  # Store original tag name
        self.tag_table.setItem(row, 1, tag_item)
        
        # Delete button
        delete_btn = QtWidgets.QPushButton("✕")
        delete_btn.setMaximumWidth(20)
        delete_btn.setMaximumHeight(20)
        delete_btn.setToolTip(f"Delete '{new_tag}' from all scripts")
        delete_btn.setStyleSheet("QPushButton { padding: 0px; font-weight: bold; }")
        # Use a closure to capture the tag value
        def make_delete_handler(tag_name):
            return lambda: self.delete_tag(tag_name)
        delete_btn.clicked.connect(make_delete_handler(new_tag))
        delete_widget = QtWidgets.QWidget()
        delete_layout = QtWidgets.QHBoxLayout(delete_widget)
        delete_layout.setContentsMargins(0, 0, 0, 0)
        delete_layout.setAlignment(QtCore.Qt.AlignCenter)
        delete_layout.addWidget(delete_btn)
        self.tag_table.setCellWidget(row, 2, delete_widget)
        
        self.new_tag_input.clear()
        
        # Add to all_folder_tags so it's included in the final save
        self.all_folder_tags.add(new_tag)
        
        # Save immediately for new tag
        self._toggle_tag(new_tag, True)
        
    def delete_tag(self, tag_to_delete: str):
        """Delete a tag from all scripts in the folder."""
        # Confirm deletion
        reply = QtWidgets.QMessageBox.question(
            self, "Confirm Deletion",
            f"Delete tag '{tag_to_delete}' from ALL scripts in this folder?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No
        )
        
        if reply == QtWidgets.QMessageBox.Yes:
            # Delete the tag immediately from all scripts
            self._delete_tags_globally({tag_to_delete})
            
            # Update local state to match the global deletion
            self.script_tags.discard(tag_to_delete)
            # Update metadata in memory instead of reloading from disk
            if self.script_metadata:
                self.script_metadata['tags'] = list(self.script_tags)
            
            # Track this as a removed tag so the tag bar gets updated
            self.removed_tags.add(tag_to_delete)
            # Remove from added tags if it was there
            self.added_tags.discard(tag_to_delete)
            
            # Find and remove the row from table
            for row in range(self.tag_table.rowCount()):
                tag_item = self.tag_table.item(row, 1)
                if tag_item and tag_item.text() == tag_to_delete:
                    self.tag_table.removeRow(row)
                    break
                    
            # Remove from all_folder_tags so it doesn't reappear
            self.all_folder_tags.discard(tag_to_delete)
            
            # Invalidate folder-level caches
            self._invalidate_folder_caches()
            
            # Mark as modified - signal will be emitted in closeEvent
            self._tags_modified = True
    
    def on_tag_renamed(self, item):
        """Handle tag renaming - update all scripts with the old tag name."""
        if item.column() != 1:  # Only handle tag name column
            return
            
        old_tag = item.data(QtCore.Qt.ItemDataRole.UserRole)
        new_tag = item.text().strip()
        
        if not new_tag or new_tag == old_tag:
            return
            
        # Check if new tag name already exists
        for row in range(self.tag_table.rowCount()):
            if row != item.row():
                other_item = self.tag_table.item(row, 1)
                if other_item and other_item.text() == new_tag:
                    # Revert to old name
                    item.setText(old_tag)
                    QtWidgets.QMessageBox.warning(
                        self, "Duplicate Tag",
                        f"Tag '{new_tag}' already exists."
                    )
                    return
        
        # Update all scripts with the old tag to use the new tag
        self._rename_tag_globally(old_tag, new_tag)
        
        # Track the rename
        self.renamed_tags.append((old_tag, new_tag))
        
        # Update local state to match the global rename
        if old_tag in self.script_tags:
            self.script_tags.discard(old_tag)
            self.script_tags.add(new_tag)
        
        # Update tracking based on whether old_tag was original
        if old_tag in self.original_tags:
            # Original tag being renamed
            self.original_tags.discard(old_tag)
            self.original_tags.add(new_tag)
            # If it was marked as removed, update that too
            if old_tag in self.removed_tags:
                self.removed_tags.discard(old_tag)
                self.removed_tags.add(new_tag)
        else:
            # New tag being renamed
            if old_tag in self.added_tags:
                self.added_tags.discard(old_tag)
                self.added_tags.add(new_tag)
        
        # Update metadata in memory instead of reloading from disk
        if self.script_metadata:
            self.script_metadata['tags'] = list(self.script_tags)
        
        # Update the stored original name
        item.setData(QtCore.Qt.ItemDataRole.UserRole, new_tag)
        
        # Update delete button
        delete_widget = self.tag_table.cellWidget(item.row(), 2)
        if delete_widget:
            delete_btn = delete_widget.findChild(QtWidgets.QPushButton)
            if delete_btn:
                delete_btn.clicked.disconnect()
                # Use a closure to capture the tag value
                def make_delete_handler(tag_name):
                    return lambda: self.delete_tag(tag_name)
                delete_btn.clicked.connect(make_delete_handler(new_tag))
                delete_btn.setToolTip(f"Delete '{new_tag}' from all scripts")
        
        # Mark as modified but don't emit signal yet
        self._tags_modified = True
            
    def _toggle_tag(self, tag: str, checked: bool):
        """Toggle a tag on/off for this script and save immediately."""
        # Update script_tags set
        if checked:
            self.script_tags.add(tag)
            # Track additions/removals based on original state
            if tag in self.original_tags:
                # Was removed, now being re-added
                self.removed_tags.discard(tag)
            else:
                # New tag being added
                self.added_tags.add(tag)
        else:
            self.script_tags.discard(tag)
            # Track removals based on original state
            if tag in self.original_tags:
                # Original tag being removed
                self.removed_tags.add(tag)
                self.added_tags.discard(tag)
            else:
                # New tag that was added and now removed
                self.added_tags.discard(tag)
        
        # Update and save metadata
        if self.script_metadata:
            self.script_metadata['tags'] = sorted(list(self.script_tags))
            system_debug(f"Updating tags for {self.script_path}: {self.script_metadata['tags']}")
            if update_charon_config(self.script_path, self.script_metadata):
                # Mark as modified but don't emit signal yet
                self._tags_modified = True
            else:
                # Revert on error
                if checked:
                    self.script_tags.discard(tag)
                else:
                    self.script_tags.add(tag)
                QtWidgets.QMessageBox.critical(
                    self, "Error",
                    "Failed to update script metadata."
                )
        else:
            system_error(f"No metadata loaded for {self.script_path}")
            QtWidgets.QMessageBox.critical(
                self, "Error",
                "No metadata found for this script."
            )
    
    def keyPressEvent(self, event):
        """Override to prevent Enter from closing the dialog."""
        if event.key() == QtCore.Qt.Key.Key_Return or event.key() == QtCore.Qt.Key.Key_Enter:
            # If focus is in the new tag input, add the tag
            if self.new_tag_input.hasFocus():
                self.add_new_tag()
            event.accept()
        elif event.key() == QtCore.Qt.Key.Key_Escape:
            # Allow Escape to close the dialog
            self.close()
        else:
            super().keyPressEvent(event)
        
    def _delete_tags_globally(self, tags_to_delete: Set[str]):
        """Delete specified tags from all scripts in the folder."""
        try:
            with os.scandir(self.folder_path) as entries:
                for entry in entries:
                    if entry.is_dir():
                        metadata = get_charon_config(entry.path)
                        if metadata and 'tags' in metadata:
                            original_tags = metadata.get('tags', [])
                            # Remove deleted tags
                            new_tags = [t for t in original_tags if t not in tags_to_delete]
                            if new_tags != original_tags:
                                metadata['tags'] = new_tags
                                update_charon_config(entry.path, metadata)
                                
        except Exception as e:
            system_error(f"Error deleting tags globally: {e}")
            QtWidgets.QMessageBox.critical(
                self, "Error",
                f"Failed to delete tags from some scripts: {e}"
            )
    
    def _rename_tag_globally(self, old_tag: str, new_tag: str):
        """Rename a tag in all scripts in the folder."""
        try:
            with os.scandir(self.folder_path) as entries:
                for entry in entries:
                    if entry.is_dir():
                        metadata = get_charon_config(entry.path)
                        if metadata and 'tags' in metadata:
                            original_tags = metadata.get('tags', [])
                            # Replace old tag with new tag
                            new_tags = [new_tag if t == old_tag else t for t in original_tags]
                            if new_tags != original_tags:
                                metadata['tags'] = new_tags
                                update_charon_config(entry.path, metadata)
                                
        except Exception as e:
            system_error(f"Error renaming tag globally: {e}")
            QtWidgets.QMessageBox.critical(
                self, "Error",
                f"Failed to rename tag in some scripts: {e}"
            )
    
    def _invalidate_folder_caches(self):
        """Invalidate all caches related to folder tags."""
        from ..metadata_manager import get_folder_tags
        from ..cache_manager import get_cache_manager
        
        # Clear the LRU cache for get_folder_tags
        if hasattr(get_folder_tags, 'cache_clear'):
            get_folder_tags.cache_clear()
        
        # Clear the persistent cache for this folder
        cache_manager = get_cache_manager()
        cache_manager.invalidate_folder(self.folder_path)
        
        system_debug(f"Invalidated folder caches for: {self.folder_path}")
    
    def closeEvent(self, event):
        """Override close event to emit tags_changed signal only once if modifications were made."""
        if self._tags_modified:
            # Invalidate folder-level caches before emitting signal
            self._invalidate_folder_caches()
            
            # Emit both signals for backward compatibility
            self.tags_changed.emit()
            
            # Emit detailed signal with specific changes
            self.detailed_tags_changed.emit(
                list(self.added_tags),
                list(self.removed_tags),
                self.renamed_tags
            )
        super().closeEvent(event)



