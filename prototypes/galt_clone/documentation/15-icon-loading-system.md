# Icon Loading System

## Overview

Galt implements an efficient icon loading system that pre-loads all software icons at startup and maintains them in memory throughout the session. This eliminates redundant file I/O operations and improves UI responsiveness.

## Architecture

### IconManager (`icon_manager.py`)

The core of the system is the `IconManager` singleton class that:
- Loads all software icons once at application startup
- Pre-scales icons to the configured size
- Maintains a global cache accessible throughout the application
- Provides thread-safe access to icon resources

### Key Features

1. **One-time Loading**: Icons are loaded only once when the first Galt window is created
2. **Pre-scaled**: Icons are scaled to the configured size during loading, not during rendering
3. **Shared Cache**: All UI components share the same icon instances
4. **Configurable Size**: Icon dimensions are centralized in `config.py`
5. **Memory Efficient**: Only one copy of each icon exists in memory

## Configuration

### Icon Size Setting

In `config.py`:
```python
# Icon dimensions for software logos in the script table
SOFTWARE_ICON_SIZE = 12  # Size in pixels (icons will be square: 12x12)
```

### Software Icon Paths

Software icons are configured in the `SOFTWARE` dictionary in `config.py`:
```python
SOFTWARE = {
    "windows": {
        "compatible_versions": [None],
        "logo": "resources/logos/windows.png"
    },
    "maya": {
        "compatible_versions": ["2022"],
        "logo": "resources/logos/maya.png"
    },
    "nuke": {
        "compatible_versions": ["15"],
        "logo": "resources/logos/nuke.png"
    }
}
```

## Usage

### Initialization

The icon manager is initialized early in the `GaltWindow` constructor:
```python
# Initialize icon manager early (icons are loaded once globally)
self.icon_manager = get_icon_manager()
```

### Accessing Icons

UI components can access icons through the global manager:
```python
from ..icon_manager import get_icon_manager

class SoftwareIconDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super(SoftwareIconDelegate, self).__init__(parent)
        self.icon_manager = get_icon_manager()
        self.icon_size = self.icon_manager.get_icon_size()
    
    def paint(self, painter, option, index):
        # Get pre-loaded, pre-scaled icon
        pixmap = self.icon_manager.get_icon(software)
        if pixmap:
            painter.drawPixmap(icon_rect, pixmap)
```

## Performance Benefits

### Before (On-Demand Loading)
- Icons loaded from disk when first displayed
- Each delegate instance maintained its own cache
- Icons scaled during every paint operation
- Multiple file I/O operations during scrolling

### After (Pre-loaded System)
- All icons loaded once at startup
- Single shared cache for entire application
- Icons pre-scaled to target size
- Zero file I/O during normal operation

## Technical Details

### Singleton Pattern

The `IconManager` uses the singleton pattern to ensure only one instance exists:
```python
class IconManager:
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(IconManager, cls).__new__(cls)
        return cls._instance
```

### Cache Structure

Icons are cached by software name (case-insensitive):
- Both lowercase and capitalized versions are stored for convenience
- Missing icons are cached as `None` to prevent repeated load attempts

### Thread Safety

While the current implementation doesn't use explicit locking, the manager is designed to be read-only after initialization, making it inherently thread-safe for concurrent access.

## Adding New Software Icons

To add support for a new software:

1. Add the icon file to `galt/resources/logos/`
2. Update the `SOFTWARE` dictionary in `config.py`:
   ```python
   "your_software": {
       "compatible_versions": ["1.0"],
       "logo": "resources/logos/your_software.png"
   }
   ```
3. The icon will be automatically loaded on next startup

## Best Practices

1. **Icon Format**: Use PNG format for transparency support
2. **Icon Size**: Design icons at a larger size (e.g., 64x64) for quality when scaled
3. **Consistent Style**: Maintain visual consistency across all software icons
4. **Square Dimensions**: Icons should be square for proper scaling

## Debugging

The icon manager provides debug output when `DEBUG_MODE` is enabled:
```
[GALT] DEBUG: Loading software icons...
[GALT] DEBUG: Loaded icon for maya: 12x12
[GALT] DEBUG: Loaded icon for nuke: 12x12
[GALT] INFO: Loaded 3 software icons
```

## Future Enhancements

Potential improvements:
1. **Multiple Sizes**: Pre-load icons at multiple sizes for different UI contexts
2. **Dynamic Reloading**: Support hot-reloading of icons during development
3. **Icon Themes**: Support for different icon sets/themes
4. **SVG Support**: Use vector graphics for perfect scaling at any size
5. **Lazy Loading**: Option to defer loading until first use for faster startup