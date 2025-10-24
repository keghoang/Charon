"""
Flash Animation Utilities

Centralized flash animation logic for visual feedback when scripts are executed.
"""

from ..qt_compat import QtWidgets, QtCore, Qt


def flash_table_row(table_view, row_index, viewport_parent=None):
    """
    Flash a table row with a green highlight animation.
    
    Args:
        table_view: The QTableView or QListView to flash
        row_index: The row index to flash (int) or QModelIndex
        viewport_parent: Optional specific viewport parent (defaults to table_view.viewport())
    """
    # Handle both int and QModelIndex
    if isinstance(row_index, int):
        if row_index < 0 or row_index >= table_view.model().rowCount():
            return
        index = table_view.model().index(row_index, 0)
    else:
        index = row_index
        if not index.isValid():
            return
    
    # Get the viewport parent
    parent = viewport_parent or table_view.viewport()
    
    # Get the row's visual rect
    rect = table_view.visualRect(index)
    
    # For table views, extend rect to cover full row width
    if isinstance(table_view, QtWidgets.QTableView):
        rect.setLeft(0)
        rect.setWidth(parent.width())
    
    # Create a widget for the flash effect
    flash_widget = QtWidgets.QWidget(parent)
    flash_widget.setGeometry(rect)
    flash_widget.setAttribute(Qt.WA_TransparentForMouseEvents, True)  # Don't block mouse events
    
    # Set a semi-transparent green background using stylesheet
    flash_widget.setStyleSheet("""
        QWidget {
            background-color: rgba(100, 255, 100, 80);
            border: none;
        }
    """)
    
    flash_widget.show()
    flash_widget.raise_()  # Ensure it's on top
    
    # Create a fade-out effect using multiple steps
    def fade_step(opacity):
        if opacity <= 0:
            flash_widget.hide()
            flash_widget.deleteLater()  # Properly clean up the widget
        else:
            flash_widget.setStyleSheet(f"""
                QWidget {{
                    background-color: rgba(100, 255, 100, {opacity});
                    border: none;
                }}
            """)
            # Schedule next fade step
            QtCore.QTimer.singleShot(50, lambda: fade_step(opacity - 20))
    
    # Start fading after a brief full-opacity display
    QtCore.QTimer.singleShot(100, lambda: fade_step(60))