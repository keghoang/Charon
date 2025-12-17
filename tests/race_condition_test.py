import sys
import threading
import time
import os

# Ensure 'charon' package is importable
if os.path.basename(os.getcwd()) == "Charon":
    sys.path.insert(0, os.getcwd())
elif os.path.basename(os.getcwd()) == "charon":
    sys.path.insert(0, os.path.abspath(os.path.join(os.getcwd(), os.pardir)))

try:
    from charon.execution.background_executor import ThreadLocalStdout, ThreadOutputCapture, BackgroundExecutor
except ImportError as e:
    print(f"Error importing Charon modules: {e}")
    sys.exit(1)

def test_race_condition():
    print("Starting ThreadLocalStdout Race Condition Test...")
    
    # 1. Setup the shared stdout redirector
    thread_local = ThreadLocalStdout()
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    
    # CRITICAL FIX: Tell the executor where to send non-captured output (the Script Editor)
    BackgroundExecutor._original_stdout = original_stdout
    BackgroundExecutor._original_stderr = original_stderr
    
    # Hijack stdout
    sys.stdout = thread_local
    
    errors = []
    error_lock = threading.Lock()

    # Mock Executor
    class MockExecutor:
        def __init__(self):
            self._output_queue = type('Queue', (object,), {'put': lambda self, x: None})()

    mock_executor = MockExecutor()

    def worker(idx):
        try:
            my_buffer = []
            capture = ThreadOutputCapture(
                execution_id=f"exec_{idx}", 
                executor=mock_executor, 
                original_stream=original_stdout, 
                mirror_to_terminal=False, # Keep this False so we verify the CAPTURE logic separately
                buffer=my_buffer
            )
            
            # Atomic Registration
            thread_local.register_thread(f"exec_{idx}", capture)
            
            # Critical Section: This print() goes into 'my_buffer' via ThreadLocalStdout
            msg = f"Thread {idx} unique message"
            print(msg) 
            
            # Verification
            if not any(msg in line for line in my_buffer):
                with error_lock:
                    errors.append(f"Thread {idx} FAILED. Buffer content: {my_buffer}")
            
            # PROOF OF LIFE: Write directly to original stream so user sees activity
            # We use a lock to prevent the 'finished' messages from garbling each other
            with error_lock:
                 original_stdout.write(f"  [Proof] Thread {idx} executed and captured: '{msg}'\n")

            thread_local.unregister_thread()
            
        except Exception as e:
            with error_lock:
                errors.append(f"Thread {idx} CRASHED: {e}")

    # 5. Spawn threads
    print(f"Spawning 50 concurrent threads...")
    threads = []
    for i in range(50):
        t = threading.Thread(target=worker, args=(i,))
        threads.append(t)
        t.start()
        
    for t in threads:
        t.join()
        
    # Restore
    sys.stdout = original_stdout
    sys.stderr = original_stderr
    
    # Cleanup
    if hasattr(BackgroundExecutor, '_original_stdout'):
        del BackgroundExecutor._original_stdout
    if hasattr(BackgroundExecutor, '_original_stderr'):
        del BackgroundExecutor._original_stderr
    
    if errors:
        print(f"❌ TEST FAILED with {len(errors)} errors:")
        for e in errors[:10]:
            print(e)
    else:
        print("✅ TEST PASSED: No race conditions detected. All 50 threads captured their own output correctly.")

if __name__ == "__main__":
    test_race_condition()
