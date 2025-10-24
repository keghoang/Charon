from .qt_compat import QtCore, QtGui
from .metadata_manager import get_charon_config
from .utilities import is_compatible_with_host, apply_incompatible_opacity, get_software_color_for_metadata
from .cache_manager import get_cache_manager
from .charon_logger import system_debug
from .network_optimizer import get_batch_reader
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

class ScriptItem:
    def __init__(self, name, path, metadata=None, host="None"):
        self.name = name
        self.path = path  # full folder path for the script
        self.metadata = metadata  # dict or None
        self.host = host  # Store host for software selection
        self._has_readme = None  # Cache readme status

    def has_metadata(self):
        return self.metadata is not None
    
    def has_readme(self):
        """Check if the script folder contains a readme.md file"""
        # Use cached value if available
        if self._has_readme is not None:
            return self._has_readme
            
        # Otherwise check (this is slow on network drives)
        if not self.path:
            self._has_readme = False
            return False
            
        readme_path = os.path.join(self.path, "readme.md")
        # Also check for uppercase README.md
        readme_upper_path = os.path.join(self.path, "README.md")
        self._has_readme = os.path.exists(readme_path) or os.path.exists(readme_upper_path)
        return self._has_readme
    
    def clear_readme_cache(self):
        """Clear the cached readme status to force re-check"""
        self._has_readme = None

    def display_text(self):
        # Build prefix with bookmark and hotkey emojis
        prefix = ""
        
        # Add specific hotkey first if available (from HotkeyLoader)
        if hasattr(self, 'hotkey') and self.hotkey:
            prefix += f"[{self.hotkey}] "
        
        # Add bookmark emoji if bookmarked
        if getattr(self, 'is_bookmarked', False):
            prefix += "★ "
        
        # Add hotkey emoji if has hotkey
        if getattr(self, 'has_hotkey', False):
            prefix += "▶ "
        
        # Build the name with readme indicator
        name_part = self.name
        if self.has_readme():
            name_part += " [r]"
        
        return f"{prefix}{name_part}"


class BaseScriptLoader(QtCore.QThread):
    """Base class for script loaders to eliminate code duplication."""
    scripts_loaded = QtCore.Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._should_stop = False

    def stop_loading(self):
        """Signal the thread to stop loading"""
        self._should_stop = True
        if self.isRunning():
            self.wait(1000)  # Wait up to 1 second for thread to finish

    def _load_script_item(self, script_path, script_name, metadata):
        """Common method to create ScriptItem"""
        item = ScriptItem(script_name, script_path, metadata, self.host)
        return item


class GlobalIndexLoader(BaseScriptLoader):
    """Background thread to load the global script index without blocking the UI."""
    index_loaded = QtCore.Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.base_path = None
        # Be resource-aware: use a reasonable number of threads.
        self.max_workers = min(4, (os.cpu_count() or 1))

    def load_index(self, base_path):
        if self.isRunning():
            self.stop_loading()
        self.base_path = base_path
        self._should_stop = False
        self.start()

    def _scan_folder(self, folder_name, folder_path):
        """Scans a single folder and returns a list of script data tuples."""
        results = []
        if not os.path.isdir(folder_path):
            return results
        try:
            for script in os.listdir(folder_path):
                if self._should_stop:
                    break
                script_path = os.path.join(folder_path, script)
                if os.path.isdir(script_path):
                    display = f"{folder_name} > {script}"
                    metadata = get_charon_config(script_path)
                    results.append((display, script_path, metadata))
        except Exception as e:
            from .charon_logger import system_error
            system_error(f"Error scanning folder {folder_path}: {e}")
        return results

    def run(self):
        if not self.base_path or not os.path.exists(self.base_path):
            self.index_loaded.emit([])
            return

        all_results = []
        folders_to_scan = []

        try:
            for folder in os.listdir(self.base_path):
                if self._should_stop: return
                folders_to_scan.append((folder, os.path.join(self.base_path, folder)))

            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                future_to_folder = {executor.submit(self._scan_folder, name, path): name for name, path in folders_to_scan}
                
                for future in as_completed(future_to_folder):
                    if self._should_stop:
                        for f in future_to_folder: f.cancel()
                        return
                    
                    try:
                        folder_results = future.result()
                        if folder_results:
                            all_results.extend(folder_results)
                    except Exception as exc:
                        folder_name = future_to_folder[future]
                        from .charon_logger import system_error
                        system_error(f'Folder {folder_name} generated an exception: {exc}')

            if not self._should_stop:
                self.index_loaded.emit(all_results)
        except Exception as e:
            from .charon_logger import system_error
            system_error(f"Error preparing global index: {e}")
            if not self._should_stop:
                self.index_loaded.emit([])


class BookmarkLoader(BaseScriptLoader):
    """Background thread to load bookmarked scripts without blocking the UI"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.host = "None"
        self.base_path = None  # Add base path to filter bookmarks
    
    def load_bookmarks(self, host="None", base_path=None):
        """Start loading bookmarked scripts"""
        self.host = host
        self.base_path = base_path
        self._should_stop = False
        if not self.isRunning():
            self.start()
    
    def run(self):
        """Load bookmarked scripts in background thread"""
        try:
            from charon.settings import user_settings_db
            
            # Get bookmarked script paths
            bookmark_paths = user_settings_db.get_bookmarks()
            
            # Filter bookmarks to current base path and check existence
            valid_bookmarks = []
            for script_path in bookmark_paths:
                if self._should_stop:
                    return
                
                # Check if script still exists
                if os.path.exists(script_path):
                    # IMPORTANT: Only include bookmarks that are within the current base path
                    if self.base_path:
                        # Normalize both paths for comparison
                        normalized_script = os.path.normpath(script_path).lower()
                        normalized_base = os.path.normpath(self.base_path).lower()
                        if not normalized_script.startswith(normalized_base):
                            continue
                    valid_bookmarks.append(script_path)
            
            # Batch check for readme files
            readme_paths = {}
            for script_path in valid_bookmarks:
                script_name = os.path.basename(script_path)
                readme_paths[script_name] = (
                    os.path.join(script_path, "readme.md"),
                    os.path.join(script_path, "README.md")
                )
            
            # Check readme existence in parallel
            from concurrent.futures import ThreadPoolExecutor, as_completed
            scripts_with_readme = set()
            
            with ThreadPoolExecutor(max_workers=4) as executor:
                future_to_name = {}
                for name, (lower_path, upper_path) in readme_paths.items():
                    future = executor.submit(
                        lambda p1, p2: os.path.exists(p1) or os.path.exists(p2),
                        lower_path,
                        upper_path
                    )
                    future_to_name[future] = name
                
                for future in as_completed(future_to_name):
                    name = future_to_name[future]
                    if future.result():
                        scripts_with_readme.add(name)
            
            # Now load the scripts with pre-cached readme status
            items = []
            for script_path in valid_bookmarks:
                if self._should_stop:
                    return
                
                script_name = os.path.basename(script_path)
                # Load metadata in background thread
                metadata = get_charon_config(script_path)
                item = self._load_script_item(script_path, script_name, metadata)
                # Mark as bookmarked for proper sorting
                item.is_bookmarked = True
                
                # Pre-populate readme cache
                item._has_readme = script_name in scripts_with_readme
                
                items.append(item)
            
            if not self._should_stop:
                self.scripts_loaded.emit(items)
                
        except Exception as e:
            from .charon_logger import system_error
            system_error(f"Error loading bookmarks: {str(e)}")
            if not self._should_stop:
                self.scripts_loaded.emit([])



class FolderLoader(BaseScriptLoader):
    """Background thread to load scripts from a folder without blocking the UI"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.folder_path = None
        self.host = "None"
    
    def load_folder(self, folder_path, host="None"):
        """Start loading scripts from the given folder path"""
        self.folder_path = folder_path
        self.host = host
        self._should_stop = False
        if not self.isRunning():
            self.start()
    
    def run(self):
        """Load scripts in background thread with batch operations for network optimization"""
        if not self.folder_path or not os.path.exists(self.folder_path):
            self.scripts_loaded.emit([])
            return
        
        cache_manager = get_cache_manager()
        batch_reader = get_batch_reader()
        
        try:
            # Check cache first
            cached_contents = cache_manager.get_folder_contents(self.folder_path)
            
            if cached_contents:
                # Use cached folder contents
                script_paths = cached_contents
                system_debug(f"Using cached folder contents for {self.folder_path}")
            else:
                # First pass: collect all directories
                script_paths = []
                with os.scandir(self.folder_path) as entries:
                    for entry in entries:
                        if self._should_stop:
                            return
                        
                        if entry.is_dir() and not entry.name.startswith('.'):
                            script_paths.append((entry.path, entry.name))
                
                # Cache the folder contents
                cache_manager.cache_folder_contents(self.folder_path, script_paths)
            
            # Use batch operations for metadata and readme checks
            items = []
            
            if script_paths:
                # Check if we have cached batch metadata
                batch_metadata_key = f"batch_metadata:{self.folder_path}"
                cached_metadata = cache_manager.get_cached_data(batch_metadata_key)
                
                if cached_metadata:
                    # Use cached metadata
                    metadata_map = cached_metadata
                    system_debug(f"Using cached batch metadata for {self.folder_path}")
                else:
                    # Batch load all metadata at once
                    metadata_map = batch_reader.batch_read_metadata(self.folder_path)
                    # Cache it
                    cache_manager.cache_data(batch_metadata_key, metadata_map, ttl_seconds=600)
                
                # Check for cached readme data
                batch_readme_key = f"batch_readme:{self.folder_path}"
                cached_readme = cache_manager.get_cached_data(batch_readme_key)
                
                if cached_readme:
                    # Use cached readme data
                    readme_set = cached_readme
                    system_debug(f"Using cached batch readme data for {self.folder_path}")
                else:
                    # Batch check readme files
                    readme_set = batch_reader.batch_check_readmes(self.folder_path)
                    # Cache it
                    cache_manager.cache_data(batch_readme_key, readme_set, ttl_seconds=600)
                
                # Create script items
                for path, name in script_paths:
                    if self._should_stop:
                        return
                    
                    # Get metadata from batch results
                    metadata = metadata_map.get(name)
                    
                    # Create item
                    item = self._load_script_item(path, name, metadata)
                    
                    # Set readme flag from batch results (both True and False)
                    item._has_readme = (name in readme_set)
                    
                    items.append(item)
            
            if not self._should_stop:
                self.scripts_loaded.emit(items)
                
        except Exception as e:
            from .charon_logger import system_error
            system_error(f"Error loading folder {self.folder_path}: {str(e)}")
            if not self._should_stop:
                self.scripts_loaded.emit([])


class ScriptListModel(QtCore.QAbstractListModel):
    from .qt_compat import UserRole
    NameRole = UserRole + 1
    MetadataRole = UserRole + 2
    PathRole = UserRole + 3

    def __init__(self, parent=None):
        super(ScriptListModel, self).__init__(parent)
        self.scripts = []  # This is the list we want to access
        self.host = "None"  # Default host

    def rowCount(self, parent=QtCore.QModelIndex()):
        return len(self.scripts)

    def data(self, index, role):
        from .qt_compat import DisplayRole, ForegroundRole
        if not index.isValid():
            return None
        item = self.scripts[index.row()]
        if role == DisplayRole:
            return item.display_text()
        if role == ForegroundRole:
            # Get the base color using centralized utility
            base_color = get_software_color_for_metadata(item.metadata)
            
            # Check if script is compatible with current host
            is_compatible = is_compatible_with_host(item.metadata, self.host)
            
            if is_compatible:
                return QtGui.QBrush(QtGui.QColor(base_color))
            else:
                # Apply opacity to incompatible scripts while preserving base color
                color = QtGui.QColor(base_color)
                return QtGui.QBrush(apply_incompatible_opacity(color))
        if role == ScriptListModel.NameRole:
            return item.name
        if role == ScriptListModel.MetadataRole:
            return item.metadata
        if role == ScriptListModel.PathRole:
            return item.path
        return None

    def roleNames(self):
        roles = {
            ScriptListModel.NameRole: b"name",
            ScriptListModel.MetadataRole: b"metadata",
            ScriptListModel.PathRole: b"path"
        }
        return roles

    def updateItems(self, scripts):
        self.beginResetModel()
        self.scripts = scripts  # This updates the list
        self.endResetModel()

    def clear(self):
        self.beginResetModel()
        self.scripts = []
        self.endResetModel()
    
    def update_single_script(self, script_path: str) -> bool:
        """Update a single script in the model without full reload.
        
        Args:
            script_path: Path to the script to update
            
        Returns:
            True if script was found and updated, False otherwise
        """
        from .metadata_manager import get_charon_config
        
        # Find the script in our list
        for i, script in enumerate(self.scripts):
            if script.path == script_path:
                # Reload metadata from disk
                new_metadata = get_charon_config(script_path)
                
                # Update metadata
                script.metadata = new_metadata
                
                # Refresh hotkey data from database
                from .settings import user_settings_db
                hotkey = user_settings_db.get_hotkey_for_script(script_path, self.host)
                if hotkey:
                    script.has_hotkey = True
                    script.hotkey = hotkey
                else:
                    script.has_hotkey = False
                    script.hotkey = None
                
                # Preserve properties that shouldn't change with metadata
                old_is_bookmarked = getattr(script, 'is_bookmarked', False)
                old_has_readme = getattr(script, '_has_readme', None)
                
                script.is_bookmarked = old_is_bookmarked
                if old_has_readme is not None:
                    script._has_readme = old_has_readme
                
                # Emit dataChanged signal for this row
                idx = self.index(i)
                self.dataChanged.emit(idx, idx)
                
                return True
        
        return False
    
    def update_script_tags(self, script_path: str, new_tags: list) -> bool:
        """Update tags for a single script without reloading metadata.
        
        Args:
            script_path: Path to the script to update
            new_tags: New list of tags
            
        Returns:
            True if script was found and updated, False otherwise
        """
        # Find the script in our list
        for i, script in enumerate(self.scripts):
            if script.path == script_path:
                # Update just the tags
                if script.metadata:
                    script.metadata['tags'] = new_tags
                else:
                    script.metadata = {'tags': new_tags}
                
                # Emit dataChanged signal for this row
                idx = self.index(i)
                self.dataChanged.emit(idx, idx)
                
                return True
        
        return False

    def sortItems(self):
        from charon.utilities import create_script_sort_key
        self.scripts.sort(key=lambda i: create_script_sort_key(i, self.host))
        self.layoutChanged.emit()

    def set_host(self, host):
        """Set the host software and re-sort items if needed."""
        if self.host != host:
            self.host = host
            if self.scripts:  # Only sort if we have items
                self.sortItems()
                # Trigger visual refresh to update colors
                self.layoutChanged.emit()
