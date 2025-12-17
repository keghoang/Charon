"""
Execution History Panel for Galt

Shows recent script executions with status indicators and detailed popup on double-click.
"""

from ..qt_compat import (QtWidgets, QtCore, QtGui, Qt, UserRole, ToolTipRole, 
                         DisplayRole, WindowContextHelpButtonHint, WindowCloseButtonHint, PointingHandCursor,
                         AlignBottom, AlignRight, SingleSelection)
from ..execution.result import ExecutionStatus, ExecutionResult
import os

# Import config with fallback
try:
    from .. import config
except ImportError:
    # Fallback for CLI usage
    class FallbackConfig:
        EXECUTION_DIALOG_WIDTH = 600
        EXECUTION_DIALOG_HEIGHT = 400
        EXECUTION_DIALOG_OUTPUT_HEIGHT = 200
        UI_SMALL_BUTTON_WIDTH = 60
        UI_ICON_FONT_FAMILY = "Segoe UI"
    config = FallbackConfig()
from typing import List, Optional


class ExecutionHistoryItem:
    """Represents a single execution history item"""
    
    def __init__(self, execution_id: str, script_path: str, result: ExecutionResult):
        self.execution_id = execution_id
        self.script_path = script_path
        self.script_name = os.path.basename(script_path)
        self.result = result
        self.timestamp = result.start_time
    
    def get_status_icon(self) -> str:
        """Get the status icon for this execution"""
        if self.result.status == ExecutionStatus.COMPLETED:
            return "✅"
        elif self.result.status == ExecutionStatus.FAILED:
            return "❌"
        elif self.result.status == ExecutionStatus.CANCELLED:
            return "⏹️"
        elif self.result.status == ExecutionStatus.RUNNING:
            return "⏳"
        elif self.result.status == ExecutionStatus.PENDING:
            return "🕐"  # Clock icon for pending/queued executions
        else:
            return "❓"
    
    def get_display_text(self) -> str:
        """Get the display text for this execution, including duration if available"""
        icon = self.get_status_icon()
        # Calculate duration if possible
        duration = None
        if self.result.status != ExecutionStatus.RUNNING and self.result.end_time and self.result.start_time:
            duration = self.result.end_time - self.result.start_time
        elif self.result.status == ExecutionStatus.RUNNING and self.result.start_time:
            import time
            duration = time.time() - self.result.start_time
        if duration is not None:
            return f"{icon} {self.script_name} ({duration:.1f}s)"
        else:
            return f"{icon} {self.script_name}"
    
    def get_tooltip(self) -> str:
        """Get tooltip text for this execution"""
        if self.result.status == ExecutionStatus.RUNNING:
            # For running scripts, show elapsed time
            import time
            elapsed = time.time() - self.result.start_time
            status_text = self.result.status.value.title()
            return f"{self.script_name}\nStatus: {status_text}\nElapsed: {elapsed:.1f}s"
        else:
            # For completed scripts, show total duration
            duration = self.result.end_time - self.result.start_time if self.result.end_time else 0
            status_text = self.result.status.value.title()
            return f"{self.script_name}\nStatus: {status_text}\nDuration: {duration:.1f}s"
    
    def update_result(self, new_result: ExecutionResult):
        """Update the result for this execution"""
        # Preserve live_output if it exists
        if hasattr(self.result, 'live_output'):
            # If the new result doesn't have output, use the live_output
            if not new_result.output:
                new_result.output = self.result.live_output
            # Also preserve live_output on the new result for consistency
            new_result.live_output = self.result.live_output
        self.result = new_result
    
    def append_output(self, output_chunk: str):
        """Append output chunk to the current result"""
        if not hasattr(self.result, 'live_output'):
            self.result.live_output = ""
        self.result.live_output += output_chunk


class ExecutionHistoryModel(QtCore.QAbstractListModel):
    """Qt model for execution history"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._history: List[ExecutionHistoryItem] = []
        self._max_items = config.EXECUTION_HISTORY_MAX_ITEMS
    
    def add_execution(self, execution_id: str, script_path: str, result: ExecutionResult):
        """Add a new execution to the history"""
        item = ExecutionHistoryItem(execution_id, script_path, result)
        
        # Check if we need to remove items before inserting
        items_to_remove = max(0, len(self._history) + 1 - self._max_items)
        
        # Remove excess items from the end first
        if items_to_remove > 0:
            self.beginRemoveRows(QtCore.QModelIndex(), 
                               len(self._history) - items_to_remove, 
                               len(self._history) - 1)
            self._history = self._history[:-items_to_remove]
            self.endRemoveRows()
        
        # Insert at the beginning (most recent first)
        self.beginInsertRows(QtCore.QModelIndex(), 0, 0)
        self._history.insert(0, item)
        self.endInsertRows()

    def has_execution(self, execution_id: str) -> bool:
        """Check if an execution already exists in history"""
        return any(item.execution_id == execution_id for item in self._history)

    def update_execution(self, execution_id: str, result: ExecutionResult):
        """Update an existing execution with a new result"""
        for i, item in enumerate(self._history):
            if item.execution_id == execution_id:
                item.update_result(result)
                self.dataChanged.emit(self.index(i, 0), self.index(i, 0))
                return

    def update_execution_output(self, execution_id: str, output_chunk: str):
        """Update the output for a specific execution"""
        # Find the execution by ID (regardless of status)
        for i, existing_item in enumerate(self._history):
            if existing_item.execution_id == execution_id:
                # Append the output chunk
                existing_item.append_output(output_chunk)
                # Notify the view that this row has changed
                self.dataChanged.emit(self.index(i, 0), self.index(i, 0))
                return
    
    def clear_history(self):
        """Clear all history"""
        self.beginResetModel()
        self._history.clear()
        self.endResetModel()
    
    def rowCount(self, parent=QtCore.QModelIndex()):
        return len(self._history)
    
    def data(self, index, role=DisplayRole):
        if not index.isValid() or index.row() >= len(self._history):
            return None
        
        item = self._history[index.row()]
        
        if role == DisplayRole:
            return item.get_display_text()
        elif role == ToolTipRole:
            return item.get_tooltip()
        elif role == UserRole:
            return item
        
        return None


class ExecutionDetailsDialog(QtWidgets.QDialog):
    """Dialog showing detailed execution information"""
    
    def __init__(self, history_item: ExecutionHistoryItem, parent=None):
        super().__init__(parent)
        self.history_item = history_item
        self.update_timer = None
        self.setup_ui()
        self.populate_data()
        
        # Start timer if script is running
        if self.history_item.result.status == ExecutionStatus.RUNNING:
            self.start_update_timer()
    
    def setup_ui(self):
        """Setup the dialog UI"""
        self.setWindowTitle(f"Script Details: {self.history_item.script_name} (ID: {self.history_item.execution_id[:8]}...)")
        self.setWindowModality(Qt.NonModal)
        
        # Remove the "?" button from the window
        self.setWindowFlag(WindowContextHelpButtonHint, False)
        self.setWindowFlag(WindowCloseButtonHint, True)
        
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(2)  # Minimal spacing between rows
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Status row
        status_layout = QtWidgets.QHBoxLayout()
        status_layout.setSpacing(6)
        status_label_text = QtWidgets.QLabel("Status:")
        status_label_text.setStyleSheet("font-weight: bold;")
        status_layout.addWidget(status_label_text)
        
        self.status_icon = QtWidgets.QLabel(self.history_item.get_status_icon())
        self.status_icon.setStyleSheet("font-size: 14px;")  # Slightly smaller icon
        status_layout.addWidget(self.status_icon)
        
        self.status_text = QtWidgets.QLabel(self.history_item.result.status.value.title())
        status_layout.addWidget(self.status_text)
        status_layout.addStretch()
        layout.addLayout(status_layout)
        
        # Duration row
        duration_layout = QtWidgets.QHBoxLayout()
        duration_layout.setSpacing(6)
        duration_label_text = QtWidgets.QLabel("Duration:")
        duration_label_text.setStyleSheet("font-weight: bold;")
        duration_layout.addWidget(duration_label_text)
        
        duration = self.history_item.result.end_time - self.history_item.result.start_time if self.history_item.result.end_time else 0
        self.duration_value = QtWidgets.QLabel(f"{duration:.1f}s")
        duration_layout.addWidget(self.duration_value)
        duration_layout.addStretch()
        layout.addLayout(duration_layout)
        
        # Script row
        script_layout = QtWidgets.QHBoxLayout()
        script_layout.setSpacing(6)
        script_label_text = QtWidgets.QLabel("Script:")
        script_label_text.setStyleSheet("font-weight: bold;")
        script_layout.addWidget(script_label_text)
        
        script_value = QtWidgets.QLabel(self.history_item.script_name)
        script_layout.addWidget(script_value)
        script_layout.addStretch()
        layout.addLayout(script_layout)
        
        # Small spacing before output
        layout.addSpacing(8)
        
        self.content_text = QtWidgets.QTextEdit()
        self.content_text.setReadOnly(True)
        # Remove maximum height to let output panel use available space
        
        # Set monospace font that works across Windows and Mac
        # Consolas is default on Windows, Menlo on Mac, fallback to monospace
        font = QtGui.QFont()
        font.setFamily("Consolas, Menlo, Monaco, 'Courier New', monospace")
        font.setFixedPitch(True)
        font.setStyleHint(QtGui.QFont.TypeWriter)
        # Force a reasonable size even if Maya/Nuke try to override
        font.setPointSize(10)
        self.content_text.setFont(font)
        
        # Also ensure the font is applied via stylesheet for extra enforcement
        self.content_text.setStyleSheet("""
            QTextEdit {
                font-family: Consolas, Menlo, Monaco, 'Courier New', monospace;
                font-size: 10pt;
            }
        """)
        
        layout.addWidget(self.content_text, 1)  # Give stretch factor to output panel
        
        # Buttons
        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addStretch()
        
        self.copy_button = QtWidgets.QPushButton("Copy to Clipboard")
        self.copy_button.clicked.connect(self.copy_to_clipboard)
        button_layout.addWidget(self.copy_button)
        
        self.open_folder_button = QtWidgets.QPushButton("Open Folder")
        self.open_folder_button.clicked.connect(self.open_folder)
        button_layout.addWidget(self.open_folder_button)
        
        
        layout.addLayout(button_layout)
    
    def populate_data(self):
        """Populate the dialog with execution data"""
        if self.history_item.result.status == ExecutionStatus.COMPLETED:
            # Show output if available (prefer output, fallback to live_output)
            content = self.history_item.result.output
            if not content and hasattr(self.history_item.result, 'live_output'):
                content = self.history_item.result.live_output
            if not content:
                content = ""  # Show empty if no output
        elif self.history_item.result.status == ExecutionStatus.RUNNING:
            # Show live output if available
            if hasattr(self.history_item.result, 'live_output'):
                content = self.history_item.result.live_output or "Script is running..."
            else:
                content = "Script is running..."
        else:
            # Show error message
            content = self.history_item.result.error_message or "Unknown error occurred."
        
        # Set content directly without timing info
        self.content_text.setPlainText(content)
    
    def update_content(self):
        """Update the dialog content with latest data"""
        # Update status
        self.status_icon.setText(self.history_item.get_status_icon())
        self.status_text.setText(self.history_item.result.status.value.title())
        
        # Update duration
        if self.history_item.result.status == ExecutionStatus.RUNNING:
            # For running scripts, calculate elapsed time
            import time
            elapsed = time.time() - self.history_item.result.start_time
            self.duration_value.setText(f"{elapsed:.1f}s")
        else:
            # For completed scripts, use the final duration
            duration = self.history_item.result.end_time - self.history_item.result.start_time if self.history_item.result.end_time else 0
            self.duration_value.setText(f"{duration:.1f}s")
        
        # Update output content
        self.populate_data()
        
        # Manage timer based on status
        if self.history_item.result.status == ExecutionStatus.RUNNING:
            # Ensure timer is running
            if not self.update_timer:
                self.start_update_timer()
        else:
            # Script finished, stop timer
            self.stop_update_timer()
    
    def copy_to_clipboard(self):
        """Copy content to clipboard"""
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(self.content_text.toPlainText())
    
    def open_folder(self):
        """Open the script folder"""
        import os
        folder_path = self.history_item.script_path
        if os.path.exists(folder_path):
            # Cross-platform file opening
            import platform
            import subprocess
            
            if platform.system() == "Windows":
                os.startfile(folder_path)
            elif platform.system() == "Darwin":  # macOS
                subprocess.run(["open", folder_path])
            else:  # Linux
                subprocess.run(["xdg-open", folder_path])
    
    def start_update_timer(self):
        """Start timer to update duration for running scripts"""
        if self.update_timer is None:
            self.update_timer = QtCore.QTimer(self)
            self.update_timer.timeout.connect(self.update_duration_only)
            self.update_timer.start(100)  # Update every 100ms for smooth updates
    
    def stop_update_timer(self):
        """Stop the update timer"""
        if self.update_timer:
            self.update_timer.stop()
            self.update_timer.deleteLater()
            self.update_timer = None
    
    def update_duration_only(self):
        """Update only the duration field (for timer updates)"""
        if self.history_item.result.status == ExecutionStatus.RUNNING:
            import time
            elapsed = time.time() - self.history_item.result.start_time
            self.duration_value.setText(f"{elapsed:.1f}s")
        else:
            # Script finished, stop the timer
            self.stop_update_timer()
    
    def closeEvent(self, event):
        """Clean up timer when dialog closes"""
        self.stop_update_timer()
        super().closeEvent(event)


class ExecutionHistoryPanel(QtWidgets.QWidget):
    """Panel showing execution history"""
    
    execution_selected = QtCore.Signal(ExecutionHistoryItem)  # Signal when execution is selected
    collapse_requested = QtCore.Signal()  # Emitted when collapse button clicked
    
    def __init__(self, parent=None, show_collapse_button=True, show_header_label=True):
        super().__init__(parent)
        self.open_dialogs = {}  # Track open execution detail dialogs
        self.show_collapse_button = show_collapse_button
        self.show_header_label = show_header_label
        self.setup_ui()
    
    def setup_ui(self):
        """Setup the panel UI"""
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        
        # Import config for standardized header height
        from .. import config
        
        # Only add header if we're showing something
        if self.show_collapse_button or self.show_header_label:
            # Header with optional collapse button and title - standardized height
            header_container = QtWidgets.QWidget()
            header_container.setFixedHeight(config.UI_PANEL_HEADER_HEIGHT)
            header_layout = QtWidgets.QHBoxLayout(header_container)
            header_layout.setContentsMargins(0, 0, 0, 0)
            
            # Create collapse button only if requested
            if self.show_collapse_button:
                self.collapse_button = QtWidgets.QPushButton(">>")
                self.collapse_button.setStyleSheet("""
                    QPushButton {
                        color: palette(mid);
                        background-color: transparent;
                        border: none;
                        padding: 0px 4px;
                        font-size: 12px;
                    }
                    QPushButton:hover {
                        background-color: palette(midlight);
                        border-radius: 2px;
                    }
                """)
                self.collapse_button.setCursor(PointingHandCursor)
                header_layout.addWidget(self.collapse_button)
                # Connect collapse button
                self.collapse_button.clicked.connect(self.collapse_requested.emit)
            
            if self.show_header_label:
                header_layout.addWidget(QtWidgets.QLabel("History"))
            header_layout.addStretch()
            
            layout.addWidget(header_container)
        
        # Create container for history list and floating button
        container = QtWidgets.QWidget()
        container_layout = QtWidgets.QGridLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        
        # History list
        self.history_model = ExecutionHistoryModel(self)
        self.history_view = QtWidgets.QListView()
        self.history_view.setModel(self.history_model)
        self.history_view.setSelectionMode(SingleSelection)
        self.history_view.doubleClicked.connect(self.on_execution_double_clicked)
        
        # Enable text eliding for narrow widths
        self.history_view.setTextElideMode(Qt.ElideRight)
        self.history_view.setWordWrap(False)
        
        # Set font for better icon display
        font = self.history_view.font()
        font.setFamily(config.UI_ICON_FONT_FAMILY)
        self.history_view.setFont(font)
        
        # Add history view to grid layout
        container_layout.addWidget(self.history_view, 0, 0, 1, 1)
        
        # Create clear button as floating overlay
        self.clear_button = QtWidgets.QPushButton("Clear")
        # Don't set maximum width - let it adapt to container
        self.clear_button.clicked.connect(self.clear_history)
        self.clear_button.setStyleSheet("""
            QPushButton {
                background-color: palette(button);
                border: 1px solid palette(mid);
                border-radius: 2px;
                padding: 2px 4px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: palette(midlight);
            }
        """)
        
        # Position button at bottom-right
        container_layout.addWidget(self.clear_button, 0, 0, AlignBottom | AlignRight)
        self.clear_button.raise_()  # Ensure button is on top
        
        layout.addWidget(container)
    
    def add_execution(self, execution_id: str, script_path: str, result: ExecutionResult):
        """Add a new execution to the history"""
        self.history_model.add_execution(execution_id, script_path, result)
    
    def has_execution(self, execution_id: str) -> bool:
        """Check if an execution already exists in history"""
        return self.history_model.has_execution(execution_id)

    def update_execution(self, execution_id: str, result: ExecutionResult):
        """Update an existing execution"""
        self.history_model.update_execution(execution_id, result)
        
        # Update any open dialogs for this execution
        if execution_id in self.open_dialogs:
            dialog = self.open_dialogs[execution_id]
            if dialog.isVisible():
                dialog.update_content()
    
    def clear_history(self):
        """Clear the execution history"""
        self.history_model.clear_history()
    
    def update_execution_output(self, execution_id: str, output_chunk: str):
        """Update the output for a running execution"""
        self.history_model.update_execution_output(execution_id, output_chunk)
        
        # Update any open dialogs for this script
        if execution_id in self.open_dialogs:
            dialog = self.open_dialogs[execution_id]
            if dialog.isVisible():
                dialog.update_content()
    
    def on_execution_double_clicked(self, index):
        """Handle double-click on execution item"""
        if not index.isValid():
            return
        
        history_item = self.history_model.data(index, UserRole)
        if history_item:
            # Check if dialog already exists for this execution
            if history_item.execution_id in self.open_dialogs:
                # Bring existing dialog to front
                existing_dialog = self.open_dialogs[history_item.execution_id]
                existing_dialog.raise_()
                existing_dialog.activateWindow()
                return
            
            # Create new dialog with a copy of the history item to avoid shared references
            # Actually, we want to keep the reference so updates work
            dialog = ExecutionDetailsDialog(history_item, self)
            dialog.resize(config.EXECUTION_DIALOG_WIDTH, config.EXECUTION_DIALOG_HEIGHT)
            
            # Track the dialog for live updates
            self.open_dialogs[history_item.execution_id] = dialog
            
            # Connect dialog close to remove from tracking
            dialog.finished.connect(lambda: self.open_dialogs.pop(history_item.execution_id, None))
            
            dialog.show() 

