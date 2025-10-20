from ..qt_compat import QtWidgets, QtCore, QtGui, QShortcut, QKeySequence
from ..utilities import get_software_color_for_metadata, is_compatible_with_host, apply_incompatible_opacity, create_sort_key
from ..icon_manager import get_icon_manager
from .. import config

class QuickSearchDelegate(QtWidgets.QStyledItemDelegate):
    """Custom delegate for rendering quick search items with software icons."""
    
    def __init__(self, parent=None):
        super(QuickSearchDelegate, self).__init__(parent)
        self.icon_manager = get_icon_manager()
        self.icon_size = config.SOFTWARE_ICON_SIZE
        self.icon_spacing = 4  # Space between icons
        
    def paint(self, painter, option, index):
        """Paint the search result with text on left and software icons on right."""
        # Get data from model
        display_text = index.data(QtCore.Qt.ItemDataRole.DisplayRole)
        text_color = index.data(QtCore.Qt.ItemDataRole.ForegroundRole)
        
        # Get metadata for software icons
        if hasattr(index.model(), 'entries') and 0 <= index.row() < len(index.model().entries):
            _, _, metadata = index.model().entries[index.row()]
        else:
            metadata = None
            
        # Save painter state
        painter.save()
        
        # Draw selection/hover background
        if option.state & QtWidgets.QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
        elif option.state & QtWidgets.QStyle.StateFlag.State_MouseOver:
            painter.fillRect(option.rect, option.palette.alternateBase())
            
        # Calculate text area (leaving room for icons on right)
        text_rect = QtCore.QRect(option.rect)
        text_rect.setLeft(text_rect.left() + 12)  # Left padding
        
        # Calculate how much space we need for icons
        if metadata and 'software' in metadata:
            software_list = metadata['software']
            if isinstance(software_list, list) and software_list:
                icon_count = len(software_list)
                icons_width = (self.icon_size * icon_count) + (self.icon_spacing * (icon_count - 1))
                text_rect.setRight(text_rect.right() - icons_width - 12)  # Right padding for icons
        
        # Draw text
        if text_color:
            color = text_color.color()
            
            # Adjust color if selected
            if option.state & QtWidgets.QStyle.StateFlag.State_Selected:
                # Get the highlight color's lightness to determine contrast direction
                highlight_color = option.palette.color(QtGui.QPalette.ColorRole.Highlight)
                highlight_lightness = highlight_color.lightness()
                
                # If highlight is dark, make text lighter; if highlight is light, make text darker
                if highlight_lightness < 128:
                    # Dark highlight - make text lighter
                    color = color.lighter(200)  # 200% lighter
                else:
                    # Light highlight - make text darker
                    color = color.darker(200)  # 200% darker
            
            painter.setPen(color)
        else:
            # Use standard palette colors
            if option.state & QtWidgets.QStyle.StateFlag.State_Selected:
                painter.setPen(option.palette.highlightedText().color())
            else:
                painter.setPen(option.palette.text().color())
            
        # Use elided text if too long
        elided_text = painter.fontMetrics().elidedText(
            display_text, QtCore.Qt.TextElideMode.ElideRight, text_rect.width()
        )
        painter.drawText(text_rect, QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter, elided_text)
        
        # Draw software icons on the right
        if metadata and 'software' in metadata:
            software_list = metadata['software']
            if isinstance(software_list, list) and software_list:
                # Start from right edge
                x = option.rect.right() - 12  # Right padding
                
                # Draw icons from right to left
                for software in reversed(software_list):
                    x -= self.icon_size
                    
                    pixmap = self.icon_manager.get_icon(software)
                    if pixmap and not pixmap.isNull():
                        icon_rect = QtCore.QRect(
                            x,
                            option.rect.top() + (option.rect.height() - self.icon_size) // 2,
                            self.icon_size,
                            self.icon_size
                        )
                        
                        # Apply opacity based on compatibility
                        if hasattr(index.model(), 'host'):
                            host = index.model().host
                            is_compatible = is_compatible_with_host(metadata, host)
                            
                            if not is_compatible:
                                # Script can't run at all - use incompatible opacity
                                painter.setOpacity(config.INCOMPATIBLE_OPACITY)
                            elif software.lower() == host.lower():
                                # Software matches current host - full opacity
                                painter.setOpacity(1.0)
                            else:
                                # Software doesn't match current host - faded
                                painter.setOpacity(config.INCOMPATIBLE_OPACITY)
                        else:
                            # No host info - default to full opacity
                            painter.setOpacity(1.0)
                        
                        painter.drawPixmap(icon_rect, pixmap)
                        painter.setOpacity(1.0)  # Reset opacity
                    
                    x -= self.icon_spacing
        
        painter.restore()
        
    def sizeHint(self, option, index):
        """Return the size hint for items."""
        size = super(QuickSearchDelegate, self).sizeHint(option, index)
        size.setHeight(32)  # Fixed height to match list styling
        return size


class QuickSearchModel(QtCore.QAbstractListModel):
    """Custom model for quick search that supports colored text."""
    
    def __init__(self, parent=None):
        super(QuickSearchModel, self).__init__(parent)
        self.entries = []  # List of (display, path, metadata) tuples
        self.host = "None"  # Store host for software selection
    
    def rowCount(self, parent=QtCore.QModelIndex()):
        return len(self.entries)
    
    def data(self, index, role):
        if not index.isValid():
            return None
        
        if role == QtCore.Qt.ItemDataRole.DisplayRole:
            display, _, _ = self.entries[index.row()]
            return display
        
        if role == QtCore.Qt.ItemDataRole.ForegroundRole:
            _, _, metadata = self.entries[index.row()]
            base_color = get_software_color_for_metadata(metadata, self.host)
            
            # Check if script is compatible with current host
            is_compatible = is_compatible_with_host(metadata, self.host)
            
            if is_compatible:
                return QtGui.QBrush(QtGui.QColor(base_color))
            else:
                # Apply opacity to incompatible scripts while preserving base color
                color = QtGui.QColor(base_color)
                return QtGui.QBrush(apply_incompatible_opacity(color))
        
        return None
    
    def update_entries(self, entries):
        """Update the model with new entries."""
        self.beginResetModel()
        self.entries = entries
        self.endResetModel()
    
    def set_host(self, host):
        """Set the host software for proper software selection."""
        self.host = host

class QuickSearchDialog(QtWidgets.QDialog):
    """Dynamic popup dialog that starts minimal and grows with search results."""

    script_chosen = QtCore.Signal(str)  # Emits full script path when accepted
    script_executed = QtCore.Signal(str)  # Emits script path to execute in tiny mode

    def __init__(self, all_scripts, parent=None, host="None", tiny_mode=False):
        """
        all_scripts: List[Tuple[str display, str full_path, dict metadata]]
        host: Current host software for proper software selection
        tiny_mode: If True, executes scripts instead of navigating to them
        """
        super(QuickSearchDialog, self).__init__(parent)
        # Remove title bar and make it frameless
        self.setWindowFlags(QtCore.Qt.WindowType.FramelessWindowHint | QtCore.Qt.WindowType.Popup)
        self.setModal(True)
        self.all_scripts = all_scripts  # raw data list
        self.host = host
        self.tiny_mode = tiny_mode
        
        # Add a shortcut to close the dialog with the same quick search hotkey
        # Different contexts needed for normal vs tiny mode
        if parent and hasattr(parent, 'keybind_manager'):
            from ..settings import user_settings_db
            local_keybinds = user_settings_db.get_or_create_local_keybinds()
            if 'quick_search' in local_keybinds and local_keybinds['quick_search']['enabled']:
                # Only add close shortcut in normal mode
                # In tiny mode, the main window's global detection handles it
                if not tiny_mode:
                    key_seq = local_keybinds['quick_search']['key_sequence']
                    close_shortcut = QShortcut(QKeySequence(key_seq), self)
                    close_shortcut.setContext(QtCore.Qt.ShortcutContext.WindowShortcut)
                    close_shortcut.activated.connect(self.close)
        

        # Set a fixed width, but let height be dynamic
        self.base_width = 350
        self.input_height = 35
        self.setFixedWidth(self.base_width)

        # Main layout with minimal margins
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)  # Minimal border
        layout.setSpacing(0)

        # Search input with theme-neutral styling
        self.search_edit = QtWidgets.QLineEdit(self)
        placeholder_text = "Search and Run" if self.tiny_mode else "Search"
        self.search_edit.setPlaceholderText(placeholder_text)
        self.search_edit.setStyleSheet("""
            QLineEdit {
                border: 1px solid palette(mid);
                border-radius: 3px;
                padding: 8px 12px;
                background: palette(base);
                color: palette(text);
            }
            QLineEdit:focus {
                border: 1px solid palette(highlight);
                outline: none;
            }
        """)
        layout.addWidget(self.search_edit)

        # Results container (always present but hidden when empty)
        self.results_container = QtWidgets.QWidget(self)
        self.results_container.hide()  # Start hidden
        
        results_layout = QtWidgets.QVBoxLayout(self.results_container)
        results_layout.setContentsMargins(0, 1, 0, 0)  # Small top margin to separate from input
        results_layout.setSpacing(0)  # No spacing between elements
        
        self.list_view = QtWidgets.QListView(self.results_container)
        self.list_view.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.list_view.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.list_view.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.list_view.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_view.setFrameStyle(QtWidgets.QFrame.Shape.NoFrame)
        self.list_view.setStyleSheet("""
            QListView {
                background: palette(base);
                border: 1px solid palette(mid);
                border-top: none;
                border-radius: 0px 0px 3px 3px;
                outline: none;
                color: palette(text);
                selection-background-color: palette(highlight);
                selection-color: palette(highlighted-text);
            }
            QListView::item {
                padding: 6px 12px;
                border-bottom: 1px solid palette(light);
            }
            QListView::item:hover {
                background: palette(alternate-base);
            }
            QListView::item:selected {
                background: palette(highlight);
                color: palette(highlighted-text);
            }
        """)
        results_layout.addWidget(self.list_view)
        layout.addWidget(self.results_container)

        self.model = QuickSearchModel()
        self.model.set_host(self.host)  # Set the host for proper software selection
        self.list_view.setModel(self.model)
        
        # Set custom delegate for software icons
        self.delegate = QuickSearchDelegate(self)
        self.list_view.setItemDelegate(self.delegate)

        self.search_edit.textChanged.connect(self.on_text_changed)
        self.list_view.doubleClicked.connect(self.accept)

        # key navigation
        self.search_edit.installEventFilter(self)
        self.list_view.installEventFilter(self)

        self.search_edit.setFocus()

        # Let the dialog size itself initially to fit just the search box
        self.adjustSize()
        
    def _normalize_search_string(self, text):
        """Removes separators and converts to lowercase for consistent searching."""
        return text.lower().replace('-', '').replace('_', '').replace(' ', '')

    # ---------- helpers ----------
    def update_list(self, entries):
        """Update the model and adjust the dialog size for the new entries."""
        self.entries = entries
        self.model.update_entries(entries)
        
        self._adjust_dialog_size(len(entries))

        if entries:
            # Select first item if there are results
            self.list_view.setCurrentIndex(self.model.index(0, 0))
    
    def _adjust_dialog_size(self, item_count):
        """
        Adjusts the dialog size to fit its content, keeping the search box anchored.
        """
        if item_count > 0:
            # Show the container with a fixed height.
            fixed_results_height = 8 * 32 + 2  # 8 items * 32px/item + 2px for border
            self.results_container.setFixedHeight(fixed_results_height)
            self.results_container.show()
        else:
            # When hiding, we MUST unset the fixed height before hiding the widget.
            # This allows the layout to correctly treat it as having zero size.
            self.results_container.setMinimumHeight(0)
            self.results_container.setMaximumHeight(16777215)  # QWIDGETSIZE_MAX
            self.results_container.hide()
        
        # Ask the dialog to resize to the layout's new preferred size.
        self.adjustSize()

    def on_text_changed(self, text):
        query = self._normalize_search_string(text)
        if not query:
            self.update_list([])
            return

        filtered = []
        for disp, path, metadata in self.all_scripts:
            normalized_disp = self._normalize_search_string(disp)
            if query in normalized_disp:
                filtered.append((disp, path, metadata))

        # Sort filtered results by compatibility priority
        def quicksearch_sort_key(entry):
            display, path, metadata = entry
            # Extract script name from display text (format: "folder > script")
            if " > " in display:
                script_name = display.split(" > ")[1]
            else:
                script_name = display
            
            # Create a mock ScriptItem-like object for sorting
            class MockScriptItem:
                def __init__(self, name, metadata):
                    self.name = name
                    self.metadata = metadata
            
            mock_item = MockScriptItem(script_name, metadata)
            return create_sort_key(mock_item, self.host)
        
        filtered.sort(key=quicksearch_sort_key)
        
        self.update_list(filtered[:10])

    # ---------- event handling ----------
    def accept(self):
        idx = self.list_view.currentIndex()
        if idx.isValid():
            row = idx.row()
            from ..galt_logger import system_debug
            system_debug(f"QuickSearch accept() - row: {row}, entries count: {len(self.entries)}")
            if row < len(self.entries):
                display, path, metadata = self.entries[row]
                system_debug(f"QuickSearch entry - display: {display}, path: {path}")
            else:
                system_debug(f"QuickSearch error: row {row} out of bounds")
                return
            
            if self.tiny_mode:
                # In command mode, validate and execute
                from ..script_validator import ScriptValidator
                can_run, reason = ScriptValidator.can_execute(path, metadata, self.host)
                
                if can_run:
                    self.script_executed.emit(path)
                else:
                    # Show error message
                    QtWidgets.QMessageBox.warning(
                        self, 
                        "Cannot Execute", 
                        f"Cannot run script: {reason}"
                    )
                    return  # Don't close dialog
            else:
                # Normal mode - navigate to script
                from ..galt_logger import system_debug
                system_debug(f"QuickSearch: Emitting script_chosen with path: {path}")
                self.script_chosen.emit(path)
                
        super(QuickSearchDialog, self).accept()

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.Type.KeyPress:
            key = event.key()
            if obj is self.search_edit and key in (QtCore.Qt.Key.Key_Down, QtCore.Qt.Key.Key_Up):
                # forward to list view
                QtWidgets.QApplication.sendEvent(self.list_view, event)
                return True
            if obj is self.search_edit and key == QtCore.Qt.Key.Key_Return:
                # If list has entries, accept the currently selected one
                if self.entries:
                    self.accept()
                return True
            if obj is self.list_view and key == QtCore.Qt.Key.Key_Return:
                self.accept()
                return True
            if key in (QtCore.Qt.Key.Key_Escape, QtCore.Qt.Key.Key_Tab):
                self.reject()
                return True
        return False 