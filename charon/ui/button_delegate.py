from ..qt_compat import QtCore, QtWidgets, QtGui
from ..script_table_model import ScriptTableModel


class ButtonDelegate(QtWidgets.QStyledItemDelegate):
    """Delegate that draws and handles clicks for table buttons."""
    
    clicked = QtCore.Signal(QtCore.QModelIndex)
    
    def __init__(
        self,
        parent=None,
        *,
        column,
        label=None,
        enabled_role=None,
        size_hint: QtCore.QSize = QtCore.QSize(80, 30),
    ):
        super(ButtonDelegate, self).__init__(parent)
        self._pressed_index = None
        self._column = column
        self._label = label
        self._enabled_role = enabled_role
        self._size_hint = size_hint
        
    def paint(self, painter, option, index):
        """Draw a styled button without relying on the widget style."""
        if index.column() != self._column:
            super().paint(painter, option, index)
            return

        model = index.model()
        source_model = model
        source_index = index
        if hasattr(model, 'sourceModel'):
            source_model = model.sourceModel()
            source_index = model.mapToSource(index)

        is_enabled = True
        if source_model and source_index.isValid() and self._enabled_role is not None:
            can_use = source_model.data(source_index, self._enabled_role)
            if can_use is not None:
                is_enabled = bool(can_use)

        validation_state = None
        if source_model and source_index.isValid():
            validation_state = source_model.data(source_index, ScriptTableModel.ValidationStateRole)

        if self._column == ScriptTableModel.COL_VALIDATE and validation_state == "validated":
            super().paint(painter, option, index)
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

        if (
            self._column == ScriptTableModel.COL_VALIDATE
            and validation_state == "validating"
        ):
            background_color = QtGui.QColor("#FF8C00")
            text_color = QtGui.QColor("#FFFFFF")
            if not is_enabled:
                background_color = palette.mid().color()
                text_color = palette.midlight().color()
            elif opt.state & QtWidgets.QStyle.State_MouseOver:
                background_color = background_color.lighter(110)
        elif (
            self._column == ScriptTableModel.COL_VALIDATE
            and validation_state == "needs_resolve"
        ):
            background_color = QtGui.QColor("#B22222")
            text_color = QtGui.QColor("#FFFFFF")
            if not is_enabled:
                background_color = palette.mid().color()
                text_color = palette.midlight().color()
            elif opt.state & QtWidgets.QStyle.State_MouseOver:
                background_color = background_color.lighter(110)
        else:
            if opt.state & QtWidgets.QStyle.State_Selected:
                background_color = palette.highlight().color()
                text_color = palette.highlightedText().color()
            else:
                background_color = palette.button().color()
                text_color = palette.buttonText().color()

            if not is_enabled:
                background_color = palette.mid().color()
                text_color = palette.midlight().color()
            elif opt.state & QtWidgets.QStyle.State_MouseOver:
                background_color = background_color.lighter(110)

        if self._pressed_index == index:
            background_color = background_color.darker(110)

        painter.setPen(QtGui.QPen(palette.mid().color()))
        painter.setBrush(background_color)
        painter.drawRoundedRect(button_rect, 6, 6)

        button_text = self._label if self._label is not None else index.data(QtCore.Qt.DisplayRole) or ""
        if (
            self._column == ScriptTableModel.COL_VALIDATE
            and validation_state == "validated"
        ):
            text_color = QtGui.QColor(34, 139, 34)
        elif (
            self._column == ScriptTableModel.COL_VALIDATE
            and validation_state == "needs_resolve"
        ):
            text_color = QtGui.QColor("#FFFFFF")

        painter.setPen(text_color)
        painter.drawText(button_rect, QtCore.Qt.AlignCenter, button_text)
        painter.restore()

    def editorEvent(self, event, model, option, index):
        """Handle mouse events for button clicks"""
        if index.column() != self._column:
            return False
            
        # Check compatibility
        is_enabled = True
        source_model = model
        source_index = index
        
        if hasattr(model, 'sourceModel'):
            source_model = model.sourceModel()
            source_index = model.mapToSource(index)
            
        if source_model and source_index.isValid() and self._enabled_role is not None:
            can_use = source_model.data(source_index, self._enabled_role)
            is_enabled = bool(can_use) if can_use is not None else False

        if (
            self._column == ScriptTableModel.COL_VALIDATE
            and source_model
            and source_index.isValid()
            and source_model.data(source_index, ScriptTableModel.ValidationStateRole) == "validated"
        ):
            return False
                
        if not is_enabled:
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
        if index.column() == self._column:
            return self._size_hint
        return super().sizeHint(option, index)
