from __future__ import annotations

from ..qt_compat import QtCore, QtGui, QtWidgets

# Unified palette shared across Charon UI surfaces (aligned to validation dialog).
CHARON_COLORS = {
    "bg_main": "#212529",
    "bg_card": "#17191d",
    "bg_hover": "#3f3f46",
    "text_main": "#f4f4f5",
    "text_sub": "#a1a1aa",
    "danger": "#ef4444",
    "success": "#22c55e",
    "restart": "#f97316",
    "restart_hover": "#fb923c",
    "border": "#3f3f46",
    "btn_bg": "#27272a",
    "accent": "#3b82f6",
}

FONT_FAMILY = "'Segoe UI', 'Inter', sans-serif"


def build_charon_palette() -> QtGui.QPalette:
    """Return a dark palette matching the validation results dialog."""
    palette = QtGui.QPalette()
    colors = CHARON_COLORS

    palette.setColor(QtGui.QPalette.Window, QtGui.QColor(colors["bg_main"]))
    palette.setColor(QtGui.QPalette.WindowText, QtGui.QColor(colors["text_main"]))
    palette.setColor(QtGui.QPalette.Base, QtGui.QColor(colors["bg_card"]))
    palette.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor(colors["bg_main"]))
    palette.setColor(QtGui.QPalette.Text, QtGui.QColor(colors["text_main"]))
    palette.setColor(QtGui.QPalette.Button, QtGui.QColor(colors["btn_bg"]))
    palette.setColor(QtGui.QPalette.ButtonText, QtGui.QColor(colors["text_main"]))
    palette.setColor(QtGui.QPalette.BrightText, QtGui.QColor(QtCore.Qt.GlobalColor.white))
    palette.setColor(QtGui.QPalette.Highlight, QtGui.QColor(colors["bg_hover"]))
    palette.setColor(
        QtGui.QPalette.HighlightedText, QtGui.QColor(colors["text_main"])
    )
    palette.setColor(QtGui.QPalette.Link, QtGui.QColor(colors["restart_hover"]))
    palette.setColor(QtGui.QPalette.Mid, QtGui.QColor(colors["border"]))
    palette.setColor(QtGui.QPalette.Midlight, QtGui.QColor(colors["bg_hover"]))
    palette.setColor(QtGui.QPalette.Dark, QtGui.QColor(colors["bg_card"]))
    palette.setColor(QtGui.QPalette.Shadow, QtGui.QColor(colors["border"]))
    return palette


def build_main_stylesheet() -> str:
    """Compose the core stylesheet for the main Charon window."""
    c = CHARON_COLORS
    return f"""
    #CharonWindow {{
        background-color: {c['bg_main']};
        color: {c['text_main']};
        font-family: {FONT_FAMILY};
    }}
    #CharonWindow QLabel {{
        color: {c['text_main']};
        font-family: {FONT_FAMILY};
    }}
    #CharonWindow QLabel#CharonSubtitle,
    #CharonWindow QLabel#charonProjectLabel {{
        color: {c['text_sub']};
    }}
    #CharonWindow QFrame,
    #CharonWindow QWidget {{
        background-color: {c['bg_main']};
    }}
    #CharonWindow QTabWidget::pane {{
        border: 1px solid {c['border']};
        background: {c['bg_card']};
        border-radius: 6px;
        margin-top: 4px;
    }}
    #CharonWindow QTabBar::tab {{
        background: {c['bg_card']};
        color: {c['text_sub']};
        padding: 8px 14px;
        margin-right: 2px;
        border: 1px solid {c['border']};
        border-bottom-color: {c['bg_card']};
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
    }}
    #CharonWindow QTabBar::tab:hover {{
        background: {c['bg_hover']};
        color: {c['text_main']};
    }}
    #CharonWindow QTabBar::tab:selected {{
        background: {c['btn_bg']};
        color: {c['text_main']};
        border-bottom-color: {c['btn_bg']};
    }}
    #CharonWindow QTabWidget#CenterTabWidget::pane {{
        margin-top: 0px;
        margin-left: 10px;
    }}
    #CharonWindow QTabWidget#CenterTabWidget QTabBar::tab {{
        background: {c['bg_card']};
        color: {c['text_sub']};
        padding: 12px 10px;
        margin: 0px 0px 8px 0px;
        border: 1px solid {c['border']};
        border-radius: 8px;
        border-bottom-color: {c['border']};
    }}
    #CharonWindow QTabWidget#CenterTabWidget QTabBar::tab:hover {{
        background: {c['bg_hover']};
        color: {c['text_main']};
    }}
    #CharonWindow QTabWidget#CenterTabWidget QTabBar::tab:selected {{
        background: {c['btn_bg']};
        color: {c['text_main']};
        border-color: {c['btn_bg']};
    }}
    #CharonWindow QSplitter::handle {{
        background-color: {c['bg_card']};
    }}
    #CharonWindow QSplitter::handle:pressed {{
        background-color: {c['bg_hover']};
    }}
    #CharonWindow QLineEdit,
    #CharonWindow QTextEdit,
    #CharonWindow QPlainTextEdit,
    #CharonWindow QComboBox {{
        background: {c['bg_card']};
        color: {c['text_main']};
        border: 1px solid {c['border']};
        border-radius: 6px;
        padding: 6px 8px;
    }}
    #CharonWindow QLineEdit:focus,
    #CharonWindow QTextEdit:focus,
    #CharonWindow QPlainTextEdit:focus,
    #CharonWindow QComboBox:focus {{
        border: 1px solid {c['bg_hover']};
    }}
    #CharonWindow QPushButton {{
        background: {c['btn_bg']};
        color: {c['text_main']};
        border: 1px solid {c['border']};
        border-radius: 4px;
        padding: 6px 12px;
    }}
    #CharonWindow QPushButton:hover {{
        background: {c['bg_hover']};
        border-color: {c['text_sub']};
    }}
    #CharonWindow QPushButton:disabled {{
        color: {c['text_sub']};
        background: {c['bg_card']};
        border-color: {c['bg_hover']};
    }}
    #CharonWindow QTreeView,
    #CharonWindow QTableView,
    #CharonWindow QListView {{
        background: {c['bg_card']};
        alternate-background-color: {c['bg_main']};
        color: {c['text_main']};
        border: 1px solid {c['border']};
        selection-background-color: {c['bg_hover']};
        selection-color: {c['text_main']};
    }}
    #CharonWindow QHeaderView::section {{
        background: {c['bg_card']};
        color: {c['text_sub']};
        border: 1px solid {c['border']};
        padding: 4px 6px;
    }}
    #CharonWindow QScrollBar:vertical {{
        background: {c['bg_card']};
        width: 10px;
        margin: 0px;
    }}
    #CharonWindow QScrollBar::handle:vertical {{
        background: {c['bg_hover']};
        min-height: 20px;
        border-radius: 4px;
    }}
    #CharonWindow QScrollBar:horizontal {{
        background: {c['bg_card']};
        height: 10px;
        margin: 0px;
    }}
    #CharonWindow QScrollBar::handle:horizontal {{
        background: {c['bg_hover']};
        min-width: 20px;
        border-radius: 4px;
    }}
    """


def apply_charon_theme(widget: QtWidgets.QWidget) -> None:
    """Apply palette and stylesheet to a widget tree."""
    widget.setPalette(build_charon_palette())
    widget.setAutoFillBackground(True)
    widget.setStyleSheet(build_main_stylesheet())
