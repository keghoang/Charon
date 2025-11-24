# Keybind Architecture

## Overview

Charon's keybind system provides a sophisticated way to manage keyboard shortcuts with clear separation between:
- **Local keybinds**: UI shortcuts that only work when Charon has focus
- **Global keybinds**: Script execution shortcuts that work system-wide

This architecture was designed to prevent Charon's UI keybinds from interfering with host software (Maya, Nuke) while still allowing quick script execution from anywhere.

## Design Goals

1. **No Interference**: Charon keybinds shouldn't interfere with host software shortcuts
2. **User Control**: Users can customize all keybinds and resolve conflicts
3. **Priority System**: Clear rules for which keybind wins in conflicts
4. **Persistence**: All preferences saved per-user in database
5. **Easy Extension**: Simple to add new keybinds or modify behavior

## Architecture Components

### 1. KeybindManager (`keybind_manager.py`)
Central coordinator that:
- Manages both local and global handlers
- Detects conflicts between keybind types
- Routes keybind triggers to appropriate handlers
- Provides unified interface for keybind operations

### 2. LocalKeybindHandler (`local_handler.py`)
Manages Charon's built-in UI keybinds:
- Uses `Qt.WindowShortcut` context (only active when window focused)
- Command mode uses `Qt.ApplicationShortcut` context (always active)
- Default keybinds loaded from `config.DEFAULT_LOCAL_KEYBINDS`
- Loads custom mappings from database per user
- Auto-initializes defaults for new users
- Can be disabled/remapped via settings

### 3. GlobalKeybindHandler (`global_handler.py`)
Manages user-assigned script keybinds:
- Uses `Qt.ApplicationShortcut` context (always active)
- Stored in existing hotkeys database table
- Takes priority over local keybinds by default
- Triggers script execution directly

### 4. ConflictResolver (`conflict_resolver.py`)
Handles keybind conflicts:
- Detects when global and local keybinds overlap
- Shows warning dialog with options
- Saves user's resolution preference
- Supports "don't show again" option

### 5. Settings UI (`settings_ui.py`)
Comprehensive keybind configuration:
- Two tabs: Charon Keybinds, Global Keybinds
- Command mode keybind now appears in Charon Keybinds tab
- Visual editing of all keybinds with "Current" and "Default" columns
- Conflicts handled automatically by Charon (no separate tab)
- Apply/OK/Cancel pattern

## Data Flow

```
User presses key
    ↓
Qt captures keypress
    ↓
KeybindManager checks both handlers
    ↓
Conflict? → ConflictResolver checks preference
    ↓
Execute appropriate action (local or global)
```

## Database Schema

### New Tables

```sql
keybind_conflicts (
    user TEXT,
    key_sequence TEXT,
    local_action TEXT,
    global_script TEXT,
    resolution TEXT,  -- 'global', 'local', 'disabled'
    show_warning INTEGER
)

local_keybind_settings (
    user TEXT,
    action_name TEXT,  -- 'run_script', 'quick_search', etc.
    key_sequence TEXT,
    enabled INTEGER,
    UNIQUE(user, action_name)
)
```

### Integration with Existing
- Uses existing `hotkeys` table for global keybinds
- Local keybinds now stored per-user in `local_keybind_settings` table
- Auto-initialized with defaults for new users
- Maintains backward compatibility

## Key Technical Decisions

### 1. Shift Key Fix
Problem: Qt returns shifted characters (# instead of 3) when Shift is pressed.

Solution: In `HotkeyDialog.keyPressEvent()`, we map shifted symbols back to their base keys:
```python
shift_number_map = {
    QtCore.Qt.Key_NumberSign: QtCore.Qt.Key_3,  # # → 3
    # ... etc
}
```

### 2. Context Separation
- Local: `Qt.WindowShortcut` - respects focus
- Global: `Qt.ApplicationShortcut` - always active

This prevents Charon from capturing Maya's shortcuts when not focused.

### 3. Priority System
Default: Global keybinds override local ones
- Rationale: User-assigned shortcuts are intentional
- Can be changed per-conflict in settings
- "Disabled" option turns off both

### 4. Warning Dialog
Shows when assigning a global keybind that conflicts with local:
- Clear explanation of conflict
- Options to proceed or cancel
- "Don't show again" checkbox
- Stored in database

## Usage Examples

### Assigning a Global Keybind
1. Right-click script → "Assign Hotkey"
2. Press key combination (e.g., Ctrl+Shift+3)
3. If conflicts with local keybind, warning appears
4. Choose to override or cancel

### Adding New Local Keybinds (Developer)
1. Edit `DEFAULT_LOCAL_KEYBINDS` in `config.py`
2. Add action mapping in `_setup_local_keybind_handlers()` in `main_window.py`
3. Create the handler function in `CharonWindow` class
4. Update display names in `settings_ui.py` if needed

### Customizing Local Keybinds (User)
1. Click Settings button
2. Go to Charon Keybinds tab
3. Click "Edit" button to modify keybinds
4. Command mode toggle (F3 by default) is now in this tab
5. Click "Reset to Defaults" to restore original keybinds

### Hotkey Cleanup
- **Automatic Cleanup**: Missing scripts are purged on startup and refresh
- **Centralized Logic**: Same cleanup function used for both operations
- **Console Output**: Shows cleaned script names (not full paths) in terminal
- **Triggered By**: Application startup or clicking Refresh button
5. Changes are saved per-user in database

### Viewing/Editing Global Keybinds
1. Settings → Global Keybinds tab
2. See all script keybinds with script names
3. Click "Edit" to change a keybind
4. Click "Remove Selected" to delete keybinds

## Future Enhancements

### 1. Floating Keybind Display
- Always-on-top Qt.Tool window
- Shows active global keybinds
- Visual feedback when triggered
- Can be toggled on/off

### 2. Import/Export Settings
- Save keybind configurations
- Share between users
- Backup/restore functionality

### 3. Host-Specific Keybinds
- Different keybinds per host (Maya vs Nuke)
- Automatic switching based on context
- Prevents conflicts with host shortcuts

### 4. Advanced Conflict Resolution
- Auto-suggest alternative keybinds
- Check against host software shortcuts
- Machine learning for optimal suggestions

## Testing Considerations

### Manual Testing
1. **Shift combinations**: Verify Ctrl+Shift+1-9 work correctly
2. **Focus behavior**: Local keybinds only work when focused
3. **Conflict warnings**: Appear appropriately
4. **Settings persistence**: Changes saved/loaded correctly

### Edge Cases
- Multiple Charon windows open
- Keybind assigned to non-existent script
- Database corruption/migration
- Cross-platform key differences

## Best Practices

### For Developers
1. Always use KeybindManager, not direct QShortcut
2. Check for conflicts before adding new defaults
3. Provide clear action names for display
4. Test on all target platforms

### For Users
1. Choose global keybinds that don't conflict with host
2. Use Settings UI rather than manual database edits
3. Report any focus/capture issues
4. Back up database before major changes

## Troubleshooting

### Common Issues

**"My keybind doesn't work"**
- Check Settings → is it enabled?
- Check Conflicts → is it overridden?
- Is Charon window focused? (for local)
- Is script still at that path? (for global)

**"Keybind interferes with Maya"**
- Charon window may be stealing focus
- Change the local keybind in Settings
- Disable the conflicting keybind

**"Settings won't save"**
- Check database write permissions
- Look for errors in console
- Try resetting to defaults

## Implementation Notes

### Thread Safety
- All keybind operations happen on main thread
- Database access is synchronized
- No threading issues expected

### Performance
- Keybind lookup is O(1) via dictionaries
- Database queries cached in memory
- Minimal overhead on keypress

### Compatibility
- Works with PySide2/PySide6 (auto-detected based on host/availability)
- No Python 3.8+ features used (maintains Python 3.7 compatibility)
- Cross-platform Qt key codes
