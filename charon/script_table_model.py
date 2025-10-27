from .qt_compat import QtCore, QtGui, UserRole, DisplayRole, ForegroundRole, TextAlignmentRole, AlignCenter, Horizontal
from .qt_compat import (
    QtCore,
    QtGui,
    UserRole,
    DisplayRole,
    ForegroundRole,
    TextAlignmentRole,
    AlignCenter,
    Horizontal,
    FontRole,
)
from .workflow_model import ScriptItem, BaseScriptLoader
from .script_validator import ScriptValidator
from .settings import user_settings_db
import os
import time

class ScriptTableModel(QtCore.QAbstractTableModel):
    """Table model for displaying workflows with columns: Name, Hotkey, Run"""
    
    # Column indices
    COL_NAME = 0
    COL_HOTKEY = 1
    COL_VALIDATE = 2
    COL_RUN = 3
    COLUMN_COUNT = 4
    
    # Custom roles
    ScriptRole = UserRole + 1
    PathRole = UserRole + 2
    MetadataRole = UserRole + 3
    CanRunRole = UserRole + 6
    TagsRole = UserRole + 100  # Role for tag filtering
    ValidationStateRole = UserRole + 200
    ValidationEnabledRole = UserRole + 201
    ValidationPayloadRole = UserRole + 202
    PASSED_LABEL = "\u2713 Passed"
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scripts = []
        self.host = "None"
        self.validation_states = {}
    
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
        from .metadata_manager import get_charon_config
        
        # Find the script in our list
        for i, script in enumerate(self.scripts):
            if script.path == script_path:
                # Reload metadata from disk
                new_metadata = get_charon_config(script_path)
                
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
        from .charon_logger import system_debug
        
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
                
                return f"{prefix}{script.name}"
                    
            elif col == self.COL_HOTKEY:
                # Show the specific hotkey if available
                if hasattr(script, 'hotkey') and script.hotkey:
                    return script.hotkey
                return ""
                
            elif col == self.COL_VALIDATE:
                state = self._get_validation_state_for_script(script)
                entry = self._get_validation_entry_for_script(script)
                phase = int(entry.get("phase", 0)) if isinstance(entry, dict) else 0
                if state == "validating":
                    dots = "." * (phase % 4)
                    return f"Validating{dots}"
                if state == "validated":
                    return self.PASSED_LABEL
                if state == "needs_resolve":
                    return "Resolve"
                return "Validate"
            elif col == self.COL_RUN:
                # This column will have buttons, no text
                return ""
                
        elif role == ForegroundRole:
            # Only apply color to name column
            if col == self.COL_NAME:
                return self.get_foreground_brush(script)
            if col == self.COL_VALIDATE:
                state = self._get_validation_state_for_script(script)
                if state == "validated":
                    return QtGui.QBrush(QtGui.QColor(34, 139, 34))
                if state == "needs_resolve":
                    return QtGui.QBrush(QtGui.QColor(178, 34, 34))
                    
        elif role == TextAlignmentRole:
            if col == self.COL_HOTKEY:
                return AlignCenter
        elif role == FontRole:
            if col == self.COL_VALIDATE and self._get_validation_state_for_script(script) == "validated":
                bold = QtGui.QFont()
                bold.setBold(True)
                return bold
                
        # Custom roles for accessing script data
        elif role == self.ScriptRole:
            return script
        elif role == self.PathRole:
            return script.path
        elif role == self.MetadataRole:
            return script.metadata
        elif role == self.CanRunRole:
            base_ready = self.can_run_script(script)
            return base_ready and self._get_validation_state_for_script(script) == "validated"
        elif role == self.TagsRole:
            # Return a string representation of tags for filtering
            if script.metadata and 'tags' in script.metadata:
                tags = script.metadata.get('tags', [])
                if isinstance(tags, list):
                    return ','.join(tags)  # Join tags for easy searching
            return ""
        elif role == self.ValidationStateRole:
            return self._get_validation_state_for_script(script)
        elif role == self.ValidationEnabledRole:
            state = self._get_validation_state_for_script(script)
            return state != "validating"
        elif role == self.ValidationPayloadRole:
            entry = self._get_validation_entry_for_script(script)
            return entry.get("payload") if isinstance(entry, dict) else None
            
        return None
        
    def headerData(self, section, orientation, role=DisplayRole):
        """Provide header labels for columns"""
        if orientation == Horizontal and role == DisplayRole:
            if section == self.COL_NAME:
                return "Workflow"
            elif section == self.COL_HOTKEY:
                return "Hotkey"
            elif section == self.COL_VALIDATE:
                return "Validate"
            elif section == self.COL_RUN:
                return ""
        return None
    
    def _normalize_path(self, path: str) -> str:
        return os.path.normpath(path) if path else ""

    def _row_for_path(self, normalized_path: str):
        for row, script in enumerate(self.scripts):
            if self._normalize_path(script.path) == normalized_path:
                return row
        return None

    def _get_validation_entry_for_script(self, script: ScriptItem) -> dict:
        normalized = self._normalize_path(script.path)
        entry = self.validation_states.get(normalized)
        if not isinstance(entry, dict):
            entry = {"state": "idle", "phase": 0, "payload": None}
            self.validation_states[normalized] = entry
        entry.setdefault("state", "idle")
        entry.setdefault("phase", 0)
        if entry["state"] != "validating":
            entry["phase"] = 0
        return entry

    def _get_validation_state_for_script(self, script: ScriptItem) -> str:
        entry = self._get_validation_entry_for_script(script)
        return str(entry.get("state") or "idle")

    def set_validation_state(self, script_path: str, state: str, payload=None) -> None:
        normalized = self._normalize_path(script_path)
        entry = self.validation_states.get(normalized, {"state": "idle", "phase": 0, "payload": None})
        entry["state"] = state
        if state == "validating":
            entry["phase"] = 0
            entry["animation_start"] = time.time()
        else:
            entry["phase"] = 0
            entry.pop("animation_start", None)
        entry["payload"] = payload
        self.validation_states[normalized] = entry
        row = self._row_for_path(normalized)
        if row is not None:
            model_index = self.index(row, self.COL_VALIDATE)
            self.dataChanged.emit(
                model_index,
                model_index,
                [DisplayRole, self.ValidationStateRole, self.ValidationEnabledRole, self.ValidationPayloadRole],
            )

    def get_validation_state(self, script_path: str) -> str:
        normalized = self._normalize_path(script_path)
        entry = self.validation_states.get(normalized, {})
        return str(entry.get("state") or "idle")

    def get_validation_payload(self, script_path: str):
        normalized = self._normalize_path(script_path)
        entry = self.validation_states.get(normalized)
        if isinstance(entry, dict):
            return entry.get("payload")
        return None

    def advance_validation_animation(self) -> bool:
        updated_rows = []
        for normalized, entry in list(self.validation_states.items()):
            if entry.get("state") == "validating":
                entry["phase"] = (entry.get("phase", 0) + 1) % 4
                row = self._row_for_path(normalized)
                if row is not None:
                    updated_rows.append(row)
        for row in updated_rows:
            index = self.index(row, self.COL_VALIDATE)
            self.dataChanged.emit(index, index, [DisplayRole])
        return bool(updated_rows)

    def has_active_validation(self) -> bool:
        return any(entry.get("state") == "validating" for entry in self.validation_states.values())

    def _prune_validation_states(self) -> None:
        valid_paths = {self._normalize_path(script.path) for script in self.scripts}
        self.validation_states = {
            path: entry for path, entry in self.validation_states.items() if path in valid_paths
        }
        
    def updateItems(self, scripts, sort=True):
        """Update the model with new script items
        
        Args:
            scripts: List of script items to display
            sort: If True, sort the scripts before updating (default: True)
        """
        self.beginResetModel()
        if sort and scripts:
            from charon.utilities import create_sort_key
            scripts.sort(key=lambda i: create_sort_key(i, self.host))
        self.scripts = scripts
        self._prune_validation_states()
        self.endResetModel()
        
    def clear(self):
        """Clear all scripts"""
        self.beginResetModel()
        self.scripts = []
        self.validation_states = {}
        self.endResetModel()
        
    def sortItems(self):
        """Sort scripts using the same algorithm as list model"""
        from charon.utilities import create_sort_key
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
        from .metadata_manager import get_charon_config
        from .charon_logger import system_debug
        
        system_debug(f"Refreshing tags from disk for {len(self.scripts)} scripts")
        
        # Begin model reset to ensure views update properly
        self.beginResetModel()
        
        for script in self.scripts:
            # Re-read metadata from disk
            fresh_metadata = get_charon_config(script.path)
            if fresh_metadata:
                # Update the script's metadata
                script.metadata = fresh_metadata
                system_debug(f"Refreshed tags for {script.name}: {fresh_metadata.get('tags', [])}")
        
        # End model reset
        self.endResetModel()

