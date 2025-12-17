"""
Tiny Mode Widget

A minimal UI for tiny mode showing execution history and essential controls.
"""

from ..qt_compat import QtWidgets, QtCore, QtGui
from .execution_history_panel import ExecutionHistoryPanel
from .bookmarks_panel import BookmarksPanel

# Import config with fallback
try:
    from .. import config
except ImportError:
    # Fallback for CLI usage
    class FallbackConfig:
        UI_ICON_FONT_FAMILY = "Segoe UI"
    config = FallbackConfig()


class TinyModeWidget(QtWidgets.QWidget):
    """Minimal UI widget for tiny mode."""
    
    # Signals
    exit_tiny_mode = QtCore.Signal()
    open_settings = QtCore.Signal()
    open_help = QtCore.Signal()
    
    def __init__(self, parent=None):
        super().__init__(parent)
        # Set minimum size from config
        self.setMinimumSize(config.TINY_MODE_MIN_WIDTH, config.TINY_MODE_MIN_HEIGHT)
        self.bookmarks = []  # List of bookmarked script paths
        self.host = "None"
        self.setup_ui()
    
    def setup_ui(self):
        """Setup the tiny mode UI."""
        # Main layout
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        
        # Top button bar
        top_layout = QtWidgets.QHBoxLayout()
        
        # Normal button on the left (returns to normal mode)
        self.exit_button = QtWidgets.QPushButton("Normal")
        self.exit_button.setToolTip("Return to Normal Mode (F2)")
        self.exit_button.clicked.connect(self.exit_tiny_mode.emit)
        top_layout.addWidget(self.exit_button)
        
        top_layout.addStretch()
        
        # Settings and Help buttons on the right
        self.settings_button = QtWidgets.QPushButton("Settings")
        self.settings_button.clicked.connect(self.open_settings.emit)
        top_layout.addWidget(self.settings_button)
        
        self.help_button = QtWidgets.QPushButton("Help")
        self.help_button.clicked.connect(self.open_help.emit)
        top_layout.addWidget(self.help_button)
        
        layout.addLayout(top_layout)
        
        # Create tab widget for panels
        self.tab_widget = QtWidgets.QTabWidget()
        
        # Execution history panel (will be set from main window)
        # Don't show collapse button or header label in tiny mode
        self.execution_history_panel = ExecutionHistoryPanel(self, show_collapse_button=False, show_header_label=False)
        self.tab_widget.addTab(self.execution_history_panel, "History")
        
        # Bookmarks panel will be created lazily when needed
        self.bookmarks_panel = None
        
        layout.addWidget(self.tab_widget, 1)  # Give it stretch
        
        # Force initial layout update
        self.tab_widget.updateGeometry()
        QtCore.QTimer.singleShot(0, self.updateGeometry)
    
    def set_execution_history_model(self, model):
        """Set the execution history model to share with main UI."""
        self.execution_history_panel.history_model = model
        self.execution_history_panel.history_view.setModel(model)
        
        # Set font for history view to match main UI
        font = self.execution_history_panel.history_view.font()
        font.setFamily(config.UI_ICON_FONT_FAMILY)
        self.execution_history_panel.history_view.setFont(font)
        
    def share_execution_panel_state(self, main_execution_panel):
        """Share the execution panel state with main UI panel."""
        # Share the open dialogs dictionary so both panels track the same windows
        self.execution_history_panel.open_dialogs = main_execution_panel.open_dialogs
    
    def set_bookmarks(self, bookmark_paths):
        """Set the bookmarked scripts."""
        self.bookmarks = bookmark_paths
        
        if bookmark_paths:
            # Create bookmarks panel if it doesn't exist
            if self.bookmarks_panel is None:
                self.bookmarks_panel = BookmarksPanel(self)
                self.bookmarks_panel.script_run_requested.connect(self._on_bookmark_run)
                self.bookmarks_panel.set_host(self.host)
            
            # Set the bookmarks
            self.bookmarks_panel.set_bookmarks(bookmark_paths)
            
            # Add bookmarks tab if not already present
            bookmarks_tab_index = self.tab_widget.indexOf(self.bookmarks_panel)
            if bookmarks_tab_index == -1:
                self.tab_widget.addTab(self.bookmarks_panel, "Bookmarks")
                # Always keep History tab as default (index 0)
                self.tab_widget.setCurrentIndex(0)
                # Force layout update
                self.tab_widget.updateGeometry()
                QtCore.QTimer.singleShot(0, self.updateGeometry)
        else:
            # Remove bookmarks tab if present
            if self.bookmarks_panel is not None:
                bookmarks_tab_index = self.tab_widget.indexOf(self.bookmarks_panel)
                if bookmarks_tab_index != -1:
                    # Make sure History tab is selected before removing bookmarks
                    self.tab_widget.setCurrentIndex(0)
                    self.tab_widget.removeTab(bookmarks_tab_index)
                    # Force layout update
                    self.tab_widget.updateGeometry()
                    QtCore.QTimer.singleShot(0, self.updateGeometry)
    
    def set_host(self, host):
        """Set the host software for compatibility checking."""
        self.host = host
        # Only set host on bookmarks panel if it exists
        if self.bookmarks_panel is not None:
            self.bookmarks_panel.set_host(host)
    
    def _on_bookmark_run(self, script_path):
        """Handle bookmark run request."""
        # Flash is already handled by the bookmarks panel itself
        # Get the main window (traverse up the widget hierarchy if needed)
        main_window = self.parent()
        while main_window and not hasattr(main_window, 'run_script_by_path'):
            main_window = main_window.parent()
        
        if main_window and hasattr(main_window, 'run_script_by_path'):
            # Run the script without exiting tiny mode
            main_window.run_script_by_path(script_path)
        else:
            from ...charon_logger import system_error
            system_error(f"Could not find main window to run script: {script_path}")