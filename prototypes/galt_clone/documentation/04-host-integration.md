# Galt Host Integration Patterns

## Host Detection

### Detection Logic in [utilities.py](md:utilities.py)
```python
def detect_host():
    try:
        import nuke
        return "Nuke"
    except ImportError:
        try:
            import maya.OpenMayaUI as omui
            return "Maya"
        except ImportError:
            import platform
            system = platform.system()
            if system == "Windows":
                return "Windows"
            elif system == "Darwin":  # macOS
                return "Macos"
            elif system == "Linux":
                return "Linux"
            else:
                return "Windows"  # Default fallback
```

### Host-Specific Configuration
- Software colors defined in [config.py](md:config.py)
- Host-specific embedding logic in [__init__.py](md:__init__.py)
- Compatibility checking in [utilities.py](md:utilities.py)

## Embedding Patterns

### Maya Integration
```python
def _create_maya_workspace_control():
    import maya.cmds as cmds
    import maya.OpenMayaUI as omui
    from galt.qt_compat import QtWidgets, QtCore
    import shiboken2  # Note: May need shiboken6 for Maya 2025+
    
    ctrl_name = "GaltWorkspace"
    if cmds.workspaceControl(ctrl_name, exists=True):
        cmds.deleteUI(ctrl_name)
    
    ctrl = cmds.workspaceControl(
        ctrl_name,
        label="Galt",
        initialWidth=config.WINDOW_WIDTH,
        initialHeight=config.WINDOW_HEIGHT,
        floating=True
    )
    
    ptr = omui.MQtUtil.findControl(ctrl_name)
    widget = shiboken2.wrapInstance(int(ptr), QtWidgets.QWidget)
    return widget
```

### Nuke Integration
```python
def _create_nuke_panel():
    import nukescripts.panels as panels
    
    def create_galt_panel():
        return _create_galt_widget(
            host_override="Nuke",
            show_window=False
        )
    
    panels.registerWidgetAsPanel(
        "create_galt_panel",
        "Galt",
        "GaltPanel"
    )
```

### Standalone Mode
```python
def _create_galt_widget(show_window=True):
    if show_window:
        from galt.qt_compat import QtWidgets
        import sys
        
        app = None
        if not QtWidgets.QApplication.instance():
            app = QtWidgets.QApplication(sys.argv)
        
        window = GaltWindow(...)
        window.show()
        
        if app:
            sys.exit(app.exec_())
```

## Script Execution

### Host-Specific Execution
```python
def _execute_script(self, script_path):
    # Check compatibility
    metadata = get_galt_config(script_path)
    if metadata and not is_compatible_with_host(metadata, self.host):
        return
    
    # Find entry file
    entry_file = self._find_entry_file(script_path)
    
    # Execute based on type
    if entry_file.endswith('.py'):
        # Python execution
        if script_path not in sys.path:
            sys.path.insert(0, script_path)
        exec(code, __main__.__dict__)
    elif entry_file.endswith('.mel') and self.host.lower() == "maya":
        # MEL execution
        import maya.mel as mel
        mel.eval(f'source "{entry_file}"')
```

## Compatibility Checking

### Software Compatibility
```python
def is_compatible_with_host(metadata, host):
    if not metadata or "software" not in metadata:
        return True  # No restrictions
    
    software_list = metadata["software"]
    if not software_list:
        return True  # Empty list means compatible with all
    
    return host in software_list
```

### Visual Feedback
- Incompatible items shown with reduced opacity
- Color coding based on software compatibility
- Special folders (Bookmarks, Hotkeys) for cross-host organization

## Configuration

### Host-Specific Settings
```python
# In config.py - Unified SOFTWARE configuration
SOFTWARE = {
    "windows": {
        "compatible_versions": [None],
        "logo": "resources/logos/windows.png",
        "color": "#27ae60",  # Green
        "pyside_version": None,  # Auto-detect
        "hidden": False  # Show in dialogs
    },
    "maya": {
        "compatible_versions": {
            "2020": {"pyside": 2},
            "2022": {"pyside": 2},
            "2025": {"pyside": 6}
        },
        "logo": "resources/logos/maya.png",
        "color": "#3498db",  # Blue
        "pyside_version": None,
        "hidden": False
    },
    # ... other software
}

# Legacy SOFTWARE_COLORS kept for backward compatibility
SOFTWARE_COLORS = {
    "Windows": "#27ae60",
    "Maya": "#3498db",
    # ... etc
}

INCOMPATIBLE_OPACITY = 0.5  # opacity for greyed out items
```

## Development Guidelines

### Adding New Hosts
1. Update `detect_host()` in [utilities.py](md:utilities.py)
2. Add embedding logic in [__init__.py](md:__init__.py)
3. Add entry to `SOFTWARE` dictionary in [config.py](md:config.py) with:
   - `compatible_versions`
   - `logo` path
   - `color` for UI elements
   - `pyside_version` requirements
   - `hidden` flag for dialog visibility
4. Add execution logic if needed

### Host-Specific Features
- Use `self.host` parameter throughout UI components
- Implement `set_host()` method in panels
- Check compatibility before script execution
- Provide host-specific visual feedback
description:
globs:
alwaysApply: false
---
