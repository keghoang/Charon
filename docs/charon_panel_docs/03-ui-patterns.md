# Charon UI Development Patterns

## Qt Architecture Guidelines

### Signal/Slot Communication
- Always use Qt signals for cross-component communication
- Connect signals in the main window to orchestrate panel interactions
- Use `QtCore.Signal()` for custom signals in panels

### Background Loading Pattern
```python
# Use QThread-based loaders for all data operations
class SomeLoader(QtCore.QThread):
    data_loaded = QtCore.Signal(list)
    
    def run(self):
        # Do work in background
        self.data_loaded.emit(results)
```

### Model/View Architecture
- Use `QtCore.QAbstractTableModel` for folder/script display, `QtCore.QAbstractListModel` for other data
- Implement `data()` method with role-based access
- Use proxy models for filtering (`QSortFilterProxyModel`)

### Custom Delegates
- Extend `QtWidgets.QStyledItemDelegate` for custom rendering
- Override `paint()` and `editorEvent()` for interactive elements
- Use `QtCore.Qt.UserRole` for custom data storage

## UI Component Guidelines

### Panel Structure
- Each panel should inherit from `QtWidgets.QWidget`
- Use `QtCore.Signal()` for panel-specific events
- Implement `set_host()` method for host-specific behavior

### Layout Best Practices
- Use `QVBoxLayout` and `QHBoxLayout` for structure
- Set `setContentsMargins(2, 2, 2, 2)` for consistent spacing
- Use `addStretch()` for flexible spacing

### Context Menus
- Implement `contextMenuEvent()` in custom list/table views
- Use `QtWidgets.QMenu` with `addAction()` for menu items
- Connect actions to panel signals
- **Empty Space Context Menus**: Right-clicking empty space in script panel shows "New Script" and "Open Folder" options
- **Folder Context Menu**: Right-clicking folders shows "New Script" and "Open Folder" (excludes special folders like Bookmarks)
- **Comfy Control Widget**: Launch button exposes a custom context menu (via `setContextMenuPolicy(Qt.CustomContextMenu)`) with a "Terminate ComfyUI" action that posts to `/system/shutdown` when the footer detects a running instance.

### Keyboard Navigation
- Implement `keyPressEvent()` for custom navigation
- Use `QtCore.Qt.Key_*` constants for key detection

### Custom Widgets
- Tag badges centralized in `custom_widgets.create_tag_badge()`
- Consistent styling using system button appearance
- Fixed height (24px) with dynamic width based on content
- Emit custom signals for navigation events

### Theme Compatibility
- Use Qt palette colors for theme independence:
  - `palette().window()` for backgrounds
  - `palette().windowText()` for text
  - `palette().highlight()` for selections
  - `palette().mid()` for neutral/subtle elements
  - `palette().brightText()` for text on mid backgrounds
  - `palette().midlight()` for subtle hover effects

### Panel Collapse Indicators
- **Visual Indicators**: "<<" and ">>" appear in script panel header when folders/history panels are collapsed
- **Interactive**: Clicking indicators reopens the collapsed panel
- **Styling**: 
  - Transparent background with `palette(mid)` text color
  - Subtle `palette(midlight)` background on hover
  - No borders for clean appearance
- **Implementation**: Uses flat QPushButtons with custom stylesheets

### Workflow Browser Interactions
- **Validation Column**: `ScriptTableModel` exposes a dedicated column that cycles between *Validate* ? *Validating…* ? *Resolve* ? *? Passed*. Delegates consume `ValidationStateRole` to render state and colorize the button text.`n- **Run Guarding**: Grab/Execute buttons consult the same validation role, keeping the control visible but disabled until a workflow reaches *? Passed*.`n- **Context Actions**: Right-clicking the Validate column offers *Revalidate*, and—when Advanced User Mode is enabled—*Show Raw Validation Payload*.`n- **Per-Workflow Caching**: Validation results are restored from `%LOCALAPPDATA%\Charon\plugins\charon\Charon_repo_local\workflow\<workflow>\.charon_cache\validation\\validation_status.json` during `ScriptPanel.on_scripts_loaded`, allowing offline browsing without re-hitting ComfyUI.**: Validation results are restored from `%LOCALAPPDATA%\Charon\plugins\charon\Charon_repo_local\workflow\<workflow>\.charon_cache\validation\\validation_status.json` during `ScriptPanel.on_scripts_loaded`, allowing offline browsing without re-hitting ComfyUI.
- **Quick Output Access**: CharonOp action menu includes *Open Output Folder*, wired to the `charon_last_output` knob so artists jump directly to the most recent render batch.

## Tag System

### Tag Bar Component
- Vertical tag bar with rotated buttons for space efficiency
- Located along the left spine of the script panel
- Shows all unique tags from scripts in current folder
- Clicking tags filters scripts to show only those with selected tags
- Multiple tags can be selected (shows scripts with ANY selected tag)

### Tag Management
- **Tag Manager Dialog**: Accessed via right-click â†’ "Manage Tags"
  - Shows all tags in the folder with checkboxes
  - Checked tags are assigned to the selected script
  - Add new tags with input field
  - Delete tags (removes from all scripts in folder)
  - Double-click tags to rename (updates all scripts)
  - Changes apply immediately without OK/Cancel buttons

### Tag Display
- Tags shown as theme-neutral badges in:
  - Edit Metadata dialog
  - Tag manager dialog
- Use `palette(mid)` for background and `palette(brightText)` for text
- Tags are folder-specific (each folder has its own tag set)

### Centralized Tag Manager Access
- Tag manager opens consistently from:
  - Right-click context menu
  - Edit Metadata dialog
- Uses `CharonWindow.open_tag_manager()` for consistent behavior
- Ensures proper folder handling and UI refresh

## Execution Dialog

### Design Principles
- **Minimal Interface**: Shows only Status, Duration, Script name, and Output
- **Compact Layout**: Tight spacing (2px between rows) with bold labels
- **Dynamic Updates**: All fields update in real-time while script runs
- **No Window Decorations**: Removed "?" help button using `WindowContextHelpButtonHint`

### Output Display
- **Monospace Font**: Enforced Consolas (Windows) / Menlo (Mac) with fallbacks
- **Clean Output**: Shows only script output, no execution messages
- **Full Height**: Output panel expands to use available dialog space

### Real-time Updates
- **Duration Counter**: Updates every 100ms for smooth elapsed time display
- **Status Changes**: Immediately reflects when script completes or fails
- **Auto-stop Timer**: Cleans up when script finishes or dialog closes

## Tiny Mode

### Overview
Tiny Mode provides a minimal UI for quick script access without the full Charon interface.

### Implementation Pattern
```python
# Main window uses QStackedWidget for mode switching
self.stacked_widget = QtWidgets.QStackedWidget()
self.stacked_widget.addWidget(self.normal_widget)  # Index 0
self.stacked_widget.addWidget(self.tiny_mode_widget)  # Index 1
```

### Tiny Mode Widget Structure
- **Minimal toolbar**: Exit, Settings, Help buttons only
- **Tab widget**: History and Bookmarks tabs
- **Compact size**: 200x300 pixels by default
- **Global keybind**: Ctrl+Shift+G (ApplicationShortcut context)

### Design Principles
- **Fast access**: Single hotkey to toggle modes
- **Shared state**: Execution history shared with main UI
- **Lazy loading**: Bookmarks panel created only when needed
- **Host-aware**: Different window flags per host application

### Bookmarks Panel
- **Simple list view**: Shows bookmark names only
- **Visual consistency**: Uses same fading/coloring as main UI
- **Validation**: Prevents execution of invalid scripts
- **Double-click execution**: Consistent with history panel

## File References
- Main window: [ui/main_window.py](md:ui/main_window.py)
- Command mode: [ui/quick_search.py](md:ui/quick_search.py)
- Bookmarks panel: [ui/bookmarks_panel.py](md:ui/bookmarks_panel.py)
- Custom widgets: [ui/custom_widgets.py](md:ui/custom_widgets.py)
- Execution history panel: [ui/execution_history_panel.py](md:ui/execution_history_panel.py)
- Custom delegates: [ui/custom_delegates.py](md:ui/custom_delegates.py)
- Dialogs: [ui/dialogs.py](md:ui/dialogs.py)
description:
globs:
alwaysApply: false
---


