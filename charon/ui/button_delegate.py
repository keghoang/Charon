from ..qt_compat import QtCore, QtWidgets, QtGui
from ..utilities import is_compatible_with_host
from ..script_table_model import ScriptTableModel


class ButtonDelegate(QtWidgets.QStyledItemDelegate):
    """Delegate that draws and handles clicks for Run buttons in table"""
    
    clicked = QtCore.Signal(QtCore.QModelIndex)
    
    def __init__(self, parent=None):
        super(ButtonDelegate, self).__init__(parent)
        self._pressed_index = None
        
    def paint(self, painter, option, index):
        """Draw a styled button without relying on the widget style."""
        if index.column() != ScriptTableModel.COL_RUN:
            super().paint(painter, option, index)
            return

        source_model = index.model()
        source_index = index
        if hasattr(index.model(), 'sourceModel'):
            source_model = index.model().sourceModel()
            source_index = index.model().mapToSource(index)

        is_compatible = True
        if source_model and source_index.isValid():
            name_index = source_model.index(source_index.row(), ScriptTableModel.COL_NAME)
            can_run = source_model.data(name_index, ScriptTableModel.CanRunRole)
            is_compatible = can_run if can_run is not None else True

        if not is_compatible:
            return

        opt = QtWidgets.QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.state &= ~QtWidgets.QStyle.State_HasFocus
        if hasattr(QtWidgets.QStyle, 'State_KeyboardFocusChange'):
            opt.state &= ~QtWidgets.QStyle.State_KeyboardFocusChange
        opt.text = ''
        opt.icon = QtGui.QIcon()
        opt.features &= ~QtWidgets.QStyleOptionViewItem.HasDisplay

        style = opt.widget.style() if opt.widget else QtWidgets.QApplication.style()
        style.drawPrimitive(QtWidgets.QStyle.PE_PanelItemViewItem, opt, painter, opt.widget)

        button_rect = opt.rect.adjusted(6, 4, -6, -4)
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

        if self._pressed_index == index:
            background_color = background_color.darker(110)

        painter.setPen(QtGui.QPen(palette.mid().color()))
        painter.setBrush(background_color)
        painter.drawRoundedRect(button_rect, 6, 6)

        painter.setPen(text_color)
        painter.drawText(button_rect, QtCore.Qt.AlignCenter, 'Grab')
        painter.restore()

    def editorEvent(self, event, model, option, index):
        """Handle mouse events for button clicks"""
        if index.column() != ScriptTableModel.COL_RUN:
            return False
            
        # Check compatibility
        is_compatible = True
        source_model = model
        source_index = index
        
        if hasattr(model, 'sourceModel'):
            source_model = model.sourceModel()
            source_index = model.mapToSource(index)
            
        if source_model and source_index.isValid():
            name_index = source_model.index(source_index.row(), ScriptTableModel.COL_NAME)
            can_run = source_model.data(name_index, ScriptTableModel.CanRunRole)
            is_compatible = can_run if can_run is not None else True
                
        if not is_compatible:
            return False
            
        # Handle mouse press
        if event.type() == QtCore.QEvent.MouseButtonPress:
            if event.button() == QtCore.Qt.LeftButton:
                self._pressed_index = index
                return True
                
        # Handle mouse release
        elif event.type() == QtCore.QEvent.MouseButtonRelease:
            if event.button() == QtCore.Qt.LeftButton and self._pressed_index == index:
                self._pressed_index = None
                self.clicked.emit(index)
                return True
            self._pressed_index = None
            
        return False
        
    def sizeHint(self, option, index):
        """Provide size hint for button cells"""
        if index.column() == ScriptTableModel.COL_RUN:
            return QtCore.QSize(80, 30)
        return super().sizeHint(option, index)
