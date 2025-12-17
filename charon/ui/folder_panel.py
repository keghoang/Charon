from ..qt_compat import QtWidgets, QtCore, QtGui, Qt, QEvent
from ..metadata_manager import is_folder_compatible_with_host
from .. import config
from ..utilities import apply_incompatible_opacity, is_compatible_with_host
from .custom_table_widgets import FolderTableView
from ..folder_table_model import FolderTableModel, FolderItem
import os

class FolderPanel(QtWidgets.QWidget):
    folder_selected = QtCore.Signal(str)
    folder_deselected = QtCore.Signal()
    navigate_right = QtCore.Signal()
    create_script_requested = QtCore.Signal(str)  # Emits folder name
    open_folder_requested = QtCore.Signal(str)  # For opening folder in file explorer
    collapse_requested = QtCore.Signal()  # Emitted when collapse button clicked

    def __init__(self, parent=None):
        super(FolderPanel, self).__init__(parent)
        self.selected_folder = None
        self.host = "None"
        self.base_path = None
        self._selection_timer = QtCore.QTimer()
        self._selection_timer.setSingleShot(True)
        self._selection_timer.timeout.connect(self._process_selection_change)
        self._pending_selection = None
        self._is_mouse_pressed = False
        self._last_emitted_folder = None
        
        # Create layout
        self.layout = QtWidgets.QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        # Create folder view with custom deselection behavior
        self.folder_view = FolderTableView()
        self.folder_view.clicked.connect(self.on_folder_selected)
        self.folder_view.deselected.connect(self.on_folder_deselected)
        self.folder_view.navigateRight.connect(self.navigate_right)
        self.folder_view.openFolderRequested.connect(self._emit_open_folder_request)
        self.folder_view.createScriptRequested.connect(self._emit_create_script_request)
        self.folder_view.horizontalHeader().show()
        self.folder_view.horizontalHeader().setHighlightSections(False)
        self.folder_view.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.folder_view.horizontalHeader().setFixedHeight(30)
        self.folder_view.setFrameShape(QtWidgets.QFrame.NoFrame)
        
        # Connect mouse signals for drag tracking
        self.folder_view.installEventFilter(self)
        
        # Create folder model
        self.folder_model = FolderTableModel()
        self.folder_view.setModel(self.folder_model)
        
        # Wrap view in a rounded container
        container = QtWidgets.QFrame()
        container.setObjectName("FolderFrame")
        container.setStyleSheet("""
            QFrame#FolderFrame {
                border: 1px solid #171a1f;
                border-radius: 8px;
                background: #262a2e;
            }
        """)
        container.setFrameShape(QtWidgets.QFrame.StyledPanel)
        container_layout = QtWidgets.QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        container_layout.addWidget(self.folder_view)
        
        # Add view to layout
        self.layout.addWidget(container)


    def set_host(self, host):
        """Set the host software for compatibility checking"""
        self.host = host
        if hasattr(self.folder_model, 'set_host'):
            self.folder_model.set_host(host)

    def set_base_path(self, base_path):
        """Set the base path for folder compatibility checking"""
        self.base_path = base_path
        if hasattr(self.folder_model, 'set_base_path'):
            self.folder_model.set_base_path(base_path)

    def update_folders(self, folders):
        """Update the folder list model with a new list of folders."""
        # Create FolderItem objects
        folder_items = []
        for folder_name in folders:
            is_special = folder_name == "Bookmarks"
            # For special folders, we'll show the emoji in the model's display text
            if folder_name == "Bookmarks":
                display_name = "★ Bookmarks"
            else:
                display_name = folder_name
                
            folder_path = os.path.join(self.base_path, folder_name) if self.base_path else folder_name
            item = FolderItem(display_name, folder_path, is_special)
            # Store original name for signals
            item.original_name = folder_name
            folder_items.append(item)
        
        # Update model
        self.folder_model.updateItems(folder_items)
        self.folder_model.sortItems()
        
        # Connect selection model
        if self.folder_view.selectionModel():
            try:
                self.folder_view.selectionModel().currentChanged.disconnect(self.on_current_changed)
            except (TypeError, RuntimeError):
                pass
            self.folder_view.selectionModel().currentChanged.connect(self.on_current_changed)

    def apply_compatibility(self, compatibility_map):
        """Update compatibility while preserving selection."""
        selected = self.get_selected_folder()
        self.folder_model.update_compatibility(compatibility_map)
        if selected:
            self.select_folder(selected)

    def on_current_changed(self, current, previous):
        """Handle folder selection by keyboard navigation."""
        if current.isValid():
            folder = self.folder_model.get_folder_at_row(current.row())
            if folder and hasattr(folder, 'original_name'):
                # If already selected, don't trigger update
                if folder.original_name == self._last_emitted_folder:
                    self._selection_timer.stop()
                    return
                    
                # Schedule new update
                self._pending_selection = folder.original_name
                self._selection_timer.stop()
                self._selection_timer.start(config.UI_FOLDER_SELECTION_DELAY_MS)

    def on_folder_selected(self, index):
        """Handle folder selection."""
        if not index.isValid():
            return
        
        folder = self.folder_model.get_folder_at_row(index.row())
        if folder and hasattr(folder, 'original_name'):
            # Check if this is actually a different folder
            if folder.original_name != self._last_emitted_folder:
                self._pending_selection = folder.original_name
                if self._is_mouse_pressed:
                    # During drag, use longer delay to reduce refreshes
                    self._selection_timer.stop()
                    self._selection_timer.start(config.UI_FOLDER_DRAG_DELAY_MS)
                else:
                    # Normal click - shorter delay
                    self._selection_timer.stop()
                    self._selection_timer.start(config.UI_FOLDER_SELECTION_DELAY_MS)
        
    def on_folder_deselected(self):
        """Handle when the user clicks empty space to deselect."""
        self._selection_timer.stop()
        self._pending_selection = None
        self._last_emitted_folder = None
        self.folder_deselected.emit()

    def get_selected_folder(self):
        """Return the currently selected folder name or None"""
        current = self.folder_view.currentIndex()
        if current.isValid():
            folder = self.folder_model.get_folder_at_row(current.row())
            if folder and hasattr(folder, 'original_name'):
                return folder.original_name
        return None

    # ----- programmatic selection helper -----
    def select_folder(self, folder_name):
        """Select given folder if exists in model and focus the view."""
        for row in range(self.folder_model.rowCount()):
            folder = self.folder_model.get_folder_at_row(row)
            if folder and hasattr(folder, 'original_name') and folder.original_name == folder_name:
                index = self.folder_model.index(row, 0)
                self.folder_view.setCurrentIndex(index)
                self.folder_view.setFocus()
                # For programmatic selection, emit immediately without delay
                self._selection_timer.stop()
                self._pending_selection = None
                self._last_emitted_folder = folder_name
                self.folder_selected.emit(folder_name)
                return True
        return False
    
    def _emit_open_folder_request(self, folder_name):
        """Re-emit the open folder request from the view"""
        self.open_folder_requested.emit(folder_name)
        
    def _emit_create_script_request(self, folder_name):
        """Re-emit the create script request from the view"""
        self.create_script_requested.emit(folder_name)
    
    def _process_selection_change(self):
        """Process the pending selection change after delay."""
        if self._pending_selection and self._pending_selection != self._last_emitted_folder:
            # Store the selection we're about to emit to prevent duplicates
            current_selection = self._pending_selection
            self._pending_selection = None
            self._last_emitted_folder = current_selection
            self.folder_selected.emit(current_selection)
    
    def eventFilter(self, obj, event):
        """Track mouse press/release for drag detection."""
        if obj == self.folder_view:
            if event.type() == QEvent.MouseButtonPress:
                self._is_mouse_pressed = True
            elif event.type() == QEvent.MouseButtonRelease:
                self._is_mouse_pressed = False
                # If there's a pending selection, process it immediately on release
                if self._pending_selection:
                    self._selection_timer.stop()
                    self._process_selection_change()
        return super(FolderPanel, self).eventFilter(obj, event)
