"""
Main Thread Executor for Galt Script Engine

Executes scripts on the main GUI thread for Qt/GUI scripts.
This is the safe execution mode for scripts that create Qt widgets.
"""

import os
import sys
import time
import traceback
from pathlib import Path
from typing import Optional, Dict, Any
from ..qt_compat import QtCore, QtWidgets

from .result import ExecutionResult, ExecutionStatus
from .script_executors import ScriptExecutorRegistry
from ..galt_logger import system_info, system_debug, system_warning, system_error, qt_message_handler

# Import config with fallback
try:
    from galt import config
except ImportError:
    # Fallback for CLI usage
    class FallbackConfig:
        MAIN_THREAD_TIMEOUT_MS = 30000
        DEBUG_MODE = False
    config = FallbackConfig()


# Import the qt_message_handler from galt_logger instead of defining it here


class MainThreadExecutor(QtCore.QObject):
    """
    Executes scripts on the main GUI thread.
    
    This executor is for scripts that create Qt widgets or otherwise
    need to run on the main thread. It ensures all Qt operations
    happen safely on the GUI thread.
    """
    
    # Signals for execution events (same as BackgroundExecutor for consistency)
    execution_started = QtCore.Signal(str, str)  # execution_id, script_path
    execution_completed = QtCore.Signal(str, ExecutionResult)  # execution_id, result
    execution_failed = QtCore.Signal(str, str)  # execution_id, error_message
    execution_cancelled = QtCore.Signal(str)  # execution_id
    progress_updated = QtCore.Signal(str, str)  # execution_id, progress_message
    output_updated = QtCore.Signal(str, str)  # execution_id, output_chunk
    
    def __init__(self, timeout_ms: Optional[int] = None, parent: Optional[QtCore.QObject] = None):
        super().__init__(parent)
        self.timeout_ms = timeout_ms if timeout_ms is not None else config.MAIN_THREAD_TIMEOUT_MS
        self._active_executions: Dict[str, bool] = {}
        self._thread_override_messages: Dict[str, str] = {}  # Store override messages by execution_id
        
    def execute(self, execution_id: str, script_path: str, entry_file: str, 
                host: str = "nuke", mirror_prints: bool = True, 
                script_type: str = "python", thread_override_msg: str = "") -> None:
        """
        Execute a script on the main GUI thread.
        
        Args:
            execution_id: Unique identifier for this execution
            script_path: Path to the script directory
            entry_file: Path to the entry file to execute
            host: Host environment name
            mirror_prints: Whether to mirror output to terminal (always captured in dialog)
            script_type: Type of script to execute (python, mel, etc.)
        """
        # Store thread override message if provided
        if thread_override_msg:
            self._thread_override_messages[execution_id] = thread_override_msg
        
        # Check if we're on the main thread
        if QtCore.QThread.currentThread() != QtWidgets.QApplication.instance().thread():
            # If not on main thread, schedule execution on main thread
            QtCore.QMetaObject.invokeMethod(
                self,
                "_execute_on_main_thread",
                QtCore.Qt.QueuedConnection,
                QtCore.Q_ARG(str, execution_id),
                QtCore.Q_ARG(str, script_path),
                QtCore.Q_ARG(str, entry_file),
                QtCore.Q_ARG(str, host),
                QtCore.Q_ARG(bool, mirror_prints),
                QtCore.Q_ARG(str, script_type)
            )
        else:
            # Already on main thread, execute directly
            self._execute_on_main_thread(execution_id, script_path, entry_file, host, mirror_prints, script_type)
    
    @QtCore.Slot(str, str, str, str, bool, str)
    def _execute_on_main_thread(self, execution_id: str, script_path: str, 
                               entry_file: str, host: str, mirror_prints: bool = True,
                               script_type: str = "python") -> None:
        """Execute script directly on main thread"""
        start_time = time.time()
        
        # Retrieve thread override message if stored
        thread_override_msg = self._thread_override_messages.pop(execution_id, "")
        
        # Install custom Qt message handler to filter unwanted warnings
        old_handler = QtCore.qInstallMessageHandler(qt_message_handler)
        
        # Track this execution
        self._active_executions[execution_id] = True
        
        # Emit started signal
        self.execution_started.emit(execution_id, script_path)
        
        try:
            # Set up timeout protection
            timeout_timer = QtCore.QTimer()
            timeout_timer.setSingleShot(True)
            timeout_occurred = [False]  # Use list to allow modification in closure
            
            def on_timeout():
                timeout_occurred[0] = True
                system_warning(f"Script execution timeout ({self.timeout_ms}ms) - stopping script")
            
            timeout_timer.timeout.connect(on_timeout)
            timeout_timer.start(self.timeout_ms)
            
            try:
                # Execute the script
                result = self._execute_script_sync(
                    execution_id, script_path, entry_file, host, 
                    start_time, timeout_occurred, mirror_prints, script_type, thread_override_msg
                )
            finally:
                timeout_timer.stop()
                timeout_timer.deleteLater()
            
            # Check if timeout occurred
            if timeout_occurred[0]:
                result = ExecutionResult(
                    status=ExecutionStatus.FAILED,
                    start_time=start_time,
                    end_time=time.time(),
                    error_message=f"Script execution timeout after {self.timeout_ms}ms",
                    output=result.output if 'result' in locals() and hasattr(result, 'output') else None,
                    execution_mode="main_thread"
                )
        
        except Exception as e:
            # Handle unexpected errors in the framework
            result = ExecutionResult(
                status=ExecutionStatus.FAILED,
                start_time=start_time,
                end_time=time.time(),
                error_message=f"Main thread execution framework error: {str(e)}\n{traceback.format_exc()}",
                execution_mode="main_thread"
            )
        
        finally:
            # Restore original Qt message handler
            QtCore.qInstallMessageHandler(old_handler)
            
            # Clean up tracking
            self._active_executions.pop(execution_id, None)
            self._thread_override_messages.pop(execution_id, None)  # Clean up any leftover message
        
        # Emit completion signals
        self._emit_completion(execution_id, result)
    
    def _execute_script_sync(self, execution_id: str, script_path: str, 
                            entry_file: str, host: str, start_time: float,
                            timeout_occurred: list, mirror_prints: bool = True,
                            script_type: str = "python", thread_override_msg: str = "") -> ExecutionResult:
        """Execute the actual script with output capture"""
        # Always capture for dialog, mirror_prints controls mirroring to terminal
        output_buffer = []
        
        class MainThreadOutputCapture:
            def __init__(self, execution_id: str, executor, original_stream, mirror_to_terminal: bool):
                self.execution_id = execution_id
                self.executor = executor
                self.buffer = output_buffer
                self.original_stream = original_stream
                self.mirror_to_terminal = mirror_to_terminal
            
            def write(self, text: str):
                # Always write to buffer for dialog
                self.buffer.append(text)
                # Emit output update immediately (already on main thread)
                self.executor.output_updated.emit(self.execution_id, text)
                # Only write to original stream (terminal) if mirroring enabled
                if self.mirror_to_terminal:
                    self.original_stream.write(text)
            
            def flush(self):
                if self.mirror_to_terminal:
                    self.original_stream.flush()
        
        # Always set up output capture for dialog
        original_stdout = sys.stdout
        original_stderr = sys.stderr
        
        # Create output capture (always for dialog, conditionally mirror to terminal)
        stdout_capture = MainThreadOutputCapture(execution_id, self, original_stdout, mirror_prints)
        stderr_capture = MainThreadOutputCapture(execution_id, self, original_stderr, mirror_prints)
        # Always redirect streams to our capture objects
        sys.stdout = stdout_capture
        sys.stderr = stderr_capture
        
        try:
            # Print thread override message if provided (after output capture is set up)
            if thread_override_msg and thread_override_msg.strip():  # Check for non-empty string
                print(thread_override_msg)
            
            # Add script path to sys.path
            if script_path not in sys.path:
                sys.path.insert(0, script_path)
                path_added = True
            else:
                path_added = False
            
            
            # Read the script
            with open(entry_file, 'r', encoding='utf-8') as f:
                code = f.read()
            
            # Create basic execution namespace
            script_namespace = {
                '__name__': '__main__',
                '__file__': entry_file,
                '__script_path__': script_path,
                '__host__': host,
                '__execution_mode__': 'main_thread'
            }
            # Inject shared globals
            try:
                from .injected_globals import collect_globals
                script_namespace.update(collect_globals(Path(script_path).name))
            except Exception as exc:
                system_warning(f"Failed to collect injected globals: {exc}")
            
            # Only apply Python-specific patches for Python scripts
            if script_type.lower() == "python":
                # Apply all the Python-specific patches
                script_namespace = self._apply_python_patches(script_namespace, mirror_prints, stdout_capture, stderr_capture)
            
            # Get the script executor for this script type
            executor = ScriptExecutorRegistry.get_executor_or_raise(script_type)
            
            # Validate script can run on this host
            is_valid, error_msg = executor.validate_for_host(host)
            if not is_valid:
                raise RuntimeError(error_msg)
            
            # Prepare namespace if needed
            script_namespace = executor.prepare_namespace(script_namespace, host)
            
            # Provide helpful information (only in debug mode)
            try:
                from galt import config
                system_debug(f"Executing {script_type} script on main GUI thread")
                system_debug(f"Host: {host}, Script: {os.path.basename(script_path)}")
            except ImportError:
                pass
            
            # Execute the script using appropriate executor
            try:
                executor.execute(code, script_namespace, host)
                
                # CRITICAL FIX: For redirected Qt scripts, ensure event loop runs
                # The script's app.exec_() might return immediately, so we need to
                # keep the event loop running to allow interaction
                if thread_override_msg and script_type.lower() == "python":
                    # Check if any Qt windows are visible
                    from ..qt_compat import QtWidgets
                    
                    # In Maya/Nuke, window detection is tricky because they have many windows
                    # Instead, we'll just ensure a minimum runtime for interaction
                    if host.lower() in ['maya', 'nuke']:
                        # Simple approach for Maya/Nuke: just wait a bit for interaction
                        # The script will complete when sys.exit() is called
                        for _ in range(20):  # 2 seconds total
                            QtWidgets.QApplication.processEvents()
                            time.sleep(0.1)
                    else:
                        # For standalone Windows, we can do proper window detection
                        start_wait = time.time()
                        min_wait = 2.0  # Minimum 2 seconds for interaction
                        max_wait = 30.0  # Maximum 30 seconds
                        
                        # Keep processing events while windows are visible
                        while time.time() - start_wait < max_wait:
                            QtWidgets.QApplication.processEvents()
                            
                            # Count visible windows (excluding Galt's own windows)
                            visible_windows = 0
                            for w in QtWidgets.QApplication.topLevelWidgets():
                                if w.isVisible() and hasattr(w, 'windowTitle'):
                                    title = w.windowTitle()
                                    if title and title not in ['Galt', 'Script Details', '', None]:
                                        visible_windows += 1
                            
                            # After minimum wait time, exit if no script windows
                            if time.time() - start_wait >= min_wait and visible_windows == 0:
                                break
                            
                            time.sleep(0.01)
                
            except SystemExit as e:
                # Handle sys.exit() calls from the script
                system_debug(f"Script exited with code: {e.code}")
                # Continue to create a successful result - script ran to completion
            
            # Get final output - always available since we always capture
            combined_output = ''.join(output_buffer) if output_buffer else None
            
            # IMPORTANT: If we have a thread override message, ensure it's in the final output
            # The message might have been emitted as a signal before the execution was registered
            # in the history panel, so it wouldn't be in live_output
            if thread_override_msg and thread_override_msg.strip():
                if combined_output and not combined_output.startswith(thread_override_msg):
                    # Thread message should be at the start if it's not already there
                    combined_output = thread_override_msg + '\n' + combined_output
                elif not combined_output:
                    # If no other output, at least include the thread message
                    combined_output = thread_override_msg + '\n'
            
            # Create successful result
            return ExecutionResult(
                status=ExecutionStatus.COMPLETED,
                start_time=start_time,
                end_time=time.time(),
                return_value=script_namespace.get('__return_value__'),
                output=combined_output,
                execution_mode="main_thread"
            )
            
        except Exception as e:
            # Handle script execution errors
            error_output = ''.join(output_buffer) if output_buffer else None
            full_traceback = traceback.format_exc()
            
            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                start_time=start_time,
                end_time=time.time(),
                error_message=f"Script execution error: {str(e)}\n{full_traceback}",
                output=error_output,
                execution_mode="main_thread"
            )
            
        finally:
            # Restore original stdout/stderr
            sys.stdout = original_stdout
            sys.stderr = original_stderr
            
            # Clean up sys.path
            if 'path_added' in locals() and path_added and script_path in sys.path:
                sys.path.remove(script_path)
            
            # For Python scripts, restore any module patches
            if script_type.lower() == "python":
                self._restore_python_patches()
    
    def _apply_python_patches(self, script_namespace: Dict[str, Any], mirror_prints: bool, stdout_capture, stderr_capture) -> Dict[str, Any]:
        """Apply Python-specific patches for Qt compatibility"""
        existing_app = QtWidgets.QApplication.instance()
        # Store reference to original QApplication class before any patching
        original_qapp_class = QtWidgets.QApplication
        
        class PatchedQApplicationMeta(type):
            """Metaclass to forward class-level attribute access"""
            def __getattr__(cls, name):
                # Special handling for exec_ to prevent event loop issues
                if name == 'exec_':
                    return lambda: 0
                # Forward other class method/attribute access to the original QApplication class
                return getattr(original_qapp_class, name)
        
        class PatchedQApplication(metaclass=PatchedQApplicationMeta):
            """Patched QApplication that returns existing instance"""
            def __new__(cls, *args, **kwargs):
                # Return existing QApplication instance instead of creating new one
                return existing_app
            
            def __init__(self, *args, **kwargs):
                # No-op, we're using existing instance
                pass
            
            @staticmethod
            def instance():
                return existing_app
            
            def exec_(self):
                # Run event loop to allow Qt script interaction
                # This is needed when scripts are redirected from background to main thread
                import time
                from ..qt_compat import QtWidgets
                
                # IMPORTANT: When redirected from background to main thread,
                # we need to ensure the script has time to be interactive.
                # The script may have created windows before calling exec_().
                
                start_time = time.time()
                timeout = 30  # 30 second safety timeout
                minimum_run_time = 2.0  # Minimum 2 seconds for interaction
                
                # Process events for at least minimum_run_time
                while time.time() - start_time < timeout:
                    QtWidgets.QApplication.processEvents()
                    
                    # Check for visible non-Galt windows
                    script_windows = []
                    for w in QtWidgets.QApplication.topLevelWidgets():
                        if w.isVisible() and hasattr(w, 'windowTitle'):
                            title = w.windowTitle()
                            # Exclude known Galt windows
                            if title not in ['Galt', 'Script Details', 'Execution Details', '', None]:
                                script_windows.append(w)
                    
                    # After minimum run time, exit if no script windows
                    if time.time() - start_time >= minimum_run_time:
                        if not script_windows:
                            break
                    
                    # Small delay to prevent CPU spinning
                    time.sleep(0.01)
                
                return 0
            
            @classmethod 
            def exec_class(cls):
                # Class method version - delegate to instance method
                app = QtWidgets.QApplication.instance()
                if app:
                    patched = PatchedQApplication()
                    return patched.exec_()
                return 0
            
            def quit(self):
                # Don't quit the main app from scripts
                system_debug("Script called QApplication.quit() - ignoring (use dialog close instead)")
                return
            
            @classmethod
            def quit_class(cls):
                system_debug("Script called QApplication.quit() - ignoring (use dialog close instead)")
                return
            
            def exit(self, retcode=0):
                # Don't exit the main app from scripts
                system_debug("Script called QApplication.exit() - ignoring (use dialog close instead)")
                return
            
            @classmethod
            def exit_class(cls, retcode=0):
                system_debug("Script called QApplication.exit() - ignoring (use dialog close instead)")
                return
            
            # Forward other attributes to the real app
            def __getattr__(self, name):
                return getattr(existing_app, name)
        
        # Create a custom sys module to intercept exit calls
        class ScriptSysModule:
            """Custom sys module that prevents script from exiting Galt"""
            def __init__(self, original_sys, mirror_prints):
                self._original = original_sys
            
            def exit(self, code=0):
                """Intercept sys.exit() to prevent closing Galt"""
                # Only print in debug mode
                try:
                    from galt import config
                    if config.DEBUG_MODE:
                        system_debug(f"Script called sys.exit({code}) - stopping script execution only")
                except ImportError:
                    pass
                # For Qt event handlers, we need to stop event propagation
                # Close any script windows but don't exit
                from ..qt_compat import QtWidgets
                # Close all windows except the main Galt window
                for widget in QtWidgets.QApplication.topLevelWidgets():
                    if widget.windowTitle() == "QuickQT":  # Script window
                        widget.close()
                # Don't raise SystemExit in event handlers as it may close Galt
            
            @property
            def stdout(self):
                """Always return the current sys.stdout (which should be our capture)"""
                import sys
                return sys.stdout
                
            @property  
            def stderr(self):
                """Always return the current sys.stderr (which should be our capture)"""
                import sys
                return sys.stderr
            
            def __getattr__(self, name):
                # Forward all other attributes to original sys
                return getattr(self._original, name)
        
        # Inject our custom sys module
        script_namespace['sys'] = ScriptSysModule(sys, mirror_prints)
        
        # Inject Qt patches into namespace
        script_namespace['QApplication'] = PatchedQApplication
        
        # Patch the import system to handle module-level QApplication creation
        # Handle both dict and module forms of __builtins__
        builtins_obj = __builtins__
        
        # CRITICAL: Override print to ensure Qt event handler output is captured
        # This is ALWAYS needed regardless of mirror_prints setting
        def captured_print(*args, **kwargs):
            """Custom print that ensures output goes to capture even in Qt event handlers"""
            import io
            buffer = io.StringIO()
            # Use file parameter to write to our buffer
            kwargs['file'] = buffer
            # Call original print with our buffer
            original_print(*args, **kwargs)
            # Explicitly write to our output capture
            output_capture = stdout_capture if 'stderr' not in kwargs else stderr_capture
            output_capture.write(buffer.getvalue())
        
        # Store original print for use in captured_print
        original_print = builtins_obj.get('print', print) if isinstance(builtins_obj, dict) else getattr(builtins_obj, 'print', print)
        
        # Override print in namespace - this is REQUIRED for Qt scripts
        script_namespace['print'] = captured_print
        if isinstance(builtins_obj, dict):
            original_import = builtins_obj['__import__']
        else:
            original_import = builtins_obj.__import__
        
        # Store for later restoration
        self._modules_to_restore = []
        self._original_import = original_import
        self._original_qapp_class = original_qapp_class
        self._builtins_obj = builtins_obj
        
        def patched_import(name, *args, **kwargs):
            """Custom import that patches sys and PySide2.QtWidgets"""
            # Intercept sys import to return our custom module
            if name == 'sys':
                return script_namespace['sys']
            
            module = original_import(name, *args, **kwargs)
            
            # If importing PySide2.QtWidgets, patch QApplication
            if name == 'PySide2.QtWidgets' or (name == 'PySide2' and args and 'QtWidgets' in args[0]):
                if hasattr(module, 'QtWidgets'):
                    # Patch PySide2.QtWidgets submodule
                    if not hasattr(module.QtWidgets.QApplication, '_galt_patched'):
                        module.QtWidgets.QApplication = PatchedQApplication
                        PatchedQApplication._galt_patched = True
                        self._modules_to_restore.append(('PySide2.QtWidgets.QApplication', original_qapp_class))
                elif hasattr(module, 'QApplication'):
                    # Direct QtWidgets module
                    if not hasattr(module.QApplication, '_galt_patched'):
                        module.QApplication = PatchedQApplication
                        PatchedQApplication._galt_patched = True
                        self._modules_to_restore.append((name + '.QApplication', original_qapp_class))
            
            return module
        
        # Replace import for script execution
        if isinstance(builtins_obj, dict):
            builtins_obj['__import__'] = patched_import
        else:
            builtins_obj.__import__ = patched_import
        
        # Store original sys module in custom sys for access
        script_namespace['sys']._original_sys = sys
        
        # Also patch the actual sys module temporarily
        self._sys_modules_backup = sys.modules.get('sys')
        sys.modules['sys'] = script_namespace['sys']
        
        # CRITICAL: Also patch already-imported PySide2.QtWidgets
        # The script might import QApplication before exec() is called
        if 'PySide2.QtWidgets' in sys.modules:
            qtwidgets = sys.modules['PySide2.QtWidgets']
            if hasattr(qtwidgets, 'QApplication') and qtwidgets.QApplication != PatchedQApplication:
                self._original_qapp_in_module = qtwidgets.QApplication
                qtwidgets.QApplication = PatchedQApplication
                self._modules_to_restore.append(('sys.modules.PySide2.QtWidgets.QApplication', self._original_qapp_in_module))
        
        return script_namespace
    
    def _restore_python_patches(self):
        """Restore any Python-specific patches"""
        # Restore import function
        if hasattr(self, '_builtins_obj') and hasattr(self, '_original_import'):
            if isinstance(self._builtins_obj, dict):
                self._builtins_obj['__import__'] = self._original_import
            else:
                self._builtins_obj.__import__ = self._original_import
        
        # Restore sys module
        if hasattr(self, '_sys_modules_backup'):
            sys.modules['sys'] = self._sys_modules_backup
        
        # Restore any patched modules
        if hasattr(self, '_modules_to_restore'):
            for module_path, original_class in self._modules_to_restore:
                parts = module_path.split('.')
                module = sys.modules.get(parts[0])
                if module:
                    for part in parts[1:-1]:
                        module = getattr(module, part, None)
                        if not module:
                            break
                    if module:
                        setattr(module, parts[-1], original_class)
    
    def cancel(self, execution_id: str) -> bool:
        """
        Cancel an execution.
        
        Main thread execution can't really be cancelled once started,
        but we track the attempt.
        
        Args:
            execution_id: The execution to cancel
            
        Returns:
            True if the execution was found (even if can't be stopped)
        """
        if execution_id in self._active_executions:
            # Can't really stop main thread execution, but we acknowledge the request
            self.execution_cancelled.emit(execution_id)
            return True
        return False
    
    def is_active(self, execution_id: str) -> bool:
        """Check if an execution is currently active"""
        return execution_id in self._active_executions
    
    def _emit_completion(self, execution_id: str, result: ExecutionResult) -> None:
        """Emit appropriate completion signal based on result status"""
        if result.status == ExecutionStatus.COMPLETED:
            self.execution_completed.emit(execution_id, result)
        elif result.status == ExecutionStatus.FAILED:
            # Also emit failed signal for better error handling
            self.execution_failed.emit(execution_id, result.error_message or "Unknown error")
            self.execution_completed.emit(execution_id, result)
        elif result.status == ExecutionStatus.CANCELLED:
            self.execution_cancelled.emit(execution_id)
            self.execution_completed.emit(execution_id, result)
