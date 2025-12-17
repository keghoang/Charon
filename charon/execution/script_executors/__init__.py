"""
Script Executors for Charon

This package provides a clean abstraction for executing different script types
(Python, MEL, JavaScript, etc.) within Charon's execution framework.

The script executor pattern separates the concerns of:
- Thread management (handled by MainThreadExecutor/BackgroundExecutor)
- Script execution (handled by script-specific executors)

This makes it easy to add new script types without modifying the threading logic.
"""

from .base import ScriptExecutor
from .python_executor import PythonExecutor
from .mel_executor import MELExecutor
from .registry import ScriptExecutorRegistry

__all__ = [
    'ScriptExecutor',
    'PythonExecutor',
    'MELExecutor',
    'ScriptExecutorRegistry'
]

# Auto-register built-in executors
ScriptExecutorRegistry.register("python", PythonExecutor())
ScriptExecutorRegistry.register("mel", MELExecutor())