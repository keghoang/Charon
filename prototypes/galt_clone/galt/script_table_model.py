from .qt_compat import QtCore, QtGui, UserRole, DisplayRole, ForegroundRole, TextAlignmentRole, AlignCenter, Horizontal
from .script_model import ScriptItem, BaseScriptLoader
from .script_validator import ScriptValidator
from .settings import user_settings_db
import os

class ScriptTableModel(QtCore.QAbstractTableModel):
    """Table model for displaying workflows with columns: Name, Hotkey, Run"""
    
    # Column indices
    COL_NAME = 0
    COL_HOTKEY = 1
    COL_RUN = 2
    COLUMN_COUNT = 3
    
    # Custom roles
    ScriptRole = UserRole + 1
    PathRole = UserRole + 2
    MetadataRole = UserRole + 3
    CanRunRole = UserRole + 6
    TagsRole = UserRole + 100  # Role for tag filtering
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scripts = []
        self.host = "None"
    
    def _has_valid_entry_file(self, script: ScriptItem) -> bool:
        """Check if script has a valid entry file (uses cached validation)"""
        has_entry, _ = ScriptValidator.has_valid_entry(script.path, script.metadata)
        return has_entry
    
    def can_run_script(self, script: ScriptItem) -> bool:
        """Check if a script can be run."""
        can_run, _ = ScriptValidator.can_execute(script.path, script.metadata, self.host)
        return can_run
    
    def get_foreground_brush(self, script: ScriptItem):
        """Get the foreground brush for a script item."""
        from .utilities import apply_incompatible_opacity
        props = ScriptValidator.get_visual_properties(
            script.path,
            script.metadata,
            self.host,
            getattr(script, 'is_bookmarked', False)
        )
        
        color = QtGui.QColor(props["color"])
        if props["should_fade"]:
            color = apply_incompatible_opacity(color)
        
        return QtGui.QBrush(color)
    
    def update_single_script(self, script_path: str) -> bool:
        """Update a single script in the model without full reload.
        
        Args:
            script_path: Path to the script to update
            
        Returns:
            True if script was found and updated, False otherwise
        """
        from .metadata_manager import get_galt_config
        
        # Find the script in our list
        for i, script in enumerate(self.scripts):
            if script.path == script_path:
                # Reload metadata from disk
                new_metadata = get_galt_config(script_path)
                
                # Update the script's metadata
                script.metadata = new_metadata
                
                # Refresh hotkey data from database
                hotkey = user_settings_db.get_hotkey_for_script(script_path, self.host)
                if hotkey:
                    script.has_hotkey = True
                    script.hotkey = hotkey
                else:
                    script.has_hotkey = False
                    script.hotkey = None
                
                # Preserve bookmark status (this doesn't change with metadata)
                old_is_bookmarked = getattr(script, 'is_bookmarked', False)
                script.is_bookmarked = old_is_bookmarked
                
                # Emit dataChanged signal for this row
                top_left = self.index(i, 0)
                bottom_right = self.index(i, self.COLUMN_COUNT - 1)
                self.dataChanged.emit(top_left, bottom_right)
                
                return True
        
        return False
    
    def update_script_tags(self, script_path: str, new_tags: list) -> bool:
        """Update tags for a single script without reloading metadata.
        
        Args:
            script_path: Path to the script to update
            new_tags: New list of tags
            
        Returns:
            True if script was found and updated, False otherwise
        """
        import os
        from .galt_logger import system_debug
        
        # Normalize the path for comparison
        normalized_target = os.path.normpath(script_path)
        
        # Find the script in our list
        for i, script in enumerate(self.scripts):
            if os.path.normpath(script.path) == normalized_target:
                # Update just the tags
                old_tags = script.metadata.get('tags', []) if script.metadata else []
                system_debug(f"Updating tags for {script.name}: {old_tags} -> {new_tags}")
                
                if script.metadata:
                    script.metadata['tags'] = new_tags
                else:
                    script.metadata = {'tags': new_tags}
                
                # Emit dataChanged signal for this row
                # Tags might affect display in name column
                top_left = self.index(i, 0)
                bottom_right = self.index(i, self.COLUMN_COUNT - 1)
                self.dataChanged.emit(top_left, bottom_right)
                system_debug(f"Emitted dataChanged for row {i}")
                
                return True
        
        system_debug(f"Script not found in model: {script_path}")
        return False
        
    def rowCount(self, parent=QtCore.QModelIndex()):
        if parent.isValid():
            return 0
        return len(self.scripts)
        
    def columnCount(self, parent=QtCore.QModelIndex()):
        if parent.isValid():
            return 0
        return self.COLUMN_COUNT
        
    def data(self, index, role=DisplayRole):
        if not index.isValid() or index.row() >= len(self.scripts):
            return None
            
        script = self.scripts[index.row()]
        col = index.column()
        
        if role == DisplayRole:
            if col == self.COL_NAME:
                # Build display name with emoji indicators
                prefix = ""
                
                # Add bookmark emoji if bookmarked
                if getattr(script, 'is_bookmarked', False):
                    prefix += "★ "
                
                # Add hotkey emoji if has hotkey (but not showing specific key)
                if getattr(script, 'has_hotkey', False) and not hasattr(script, 'hotkey'):
                    prefix += "▶ "
                
                # Build the name with readme indicator
                name_part = script.name
                if script.has_readme():
                    name_part += " [r]"
                
                return f"{prefix}{name_part}"
                    
            elif col == self.COL_HOTKEY:
                # Show the specific hotkey if available
                if hasattr(script, 'hotkey') and script.hotkey:
                    return script.hotkey
                return ""
                
            elif col == self.COL_RUN:
                # This column will have buttons, no text
                return ""
                
        elif role == ForegroundRole:
            # Only apply color to name column
            if col == self.COL_NAME:
                return self.get_foreground_brush(script)
                    
        elif role == TextAlignmentRole:
            if col == self.COL_HOTKEY:
                return AlignCenter
                
        # Custom roles for accessing script data
        elif role == self.ScriptRole:
            return script
        elif role == self.PathRole:
            return script.path
        elif role == self.MetadataRole:
            return script.metadata
        elif role == self.CanRunRole:
            return self.can_run_script(script)
        elif role == self.TagsRole:
            # Return a string representation of tags for filtering
            if script.metadata and 'tags' in script.metadata:
                tags = script.metadata.get('tags', [])
                if isinstance(tags, list):
                    return ','.join(tags)  # Join tags for easy searching
            return ""
            
        return None
        
    def headerData(self, section, orientation, role=DisplayRole):
        """Provide header labels for columns"""
        if orientation == Horizontal and role == DisplayRole:
            if section == self.COL_NAME:
                return "Workflow"
            elif section == self.COL_HOTKEY:
                return "Hotkey"
            elif section == self.COL_RUN:
                return ""
        return None
        
    def updateItems(self, scripts, sort=True):
        """Update the model with new script items
        
        Args:
            scripts: List of script items to display
            sort: If True, sort the scripts before updating (default: True)
        """
        self.beginResetModel()
        if sort and scripts:
            from galt.utilities import create_sort_key
            scripts.sort(key=lambda i: create_sort_key(i, self.host))
        self.scripts = scripts
        self.endResetModel()
        
    def clear(self):
        """Clear all scripts"""
        self.beginResetModel()
        self.scripts = []
        self.endResetModel()
        
    def sortItems(self):
        """Sort scripts using the same algorithm as list model"""
        from galt.utilities import create_sort_key
        self.scripts.sort(key=lambda i: create_sort_key(i, self.host))
        self.layoutChanged.emit()
        
    def set_host(self, host):
        """Set the host software and re-sort if needed"""
        if self.host != host:
            self.host = host
            if self.scripts:
                self.sortItems()
                # Trigger visual refresh
                self.dataChanged.emit(
                    self.index(0, 0),
                    self.index(len(self.scripts) - 1, self.COLUMN_COUNT - 1)
                )
    
                
    def get_script_at_row(self, row):
        """Get script at given row index"""
        if 0 <= row < len(self.scripts):
            return self.scripts[row]
        return None
    
    def refresh_tags_from_disk(self):
        """Refresh all script tags from disk without full reload."""
        from .metadata_manager import get_galt_config
        from .galt_logger import system_debug
        
        system_debug(f"Refreshing tags from disk for {len(self.scripts)} scripts")
        
        # Begin model reset to ensure views update properly
        self.beginResetModel()
        
        for script in self.scripts:
            # Re-read metadata from disk
            fresh_metadata = get_galt_config(script.path)
            if fresh_metadata:
                # Update the script's metadata
                script.metadata = fresh_metadata
                system_debug(f"Refreshed tags for {script.name}: {fresh_metadata.get('tags', [])}")
        
        # End model reset
        self.endResetModel()
