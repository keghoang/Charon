# Charon Logging System

This document describes Charon's logging system which provides clear separation between system messages and script output.

## Overview

Charon uses a structured logging approach to ensure:
- **System messages** (Charon's operational messages) appear in the terminal with a `[CHARON]` prefix
- **Script output** (user script prints) appears in the ExecutionDetailsDialog and optionally in the terminal

This separation makes it easy to distinguish between what Charon is doing internally and what the user's scripts are outputting.

## System Messages

### Available Functions

All logging functions are imported from `charon_logger`:

```python
from charon_logger import system_info, system_debug, system_warning, system_error
```

#### `system_info(message: str)`
For normal operational messages that users should see:
```python
system_info("Host detected/forced as: Maya")
system_info("Created Maya docked window (workspaceControl)")
system_info("Note: Script requires main thread for Qt widgets")
```

Note: Many verbose info messages have been moved to `system_debug()` to reduce terminal spam.

#### `system_debug(message: str)`
For debug messages (only shown when `config.DEBUG_MODE = True`):
```python
system_debug("Executing script: test_script.py")
system_debug("Mode: main_thread (from metadata)")
system_debug("Script called QApplication.quit() - ignoring")
system_debug("Reconstructed path: old_path -> new_path")
system_debug("Using script_paths: [list of paths]")
```

Many previously verbose `system_info()` calls have been moved here, including:
- Path reconstruction messages
- Metadata cache clearing
- Script path corrections
- Tag manager initialization details

#### `system_warning(message: str)`
For warning messages:
```python
system_warning("Current base path does not exist: /invalid/path")
system_warning("Script execution timeout (30000ms) - stopping script")
system_warning("Qt widgets detected in script - requires main thread")
```

#### `system_error(message: str)`
For error messages:
```python
system_error(f"Error creating directory {path}: {str(e)}")
system_error("Error checking bookmarks: File not found")
system_error("Error refreshing keybinds: Invalid key combination")
```

### Special Cases

#### Thread Override Messages
When a script is redirected from background to main thread, use `print_to_terminal()`:
```python
from charon_logger import print_to_terminal
print_to_terminal("Note: Script imports PySide2 - Qt widgets require main thread")
```

This ensures the message appears in the terminal but NOT in the ExecutionDetailsDialog.

#### Qt Messages
Qt messages are automatically routed through the logging system:
```python
from charon_logger import qt_message_handler
QtCore.qInstallMessageHandler(qt_message_handler)
```

## Script Output

Script output is handled differently from system messages:

1. **Captured automatically** via stdout/stderr redirection
2. **Displayed in ExecutionDetailsDialog** 
3. **Optionally mirrored to terminal** based on the script's `mirror_prints` setting

### How It Works

```python
# In MainThreadExecutor and BackgroundExecutor
class OutputCapture:
    def write(self, text: str):
        # Always write to buffer for dialog
        self.buffer.append(text)
        # Emit output update for ExecutionDetailsDialog
        self.executor.output_updated.emit(self.execution_id, text)
        # Only write to terminal if mirror_prints is True
        if self.mirror_to_terminal:
            self.original_stream.write(text)
```

## Implementation Guidelines

### DO Use Logging Functions

Replace all system print statements with appropriate logging functions:

```python
# ❌ Bad - Using print() for system messages
print(f"Error: {e}")
print("Starting execution...")
print("Warning: File not found")

# ✅ Good - Using logging functions
system_error(f"Error: {e}")
system_info("Starting execution...")
system_warning("File not found")
```

### DON'T Mix System and Script Output

System messages should NEVER appear in the ExecutionDetailsDialog:

```python
# ❌ Bad - System message in script namespace
def execute_script():
    print("Executing script...")  # This would go to ExecutionDetailsDialog!
    exec(code, script_namespace)

# ✅ Good - System message via logging
def execute_script():
    system_info("Executing script...")  # Goes to terminal only
    exec(code, script_namespace)
```

### Debug Mode Handling

Use `system_debug()` for verbose/debug messages:

```python
# ❌ Bad - Manual debug mode check
if config.DEBUG_MODE:
    print(f"Debug: Processing {file}")

# ✅ Good - Automatic debug mode handling
system_debug(f"Processing {file}")
```

## Terminal Output Format

System messages appear with consistent formatting:

```
[CHARON] INFO: Host detected/forced as: Maya
[CHARON] WARNING: Current base path does not exist: /invalid/path
[CHARON] ERROR: Error creating directory: Permission denied
[CHARON] DEBUG: Executing script: test.py
```

## Migration Guide

When updating existing code:

1. **Identify system prints**: Look for `print()` statements in Charon's code (not user scripts)
2. **Categorize the message**:
   - Normal operation → `system_info()`
   - Debug/verbose → `system_debug()`
   - Problems/warnings → `system_warning()`
   - Errors/failures → `system_error()`
3. **Import logging functions**: Add `from charon_logger import ...` or `from ..charon_logger import ...`
4. **Replace the print call**: Change `print(msg)` to appropriate function

## Testing

Add a unit test under `tests/unit/` when logging behaviour changes:
- System messages appear with `[CHARON]` prefix in terminal
- Script output appears in ExecutionDetailsDialog
- Thread override messages stay out of ExecutionDetailsDialog
- Debug messages respect `DEBUG_MODE` setting

## Future Enhancements

The logging system is designed to be extensible:
- Could add file logging for persistent logs
- Could add log levels configuration
- Could add remote logging for debugging in production
- Could add structured logging (JSON format) for analysis

Currently, we keep it simple with terminal output only for system messages.
