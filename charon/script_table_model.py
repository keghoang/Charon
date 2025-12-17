from .qt_compat import QtCore, QtGui, UserRole, DisplayRole, ForegroundRole, Horizontal
from .workflow_model import ScriptItem
from .script_validator import ScriptValidator
import os
import time

class ScriptTableModel(QtCore.QAbstractTableModel):
    """Table model for displaying workflows with columns: Name, VRAM, Status, Run"""
    
    # Column indices
    COL_NAME = 0
    COL_VRAM = 1
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
        self._system_vram_gb = None
    
    def _has_valid_entry_file(self, script: ScriptItem) -> bool:
        """Check if script has a valid entry file (uses cached validation)"""
        has_entry, _ = ScriptValidator.has_valid_entry(script.path, script.metadata)
        return has_entry
    
    def can_run_script(self, script: ScriptItem) -> bool:
        """Check if a script can be run."""
        can_run, _ = ScriptValidator.can_execute(script.path, script.metadata, self.host)
        return can_run
    
    @staticmethod
    def _parse_min_vram(metadata: dict) -> tuple[float, str]:
        """Return (required_gb, display_text) or (None, "") if missing."""
        if not isinstance(metadata, dict):
            return None, ""
        raw = metadata.get("min_vram_gb") or metadata.get("charon_meta", {}).get("min_vram_gb")
        if raw is None:
            return None, ""
        text = str(raw).strip()
        import re
        # Accept values like "32 GB", "32GB", "32", "32.0", "32gb"
        match = re.search(r"(\d+(?:\.\d+)?)", text)
        if not match:
            return None, text or ""
        try:
            value = float(match.group(1))
        except ValueError:
            return None, text or ""
        return value, text or f"{value:g} GB"

    def _detect_system_vram_gb(self) -> float:
        """Detect the maximum available GPU VRAM (in GB) across adapters."""
        if self._system_vram_gb is not None:
            return self._system_vram_gb

        def _round_gb(value, scale):
            try:
                return float(value) / float(scale)
            except Exception:
                return None

        max_gb = None

        # Prefer nvidia-smi when available for accurate totals
        cmd = [
            "nvidia-smi",
            "--query-gpu=memory.total",
            "--format=csv,noheader,nounits",
        ]
        try:
            import subprocess

            result = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                timeout=2,
            )
            for line in result.stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                val = _round_gb(line, 1024)
                if val:
                    max_gb = max(max_gb or 0, val)
        except Exception:
            pass

        # Fallback to WMI on Windows
        if max_gb is None and os.name == "nt":
            ps_cmd = (
                "Get-CimInstance Win32_VideoController | "
                "Select-Object AdapterRAM | ConvertTo-Json -Compress"
            )
            try:
                import subprocess, json as _json

                result = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", ps_cmd],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                payload = _json.loads(result.stdout)
                records = payload if isinstance(payload, list) else [payload]
                for rec in records:
                    if not isinstance(rec, dict):
                        continue
                    raw = rec.get("AdapterRAM")
                    if isinstance(raw, (int, float)):
                        val = _round_gb(raw, 1024 ** 3)
                        if val:
                            max_gb = max(max_gb or 0, val)
            except Exception:
                pass

        self._system_vram_gb = max_gb
        return max_gb

    def _compute_vram_status(self, script: ScriptItem) -> dict:
        """Return a dict with display, color, tooltip, and state for VRAM column."""
        metadata = script.metadata or {}
        req_gb, display_text = self._parse_min_vram(metadata)
        available_gb = self._detect_system_vram_gb()

        if req_gb is None:
            return {
                "text": "?",
                "color": "#f08c00",
                "tooltip": "No minimum VRAM requirement set.",
            }

        if not display_text:
            display_text = f"{req_gb:g} GB"

        if available_gb is None:
            return {
                "text": f"{display_text} ?",
                "color": "#f08c00",
                "tooltip": f"Requires ≥ {display_text}. Unable to detect GPU VRAM.",
            }

        passes = available_gb >= req_gb
        color = "#37b24d" if passes else "#ff6b6b"
        marker = "✔" if passes else "✖"
        tooltip = f"Requires ≥ {display_text}. Detected max VRAM: {available_gb:.1f} GB."
        return {
            "text": f"{display_text} {marker}",
            "color": color,
            "tooltip": tooltip,
        }
    
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
                
                return f"{prefix}{script.name}"
            
            elif col == self.COL_VRAM:
                vram = self._compute_vram_status(script)
                return vram.get("text")
            
            elif col == self.COL_VALIDATE:
                state = self._get_validation_state_for_script(script)
                entry = self._get_validation_entry_for_script(script)
                payload = entry.get("payload") if isinstance(entry, dict) else {}
                if not isinstance(payload, dict):
                    payload = {}
                restart_required = bool(payload.get("restart_required") or payload.get("requires_restart"))
                phase = int(entry.get("phase", 0)) if isinstance(entry, dict) else 0
                if restart_required:
                    return "⚠ ComfyUI Restart required"
                if state == "installing":
                    dots = "." * (phase % 4)
                    return f"⌛ Installing{dots}"
                if state == "validated":
                    return "✔ Ready"
                if state == "needs_resolve":
                    return "⚠ Missing Models or Nodes"
                if state == "validating":
                    dots = "." * (phase % 4)
                    return f"⏳ Activating{dots}"
                return "Inactive"
            elif col == self.COL_RUN:
                state = self._get_validation_state_for_script(script)
                entry = self._get_validation_entry_for_script(script)
                payload = entry.get("payload") if isinstance(entry, dict) else {}
                if not isinstance(payload, dict):
                    payload = {}
                restart_required = bool(payload.get("restart_required") or payload.get("requires_restart"))
                if restart_required:
                    return "Fix Issue"
                if state == "validated":
                    return "Grab"
                if state == "installing":
                    return "Fix Issue"
                if state == "needs_resolve":
                    return "Fix Issue"
                if state == "validating":
                    return "Activate"
                return "Activate"
                
        elif role == ForegroundRole:
            if col == self.COL_NAME:
                return self.get_foreground_brush(script)
            if col == self.COL_VRAM:
                vram = self._compute_vram_status(script)
                color = vram.get("color")
                if color:
                    return QtGui.QBrush(QtGui.QColor(color))
            if col == self.COL_VALIDATE:
                return QtGui.QBrush(QtGui.QColor("#c2c7d1"))
        
        elif role == QtCore.Qt.ItemDataRole.ToolTipRole:
            if col == self.COL_VRAM:
                vram = self._compute_vram_status(script)
                return vram.get("tooltip")
            
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
            elif section == self.COL_VRAM:
                return "VRAM"
            elif section == self.COL_VALIDATE:
                return "Status"
            elif section == self.COL_RUN:
                return "Actions"
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
            entry = {"state": "idle", "phase": 0, "payload": {}}
            self.validation_states[normalized] = entry
        entry.setdefault("state", "idle")
        entry.setdefault("phase", 0)
        entry.setdefault("payload", {})
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
            status_index = self.index(row, self.COL_VALIDATE)
            action_index = self.index(row, self.COL_RUN)
            roles = [DisplayRole, self.ValidationStateRole, self.ValidationEnabledRole, self.ValidationPayloadRole]
            self.dataChanged.emit(status_index, status_index, roles)
            self.dataChanged.emit(action_index, action_index, [DisplayRole, self.ValidationEnabledRole])

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
            status_index = self.index(row, self.COL_VALIDATE)
            action_index = self.index(row, self.COL_RUN)
            self.dataChanged.emit(status_index, status_index, [DisplayRole])
            self.dataChanged.emit(action_index, action_index, [DisplayRole])
        return bool(updated_rows)

    def has_active_validation(self) -> bool:
        return any(entry.get("state") == "validating" for entry in self.validation_states.values())

    def _prune_validation_states(self) -> None:
        valid_paths = {self._normalize_path(script.path) for script in self.scripts}
        self.validation_states = {
            path: entry
            for path, entry in self.validation_states.items()
            if path in valid_paths or entry.get("state") == "validating"
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

