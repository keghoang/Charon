# Charon Architecture Overview

## Core Entry Points
- Main entry point: [__init__.py](md:__init__.py) - `charon.Go()` function
- Direct launch: [main.py](md:main.py) - `launch()` function
- Launcher scripts: [`software/os/run_charon.py`](md:software/os/run_charon.py)

## Key Components

### UI Architecture
- Main window: [ui/main_window.py](md:ui/main_window.py) - `CharonWindow` class orchestrates all UI
- Folder panel: [ui/folder_panel.py](md:ui/folder_panel.py) - Displays script folders and special folders
- Script panel: [ui/script_panel.py](md:ui/script_panel.py) - Shows scripts within selected folder
- Metadata panel: [ui/metadata_panel.py](md:ui/metadata_panel.py) - Edits script metadata
- Qt compatibility: [qt_compat.py](md:qt_compat.py) - Unified PySide2/PySide6 import system

### Data Models & Background Processing
- Script models: [script_model.py](md:script_model.py), [script_table_model.py](md:script_table_model.py), [folder_table_model.py](md:folder_table_model.py) - Table models and loaders
- Background loaders: `GlobalIndexLoader`, `FolderLoader`, `BookmarkLoader`, `HotkeyLoader`

### Configuration & Utilities
- Configuration: [config.py](md:config.py) - All constants and settings
- Core utilities: [utilities.py](md:utilities.py) - Host detection, compatibility checking
- Metadata management: [metadata_manager.py](md:metadata_manager.py) - JSON metadata handling

### Database & Settings
- User settings: [settings/user_settings_db.py](md:settings/user_settings_db.py) - SQLite database operations

### UI Components
- Custom widgets: [ui/custom_widgets.py](md:ui/custom_widgets.py), [ui/custom_table_widgets.py](md:ui/custom_table_widgets.py) - Enhanced list and table views
- Custom delegates: [ui/custom_delegates.py](md:ui/custom_delegates.py) - Run button rendering
- Dialogs: [ui/dialogs.py](md:ui/dialogs.py) - Metadata, readme, hotkey dialogs
- Quick search: [ui/quick_search.py](md:ui/quick_search.py) - Global script search
- Tag system: [ui/tag_bar.py](md:ui/tag_bar.py), [ui/tag_manager_dialog.py](md:ui/tag_manager_dialog.py) - Tag filtering and management
- Keybind system: [ui/keybinds/](md:ui/keybinds/) - Local and global hotkey management

## Key Design Patterns

### Signal/Slot Communication
- Folder selection: `FolderPanel.folder_selected` -> `MainWindow.on_folder_selected` -> `ScriptPanel.load_scripts_for_folder`
- Script selection: `ScriptPanel.script_selected` -> `MainWindow.on_script_selected` -> `MetadataPanel.update_metadata`
- Metadata changes: `MetadataPanel.metadata_changed` -> `MainWindow.on_metadata_changed` -> Global refresh

### Background Processing
- All data loading uses QThread-based loaders to keep UI responsive
- Metadata uses LRU caching for performance
- Global index built asynchronously for quick search

### Host Detection & Embedding
- Host detection in [utilities.py](md:utilities.py) - tries Nuke -> Maya -> Windows -> Generic
- Embedding logic in [__init__.py](md:__init__.py) - Maya workspaceControl, Nuke panels, standalone Qt

## Development Guidelines

### Adding New Features
1. Follow signal/slot pattern for UI communication
2. Use background loaders for data operations
3. Update metadata system for new script types
4. Add host-specific logic in utilities and embedding

### File Organization
- Core logic in root files
- UI components in `ui/` directory
- Settings in `settings/` directory
- All paths relative to workspace root

### Error Handling
- Graceful degradation for missing scripts/files
- Fallback to defaults for invalid metadata
- Logging without crashes for database errors
description:
globs:
alwaysApply: false
---
