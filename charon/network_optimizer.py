"""
Network Drive Optimization Utilities

Provides optimized file operations for network drives by batching operations
and minimizing individual file system calls.
"""

import os
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Optional
from .cache_manager import get_cache_manager
from .charon_logger import system_debug, system_error, log_user_action_detail
from .metadata_manager import get_metadata_path


class NetworkBatchReader:
    """Batches file read operations to minimize network round-trips."""
    
    def __init__(self, max_workers: int = 8):
        self.max_workers = max_workers
        self.cache_manager = get_cache_manager()
    
    def batch_read_metadata(self, folder_path: str, stop_callback=None) -> Dict[str, dict]:
        """
        Read all metadata files in a folder in parallel.
        
        Returns:
            Dict mapping script_name -> metadata
        """
        start_time = time.perf_counter()
        log_user_action_detail(
            "script_metadata_batch_start",
            folder_path=folder_path,
            max_workers=self.max_workers,
        )
        cache_key = f"batch_metadata:{folder_path}"
        cached = self.cache_manager.get_cached_data(cache_key, max_age_seconds=300)
        if cached is not None:
            log_user_action_detail(
                "script_metadata_batch_cache_hit",
                folder_path=folder_path,
                result_count=len(cached),
            )
            return cached
        
        metadata_map = {}
        
        try:
            # First, collect all potential metadata files
            metadata_files = []
            def _cancelled() -> bool:
                try:
                    return bool(stop_callback and stop_callback())
                except Exception:
                    return False

            with os.scandir(folder_path) as entries:
                for entry in entries:
                    if _cancelled():
                        log_user_action_detail(
                            "script_metadata_batch_cancelled_during_scan",
                            folder_path=folder_path,
                        )
                        return {}
                    if entry.is_dir() and not entry.name.startswith('.'):
                        json_path = get_metadata_path(entry.path)
                        metadata_files.append((entry.name, json_path))
            log_user_action_detail(
                "script_metadata_batch_scan_complete",
                folder_path=folder_path,
                candidate_count=len(metadata_files),
            )
            
            # Read all metadata files in parallel
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                future_to_script = {
                    executor.submit(self._read_json_file, path): name
                    for name, path in metadata_files
                }
                
                for future in as_completed(future_to_script):
                    if _cancelled():
                        for f in future_to_script:
                            f.cancel()
                        log_user_action_detail(
                            "script_metadata_batch_cancelled_during_read",
                            folder_path=folder_path,
                            processed=len(metadata_map),
                        )
                        return {}
                    script_name = future_to_script[future]
                    try:
                        metadata = future.result()
                        if metadata is not None:
                            metadata_map[script_name] = metadata
                    except Exception as e:
                        system_error(f"Error reading metadata for {script_name}: {e}")
                        log_user_action_detail(
                            "script_metadata_batch_error",
                            folder_path=folder_path,
                            script=script_name,
                            error=str(e),
                        )
            
            # Cache the result
            self.cache_manager.cache_data(cache_key, metadata_map, ttl_seconds=300)
            log_user_action_detail(
                "script_metadata_batch_complete",
                folder_path=folder_path,
                result_count=len(metadata_map),
                duration_ms=int((time.perf_counter() - start_time) * 1000),
            )
            return metadata_map
            
        except Exception as e:
            system_error(f"Error batch reading metadata from {folder_path}: {e}")
            log_user_action_detail(
                "script_metadata_batch_error",
                folder_path=folder_path,
                error=str(e),
            )
            return {}
        finally:
            if not metadata_map:
                log_user_action_detail(
                    "script_metadata_batch_complete",
                    folder_path=folder_path,
                    result_count=len(metadata_map),
                    duration_ms=int((time.perf_counter() - start_time) * 1000),
                )
    
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
    
# Global instance
_batch_reader: Optional[NetworkBatchReader] = None


def get_batch_reader() -> NetworkBatchReader:
    """Get the global batch reader instance."""
    global _batch_reader
    if _batch_reader is None:
        _batch_reader = NetworkBatchReader()
    return _batch_reader
