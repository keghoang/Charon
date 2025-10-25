from ..qt_compat import QtWidgets, QtCore, Qt, UserRole, exec_menu


def create_tag_badge(tag_name, fixed_height=24):
    """
    Create a consistent tag badge label widget using button styling.
    
    Args:
        tag_name: The text to display in the badge
        fixed_height: Height of the badge in pixels (default: 24)
        
    Returns:
        QLabel widget styled as a tag badge with button appearance
    """
    tag_label = QtWidgets.QLabel(tag_name)
    tag_label.setStyleSheet("""
        QLabel {
            background-color: palette(button);
            color: palette(buttonText);
            border: 1px solid palette(mid);
            padding: 3px 8px;
            border-radius: 3px;
            font-size: 11px;
        }
    """)
    # Set size constraints - fixed height, dynamic width
    tag_label.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Fixed)
    tag_label.setFixedHeight(fixed_height)
    
    return tag_label

class DeselectionListView(QtWidgets.QListView):
    """
    A QListView subclass that deselects items when clicking on empty space.
    Also emits a deselected signal when this happens.
    """
    deselected = QtCore.Signal()
    openFolderRequested = QtCore.Signal()  # Signal for opening folder
    
    def __init__(self, parent=None):
        super(DeselectionListView, self).__init__(parent)
    
    def mousePressEvent(self, event):
        """Override mouse press event to check if clicking on empty space"""
        index = self.indexAt(event.pos())
        if not index.isValid():
            # Clicked on empty space, clear selection
            self.clearSelection()
            self.setCurrentIndex(QtCore.QModelIndex())
            self.deselected.emit()
        
        # Call the parent handler to maintain normal list view behavior
        super(DeselectionListView, self).mousePressEvent(event) 


class FolderListView(DeselectionListView):
    """List view used in FolderPanel with custom right-arrow navigation to scripts list."""
    navigateRight = QtCore.Signal()
    openFolderRequested = QtCore.Signal(str)  # Signal for opening folder with folder name

    def keyPressEvent(self, event):
        key = event.key()

        # Right arrow -> jump to scripts list
        if key == Qt.Key_Right:
            # Emit signal so parent can move focus to scripts list
            self.navigateRight.emit()
            event.accept()
            return
        # Swallow Left arrow to avoid pickWalk prints
        if key == Qt.Key_Left:
            # Swallow left arrow to avoid pickWalk prints
            event.accept()
            return

        # Trap Up/Down when at list bounds to keep focus in Charon
        if key in (Qt.Key_Up, Qt.Key_Down):
            model = self.model()
            row_count = model.rowCount() if model else 0
            if row_count == 0:
                event.accept()
                return

            current = self.currentIndex()
            if not current.isValid():
                super().keyPressEvent(event)
                return

            row = current.row()
            if key == Qt.Key_Up and row == 0:
                event.accept()
                return
            if key == Qt.Key_Down and row == row_count - 1:
                event.accept()
                return

        super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        index = self.indexAt(event.pos())
        if not index.isValid():
            return

        menu = QtWidgets.QMenu(self)
        open_folder_action = menu.addAction("Open Folder")
        # Store the folder name in the action for context
        folder_item = self.model().item(index.row())
        folder_name = folder_item.data(UserRole) or folder_item.text()
        open_folder_action.setData(folder_name)
        open_folder_action.triggered.connect(lambda: self.openFolderRequested.emit(folder_name))
        exec_menu(menu, event.globalPos())


class ScriptListView(DeselectionListView):
    """List view used in ScriptPanel with custom left-arrow navigation back to folders and end-of-list trapping."""
    navigateLeft = QtCore.Signal()
    bookmarkRequested = QtCore.Signal(str)  # Signal emitted when bookmark is requested
    assignHotkeyRequested = QtCore.Signal(str)
    createMetadataRequested = QtCore.Signal(str)  # Signal for creating metadata
    editMetadataRequested = QtCore.Signal(str)  # Signal for editing metadata
    openReadmeRequested = QtCore.Signal(str)  # Signal for opening/creating readme
    openFolderRequested = QtCore.Signal(str)  # Signal for opening script's folder

    def __init__(self, parent=None):
        super(ScriptListView, self).__init__(parent)
        self.host = "None"
        # Set uniform item sizes for consistent row heights
        self.setUniformItemSizes(True)

    def set_host(self, host):
        self.host = host

    def keyPressEvent(self, event):
        key = event.key()

        # Swallow Right arrow to keep focus inside Charon (fix Maya pickWalk)
        if key == Qt.Key_Right:
            event.accept()
            return

        # Left arrow – go back to folders list
        if key == Qt.Key_Left:
            self.navigateLeft.emit()
            event.accept()
            return

        # Trap Up/Down when at the ends so Maya pickWalk command isn't printed
        if key in (Qt.Key_Up, Qt.Key_Down):
            model = self.model()
            row_count = model.rowCount() if model else 0
            if row_count == 0:
                event.accept()
                return

            current = self.currentIndex()
            if not current.isValid():
                super().keyPressEvent(event)
                return

            row = current.row()
            if key == Qt.Key_Up and row == 0:
                event.accept()
                return
            if key == Qt.Key_Down and row == row_count - 1:
                event.accept()
                return

        super().keyPressEvent(event)
    
    def contextMenuEvent(self, event):
        """Handle right-click context menu"""
        from ..script_table_model import ScriptTableModel
        
        index = self.indexAt(event.pos())
        if not index.isValid():
            return
        
        # Get the script path from the model
        model = self.model()
        script = None
        if hasattr(model, 'mapToSource'):
            # If we have a proxy model, map to source
            source_index = model.mapToSource(index)
            source_model = model.sourceModel()
            if hasattr(source_model, 'scripts') and source_index.row() < len(source_model.scripts):
                script = source_model.scripts[source_index.row()]
        else:
            # Direct model access
            if hasattr(model, 'scripts') and index.row() < len(model.scripts):
                script = model.scripts[index.row()]
        
        if not script:
            return
            
        script_path = script.path
        
        # Create context menu
        menu = QtWidgets.QMenu(self)

        # Add Open Folder action (emits signal instead of calling window method directly)
        open_folder_action = menu.addAction("Open Folder")
        open_folder_action.triggered.connect(lambda: self.openFolderRequested.emit(script_path))

        # Check if script is already bookmarked
        try:
            from charon.settings import user_settings_db
            import os
            normalized_path = os.path.normpath(script_path)
            is_bookmarked = user_settings_db.is_bookmarked(normalized_path)
            
            if is_bookmarked:
                bookmark_action = menu.addAction("✗ Remove Bookmark")
            else:
                bookmark_action = menu.addAction("★ Add Bookmark")
                
            bookmark_action.triggered.connect(lambda: self.bookmarkRequested.emit(script_path))
        except Exception as e:
            # Fallback to generic text if there's an error
            bookmark_action = menu.addAction("Bookmark")
            bookmark_action.triggered.connect(lambda: self.bookmarkRequested.emit(script_path))

        # Add separator for metadata actions
        menu.addSeparator()

        # Add metadata actions
        if script.has_metadata():
            # Script has metadata - show edit options
            edit_metadata_action = menu.addAction("Edit Metadata")
            edit_metadata_action.triggered.connect(lambda: self.editMetadataRequested.emit(script_path))
        else:
            # Script has no metadata - show create option
            create_metadata_action = menu.addAction("Create Metadata")
            create_metadata_action.triggered.connect(lambda: self.createMetadataRequested.emit(script_path))

        # Add Readme action (after metadata, before hotkey)
        import os
        readme_path = os.path.join(script_path, "readme.md")
        if os.path.exists(readme_path):
            
        else:
            readme_action = menu.addAction("Create Readme")
        readme_action.triggered.connect(lambda: self.openReadmeRequested.emit(script_path))

        # Add separator for hotkey action
        menu.addSeparator()

        # Hotkey action
        script_sw = self.host if self.host and str(self.host).lower() != "none" else "nuke"
        current_hotkey = user_settings_db.get_hotkey_for_script(normalized_path, script_sw)

        if current_hotkey:
            hotkey_action = menu.addAction(f"? Remove Hotkey ({current_hotkey})")
            hotkey_action.setEnabled(True)
        else:
            hotkey_action = menu.addAction("? Assign Hotkey")
            from ..script_validator import ScriptValidator
            has_valid_entry, _ = ScriptValidator.has_valid_entry(script.path, script.metadata)
            hotkey_action.setEnabled(has_valid_entry)
            if not has_valid_entry:
                hotkey_action.setToolTip("Script must have a valid entry file (main.py, main.mel, etc.)")

        hotkey_action.triggered.connect(lambda: self.assignHotkeyRequested.emit(script_path))
        
        # Show menu at cursor position
        exec_menu(menu, event.globalPos())
