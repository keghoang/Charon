# Charon Project Structure

## Root Directory
```
charon/
|-- AGENTS.md                 # Guidance for AI/code assistants
|-- README.md                 # User-facing documentation
|-- main.py                   # Standalone GUI entry point
|-- __init__.py               # Package entry point (charon.Go())
|-- config.py                 # Configuration constants
|-- metadata_manager.py       # Script metadata handling
|-- script_model.py           # Script data models
|-- script_table_model.py     # Script table Qt model
|-- folder_table_model.py     # Folder table Qt model
|-- script_validator.py       # Centralized script validation logic
|-- validation_resolver.py    # Model / custom node auto-resolve helpers
|-- cache_manager.py          # Persistent memory cache system
|-- charon_logger.py            # Logging system with strict separation
|-- utilities.py              # Utility helpers and sorting
|-- pyproject.toml            # Project dependencies
`-- uv.lock                   # Locked dependency versions
```

## Documentation (`docs/charon_panel_docs/`)
Architecture and design references:
```
docs/charon_panel_docs/
|-- README.md                     # Documentation overview
|-- 01-architecture.md            # System overview and components
|-- 02-data-patterns.md           # Data handling and threading
|-- 03-ui-patterns.md             # UI design patterns
|-- 04-host-integration.md        # Maya/Nuke integration
|-- 05-script-engine.md           # Script execution architecture
|-- 06-script-executors.md        # Script type handlers (Python, MEL)
|-- 07-keybind-architecture.md    # Keybind system design
|-- 08-qt-output-capture.md       # Qt output capture details
|-- 09-logging-system.md          # Logging architecture
|-- 10-window-management.md       # Window positioning system
|-- 11-tag-system.md              # Tag filtering system
|-- 12-tiny-mode.md               # Tiny/command mode feature
|-- 13-script-validation.md       # Script validation system
|-- 14-caching-system.md          # Performance caching
|-- 15-icon-loading-system.md     # Icon pipeline
|-- 16-development-guide.md       # Python compatibility & threading
|-- 17-troubleshooting.md         # Common issues & fixes
|-- 18-testing-guide.md           # Testing patterns & collaboration
|-- 19-configuration-reference.md # Config settings reference
`-- archive/                      # Historical documentation
    |-- 90-refactor-plan.md       # Phase 1-2 planning
    |-- 91-phase1-complete.md     # Phase 1 achievements
    `-- 92-qt-patches-info.md     # Legacy Qt patching approach
```

## Execution Engine (`charon/execution/`)
```
execution/
|-- __init__.py                   # Engine exports
|-- engine.py                     # Main execution coordinator
|-- main_thread_executor.py       # For Qt/UI scripts
|-- background_executor.py        # For computation scripts
|-- result.py                     # Execution result models
`-- script_executors/             # Script type handlers
    |-- __init__.py
    |-- base.py                   # Base executor interface
    |-- python_executor.py        # Python script execution
    |-- mel_executor.py           # MEL script execution
    `-- registry.py               # Executor registration
```

## UI Components (`charon/ui/`)
```
ui/
|-- __init__.py
|-- main_window.py                # Main application window
|-- script_panel.py               # Script browsing panel
|-- metadata_panel.py             # Script metadata editor
|-- execution_history_panel.py    # Execution history & output
|-- folder_panel.py               # Folder navigation
|-- quick_search.py               # Quick search dialog and command mode
|-- bookmarks_panel.py            # Bookmarks view (tiny mode)
|-- dialogs.py                    # Dialogs (metadata, readme, etc.)
|-- custom_widgets.py             # Custom list widgets
|-- custom_table_widgets.py       # Custom table widgets
|-- custom_delegates.py           # Delegate utilities
|-- button_delegate.py            # Run button delegate
|-- tag_bar.py                    # Vertical tag filter bar
|-- tag_manager_dialog.py         # Tag management dialog
|-- validation_dialog.py         # Validation checklist / resolve UI
|-- flash_utils.py                # Row flash helper
|-- window_manager.py             # Window creation/docking logic
`-- keybinds/                     # Keybind system
    |-- __init__.py
    |-- keybind_manager.py        # Keybind coordinator
    |-- local_handler.py          # Local UI shortcuts
    `-- settings_ui.py            # Keybind settings dialog
```

## Tests (`tests/`)
```
tests/
|-- README.md                     # Testing guide
|-- test_*.py                     # Feature test files
|-- cli/                          # CLI testing tools
|    |-- cli_full.py               # Full-featured CLI
|    `-- cli_simple.py             # Simple CLI interface
`-- test_scripts/                 # Mock script repository
    |-- simple_test/              # Basic execution test
    |-- qt_test/                  # Interactive Qt test
    |-- qt_test_auto/             # Auto-closing Qt test
    `-- test_intercept_prints/    # Output capture test
```

## Settings (`charon/settings/`)
```
settings/
`-- user_settings_db.py           # SQLite-based settings storage
```

## Software Launchers (`software/`)
```
software/
|-- maya/                         # Maya shelf integration
|-- nuke/                         # Nuke menu integration
`-- os/
    |-- README.md
    |-- run_charon.bat              # Windows launcher
    |-- run_charon.sh               # macOS/Linux launcher
    `-- run_charon.py               # Cross-platform launcher script
```

## Virtual Environment (`.venv/`)
```
.venv/
`-- Scripts/python.exe            # Windows Python with PySide2/PySide6
```

## Key Reference Files
- `main.py` / `__init__.py` - Primary entry points (`charon.Go()` and standalone launch)
- `config.py` - Core configuration constants and search paths
- `metadata_manager.py` - `.charon.json` handling utilities
- `utilities.py` - Shared helpers (host detection, sorting, markdown)
- `charon/execution/engine.py` - Routes scripts to the correct executor

## Usage Patterns

### Development
```bash
# Launch Charon GUI
.venv/Scripts/python.exe main.py

# Run unit tests
.venv/Scripts/python.exe tools/run_tests.py --tier unit

# Run headless UI smoke tests
.venv/Scripts/python.exe tools/run_tests.py --tier headless

# Explore with fixture scripts
.venv/Scripts/python.exe main.py --global-path tests/fixtures/scripts
```

### Production (Maya/Nuke)
```python
import charon
charon.Go()  # Auto-detects host
```

### CLI Helpers
```bash
# Run scenario suite
.venv/Scripts/python.exe tools/run_tests.py --tier scenario
```


## Architecture Highlights
- Dual-mode execution keeps UI responsive while supporting Qt scripts safely
- Relative imports ensure consistency across hosts without polluting `sys.path`
- Persistent caching reduces network load for large repositories
- Extensible script executor registry makes it easy to add new script types

## Host Compatibility Snapshot
- **Windows/macOS/Linux**: Full standalone support with PySide auto-detection
- **Maya 2020-2024**: PySide2 integration
- **Maya 2025+**: PySide6 integration
- **Nuke 13-15**: PySide2 integration
- **Nuke 16+**: PySide6 integration

_Future host integrations (e.g., Houdini, Blender) are exploratory only; see documentation for roadmap notes._
