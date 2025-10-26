"""
Persistent memory cache manager for Charon.
Manages in-memory caching of metadata, folder contents, and tags to minimize network reads.
"""

import os
import time
from typing import Dict, List, Optional, Set, Tuple, Any
from collections import OrderedDict
from threading import Lock, Thread
import queue
from concurrent.futures import ThreadPoolExecutor

from .metadata_manager import get_charon_config, get_folder_tags
from .charon_logger import system_debug, system_error, system_info
from . import config


class CacheEntry:
    """Single cache entry with timestamp and data."""
    def __init__(self, data: Any, timestamp: float = None):
        self.data = data
        self.timestamp = timestamp or time.time()
        
    def age(self) -> float:
        """Return age of entry in seconds."""
        return time.time() - self.timestamp


class PersistentCacheManager:
    """
    Manages persistent in-memory caching for Charon.
    
    Features:
    - Folder contents caching
    - Metadata caching (extends existing LRU cache)
    - Tag collection caching
    - Background pre-fetching
    - Hot cache for recently visited folders
    - Memory usage monitoring
    """
    
    def __init__(self, max_memory_mb: int = None):
        # Cache dictionaries
        self.folder_cache: Dict[str, CacheEntry] = {}  # folder_path -> list of (script_path, script_name)
        self.tag_cache: Dict[str, CacheEntry] = {}     # folder_path -> set of tags
        self.general_cache: Dict[str, CacheEntry] = {}  # general purpose cache with TTL
        self.validation_cache: Dict[str, CacheEntry] = {}  # script_path -> validation results
        
        # Hot cache - recently visited folders (LRU)
        self.hot_folders: OrderedDict[str, float] = OrderedDict()
        self.max_hot_folders = 20
        
        # Pre-fetch queue for background loading
        self.prefetch_queue: queue.Queue = queue.Queue()
        self.prefetch_executor = ThreadPoolExecutor(
            max_workers=config.CACHE_PREFETCH_THREADS, 
            thread_name_prefix="CachePrefetch"
        )
        self.prefetch_active = True
        
        # Track folders to prefetch
        self.folders_to_prefetch: List[str] = []
        self.prefetch_index = 0
        
        # Thread safety
        self.cache_lock = Lock()
        
        # Memory management
        self.max_memory_mb = max_memory_mb or config.CACHE_MAX_MEMORY_MB
        self.estimated_memory_usage = 0  # Rough estimate in bytes
        
        # Start background prefetch worker
        self._start_prefetch_worker()
        
    def _start_prefetch_worker(self):
        """Start background thread for pre-fetching."""
        def worker():
            while self.prefetch_active:
                try:
                    task = self.prefetch_queue.get(timeout=1)
                    if task is None:  # Shutdown signal
                        break
                    
                    task_type, *args = task
                    if task_type == "folder":
                        self._prefetch_folder(*args)
                    elif task_type == "all_folders":
                        self._prefetch_all_folders(*args)
                        
                except queue.Empty:
                    continue
                except Exception as e:
                    system_error(f"Prefetch worker error: {e}")
                    
        Thread(target=worker, name="CachePrefetchWorker", daemon=True).start()
        
    def shutdown(self):
        """Shutdown the cache manager and cleanup resources."""
        self.prefetch_active = False
        self.prefetch_queue.put(None)  # Shutdown signal
        self.prefetch_executor.shutdown(wait=True)
        
    def get_folder_contents(self, folder_path: str) -> Optional[List[Tuple[str, str]]]:
        """
        Get cached folder contents if available.
        Returns list of (script_path, script_name) tuples or None if not cached.
        """
        with self.cache_lock:
            if folder_path in self.folder_cache:
                entry = self.folder_cache[folder_path]
                # Update hot cache
                self._mark_hot(folder_path)
                system_debug(f"Cache hit for folder: {folder_path} (age: {entry.age():.1f}s)")
                return entry.data
        return None
        
    def cache_folder_contents(self, folder_path: str, contents: List[Tuple[str, str]]):
        """Cache folder contents."""
        with self.cache_lock:
            self.folder_cache[folder_path] = CacheEntry(contents)
            self._mark_hot(folder_path)
            self._estimate_memory_usage()
            
    def get_folder_tags(self, folder_path: str) -> Optional[Set[str]]:
        """Get cached folder tags if available."""
        with self.cache_lock:
            if folder_path in self.tag_cache:
                entry = self.tag_cache[folder_path]
                system_debug(f"Tag cache hit for folder: {folder_path}")
                return entry.data
        return None
        
    def cache_folder_tags(self, folder_path: str, tags: Set[str]):
        """Cache folder tags."""
        with self.cache_lock:
            self.tag_cache[folder_path] = CacheEntry(tags)
            self._estimate_memory_usage()
            
    def invalidate_folder(self, folder_path: str):
        """Invalidate all caches for a specific folder."""
        with self.cache_lock:
            if folder_path in self.folder_cache:
                del self.folder_cache[folder_path]
            if folder_path in self.tag_cache:
                del self.tag_cache[folder_path]
            if folder_path in self.hot_folders:
                del self.hot_folders[folder_path]
            
            # Also invalidate batch metadata cache
            batch_cache_key = f"batch_metadata:{folder_path}"
            if batch_cache_key in self.general_cache:
                del self.general_cache[batch_cache_key]
            
            # Invalidate validation cache for all scripts in this folder
            scripts_to_remove = [path for path in self.validation_cache.keys() 
                               if path.startswith(folder_path + os.sep)]
            for script_path in scripts_to_remove:
                del self.validation_cache[script_path]
                
    def invalidate_script(self, script_path: str):
        """Invalidate cache entries related to a specific script."""
        # When a script changes, invalidate its parent folder
        folder_path = os.path.dirname(script_path)
        self.invalidate_folder(folder_path)
        
    def queue_folder_prefetch(self, folder_path: str):
        """Queue a folder for background pre-fetching."""
        try:
            self.prefetch_queue.put_nowait(("folder", folder_path))
        except queue.Full:
            pass  # Skip if queue is full
            
    def queue_all_folders_prefetch(self, base_path: str, host: str = "None"):
        """Queue all folders for background pre-fetching in alphabetical order."""
        try:
            self.prefetch_queue.put_nowait(("all_folders", base_path, host))
        except queue.Full:
            pass
            
    def _prefetch_folder(self, folder_path: str):
        """Pre-fetch a folder's contents and expensive operations in background."""
        if not os.path.exists(folder_path):
            return
            
        # Check if already fully cached
        with self.cache_lock:
            if folder_path in self.folder_cache:
                # Already have folder contents, but check if we have metadata
                cache_key = f"batch_metadata:{folder_path}"
                if cache_key in self.general_cache:
                    return  # Already fully cached
                
        try:
            # Load folder contents
            contents = []
            with os.scandir(folder_path) as entries:
                for entry in entries:
                    if entry.is_dir() and not entry.name.startswith('.'):
                        contents.append((entry.path, entry.name))
                        
            # Cache the contents
            self.cache_folder_contents(folder_path, contents)
            
            # Now do the expensive operations - load metadata for all scripts
            if contents:
                from .network_optimizer import get_batch_reader
                batch_reader = get_batch_reader()
                
                # Batch load all metadata
                metadata_map = batch_reader.batch_read_metadata(folder_path)
                
                # Cache the batch metadata
                cache_key = f"batch_metadata:{folder_path}"
                self.cache_data(cache_key, metadata_map, ttl_seconds=600)  # 10 min cache
                
                # Collect and cache tags for the folder
                all_tags = set()
                for script_name, metadata in metadata_map.items():
                    if metadata and 'tags' in metadata:
                        all_tags.update(metadata['tags'])
                self.cache_folder_tags(folder_path, all_tags)
                
                # Pre-validate scripts and cache validation results
                from .script_validator import ScriptValidator
                for script_name, metadata in metadata_map.items():
                    script_path = os.path.join(folder_path, script_name)
                    # This will populate the validation cache
                    ScriptValidator.has_valid_entry(script_path, metadata)
                    
                    # Also check for custom icons and cache the result
                    validation_data = self.get_script_validation(script_path) or {}
                    if 'has_icon' not in validation_data:
                        # Check for icon files
                        has_icon = False
                        icon_path = None
                        for icon_name in ["icon.png", "icon.jpg"]:
                            test_path = os.path.join(script_path, icon_name)
                            if os.path.exists(test_path):
                                has_icon = True
                                icon_path = test_path
                                break
                        
                        validation_data['has_icon'] = has_icon
                        if has_icon:
                            validation_data['icon_path'] = icon_path
                        validation_data['validation_time'] = time.time()
                        
                        # Update cache
                        self.cache_script_validation(script_path, validation_data)
                
            system_debug(f"Pre-fetched folder with metadata: {folder_path}")
            
        except Exception as e:
            system_error(f"Error pre-fetching folder {folder_path}: {e}")
            
    def _prefetch_all_folders(self, base_path: str, host: str = "None"):
        """Pre-fetch all folders in alphabetical order."""
        if not os.path.exists(base_path):
            return
            
        try:
            # Get all folders
            all_folders = []
            with os.scandir(base_path) as entries:
                for entry in entries:
                    if entry.is_dir() and not entry.name.startswith('.'):
                        all_folders.append(entry.path)
            
            # Sort alphabetically
            all_folders.sort()
            
            system_debug(f"Starting prefetch of {len(all_folders)} folders")
            
            # Prefetch folder compatibility for all folders
            from .metadata_manager import is_folder_compatible_with_host
            
            # Process each folder
            for i, folder_path in enumerate(all_folders):
                if not self.prefetch_active:
                    break
                    
                # Check if already cached to skip
                with self.cache_lock:
                    cache_key = f"batch_metadata:{folder_path}"
                    if folder_path in self.folder_cache and cache_key in self.general_cache:
                        # Still check if we need to cache compatibility
                        folder_name = os.path.basename(folder_path)
                        compat_cache_key = f"compat:{base_path}:{folder_name}:{host}"
                        if compat_cache_key not in self.general_cache:
                            # Cache compatibility
                            is_compatible = is_folder_compatible_with_host(folder_path, host)
                            self.cache_data(compat_cache_key, is_compatible, ttl_seconds=600)
                        continue  # Folder contents already cached
                
                # Prefetch this folder
                self._prefetch_folder(folder_path)
                
                # Also cache folder compatibility
                folder_name = os.path.basename(folder_path)
                compat_cache_key = f"compat:{base_path}:{folder_name}:{host}"
                is_compatible = is_folder_compatible_with_host(folder_path, host)
                self.cache_data(compat_cache_key, is_compatible, ttl_seconds=600)
                
                # Log progress every 10 folders
                if (i + 1) % 10 == 0:
                    system_debug(f"Prefetched {i + 1}/{len(all_folders)} folders")
                    
            system_debug(f"Completed prefetching {len(all_folders)} folders")
            
        except Exception as e:
            system_error(f"Error in prefetch all folders: {e}")
            
    def _mark_hot(self, folder_path: str):
        """Mark a folder as recently accessed."""
        # Remove if already exists to move to end
        if folder_path in self.hot_folders:
            del self.hot_folders[folder_path]
            
        # Add to end (most recent)
        self.hot_folders[folder_path] = time.time()
        
        # Limit size
        while len(self.hot_folders) > self.max_hot_folders:
            self.hot_folders.popitem(last=False)  # Remove oldest
            
    def get_hot_folders(self) -> List[str]:
        """Get list of hot (recently accessed) folders."""
        with self.cache_lock:
            return list(self.hot_folders.keys())
            
    def _estimate_memory_usage(self):
        """Rough estimate of memory usage."""
        # Very rough estimates
        folder_size = len(self.folder_cache) * 1000  # ~1KB per folder entry
        tag_size = len(self.tag_cache) * 500  # ~500B per tag set
        validation_size = len(self.validation_cache) * 200  # ~200B per validation entry
        general_size = len(self.general_cache) * 500  # ~500B per general entry
        
        self.estimated_memory_usage = folder_size + tag_size + validation_size + general_size
        
        # If over limit, evict oldest entries
        if self.estimated_memory_usage > self.max_memory_mb * 1024 * 1024:
            self._evict_old_entries()
            
    def _evict_old_entries(self):
        """Evict oldest cache entries to free memory."""
        # Find oldest entries
        all_entries = []
        
        for path, entry in self.folder_cache.items():
            if path not in self.hot_folders:  # Don't evict hot folders
                all_entries.append((entry.timestamp, 'folder', path))
                
        for path, entry in self.tag_cache.items():
            all_entries.append((entry.timestamp, 'tag', path))
            
        for key, entry in self.general_cache.items():
            all_entries.append((entry.timestamp, 'general', key))
            
        # Sort by age (oldest first)
        all_entries.sort()
        
        # Evict oldest 20%
        evict_count = len(all_entries) // 5
        for _, cache_type, key in all_entries[:evict_count]:
            if cache_type == 'folder':
                del self.folder_cache[key]
            elif cache_type == 'tag':
                del self.tag_cache[key]
            else:
                del self.general_cache[key]
                
        system_debug(f"Evicted {evict_count} old cache entries")
        
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self.cache_lock:
            return {
                'folder_cache_size': len(self.folder_cache),
                'tag_cache_size': len(self.tag_cache),
                'validation_cache_size': len(self.validation_cache),
                'general_cache_size': len(self.general_cache),
                'hot_folders': len(self.hot_folders),
                'prefetch_queue_size': self.prefetch_queue.qsize(),
                'estimated_memory_mb': self.estimated_memory_usage / (1024 * 1024)
            }
    
    def cache_data(self, key: str, data: Any, ttl_seconds: int = 300):
        """
        Cache arbitrary data with a time-to-live.
        
        Args:
            key: Cache key
            data: Data to cache
            ttl_seconds: Time to live in seconds (default 5 minutes)
        """
        with self.cache_lock:
            self.general_cache[key] = CacheEntry(data)
            # Rough memory estimate
            self.estimated_memory_usage += len(str(data))

    def invalidate_cached_data(self, key: str):
        """Remove a general cache entry if present."""
        with self.cache_lock:
            if key in self.general_cache:
                del self.general_cache[key]
            
    def get_cached_data(self, key: str, max_age_seconds: int = None) -> Optional[Any]:
        """
        Get cached data if available and not expired.
        
        Args:
            key: Cache key
            max_age_seconds: Maximum age in seconds (overrides default TTL)
            
        Returns:
            Cached data or None if not found/expired
        """
        with self.cache_lock:
            if key in self.general_cache:
                entry = self.general_cache[key]
                # Check age if max_age specified
                if max_age_seconds is not None and entry.age() > max_age_seconds:
                    del self.general_cache[key]
                    return None
                return entry.data
        return None
    
    def get_script_validation(self, script_path: str) -> Optional[Dict[str, Any]]:
        """
        Get cached validation results for a script.
        
        Returns dict with:
            - has_entry: bool
            - entry_size: int
            - has_icon: bool
            - icon_path: str (if exists)
            - can_execute: bool
            - validation_time: float
        """
        with self.cache_lock:
            if script_path in self.validation_cache:
                entry = self.validation_cache[script_path]
                # Validation cache has longer TTL (10 minutes)
                if entry.age() < 600:
                    return entry.data
                else:
                    del self.validation_cache[script_path]
        return None
    
    def cache_script_validation(self, script_path: str, validation_data: Dict[str, Any]):
        """Cache validation results for a script."""
        with self.cache_lock:
            self.validation_cache[script_path] = CacheEntry(validation_data)
            self._estimate_memory_usage()
    
    def invalidate_script_validation(self, script_path: str):
        """Invalidate validation cache for a specific script."""
        with self.cache_lock:
            if script_path in self.validation_cache:
                del self.validation_cache[script_path]


# Global instance
_cache_manager: Optional[PersistentCacheManager] = None


def get_cache_manager() -> PersistentCacheManager:
    """Get the global cache manager instance."""
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = PersistentCacheManager()
    return _cache_manager


def shutdown_cache_manager():
    """Shutdown the global cache manager."""
    global _cache_manager
    if _cache_manager is not None:
        _cache_manager.shutdown()
        _cache_manager = None
