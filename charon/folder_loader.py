"""
Asynchronous Folder List Loader

Loads folder lists from directories without blocking the UI thread.
"""

from .qt_compat import QtCore, Signal
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from .cache_manager import get_cache_manager
from .charon_logger import system_debug, system_error, log_user_action_detail
import time


class FolderListLoader(QtCore.QThread):
    """Background thread to load folder lists without blocking the UI."""
    
    folders_loaded = Signal(list)  # List of folder names
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.base_path = None
        self.host = "Nuke"
        self.check_compatibility = False
        self._should_stop = False
        self.max_workers = min(4, os.cpu_count() or 1)
        
    def load_folders(self, base_path, host="None", check_compatibility=False):
        """Start loading folders from the given base path."""
        log_user_action_detail(
            "folder_load_start",
            base_path=base_path,
            host=host,
            check_compatibility=check_compatibility,
        )
        if self.isRunning():
            self.stop_loading()
            if self.isRunning():
                # Defer reload until the previous thread fully stops
                QtCore.QTimer.singleShot(
                    50, lambda bp=base_path, h=host, cc=check_compatibility: self.load_folders(bp, h, cc)
                )
                return
            
        self.base_path = base_path
        self.host = host or "Nuke"
        self.check_compatibility = False  # Compatibility checks removed
        self._should_stop = False
        self.start()

    def stop_loading(self):
        """Signal the thread to stop loading."""
        self._should_stop = True
        log_user_action_detail(
            "folder_load_stop_requested",
            base_path=self.base_path,
            host=self.host,
            running=self.isRunning(),
        )
        if self.isRunning():
            self.requestInterruption()
            self.quit()
            # Non-blocking wait to allow the event loop to continue
            self.wait(0)
            
    def run(self):
        """Load folders in background thread."""
        if not self.base_path or not os.path.exists(self.base_path):
            log_user_action_detail(
                "folder_load_missing_base",
                base_path=self.base_path,
                host=self.host,
            )
            self.folders_loaded.emit([])
            return
            
        cache_manager = get_cache_manager()
        start_time = time.perf_counter()
        
        try:
            # Check cache first for folder list
            cache_key = f"folders:{self.base_path}"
            cached_folders = cache_manager.get_cached_data(cache_key)
            
            if cached_folders is not None:
                system_debug(f"Using cached folder list for {self.base_path}")
                folders = cached_folders
                log_user_action_detail(
                    "folder_load_cache_hit",
                    base_path=self.base_path,
                    host=self.host,
                    count=len(folders),
                )
            else:
                # Scan directory for folders
                folders = []
                try:
                    with os.scandir(self.base_path) as entries:
                        for entry in entries:
                            if self._should_stop:
                                log_user_action_detail(
                                    "folder_load_cancelled_during_scan",
                                    base_path=self.base_path,
                                    host=self.host,
                                )
                                return
                                
                            if entry.is_dir() and not entry.name.startswith('.'):
                                folders.append(entry.name)
                                
                    # Cache the folder list
                    cache_manager.cache_data(cache_key, folders, ttl_seconds=300)  # 5 min cache
                    
                except Exception as e:
                    system_error(f"Error scanning folders in {self.base_path}: {e}")
                    self.folders_loaded.emit([])
                    return
                    
            # Sort folders alphabetically for now
            folders.sort()
            log_user_action_detail(
                "folder_load_scanned",
                base_path=self.base_path,
                host=self.host,
                count=len(folders),
                duration_ms=int((time.perf_counter() - start_time) * 1000),
            )
            
            # Emit folder list immediately so UI can update
            if not self._should_stop:
                self.folders_loaded.emit(folders)
                log_user_action_detail(
                    "folder_load_emitted",
                    base_path=self.base_path,
                    host=self.host,
                    count=len(folders),
                )
                
        except Exception as e:
            system_error(f"Error loading folders: {e}")
            if not self._should_stop:
                self.folders_loaded.emit([])
            log_user_action_detail(
                "folder_load_error",
                base_path=self.base_path,
                host=self.host,
                error=str(e),
            )


class FolderDataCache:
    """Simple cache for folder-related data with TTL support."""
    
    def __init__(self):
        self._cache = {}
        self._timestamps = {}
        
    def get(self, key, default=None):
        """Get cached value if not expired."""
        import time
        if key in self._cache:
            if time.time() - self._timestamps[key] < 300:  # 5 minute TTL
                return self._cache[key]
            else:
                # Expired
                del self._cache[key]
                del self._timestamps[key]
        return default
        
    def set(self, key, value):
        """Set cached value with current timestamp."""
        import time
        self._cache[key] = value
        self._timestamps[key] = time.time()
        
    def clear(self):
        """Clear all cached data."""
        self._cache.clear()
        self._timestamps.clear()
