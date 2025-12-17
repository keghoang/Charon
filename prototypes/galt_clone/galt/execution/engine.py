"""
Galt Script Execution Engine

This is the main coordinator that replaces the complex qt_patcher.py approach
with a simple, reliable dual-mode execution system.
"""

import os
import sys
import uuid
import time
from typing import Optional, Dict, Any, List, Callable, Tuple
from ..qt_compat import QtCore

from .result import ExecutionResult, ExecutionStatus
from .main_thread_executor import MainThreadExecutor
from .background_executor import BackgroundExecutor
from ..galt_logger import system_info, system_debug, system_error, print_to_terminal

# Add parent directory to path for metadata_manager import
_parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)


class ScriptExecutionEngine(QtCore.QObject):
    """
    Clean, simple script execution engine.
    
    Replaces the complex threading and Qt patching with a straightforward
    dual-mode approach based on script metadata.
    
    Usage:
        engine = ScriptExecutionEngine(host="maya")
        
        # Execute script - mode determined by metadata
        engine.execute_script("/path/to/script")
        
        # Force specific mode
        engine.execute_script("/path/to/script", force_background=True)
    """
    
    # Signals for execution events
    execution_started = QtCore.Signal(str, str)  # execution_id, script_path
    execution_completed = QtCore.Signal(str, ExecutionResult)  # execution_id, result
    execution_failed = QtCore.Signal(str, str)  # execution_id, error_message
    execution_cancelled = QtCore.Signal(str)  # execution_id
    progress_updated = QtCore.Signal(str, str)  # execution_id, progress_message
    output_updated = QtCore.Signal(str, str)  # execution_id, output_chunk
    
    def __init__(self, host: str = "nuke", parent: Optional[QtCore.QObject] = None):
        super().__init__(parent)
        self.host = host
        
        # Create executors
        self.main_executor = MainThreadExecutor(parent=self)
        self.background_executor = BackgroundExecutor(parent=self)
        
        # Execution tracking
        self._execution_history: Dict[str, ExecutionResult] = {}
        self._active_executions: Dict[str, str] = {}  # execution_id -> mode
        self._thread_override_reason: Optional[str] = None  # Track why thread mode was overridden
        
        # Connect executor signals to our signals
        self._connect_executor_signals()
    
    def _connect_executor_signals(self):
        """Connect signals from both executors to our main signals"""
        # Main thread executor
        self.main_executor.execution_started.connect(self.execution_started)
        self.main_executor.execution_completed.connect(self._on_execution_completed)
        self.main_executor.execution_failed.connect(self.execution_failed)
        self.main_executor.execution_cancelled.connect(self.execution_cancelled)
        self.main_executor.progress_updated.connect(self.progress_updated)
        self.main_executor.output_updated.connect(self.output_updated)
        
        # Background executor
        self.background_executor.execution_started.connect(self.execution_started)
        self.background_executor.execution_completed.connect(self._on_execution_completed)
        self.background_executor.execution_failed.connect(self.execution_failed)
        self.background_executor.execution_cancelled.connect(self.execution_cancelled)
        self.background_executor.progress_updated.connect(self.progress_updated)
        self.background_executor.output_updated.connect(self.output_updated)
    
    def execute_script(self, script_path: str, entry_file: Optional[str] = None,
                      force_background: bool = False, force_main_thread: bool = False) -> str:
        """
        Execute a script using the appropriate execution mode.
        
        Args:
            script_path: Path to the script directory
            entry_file: Optional specific entry file to run
            force_background: Force background execution (overrides metadata)
            force_main_thread: Force main thread execution (overrides metadata)
            
        Returns:
            str: Execution ID for tracking this execution
            
        Raises:
            ValueError: If script path doesn't exist or no entry file found
            RuntimeError: If both force options are True
        """
        if force_background and force_main_thread:
            raise RuntimeError("Cannot force both background and main thread execution")
        
        # Validate script path
        if not os.path.exists(script_path):
            raise ValueError(f"Script path does not exist: {script_path}")
        
        # Find entry file if not specified
        if not entry_file:
            entry_file = self._find_entry_file(script_path)
            if not entry_file:
                raise ValueError("No valid entry file found")
        
        # Determine execution mode
        run_on_main = self._determine_execution_mode(
            script_path, force_background, force_main_thread, entry_file
        )
        
        # Load metadata with robust fallbacks
        metadata = {}  # Initialize metadata dict
        try:
            # Import utilities for metadata handling
            from ..utilities import get_metadata_with_fallbacks, detect_script_type_from_extension
            metadata = get_metadata_with_fallbacks(script_path, self.host)
            mirror_prints = metadata.get("mirror_prints", True)
            
            # Validate script type from entry file extension
            try:
                detected_script_type = detect_script_type_from_extension(entry_file)
                # Optionally override metadata script_type with detected type for consistency
                metadata["script_type"] = detected_script_type
            except ValueError as e:
                # Script type not recognized - prevent execution
                raise ValueError(f"Cannot execute script: {str(e)}")
                
        except ImportError:
            # Fallback for CLI usage without utilities import
            import json
            metadata_file = os.path.join(script_path, ".galt.json")
            if os.path.exists(metadata_file):
                with open(metadata_file, 'r') as f:
                    metadata = json.load(f)
                mirror_prints = metadata.get("mirror_prints", metadata.get("intercept_prints", True))
            else:
                metadata = {}
                mirror_prints = True
            
            # Simple script type detection for fallback
            if entry_file.endswith('.mel'):
                metadata["script_type"] = "mel"
            elif entry_file.endswith('.py'):
                metadata["script_type"] = "python"
            else:
                # Default to python if unknown
                metadata["script_type"] = "python"
        except Exception as e:
            # If metadata loading fails completely, use safe defaults
            metadata = {}
            mirror_prints = True
            
            # Simple script type detection for exception case
            if entry_file.endswith('.mel'):
                metadata["script_type"] = "mel"
            elif entry_file.endswith('.py'):
                metadata["script_type"] = "python"
            else:
                # Default to python if unknown
                metadata["script_type"] = "python"
        
        # Generate execution ID
        execution_id = str(uuid.uuid4())
        
        # Track execution mode
        mode = "main_thread" if run_on_main else "background"
        self._active_executions[execution_id] = mode
        
        # Log execution decision
        try:
            from galt import config
            debug_mode = config.DEBUG_MODE
        except ImportError:
            debug_mode = False
        
        # Check if thread mode was overridden
        thread_override_msg = None
        if hasattr(self, '_thread_override_reason') and self._thread_override_reason:
            thread_override_msg = f"Note: {self._thread_override_reason}"
            # Print to terminal immediately (not to execution dialog)
            system_info(thread_override_msg)
            # Clear the reason after using it
            self._thread_override_reason = None
        
        system_debug(f"Executing script: {os.path.basename(script_path)}")
        system_debug(f"Mode: {mode} ({'forced' if force_background or force_main_thread else 'from metadata'})")
        system_debug(f"Entry: {os.path.basename(entry_file)}")
        
        # Get script type from metadata
        script_type = metadata.get("script_type", "python")
        
        # Execute using appropriate executor
        if run_on_main:
            self.main_executor.execute(execution_id, script_path, entry_file, self.host, mirror_prints, script_type)
        else:
            self.background_executor.execute(execution_id, script_path, entry_file, self.host, mirror_prints, script_type)
        
        return execution_id
    
    def _check_thread_compatibility(self, script_path: str, entry_file: str, 
                                   metadata: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Check if a script can run in a background thread.
        
        This centralizes all thread compatibility rules for maintainability.
        
        Args:
            script_path: Path to the script directory
            entry_file: The entry file to execute
            metadata: Script metadata dictionary
            
        Returns:
            Tuple of (can_run_in_background, reason_if_not)
        """
        script_type = metadata.get("script_type", "python").lower()
        
        # Rule 1: MEL scripts MUST run on main thread in Maya
        if script_type == "mel" and self.host.lower() == "maya":
            return (False, "MEL scripts are not thread-safe and must run on main thread")
        
        # Also check file extension as fallback
        if entry_file and entry_file.lower().endswith('.mel') and self.host.lower() == "maya":
            return (False, "MEL scripts are not thread-safe and must run on main thread")
        
        # Rule 2: Qt/GUI scripts should run on main thread
        # Check if script imports Qt libraries
        if entry_file and os.path.exists(entry_file):
            try:
                with open(entry_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    qt_imports = ['PySide2', 'PyQt5', 'PyQt6', 'PySide6', 'QtWidgets', 'QtCore', 'QtGui']
                    for qt_import in qt_imports:
                        if qt_import in content:
                            return (False, f"Script imports {qt_import} - Qt widgets require main thread")
            except Exception:
                pass  # If we can't read the file, we'll let it proceed
        
        # Future rules can be added here:
        # Rule 3: MaxScript must run on main thread in 3ds Max
        # if script_type == "maxscript" and self.host.lower() == "3dsmax":
        #     return (False, "MaxScript must run on main thread")
        
        # Script can run in background
        return (True, None)
    
    def _determine_execution_mode(self, script_path: str, force_background: bool, 
                                 force_main_thread: bool, entry_file: str = None) -> bool:
        """
        Determine whether to run on main thread based on metadata and overrides.
        
        Returns:
            bool: True for main thread, False for background
        """
        if force_main_thread:
            return True
        
        # Load metadata with fallbacks
        try:
            from ..utilities import get_metadata_with_fallbacks
            metadata = get_metadata_with_fallbacks(script_path, self.host)
        except ImportError:
            # Fallback for CLI usage
            try:
                from ..charon_metadata import load_charon_metadata
                metadata = load_charon_metadata(script_path) or {}
            except Exception:
                metadata = {}
        except Exception:
            metadata = {}
        
        # Check what the user wants
        user_wants_main = metadata.get("run_on_main", True) if not force_background else False
        
        # If user already wants main thread, no need to check compatibility
        if user_wants_main and not force_background:
            return True
        
        # User wants background (either from metadata or force_background), check if that's safe
        can_run_in_background, reason = self._check_thread_compatibility(script_path, entry_file, metadata)
        
        # If script cannot run in background, force to main thread
        if not can_run_in_background:
            # Store the reason for later logging
            self._thread_override_reason = reason
            return True
        
        # Script can safely run in background as user requested
        return False
    
    def _find_entry_file(self, script_path: str) -> Optional[str]:
        """Find the entry file for a script using centralized validator."""
        from ..metadata_manager import get_galt_config
        from ..script_validator import ScriptValidator
        
        metadata = get_galt_config(script_path)
        return ScriptValidator.find_entry_file(script_path, metadata)
    
    def cancel_execution(self, execution_id: str) -> bool:
        """
        Cancel a running execution.
        
        Args:
            execution_id: ID of execution to cancel
            
        Returns:
            bool: True if cancellation was requested, False if execution not found
        """
        if execution_id not in self._active_executions:
            return False
        
        mode = self._active_executions[execution_id]
        
        if mode == "main_thread":
            return self.main_executor.cancel(execution_id)
        else:
            return self.background_executor.cancel_execution(execution_id)
    
    def is_executing(self, execution_id: str) -> bool:
        """Check if a specific execution is running"""
        if execution_id not in self._active_executions:
            return False
        
        mode = self._active_executions[execution_id]
        
        if mode == "main_thread":
            return self.main_executor.is_active(execution_id)
        else:
            return self.background_executor.is_executing(execution_id)
    
    def get_active_executions(self) -> List[str]:
        """Get list of currently active execution IDs"""
        return [eid for eid in self._active_executions.keys() 
                if self.is_executing(eid)]
    
    def get_execution_history(self) -> Dict[str, ExecutionResult]:
        """Get execution history"""
        return self._execution_history.copy()
    
    def clear_history(self):
        """Clear execution history"""
        self._execution_history.clear()
    
    @QtCore.Slot(str, ExecutionResult)
    def _on_execution_completed(self, execution_id: str, result: ExecutionResult):
        """Handle completion from either executor"""
        # Store in history
        self._execution_history[execution_id] = result
        
        # Clean up tracking
        self._active_executions.pop(execution_id, None)
        
        # Forward signal
        self.execution_completed.emit(execution_id, result)
    
    # Legacy compatibility methods for existing UI code
    def execute_script_legacy(self, script_path: str, entry_file: Optional[str] = None):
        """
        Legacy compatibility method for existing UI code.
        
        This maintains the interface expected by the current main_window.py
        while using the new execution system internally.
        """
        try:
            execution_id = self.execute_script(script_path, entry_file)
            return execution_id
        except (ValueError, RuntimeError) as e:
            # Emit failure signal for compatibility
            self.execution_failed.emit("legacy", str(e))
            return None
    
    def get_current_execution(self) -> Optional[str]:
        """Legacy method - get first active execution ID"""
        active = self.get_active_executions()
        return active[0] if active else None
