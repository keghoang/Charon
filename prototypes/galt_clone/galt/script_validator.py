"""
Central Script Validator

Single source of truth for all script validation logic.
Handles compatibility checking, entry file validation, and execution readiness.
"""

import os
import time
from typing import Dict, Any, Optional, Tuple
from .utilities import is_compatible_with_host
from .galt_logger import system_debug
from .cache_manager import get_cache_manager


class ScriptValidator:
    """Centralized script validation logic."""
    @staticmethod
    def _is_charon_metadata(metadata: Optional[Dict[str, Any]]) -> bool:
        """Return True if metadata represents a Charon workflow."""
        if not metadata:
            return False
        if metadata.get("charon_meta"):
            return True
        return bool(metadata.get("workflow_file"))
    
    @staticmethod
    def can_execute(script_path: str, metadata: Optional[Dict[str, Any]], host: str) -> Tuple[bool, str]:
        """
        Determine if a script can be executed.
        
        Returns:
            (can_execute, reason_if_not)
        """
        # Check path exists (use cached validation if available)
        if not script_path:
            return False, "No script path provided"
            
        # Check validation cache first for path existence
        cache_manager = get_cache_manager()
        cached_validation = cache_manager.get_script_validation(script_path)
        
        if cached_validation and 'path_exists' in cached_validation:
            if not cached_validation['path_exists']:
                return False, "Script path does not exist"
        else:
            # Not in cache, check and cache the result
            path_exists = os.path.exists(script_path)
            if cached_validation:
                cached_validation['path_exists'] = path_exists
                cache_manager.cache_script_validation(script_path, cached_validation)
            else:
                # Create minimal validation entry
                validation_data = {
                    'path_exists': path_exists,
                    'validation_time': time.time()
                }
                cache_manager.cache_script_validation(script_path, validation_data)
            
            if not path_exists:
                return False, "Script path does not exist"
        
        # Temporarily treat all workflows as runnable within the prototype while
        # Charon-centric execution semantics are defined.
        return True, ""
    
    @staticmethod
    def has_valid_entry(script_path: str, metadata: Optional[Dict[str, Any]]) -> Tuple[bool, Optional[str]]:
        """
        Check if script has a valid entry file (with caching).
        
        Returns:
            (has_valid_entry, entry_path)
        """
        cache_manager = get_cache_manager()
        if ScriptValidator._is_charon_metadata(metadata):
            validation_data = cache_manager.get_script_validation(script_path) or {}
            validation_data.update({
                'has_entry': True,
                'entry_path': None,
                'entry_size': 0,
                'path_exists': validation_data.get('path_exists', True),
                'validation_time': time.time()
            })
            cache_manager.cache_script_validation(script_path, validation_data)
            return True, None

        if not metadata:
            return True, None

        # Check cache first
        cached_validation = cache_manager.get_script_validation(script_path)
        
        if cached_validation and 'has_entry' in cached_validation:
            # Return cached result
            if cached_validation['has_entry']:
                return True, cached_validation.get('entry_path')
            else:
                return False, None
        
        # Not in cache, do the actual validation
        validation_data = {
            'has_entry': False,
            'entry_path': None,
            'entry_size': 0,
            'path_exists': True,  # If we're checking entries, the path must exist
            'validation_time': time.time()
        }
        
        # Treat Charon workflows as valid even without a Python entry point.
        if metadata.get("charon_meta"):
            validation_data['has_entry'] = True
            cache_manager.cache_script_validation(script_path, validation_data)
            return True, None

        # Check explicit entry in metadata
        entry = metadata.get("entry")
        if entry:
            entry_path = os.path.join(script_path, entry)
            if os.path.exists(entry_path):
                size = os.path.getsize(entry_path)
                if size > 0:
                    validation_data['has_entry'] = True
                    validation_data['entry_path'] = entry_path
                    validation_data['entry_size'] = size
                    cache_manager.cache_script_validation(script_path, validation_data)
                    return True, entry_path
        
        # Check common entry files if no explicit entry
        common_entries = ["main.py", "run.py", "script.py", "main.mel", "run.mel", "script.mel"]
        for candidate in common_entries:
            candidate_path = os.path.join(script_path, candidate)
            if os.path.exists(candidate_path):
                size = os.path.getsize(candidate_path)
                if size > 0:
                    validation_data['has_entry'] = True
                    validation_data['entry_path'] = candidate_path
                    validation_data['entry_size'] = size
                    cache_manager.cache_script_validation(script_path, validation_data)
                    return True, candidate_path
        
        # No valid entry found, cache the negative result
        cache_manager.cache_script_validation(script_path, validation_data)
        return False, None
    
    @staticmethod
    def is_compatible(metadata: Optional[Dict[str, Any]], host: str) -> bool:
        """Check if script is compatible with the current host."""
        if not metadata:
            return True
        return is_compatible_with_host(metadata, host)
    
    @staticmethod
    def get_visual_properties(script_path: str, metadata: Optional[Dict[str, Any]], 
                            host: str, is_bookmarked: bool = False) -> Dict[str, Any]:
        """
        Get all visual properties for a script in one call.
        
        Returns dict with:
            - color: The base color for the script
            - should_fade: Whether to apply incompatible opacity
            - is_selectable: Whether the item can be selected
            - can_run: Whether the item can be executed
            - tooltip_suffix: Additional tooltip info
        """
        from .utilities import get_software_color_for_metadata
        from . import config
        
        # Get base color
        color = get_software_color_for_metadata(metadata)
        
        # Check if script can run
        can_run, reason = ScriptValidator.can_execute(script_path, metadata, host)
        
        # Determine visual properties
        is_compatible = ScriptValidator.is_compatible(metadata, host)
        has_entry, _ = ScriptValidator.has_valid_entry(script_path, metadata)
        is_charon = ScriptValidator._is_charon_metadata(metadata)

        should_fade = False
        if metadata and not is_charon:
            should_fade = not (is_compatible and has_entry)

        return {
            "color": color,
            "should_fade": should_fade,
            "is_selectable": can_run,
            "can_run": can_run,
            "tooltip_suffix": f" ({reason})" if not can_run else "",
            "is_bookmarked": is_bookmarked,
            "is_compatible": is_compatible,
            "has_entry": has_entry,
            "is_charon": is_charon
        }
    
    @staticmethod
    def find_entry_file(script_path: str, metadata: Optional[Dict[str, Any]]) -> Optional[str]:
        """
        Find the entry file for a script.
        
        This is used by the execution engine.
        """
        has_entry, entry_path = ScriptValidator.has_valid_entry(script_path, metadata)
        return entry_path if has_entry else None
