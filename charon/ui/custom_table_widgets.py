import os
from typing import Callable, Optional

from ..qt_compat import QtWidgets, QtCore, QtGui, Qt, AlignLeft, AlignVCenter, exec_menu
from ..script_table_model import ScriptTableModel
from ..folder_table_model import FolderTableModel
from .button_delegate import ButtonDelegate
from .custom_delegates import ScriptNameDelegate


class ScriptTableView(QtWidgets.QTableView):
    """Table view for workflows with keyboard navigation and context menus preserved from list view"""
    
    # Signals
    deselected = QtCore.Signal()
    navigateLeft = QtCore.Signal()
    bookmarkRequested = QtCore.Signal(str)
    assignHotkeyRequested = QtCore.Signal(str)
    createMetadataRequested = QtCore.Signal(str)
    editMetadataRequested = QtCore.Signal(str)
    manageTagsRequested = QtCore.Signal(str)
    openFolderRequested = QtCore.Signal(str)
    script_run = QtCore.Signal(str)
    script_validate = QtCore.Signal(str)
    script_show_validation_payload = QtCore.Signal(str)
    script_show_raw_validation_payload = QtCore.Signal(str)
    script_revalidate = QtCore.Signal(str)
    script_override_validation = QtCore.Signal(str)
    mousePressed = QtCore.Signal()
    mouseReleased = QtCore.Signal()
    createScriptInCurrentFolder = QtCore.Signal()
    openCurrentFolder = QtCore.Signal()
    workflowFileDropped = QtCore.Signal(list)
    
    def __init__(self, parent=None):
        super(ScriptTableView, self).__init__(parent)
        self.host = "None"
        self._advanced_mode_provider: Optional[Callable[[], bool]] = None
        
        # Configure table appearance
        self.setShowGrid(False)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.verticalHeader().hide()
        
        # Set uniform row height for consistency
        self.verticalHeader().setDefaultSectionSize(30)
        self.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Fixed)
        
        # Configure horizontal header
        self.horizontalHeader().setStretchLastSection(False)
        self.horizontalHeader().setHighlightSections(False)
        # Set header height to match row height
        self.horizontalHeader().setFixedHeight(30)
        # Ensure the header cells have proper alignment
        self.horizontalHeader().setDefaultAlignment(AlignLeft | AlignVCenter)
        
        # Create and set button delegate for Validate column
        self._validate_delegate = ButtonDelegate(
            self,
            column=ScriptTableModel.COL_VALIDATE,
            label=None,
            enabled_role=ScriptTableModel.ValidationEnabledRole,
            size_hint=QtCore.QSize(110, 30),
        )
        self._validate_delegate.clicked.connect(self._on_validate_clicked)
        self.setItemDelegateForColumn(ScriptTableModel.COL_VALIDATE, self._validate_delegate)

        # Create and set button delegate for Run column
        self._grab_delegate = ButtonDelegate(
            self,
            column=ScriptTableModel.COL_RUN,
            label="Grab",
            enabled_role=ScriptTableModel.CanRunRole,
            size_hint=QtCore.QSize(80, 30),
        )
        self._grab_delegate.clicked.connect(self._on_grab_clicked)
        self.setItemDelegateForColumn(ScriptTableModel.COL_RUN, self._grab_delegate)
        
        # Create and set name delegate for Name column
        self._name_delegate = ScriptNameDelegate(self)
        self.setItemDelegateForColumn(ScriptTableModel.COL_NAME, self._name_delegate)
        
        
        # Enable mouse tracking to properly handle drag selection
        self.setMouseTracking(True)
        existing_style = self.styleSheet() or ''
        focusless_style = 'QTableView::item:focus { outline: none; }'
        header_style = """
        QHeaderView {
            background: #37393f;
            border: 1px solid #171a1f;
            border-bottom: 0px;
            border-top-left-radius: 8px;
            border-top-right-radius: 8px;
            margin: 0px;
            padding: 0px;
        }
        QHeaderView::section {
            background: #37393f;
            color: palette(windowText);
            border: none;
            padding: 4px 6px;
            font-weight: bold;
            margin: 0px;
        }
        """
        table_style = """
        QTableView {
            background: #262a2e;
            alternate-background-color: #1f2226;
            color: #f4f4f5;
            selection-background-color: #84a8de;
            selection-color: #0f1114;
            border: none;
            border-radius: 0px;
            padding: 0px;
        }
        QTableCornerButton::section {
            background: #37393f;
            border: 1px solid #171a1f;
            border-bottom: 0px;
            border-top-left-radius: 8px;
            margin: 0px;
            padding: 0px;
        }
        """
        if focusless_style not in existing_style:
            combined_style = focusless_style if not existing_style else '{}\n{}'.format(existing_style, focusless_style)
            combined_style = '{}\n{}\n{}'.format(combined_style, header_style, table_style)
            self.setStyleSheet(combined_style)
        else:
            combined_style = '{}\n{}\n{}'.format(existing_style, header_style, table_style)
            self.setStyleSheet(combined_style)
        self.setAcceptDrops(True)
        
    def set_host(self, host):
        self.host = host
    
    def clear_delegate_caches(self):
        """Clear any caches held by delegates"""
        if hasattr(self, '_name_delegate'):
            self._name_delegate.clear_icon_cache()
        
    def setModel(self, model):
        """Override to configure column widths"""
        super().setModel(model)
        
        if model:
            # Configure column widths
            self.setColumnWidth(ScriptTableModel.COL_NAME, 300)  # Name column
            self.setColumnWidth(ScriptTableModel.COL_HOTKEY, 80)  # Hotkey column
            self.setColumnWidth(ScriptTableModel.COL_VALIDATE, 110)  # Validate button column
            self.setColumnWidth(ScriptTableModel.COL_RUN, 80)  # Run button column
            
            # Stretch the name column to fill available space
            self.horizontalHeader().setSectionResizeMode(
                ScriptTableModel.COL_NAME, QtWidgets.QHeaderView.Stretch
            )

    def set_advanced_mode_provider(self, provider: Optional[Callable[[], bool]]) -> None:
        """Register a callback returning whether advanced mode is enabled."""
        self._advanced_mode_provider = provider

    def _extract_json_paths(self, mime_data) -> list:
        """Pull supported workflow JSON paths from mime data."""
        if mime_data is None:
            return []

        json_paths = []
        if mime_data.hasUrls():
            for url in mime_data.urls():
                if url.isLocalFile():
                    local_path = url.toLocalFile()
                    if isinstance(local_path, str) and local_path.lower().endswith(".json"):
                        json_paths.append(local_path)
        elif mime_data.hasText():
            for line in mime_data.text().splitlines():
                candidate = line.strip()
                if candidate.lower().endswith(".json") and os.path.isfile(candidate):
                    json_paths.append(candidate)
        return json_paths

    def _can_accept_drop(self, mime_data) -> bool:
        """Check if the drag contains at least one workflow JSON."""
        return bool(self._extract_json_paths(mime_data))

    def _emit_script_signal(self, index, signal):
        """Emit the provided signal with the script path resolved from the index."""
        if not index.isValid():
            return
            
        # Get the script path
        model = index.model()
        source_model = model
        source_index = index
        
        if hasattr(model, 'sourceModel'):
            source_model = model.sourceModel()
            source_index = model.mapToSource(index)
            
        if source_model and source_index.isValid():
            # Get script path from the name column
            name_index = source_model.index(source_index.row(), ScriptTableModel.COL_NAME)
            script_path = source_model.data(name_index, ScriptTableModel.PathRole)
            if script_path:
                signal.emit(script_path)

    def _on_grab_clicked(self, index):
        """Handle Grab button click."""
        self._emit_script_signal(index, self.script_run)

    def _on_validate_clicked(self, index):
        """Handle Validate button click."""
        self._emit_script_signal(index, self.script_validate)
        
    def mousePressEvent(self, event):
        """Handle mouse press to detect clicks on empty space"""
        # Emit signal that mouse was pressed
        self.mousePressed.emit()
        
        index = self.indexAt(event.pos())
        if not index.isValid():
            # Clicked on empty space
            self.clearSelection()
            self.setCurrentIndex(QtCore.QModelIndex())
            self.deselected.emit()
            # Don't process the event further to avoid conflicts
            event.accept()
            return
            
        super().mousePressEvent(event)
        
    def mouseReleaseEvent(self, event):
        """Handle mouse release"""
        # Emit signal that mouse was released
        self.mouseReleased.emit()
        super().mouseReleaseEvent(event)

    def dragEnterEvent(self, event):
        """Accept drags that include workflow JSON files."""
        if self._can_accept_drop(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        """Accept drag move for workflow JSON files."""
        if self._can_accept_drop(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event):
        """Handle dropped workflow JSON files."""
        paths = self._extract_json_paths(event.mimeData())
        if not paths:
            event.ignore()
            return

        self.workflowFileDropped.emit(paths)
        event.acceptProposedAction()
        
    def keyPressEvent(self, event):
        """Preserve keyboard navigation from list view"""
        key = event.key()
        
        # Swallow Right arrow to keep focus inside Charon
        if key == QtCore.Qt.Key_Right:
            event.accept()
            return
            
        # Left arrow - go back to folders list
        if key == QtCore.Qt.Key_Left:
            self.navigateLeft.emit()
            event.accept()
            return
            
        # Trap Up/Down at boundaries
        if key in (QtCore.Qt.Key_Up, QtCore.Qt.Key_Down):
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
            if key == QtCore.Qt.Key_Up and row == 0:
                event.accept()
                return
            if key == QtCore.Qt.Key_Down and row == row_count - 1:
                event.accept()
                return
                
        super().keyPressEvent(event)
        
    def contextMenuEvent(self, event):
        """Handle right-click context menu"""
        from ..script_table_model import ScriptTableModel
        
        index = self.indexAt(event.pos())
        if not index.isValid():
            # Show empty space context menu
            self._showEmptySpaceMenu(event)
            return
            
        model = self.model()
        if not model:
            return
            
        # Handle proxy model
        source_model = model
        source_index = index
        
        if hasattr(model, 'sourceModel'):
            source_model = model.sourceModel()
            source_index = model.mapToSource(index)
            
        # Get script from source model
        script = source_model.data(source_index, ScriptTableModel.ScriptRole)
        if not script:
            return
            
        script_path = script.path
        column = source_index.column()
        state = "idle"
        if hasattr(source_model, "get_validation_state"):
            try:
                state = source_model.get_validation_state(script_path)
            except Exception:
                state = "idle"

        if column == ScriptTableModel.COL_VALIDATE:
            menu = QtWidgets.QMenu(self)
            revalidate_action = menu.addAction("Revalidate")
            revalidate_action.setEnabled(state != "validating")
            revalidate_action.triggered.connect(lambda: self.script_revalidate.emit(script_path))

            view_result_action = menu.addAction("View Validation Result")
            view_result_action.triggered.connect(lambda: self.script_show_validation_payload.emit(script_path))

            override_action = menu.addAction("Override Validation (Force Passed)")
            override_action.triggered.connect(lambda: self.script_override_validation.emit(script_path))

            exec_menu(menu, event.globalPos())
            return

        # Create context menu
        menu = QtWidgets.QMenu(self)

        # Open Folder action
        open_folder_action = menu.addAction("Open Folder")
        open_folder_action.triggered.connect(lambda: self.openFolderRequested.emit(script_path))
        
        # Bookmark action
        try:
            from charon.settings import user_settings_db
            # Normalize path before checking bookmark status
            import os
            normalized_path = os.path.normpath(script_path)
            is_bookmarked = user_settings_db.is_bookmarked(normalized_path)
            
            if is_bookmarked:
                bookmark_action = menu.addAction("✗ Remove Bookmark")
            else:
                bookmark_action = menu.addAction("★ Add Bookmark")
                
            bookmark_action.triggered.connect(lambda: self.bookmarkRequested.emit(script_path))
        except Exception:
            bookmark_action = menu.addAction("Bookmark")
            bookmark_action.triggered.connect(lambda: self.bookmarkRequested.emit(script_path))
            
        menu.addSeparator()

        # Metadata actions
        if script.has_metadata():
            edit_metadata_action = menu.addAction("Edit Metadata")
            edit_metadata_action.triggered.connect(lambda: self.editMetadataRequested.emit(script_path))
            
            # Manage Tags action (only if metadata exists)
            manage_tags_action = menu.addAction("Manage Tags")
            manage_tags_action.triggered.connect(lambda: self.manageTagsRequested.emit(script_path))
        else:
            create_metadata_action = menu.addAction("Create Metadata")
            create_metadata_action.triggered.connect(lambda: self.createMetadataRequested.emit(script_path))
            
        menu.addSeparator()
        
        # Hotkey action
        script_sw = self.host if self.host and str(self.host).lower() != "none" else "nuke"
        # Use normalized path for hotkey lookup
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
                hotkey_action.setToolTip("Workflow must have a valid entry file (main.py, main.mel, etc.)")

        hotkey_action.triggered.connect(lambda: self.assignHotkeyRequested.emit(script_path))
        
        exec_menu(menu, event.globalPos())
    
    def _showEmptySpaceMenu(self, event):
        """Show context menu for empty space in the workflow panel."""
        menu = QtWidgets.QMenu(self)
        
        # New Workflow action
        new_script_action = menu.addAction("New Workflow")
        new_script_action.triggered.connect(self.createScriptInCurrentFolder.emit)
        
        # Open Folder action
        open_folder_action = menu.addAction("Open Folder")
        open_folder_action.triggered.connect(self.openCurrentFolder.emit)
        
        exec_menu(menu, event.globalPos())


class FolderTableView(QtWidgets.QTableView):
    """Table view for folders with keyboard navigation preserved from list view"""
    
    # Signals
    deselected = QtCore.Signal()
    navigateRight = QtCore.Signal()
    openFolderRequested = QtCore.Signal(str)
    createScriptRequested = QtCore.Signal(str)
    
    def __init__(self, parent=None):
        super(FolderTableView, self).__init__(parent)
        
        # Configure table appearance
        self.setShowGrid(False)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.verticalHeader().hide()
        self.horizontalHeader().show()
        header_style = """
        QHeaderView {
            background: #37393f;
            border: 1px solid #171a1f;
            border-bottom: 0px;
            border-top-left-radius: 8px;
            border-top-right-radius: 8px;
            margin: 0px;
            padding: 0px;
        }
        QHeaderView::section {
            background: #37393f;
            color: palette(windowText);
            border: none;
            padding: 4px 6px;
            font-weight: bold;
            margin: 0px;
        }
        """
        table_style = """
        QTableView {
            background: #262a2e;
            alternate-background-color: #1f2226;
            color: #f4f4f5;
            selection-background-color: #84a8de;
            selection-color: #0f1114;
            border: none;
            border-radius: 0px;
            padding: 0px;
        }
        QTableCornerButton::section {
            background: #37393f;
            border: 1px solid #171a1f;
            border-bottom: 0px;
            border-top-left-radius: 8px;
            margin: 0px;
            padding: 0px;
        }
        """
        self.setStyleSheet(f"{header_style}\n{table_style}")
        
        # Set uniform row height
        self.verticalHeader().setDefaultSectionSize(30)
        self.verticalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Fixed)
        
        # Stretch column to fill width
        self.horizontalHeader().setStretchLastSection(True)
        
    def mousePressEvent(self, event):
        """Handle mouse press to detect clicks on empty space"""
        index = self.indexAt(event.pos())
        if not index.isValid():
            # Clicked on empty space
            self.clearSelection()
            self.setCurrentIndex(QtCore.QModelIndex())
            self.deselected.emit()
            
        super().mousePressEvent(event)
        
    def keyPressEvent(self, event):
        """Handle keyboard navigation"""
        key = event.key()
        
        # Right arrow -> jump to scripts list
        if key == QtCore.Qt.Key_Right:
            self.navigateRight.emit()
            event.accept()
            return
            
        # Swallow Left arrow to avoid pickWalk prints
        if key == QtCore.Qt.Key_Left:
            event.accept()
            return
            
        # Trap Up/Down at boundaries
        if key in (QtCore.Qt.Key_Up, QtCore.Qt.Key_Down):
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
            if key == QtCore.Qt.Key_Up and row == 0:
                event.accept()
                return
            if key == QtCore.Qt.Key_Down and row == row_count - 1:
                event.accept()
                return
                
        super().keyPressEvent(event)
        
    def contextMenuEvent(self, event):
        """Handle right-click context menu"""
        index = self.indexAt(event.pos())
        if not index.isValid():
            return
            
        model = self.model()
        if not model:
            return
            
        # Get folder from model
        folder = model.data(index, FolderTableModel.FolderRole)
        if not folder:
            return
            
        menu = QtWidgets.QMenu(self)
        
        # Only add "New Workflow" for real folders (not Bookmarks, Hotkeys, etc.)
        if not (hasattr(folder, 'is_special') and folder.is_special):
            new_script_action = menu.addAction("New Workflow")
            new_script_action.triggered.connect(lambda: self.createScriptRequested.emit(folder.name))
            menu.addSeparator()
        
        open_folder_action = menu.addAction("Open Folder")
        open_folder_action.triggered.connect(lambda: self.openFolderRequested.emit(folder.name))
        exec_menu(menu, event.globalPos())
