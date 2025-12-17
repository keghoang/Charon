"""
Conflict resolution for keybind conflicts.

This module handles conflicts between local (Charon) and global (script) keybinds.
Current policy: Local keybinds always win - they cannot be overridden.
"""

from ...qt_compat import QtWidgets, QtCore, WindowContextHelpButtonHint, WindowCloseButtonHint
from enum import Enum
import os
from typing import Dict, Optional, Tuple


class ConflictType(Enum):
    """Types of keybind conflicts."""
    LOCAL_VS_GLOBAL = "local_vs_global"
    GLOBAL_VS_GLOBAL = "global_vs_global"
    

class ConflictResolution(Enum):
    """Possible conflict resolutions."""
    LOCAL_PRIORITY = "local_priority"
    GLOBAL_PRIORITY = "global_priority"
    DISABLED = "disabled"
    CANCEL = "cancel"


class ConflictResolver:
    """Manages keybind conflict resolution."""
    
    def __init__(self, parent):
        """Initialize resolver.
        
        Args:
            parent: Parent widget (usually the main window)
        """
        self.parent = parent
        # In-memory storage of conflict resolutions
        self._resolutions = {}
    
    def handle_keybind_conflict(self, parent: QtWidgets.QWidget, 
                               key_sequence: str, 
                               new_target: str,
                               conflict_type: ConflictType,
                               existing_target: str) -> bool:
        """
        Handle a keybind conflict by showing appropriate dialog.
        
        Args:
            parent: Parent widget for dialog
            key_sequence: The conflicting key sequence
            new_target: New assignment target (script path or local action)
            conflict_type: Type of conflict
            existing_target: Existing assignment (script path or local action)
            
        Returns:
            True if user wants to proceed with reassignment, False otherwise
        """
        if conflict_type == ConflictType.LOCAL_VS_GLOBAL:
            # Show local vs global conflict dialog
            return self.show_conflict_warning(parent, key_sequence, existing_target, new_target)
        elif conflict_type == ConflictType.GLOBAL_VS_GLOBAL:
            # Show global vs global conflict dialog
            return self._show_global_conflict_warning(parent, key_sequence, new_target, existing_target)
        
        return False
    
    def _show_global_conflict_warning(self, parent: QtWidgets.QWidget,
                                     key_sequence: str,
                                     new_script: str,
                                     old_script: str) -> bool:
        """Show warning for global vs global conflicts."""
        # Format names for display
        current_name = os.path.basename(old_script)
        new_name = os.path.basename(new_script)
        
        # Create unified dialog
        dialog = KeybindConflictDialog(parent, key_sequence, current_name, new_name)
        result = dialog.exec_()
        return result == QtWidgets.QDialog.Accepted
    
    def show_conflict_warning(self, parent: QtWidgets.QWidget, 
                            key_sequence: str, 
                            local_action: str,
                            script_path: str) -> bool:
        """
        Show a conflict warning dialog for local vs global conflicts.
        
        Returns:
            True if user wants to proceed with override, False otherwise
        """
        # Format names for display
        from ..main_window import CharonWindow
        if hasattr(parent, 'window') and callable(parent.window):
            main_window = parent.window()
            if isinstance(main_window, CharonWindow) and hasattr(main_window, 'keybind_manager'):
                action_names = main_window.keybind_manager.get_action_display_names()
                current_name = action_names.get(local_action, local_action)
            else:
                current_name = local_action
        else:
            current_name = local_action
            
        new_name = os.path.basename(script_path)
        
        # Create unified dialog
        dialog = KeybindConflictDialog(parent, key_sequence, current_name, new_name)
        result = dialog.exec_()
        
        return result == QtWidgets.QDialog.Accepted
    
    def clear_resolution(self, key_sequence: str):
        """Clear a saved resolution."""
        # Note: Conflict resolution is now handled automatically with "local always wins"
        # This method is kept for compatibility but doesn't need to do anything
        if key_sequence in self._resolutions:
            del self._resolutions[key_sequence]
    
    def get_resolutions(self) -> Dict[str, ConflictResolution]:
        """Get all saved resolutions."""
        # Note: With "local always wins" policy, we don't persist resolutions
        # Returns in-memory resolutions only
        return {}


class KeybindConflictDialog(QtWidgets.QDialog):
    """Keybind conflict dialog for all conflict types."""
    
    def __init__(self, parent: QtWidgets.QWidget, key_sequence: str,
                 current_name: str, new_name: str):
        super().__init__(parent)
        self.setWindowTitle("Keybind Conflict")
        self.setWindowFlag(WindowContextHelpButtonHint, False)
        self.setWindowFlag(WindowCloseButtonHint, True)
        self.setMinimumWidth(400)
        
        # Create layout
        layout = QtWidgets.QVBoxLayout(self)
        
        # Warning icon and message
        message_layout = QtWidgets.QHBoxLayout()
        
        # Warning icon
        icon_label = QtWidgets.QLabel()
        icon_label.setPixmap(
            self.style().standardPixmap(QtWidgets.QStyle.SP_MessageBoxWarning, None, self)
        )
        message_layout.addWidget(icon_label)
        
        # Warning text with consistent format
        message = QtWidgets.QLabel(
            f"The keybind <b>{key_sequence}</b> is currently assigned to:<br>"
            f"<b>{current_name}</b><br><br>"
            f"Do you want to reassign it to <b>{new_name}</b>?"
        )
        message.setWordWrap(True)
        message_layout.addWidget(message, 1)
        
        layout.addLayout(message_layout)
        layout.addSpacing(20)
        
        # Buttons
        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addStretch()
        
        self.yes_button = QtWidgets.QPushButton("Yes")
        self.yes_button.setDefault(True)  # Default to Yes
        self.yes_button.clicked.connect(self.accept)
        button_layout.addWidget(self.yes_button)
        
        self.no_button = QtWidgets.QPushButton("No")
        self.no_button.clicked.connect(self.reject)
        button_layout.addWidget(self.no_button)
        
        layout.addLayout(button_layout)