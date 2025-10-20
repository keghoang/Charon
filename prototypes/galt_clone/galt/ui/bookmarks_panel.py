"""
Bookmarks Panel for Command Mode

A simple panel showing bookmarked scripts with names and icons.
"""

from ..qt_compat import QtWidgets, QtCore, QtGui, Qt, ItemIsEnabled, ItemIsSelectable
import os

# Import config with fallback
try:
    from .. import config
except ImportError:
    # Fallback for CLI usage
    class FallbackConfig:
        UI_ICON_FONT_FAMILY = "Segoe UI"
        INCOMPATIBLE_OPACITY = 0.4
    config = FallbackConfig()

# Import centralized logic
from ..script_validator import ScriptValidator
from ..utilities import create_script_sort_key, apply_incompatible_opacity
from ..metadata_manager import get_galt_config
from ..script_model import ScriptItem


class BookmarksListModel(QtCore.QAbstractListModel):
    """List model for bookmarked scripts with sorting and compatibility checking."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scripts = []  # List of ScriptItem objects
        self.host = "None"
    
    def sort_scripts(self):
        """Sort scripts using centralized sorting logic."""
        self.scripts.sort(key=lambda item: create_script_sort_key(item, self.host))
        self.layoutChanged.emit()
    
    def get_visual_properties(self, script_item):
        """Get visual properties for a script using centralized logic."""
        return ScriptValidator.get_visual_properties(
            script_item.path,
            script_item.metadata,
            self.host,
            getattr(script_item, 'is_bookmarked', False)
        )
    
    def get_foreground_brush(self, script_item):
        """Get the foreground brush for a script item."""
        props = self.get_visual_properties(script_item)
        
        color = QtGui.QColor(props["color"])
        if props["should_fade"]:
            color = apply_incompatible_opacity(color)
        
        return QtGui.QBrush(color)
    
    def can_run_script(self, script_item):
        """Check if a script can be executed."""
        props = self.get_visual_properties(script_item)
        return props["can_run"]
    
    def get_item_flags(self, script_item):
        """Get Qt item flags based on script properties."""
        props = self.get_visual_properties(script_item)
        
        if props["is_selectable"]:
            return ItemIsEnabled | ItemIsSelectable
        else:
            return ItemIsEnabled  # Visible but not selectable
    
    def set_bookmarks(self, bookmark_paths):
        """Set the bookmarks from a list of script paths."""
        self.beginResetModel()
        self.scripts = []
        
        # Load metadata and create ScriptItem objects
        for path in bookmark_paths:
            if os.path.exists(path):
                script_name = os.path.basename(path)
                # Load metadata
                metadata = get_galt_config(path)
                # Create ScriptItem
                item = ScriptItem(script_name, path, metadata, self.host)
                item.is_bookmarked = True  # Mark as bookmarked for sorting
                self.scripts.append(item)
        
        # Sort bookmarks using centralized sorting logic
        self.sort_scripts()
        self.endResetModel()
    
    def set_host(self, host):
        """Set the host software and re-sort/recolor items."""
        if self.host != host:
            self.host = host
            # Update host for all items
            for item in self.scripts:
                item.host = host
            # Refresh all visual properties
            if self.scripts:
                self.layoutChanged.emit()
    
    def rowCount(self, parent=QtCore.QModelIndex()):
        return len(self.scripts)
    
    def data(self, index, role=QtCore.Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self.scripts):
            return None
        
        item = self.scripts[index.row()]
        
        if role == QtCore.Qt.DisplayRole:
            return item.name
        elif role == QtCore.Qt.ToolTipRole:
            return item.path
        elif role == QtCore.Qt.UserRole:
            return item.path
        elif role == QtCore.Qt.ForegroundRole:
            # Use centralized method for consistent coloring
            return self.get_foreground_brush(item)
        
        return None
    
    def flags(self, index):
        """Return item flags - disable selection for invalid scripts."""
        if not index.isValid():
            return QtCore.Qt.NoItemFlags
        
        item = self.scripts[index.row()]
        # Use centralized method for consistent behavior
        return self.get_item_flags(item)
    


class BookmarksPanel(QtWidgets.QWidget):
    """Simple panel showing bookmarked scripts."""
    
    # Signals
    script_run_requested = QtCore.Signal(str)  # script_path
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.host = "None"
        self.setup_ui()
    
    def setup_ui(self):
        """Setup the panel UI."""
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        
        # Remove header since tab already shows "Bookmarks"
        
        # Bookmarks list
        self.bookmarks_model = BookmarksListModel(self)
        self.bookmarks_view = QtWidgets.QListView()
        self.bookmarks_view.setModel(self.bookmarks_model)
        self.bookmarks_view.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.bookmarks_view.doubleClicked.connect(self.on_bookmark_double_clicked)
        
        # Enable text eliding for narrow widths
        self.bookmarks_view.setTextElideMode(QtCore.Qt.ElideRight)
        self.bookmarks_view.setWordWrap(False)
        
        # Set font for icon display
        font = self.bookmarks_view.font()
        font.setFamily(config.UI_ICON_FONT_FAMILY)
        self.bookmarks_view.setFont(font)
        
        layout.addWidget(self.bookmarks_view)
    
    def set_bookmarks(self, bookmark_paths):
        """Set the bookmarked scripts to display."""
        self.bookmarks_model.set_bookmarks(bookmark_paths)
    
    def set_host(self, host):
        """Set the host software for compatibility checking."""
        self.host = host
        self.bookmarks_model.set_host(host)
    
    def on_bookmark_double_clicked(self, index):
        """Handle double-click on bookmark."""
        if not index.isValid():
            return
        
        # Get the item to check if it's runnable
        item = self.bookmarks_model.scripts[index.row()]
        
        # Check if script can run using centralized validation
        if not self.bookmarks_model.can_run_script(item):
            # Don't run incompatible or invalid scripts
            return
        
        script_path = self.bookmarks_model.data(index, QtCore.Qt.UserRole)
        if script_path:
            # Don't flash here - it's handled centrally via execute_script
            self.script_run_requested.emit(script_path)
    
    def flash_bookmark_execution(self, script_path):
        """Flash the bookmark row to indicate execution."""
        # Import the centralized flash function
        from .flash_utils import flash_table_row
        
        # Find the bookmark in the model
        for row, item in enumerate(self.bookmarks_model.scripts):
            if item.path == script_path:
                # Use centralized flash function
                flash_table_row(self.bookmarks_view, row)
                break