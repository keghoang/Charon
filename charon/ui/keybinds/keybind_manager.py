"""
Central Keybind Manager

Coordinates between local and global keybind handlers, manages conflicts,
and provides a unified interface for keybind operations.
"""

from typing import Any, Dict, List, Optional, Callable, Tuple
from ...qt_compat import QtCore, QtWidgets, QtGui
from .local_handler import LocalKeybindHandler
from .global_handler import GlobalKeybindHandler
from .conflict_resolver import ConflictResolver
from ...settings import user_settings_db
from ... import config
import os


class KeybindManager(QtCore.QObject):
    """
    Central manager for all keybind operations in Charon.
    
    Responsibilities:
    - Coordinate between local and global keybind handlers
    - Detect and resolve conflicts
    - Manage user preferences
    - Provide unified keybind registration interface
    """
    
    # Signals
    keybind_triggered = QtCore.Signal(str, str)  # keybind_type, keybind_id
    conflict_detected = QtCore.Signal(str, str, str)  # local_key, global_key, script_path
    
    def __init__(self, main_window: QtWidgets.QMainWindow, host: str):
        super().__init__(main_window)
        self.main_window = main_window
        self.host = host
        # Tiny mode state
        self.tiny_mode_active = False
        self.quick_search_shortcut = None  # Track quick search shortcut for context switching
        
        # Initialize handlers
        self.local_handler = LocalKeybindHandler(main_window)
        self.global_handler = GlobalKeybindHandler(main_window, host)
        self.conflict_resolver = ConflictResolver(self)
        self.app_settings = user_settings_db.get_app_settings_for_host(self.host)
        self._debug_logging_active: Optional[bool] = None
        self._apply_debug_logging_setting(initial=True)
        
        # Connect signals
        self.local_handler.keybind_triggered.connect(self._on_local_keybind)
        self.global_handler.keybind_triggered.connect(self._on_global_keybind)
        
        # Initialize keybinds
        self.refresh_keybinds()
        
        # Print a simple summary
        from ...charon_logger import system_debug
        global_count = len(self.global_handler.keybind_map)
        if global_count > 0:
            system_debug(f"Loaded {global_count} hotkey{'s' if global_count != 1 else ''}")
    
    def update_quick_search_context(self, tiny_mode: bool):
        """Update quick search keybind context based on tiny mode state."""
        # Find the quick search shortcut in local handler
        if 'quick_search' in self.local_handler.shortcuts:
            shortcut = self.local_handler.shortcuts['quick_search']
            if tiny_mode:
                # Make it global in tiny mode
                shortcut.setContext(QtCore.Qt.ApplicationShortcut)
                from ...charon_logger import system_debug
                system_debug(f"Quick search context set to ApplicationShortcut (global)")
            else:
                # Make it local in normal mode
                shortcut.setContext(QtCore.Qt.WindowShortcut)
                from ...charon_logger import system_debug
                system_debug(f"Quick search context set to WindowShortcut (local)")
            
            # Store reference for future updates
            self.quick_search_shortcut = shortcut
        else:
            from ...charon_logger import system_warning
            system_warning("Quick search shortcut not found in local handler!")
    
    def set_tiny_mode(self, active: bool):
        """Set tiny mode state and update keybind contexts."""
        self.tiny_mode_active = active
        self.update_quick_search_context(active)
    
    def refresh_keybinds(self):
        """Refresh all keybinds, checking for conflicts."""
        
        # Clear all existing shortcuts
        self._clear_all_keybinds()
        
        # Reload keybind definitions from database but don't register yet
        # Just load the definitions
        from ...settings import user_settings_db
        
        # Load local keybind definitions
        db_keybinds = user_settings_db.get_or_create_local_keybinds()
        self.local_handler.keybind_definitions = {}
        for action, data in db_keybinds.items():
            if data['enabled']:
                self.local_handler.keybind_definitions[action] = data['key_sequence']
        
        # Load global keybind definitions
        self.global_handler._load_keybinds()
        
        # Get all keybind definitions  
        local_defs = self.local_handler.get_keybind_definitions()
        global_defs = self.global_handler.get_keybind_definitions()
        
        
        # Check for conflicts
        conflicts = self._detect_conflicts(local_defs, global_defs)
        
        # Register keybinds with conflict resolution
        self._register_keybinds_with_conflicts(local_defs, global_defs, conflicts)
        
        # Re-apply tiny mode context if active
        # This fixes the issue where quick search stops working after keybind changes.
        # When keybinds are refreshed (e.g., after settings changes), all shortcuts
        # are cleared and re-created. The new quick_search shortcut is created with
        # the default WindowShortcut context. If tiny mode is active, we need to
        # update it to ApplicationShortcut context so it works globally.
        self.app_settings = user_settings_db.get_app_settings_for_host(self.host)
        if self.tiny_mode_active:
            # Use a small delay to ensure shortcuts are fully registered
            QtCore.QTimer.singleShot(50, lambda: self.update_quick_search_context(True))
    
    def _detect_conflicts(self, 
                         local_defs: Dict[str, str], 
                         global_defs: Dict[str, str]) -> List[Tuple[str, str, str]]:
        """
        Detect conflicts between local and global keybinds.
        
        Returns:
            List of (local_action, global_script, key_sequence) tuples
        """
        conflicts = []
        
        # Build reverse map of key sequences to actions
        local_by_key = {seq: action for action, seq in local_defs.items()}
        
        # Check each global keybind for conflicts
        for script_path, key_seq in global_defs.items():
            if key_seq in local_by_key:
                local_action = local_by_key[key_seq]
                conflicts.append((local_action, script_path, key_seq))
        
        return conflicts
    
    def _register_keybinds_with_conflicts(self, 
                                         local_defs: Dict[str, str],
                                         global_defs: Dict[str, str],
                                         conflicts: List[Tuple[str, str, str]]):
        """Register keybinds. When conflicts occur, local keybinds always win."""
        # Note: keybinds are already cleared in refresh_keybinds()
        
        # Process conflicts first
        conflicting_global_scripts = set()  # Track which global scripts to skip
        for local_action, global_script, key_seq in conflicts:
            # Local keybind always wins - mark global script to be skipped
            conflicting_global_scripts.add(global_script)
            # Unassign the global keybind from database
            user_settings_db.remove_hotkey_for_script_software(global_script, self.host)
        
        # Register all local keybinds
        for action, key_seq in local_defs.items():
            self._register_local_keybind(action, key_seq)
        
        # Register non-conflicting global keybinds
        for script_path, key_seq in global_defs.items():
            if script_path not in conflicting_global_scripts:
                self._register_global_keybind(script_path, key_seq)
    
    def _register_local_keybind(self, action: str, key_sequence: str):
        """Register a local keybind."""
        # Just register with the handler, don't store duplicates
        self.local_handler.register_keybind(action, key_sequence)
    
    def _register_global_keybind(self, script_path: str, key_sequence: str):
        """Register a global keybind."""
        # Just register with the handler, don't store duplicates
        self.global_handler.register_keybind(script_path, key_sequence)
    
    def _clear_all_keybinds(self):
        """Clear all registered keybinds."""
        # Since we're not storing duplicates anymore, just clear the handlers
        self.local_handler.clear_all()
        self.global_handler.clear_all()
        
        # Process events to ensure shortcuts are actually deleted
        QtWidgets.QApplication.processEvents()
        
        # Small delay to ensure Qt has cleaned up
        QtCore.QTimer.singleShot(10, lambda: None)
    
    def _on_local_keybind(self, action: str):
        """Handle local keybind trigger."""
        if action == 'tiny_mode':
            # Toggle tiny mode
            self.set_tiny_mode(not self.tiny_mode_active)
            
            # Send debug log about the mode change
            from ...charon_logger import system_debug
            if self.tiny_mode_active:
                system_debug("Tiny mode on")
            else:
                system_debug("Tiny mode off")
        
        self.keybind_triggered.emit('local', action)
    
    def _on_global_keybind(self, script_path: str):
        """Handle global keybind trigger."""
        self.keybind_triggered.emit('global', script_path)
    
    def add_global_keybind(self, script_path: str, key_sequence: str) -> bool:
        """
        Add a new global keybind, checking for conflicts.
        Local keybinds always take priority - cannot assign global if local uses it.
        
        Returns:
            True if successfully added, False if cancelled/failed
        """
        from .conflict_resolver import ConflictType
        from ...settings import user_settings_db
        
        # Check if this conflicts with a local keybind
        local_defs = self.local_handler.get_keybind_definitions()
        local_by_key = {seq: action for action, seq in local_defs.items()}
        
        if key_sequence in local_by_key:
            local_action = local_by_key[key_sequence]
            
            # Allow overwriting Charon keybind with confirmation dialog (same as settings UI)
            action_names = {
                'quick_search': 'Quick Search',
                'run_script': 'Run Script',
                'refresh': 'Refresh',
                'open_folder': 'Open Folder',
            }
            
            current_name = action_names.get(local_action, local_action)
            new_name = os.path.basename(script_path)
            
            # Use unified dialog
            from .conflict_resolver import KeybindConflictDialog
            dialog = KeybindConflictDialog(self.main_window, key_sequence, current_name, new_name)
            
            if dialog.exec_() != QtWidgets.QDialog.Accepted:
                return False  # User cancelled
            
            # Clear the local keybind (same pattern as settings UI)
            user_settings_db.set_local_keybind(local_action, "", True)
            
            # Process events to ensure database operation completes
            QtWidgets.QApplication.processEvents()
        else:
            # Check for conflicts with other global keybinds
            global_defs = self.global_handler.get_keybind_definitions()
            
            # Find if any other global keybind uses this key
            conflicting_script = None
            for other_script_path, key_seq in global_defs.items():
                if key_seq == key_sequence:
                    conflicting_script = other_script_path
                    break
            
            if conflicting_script:
                # Use centralized conflict handler for global vs global
                should_proceed = self.conflict_resolver.handle_keybind_conflict(
                    self.main_window,
                    key_sequence,
                    script_path,  # new target
                    ConflictType.GLOBAL_VS_GLOBAL,
                    conflicting_script  # existing target
                )
                
                if not should_proceed:
                    return False
        
        # Add to database
        # Note: set_hotkey expects (user, hotkey, script, software) - different order!
        # Normalize the script path before storing to ensure consistent comparisons
        import os
        normalized_path = os.path.normpath(script_path)
        user_settings_db.set_hotkey(key_sequence, normalized_path, self.host)
        
        # Refresh keybinds
        self.refresh_keybinds()
        return True
    
    def remove_global_keybind(self, script_path: str):
        """Remove a global keybind."""
        user_settings_db.remove_hotkey_for_script_software(script_path, self.host)
        self.refresh_keybinds()
    
    def get_app_setting(self, key: str):
        """Return a stored application-level setting."""
        value = self.app_settings.get(key)
        if value is None:
            value = user_settings_db.get_app_setting_for_host(key, self.host)
            if value is not None:
                self.app_settings[key] = value
        return value

    def set_app_setting(self, key: str, value: Any) -> None:
        """Persist an application-level setting and refresh cache."""
        str_value = str(value)
        user_settings_db.set_app_setting_for_host(key, self.host, str_value)
        self.app_settings[key] = str_value
        if key == "debug_logging":
            self._apply_debug_logging_setting()

    def reset_app_settings_to_defaults(self) -> None:
        """Reset all application settings for the current host to defaults."""
        user_settings_db.reset_app_settings_for_host(self.host)
        self.app_settings = user_settings_db.get_app_settings_for_host(self.host)
        self._apply_debug_logging_setting()

    def get_all_app_settings(self) -> Dict[str, str]:
        """Return a copy of cached application settings."""
        return dict(self.app_settings)

    def get_all_keybinds(self) -> Dict[str, Dict[str, str]]:
        """
        Get all registered keybinds.
        
        Returns:
            {
                'local': {action: key_sequence},
                'global': {script_path: key_sequence}
            }
        """
        return {
            'local': self.local_handler.get_keybind_definitions(),
            'global': self.global_handler.get_keybind_definitions()
        }
    
    def get_conflicts(self) -> List[Dict[str, str]]:
        """
        Get all current conflicts.
        
        Returns:
            List of conflict info dictionaries
        """
        local_defs = self.local_handler.get_keybind_definitions()
        global_defs = self.global_handler.get_keybind_definitions()
        conflicts = self._detect_conflicts(local_defs, global_defs)
        
        return [
            {
                'key_sequence': key_seq,
                'local_action': local_action,
                'global_script': global_script,
                'resolution': self.conflict_resolver.get_resolution(key_seq, local_action, global_script)
            }
            for local_action, global_script, key_seq in conflicts
        ]

    def _apply_debug_logging_setting(self, *, initial: bool = False) -> None:
        """Ensure config.DEBUG_MODE matches the stored preference."""
        value = self.app_settings.get("debug_logging", "off")
        enabled = str(value).lower() == "on"
        previous = self._debug_logging_active
        config.DEBUG_MODE = enabled
        self._debug_logging_active = enabled
        should_log = False
        if previous is None:
            should_log = enabled
        else:
            should_log = previous != enabled
        if should_log:
            from ...charon_logger import system_info
            state = "enabled" if enabled else "disabled"
            system_info(f"Debug logging {state} for host '{self.host}'.")

    def apply_debug_logging_setting(self) -> None:
        """Public wrapper so UI can re-apply after batch updates."""
        self._apply_debug_logging_setting()
