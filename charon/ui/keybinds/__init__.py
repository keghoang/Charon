"""
Keybind Management System for Charon

This package provides a clean separation between:
- Local keybinds: Charon UI shortcuts (only active when focused)
- Global keybinds: User-assigned script shortcuts (always active)

It handles conflict detection, priority resolution, and user preferences.
"""

from .keybind_manager import KeybindManager
from .local_handler import LocalKeybindHandler
from .global_handler import GlobalKeybindHandler
from .conflict_resolver import ConflictResolver
from .settings_ui import KeybindSettingsDialog

__all__ = [
    'KeybindManager',
    'LocalKeybindHandler',
    'GlobalKeybindHandler',
    'ConflictResolver',
    'KeybindSettingsDialog'
]