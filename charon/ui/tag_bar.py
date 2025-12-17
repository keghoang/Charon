"""Vertical tag bar widget for filtering scripts by tags."""

from ..qt_compat import QtWidgets, QtCore, QtGui
from typing import List, Set


class RotatedButton(QtWidgets.QPushButton):
    """A button that displays text rotated 90 degrees counter-clockwise."""
    
    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._text = text
        self.setCheckable(True)
        self.setFixedWidth(30)  # Narrow width for vertical bar
        
        # Calculate height based on text length
        font_metrics = QtGui.QFontMetrics(self.font())
        # Use horizontalAdvance for Qt6, width for Qt5
        if hasattr(font_metrics, 'horizontalAdvance'):
            text_width = font_metrics.horizontalAdvance(text) + 20  # Add padding
        else:
            text_width = font_metrics.width(text) + 20  # Add padding
        self.setFixedHeight(text_width)
        
    def paintEvent(self, event):
        """Custom paint to draw rotated text."""
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        
        # Draw button background
        option = QtWidgets.QStyleOptionButton()
        option.initFrom(self)
        option.state = QtWidgets.QStyle.StateFlag.State_Enabled
        
        if self.isChecked():
            option.state |= QtWidgets.QStyle.StateFlag.State_On
            option.state |= QtWidgets.QStyle.StateFlag.State_Sunken
        else:
            option.state |= QtWidgets.QStyle.StateFlag.State_Raised
            
        self.style().drawControl(QtWidgets.QStyle.ControlElement.CE_PushButton, option, painter, self)
        
        # Draw rotated text
        painter.save()
        
        # Set text color based on button state
        if self.isChecked():
            painter.setPen(self.palette().buttonText().color())
        else:
            painter.setPen(self.palette().text().color())
            
        # Rotate around center
        painter.translate(self.width() / 2, self.height() / 2)
        painter.rotate(-90)  # Counter-clockwise
        
        # Draw text centered
        rect = QtCore.QRect(-self.height() / 2, -self.width() / 2, 
                           self.height(), self.width())
        painter.drawText(rect, QtCore.Qt.AlignmentFlag.AlignCenter, self._text)
        
        painter.restore()
        
    def sizeHint(self):
        """Return size hint for the button."""
        return QtCore.QSize(30, 100)
        
        
class TagBar(QtWidgets.QWidget):
    """Vertical bar containing tag filter buttons."""
    
    tags_changed = QtCore.Signal(list)  # Emits list of active tag names
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(35)  # Slightly wider than buttons for margins
        
        # Ensure the widget background blends with parent
        self.setAutoFillBackground(False)
        
        # Track buttons
        self._tag_buttons = {}  # tag_name -> button
        self._active_tags = set()
        
        # Create layout
        self.layout = QtWidgets.QVBoxLayout(self)
        # Add top margin to align with table headers (accounting for panel title)
        self.layout.setContentsMargins(2, 0, 2, 2)
        self.layout.setSpacing(4)
        
        # Scroll area for dynamic tags
        self.scroll_area = QtWidgets.QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Remove frame/border from scroll area
        self.scroll_area.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        
        # Container for tag buttons
        self.tag_container = QtWidgets.QWidget()
        self.tag_layout = QtWidgets.QVBoxLayout(self.tag_container)
        self.tag_layout.setContentsMargins(0, 0, 0, 0)
        self.tag_layout.setSpacing(4)
        
        self.scroll_area.setWidget(self.tag_container)
        self.layout.addWidget(self.scroll_area, 1)  # Take remaining space
        
        # Add stretch at bottom
        self.tag_layout.addStretch()
        
    def update_tags(self, available_tags: List[str]):
        """Update the available tags based on current folder's scripts."""
        # Clear existing tag buttons more thoroughly
        for button in self._tag_buttons.values():
            self.tag_layout.removeWidget(button)
            button.setParent(None)
            button.deleteLater()
        self._tag_buttons.clear()
        
        # Process events to ensure buttons are actually deleted
        QtWidgets.QApplication.processEvents()
        
        # Sort tags alphabetically and ensure uniqueness
        sorted_tags = sorted(set(available_tags))
        
        # Create new buttons
        for tag in sorted_tags:
            if tag:  # Skip empty tags
                button = RotatedButton(tag, self)
                button.toggled.connect(lambda checked, t=tag: self._on_tag_toggled(t, checked))
                self.tag_layout.insertWidget(self.tag_layout.count() - 1, button)  # Before stretch
                self._tag_buttons[tag] = button
                
        # Clear active tags
        self._active_tags.clear()
        self.tags_changed.emit([])  # Empty list means show all
        
    def _on_tag_toggled(self, tag: str, checked: bool):
        """Handle individual tag toggle."""
        if checked:
            self._active_tags.add(tag)
        else:
            self._active_tags.discard(tag)
            
        # Emit the current active tags (empty list means show all)
        self.tags_changed.emit(list(self._active_tags))
            
    def get_active_tags(self) -> List[str]:
        """Get list of currently active tags."""
        return list(self._active_tags)
        
    def clear_selection(self):
        """Clear all selections."""
        for button in self._tag_buttons.values():
            button.setChecked(False)
        self._active_tags.clear()
        self.tags_changed.emit([])
    
    def add_tag(self, tag_name: str):
        """Add a single tag button if it doesn't already exist."""
        if not tag_name or tag_name in self._tag_buttons:
            return
            
        # Create new button
        button = RotatedButton(tag_name, self)
        button.toggled.connect(lambda checked, t=tag_name: self._on_tag_toggled(t, checked))
        
        # Insert in alphabetical order
        sorted_tags = sorted(list(self._tag_buttons.keys()) + [tag_name])
        insert_index = sorted_tags.index(tag_name)
        
        # Insert at the correct position (before stretch)
        self.tag_layout.insertWidget(insert_index, button)
        self._tag_buttons[tag_name] = button
    
    def remove_tag(self, tag_name: str):
        """Remove a single tag button if it exists."""
        if tag_name not in self._tag_buttons:
            return
            
        button = self._tag_buttons[tag_name]
        self.tag_layout.removeWidget(button)
        button.setParent(None)
        button.deleteLater()
        del self._tag_buttons[tag_name]
        
        # Also remove from active tags if selected
        self._active_tags.discard(tag_name)
    
    def update_tag_name(self, old_name: str, new_name: str):
        """Rename a tag button."""
        if old_name not in self._tag_buttons or new_name in self._tag_buttons:
            return
            
        # Get the old button
        old_button = self._tag_buttons[old_name]
        was_checked = old_button.isChecked()
        
        # Remove old button
        self.remove_tag(old_name)
        
        # Add new button
        self.add_tag(new_name)
        
        # Restore checked state
        if was_checked and new_name in self._tag_buttons:
            self._tag_buttons[new_name].setChecked(True)
