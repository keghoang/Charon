# Charon Configuration Reference

## SOFTWARE Dictionary

The unified SOFTWARE dictionary in `config.py` contains all software-specific settings:

```python
SOFTWARE = {
    "windows": {
        "compatible_versions": [None],  # None = any version
        "logo": "resources/logos/windows.png",
        "color": "#27ae60",  # Green
        "pyside_version": None,  # Auto-detect
        "hidden": False  # Show in dialogs
    },
    "maya": {
        "compatible_versions": {
            "2020": {},  # No specific PySide requirement
            "2022": {"pyside": 2},  # Force PySide2
            "2025": {"pyside": 6}   # Force PySide6
        },
        "logo": "resources/logos/maya.png", 
        "color": "#3498db",  # Blue
        "pyside_version": None,
        "hidden": False
    },
    "nuke": {
        "compatible_versions": {
            "12": {"pyside": 2},
            "13": {"pyside": 2},
            "15": {"pyside": 6}
        },
        "logo": "resources/logos/nuke.png",
        "color": "#e74c3c",  # Red
        "pyside_version": None,
        "hidden": False
    },
    "macos": {
        "compatible_versions": [None],
        "logo": "resources/logos/macos.png",
        "color": "#95a5a6",  # Gray
        "pyside_version": None,
        "hidden": True  # Hidden from dialogs
    },
    "linux": {
        "compatible_versions": [None],
        "logo": "resources/logos/linux.png", 
        "color": "#f39c12",  # Orange
        "pyside_version": None,
        "hidden": True  # Hidden from dialogs
    }
}
```

### Configuration Fields

**compatible_versions**: 
- `[None]` - Any version is compatible
- `{}` - Empty dict means no specific requirements
- `{"2022": {"pyside": 2}}` - Version-specific requirements

**logo**: Path to software icon (relative to Charon root)

**color**: Hex color for UI elements (#RRGGBB format)

**pyside_version**: 
- `None` - Auto-detect based on availability
- `2` - Force PySide2
- `6` - Force PySide6

**hidden**: 
- `True` - Hide from new script/edit metadata dialogs
- `False` - Show in dialogs (default)

### Legacy Support

`SOFTWARE_COLORS` is maintained for backward compatibility but deprecated:
```python
SOFTWARE_COLORS = {
    software: config["color"] 
    for software, config in SOFTWARE.items()
}
```

## Repository Paths & Validation Cache

```python
WORKFLOW_REPOSITORY_ROOT = r"\\buck\globalprefs\SHARED\CODE\Charon_repo\workflows"
REPOSITORY_SEARCH_PATHS = [WORKFLOW_REPOSITORY_ROOT]
```

- **Global Repository**: All workflow browsing starts at the shared `Charon_repo\workflows` hierarchy. Folder loaders enforce the boundary so the UI cannot traverse outside the approved tree.
- **Artist Cache**: Workflow validation payloads persist per user under `%LOCALAPPDATA%\Charon\plugins\charon\validation_cache\<workflow>_<hash>\status.json`, allowing personal model layouts without polluting source control.
- **Overrides**: Runtime arguments or environment overrides can still redirect discovery, but defaults now assume the shared `Charon_repo`.

## Qt Compatibility Settings

### PySide Version Detection

The `qt_compat.py` module uses SOFTWARE configuration to determine Qt bindings:

1. **Host Detection**: Identify current software (Maya, Nuke, etc.)
2. **Version Check**: Look up version-specific requirements
3. **Fallback**: Try both PySide2 and PySide6 by availability

### Manual Override

Force specific PySide version for testing:
```python
# In config.py
QT_BINDING_OVERRIDE = "PySide2"  # or "PySide6"
```

## Cache Configuration

### Memory Settings

```python
# Maximum cache memory in megabytes
CACHE_MAX_MEMORY_MB = 500

# Number of background prefetch threads
CACHE_PREFETCH_THREADS = 2

# Prefetch all folders alphabetically on startup
CACHE_PREFETCH_ALL_FOLDERS = True
```

### Cache Types and TTL

```python
# General cache TTL (Time To Live) in seconds
CACHE_GENERAL_TTL = 600  # 10 minutes

# Validation cache TTL
CACHE_VALIDATION_TTL = 600  # 10 minutes

# Hot folders count (hardcoded in implementation)
# MAX_HOT_FOLDERS = 20  # Not configurable
```

## Icon System Configuration

### Icon Loading Settings

```python
# Software icon size in pixels
SOFTWARE_ICON_SIZE = 20

# Icon file search order
ICON_EXTENSIONS = [".png", ".jpg", ".jpeg", ".svg"]

# Custom script icon names
CUSTOM_ICON_NAMES = ["icon.png", "icon.jpg"]
```

## Keybind Configuration

### Default Local Keybinds

```python
DEFAULT_LOCAL_KEYBINDS = {
    "run_script": "Ctrl+Return",
    "quick_search": "F4", 
    "tiny_mode": "F2",
    "refresh": "F5",
    "close_dialogs": "Escape"
}
```

### Keybind Context Settings

```python
# Local keybinds use WindowShortcut context
LOCAL_KEYBIND_CONTEXT = Qt.WindowShortcut

# Global keybinds use ApplicationShortcut context  
GLOBAL_KEYBIND_CONTEXT = Qt.ApplicationShortcut
```

## Path Configuration

### Repository Paths

```python
# Default paths for different hosts
DEFAULT_PATHS = {
    "maya": "/network/scripts/maya",
    "nuke": "/network/scripts/nuke", 
    "windows": "/network/scripts/general"
}

# Special folder names
BOOKMARKS_FOLDER = "_bookmarks"
HOTKEYS_FOLDER = "_hotkeys"
```

## Database Configuration

### User Settings Database

```python
# Database location
USER_SETTINGS_DB = "~/.charon/user_settings.db"

# Table versions for migration
DB_SCHEMA_VERSION = 3

# Batch operation sizes
DB_BATCH_SIZE = 100
```

## Logging Configuration

### Debug Settings

```python
# Enable debug output
DEBUG_MODE = False

# Log levels
LOG_LEVELS = {
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "ERROR": 40
}

# Output destinations
LOG_TO_CONSOLE = True
LOG_TO_FILE = False
LOG_FILE_PATH = "~/.charon/charon.log"
```

## Performance Tuning

### UI Responsiveness

```python
# Delay before showing loading indicators (ms)
LOADING_DELAY = 100

# Update frequency for progress bars (ms)
PROGRESS_UPDATE_INTERVAL = 50

# Maximum items to load before yielding to UI
BATCH_LOAD_SIZE = 50
```

### Background Processing

```python
# Thread pool sizes
LOADER_THREAD_COUNT = 4
VALIDATION_THREAD_COUNT = 2

# Queue sizes
MAX_QUEUE_SIZE = 1000
```

## Script Execution Configuration

### Execution Modes

```python
# Default execution mode for scripts
DEFAULT_EXECUTION_MODE = "auto"  # "main", "background", "auto"

# Timeout for script execution (ms)
SCRIPT_EXECUTION_TIMEOUT = 30000  # 30 seconds

# Output buffer size
MAX_OUTPUT_SIZE = 1048576  # 1MB
```

### Mirror Prints Setting

```python
# Default mirror_prints for new scripts
DEFAULT_MIRROR_PRINTS = False

# Force mirror for specific script types
FORCE_MIRROR_TYPES = ["mel"]  # MEL always mirrors
```

## UI Configuration

### Window Settings

```python
# Default window size
DEFAULT_WINDOW_WIDTH = 800
DEFAULT_WINDOW_HEIGHT = 600

# Remember window position
REMEMBER_WINDOW_POSITION = True

# Always on top for specific hosts
ALWAYS_ON_TOP_HOSTS = ["maya", "nuke"]
```

### Table View Settings

```python
# Column widths
FOLDER_COLUMN_WIDTH = 200
SCRIPT_COLUMN_WIDTH = 300

# Row heights
DEFAULT_ROW_HEIGHT = 24
COMPACT_ROW_HEIGHT = 20
```

## Environment Variables

Charon checks these environment variables:

```bash
# Override global repository path
CHARON_GLOBAL_PATH=/custom/path

# Override host detection
CHARON_HOST=maya

# Enable debug mode
CHARON_DEBUG=1

# Custom config file
CHARON_CONFIG=/path/to/config.py
```

## Extending Configuration

### Adding New Software

```python
SOFTWARE["your_software"] = {
    "compatible_versions": {
        "1.0": {"pyside": 2}
    },
    "logo": "resources/logos/your_software.png",
    "color": "#ff6600",
    "pyside_version": None,
    "hidden": False
}
```

### Custom Validators

```python
# Add to SCRIPT_VALIDATORS list
def validate_custom_script(script_path, metadata):
    """Example validation hook for extra host checks"""
    # Implement host-specific requirements here
    return True

SCRIPT_VALIDATORS.append(validate_custom_script)
```
