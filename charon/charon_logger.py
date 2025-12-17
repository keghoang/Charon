"""
Charon Logging System

Provides clear separation between system messages and script output.
- System messages: Charon's own operational messages (go to terminal only)
- Script output: User script output (captured and sent to ExecutionDetailsDialog)
"""

import logging
import sys
from typing import Optional
import os

# Configure the system logger
_system_logger: Optional[logging.Logger] = None

# Import config if available
try:
    from . import config
except ImportError:
    pass


# No longer using colored formatter since Maya/Nuke don't support ANSI codes


def _get_system_logger() -> logging.Logger:
    """Get or create the system logger instance."""
    global _system_logger
    
    if _system_logger is None:
        # Create logger
        _system_logger = logging.getLogger('charon.system')
        _system_logger.setLevel(logging.DEBUG)
        
        # Remove any existing handlers
        _system_logger.handlers.clear()
        
        # Create console handler that outputs to stderr (to avoid mixing with script output)
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setLevel(logging.DEBUG)
        
        # Create formatter with clear prefix (no colors)
        formatter = logging.Formatter('[CHARON] %(levelname)s: %(message)s')
        console_handler.setFormatter(formatter)
        
        # Add handler to logger
        _system_logger.addHandler(console_handler)
        
        # Prevent propagation to root logger
        _system_logger.propagate = False
    
    return _system_logger


def system_info(message: str) -> None:
    """Log an informational system message (normal operation)."""
    _get_system_logger().info(message)


def system_debug(message: str) -> None:
    """Log a debug system message (only shown when DEBUG_MODE is True)."""
    config_module = None

    try:
        from charon import config as global_config  # type: ignore
        config_module = global_config
    except ImportError:
        try:
            from . import config as local_config  # type: ignore
            config_module = local_config
        except ImportError:
            config_module = None

    if config_module is None:
        # No configuration available; default to emitting for safety.
        _get_system_logger().debug(message)
        return

    if getattr(config_module, "DEBUG_MODE", False):
        _get_system_logger().debug(message)


def system_warning(message: str) -> None:
    """Log a warning system message."""
    _get_system_logger().warning(message)


def system_error(message: str) -> None:
    """Log an error system message."""
    _get_system_logger().error(message)


def system_critical(message: str) -> None:
    """Log a critical system message."""
    _get_system_logger().critical(message)


# Qt-specific message handler that uses our logging system
def qt_message_handler(msg_type, msg_context, msg_string):
    """Custom Qt message handler that routes through our logging system."""
    from .qt_compat import QtCore
    
    # Filter out the "event loop already running" warning unless in debug mode
    try:
        from charon import config
        if not config.DEBUG_MODE and "event loop is already running" in msg_string:
            return  # Suppress this message
    except ImportError:
        pass
    
    # Route Qt messages through our logging system
    if msg_type == QtCore.QtMsgType.QtDebugMsg:
        system_debug(f"Qt Debug: {msg_string}")
    elif msg_type == QtCore.QtMsgType.QtWarningMsg:
        system_warning(f"Qt Warning: {msg_string}")
    elif msg_type == QtCore.QtMsgType.QtCriticalMsg:
        system_error(f"Qt Critical: {msg_string}")
    elif msg_type == QtCore.QtMsgType.QtFatalMsg:
        system_critical(f"Qt Fatal: {msg_string}")
    elif msg_type == QtCore.QtMsgType.QtInfoMsg:
        system_info(f"Qt Info: {msg_string}")


# Convenience function for transitioning from print() statements
def print_to_terminal(message: str) -> None:
    """
    Direct print to terminal (for special cases like thread override messages).
    This bypasses the logging system and prints directly to stdout.
    """
    print(message, file=sys.stdout, flush=True)
