import os

# =============================================================================
# COMFYUI SETTINGS
# =============================================================================

COMFY_URL_BASE = "http://127.0.0.1:8188"
COMFY_BATCH_TIMEOUT_SEC = 300
COMFY_QUEUE_GRACE_SEC = 15
COMFY_RESULT_WATCH_TIMEOUT_SEC = 300
COMFY_RESULT_WATCH_GRACE_SEC = 60
COMFY_DOWNLOAD_RETRIES = 4
COMFY_DOWNLOAD_RETRY_DELAY_SEC = 0.75
COMFY_DOWNLOAD_MIN_BYTES = 1
COMFY_OUTPUT_SCAN_LIMIT = 4000
COMFY_OUTPUT_SCAN_GRACE_SEC = 30
STATUS_COLOR_UPDATE_INTERVAL_SEC = 0.5
CHARON_NODE_ID_LENGTH = 12
CHARON_NODE_ID_SCRIPT_HASH_PREFIX = 5

# =============================================================================
# UI SETTINGS
# =============================================================================

# Window dimensions
WINDOW_WIDTH = 690
WINDOW_HEIGHT = 450

# Tiny Mode dimensions
TINY_MODE_WIDTH = 210        # Default width for tiny mode (pixels)
TINY_MODE_HEIGHT = 420       # Default height for tiny mode (pixels)
TINY_MODE_MIN_WIDTH = 100    # Minimum width for tiny mode (pixels)
TINY_MODE_MIN_HEIGHT = 180   # Minimum height for tiny mode (pixels)
# Layout and Spacing
UI_WINDOW_MARGINS = 4  # Padding around main window content (pixels)
UI_ELEMENT_SPACING = 4  # Spacing between UI elements (pixels)
UI_FOLDER_WORKFLOW_GAP = 14  # Extra spacing between folder and workflow tables (pixels)

# Button Dimensions
UI_BUTTON_WIDTH = 80  # Width of standard buttons (pixels)
UI_SMALL_BUTTON_WIDTH = 60  # Width of small buttons like Clear (pixels)

# Panel Layout Ratios (MUST sum to 1.0)
# Adjust these values to change the relative size of each panel
UI_FOLDER_PANEL_RATIO = 0.17   # 25% of width for folder panel (left)
UI_CENTER_PANEL_RATIO = 0.66   # 60% of width for center panel (scripts/metadata) 
UI_HISTORY_PANEL_RATIO = 0.17   # 15% of width for history panel (right)

# Validate that ratios sum to 1.0
_RATIO_SUM = UI_FOLDER_PANEL_RATIO + UI_CENTER_PANEL_RATIO + UI_HISTORY_PANEL_RATIO
if abs(_RATIO_SUM - 1.0) > 0.001:  # Allow small floating point error
    raise ValueError(f"Panel ratios must sum to 1.0, got {_RATIO_SUM}. "
                   f"Folder: {UI_FOLDER_PANEL_RATIO}, Center: {UI_CENTER_PANEL_RATIO}, "
                   f"History: {UI_HISTORY_PANEL_RATIO}")

# Font Configuration for UI elements (not for code output)
import platform
if platform.system() == "Windows":
    UI_ICON_FONT_FAMILY = "Segoe UI"  # Windows UI font
elif platform.system() == "Darwin":  # macOS
    UI_ICON_FONT_FAMILY = "SF Pro Text"  # macOS UI font (or system default)
else:  # Linux
    UI_ICON_FONT_FAMILY = "Ubuntu"  # Linux UI font (or "DejaVu Sans")
# =============================================================================
# REPOSITORY SETTINGS
# =============================================================================

# Repository search paths - used when no repository is specified at runtime
# First existing path will be used
# Priority order: Runtime argument → CHARON_REPO env var → These paths
WORKFLOW_REPOSITORY_ROOT = r"\\buck\globalprefs\SHARED\CODE\Charon_repo\workflows"
REPOSITORY_SEARCH_PATHS = [
    WORKFLOW_REPOSITORY_ROOT,
]

# Legacy fallback - kept for backward compatibility
# Deprecated: Use REPOSITORY_SEARCH_PATHS instead
GLOBAL_REPO_PATH = WORKFLOW_REPOSITORY_ROOT


# =============================================================================
# ICON SETTINGS
# =============================================================================

# Icon dimensions for software logos in the script table
SOFTWARE_ICON_SIZE = 12  # Size in pixels (icons will be square: 12x12)

# =============================================================================
# SOFTWARE SETTINGS
# =============================================================================

# Each software entry contains:
#   - compatible_versions: Version compatibility rules
#     - None in list: Any version supported (e.g., [None])
#     - List of strings: Simple version list (backward compatible)
#     - Dict: Version-specific configuration including PySide version
#   - logo: Path to software logo
#   - color: Theme color for UI elements
#   - pyside_version: Global PySide preference (overridden by version-specific)
#   - hidden: If True, hide from new script and edit metadata dialogs
#
# Version-specific PySide configuration example:
#   "maya": {
#       "compatible_versions": {
#           "2022": {"pyside": 2},  # Force PySide2 for Maya 2022
#           "2025": {"pyside": 6},  # Force PySide6 for Maya 2025
#       }
#   }
#
# If pyside value is None or missing, auto-detection is used
SOFTWARE = {
    "nuke": {
        "compatible_versions": {
            "13": {"pyside": 2},  # Nuke 13-15 use PySide2
            "14": {"pyside": 2},
            "15": {"pyside": 2},
            "16": {"pyside": 6},  # Nuke 16+ use PySide6
            "17": {"pyside": 6},
        },
        "logo": "resources/logos/nuke.png",
        "color": "#f1c40f",  # Yellow
        "pyside_version": None,  # Will be determined by version
        "hidden": False,
        "host_settings": True,
    },
}

# Recognized script types and their file extensions
SCRIPT_TYPES = {
    "python": [".py"],
    "mel": [".mel"]
}

# ==============================================================================
# WINDOW MANAGEMENT SETTINGS
# ==============================================================================

# Default window configuration (used as fallback for undefined hosts)
DEFAULT_WINDOW_CONFIG = {
    "supports_docking": False,
    "docking_method": None,
    "window_flags": "Qt.Window",
    "window_attributes": ["Qt.WA_DeleteOnClose"],
    "parent_to_host": False,  # New flag
    "tiny_mode_flags": [],  # No extra flags by default
    "description": "Standard application window"
}

# Host-specific window configurations
WINDOW_CONFIGS = {
    "nuke": {
        "supports_docking": False,
        "docking_method": "registerWidgetAsPanel",
        "window_flags": "Qt.Tool",
        "window_attributes": ["Qt.WA_DeleteOnClose"],
        "parent_to_host": True,  # Enable parenting to Nuke main window
        "tiny_mode_flags": [],
        "description": "Nuke integration with panel registration",
    },
    "standalone": {
        "supports_docking": False,
        "docking_method": None,
        "window_flags": "Qt.Window",
        "window_attributes": ["Qt.WA_DeleteOnClose", "Qt.WA_QuitOnClose"],
        "parent_to_host": False,
        "tiny_mode_flags": [],
        "description": "Standalone application window",
    },
}


DEFAULT_METADATA = {
    "software": [],  # Will default to current host if empty
    "entry": "main.py", 
    "script_type": "python",  # Auto-detected from file extension if not specified
    "run_on_main": True,  # Whether to run on main thread (default True)
    "mirror_prints": True,  # Whether to mirror prints to terminal (default True)
    "tags": []  # List of tags for categorizing scripts
}

# Opacity for incompatible items (0.0 = fully transparent, 1.0 = fully opaque)
INCOMPATIBLE_OPACITY = 0.5  # opacity for greyed out items

# DEPRECATED: Use SOFTWARE[software]["color"] instead
# Kept for backward compatibility only
SOFTWARE_COLORS = {
    "Nuke": "#f1c40f",        # Yellow
    "None": "#ffffff",        # White
    "No Metadata": "#7f8c8d",  # Gray
    "Default": "#95a5a6",     # Default fallback color
}


DEFAULT_README_STYLE = """
QTextBrowser { margin: 0; padding: 0; }
p { margin: 0px 0; }
h1, h2, h3, h4, h5, h6 { margin: 0px 0; }
ul, ol { margin: 0px 0px; padding: 0; }
li { margin: 0 0 0px 0; }
pre { margin: 0px 0; }
"""

# Debug mode flag - controls verbose output
# Debug and Logging Settings
DEBUG_MODE = False

# Logging configuration
# System messages are always shown to terminal
# Script output goes to ExecutionDetailsDialog (and optionally terminal based on mirror_prints)

# Execution history settings
EXECUTION_HISTORY_MAX_ITEMS = 50  # Maximum number of executions to keep in history

# Background execution settings
MAX_BACKGROUND_THREADS = 4  # Maximum number of concurrent background threads

# Timing and Performance
UI_NAVIGATION_DELAY_MS = 50  # Delay before navigation after folder refresh (milliseconds)

# Selection delay settings (to prevent excessive refreshes during rapid selection changes)
UI_FOLDER_SELECTION_DELAY_MS = 50  # Delay before loading scripts when selecting folders (normal click)
UI_SCRIPT_SELECTION_DELAY_MS = 50  # Delay before updating metadata when selecting scripts
UI_FOLDER_DRAG_DELAY_MS = 50  # Delay during folder dragging to reduce refresh frequency
UI_SCRIPT_DRAG_DELAY_MS = 50  # Delay during script dragging (currently uses same as normal selection)

# Panel header settings
UI_PANEL_HEADER_HEIGHT = 24  # Standardized height for all panel headers (Folders, Scripts, History)

# =============================================================================
# APPLICATION SETTINGS
# =============================================================================

APP_SETTING_HOSTS = tuple(sorted({*SOFTWARE.keys(), "standalone"}))

APP_SETTING_DEFINITIONS = {
    "run_at_startup": {
        "slug": "run_at_startup",
        "default": "off",
        "choices": ["off", "on"],
    },
    "startup_mode": {
        "slug": "startup",
        "default": "normal",
        "choices": ["normal", "tiny"],
    },
    "always_on_top": {
        "slug": "always_on_top",
        "default": "off",
        "choices": ["off", "on"],
    },
    "advanced_user_mode": {
        "slug": "advanced_mode",
        "default": "off",
        "choices": ["off", "on"],
    },
    "debug_logging": {
        "slug": "debug_mode",
        "default": "off",
        "choices": ["off", "on"],
    },
    "tiny_offset_x": {
        "slug": "tiny_offset_x",
        "default": "0",
    },
    "tiny_offset_y": {
        "slug": "tiny_offset_y",
        "default": "0",
    },
}

_TINY_MODE_FLAGS_BY_HOST = {
    host: WINDOW_CONFIGS.get(host, DEFAULT_WINDOW_CONFIG).get("tiny_mode_flags", [])
    for host in APP_SETTING_HOSTS
}

APP_SETTING_SLUGS = {key: meta["slug"] for key, meta in APP_SETTING_DEFINITIONS.items()}

DEFAULT_APP_SETTINGS = {
    f"{meta['slug']}-{host}": (
        "on"
        if meta["slug"] == "always_on_top" and "Qt.WindowStaysOnTopHint" in _TINY_MODE_FLAGS_BY_HOST.get(host, [])
        else meta["default"]
    )
    for host in APP_SETTING_HOSTS
    for meta in APP_SETTING_DEFINITIONS.values()
}

APP_SETTING_CHOICES = {
    key: list(meta["choices"])
    for key, meta in APP_SETTING_DEFINITIONS.items()
    if "choices" in meta
}

# =============================================================================
# KEYBIND SETTINGS
# =============================================================================

# Default local keybinds (Charon UI shortcuts)
DEFAULT_LOCAL_KEYBINDS = {
    'quick_search': {'key_sequence': 'F4', 'enabled': True},
    'run_script': {'key_sequence': 'Ctrl+Return', 'enabled': True},
    'refresh': {'key_sequence': 'Ctrl+R', 'enabled': True},
    'open_folder': {'key_sequence': 'Ctrl+O', 'enabled': True},
    'settings': {'key_sequence': 'Ctrl+,', 'enabled': True},
    'tiny_mode': {'key_sequence': 'F3', 'enabled': True}
}

# =============================================================================
# EXECUTION SETTINGS
# =============================================================================

# Timeouts and Intervals
MAIN_THREAD_TIMEOUT_MS = 30000  # Main thread script timeout in milliseconds
EXECUTION_OUTPUT_UPDATE_INTERVAL_MS = 50  # How often to check for background output updates (milliseconds)

# =============================================================================
# DIALOG SETTINGS
# =============================================================================

# Execution Details Dialog
EXECUTION_DIALOG_WIDTH = 600  # Default execution dialog width (pixels)
EXECUTION_DIALOG_HEIGHT = 400  # Default execution dialog height (pixels)
EXECUTION_DIALOG_OUTPUT_HEIGHT = 200  # Maximum height for output text area (pixels)

# =============================================================================
# CACHE SETTINGS
# =============================================================================

# Background prefetch thread configuration
CACHE_PREFETCH_THREADS = 2  # Number of background threads for prefetching (adjustable)
CACHE_MAX_MEMORY_MB = 500   # Maximum memory usage for cache in MB
CACHE_PREFETCH_ALL_FOLDERS = True  # If True, prefetch all folders alphabetically

# =============================================================================
# WARNING MESSAGES
# =============================================================================

# Qt Threading Warning Template
QT_WARNING_MESSAGE_TEMPLATE = """WARNING: {qt_import} detected in script.
Qt widgets cannot be created in background threads.
Set 'run_on_main: true' in .charon.json to use Qt widgets."""

