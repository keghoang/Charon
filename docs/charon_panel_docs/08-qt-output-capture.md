# Qt Script Output Capture - Critical Implementation Details

## Overview

This document explains a critical implementation detail for capturing output from Qt scripts, particularly when Qt event handlers (button clicks, timers, etc.) print output after the main script execution completes.

## The Problem

When executing Qt scripts that create widgets with event handlers (like buttons), the output from these handlers may not be captured in the execution dialog if the implementation is incorrect. This happens because:

1. The main script execution completes
2. `sys.stdout` is restored to the original in the `finally` block
3. Qt widgets remain open and their event handlers fire later
4. These event handlers print to the restored `sys.stdout` (console) instead of our capture

## The Solution: Python Closures

The solution relies on Python's closure mechanism to maintain references to the output capture objects even after `sys.stdout` is restored.

### Incorrect Implementation ❌
```python
def captured_print(*args, **kwargs):
    """This will FAIL after sys.stdout is restored"""
    import io
    buffer = io.StringIO()
    kwargs['file'] = buffer
    original_print(*args, **kwargs)
    # WRONG: References sys.stdout which will be restored
    output_capture = sys.stdout if 'stderr' not in kwargs else sys.stderr
    output_capture.write(buffer.getvalue())
```

### Correct Implementation ✅
```python
def captured_print(*args, **kwargs):
    """This WORKS because it closes over the capture objects"""
    import io
    buffer = io.StringIO()
    kwargs['file'] = buffer
    original_print(*args, **kwargs)
    # CORRECT: References capture objects directly via closure
    output_capture = stdout_capture if 'stderr' not in kwargs else stderr_capture
    output_capture.write(buffer.getvalue())
```

## Implementation Details

### 1. Capture Object Creation
In `main_thread_executor.py`, the capture objects are created in `_execute_script_sync`:

```python
# Create output capture objects
stdout_capture = MainThreadOutputCapture(execution_id, self, original_stdout, mirror_prints)
stderr_capture = MainThreadOutputCapture(execution_id, self, original_stderr, mirror_prints)
```

### 2. Passing to Python Patches
These capture objects must be passed to `_apply_python_patches`:

```python
if script_type.lower() == "python":
    script_namespace = self._apply_python_patches(
        script_namespace, mirror_prints, stdout_capture, stderr_capture
    )
```

### 3. Creating the Closure
In `_apply_python_patches`, the `captured_print` function creates a closure over these objects:

```python
def _apply_python_patches(self, script_namespace, mirror_prints, stdout_capture, stderr_capture):
    # ... other code ...
    
    def captured_print(*args, **kwargs):
        """Custom print that ensures output goes to capture even in Qt event handlers"""
        # This function has access to stdout_capture and stderr_capture
        # through Python's closure mechanism
        import io
        buffer = io.StringIO()
        kwargs['file'] = buffer
        original_print(*args, **kwargs)
        # Direct reference to capture objects, not sys.stdout
        output_capture = stdout_capture if 'stderr' not in kwargs else stderr_capture
        output_capture.write(buffer.getvalue())
    
    # Inject into script namespace
    script_namespace['print'] = captured_print
```

## Why This Works

1. **Closure Creation**: When `captured_print` is defined inside `_apply_python_patches`, it creates a closure that captures references to `stdout_capture` and `stderr_capture`.

2. **Reference Persistence**: Even after the `finally` block restores `sys.stdout` to the original, the `captured_print` function still has references to the capture objects.

3. **Qt Event Handlers**: When Qt buttons are clicked or timers fire, they call `print()` which is our `captured_print` function. This function writes to the capture objects, not `sys.stdout`.

## Testing

To test this functionality:

1. Run a Qt script that creates buttons with print statements
2. Click the buttons AFTER the script execution completes
3. Verify the output appears in the execution dialog, not just the console

Example test script (`tests/fixtures/scripts/main_thread_qt/main.py`):
```python
from charon.qt_compat import QApplication, QPushButton, QVBoxLayout, QWidget

app = QApplication.instance() or QApplication([])
window = QWidget()
window.setWindowTitle("QuickQT")

layout = QVBoxLayout()
hi_button = QPushButton("hi")
hi_button.clicked.connect(lambda: print("hi"))
layout.addWidget(hi_button)

window.setLayout(layout)
window.show()
```

## Common Mistakes to Avoid

1. **Don't reference sys.stdout in captured_print**: Always use the capture objects passed via closure
2. **Don't forget to pass capture objects**: Ensure they're passed from `_execute_script_sync` to `_apply_python_patches`
3. **Don't define captured_print outside the closure scope**: It must have access to the capture objects

## Summary

The key to capturing Qt event handler output is using Python closures to maintain references to the output capture objects. This ensures that even after `sys.stdout` is restored, Qt event handlers can still write to our capture system, making their output appear in the execution dialog where users expect to see it.