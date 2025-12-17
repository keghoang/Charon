"""
Script Executor Registry

Central registry for managing script executors. This registry allows
dynamic registration of executors and provides a clean way to look up
the appropriate executor for a given script type.
"""

from typing import Dict, Optional, List, Tuple
from .base import ScriptExecutor


class ScriptExecutorRegistry:
    """
    Registry for script executors.
    
    This class maintains a mapping of script types to their executors
    and provides methods for registration and lookup.
    
    Example:
        # Register a custom executor
        from my_executors import JavaScriptExecutor
        ScriptExecutorRegistry.register("javascript", JavaScriptExecutor())
        
        # Get executor for a script type
        executor = ScriptExecutorRegistry.get_executor("javascript")
        result = executor.execute(code, namespace, host)
    """
    
    # Class-level storage for executors
    _executors: Dict[str, ScriptExecutor] = {}
    
    @classmethod
    def register(cls, script_type: str, executor: ScriptExecutor) -> None:
        """
        Register a script executor.
        
        Args:
            script_type: The script type identifier (e.g., "python", "mel")
            executor: The executor instance
            
        Raises:
            ValueError: If script_type is empty or executor is None
        """
        if not script_type:
            raise ValueError("Script type cannot be empty")
        
        if executor is None:
            raise ValueError("Executor cannot be None")
        
        # Normalize script type to lowercase for consistency
        script_type = script_type.lower()
        
        # Warn if overwriting an existing executor
        if script_type in cls._executors:
            print(f"Warning: Overwriting existing executor for script type '{script_type}'")
        
        cls._executors[script_type] = executor
    
    @classmethod
    def unregister(cls, script_type: str) -> bool:
        """
        Unregister a script executor.
        
        Args:
            script_type: The script type to unregister
            
        Returns:
            True if an executor was removed, False if not found
        """
        script_type = script_type.lower()
        if script_type in cls._executors:
            del cls._executors[script_type]
            return True
        return False
    
    @classmethod
    def get_executor(cls, script_type: str) -> Optional[ScriptExecutor]:
        """
        Get the executor for a script type.
        
        Args:
            script_type: The script type to look up
            
        Returns:
            The executor instance, or None if not found
        """
        return cls._executors.get(script_type.lower())
    
    @classmethod
    def get_executor_or_raise(cls, script_type: str) -> ScriptExecutor:
        """
        Get the executor for a script type, raising an error if not found.
        
        Args:
            script_type: The script type to look up
            
        Returns:
            The executor instance
            
        Raises:
            ValueError: If no executor is registered for the script type
        """
        executor = cls.get_executor(script_type)
        if executor is None:
            available = ", ".join(sorted(cls._executors.keys()))
            raise ValueError(
                f"No executor registered for script type '{script_type}'. "
                f"Available types: {available}"
            )
        return executor
    
    @classmethod
    def has_executor(cls, script_type: str) -> bool:
        """
        Check if an executor is registered for a script type.
        
        Args:
            script_type: The script type to check
            
        Returns:
            True if an executor is registered
        """
        return script_type.lower() in cls._executors
    
    @classmethod
    def get_registered_types(cls) -> List[str]:
        """
        Get all registered script types.
        
        Returns:
            List of registered script type names
        """
        return sorted(cls._executors.keys())
    
    @classmethod
    def get_all_file_extensions(cls) -> Dict[str, str]:
        """
        Get a mapping of all file extensions to script types.
        
        Returns:
            Dict mapping file extension to script type
            
        Example:
            {".py": "python", ".mel": "mel", ".js": "javascript"}
        """
        extensions = {}
        for script_type, executor in cls._executors.items():
            for ext in executor.get_file_extensions():
                extensions[ext] = script_type
        return extensions
    
    @classmethod
    def clear(cls) -> None:
        """
        Clear all registered executors.
        
        This is mainly useful for testing.
        """
        cls._executors.clear()
    
    @classmethod
    def validate_script_for_host(cls, script_type: str, host: str) -> Tuple[bool, str]:
        """
        Validate if a script type can run on a given host.
        
        Args:
            script_type: The script type to validate
            host: The host application
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        executor = cls.get_executor(script_type)
        if executor is None:
            return False, f"Unknown script type: {script_type}"
        
        return executor.validate_for_host(host)