# Charon Troubleshooting Guide

## Common Issues and Solutions

### Python Compatibility Errors

#### TypeError: 'type' object is not subscriptable

**Symptom:**
```
TypeError: 'type' object is not subscriptable
```

**Cause:** Using Python 3.8+ syntax in Python 3.7 environment

**Solution:**
```python
# Replace all built-in type hints with typing imports
from typing import List, Dict, Tuple, Optional, Union

# Change list[str] -> List[str]
# Change dict[str, int] -> Dict[str, int]
# Change tuple[str, ...] -> Tuple[str, ...]
```

### Threading Issues

#### Maya Freezes When Running Scripts

**Symptom:** Maya becomes unresponsive after running a script with Qt widgets

**Cause:** Qt widgets created in background thread

**Solutions:**

1. **Set run_on_main in .charon.json:**
```json
{
    "run_on_main": true,
    "script_type": "python"
}
```

2. **For MEL scripts:** Automatically run on main thread (no action needed)

3. **Check imports:** Scripts importing Qt modules auto-detect main thread requirement

#### ModuleNotFoundError with Mixed Imports

**Symptom:**
```
ModuleNotFoundError: No module named 'charon.ui'
```

**Cause:** Mixing absolute and relative imports in same module

**Solution:** Use consistent import style:
- Within Charon: Use relative imports (`from .ui import ...`)
- In tests: Use absolute imports (`from charon.ui import ...`)

### Permission Errors

#### Permission Denied When Updating Metadata

**Symptom:**
```
[CHARON] ERROR: Failed to write metadata to [path]: [Errno 13] Permission denied
```

**Cause:** Windows/network drive permission handling

**Solution:** Already implemented in codebase - the metadata writer tries:
1. Direct write with UTF-8 encoding
2. Remove read-only attributes and retry
3. Write to temp file and replace

If still failing:
- Check file ownership
- Verify network drive permissions
- Run as administrator (last resort)

### Qt/PySide Issues

#### AttributeError: module 'PySide2' has no attribute 'QtWidgets'

**Cause:** Direct PySide2/PySide6 imports instead of using qt_compat

**Solution:**
```python
# [X] WRONG
from PySide2 import QtWidgets

# [OK] CORRECT
from charon.qt_compat import QtWidgets
```

#### Qt Application Already Exists

**Symptom:** Warning about QApplication instance

**Solution:**
```python
# Safe QApplication creation
app = QApplication.instance() or QApplication([])
```

### Keybind Issues

#### Keybind Doesn't Work

**Checklist:**
1. Check Settings -> Charon Keybinds -> Is it enabled?
2. Is Charon window focused?
3. Did you reassign the shortcut in Settings?

#### Keybind Interferes with Host Software

**Solutions:**
1. Change the keybind in Settings -> Charon Keybinds
2. Disable the conflicting keybind
3. Use different keybind that doesn't conflict with host

### Execution Issues

#### Script Output Not Showing in Dialog

**Symptom:** Print statements from Qt button clicks don't appear in execution dialog

**Cause:** Output capture not maintained after main script completes

**Solution:** Implemented via Python closures - ensure you're using latest version

#### Script Runs But No Output

**Checklist:**
1. Check script's `mirror_prints` setting in .charon.json
2. Verify script is actually producing output
3. Check execution history panel for errors
4. Run with `--debug` flag for verbose output

### Cache Issues

#### Slow Performance on Network Drives

**Solutions:**
1. Enable prefetch in config.py: `CACHE_PREFETCH_ALL_FOLDERS = True`
2. Increase cache memory limit: `CACHE_MAX_MEMORY_MB = 1000`
3. Check cache stats in refresh button tooltip

#### Stale Data After External Changes

**Solution:** Click Refresh button (invalidates cache for current context)

### Icon Loading Issues

#### Missing Software Icons

**Symptom:** Generic icons instead of software-specific ones

**Solutions:**
1. Verify icon files exist in `resources/logos/`
2. Check `SOFTWARE` configuration in config.py
3. Clear icon cache by restarting Charon

### Database Issues

#### Settings Not Saving

**Symptom:** Keybinds or preferences reset on restart

**Solutions:**
1. Check database write permissions
2. Look for errors in console
3. Database location: `~/.charon/user_settings.db`
4. Try deleting database to force recreation

### ComfyUI Integration Issues

#### Model Missing in Validation

**Symptom:**
Charon reports a model as "Missing" even though it exists in the ComfyUI models directory.

**Causes:**
1. **Incorrect ComfyUI Path:** Charon might be looking at a different ComfyUI installation.
2. **Relative Path Resolution:** `folder_paths` in ComfyUI returning relative paths that resolve incorrectly.
3. **Category Mismatch:** The model is in a custom folder not recognized by standard categories.

**Solutions:**
1. **Verify ComfyUI Path:** Check Settings -> Paths to ensure the correct ComfyUI root is selected.
2. **Check `extra_model_paths.yaml`:** Ensure any custom paths in your ComfyUI configuration are correct and absolute if possible.
3. **Update Charon:** A fix for relative path resolution was added in `charon.comfy_validation`.
4. **Manual Override:** If persistent, use the "Auto Resolve" or manually specify the path if supported.

### Host-Specific Issues

#### Maya 2022 Compatibility

**Test command:**
```bash
# Windows
python software/os/run_charon.py --maya 2022

# Direct Maya test
import charon; charon.Go()
```

#### Nuke Panel Not Showing

**Solution:** Register panel in menu.py:
```python
import nuke
nuke.menu('Pane').addCommand('Charon', 'charon.launch_nuke_panel()')
```

## Debugging Techniques

### Enable Debug Mode

**In code:**
```python
# charon_logger.py
DEBUG_MODE = True
```

**Via command line:**
```bash
.venv/Scripts/python.exe tools/run_tests.py --tier scenario
```

### Trace Operations

**File system operations:**
```bash
.venv/Scripts/python.exe tests/trace_fs_operations.py
```

**Network operations:**
```bash
.venv/Scripts/python.exe tests/trace_network_operations.py
```

### Check Thread Context

```python
from charon.qt_compat import QThread
print(f"Main thread: {QThread.currentThread() == QApplication.instance().thread()}")
```

## Getting Help

### Log Locations
- Console output: Check terminal/script editor
- Execution history: In Charon UI panel
- System logs: Uses charon_logger functions

### Reporting Issues
1. Include full error message
2. Specify host software and version
3. Provide minimal reproduction steps
4. Check existing issues on GitHub

### Common Error Patterns

**Import errors:** Usually Python path or version issues
**Permission errors:** Usually Windows/network drive issues  
**Thread errors:** Usually Qt widgets on wrong thread
**Cache errors:** Usually memory limit or corruption
