"""
Python Script Executor

Executes Python scripts using the built-in exec() function.
This executor handles all .py files and maintains the existing
execution behavior from the thread executors.
"""

import sys
from typing import Any, Dict, List, Tuple
from .base import ScriptExecutor


class PythonExecutor(ScriptExecutor):
    """
    Executor for Python scripts.
    
    This executor uses Python's built-in exec() function to run scripts
    in the provided namespace. It supports all Python features and
    maintains compatibility with existing Charon scripts.
    """
    
    def can_execute(self, script_type: str) -> bool:
        """Check if this is a Python script."""
        return script_type.lower() in ["python", "py"]
    
    def execute(self, code: str, namespace: Dict[str, Any], host: str) -> Any:
        """
        Execute Python code using exec().
        
        Args:
            code: Python source code
            namespace: Execution namespace with __name__, __file__, etc.
            host: Current host (maya, nuke, windows, etc.)
            
        Returns:
            The value of __return_value__ from namespace if set, otherwise None
        """
        # Execute the Python code in the provided namespace
        exec(code, namespace)
        
        # Return any value the script set in __return_value__
        return namespace.get('__return_value__')
    
    def get_file_extensions(self) -> List[str]:
        """Python file extensions."""
        return [".py", ".pyw"]
    
    def validate_for_host(self, host: str) -> Tuple[bool, str]:
        """Python can run on all hosts."""
        return True, ""
    
    def prepare_namespace(self, namespace: Dict[str, Any], host: str) -> Dict[str, Any]:
        """
        Prepare Python-specific namespace additions.
        
        For Python scripts, we ensure certain standard modules and
        variables are available.
        """
        # Ensure __builtins__ is available
        if '__builtins__' not in namespace:
            namespace['__builtins__'] = __builtins__
        
        # Add any Python-specific globals here if needed
        # The thread executors already handle most of this
        
        return namespace