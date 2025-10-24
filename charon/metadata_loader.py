"""
Optimized metadata loading utilities for batch operations.
"""

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Tuple, Optional
from .metadata_manager import get_charon_config
from .cache_manager import get_cache_manager
from .charon_logger import system_debug, system_error


def batch_load_metadata(script_paths: List[str], max_workers: int = 8) -> Dict[str, dict]:
    """
    Load metadata for multiple scripts in parallel.
    
    Args:
        script_paths: List of script directory paths
        max_workers: Maximum number of threads to use
        
    Returns:
        Dictionary mapping script_path -> metadata
    """
    results = {}
    cache_manager = get_cache_manager()
    
    # First check cache for all paths
    uncached_paths = []
    for path in script_paths:
        cache_key = f"metadata:{path}"
        cached_metadata = cache_manager.get_cached_data(cache_key, max_age_seconds=300)
        if cached_metadata is not None:
            results[path] = cached_metadata
        else:
            uncached_paths.append(path)
    
    if uncached_paths:
        system_debug(f"Batch loading {len(uncached_paths)} uncached metadata files")
        
        # Load uncached metadata in parallel
        with ThreadPoolExecutor(max_workers=min(max_workers, len(uncached_paths))) as executor:
            future_to_path = {
                executor.submit(get_charon_config, path): path
                for path in uncached_paths
            }
            
            for future in as_completed(future_to_path):
                path = future_to_path[future]
                try:
                    metadata = future.result()
                    results[path] = metadata
                    # Cache the result
                    cache_manager.cache_data(f"metadata:{path}", metadata, ttl_seconds=300)
                except Exception as e:
                    system_error(f"Error loading metadata for {path}: {e}")
                    results[path] = None
    
    return results


def preload_folder_metadata(folder_path: str, max_workers: int = 4) -> None:
    """
    Preload all metadata in a folder asynchronously.
    
    This is a fire-and-forget operation that warms up the cache.
    """
    def _preload():
        try:
            script_paths = []
            with os.scandir(folder_path) as entries:
                for entry in entries:
                    if entry.is_dir() and not entry.name.startswith('.'):
                        script_paths.append(entry.path)
            
            if script_paths:
                batch_load_metadata(script_paths, max_workers)
                system_debug(f"Preloaded metadata for {len(script_paths)} scripts in {folder_path}")
        except Exception as e:
            system_error(f"Error preloading metadata for {folder_path}: {e}")
    
    # Run in background thread
    from threading import Thread
    Thread(target=_preload, daemon=True).start()


def get_metadata_with_fallback(script_path: str, timeout: float = 0.1) -> Optional[dict]:
    """
    Try to get metadata quickly, falling back to None if it takes too long.
    
    Useful for UI operations where responsiveness is more important than
    having complete data immediately.
    """
    cache_manager = get_cache_manager()
    cache_key = f"metadata:{script_path}"
    
    # Check cache first
    cached = cache_manager.get_cached_data(cache_key, max_age_seconds=300)
    if cached is not None:
        return cached
    
    # Try to load with timeout
    from concurrent.futures import ThreadPoolExecutor, TimeoutError
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(get_charon_config, script_path)
        try:
            metadata = future.result(timeout=timeout)
            # Cache it
            cache_manager.cache_data(cache_key, metadata, ttl_seconds=300)
            return metadata
        except TimeoutError:
            # Return None and let it load in background
            return None
        except Exception as e:
            system_error(f"Error loading metadata for {script_path}: {e}")
            return None