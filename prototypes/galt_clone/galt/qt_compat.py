"""
Qt compatibility module for PySide2/PySide6 support.

This module provides a unified interface for Qt imports, automatically
selecting the appropriate version based on:
1. Host software requirements (from config.SOFTWARE)
2. Availability of PySide versions
"""
import sys

def _detect_host_and_version():
    """Detect host application and version."""
    try:
        import nuke
        return ("Nuke", str(nuke.NUKE_VERSION_MAJOR))
    except Exception:
        # During CLI development the nuke module is typically unavailable;
        # we still report Nuke so downstream code uses the same execution path.
        return ("Nuke", None)

def _try_import_pyside(version):
    """Try to import specific PySide version."""
    if version == 6:
        try:
            import PySide6
            return 6
        except ImportError:
            # Fall back to PySide2 if configured version not available
            pass
    
    try:
        import PySide2
        return 2
    except ImportError:
        raise ImportError(f"PySide{version} is required but not available. Please install it.")

def _try_import_by_availability():
    """Try PySide6 first, fall back to PySide2."""
    try:
        import PySide6
        return 6
    except ImportError:
        try:
            import PySide2
            return 2
        except ImportError:
            raise ImportError("Neither PySide6 nor PySide2 is available. Please install one of them.")

def _get_available_qt_binding():
    """Determine Qt binding based on host software and configuration."""
    # First check if we can detect host and version
    host_info = _detect_host_and_version()
    
    if host_info:
        host, version = host_info
        try:
            from galt import config
            
            # Check if we have specific PySide requirements for this host/version
            if host.lower() in config.SOFTWARE:
                software_config = config.SOFTWARE[host.lower()]
                
                # Check if there's a global pyside preference for this software
                global_pyside = software_config.get("pyside_version")
                if global_pyside:
                    return _try_import_pyside(global_pyside)
                
                # Check version-specific configuration
                compat_versions = software_config.get("compatible_versions")
                if isinstance(compat_versions, dict) and version:
                    # Try exact version match first
                    if version in compat_versions:
                        ver_config = compat_versions[version]
                        if isinstance(ver_config, dict):
                            required_pyside = ver_config.get("pyside")
                            if required_pyside:
                                return _try_import_pyside(required_pyside)
                    
                    # Try prefix matching (e.g., "2022" matches "2022.1")
                    for ver_prefix, ver_config in compat_versions.items():
                        if version.startswith(ver_prefix):
                            if isinstance(ver_config, dict):
                                required_pyside = ver_config.get("pyside")
                                if required_pyside:
                                    return _try_import_pyside(required_pyside)
        except ImportError:
            # config module not available (e.g., during initial setup)
            pass
    
    # Fall back to availability-based selection
    return _try_import_by_availability()

# Determine which version to use
PYSIDE_VERSION = _get_available_qt_binding()
USE_PYSIDE6 = (PYSIDE_VERSION == 6)

# Import the appropriate Qt binding
if USE_PYSIDE6:
    from PySide6 import QtCore, QtGui, QtWidgets
    from PySide6.QtCore import Qt, Signal, Slot, QObject, QThread, QTimer, QEvent, QEventLoop, QMutex, QMutexLocker
    from PySide6.QtGui import QIcon, QPixmap, QPalette, QColor, QFont, QFontMetrics, QKeySequence, QTextCursor, QTextCharFormat, QSyntaxHighlighter, QTextDocument, QShortcut, QAction, QActionGroup
    from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, \
        QPushButton, QLabel, QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QCheckBox, QRadioButton, \
        QListWidget, QListWidgetItem, QTreeWidget, QTreeWidgetItem, QTableWidget, QTableWidgetItem, \
        QDialog, QMessageBox, QFileDialog, QMenu, QMenuBar, QToolBar, QStatusBar, QDockWidget, \
        QSplitter, QTabWidget, QGroupBox, QScrollArea, QSizePolicy, QSpacerItem, QFrame, \
        QProgressBar, QSlider, QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit, QDateTimeEdit, \
        QStyledItemDelegate, QStyleOptionViewItem, QAbstractItemView, QHeaderView, QTableView
    
    # Add QPalette compatibility
    QPalette.Window = QPalette.ColorRole.Window
    QPalette.Highlight = QPalette.ColorRole.Highlight
else:
    from PySide2 import QtCore, QtGui, QtWidgets
    from PySide2.QtCore import Qt, Signal, Slot, QObject, QThread, QTimer, QEvent, QEventLoop, QMutex, QMutexLocker
    from PySide2.QtGui import QIcon, QPixmap, QPalette, QColor, QFont, QFontMetrics, QKeySequence, QTextCursor, QTextCharFormat, QSyntaxHighlighter, QTextDocument
    from PySide2.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, \
        QPushButton, QLabel, QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QCheckBox, QRadioButton, \
        QListWidget, QListWidgetItem, QTreeWidget, QTreeWidgetItem, QTableWidget, QTableWidgetItem, \
        QDialog, QMessageBox, QFileDialog, QMenu, QMenuBar, QToolBar, QStatusBar, QDockWidget, \
        QSplitter, QTabWidget, QGroupBox, QScrollArea, QSizePolicy, QSpacerItem, QFrame, \
        QProgressBar, QSlider, QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit, QDateTimeEdit, \
        QStyledItemDelegate, QStyleOptionViewItem, QAbstractItemView, QHeaderView, QTableView, \
        QShortcut, QAction, QActionGroup

# Handle API differences between PySide2 and PySide6
if PYSIDE_VERSION == 6:
    # PySide6 moved many Qt enums to sub-namespaces
    AlignLeft = Qt.AlignmentFlag.AlignLeft
    AlignRight = Qt.AlignmentFlag.AlignRight
    AlignCenter = Qt.AlignmentFlag.AlignCenter
    AlignTop = Qt.AlignmentFlag.AlignTop
    AlignBottom = Qt.AlignmentFlag.AlignBottom
    AlignVCenter = Qt.AlignmentFlag.AlignVCenter
    AlignHCenter = Qt.AlignmentFlag.AlignHCenter
    
    ItemIsEnabled = Qt.ItemFlag.ItemIsEnabled
    ItemIsSelectable = Qt.ItemFlag.ItemIsSelectable
    ItemIsEditable = Qt.ItemFlag.ItemIsEditable
    
    KeepAspectRatio = Qt.AspectRatioMode.KeepAspectRatio
    IgnoreAspectRatio = Qt.AspectRatioMode.IgnoreAspectRatio
    
    SmoothTransformation = Qt.TransformationMode.SmoothTransformation
    FastTransformation = Qt.TransformationMode.FastTransformation
    
    NoBrush = Qt.BrushStyle.NoBrush
    SolidPattern = Qt.BrushStyle.SolidPattern
    
    NoPen = Qt.PenStyle.NoPen
    SolidLine = Qt.PenStyle.SolidLine
    
    WA_DeleteOnClose = Qt.WidgetAttribute.WA_DeleteOnClose
    WA_QuitOnClose = Qt.WidgetAttribute.WA_QuitOnClose
    WA_TranslucentBackground = Qt.WidgetAttribute.WA_TranslucentBackground
    
    WindowStaysOnTopHint = Qt.WindowType.WindowStaysOnTopHint
    Tool = Qt.WindowType.Tool
    Window = Qt.WindowType.Window
    Dialog = Qt.WindowType.Dialog
    FramelessWindowHint = Qt.WindowType.FramelessWindowHint
    WindowModal = Qt.WindowModality.WindowModal
    WindowContextHelpButtonHint = Qt.WindowType.WindowContextHelpButtonHint
    WindowCloseButtonHint = Qt.WindowType.WindowCloseButtonHint
    WindowSystemMenuHint = Qt.WindowType.WindowSystemMenuHint
    Popup = Qt.WindowType.Popup
    WindowShortcut = Qt.ShortcutContext.WindowShortcut
    
    Key_Return = Qt.Key.Key_Return
    Key_Enter = Qt.Key.Key_Enter
    Key_Escape = Qt.Key.Key_Escape
    Key_Space = Qt.Key.Key_Space
    Key_Delete = Qt.Key.Key_Delete
    Key_F = Qt.Key.Key_F
    Key_R = Qt.Key.Key_R
    Key_Control = Qt.Key.Key_Control
    Key_Shift = Qt.Key.Key_Shift
    Key_Alt = Qt.Key.Key_Alt
    Key_Exclam = Qt.Key.Key_Exclam
    Key_At = Qt.Key.Key_At
    Key_NumberSign = Qt.Key.Key_NumberSign
    Key_Dollar = Qt.Key.Key_Dollar
    Key_Percent = Qt.Key.Key_Percent
    Key_AsciiCircum = Qt.Key.Key_AsciiCircum
    Key_Ampersand = Qt.Key.Key_Ampersand
    Key_Asterisk = Qt.Key.Key_Asterisk
    Key_ParenLeft = Qt.Key.Key_ParenLeft
    Key_ParenRight = Qt.Key.Key_ParenRight
    Key_1 = Qt.Key.Key_1
    Key_2 = Qt.Key.Key_2
    Key_3 = Qt.Key.Key_3
    Key_4 = Qt.Key.Key_4
    Key_5 = Qt.Key.Key_5
    Key_6 = Qt.Key.Key_6
    Key_7 = Qt.Key.Key_7
    Key_8 = Qt.Key.Key_8
    Key_9 = Qt.Key.Key_9
    Key_0 = Qt.Key.Key_0
    Key_A = Qt.Key.Key_A
    Key_B = Qt.Key.Key_B
    Key_C = Qt.Key.Key_C
    Key_D = Qt.Key.Key_D
    Key_E = Qt.Key.Key_E
    Key_G = Qt.Key.Key_G
    Key_H = Qt.Key.Key_H
    Key_I = Qt.Key.Key_I
    Key_J = Qt.Key.Key_J
    Key_K = Qt.Key.Key_K
    Key_L = Qt.Key.Key_L
    Key_M = Qt.Key.Key_M
    Key_N = Qt.Key.Key_N
    Key_O = Qt.Key.Key_O
    Key_P = Qt.Key.Key_P
    Key_Q = Qt.Key.Key_Q
    Key_S = Qt.Key.Key_S
    Key_T = Qt.Key.Key_T
    Key_U = Qt.Key.Key_U
    Key_V = Qt.Key.Key_V
    Key_W = Qt.Key.Key_W
    Key_X = Qt.Key.Key_X
    Key_Y = Qt.Key.Key_Y
    Key_Z = Qt.Key.Key_Z
    Key_F1 = Qt.Key.Key_F1
    Key_F2 = Qt.Key.Key_F2
    Key_F3 = Qt.Key.Key_F3
    Key_F4 = Qt.Key.Key_F4
    Key_F5 = Qt.Key.Key_F5
    Key_F6 = Qt.Key.Key_F6
    Key_F7 = Qt.Key.Key_F7
    Key_F8 = Qt.Key.Key_F8
    Key_F9 = Qt.Key.Key_F9
    Key_F10 = Qt.Key.Key_F10
    Key_F11 = Qt.Key.Key_F11
    Key_F12 = Qt.Key.Key_F12
    Key_Up = Qt.Key.Key_Up
    Key_Down = Qt.Key.Key_Down
    Key_Left = Qt.Key.Key_Left
    Key_Right = Qt.Key.Key_Right
    
    ControlModifier = Qt.KeyboardModifier.ControlModifier
    ShiftModifier = Qt.KeyboardModifier.ShiftModifier
    AltModifier = Qt.KeyboardModifier.AltModifier
    MetaModifier = Qt.KeyboardModifier.MetaModifier
    
    LeftButton = Qt.MouseButton.LeftButton
    RightButton = Qt.MouseButton.RightButton
    MiddleButton = Qt.MouseButton.MiddleButton
    
    Horizontal = Qt.Orientation.Horizontal
    Vertical = Qt.Orientation.Vertical
    
    DisplayRole = Qt.ItemDataRole.DisplayRole
    EditRole = Qt.ItemDataRole.EditRole
    UserRole = Qt.ItemDataRole.UserRole
    DecorationRole = Qt.ItemDataRole.DecorationRole
    ToolTipRole = Qt.ItemDataRole.ToolTipRole
    ForegroundRole = Qt.ItemDataRole.ForegroundRole
    BackgroundRole = Qt.ItemDataRole.BackgroundRole
    FontRole = Qt.ItemDataRole.FontRole
    TextAlignmentRole = Qt.ItemDataRole.TextAlignmentRole
    
    NoFocus = Qt.FocusPolicy.NoFocus
    TabFocus = Qt.FocusPolicy.TabFocus
    ClickFocus = Qt.FocusPolicy.ClickFocus
    StrongFocus = Qt.FocusPolicy.StrongFocus
    
    PlainText = Qt.TextFormat.PlainText
    RichText = Qt.TextFormat.RichText
    
    UniqueConnection = Qt.ConnectionType.UniqueConnection
    
    PointingHandCursor = Qt.CursorShape.PointingHandCursor
    
    # Selection modes
    NoSelection = QAbstractItemView.SelectionMode.NoSelection
    SingleSelection = QAbstractItemView.SelectionMode.SingleSelection
    MultiSelection = QAbstractItemView.SelectionMode.MultiSelection
    ExtendedSelection = QAbstractItemView.SelectionMode.ExtendedSelection
    
    # Selection behaviors
    SelectRows = QAbstractItemView.SelectionBehavior.SelectRows
    SelectColumns = QAbstractItemView.SelectionBehavior.SelectColumns
    SelectItems = QAbstractItemView.SelectionBehavior.SelectItems
    
else:
    # PySide2 - enums are directly on Qt namespace
    AlignLeft = Qt.AlignLeft
    AlignRight = Qt.AlignRight
    AlignCenter = Qt.AlignCenter
    AlignTop = Qt.AlignTop
    AlignBottom = Qt.AlignBottom
    AlignVCenter = Qt.AlignVCenter
    AlignHCenter = Qt.AlignHCenter
    
    ItemIsEnabled = Qt.ItemIsEnabled
    ItemIsSelectable = Qt.ItemIsSelectable
    ItemIsEditable = Qt.ItemIsEditable
    
    KeepAspectRatio = Qt.KeepAspectRatio
    IgnoreAspectRatio = Qt.IgnoreAspectRatio
    
    SmoothTransformation = Qt.SmoothTransformation
    FastTransformation = Qt.FastTransformation
    
    NoBrush = Qt.NoBrush
    SolidPattern = Qt.SolidPattern
    
    NoPen = Qt.NoPen
    SolidLine = Qt.SolidLine
    
    WA_DeleteOnClose = Qt.WA_DeleteOnClose
    WA_QuitOnClose = Qt.WA_QuitOnClose
    WA_TranslucentBackground = Qt.WA_TranslucentBackground
    
    WindowStaysOnTopHint = Qt.WindowStaysOnTopHint
    Tool = Qt.Tool
    Window = Qt.Window
    Dialog = Qt.Dialog
    FramelessWindowHint = Qt.FramelessWindowHint
    WindowModal = Qt.WindowModal
    WindowContextHelpButtonHint = Qt.WindowContextHelpButtonHint
    WindowCloseButtonHint = Qt.WindowCloseButtonHint
    WindowSystemMenuHint = Qt.WindowSystemMenuHint
    Popup = Qt.Popup
    WindowShortcut = Qt.WindowShortcut
    
    Key_Return = Qt.Key_Return
    Key_Enter = Qt.Key_Enter
    Key_Escape = Qt.Key_Escape
    Key_Space = Qt.Key_Space
    Key_Delete = Qt.Key_Delete
    Key_F = Qt.Key_F
    Key_R = Qt.Key_R
    Key_Control = Qt.Key_Control
    Key_Shift = Qt.Key_Shift
    Key_Alt = Qt.Key_Alt
    Key_Exclam = Qt.Key_Exclam
    Key_At = Qt.Key_At
    Key_NumberSign = Qt.Key_NumberSign
    Key_Dollar = Qt.Key_Dollar
    Key_Percent = Qt.Key_Percent
    Key_AsciiCircum = Qt.Key_AsciiCircum
    Key_Ampersand = Qt.Key_Ampersand
    Key_Asterisk = Qt.Key_Asterisk
    Key_ParenLeft = Qt.Key_ParenLeft
    Key_ParenRight = Qt.Key_ParenRight
    Key_1 = Qt.Key_1
    Key_2 = Qt.Key_2
    Key_3 = Qt.Key_3
    Key_4 = Qt.Key_4
    Key_5 = Qt.Key_5
    Key_6 = Qt.Key_6
    Key_7 = Qt.Key_7
    Key_8 = Qt.Key_8
    Key_9 = Qt.Key_9
    Key_0 = Qt.Key_0
    Key_A = Qt.Key_A
    Key_B = Qt.Key_B
    Key_C = Qt.Key_C
    Key_D = Qt.Key_D
    Key_E = Qt.Key_E
    Key_G = Qt.Key_G
    Key_H = Qt.Key_H
    Key_I = Qt.Key_I
    Key_J = Qt.Key_J
    Key_K = Qt.Key_K
    Key_L = Qt.Key_L
    Key_M = Qt.Key_M
    Key_N = Qt.Key_N
    Key_O = Qt.Key_O
    Key_P = Qt.Key_P
    Key_Q = Qt.Key_Q
    Key_S = Qt.Key_S
    Key_T = Qt.Key_T
    Key_U = Qt.Key_U
    Key_V = Qt.Key_V
    Key_W = Qt.Key_W
    Key_X = Qt.Key_X
    Key_Y = Qt.Key_Y
    Key_Z = Qt.Key_Z
    Key_F1 = Qt.Key_F1
    Key_F2 = Qt.Key_F2
    Key_F3 = Qt.Key_F3
    Key_F4 = Qt.Key_F4
    Key_F5 = Qt.Key_F5
    Key_F6 = Qt.Key_F6
    Key_F7 = Qt.Key_F7
    Key_F8 = Qt.Key_F8
    Key_F9 = Qt.Key_F9
    Key_F10 = Qt.Key_F10
    Key_F11 = Qt.Key_F11
    Key_F12 = Qt.Key_F12
    Key_Up = Qt.Key_Up
    Key_Down = Qt.Key_Down
    Key_Left = Qt.Key_Left
    Key_Right = Qt.Key_Right
    
    ControlModifier = Qt.ControlModifier
    ShiftModifier = Qt.ShiftModifier
    AltModifier = Qt.AltModifier
    MetaModifier = Qt.MetaModifier
    
    LeftButton = Qt.LeftButton
    RightButton = Qt.RightButton
    MiddleButton = Qt.MiddleButton
    
    Horizontal = Qt.Horizontal
    Vertical = Qt.Vertical
    
    DisplayRole = Qt.DisplayRole
    EditRole = Qt.EditRole
    UserRole = Qt.UserRole
    DecorationRole = Qt.DecorationRole
    ToolTipRole = Qt.ToolTipRole
    ForegroundRole = Qt.ForegroundRole
    BackgroundRole = Qt.BackgroundRole
    FontRole = Qt.FontRole
    TextAlignmentRole = Qt.TextAlignmentRole
    
    NoFocus = Qt.NoFocus
    TabFocus = Qt.TabFocus
    ClickFocus = Qt.ClickFocus
    StrongFocus = Qt.StrongFocus
    
    PlainText = Qt.PlainText
    RichText = Qt.RichText
    
    UniqueConnection = Qt.UniqueConnection
    
    PointingHandCursor = Qt.PointingHandCursor
    
    # Selection modes
    NoSelection = QAbstractItemView.NoSelection
    SingleSelection = QAbstractItemView.SingleSelection
    MultiSelection = QAbstractItemView.MultiSelection
    ExtendedSelection = QAbstractItemView.ExtendedSelection
    
    # Selection behaviors
    SelectRows = QAbstractItemView.SelectRows
    SelectColumns = QAbstractItemView.SelectColumns
    SelectItems = QAbstractItemView.SelectItems

# Print which version is being used (helpful for debugging)

def exec_with_fallback(target, *args, **kwargs):
    """Call exec/exec_ on the given Qt object regardless of binding version."""
    execute = getattr(target, "exec", None)
    if callable(execute):
        return execute(*args, **kwargs)
    execute = getattr(target, "exec_", None)
    if callable(execute):
        return execute(*args, **kwargs)
    raise AttributeError(f"{target} has no exec/exec_ method")


def exec_dialog(dialog, *args, **kwargs):
    return exec_with_fallback(dialog, *args, **kwargs)


def exec_menu(menu, *args, **kwargs):
    return exec_with_fallback(menu, *args, **kwargs)


def exec_application(app, *args, **kwargs):
    return exec_with_fallback(app, *args, **kwargs)


if __name__ == "__main__":
    print(f"Using PySide{PYSIDE_VERSION}")
