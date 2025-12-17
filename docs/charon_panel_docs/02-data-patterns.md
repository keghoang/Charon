# Charon Data Handling Patterns

## Background Processing

### QThread Loader Pattern
```python
class BaseScriptLoader(QtCore.QThread):
    scripts_loaded = QtCore.Signal(list)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._should_stop = False
    
    def stop_loading(self):
        self._should_stop = True
        if self.isRunning():
            self.wait(1000)
    
    def run(self):
        # Background work here
        if not self._should_stop:
            self.scripts_loaded.emit(results)
```

### ThreadPoolExecutor for Parallel Processing
```python
from concurrent.futures import ThreadPoolExecutor, as_completed

with ThreadPoolExecutor(max_workers=4) as executor:
    future_to_item = {executor.submit(process_item, item): item for item in items}
    for future in as_completed(future_to_item):
        if self._should_stop:
            for f in future_to_item: f.cancel()
            return
```

## Metadata Management

### LRU Caching Pattern
```python
import functools

@functools.lru_cache(maxsize=1024)
def get_charon_config(script_path):
    # Load and return metadata
    return metadata
```

### Metadata File Structure
```json
{
    "software": ["Maya", "Nuke"],
    "entry": "main.py",
    "script_type": "python",
    "run_on_main": true,
    "mirror_prints": true,
    "tags": ["animation", "rigging", "utility"]
}
```

#### Metadata Fields
- `software`: List of compatible software (Maya, Nuke, Windows, etc.)
- `entry`: Entry point script file (e.g., "main.py")
- `script_type`: Script language ("python" or "mel")
- `run_on_main`: Whether to run on main thread (required for Qt/GUI scripts)
- `mirror_prints`: Whether to mirror output to terminal
- `tags`: List of categorization tags for the script

Note: The `display` field has been deprecated and removed.

## Database Operations

### SQLite Connection Pattern
```python
def get_connection():
    return sqlite3.connect(_get_db_path())

def some_database_operation():
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM table")
        return cursor.fetchall()
    finally:
        conn.close()
```

### Error Handling for Database
- Always use try/finally to ensure connections are closed
- Log errors but don't crash the application
- Provide fallback values for missing data

## Data Models

### ScriptItem Structure
```python
class ScriptItem:
    def __init__(self, name, path, metadata=None, host="None"):
        self.name = name
        self.path = path
        self.metadata = metadata
        self.host = host
        self.is_bookmarked = False
```

### Qt Model Implementation
```python
class ScriptListModel(QtCore.QAbstractListModel):
    NameRole = QtCore.Qt.UserRole + 1
    MetadataRole = QtCore.Qt.UserRole + 2
    PathRole = QtCore.Qt.UserRole + 3
    
    def data(self, index, role):
        if not index.isValid():
            return None
        script = self.scripts[index.row()]
        if role == self.NameRole:
            return script.name
        # ... other roles
```

## File References
- Script models: [script_model.py](md:script_model.py)
- Metadata management: [metadata_manager.py](md:metadata_manager.py)
- Database operations: [settings/user_settings_db.py](md:settings/user_settings_db.py)
- Utilities: [utilities.py](md:utilities.py)
description:
globs:
alwaysApply: false
---
