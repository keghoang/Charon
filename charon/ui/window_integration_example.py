"""
Example of how to integrate WindowManager with the existing Charon code.

This shows how to modify the launch function to use the new window management system.
"""

from ..qt_compat import QtWidgets, exec_application
from .main_window import CharonWindow
from .window_manager import WindowManager
from ..utilities import detect_host
from ..charon_logger import system_info, system_debug


def launch_with_window_manager(global_path=None, host=None, dock=False, **kwargs):
    """
    Example launch function using the WindowManager.
    
    This could replace or supplement the existing launch function in main.py
    """
    # Detect or use provided host
    if not host:
        host = detect_host()
    
    system_info(f"Launching Charon for host: {host}")
    
    # Get or create Qt application
    app = QtWidgets.QApplication.instance()
    if not app:
        app = QtWidgets.QApplication([])
    
    # Create the Charon widget
    charon_widget = CharonWindow(
        global_path=global_path,
        host=host,
        **kwargs
    )
    
    # Create window manager
    window_manager = WindowManager()
    
    # Create appropriate window for the host
    window_options = {
        "title": f"Charon - {host}",
        "as_tool": True,  # Make it a tool window by default
        "stay_on_top": kwargs.get("stay_on_top", False),
    }
    
    window = window_manager.create_window(
        charon_widget, 
        host=host,
        **window_options
    )
    
    # Attempt docking if requested
    if dock:
        dock_options = {
            "dock_name": "CharonDock",
            "label": "Charon Script Launcher",
            "floating": kwargs.get("floating", False),
        }
        
        success = window_manager.dock_window(
            window,
            host=host,
            dock_area=kwargs.get("dock_area", "right"),
            **dock_options
        )
        
        if not success:
            system_info("Docking not available, showing as floating window")
    
    # Show the window
    window.show()
    
    # For standalone mode, run the event loop
    if host.lower() == "windows":
        exec_application(app)
    
    return window


# Example usage patterns for different hosts
def usage_examples():
    """
    Show how to use the window manager for different scenarios.
    """
    # Example 1: Simple floating window (default)
    window = launch_with_window_manager()
    
    # Example 2: Docked window in Maya
    window = launch_with_window_manager(
        host="maya",
        dock=True,
        dock_area="right"
    )
    
    # Example 3: Floating tool window in Nuke with stay-on-top
    window = launch_with_window_manager(
        host="nuke",
        dock=False,
        stay_on_top=True
    )
    
    # Example 4: Custom dock configuration in Maya
    window = launch_with_window_manager(
        host="maya",
        dock=True,
        dock_area="left",
        dock_name="MyCustomCharonDock",
        floating=True  # Start docked but allow undocking
    )
