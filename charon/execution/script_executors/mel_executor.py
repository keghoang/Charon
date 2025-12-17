"""
MEL Script Executor

Executes MEL (Maya Embedded Language) scripts within Maya.
MEL scripts can only run when the host is Maya.
"""

import sys
from typing import Any, Dict, List, Tuple
from .base import ScriptExecutor


class MELExecutor(ScriptExecutor):
    """
    Executor for MEL (Maya Embedded Language) scripts.
    
    This executor uses Maya's mel.eval() function to run MEL scripts.
    It only works when running inside Maya and will raise an error
    if attempted in other hosts.
    """
    
    def can_execute(self, script_type: str) -> bool:
        """Check if this is a MEL script."""
        return script_type.lower() == "mel"
    
    def execute(self, code: str, namespace: Dict[str, Any], host: str) -> Any:
        """
        Execute MEL code using maya.mel.eval().
        
        Args:
            code: MEL source code
            namespace: Execution namespace (less relevant for MEL)
            host: Current host (must be "maya" for MEL)
            
        Returns:
            The result of the MEL evaluation
            
        Raises:
            RuntimeError: If not running in Maya
            Any Maya MEL errors
        """
        # Validate we're in Maya
        if host.lower() != "maya":
            raise RuntimeError(
                f"MEL scripts can only be executed in Maya, not in {host}. "
                "Please run this script from within Maya."
            )
        
        try:
            import maya.mel as mel
        except ImportError:
            raise RuntimeError(
                "Maya Python modules not available. "
                "MEL scripts must be run from within Maya."
            )
        
        # MEL doesn't use Python namespaces, but we can set some Maya globals
        # that might be useful for the script
        
        # Store script path in Maya global variable if provided
        if '__script_path__' in namespace:
            mel.eval(f'string $charon_script_path = "{namespace["__script_path__"]}";')
        
        # Execute the MEL code
        # mel.eval returns the result of the last MEL command
        try:
            result = mel.eval(code)
            
            # If the script set a specific return variable, try to get it
            # MEL scripts might set: global string $charon_return_value
            try:
                # First check if the variable exists before trying to access it
                exists = mel.eval('exists "$charon_return_value"')
                if exists:
                    mel_return = mel.eval('$charon_return_value')
                    if mel_return:
                        result = mel_return
            except:
                # No return value set or error accessing it, use the eval result
                pass
            
            return result
            
        except Exception as e:
            # Enhance MEL error messages for clarity
            error_msg = str(e)
            if "Error:" in error_msg:
                # Maya MEL errors often have "Error:" prefix
                raise RuntimeError(f"MEL execution error: {error_msg}")
            else:
                raise
    
    def get_file_extensions(self) -> List[str]:
        """MEL file extension."""
        return [".mel"]
    
    def validate_for_host(self, host: str) -> Tuple[bool, str]:
        """MEL only runs in Maya."""
        if host.lower() == "maya":
            return True, ""
        else:
            return False, f"MEL scripts can only run in Maya, not in {host}"
    
    def prepare_namespace(self, namespace: Dict[str, Any], host: str) -> Dict[str, Any]:
        """
        MEL doesn't use Python namespaces, but we keep it for consistency.
        """
        # MEL scripts don't use the Python namespace
        # but we return it unchanged for consistency
        return namespace
    
    def get_output_capture_enabled(self) -> bool:
        """
        MEL output is captured through Maya's script editor output.
        """
        # MEL print statements go through Maya's output system
        # which should still be captured by our stdout redirection
        return True