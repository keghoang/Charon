"""
Centralized Window Manager for Galt

This module handles all window creation, docking, and host-specific behaviors.
All window creation should go through this manager to ensure consistency.
"""

import os
import sys
from typing import Optional, Dict, Any
from ..qt_compat import QtWidgets, QtCore, Qt

from .main_window import GaltWindow
from ..galt_logger import system_info, system_debug, system_error, system_warning
from ..utilities import detect_host
from .. import config


class WindowManager:
    """
    Centralized manager for creating Galt windows with appropriate settings for each host.
    
    This consolidates all window creation logic from __init__.py and main.py into one place.
    """

    _ACTIVE_WINDOW: Optional[GaltWindow] = None
    
    @staticmethod
    def create_window(
        host: Optional[str] = None,
        user: Optional[str] = None,
        global_path: Optional[str] = None,
        dock: bool = False,
        show: bool = True,
        xoffset: int = 0,
        yoffset: int = 0
    ) -> GaltWindow:
        """
        Create a Galt window with appropriate settings.
        
        Args:
            host: Host override (Maya, Nuke, etc). Auto-detects if None.
            user: User override. Auto-detects if None.
            global_path: Script repository path
            dock: Whether to dock the window (only works in Maya/Nuke)
            show: Whether to show the window immediately
            
        Returns:
            GaltWindow instance (or docked container in Maya/Nuke)
        """
        # Reuse existing window if one already exists
        existing_window = WindowManager._get_existing_window()
        if existing_window:
            if global_path and hasattr(existing_window, "global_path") and existing_window.global_path != global_path:
                existing_window.global_path = global_path
            existing_window.show()
            try:
                existing_window.raise_()
                existing_window.activateWindow()
            except Exception:
                pass
            return existing_window

        # Auto-detect host if not provided
        if not host:
            host = detect_host()
        
        # Get version for display
        from ..utilities import get_host_version
        version = get_host_version(host)
        version_str = f" {version}" if version else ""
        
        system_info(f"Creating Galt window for host: {host}{version_str}")
        
        # Get host configuration with fallback
        host_config = WindowManager.get_host_config(host)
        
        # Handle docked windows
        if dock:
            if not host_config["supports_docking"]:
                system_info(f"Docking not supported for {host}, creating standalone window")
                dock = False
            elif host.lower() == "maya":
                return WindowManager._create_maya_docked(global_path, xoffset, yoffset)
            elif host.lower() == "nuke":
                return WindowManager._create_nuke_docked(global_path, xoffset, yoffset)
        
        # Create standalone window
        return WindowManager._create_standalone(host, user, global_path, show, xoffset, yoffset)
    
    @staticmethod
    def _create_standalone(
        host: str,
        user: Optional[str],
        global_path: Optional[str],
        show: bool,
        xoffset: int = 0,
        yoffset: int = 0
    ) -> GaltWindow:
        """
        Create a standalone (non-docked) Galt window.
        """
        # Ensure QApplication exists
        app = None
        if not QtWidgets.QApplication.instance():
            app = QtWidgets.QApplication(sys.argv)
        
        # Create the window
        window = GaltWindow(
            global_path=global_path,
            local_path=None,  # Deprecated
            host=host,
            startup_mode=None
        )
        
        # Get host configuration
        host_config = WindowManager.get_host_config(host)
        
        # Handle parenting to host main window if enabled
        if host_config.get("parent_to_host", False):
            parent_window = WindowManager._get_host_main_window(host)
            if parent_window:
                window.setParent(parent_window)
                system_info(f"Set {host} main window as parent")
            else:
                system_warning(f"Failed to get {host} main window for parenting")
        
        # Apply window flags based on host
        WindowManager._apply_window_flags(window, host)
        
        if show:
            window.show()
            if xoffset or yoffset:
                try:
                    geo = window.geometry()
                    window.move(geo.x() + xoffset, geo.y() + yoffset)
                except Exception:
                    pass
            # Focus the window after showing
            window.raise_()
            window.activateWindow()

        WindowManager._register_active_window(window)
            
        return window
    
    @staticmethod
    def _apply_window_flags(window: GaltWindow, host: str):
        """
        Apply appropriate window flags based on the host application.
        
        Uses configuration from config.py with automatic fallback.
        """
        # Get configuration with fallback
        host_config = WindowManager.get_host_config(host)
        
        # Parse window flags from string (e.g., "Qt.Window|Qt.Tool" -> QtCore.Qt.Window | QtCore.Qt.Tool)
        flag_str = host_config["window_flags"]
        if flag_str:
            # Handle combined flags with | operator
            flag_strings = [f.strip() for f in flag_str.split("|")]
            combined_flags = None
            
            for flag_string in flag_strings:
                # Convert string to actual Qt flag
                flag_parts = flag_string.split(".")
                if len(flag_parts) == 2 and flag_parts[0] == "Qt":
                    flag = getattr(Qt, flag_parts[1], None)
                    if flag is not None:
                        if combined_flags is None:
                            combined_flags = flag
                        else:
                            combined_flags |= flag
            
            # Apply the combined flags, fallback to Qt.Window if nothing valid found
            final_flags = combined_flags if combined_flags is not None else Qt.Window
            window.setWindowFlags(final_flags)
        try:
            window.setWindowFlag(Qt.WindowCloseButtonHint, True)
            window.setWindowFlag(Qt.WindowSystemMenuHint, True)
        except Exception:
            pass
        
        # Apply window attributes
        for attr_str in host_config.get("window_attributes", []):
            # Convert string to actual Qt attribute
            attr_parts = attr_str.split(".")
            if len(attr_parts) == 2 and attr_parts[0] == "Qt":
                attr = getattr(Qt, attr_parts[1], None)
                if attr:
                    window.setAttribute(attr, True)
        
        # Set window title
        window.setWindowTitle(f"Charon - {host}")
        
        system_debug(f"Applied window config for {host}: {host_config['description']}")
    
    @staticmethod
    def _create_maya_docked(global_path: Optional[str], xoffset: int = 0, yoffset: int = 0) -> QtWidgets.QWidget:
        """
        Create a docked Galt window in Maya using workspaceControl.
        """
        try:
            import maya.cmds as cmds
            import maya.OpenMayaUI as omui
            from shiboken2 import wrapInstance
            
            # Delete existing workspace control if it exists
            ctrl_name = "GaltWorkspace"
            if cmds.workspaceControl(ctrl_name, exists=True):
                cmds.deleteUI(ctrl_name)
            
            # Import config for window dimensions
            from .. import config
            
            # Create workspace control
            ctrl = cmds.workspaceControl(
                ctrl_name,
                label="Galt",
                initialWidth=config.WINDOW_WIDTH,
                initialHeight=config.WINDOW_HEIGHT,
                floating=True  # Start floating, user can dock it
            )
            
            # Get the Qt widget for the workspace control
            ptr = omui.MQtUtil.findControl(ctrl_name)
            workspace_widget = wrapInstance(int(ptr), QtWidgets.QWidget)
            
            # Add layout if needed
            if workspace_widget.layout() is None:
                layout = QtWidgets.QVBoxLayout(workspace_widget)
                layout.setContentsMargins(0, 0, 0, 0)
                workspace_widget.setLayout(layout)
            
            # Create Galt widget
            galt_widget = GaltWindow(
                global_path=global_path,
                local_path=None,
                host="Maya"  # Force Maya as host
            )
            
            # Add to workspace control
            workspace_widget.layout().addWidget(galt_widget)
            
            system_info("Created Maya docked window (workspaceControl)")
            
            # Return the Galt widget, not the workspace control
            return galt_widget
            
        except Exception as e:
            system_error(f"Failed to create Maya docked window: {str(e)}")
            system_info("Falling back to standalone window")
            return WindowManager._create_standalone("Maya", None, global_path, True, xoffset, yoffset)
    
    @staticmethod
    def _create_nuke_docked(global_path: Optional[str], xoffset: int = 0, yoffset: int = 0) -> QtWidgets.QWidget:
        """
        Create a docked Galt panel in Nuke.
        """
        try:
            import nukescripts.panels as panels
            
            # Define a function that creates a new Galt widget
            # This function will be called by Nuke when the panel is opened
            def create_galt_panel():
                return GaltWindow(
                    global_path=global_path,
                    local_path=None,
                    host="Nuke"  # Force Nuke as host
                )
            
            # Make the function available in the global namespace
            # so Nuke can find it when evaluating the string
            import __main__
            __main__.create_galt_panel = create_galt_panel
            
            # Register as a Nuke panel
            # Nuke expects a string that can be evaluated, not a function object
            panels.registerWidgetAsPanel(
                "create_galt_panel",  # String name of the function
                "Galt",              # Panel title
                "GaltPanel"          # Panel ID
            )
            
            system_info("Registered Galt as Nuke panel")
            
            # Create and return a widget for immediate use
            # In Nuke, users would go to Windows > Custom > Galt to open it
            return create_galt_panel()
            
        except Exception as e:
            system_error(f"Failed to create Nuke panel: {str(e)}")
            system_info("Falling back to standalone window")
        return WindowManager._create_standalone("Nuke", None, global_path, True, xoffset, yoffset)
    
    @staticmethod
    def _get_existing_window() -> Optional[GaltWindow]:
        def is_galt_window(widget):
            return getattr(widget, "_charon_is_galt_window", False) or getattr(widget, "objectName", lambda: "")() == "CharonGaltWindow"

        cached = WindowManager._ACTIVE_WINDOW
        if cached and is_galt_window(cached):
            return cached

        app = QtWidgets.QApplication.instance()
        if app:
            for widget in app.topLevelWidgets():
                if is_galt_window(widget):
                    WindowManager._register_active_window(widget)
                    return widget

        WindowManager._ACTIVE_WINDOW = None
        return None
    
    @staticmethod
    def _register_active_window(window: GaltWindow) -> None:
        WindowManager._ACTIVE_WINDOW = window
        try:
            system_debug(f"Registered active Galt window id={id(window)}")
        except Exception:
            pass
        try:
            window.destroyed.connect(lambda *_: WindowManager._on_window_destroyed(window))
        except Exception:
            pass

    @staticmethod
    def _on_window_destroyed(window: GaltWindow) -> None:
        if WindowManager._ACTIVE_WINDOW is window:
            WindowManager._ACTIVE_WINDOW = None
    
    @staticmethod
    def get_host_config(host: str) -> Dict[str, Any]:
        """
        Get window configuration for a host with fallback to defaults.
        
        Args:
            host: Host name (maya, nuke, windows, etc.)
            
        Returns:
            Configuration dict with all required keys
        """
        host_lower = host.lower() if host else "windows"
        
        # Get host-specific config or empty dict
        host_config = config.WINDOW_CONFIGS.get(host_lower, {})
        
        # Merge with defaults (host config overrides defaults)
        merged_config = config.DEFAULT_WINDOW_CONFIG.copy()
        merged_config.update(host_config)
        
        return merged_config
    
    @staticmethod
    def get_window_behavior_info() -> Dict[str, Any]:
        """
        Get information about window behaviors for each host.
        
        Returns a dict describing the current implementation including defaults.
        """
        # Include all configured hosts
        info = {}
        for host in config.WINDOW_CONFIGS:
            host_config = WindowManager.get_host_config(host)
            info[host] = {
                "flags": host_config["window_flags"],
                "behavior": "Regular window when standalone" if host_config["supports_docking"] else "Regular window with taskbar entry",
                "docking": host_config["supports_docking"],
                "docking_method": host_config["docking_method"],
                "parent_to_host": host_config.get("parent_to_host", False),
                "notes": host_config["description"]
            }
        
        # Add info about default behavior
        info["default"] = {
            "flags": config.DEFAULT_WINDOW_CONFIG["window_flags"],
            "behavior": "Regular window with taskbar entry",
            "docking": config.DEFAULT_WINDOW_CONFIG["supports_docking"],
            "docking_method": config.DEFAULT_WINDOW_CONFIG["docking_method"],
            "parent_to_host": config.DEFAULT_WINDOW_CONFIG.get("parent_to_host", False),
            "notes": config.DEFAULT_WINDOW_CONFIG["description"] + " (applies to any undefined host)"
        }
        
        return info


    @staticmethod
    def _get_host_main_window(host: str) -> Optional[QtWidgets.QWidget]:
        """
        Get the main window of the host application.
        
        Args:
            host: Host name (maya, nuke, etc.)
            
        Returns:
            QtWidgets.QWidget of the host's main window, or None if not found
        """
        try:
            if host.lower() == "maya":
                return WindowManager._get_maya_main_window()
            elif host.lower() == "nuke":
                return WindowManager._get_nuke_main_window()
            else:
                return None
        except Exception as e:
            system_error(f"Failed to get {host} main window: {str(e)}")
            return None
    
    @staticmethod
    def _get_maya_main_window() -> Optional[QtWidgets.QWidget]:
        """Get Maya's main window as a Qt widget."""
        try:
            import maya.OpenMayaUI as omui
            from shiboken2 import wrapInstance
            from ..qt_compat import QtWidgets
            
            # Get Maya's main window
            maya_main_window_ptr = omui.MQtUtil.mainWindow()
            maya_main_window = wrapInstance(int(maya_main_window_ptr), QtWidgets.QWidget)
            return maya_main_window
        except Exception as e:
            system_error(f"Failed to get Maya main window: {str(e)}")
            return None
    
    @staticmethod
    def _get_nuke_main_window() -> Optional[QtWidgets.QWidget]:
        """Get Nuke's main window as a Qt widget."""
        try:
            import nuke
            from ..qt_compat import QtWidgets
            
            # Nuke's main window is typically the first top-level widget
            app = QtWidgets.QApplication.instance()
            for widget in app.topLevelWidgets():
                if widget.isVisible() and widget.windowTitle():
                    # Look for Nuke's main window (usually has "Nuke" in title)
                    if "Nuke" in widget.windowTitle():
                        return widget
            return None
        except Exception as e:
            system_error(f"Failed to get Nuke main window: {str(e)}")
            return None


def create_galt_window(**kwargs) -> GaltWindow:
    """
    Convenience function that forwards to WindowManager.create_window().
    
    This provides a simple API for window creation.
    """
    return WindowManager.create_window(**kwargs)
