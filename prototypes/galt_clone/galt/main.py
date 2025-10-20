import os
import sys
import argparse
from .qt_compat import QtWidgets, QtCore
from . import config, utilities
from .ui.window_manager import WindowManager
from .galt_logger import system_info, system_debug, system_error

def launch(host_override=None, user_override=None, global_path=None, local_path=None, script_paths=None, dock=False, debug=False, xoffset=0, yoffset=0):
    """
    Launch the Galt window
    
    Args:
        host_override (str, optional): Override the host detection
        user_override (str, optional): Override the windows username
        global_path (str, optional): Override the global repository path
        local_path (str, optional): Deprecated, kept for backwards compatibility
        script_paths (list, optional): List of paths to add to sys.path
        debug (bool, optional): Enable debug mode for verbose output
    
    Returns:
        GaltWindow: The main window instance
    """
    # Set global debug mode
    config.DEBUG_MODE = debug
    # Use host override or detect host
    detected_host = host_override or utilities.detect_host()
    system_info(f"Host detected/forced as: {detected_host}")
    
    # Setup paths - either from script_paths or global_path or config default
    if script_paths:
        global_repo = utilities.setup_script_paths(script_paths)
        system_debug(f"Using script_paths: {script_paths}")
    else:
        global_repo = global_path or config.GLOBAL_REPO_PATH
        system_debug(f"Using global_path: {global_repo}")

    # Initialize the database with the determined global path
    from .settings import user_settings_db
    user_settings_db.initialize(global_repo)
    
    # Create directory if it doesn't exist
    if not os.path.exists(global_repo):
        try:
            os.makedirs(global_repo)
            system_info(f"Created directory: {global_repo}")
        except Exception as e:
            system_error(f"Error creating directory {global_repo}: {str(e)}")
    
    # Create and show the main window
    app = None
    if not QtWidgets.QApplication.instance():
        app = QtWidgets.QApplication(sys.argv)
    
    # Scripts now use dual execution model based on run_on_main metadata
    
    # Use the centralized WindowManager to create the window
    window = WindowManager.create_window(
        host=detected_host,
        user=user_override,
        global_path=global_repo,
        dock=dock,
        show=True,
        xoffset=xoffset,
        yoffset=yoffset
    )

    # Apply startup mode preference
    try:
        startup_mode = user_settings_db.get_app_setting_for_host("startup_mode", detected_host)
        if startup_mode == "tiny" and hasattr(window, "enter_tiny_mode"):
            window.enter_tiny_mode()
    except Exception as exc:
        system_error(f"Failed to apply startup mode preference: {exc}")

    # If we created a new QApplication, run the event loop
    if app:
        sys.exit(app.exec_())

    return window

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Galt - Script Management Tool")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode for verbose output")
    parser.add_argument("--host", help="Override host detection")
    parser.add_argument("--user", help="Override username")
    parser.add_argument("--repository", help="Override global repository path")
    
    args = parser.parse_args()
    
    launch(
        host_override=args.host,
        user_override=args.user,
        global_path=args.repository,
        debug=args.debug
    )

