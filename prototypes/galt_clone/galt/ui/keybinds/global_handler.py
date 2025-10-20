"""
Global Keybind Handler

Manages user-assigned script keybinds that are always active,
even when the Galt window doesn't have focus.
"""

from typing import Dict, Optional
from ...qt_compat import QtCore, QtWidgets, QtGui, Qt, QKeySequence, QShortcut, QApplication
from ...settings import user_settings_db


class GlobalKeybindHandler(QtCore.QObject):
    """
    Handles global keybinds for user-assigned scripts.
    
    These keybinds:
    - Use ApplicationShortcut context (always active)
    - Take priority over local keybinds
    - Allow quick script execution from anywhere
    """
    
    # Signal emitted when a keybind is triggered
    keybind_triggered = QtCore.Signal(str)  # script_path
    
    def __init__(self, parent_widget: QtWidgets.QWidget, host: str):
        super().__init__(parent_widget)
        self.parent_widget = parent_widget
        self.host = host
        self.shortcuts: Dict[str, QShortcut] = {}  # script_path -> shortcut
        self.keybind_map: Dict[str, str] = {}  # script_path -> key_sequence
        
        # Load keybinds from database
        self._load_keybinds()
    
    def _load_keybinds(self):
        """Load global keybinds from database."""
        try:
            hotkeys = user_settings_db.get_all_hotkeys(self.host)
            # Convert from {hotkey: script_path} to {script_path: hotkey}
            self.keybind_map = {script_path: hotkey for hotkey, script_path in hotkeys.items()}
        except Exception as e:
            # Silently fail
            self.keybind_map = {}
    
    def register_keybind(self, script_path: str, key_sequence: str) -> Optional[QShortcut]:
        """
        Register a global keybind.
        
        Args:
            script_path: Path to the script
            key_sequence: The key sequence (e.g., 'Ctrl+Shift+3')
            
        Returns:
            The created QShortcut or None if failed
        """
        
        try:
            # Remove existing shortcut for this script
            if script_path in self.shortcuts:
                old_shortcut = self.shortcuts[script_path]
                old_shortcut.setEnabled(False)
                old_shortcut.deleteLater()
                del self.shortcuts[script_path]
                # Process events to ensure it's deleted
                QApplication.processEvents()
            
            # Create new shortcut with ApplicationShortcut context
            shortcut = QShortcut(QKeySequence(key_sequence), self.parent_widget)
            shortcut.setContext(Qt.ApplicationShortcut)  # Always active
            shortcut.setEnabled(True)  # Explicitly enable the shortcut
            
            # Connect to handler - fix lambda capture issue
            shortcut.activated.connect(lambda s=script_path: self._on_keybind_activated(s))
            
            # Store shortcut
            self.shortcuts[script_path] = shortcut
            self.keybind_map[script_path] = key_sequence
            
            return shortcut
            
        except Exception as e:
            # Silently fail
            pass
            return None
    
    def _on_keybind_activated(self, script_path: str):
        """Handle keybind activation."""
        self.keybind_triggered.emit(script_path)
    
    def get_keybind_definitions(self) -> Dict[str, str]:
        """Get current keybind definitions."""
        return self.keybind_map.copy()
    
    def update_keybind(self, script_path: str, new_sequence: str):
        """Update a keybind."""
        # Update in database
        # Note: set_hotkey expects (user, hotkey, script, software) - different order!
        user_settings_db.set_hotkey(new_sequence, script_path, self.host)
        
        # Update locally
        self.keybind_map[script_path] = new_sequence
        
        # Re-register shortcut
        if script_path in self.shortcuts:
            self.register_keybind(script_path, new_sequence)
    
    def remove_keybind(self, script_path: str):
        """Remove a keybind."""
        # Remove from database
        user_settings_db.remove_hotkey_for_script_software(script_path, self.host)
        
        # Remove locally
        if script_path in self.shortcuts:
            self.shortcuts[script_path].deleteLater()
            del self.shortcuts[script_path]
        
        if script_path in self.keybind_map:
            del self.keybind_map[script_path]
    
    def clear_all(self):
        """Clear all registered shortcuts."""
        for script_path, shortcut in list(self.shortcuts.items()):
            shortcut.setEnabled(False)
            shortcut.deleteLater()
        self.shortcuts.clear()
    
    def refresh_from_database(self):
        """Refresh keybinds from database."""
        # Clear existing
        self.clear_all()
        
        # Reload
        self._load_keybinds()
        
        # Re-register all
        for script_path, key_sequence in self.keybind_map.items():
            self.register_keybind(script_path, key_sequence)
    
    def get_script_for_key(self, key_sequence: str) -> Optional[str]:
        """Get the script path associated with a key sequence."""
        for script_path, seq in self.keybind_map.items():
            if seq == key_sequence:
                return script_path
        return None
    
    def is_keybind_used(self, key_sequence: str) -> bool:
        """Check if a key sequence is already used."""
        return key_sequence in self.keybind_map.values()
    
    def validate_script_exists(self, script_path: str) -> bool:
        """Check if a script still exists."""
        import os
        return os.path.exists(script_path)