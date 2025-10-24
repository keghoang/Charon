from ..qt_compat import QtCore, QtWidgets, QtGui, QStyledItemDelegate, Qt, KeepAspectRatio, SmoothTransformation, AlignLeft, AlignVCenter
from ..utilities import is_compatible_with_host
import os

class RunButtonDelegate(QStyledItemDelegate):
    """A delegate that adds a 'Run' button to a list view item when selected."""
    
    runButtonClicked = QtCore.Signal(QtCore.QModelIndex)

    def __init__(self, parent=None, host="None"):
        super(RunButtonDelegate, self).__init__(parent)
        self.host = host

    def set_host(self, host):
        self.host = host

    def sizeHint(self, option, index):
        """Override to set custom item height."""
        size = super(RunButtonDelegate, self).sizeHint(option, index)
        size.setHeight(25)  # Set item height to 30 pixels
        return size

    def paint(self, painter, option, index):
        """Paint the item and draw a consistent Run button."""
        opt = QtWidgets.QStyleOptionViewItem(option)
        opt.state &= ~QtWidgets.QStyle.State_KeyboardFocusChange
        opt.state &= ~QtWidgets.QStyle.State_HasFocus
        super(RunButtonDelegate, self).paint(painter, opt, index)

        if not self._is_compatible(index):
            return

        button_rect = self.get_button_rect(opt)
        palette = opt.palette

        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

        if opt.state & QtWidgets.QStyle.State_Selected:
            background_color = palette.highlight().color()
            text_color = palette.highlightedText().color()
        else:
            background_color = palette.button().color()
            text_color = palette.buttonText().color()

        if opt.state & QtWidgets.QStyle.State_MouseOver:
            background_color = background_color.lighter(110)

        border_color = palette.mid().color()
        painter.setPen(QtGui.QPen(border_color))
        painter.setBrush(background_color)
        drawn_rect = button_rect.adjusted(1, 1, -1, -1)
        painter.drawRoundedRect(drawn_rect, 4, 4)

        painter.setPen(text_color)
        painter.drawText(drawn_rect, Qt.AlignCenter, "Run")
        painter.restore()

    def editorEvent(self, event, model, option, index):
        """Handle mouse events to make the button clickable."""
        if event.type() == QtCore.QEvent.MouseButtonRelease and event.button() == QtCore.Qt.LeftButton:
            button_rect = self.get_button_rect(option)
            if button_rect.contains(event.pos()):
                if self._is_compatible(index):
                    self.runButtonClicked.emit(index)
                return True
        
        return super(RunButtonDelegate, self).editorEvent(event, model, option, index)

    def _is_compatible(self, index):
        """Check if script is compatible with current host."""
        if not index.isValid():
            return False
        
        # Get script from model
        model = index.model()
        if hasattr(model, 'mapToSource'):
            source_index = model.mapToSource(index)
            source_model = model.sourceModel()
            if hasattr(source_model, 'scripts') and source_index.row() < len(source_model.scripts):
                script = source_model.scripts[source_index.row()]
            else:
                return False
        else:
            if hasattr(model, 'scripts') and index.row() < len(model.scripts):
                script = model.scripts[index.row()]
            else:
                return False
        
        # Use centralized compatibility checking
        return is_compatible_with_host(script.metadata, self.host)

    def get_button_rect(self, option):
        """Calculate the geometry for the button."""
        button_width = 60
        button_height = 20  # Changed from 20 to 25 for taller button
        # Position the button on the far right, vertically centered
        x = option.rect.right() - button_width - 5  # 5px padding from the right edge
        y = option.rect.top() + (option.rect.height() - button_height) // 2
        return QtCore.QRect(x, y, button_width, button_height)


class ScriptNameDelegate(QStyledItemDelegate):
    """Delegate that displays software logo icons inline with script names"""
    
    def __init__(self, parent=None):
        super(ScriptNameDelegate, self).__init__(parent)
        self.custom_icon_cache = {}  # Cache for script-specific icons
        self.custom_icon_size = QtCore.QSize(14, 14)  # Icon dimensions for custom script icons
        self.text_padding = 4  # Padding between icon and text
    
    def clear_icon_cache(self):
        """Clear the custom icon cache"""
        self.custom_icon_cache.clear()
        
    def _get_cached_custom_icon(self, script_path):
        """Get custom icon from script folder or cache it"""
        if script_path not in self.custom_icon_cache:
            # Check validation cache first to avoid file I/O
            from ..cache_manager import get_cache_manager
            cache_manager = get_cache_manager()
            cached_validation = cache_manager.get_script_validation(script_path)
            
            icon_found = False
            icon_path = None
            
            # Check cache for icon info
            if cached_validation and 'has_icon' in cached_validation:
                if cached_validation['has_icon'] and 'icon_path' in cached_validation:
                    icon_path = cached_validation['icon_path']
                    icon_found = True
                else:
                    # Cache says no icon
                    self.custom_icon_cache[script_path] = None
                    return None
            else:
                # Not in cache, check file system and update cache
                validation_update = {}
                for icon_name in ["icon.png", "icon.jpg"]:
                    test_path = os.path.join(script_path, icon_name)
                    if os.path.exists(test_path):
                        icon_path = test_path
                        icon_found = True
                        validation_update['has_icon'] = True
                        validation_update['icon_path'] = icon_path
                        break
                
                if not icon_found:
                    validation_update['has_icon'] = False
                
                # Update validation cache with icon info
                if cached_validation:
                    cached_validation.update(validation_update)
                    cache_manager.cache_script_validation(script_path, cached_validation)
                else:
                    # Create minimal validation entry for icon
                    import time
                    validation_update['validation_time'] = time.time()
                    cache_manager.cache_script_validation(script_path, validation_update)
            
            # Load the icon if found
            if icon_found and icon_path:
                pixmap = QtGui.QPixmap(icon_path)
                if not pixmap.isNull():
                    # Center crop to square if not already square
                    width = pixmap.width()
                    height = pixmap.height()
                    if width != height:
                        # Crop to square from center
                        size = min(width, height)
                        x = (width - size) // 2
                        y = (height - size) // 2
                        pixmap = pixmap.copy(x, y, size, size)
                    
                    # Scale to desired size with smooth transformation
                    pixmap = pixmap.scaled(self.custom_icon_size, KeepAspectRatio, SmoothTransformation)
                    self.custom_icon_cache[script_path] = pixmap
                    return pixmap
                        
            # No custom icon found
            self.custom_icon_cache[script_path] = None
                
        return self.custom_icon_cache[script_path]
        
    def paint(self, painter, option, index):
        """Paint the icon and text together"""
        # Initialize the style option
        opt = QtWidgets.QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        
        # Save painter state
        painter.save()
        
        # Get the model and script data
        model = index.model()
        from ..script_table_model import ScriptTableModel
        
        # Handle proxy models
        source_model = model
        source_index = index
        if hasattr(model, 'sourceModel'):
            source_model = model.sourceModel()
            source_index = model.mapToSource(index)
        
        # Draw the background
        style = opt.widget.style() if opt.widget else QtWidgets.QApplication.style()
        style.drawPrimitive(QtWidgets.QStyle.PE_PanelItemViewItem, opt, painter, opt.widget)
        
        # Get the display text
        display_text = model.data(index, QtCore.Qt.DisplayRole)
        if not display_text:
            painter.restore()
            return
            
        # Get script
        script = source_model.data(source_index, ScriptTableModel.ScriptRole)
                
        # Calculate content rect (accounting for padding)
        content_rect = opt.rect.adjusted(4, 0, -4, 0)
        
        # Check for custom script icon
        custom_icon_offset = 0
        if script and script.path:
            custom_pixmap = self._get_cached_custom_icon(script.path)
            if custom_pixmap:
                # Calculate icon position (vertically centered)
                icon_y = content_rect.top() + (content_rect.height() - self.custom_icon_size.height()) // 2
                icon_rect = QtCore.QRect(content_rect.left(), icon_y, self.custom_icon_size.width(), self.custom_icon_size.height())
                painter.drawPixmap(icon_rect, custom_pixmap)
                custom_icon_offset = self.custom_icon_size.width() + self.text_padding
        
        # Adjust content rect for custom icon
        text_content_rect = content_rect.adjusted(custom_icon_offset, 0, 0, 0)
        
        # Get text color from model
        text_color = model.data(index, QtCore.Qt.ForegroundRole)
        if text_color:
            color = text_color.color()
            
            # Adjust color if selected
            if opt.state & QtWidgets.QStyle.State_Selected:
                # Get the highlight color's lightness to determine contrast direction
                highlight_color = opt.palette.color(QtGui.QPalette.Highlight)
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
            if opt.state & QtWidgets.QStyle.State_Selected:
                painter.setPen(opt.palette.color(QtGui.QPalette.HighlightedText))
            else:
                painter.setPen(opt.palette.color(QtGui.QPalette.Text))
            
        # Draw text
        painter.drawText(text_content_rect, AlignLeft | AlignVCenter, display_text)
        
        painter.restore()
        
    def sizeHint(self, option, index):
        """Provide size hint that accounts for icon"""
        size = super(ScriptNameDelegate, self).sizeHint(option, index)
        # Ensure minimum height for custom icon
        size.setHeight(max(size.height(), self.custom_icon_size.height() + 4))
        return size


