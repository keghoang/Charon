"""
Background Executor for Charon Script Engine

Executes scripts in worker threads for pure computation tasks.
Qt widgets CANNOT be created in this execution mode.
"""

import os
import sys
import time
import threading
import traceback
import queue
import contextlib
from typing import Optional, Dict, Any
from ..qt_compat import QtCore

from .result import ExecutionResult, ExecutionStatus
from .script_executors import ScriptExecutorRegistry
from ..charon_logger import system_info, system_debug, system_warning, system_error

# Import config for thread limits
try:
    from charon import config
except ImportError:
    # Fallback for CLI usage
    class FallbackConfig:
        MAX_BACKGROUND_THREADS = 4
        EXECUTION_OUTPUT_UPDATE_INTERVAL_MS = 50
        QT_WARNING_MESSAGE_TEMPLATE = """WARNING: {qt_import} detected in script.
Qt widgets cannot be created in background threads.
Set 'run_on_main: true' in .charon.json to use Qt widgets."""
    config = FallbackConfig()


class ThreadLocalStdout:
    """Thread-local stdout that routes to different outputs per thread"""
    def __init__(self):
        self._outputs = {}  # execution_id -> output_capture mapping
        self._lock = threading.Lock()
    
    def register_thread(self, execution_id, output_capture):
        """Register an output capture for the current thread"""
        thread_id = threading.current_thread().ident
        with self._lock:
            self._outputs[thread_id] = (execution_id, output_capture)
    
    def unregister_thread(self):
        """Unregister the current thread"""
        thread_id = threading.current_thread().ident
        with self._lock:
            self._outputs.pop(thread_id, None)
    
    def write(self, text):
        """Write to the appropriate output for the current thread"""
        thread_id = threading.current_thread().ident
        with self._lock:
            if thread_id in self._outputs:
                _, output_capture = self._outputs[thread_id]
                output_capture.write(text)
            else:
                # Fallback to original stdout if we have it
                if hasattr(BackgroundExecutor, '_original_stdout'):
                    BackgroundExecutor._original_stdout.write(text)
                else:
                    sys.__stdout__.write(text)
    
    def flush(self):
        pass


class ThreadOutputCapture:
    def __init__(self, execution_id: str, executor, original_stream, mirror_to_terminal: bool, buffer: list):
        self.execution_id = execution_id
        self.executor = executor
        self.buffer = buffer
        self.original_stream = original_stream
        self.mirror_to_terminal = mirror_to_terminal
        self._capturing = True
    
    def write(self, text: str):
        if self._capturing:
            # Always write to buffer for dialog
            self.buffer.append(text)
            # Queue output for processing on main thread
            self.executor._output_queue.put((self.execution_id, text))
        # Only write to original stream (terminal) if mirroring enabled
        if self.mirror_to_terminal:
            self.original_stream.write(text)
    
    def flush(self):
        if self.mirror_to_terminal:
            self.original_stream.flush()
    
    def stop_capture(self):
        self._capturing = False


class BackgroundExecutor(QtCore.QObject):
    """
    Executes scripts in background threads.
    
    This executor is designed for pure computation scripts that don't
    require Qt widgets. Any attempt to create Qt widgets will fail
    with a clear error message.
    """
    
    # Signals for execution events
    execution_started = QtCore.Signal(str, str)  # execution_id, script_path
    execution_completed = QtCore.Signal(str, ExecutionResult)  # execution_id, result
    execution_failed = QtCore.Signal(str, str)  # execution_id, error_message
    execution_cancelled = QtCore.Signal(str)  # execution_id
    progress_updated = QtCore.Signal(str, str)  # execution_id, progress_message
    output_updated = QtCore.Signal(str, str)  # execution_id, output_chunk

    # Lock to prevent race conditions during global stream patching
    _patch_lock = threading.Lock()
    
    def __init__(self, parent: Optional[QtCore.QObject] = None):
        super().__init__(parent)
        self._active_threads: Dict[str, threading.Thread] = {}
        self._cancellation_flags: Dict[str, threading.Event] = {}
        self._output_queue = queue.Queue()
        self._completion_queue = queue.Queue()
        
        # Thread limiting to prevent resource exhaustion
        self._thread_semaphore = threading.Semaphore(config.MAX_BACKGROUND_THREADS)
        self._pending_executions = queue.Queue()  # Queue for executions when limit reached
        
        # Timer to process output updates from background threads
        self._output_timer = QtCore.QTimer(self)
        self._output_timer.timeout.connect(self._process_queues)
        self._output_timer.start(config.EXECUTION_OUTPUT_UPDATE_INTERVAL_MS)
    
    def execute(self, execution_id: str, script_path: str, entry_file: str, 
                host: str = "nuke", mirror_prints: bool = True, 
                script_type: str = "python", thread_override_msg: str = "") -> None:
        """
        Execute a script in a background thread.
        
        Args:
            execution_id: Unique identifier for this execution
            script_path: Path to the script directory
            entry_file: Path to the entry file to execute
            host: Host environment name
            mirror_prints: Whether to mirror output to terminal (always captured in dialog)
            script_type: Type of script to execute (python, mel, etc.)
        """
        # Try to acquire semaphore (non-blocking)
        if self._thread_semaphore.acquire(blocking=False):
            # We got a thread slot, start execution immediately
            self._start_execution(execution_id, script_path, entry_file, host, mirror_prints, script_type, thread_override_msg)
        else:
            # Thread limit reached, provide user feedback
            system_debug("Maximum background threads reached, queuing execution...")
            
            # Create PENDING result and add directly to history
            pending_result = ExecutionResult(
                status=ExecutionStatus.PENDING,
                start_time=time.time(),
                execution_mode="background"
            )
            
            # Emit a special signal to add PENDING execution to history
            # We'll use progress_updated with a special message to trigger this
            self.progress_updated.emit(execution_id, f"PENDING_EXECUTION:{script_path}")
            
            # Queue the execution parameters
            execution_params = (execution_id, script_path, entry_file, host, mirror_prints, script_type, thread_override_msg)
            self._pending_executions.put(execution_params)
    
    def _start_execution(self, execution_id: str, script_path: str, entry_file: str, 
                        host: str, mirror_prints: bool, script_type: str = "python", thread_override_msg: str = "") -> None:
        """
        Start actual thread execution (internal helper).
        
        IMPORTANT: This method assumes the semaphore has already been acquired by the caller.
        The semaphore will be released in _emit_completion() when the thread finishes.
        """
        # Create cancellation flag for this execution
        cancellation_flag = threading.Event()
        self._cancellation_flags[execution_id] = cancellation_flag
        
        # Create and start background thread
        thread = threading.Thread(
            target=self._execute_in_thread,
            args=(execution_id, script_path, entry_file, host, cancellation_flag, mirror_prints, script_type, thread_override_msg),
            daemon=True
        )
        
        self._active_threads[execution_id] = thread
        
        # Emit started signal
        self.execution_started.emit(execution_id, script_path)
        
        # Start execution
        thread.start()
    
    def cancel_execution(self, execution_id: str) -> bool:
        """
        Cancel a running execution.
        
        Args:
            execution_id: ID of execution to cancel
            
        Returns:
            bool: True if cancellation was requested, False if execution not found
        """
        if execution_id in self._cancellation_flags:
            self._cancellation_flags[execution_id].set()
            return True
        return False
    
    def is_executing(self, execution_id: str) -> bool:
        """Check if a specific execution is running"""
        return (execution_id in self._active_threads and 
                self._active_threads[execution_id].is_alive())
    
    def _execute_in_thread(self, execution_id: str, script_path: str, 
                          entry_file: str, host: str, 
                          cancellation_flag: threading.Event,
                          mirror_prints: bool = True,
                          script_type: str = "python",
                          thread_override_msg: str = "") -> None:
        """Execute script in background thread with Qt widget detection"""
        start_time = time.time()
        
        # Check for cancellation before starting
        if cancellation_flag.is_set():
            result = ExecutionResult(
                status=ExecutionStatus.CANCELLED,
                start_time=start_time,
                execution_mode="background"
            )
            # Queue completion for processing on main thread instead of calling directly
            self._completion_queue.put((execution_id, result))
            return
        
        output_capture = None
        thread_local = threading.local()
        result = None  # Initialize result variable
        
        try:
            # Always create output capture for dialog
            output_buffer = []
            
            # Save original streams - use the saved Maya/Nuke redirected streams if available
            # This ensures mirroring works with Maya/Nuke script editors
            original_stdout = BackgroundExecutor._original_stdout if hasattr(BackgroundExecutor, '_original_stdout') else sys.stdout
            original_stderr = BackgroundExecutor._original_stderr if hasattr(BackgroundExecutor, '_original_stderr') else sys.stderr
            
            # Always set up output capture for dialog
            stdout_capture = ThreadOutputCapture(execution_id, self, original_stdout, mirror_prints, output_buffer)
            stderr_capture = ThreadOutputCapture(execution_id, self, original_stderr, mirror_prints, output_buffer)
            
            # Get or create the thread-local stdout (Atomically)
            with BackgroundExecutor._patch_lock:
                if not hasattr(BackgroundExecutor, '_thread_local_stdout'):
                    BackgroundExecutor._thread_local_stdout = ThreadLocalStdout()
                    # Only save the original streams if they haven't been redirected yet
                    # This prevents us from saving an already-redirected stream
                    if not isinstance(sys.stdout, ThreadLocalStdout):
                        BackgroundExecutor._original_stdout = sys.stdout
                        BackgroundExecutor._original_stderr = sys.stderr
                    sys.stdout = BackgroundExecutor._thread_local_stdout
                    sys.stderr = BackgroundExecutor._thread_local_stdout
            
            # Register this thread's output (use stdout_capture for both stdout and stderr)
            BackgroundExecutor._thread_local_stdout.register_thread(execution_id, stdout_capture)
            
            try:
                
                # Add script path to sys.path
                if script_path not in sys.path:
                    sys.path.insert(0, script_path)
                    path_added = True
                else:
                    path_added = False
                
                # Read the script
                with open(entry_file, 'r', encoding='utf-8') as f:
                    code = f.read()
                
                # Create execution namespace
                script_namespace = {
                    '__name__': '__main__',
                    '__file__': entry_file,
                    '__script_path__': script_path,
                    '__host__': host,
                    '__execution_mode__': 'background'
                }
                
                # Check for Qt imports and warn
                qt_imports = ['PySide2', 'PyQt5', 'PyQt6', 'PySide6']
                for qt_import in qt_imports:
                    if qt_import in code:
                        system_warning(config.QT_WARNING_MESSAGE_TEMPLATE.format(qt_import=qt_import))
                        break
                
                # Get the script executor for this script type
                executor = ScriptExecutorRegistry.get_executor_or_raise(script_type)
                
                # Validate script can run on this host
                is_valid, error_msg = executor.validate_for_host(host)
                if not is_valid:
                    raise RuntimeError(error_msg)
                
                # Prepare namespace if needed
                script_namespace = executor.prepare_namespace(script_namespace, host)
                
                # Execute the script using appropriate executor
                executor.execute(code, script_namespace, host)
                
                # Get final output - always available since we always capture
                combined_output = ''.join(output_buffer) if output_buffer else None
                
                # Create successful result
                result = ExecutionResult(
                    status=ExecutionStatus.COMPLETED,
                    start_time=start_time,
                    end_time=time.time(),
                    return_value=script_namespace.get('__return_value__'),
                    output=combined_output,
                    execution_mode="background"
                )
                
                # Successful execution - result will be queued after except block
                
            finally:
                # Stop capturing to prevent loops
                if 'stdout_capture' in locals():
                    stdout_capture.stop_capture()
                    if 'stderr_capture' in locals():
                        stderr_capture.stop_capture()
                
                # Unregister this thread's output
                if hasattr(BackgroundExecutor, '_thread_local_stdout'):
                    BackgroundExecutor._thread_local_stdout.unregister_thread()
                
                # Clean up sys.path
                if 'path_added' in locals() and path_added and script_path in sys.path:
                    sys.path.remove(script_path)
        
        except Exception as e:
            # Handle execution errors
            error_output = ''.join(output_buffer) if output_buffer else None
            full_traceback = traceback.format_exc()
            
            # Check for Qt-related errors and provide helpful messages
            error_msg = str(e)
            if self._is_qt_threading_error(error_msg, full_traceback):
                error_msg = self._format_qt_error_message(error_msg, full_traceback)
            
            result = ExecutionResult(
                status=ExecutionStatus.FAILED,
                start_time=start_time,
                end_time=time.time(),
                error_message=f"Background execution error: {error_msg}",
                output=error_output,
                execution_mode="background"
            )
        
        # Store result and let main thread check for completion
        if result:  # Only process if we have a result
            self._completed_executions = getattr(self, '_completed_executions', {})
            self._completed_executions[execution_id] = result
            
            # Queue completion for processing on main thread
            self._completion_queue.put((execution_id, result))
    
    def _is_qt_threading_error(self, error_msg: str, traceback_str: str) -> bool:
        """Check if error is related to Qt threading issues"""
        qt_error_indicators = [
            "QWidget",
            "QApplication", 
            "thread",
            "main thread",
            "QBackingStore::endPaint",
            "QPainter::begin",
            "wrapped C/C++ object",
            "has been deleted"
        ]
        
        combined_text = f"{error_msg} {traceback_str}".lower()
        return any(indicator.lower() in combined_text for indicator in qt_error_indicators)
    
    def _format_qt_error_message(self, error_msg: str, traceback_str: str) -> str:
        """Format Qt threading error with helpful guidance"""
        return f"""
Qt Threading Error: This script contains Qt widget code that cannot run in background threads.

SOLUTION: Update your script's .charon.json file:
{{
    "run_on_main": true,
    "software": ["Windows", "Maya"],
    "entry": "main.py"
}}

Qt widgets (QWidget, QPushButton, QDialog, etc.) must be created on the main GUI thread.
Background threads are designed for pure computation tasks only.

Original error: {error_msg}

Full traceback:
{traceback_str}
"""
    
    @QtCore.Slot(str, ExecutionResult)
    def _emit_completion(self, execution_id: str, result: ExecutionResult):
        """Thread-safe completion signal emission"""
        # Clean up tracking
        self._active_threads.pop(execution_id, None)
        self._cancellation_flags.pop(execution_id, None)
        
        # Release semaphore and process any pending executions
        self._thread_semaphore.release()
        self._process_pending_execution()
        
        # Emit appropriate signals
        if result.status == ExecutionStatus.COMPLETED:
            self.execution_completed.emit(execution_id, result)
        elif result.status == ExecutionStatus.FAILED:
            self.execution_failed.emit(execution_id, result.error_message or "Unknown error")
            self.execution_completed.emit(execution_id, result)  # Also emit for history
        elif result.status == ExecutionStatus.CANCELLED:
            self.execution_cancelled.emit(execution_id)
            self.execution_completed.emit(execution_id, result)  # Also emit for history
    
    def _process_pending_execution(self):
        """Process the next pending execution if any are queued"""
        try:
            # First check if we have pending executions
            execution_params = self._pending_executions.get_nowait()
            # Handle both old (6 params) and new (7 params) formats
            if len(execution_params) == 7:
                execution_id, script_path, entry_file, host, mirror_prints, script_type, thread_override_msg = execution_params
            else:
                execution_id, script_path, entry_file, host, mirror_prints, script_type = execution_params
                thread_override_msg = ""
            
            # Try to acquire semaphore (should succeed since we just released one in _emit_completion)
            if self._thread_semaphore.acquire(blocking=False):
                # Start the queued execution (semaphore is now properly acquired)
                self._start_execution(execution_id, script_path, entry_file, host, mirror_prints, script_type, thread_override_msg)
            else:
                # This shouldn't happen, but if semaphore is not available, put execution back in queue
                self._pending_executions.put(execution_params)
            
        except queue.Empty:
            # No pending executions, nothing to do
            pass
    
    @QtCore.Slot(str, str)
    def _emit_output_update(self, execution_id: str, output: str):
        """Thread-safe output update signal emission"""
        self.output_updated.emit(execution_id, output)
    
    def _process_queues(self):
        """Process queued output and completion updates from background threads"""
        # Process output queue - Batch updates to prevent UI freeze
        output_batches = {}

        try:
            # Process up to 1000 items per tick to prevent UI freeze
            for _ in range(1000):
                execution_id, output = self._output_queue.get_nowait()
                if execution_id not in output_batches:
                    output_batches[execution_id] = []
                output_batches[execution_id].append(output)
        except queue.Empty:
            pass

        # Emit combined updates
        for execution_id, chunks in output_batches.items():
            combined_output = "".join(chunks)
            self.output_updated.emit(execution_id, combined_output)
        
        # Process completion queue
        try:
            while True:
                # Get completion from queue (non-blocking)
                execution_id, result = self._completion_queue.get_nowait()
                self._emit_completion(execution_id, result)
        except queue.Empty:
            # No more items in completion queue
            pass
    
    def cleanup(self):
        """Stop the output timer and clean up resources"""
        if hasattr(self, '_output_timer'):
            self._output_timer.stop()
            self._output_timer.deleteLater()
        
        # Restore original stdout/stderr if we redirected them
        self.restore_original_streams()
    
    @classmethod
    def restore_original_streams(cls):
        """Restore the original stdout/stderr streams"""
        with cls._patch_lock:
            if hasattr(cls, '_original_stdout') and hasattr(cls, '_original_stderr'):
                sys.stdout = cls._original_stdout
                sys.stderr = cls._original_stderr
                # Clean up the attributes
                if hasattr(cls, '_thread_local_stdout'):
                    delattr(cls, '_thread_local_stdout')
                if hasattr(cls, '_original_stdout'):
                    delattr(cls, '_original_stdout')
                if hasattr(cls, '_original_stderr'):
                    delattr(cls, '_original_stderr')