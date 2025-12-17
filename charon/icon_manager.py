"""
Global Icon Manager

Pre-loads and caches all software icons at startup for efficient access.
Icons are scaled once to the configured size and kept in memory.
"""

import os
from typing import Dict, Optional
from .qt_compat import QtGui, QtCore, KeepAspectRatio, SmoothTransformation
from . import config
from .charon_logger import system_info, system_debug


class IconManager:
    """
    Singleton class that manages all software icons.
    
    Icons are loaded once at startup and cached for the entire session.
    """
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(IconManager, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        # Only initialize once
        if not IconManager._initialized:
            self.icon_cache: Dict[str, Optional[QtGui.QPixmap]] = {}
            self.icon_size = QtCore.QSize(config.SOFTWARE_ICON_SIZE, config.SOFTWARE_ICON_SIZE)
            self._load_all_icons()
            IconManager._initialized = True
    
    def _load_all_icons(self):
        """Pre-load all software icons defined in config."""
        system_debug("Loading software icons...")
        
        # Get the charon module directory
        import charon
        charon_dir = os.path.dirname(os.path.abspath(charon.__file__))
        
        # Load each software icon
        for software_key, software_config in config.SOFTWARE.items():
            logo_path = software_config.get("logo")
            if not logo_path:
                system_debug(f"No logo path for {software_key}")
                self.icon_cache[software_key] = None
                continue
            
            # Convert relative path to absolute
            full_path = os.path.join(charon_dir, logo_path)
            
            if not os.path.exists(full_path):
                system_debug(f"Logo file not found: {full_path}")
                self.icon_cache[software_key] = None
                continue
            
            # Load the pixmap
            pixmap = QtGui.QPixmap(full_path)
            if pixmap.isNull():
                system_debug(f"Failed to load pixmap: {full_path}")
                self.icon_cache[software_key] = None
                continue
            
            # Scale to configured size with smooth transformation
            scaled_pixmap = pixmap.scaled(
                self.icon_size, 
                KeepAspectRatio, 
                SmoothTransformation
            )
            
            # Cache both lowercase and capitalized versions for convenience
            self.icon_cache[software_key] = scaled_pixmap
            self.icon_cache[software_key.capitalize()] = scaled_pixmap
            
            system_debug(f"Loaded icon for {software_key}: {self.icon_size.width()}x{self.icon_size.height()}")
        
        system_debug(f"Loaded {len([v for v in self.icon_cache.values() if v is not None])} software icons")
    
    def get_icon(self, software: str) -> Optional[QtGui.QPixmap]:
        """
        Get a software icon.
        
        Args:
            software: Software name (case-insensitive)
            
        Returns:
            QPixmap of the icon or None if not found
        """
        return self.icon_cache.get(software.lower())
    
    def get_icon_size(self) -> QtCore.QSize:
        """Get the configured icon size."""
        return self.icon_size


# Global instance getter
def get_icon_manager() -> IconManager:
    """Get the global IconManager instance."""
    return IconManager()
