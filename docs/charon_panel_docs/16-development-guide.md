# Charon Development Guide

## Python Version Compatibility

Charon must maintain compatibility with Python 3.7+ to support all VFX applications.

### Type Hints (Python 3.7 vs 3.8+)

**Always import from typing module:**
```python
from typing import Dict, List, Tuple, Optional, Union, Any, Set
```

**Common compatibility issues:**

```python
# ❌ WRONG (Python 3.8+)
def func() -> list[str]:
    pass

def process() -> dict[str, int]:
    pass

def get_data() -> tuple[str, int]:
    pass

# ✅ CORRECT (Python 3.7+)
from typing import List, Dict, Tuple

def func() -> List[str]:
    pass

def process() -> Dict[str, int]:
    pass

def get_data() -> Tuple[str, int]:
    pass
```

**Union types:**
```python
# ❌ WRONG (Python 3.10+)
def process(data: str | int):
    pass

# ✅ CORRECT (Python 3.7+)
from typing import Union

def process(data: Union[str, int]):
    pass
```

**Optional types:**
```python
# ❌ WRONG
def func(val: str | None):
    pass

# ✅ CORRECT
from typing import Optional

def func(val: Optional[str]):
    pass
```

### Syntax Features to Avoid

**Match statements (Python 3.10+):**
```python
# ❌ WRONG
match command:
    case "run":
        execute()
    case "stop":
        halt()

# ✅ CORRECT
if command == "run":
    execute()
elif command == "stop":
    halt()
```

**Walrus operator (Python 3.8+):**
```python
# ❌ WRONG
if (n := len(data)) > 10:
    print(f"List is too long ({n} elements)")

# ✅ CORRECT
n = len(data)
if n > 10:
    print(f"List is too long ({n} elements)")
```

## Threading Rules

### Main Thread Requirements

**MUST run on main thread:**
- ALL Qt/PySide2/PySide6 widget creation and manipulation
- MEL script execution (MEL is not thread-safe)
- Maya API calls
- Window creation/showing

**Can run on background thread:**
- File I/O operations
- Network requests
- Data processing
- Calculations

### Thread Compatibility System

The execution engine automatically determines thread requirements:

```python
# In script's .charon.json
{
    "run_on_main": true,  # Forces main thread execution
    "script_type": "python"
}
```

**Automatic main thread detection:**
- MEL scripts → Always main thread
- Scripts importing Qt modules → Main thread
- Scripts with `run_on_main: true` → Main thread

### Qt Widget Threading

**Creating widgets (MUST be on main thread):**
```python
# This will freeze Maya if run on background thread
window = QWidget()
window.show()  # CRASH/FREEZE if not on main thread
```

**Safe pattern for background operations:**
```python
class Worker(QThread):
    result_ready = Signal(object)
    
    def run(self):
        # Do heavy computation
        result = process_data()
        self.result_ready.emit(result)

# On main thread
worker = Worker()
worker.result_ready.connect(update_ui)  # update_ui runs on main thread
worker.start()
```

## Import Patterns

### Within Charon Package

**Use relative imports:**
```python
# In charon/ui/main_window.py
from .folder_panel import FolderPanel
from .script_panel import ScriptPanel
from ..execution.engine import ExecutionEngine
from ..metadata_manager import get_charon_config
```

### In Tests and External Scripts

**Use absolute imports:**
```python
# In tests/headless_ui/test_execution_engine.py
from charon.execution.engine import ExecutionEngine
from charon.ui.main_window import CharonWindow
```

### Common Import Errors

```python
# ❌ WRONG - Mixed imports in same module
from .utils import helper  # relative
from charon.config import SETTINGS  # absolute

# ✅ CORRECT - Consistent imports
from .utils import helper
from .config import SETTINGS
```

## Host Integration

### Detecting Host Environment

```python
def get_host_type():
    """Returns 'maya', 'nuke', 'windows', or 'generic'"""
    # Check Nuke first (most specific)
    try:
        import nuke
        return "nuke"
    except ImportError:
        pass
    
    # Check Maya
    try:
        import maya.cmds
        return "maya"
    except ImportError:
        pass
    
    # Check Windows
    import platform
    if platform.system() == "Windows":
        return "windows"
    
    return "generic"
```

### Host-Specific Embedding

**Maya Integration:**
```python
# Use workspaceControl for docking
from maya import cmds
workspace_name = "CharonWorkspace"
if cmds.workspaceControl(workspace_name, exists=True):
    cmds.deleteUI(workspace_name)
    
cmds.workspaceControl(
    workspace_name,
    retain=False,
    floating=True,
    uiScript=f"charon.Go(embedded=True, workspace_control_name='{workspace_name}')"
)
```

**Nuke Integration:**
```python
# Use registerWidgetAsPanel
import nuke
nuke.menu('Pane').addCommand(
    'Charon', 
    'charon.launch_nuke_panel()'
)
```

## File Operations Best Practices

### Reading Files

**Always handle encoding:**
```python
# ✅ CORRECT
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()
```

### Writing Files with Permissions

**Handle permission errors on network drives:**
```python
def write_json_file(file_path, data):
    try:
        # Try direct write
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    except PermissionError:
        # Try removing read-only flag
        import stat
        os.chmod(file_path, stat.S_IWRITE)
        
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
        except PermissionError:
            # Write to temp and replace
            temp_path = file_path + '.tmp'
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
            os.replace(temp_path, file_path)
```

## Memory Management

### Cache Eviction

```python
# Automatic eviction when memory limit reached
if self._estimate_memory_usage() > self.max_memory_bytes:
    self._evict_old_entries()
```

### Hot Folder Protection

```python
# Hot folders are protected from eviction
for path, entry in self.folder_cache.items():
    if path not in self.hot_folders:  # Only evict non-hot folders
        all_entries.append((entry.timestamp, 'folder', path))
```