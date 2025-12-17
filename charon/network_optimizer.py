"""
Network Drive Optimization Utilities

Provides optimized file operations for network drives by batching operations
and minimizing individual file system calls.
"""

import os
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Tuple, Set, Optional
from .cache_manager import get_cache_manager
from .charon_logger import system_debug, system_error
from .metadata_manager import get_metadata_path


class NetworkBatchReader:
    """Batches file read operations to minimize network round-trips."""
    
    def __init__(self, max_workers: int = 8):
        self.max_workers = max_workers
        self.cache_manager = get_cache_manager()
    
    def batch_read_metadata(self, folder_path: str) -> Dict[str, dict]:
        """
        Read all metadata files in a folder in parallel.
        
        Returns:
            Dict mapping script_name -> metadata
        """
        cache_key = f"batch_metadata:{folder_path}"
        cached = self.cache_manager.get_cached_data(cache_key, max_age_seconds=300)
        if cached is not None:
            return cached
        
        metadata_map = {}
        
        try:
            # First, collect all potential metadata files
            metadata_files = []
            with os.scandir(folder_path) as entries:
                for entry in entries:
                    if entry.is_dir() and not entry.name.startswith('.'):
                        json_path = get_metadata_path(entry.path)
                        metadata_files.append((entry.name, json_path))
            
            # Read all metadata files in parallel
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                future_to_script = {
                    executor.submit(self._read_json_file, path): name
                    for name, path in metadata_files
                }
                
                for future in as_completed(future_to_script):
                    script_name = future_to_script[future]
                    try:
                        metadata = future.result()
                        if metadata is not None:
                            metadata_map[script_name] = metadata
                    except Exception as e:
                        system_error(f"Error reading metadata for {script_name}: {e}")
            
            # Cache the result
            self.cache_manager.cache_data(cache_key, metadata_map, ttl_seconds=300)
            return metadata_map
            
        except Exception as e:
            system_error(f"Error batch reading metadata from {folder_path}: {e}")
            return {}
    
    def _read_json_file(self, path: str) -> Optional[dict]:
        """Read a JSON file if it exists."""
        try:
            # Skip existence check - just try to open
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            return None
        except Exception as e:
            system_error(f"Error reading {path}: {e}")
            return None
    
    def batch_check_readmes(self, folder_path: str) -> Set[str]:
        """
        Check which scripts have readme files.
        
        Returns:
            Set of script names that have readme files
        """
        scripts_with_readme = set()
        
        try:
            # Check all potential readme locations in parallel
            readme_checks = []
            with os.scandir(folder_path) as entries:
                for entry in entries:
                    if entry.is_dir() and not entry.name.startswith('.'):
                        readme_checks.append((
                            entry.name,
                            os.path.join(entry.path, "readme.md"),
                            os.path.join(entry.path, "README.md")
                        ))
            
            # Check in parallel
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                future_to_script = {
                    executor.submit(self._check_readme_exists, lower, upper): name
                    for name, lower, upper in readme_checks
                }
                
                for future in as_completed(future_to_script):
                    script_name = future_to_script[future]
                    if future.result():
                        scripts_with_readme.add(script_name)
            
            return scripts_with_readme
            
        except Exception as e:
            system_error(f"Error batch checking readmes in {folder_path}: {e}")
            return set()
    
    def _check_readme_exists(self, path1: str, path2: str) -> bool:
        """Check if either readme path exists."""
        try:
            # Try opening instead of exists check
            try:
                with open(path1, 'r'):
                    return True
            except:
                pass
            
            try:
                with open(path2, 'r'):
                    return True
            except:
                pass
                
            return False
        except:
            return False
    
    def batch_check_compatibility(self, folder_path: str, host: str) -> Dict[str, bool]:
        """
        Check compatibility for all subfolders at once.
        
        Returns:
            Dict mapping folder_name -> is_compatible
        """
        cache_key = f"batch_compat:{folder_path}:{host}"
        cached = self.cache_manager.get_cached_data(cache_key, max_age_seconds=600)
        if cached is not None:
            return cached
        
        # Get all metadata first
        metadata_map = self.batch_read_metadata(folder_path)
        
        # Check compatibility for each
        compat_map = {}
        for folder_name in os.listdir(folder_path):
            if not folder_name.startswith('.'):
                folder_full_path = os.path.join(folder_path, folder_name)
                if os.path.isdir(folder_full_path):
                    # Check if any script in folder is compatible
                    is_compatible = False
                    for script_name, metadata in metadata_map.items():
                        if self._is_compatible(metadata, host):
                            is_compatible = True
                            break
                    compat_map[folder_name] = is_compatible
        
        # Cache result
        self.cache_manager.cache_data(cache_key, compat_map, ttl_seconds=600)
        return compat_map
    
    def _is_compatible(self, metadata: Optional[dict], host: str) -> bool:
        """Check if metadata indicates compatibility with host."""
        if not metadata:
            return True  # No metadata = compatible
        
        software = metadata.get("software", [])
        if not software:
            return True
        
        # Check if host matches any software
        for sw in software:
            if sw.lower() == host.lower():
                return True
        
        return False


# Global instance
_batch_reader: Optional[NetworkBatchReader] = None


def get_batch_reader() -> NetworkBatchReader:
    """Get the global batch reader instance."""
    global _batch_reader
    if _batch_reader is None:
        _batch_reader = NetworkBatchReader()
    return _batch_reader
