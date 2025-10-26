"""
Local Keybind Handler

Manages Charon's built-in UI keybinds that are only active when the window has focus.
"""

from typing import Dict, Optional, Callable, Any
from ...qt_compat import QtCore, QtWidgets, QtGui, QShortcut
from ... import config


class LocalKeybindHandler(QtCore.QObject):
    """
    Handles local keybinds that are only active when Charon window has focus.
    
    These include:
    - Tab: Quick search
    - Ctrl+Enter: Run script
    - Ctrl+R: Refresh
    - Ctrl+O: Open folder
    """
    
    # Signal emitted when a keybind is triggered
    keybind_triggered = QtCore.Signal(str)  # action_name
    
    # Default keybind definitions from config
    DEFAULT_KEYBINDS = config.DEFAULT_LOCAL_KEYBINDS
    
    def __init__(self, parent_widget: QtWidgets.QWidget):
        super().__init__(parent_widget)
        self.parent_widget = parent_widget
        self.shortcuts: Dict[str, QShortcut] = {}
        self.enabled = True
        
        # Load keybind definitions from database
        self._load_keybinds_from_database()
    
    def _load_keybinds_from_database(self):
        """Load keybind definitions from the database."""
        from ...settings import user_settings_db
        
        # Get or create keybinds for this user
        db_keybinds = user_settings_db.get_or_create_local_keybinds()
        
        # Build keybind definitions from database data
        self.keybind_definitions = {}
        for action, data in db_keybinds.items():
            if data['enabled']:
                self.keybind_definitions[action] = data['key_sequence']
    
    def register_keybind(self, action: str, key_sequence: str) -> Optional[QShortcut]:
        """
        Register a local keybind.
        
        Args:
            action: The action name (e.g., 'run_script')
            key_sequence: The key sequence (e.g., 'Ctrl+Return')
            
        Returns:
            The created QShortcut or None if failed
        """
        
        if not self.enabled:
            return None
            
        try:
            # Remove existing shortcut for this action
            if action in self.shortcuts:
                old_shortcut = self.shortcuts[action]
                old_shortcut.setEnabled(False)
                old_shortcut.deleteLater()
                del self.shortcuts[action]
                # Process events to ensure it's deleted
                QtWidgets.QApplication.processEvents()
            
            # Create new shortcut
            shortcut = QShortcut(QtGui.QKeySequence(key_sequence), self.parent_widget)
            
            # Tiny mode is special - it uses global context
            if action == 'tiny_mode':
                shortcut.setContext(QtCore.Qt.ApplicationShortcut)  # Always active
            else:
                shortcut.setContext(QtCore.Qt.WindowShortcut)  # Only active when window has focus
            
            # Connect to handler - fix lambda capture issue
            shortcut.activated.connect(lambda a=action: self._on_keybind_activated(a))
            
            # Store shortcut
            self.shortcuts[action] = shortcut
            self.keybind_definitions[action] = key_sequence
            
            return shortcut
            
        except Exception as e:
            # Silently fail
            pass
            return None
    
    def _on_keybind_activated(self, action: str):
        """Handle keybind activation."""
        if self.enabled:
            self.keybind_triggered.emit(action)
    
    def get_keybind_definitions(self) -> Dict[str, str]:
        """Get current keybind definitions."""
        return self.keybind_definitions.copy()
    
    def update_keybind(self, action: str, new_sequence: str):
        """Update a keybind definition."""
        if action in self.keybind_definitions:
            self.keybind_definitions[action] = new_sequence
            # Re-register if there's an existing shortcut
            if action in self.shortcuts:
                self.register_keybind(action, new_sequence)
    
    def disable_keybind(self, action: str):
        """Disable a specific keybind."""
        if action in self.shortcuts:
            self.shortcuts[action].setEnabled(False)
    
    def remove_keybind(self, action: str):
        """Completely remove a keybind."""
        if action in self.shortcuts:
            shortcut = self.shortcuts[action]
            shortcut.setEnabled(False)
            shortcut.deleteLater()
            del self.shortcuts[action]
            # Process events to ensure it's deleted
            QtWidgets.QApplication.processEvents()
    
    def enable_keybind(self, action: str):
        """Enable a specific keybind."""
        if action in self.shortcuts:
            self.shortcuts[action].setEnabled(True)
    
    def set_enabled(self, enabled: bool):
        """Enable or disable all local keybinds."""
        self.enabled = enabled
        for shortcut in self.shortcuts.values():
            shortcut.setEnabled(enabled)
    
    def clear_all(self):
        """Clear all registered shortcuts."""
        for action, shortcut in list(self.shortcuts.items()):
            shortcut.setEnabled(False)
            shortcut.deleteLater()
        self.shortcuts.clear()
    
    def get_action_for_key(self, key_sequence: str) -> Optional[str]:
        """Get the action associated with a key sequence."""
        for action, seq in self.keybind_definitions.items():
            if seq == key_sequence:
                return action
        return None
    
    def is_keybind_used(self, key_sequence: str) -> bool:
        """Check if a key sequence is already used."""
        return key_sequence in self.keybind_definitions.values()
    
    def get_full_keybind_info(self) -> Dict[str, Dict[str, Any]]:
        """Get full keybind information including enabled state."""
        # Get keybind info from database
        
        # Get from database
        from ...settings import user_settings_db
        db_keybinds = user_settings_db.get_or_create_local_keybinds()
        
        # Add default info
        for action, data in db_keybinds.items():
            default_config = self.DEFAULT_KEYBINDS.get(action, {})
            data['default'] = default_config.get('key_sequence', '') if isinstance(default_config, dict) else ''
        
        return db_keybinds
    
    def refresh_keybinds(self):
        """Refresh keybinds from database - just load definitions, don't register."""
        # Clear existing shortcuts
        self.clear_all()
        
        # Reload from database
        self._load_keybinds_from_database()
        
        # Don't auto-register here - let the manager handle conflicts first
