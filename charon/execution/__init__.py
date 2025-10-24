"""
Charon Script Execution Engine

This module provides a clean, dual-mode execution system that replaces
the complex Qt thread patching approach with a simple, reliable solution.

Execution Modes:
- MainThreadExecutor: For Qt/GUI scripts (run_on_main: true)
- BackgroundExecutor: For pure computation scripts (run_on_main: false)

Usage:
    from execution import ScriptExecutionEngine
    
    engine = ScriptExecutionEngine(host="maya")
    result = engine.execute_script(script_path)
"""

from .engine import ScriptExecutionEngine
from .main_thread_executor import MainThreadExecutor
from .background_executor import BackgroundExecutor
from .result import ExecutionResult, ExecutionStatus

__all__ = [
    'ScriptExecutionEngine',
    'MainThreadExecutor', 
    'BackgroundExecutor',
    'ExecutionResult',
    'ExecutionStatus'
]
