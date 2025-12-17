# Galt Window Management System

This document describes Galt's window creation and docking management system for different host applications.

## Overview

The `WindowManager` class provides a centralized, extensible system for:
- Creating host-appropriate windows (floating tools, docked panels, etc.)
- Managing window flags and behavior per host
- Handling docking where supported
- Providing fallback behavior for unknown hosts

## Architecture

```python
WindowManager
|-- create_window()      # Creates appropriate window for host
|    |-- _create_standalone()      # Standalone Qt window
|    |-- _create_maya_docked()     # Maya workspaceControl
|    `-- _create_nuke_docked()     # Nuke panel registration
|
`-- dock_window()        # Docks window if host supports it
    |-- _dock_maya_window()        # Maya dockControl
    `-- _dock_nuke_window()        # Nuke panel fallback
```

## Usage

### Basic Usage

```python
from ui.window_manager import WindowManager
from ui.main_window import GaltWindow

# Create window manager
manager = WindowManager()

# Create your Galt widget
galt = GaltWindow(host="maya")

# Create appropriate window
window = manager.create_window(galt, host="maya", title="Galt - Maya")

# Optionally dock it
manager.dock_window(window, host="maya", dock_area="right")

# Show the window
window.show()
```

### Convenience Function

```python
from ui.window_manager import create_galt_window

# Create and optionally dock in one call
window = create_galt_window(
    galt_widget,
    host="maya",
    dock=True,
    dock_area="right",
    title="Galt Script Launcher"
)
```

## Host-Specific Behavior

### Default (Unknown Hosts)
- Creates a floating tool window
- `Qt.Tool` flag for proper tool window behavior
- Optional `Qt.WindowStaysOnTopHint`
- No docking support

### Maya
**Window Creation:**
- Parents to Maya's main window
- Proper window flags for Maya integration
- Maintains Maya's window management

**Docking:**
- Uses `cmds.dockControl`
- Supports left/right docking
- Can start floating or docked
- Remembers dock state

### Nuke
**Window Creation:**
- Currently uses default floating behavior
- Future: Could register as Nuke panel

**Docking:**
- Placeholder for future panel registration
- Currently falls back to floating

### Houdini (Roadmap)
**Window Creation:**
- Integration not implemented; tracked as future work

**Docking:**
- No docking support today; would rely on Houdini's panel system once prioritized

### Blender (Roadmap)
**Note:** No integration today; Blender lacks native Qt so support would require a custom windowing path.

## Window Options

### create_window() Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `title` | str | "Galt" | Window title |
| `as_tool` | bool | True | Use Qt.Tool flag |
| `stay_on_top` | bool | False | Window stays on top |

### dock_window() Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `dock_area` | str | "right" | Where to dock (left/right/top/bottom) |
| `dock_name` | str | "GaltDock" | Internal dock control name |
| `label` | str | "Galt" | Dock tab label |
| `floating` | bool | False | Start floating (Maya) |

## Extending for New Hosts

To add support for a new host application:

### 1. Add Window Creator

```python
def _create_newhost_window(self, content_widget: QtWidgets.QWidget, 
                          options: Dict[str, Any]) -> QtWidgets.QWidget:
    """Create a window for NewHost."""
    try:
        import newhost_api
        
        # Host-specific window setup
        # ...
        
        return content_widget
    except Exception as e:
        system_error(f"Failed to create NewHost window: {e}")
        return self._create_default_window(content_widget, options)
```

### 2. Register in __init__

```python
self._window_creators["newhost"] = self._create_newhost_window
```

### 3. Add Docking Support (Optional)

```python
def _dock_newhost_window(self, window: QtWidgets.QWidget, 
                        dock_area: str, options: Dict[str, Any]) -> None:
    """Dock window in NewHost."""
    try:
        import newhost_api
        # Docking implementation
    except Exception as e:
        system_error(f"Failed to dock in NewHost: {e}")
        raise

# Register in __init__
self._dockers["newhost"] = self._dock_newhost_window
```

## Best Practices

1. **Always provide fallbacks** - Unknown hosts should get reasonable defaults
2. **Handle import failures** - Host APIs might not be available
3. **Use system logging** - Log window operations for debugging
4. **Test in host** - Window behavior can vary between hosts
5. **Preserve user preferences** - Remember dock states, positions, etc.

## Integration with Existing Code

The window manager can be integrated gradually:

1. **1**: Use for new window creation
2. **2**: Migrate existing launch code
3. **3**: Add user preferences for window state
4. **4**: Implement host-specific features