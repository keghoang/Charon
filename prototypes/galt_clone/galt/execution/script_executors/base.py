"""
Base Script Executor Interface

This module defines the abstract base class that all script executors must implement.
A script executor is responsible for executing code of a specific type (Python, MEL, etc.)
within the appropriate host environment.

Example of creating a new script executor:

    from galt.execution.script_executors.base import ScriptExecutor
    
    class MyScriptExecutor(ScriptExecutor):
        def can_execute(self, script_type: str) -> bool:
            return script_type.lower() == "myscript"
        
        def execute(self, code: str, namespace: dict, host: str) -> Any:
            # Your execution logic here
            result = my_interpreter.run(code)
            return result
        
        def get_file_extensions(self) -> List[str]:
            return [".mys", ".myscript"]
        
        def validate_for_host(self, host: str) -> Tuple[bool, str]:
            if host.lower() in ["maya", "windows"]:
                return True, ""
            return False, "MyScript only runs in Maya or Windows"
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple


class ScriptExecutor(ABC):
    """
    Abstract base class for script executors.
    
    All script executors must implement this interface to integrate with Galt's
    execution framework. The executor is responsible for:
    
    1. Identifying which script types it can handle
    2. Executing the script code in the appropriate interpreter
    3. Providing file extension mappings
    4. Validating host compatibility
    """
    
    @abstractmethod
    def can_execute(self, script_type: str) -> bool:
        """
        Check if this executor can handle the given script type.
        
        Args:
            script_type: The script type from metadata (e.g., "python", "mel")
            
        Returns:
            True if this executor can handle the script type
        """
        pass
    
    @abstractmethod
    def execute(self, code: str, namespace: Dict[str, Any], host: str) -> Any:
        """
        Execute the script code.
        
        Args:
            code: The script source code to execute
            namespace: The namespace dictionary to execute in (contains __name__, __file__, etc.)
            host: The current host application (e.g., "maya", "nuke", "windows")
            
        Returns:
            The result of script execution (if any)
            
        Raises:
            Any exception raised by the script or interpreter
        """
        pass
    
    @abstractmethod
    def get_file_extensions(self) -> List[str]:
        """
        Get the file extensions this executor handles.
        
        Returns:
            List of file extensions including the dot (e.g., [".py", ".pyw"])
        """
        pass
    
    def validate_for_host(self, host: str) -> Tuple[bool, str]:
        """
        Validate if this script type can run on the given host.
        
        Override this method to provide host-specific validation.
        
        Args:
            host: The host application name
            
        Returns:
            Tuple of (is_valid, error_message)
            - is_valid: True if the script can run on this host
            - error_message: Human-readable error if not valid, empty string if valid
        """
        # Default implementation - all hosts are valid
        return True, ""
    
    def prepare_namespace(self, namespace: Dict[str, Any], host: str) -> Dict[str, Any]:
        """
        Prepare or modify the namespace before execution.
        
        Override this method to add script-type-specific globals or imports.
        
        Args:
            namespace: The base namespace dictionary
            host: The current host application
            
        Returns:
            The modified namespace (can be the same dict or a new one)
        """
        # Default implementation - return namespace unchanged
        return namespace
    
    def get_output_capture_enabled(self) -> bool:
        """
        Whether output capture should be enabled for this script type.
        
        Some script types may handle their own output differently.
        
        Returns:
            True if stdout/stderr should be captured (default)
        """
        return True