# Charon Architecture Documentation

This directory contains comprehensive architecture and design documentation for the Charon project.

## Current Architecture 

**Execution Engine** - Dual-mode execution system:
- **Main Thread Executor**: For Qt/UI scripts (`run_on_main: true`)
- **Background Executor**: For pure computation scripts (default)
- **No Qt Patching**: Clean architecture without monkey-patching Qt

**Import System** - Relative imports within Charon package:
- Internal imports use `.` prefix (e.g., `from .ui.main_window import CharonWindow`)
- Ensures compatibility across Windows, Maya, and Nuke (future hosts documented separately)
- Scripts run in isolated namespaces with proper import paths

**Thread Safety**:
- Qt widgets MUST run on main thread (especially critical in Maya)
- Background threads handle pure computation efficiently
- Thread pool limiting prevents resource exhaustion

## Documentation Files

### Core Architecture (01-05)
- **01-architecture.md** - System overview and component relationships
- **02-data-patterns.md** - Data handling, threading, and background processing patterns  
- **03-ui-patterns.md** - UI design patterns and component structure
- **04-host-integration.md** - Maya/Nuke integration patterns and host detection
- **05-script-engine.md** - Script execution engine architecture and threading model

### Features and Extensions (06-11)
- **06-script-executors.md** - Script type handlers (Python, MEL, extensible system)
- **07-keybind-architecture.md** - Keybind system with local/global separation and cleanup
- **08-qt-output-capture.md** - WARNING: Qt event handler output capture implementation
- **09-logging-system.md** - System message logging and output separation
- **10-window-management.md** - Window creation and docking for different hosts
- **11-tag-system.md** - Tag-based script organization with batched updates

### Recent Improvements
- **Context Menus**: Right-click empty space for "New Script" and "Open Folder"
- **Panel Indicators**: Collapsible panels show << >> indicators, clickable to reopen
- **Execution Dialog**: Real-time updates, monospace font, minimal interface
- **Tag System**: Batched updates prevent UI flicker during tag operations
- **Hotkey Cleanup**: Automatic purge of missing scripts on startup and refresh

### Project Information
- **PROJECT_STRUCTURE.md** - Complete project file organization

### Historical Archive
- **archive/** - Historical planning and implementation documents
  - Phase 1-2 refactor plans
  - Old Qt patching approach documentation

## Key Architecture Decisions

### Execution Model
- Scripts declare execution preference via `.charon.json` metadata
- `run_on_main: true` for UI/widget scripts
- Background execution is default for better performance
- Automatic detection of Qt usage with helpful error messages

### Host Compatibility
- **Windows/macOS/Linux**: PySide2/PySide6 auto-detection
- **Maya 2020-2024**: PySide2 integration
- **Maya 2025+**: PySide6 integration  
- **Nuke 13-15**: PySide2 integration
- **Nuke 16+**: PySide6 integration
- **Roadmap**: Potential Houdini/Blender support (not implemented yet)

### Import Architecture
- Relative imports (`.` prefix) within Charon package
- Absolute imports (`charon.*`) from external code/tests
- Scripts execute in isolated namespaces
- No sys.path pollution

## Recent Changes 

1. **Removed qt_patcher.py** - No more monkey-patching
2. **Implemented dual executors** - Clean separation of concerns
3. **Fixed relative imports** - Consistent across all hosts
4. **Added execution history** - Track script runs with output
5. **Improved error handling** - Clear messages for Qt threading issues

## Critical Warnings

WARNING: Qt Threading: Qt widgets in background threads will freeze Maya. Always use `run_on_main: true` for UI scripts.

WARNING: Import Patterns: Never mix relative and absolute imports within the same module.

WARNING: Host Testing: Always verify changes work in both standalone and hosted environments.

WARNING: Qt Output Capture: MUST use closure-based capture for Qt event handlers. See **08-qt-output-capture.md** for details. Never reference `sys.stdout` in `captured_print` - use the capture objects directly.

## Reading Order

For new developers:
1. Start with **01-architecture.md** for system overview
2. Read **05-script-engine.md** for execution model
3. Review **04-host-integration.md** for Maya/Nuke specifics
4. Check **PROJECT_STRUCTURE.md** for code organization

## Maintenance Notes

- Update relevant architecture files when making significant changes
- Test across Windows and Maya environments (Nuke when available)
- Keep import patterns consistent (relative within package)
- Document any host-specific behaviors or workarounds
