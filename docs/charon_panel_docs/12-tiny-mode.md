# Tiny Mode

Tiny Mode is a minimal, focused UI mode in Charon that provides quick access to execution history and bookmarked scripts. It's designed for power users who want rapid script execution without the full Charon interface.

## Overview

Tiny Mode offers:
- Instant access to recently executed scripts
- Quick access to bookmarked scripts
- Minimal UI footprint (200x300 pixels by default)
- Global hotkey activation (`F2` by default)
- Seamless integration with the main Charon interface

## Activation

### Global Hotkey
- **Default**: `F2` (configurable in `config.py`)
- Works from anywhere in the application
- Toggles between normal mode and tiny mode
- Customizable via Settings → Charon Keybinds tab
- Window gains focus when entering tiny mode

### Window Behavior
- Tiny mode uses a smaller window size
- Window position is remembered separately from normal mode
- Host-specific window flags (e.g., stays on top for Windows standalone)

## User Interface

### Layout
Tiny Mode consists of:
1. **Tab Widget** with two tabs:
   - **History**: Shows recent script executions
   - **Bookmarks**: Shows bookmarked scripts (only visible if bookmarks exist)
2. **Minimal toolbar** with:
   - Exit button (returns to normal mode)
   - Settings button
   - Help button

### History Tab
- Lists recently executed scripts
- Shows execution status (✓ for success, ✗ for failure, ❓ for unknown)
- Double-click to re-execute any script
- Shared with main UI - executions from either mode appear in both

### Bookmarks Tab
- Displays user's bookmarked scripts
- Only appears if user has bookmarks
- Shows script compatibility:
  - Compatible scripts shown in normal color
  - Incompatible scripts are faded and cannot be executed
- Double-click to execute bookmarked scripts

## Features

### Script Execution
- **Double-click** on any history item or bookmark to execute
- Scripts run using the same execution engine as normal mode
- Validation ensures:
  - Script has valid entry file
  - Script is compatible with current host
  - Proper threading mode is used (main vs background)

### Visual Feedback
- **Compatibility indication**: Incompatible scripts are faded
- **Status icons**: History shows execution results
- **Tooltips**: Hover for script paths and additional info

### State Persistence
- Execution history persists between mode switches
- Window geometry saved separately for each mode
- Bookmarks automatically sync with user settings

## Configuration

### Window Size
In `config.py`:
```python
COMMAND_MODE_WIDTH = 200  # Default width in pixels
COMMAND_MODE_HEIGHT = 300  # Default height in pixels
```

### Keybind Customization
1. Open Settings (gear icon)
2. Navigate to Charon Keybinds tab
3. Find "Tiny Mode" in the list
4. Click "Edit" to set new keybind
5. The keybind is stored per-user in the database

## Use Cases

### Quick Re-execution
1. Press `F2` to enter tiny mode
2. Double-click a recent script from history
3. Script executes immediately
4. Press `F2` again to return to normal mode

### Bookmark Workflow
1. Bookmark frequently used scripts in normal mode
2. Access them instantly via tiny mode
3. Perfect for repetitive tasks

### Minimal Footprint
- Keep tiny mode open in corner of screen
- Quick access without blocking workspace
- Ideal for multi-monitor setups

## Technical Details

### Architecture
- Implemented as `TinyModeWidget` class
- Uses `QStackedWidget` for mode switching
- Shares execution engine with main window
- Lazy loading of bookmarks panel

### Integration Points
- **Keybind System**: Uses global application shortcuts
- **Execution Engine**: Same validation and execution as main UI
- **Settings Database**: Shares user preferences and bookmarks
- **Window Manager**: Handles mode-specific window properties

### Host-Specific Behavior
- **Windows**: Window stays on top by default
- **Maya/Nuke**: Standard window flags
- **All hosts**: Separate geometry persistence
- **Focus behavior**: Window is raised and activated on mode entry

## Best Practices

1. **Use for repetitive tasks**: Ideal for scripts you run frequently
2. **Combine with bookmarks**: Bookmark your most-used scripts
3. **Keyboard-driven workflow**: Use Tab to switch between History/Bookmarks
4. **Keep it accessible**: Position window for easy access

## Future Enhancements

Planned improvements:
- Search/filter in tiny mode
- Keyboard navigation (arrow keys)
- Recent folders quick access
- Customizable tab order
- Mini-mode (even smaller UI)