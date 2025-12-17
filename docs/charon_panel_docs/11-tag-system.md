# Charon Tag System

## Overview

The tag system provides folder-specific categorization and filtering of scripts. Tags help organize scripts by purpose, type, or any other user-defined categories.

## Architecture

### Core Components

1. **Tag Bar** (`ui/tag_bar.py`)
   - Vertical bar along the left spine of the script panel
   - Displays all unique tags from scripts in the current folder
   - Uses rotated QPushButtons for space-efficient vertical layout
   - Supports multi-selection for filtering

2. **Tag Manager Dialog** (`ui/tag_manager_dialog.py`)
   - Table-based interface for managing script tags
   - Immediate-apply pattern (no OK/Cancel buttons)
   - Supports add, delete, and rename operations
   - Changes affect all scripts in the folder

3. **Tag Storage**
   - Tags stored in `.charon.json` metadata files
   - `"tags": ["tag1", "tag2", "tag3"]` array format
   - Folder-specific (each folder has its own tag namespace)

## User Interface

### Tag Bar Behavior
- Shows when at least one script in the folder has tags
- Hidden when no scripts have tags
- Clicking a tag toggles its selection
- Multiple tags can be selected (OR logic - shows scripts with ANY selected tag)
- Tag buttons use theme-neutral colors for cross-host compatibility

### Tag Manager Features
- **Add Tags**: Input field at top, adds to current script
- **Delete Tags**: Inline delete buttons, removes from ALL scripts in folder
- **Rename Tags**: Double-click to edit, updates ALL scripts in folder
- **Checkbox Selection**: Check/uncheck to assign/remove tags from current script
- **Immediate Apply**: Changes save instantly without confirmation
- **Batched Updates**: Tag changes are batched and only emit a single refresh signal when the dialog closes, preventing UI flicker and maintaining script selection

### Tag Display
- Script names show 📝 emoji if they have a readme.md file
- Tags shown as badges in:
  - Edit Metadata dialog
  - Metadata panel (bottom of script list)
- Centralized badge creation via `custom_widgets.create_tag_badge()`
- Consistent button-style appearance using `palette(button)` and `palette(buttonText)`
- Fixed height (24px) with scrollable horizontal container in metadata panel

## Implementation Details

### Tag Filtering Logic
```python
# In ScriptPanel.apply_tag_filter()
if not selected_tags:
    # Show all scripts
else:
    # Show only scripts that have ANY of the selected tags
    script_tags = set(script.metadata.get('tags', []))
    if script_tags.intersection(selected_tags):
        # Show this script
```

### Centralized Access Pattern
```python
# All tag manager access goes through CharonWindow
def open_tag_manager(self, script_path):
    # Handles folder path calculation
    # Manages UI refresh connections
    # Ensures consistent behavior
```

### Metadata Refresh
- Tag changes trigger metadata cache refresh
- UI updates immediately to reflect changes
- Preserves user's current selection when possible

## Best Practices

1. **Tag Naming**
   - Use lowercase for consistency
   - Use hyphens for multi-word tags (e.g., "character-rig")
   - Keep tags concise and descriptive

2. **Tag Organization**
   - Group related scripts with common tags
   - Use hierarchical naming when appropriate (e.g., "rig-body", "rig-face")
   - Avoid over-tagging (3-5 tags per script is usually sufficient)

3. **Folder Management**
   - Tags are folder-specific by design
   - Consider folder structure when planning tag taxonomy
   - Use consistent tag names across similar folders

## Technical Considerations

### Performance
- Tags loaded once per folder switch
- Cached with script metadata
- Efficient set operations for filtering

### Theme Compatibility
- All UI elements use Qt palette colors
- No hardcoded colors
- Works across Maya, Nuke, and Windows themes

### State Management
- Tag selection persists during folder navigation
- Clears when switching folders
- Tag manager dialog syncs with main UI state

## Future Enhancements

Potential improvements:
- Tag auto-completion
- Tag usage statistics
- Global tag search
- Tag color coding (using theme-safe colors)
- Tag hierarchies/grouping