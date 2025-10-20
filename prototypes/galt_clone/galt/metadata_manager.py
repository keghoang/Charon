import os, json
import sys
import functools
from galt import config
from .utilities import is_compatible_with_host
from .galt_logger import system_warning, system_error
from .charon_metadata import load_charon_metadata, write_charon_metadata, CHARON_METADATA_FILENAME

CHARON_METADATA_FILENAME = ".charon.json"
GALT_METADATA_FILENAME = ".galt.json"


def get_metadata_path(script_path):
    """
    Return the metadata path the loader should use. Prefers the new Charon
    metadata when available, falling back to legacy `.galt.json` files.
    """
    charon_path = os.path.join(script_path, CHARON_METADATA_FILENAME)
    if os.path.exists(charon_path):
        return charon_path
    return os.path.join(script_path, GALT_METADATA_FILENAME)

def _write_json_file(file_path, data):
    """
    Robust JSON file writer that handles Windows permission issues.
    
    Returns:
        bool: True if successful, False otherwise
    """
    # Ensure the directory exists
    dir_path = os.path.dirname(file_path)
    if not os.path.exists(dir_path):
        try:
            os.makedirs(dir_path)
        except Exception as e:
            system_error(f"Failed to create directory {dir_path}: {str(e)}")
            return False
    
    # Method 1: Direct write
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
        return True
    except PermissionError as e:
        # Method 2: Try to remove read-only attribute on Windows
        if sys.platform == 'win32' and os.path.exists(file_path):
            try:
                import stat
                # Get current file stats
                current_stat = os.stat(file_path)
                # Remove read-only flag if set
                if not (current_stat.st_mode & stat.S_IWRITE):
                    os.chmod(file_path, current_stat.st_mode | stat.S_IWRITE)
                
                # Try writing again
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=4)
                return True
            except Exception:
                pass
        
        # Method 3: Write to temp file and replace
        temp_path = file_path + '.tmp'
        try:
            # Write to temporary file
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
            
            # On Windows, we may need to remove the target file first
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except:
                    # If direct removal fails, try renaming to backup first
                    backup_path = file_path + '.bak'
                    if os.path.exists(backup_path):
                        os.remove(backup_path)
                    os.rename(file_path, backup_path)
                    try:
                        os.remove(backup_path)
                    except:
                        pass  # Ignore if we can't remove the backup
            
            # Rename temp file to final name
            os.rename(temp_path, file_path)
            return True
        except Exception as e2:
            # Clean up temp file if it exists
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except:
                    pass
            system_error(f"All write methods failed for {file_path}: Direct: {e}, Temp file: {e2}")
            return False
    except Exception as e:
        system_error(f"Unexpected error writing {file_path}: {e}")
        return False

def get_software_for_host(metadata, host="None"):
    """
    Get the appropriate software from metadata based on the current host.
    
    Args:
        metadata (dict): The metadata dictionary containing software list
        host (str): The current host software (e.g., "Maya", "Nuke", "Windows")
        
    Returns:
        str: The software to use. Prioritizes host software if it exists in the list,
             otherwise returns the first software in the list.
    """
    if not metadata or "software" not in metadata:
        return "None"
    
    software_list = metadata.get("software", ["None"])
    if not software_list:
        return "None"
    
    # If host is "None" or not specified, return the first software
    if host.lower() == "none":
        return software_list[0]
    
    # Check if the current host software exists in the list
    for software in software_list:
        if software.lower() == host.lower():
            return software
    
    # If host software not found, return the first software in the list
    return software_list[0]


def is_folder_compatible_with_host(folder_path, host="None", use_cache=True):
    """
    Check if a folder contains any scripts compatible with the current host.
    
    Args:
        folder_path (str): Path to the folder to check
        host (str): The current host software (e.g., "Maya", "Nuke", "Windows")
        use_cache (bool): Whether to use cached results
        
    Returns:
        bool: True if the folder contains at least one script compatible with the host,
              False otherwise
    """
    if not os.path.exists(folder_path) or not os.path.isdir(folder_path):
        return False
    
    # Check cache first
    if use_cache:
        from .cache_manager import get_cache_manager
        cache_manager = get_cache_manager()
        cache_key = f"folder_compat:{folder_path}:{host}"
        cached_result = cache_manager.get_cached_data(cache_key, max_age_seconds=600)  # 10 min cache
        if cached_result is not None:
            return cached_result
    
    try:
        # Check each subdirectory (script folder) in the given folder
        for entry in os.scandir(folder_path):
            if entry.is_dir() and not entry.name.startswith('.'):
                metadata = get_galt_config(entry.path)
                # Scripts without metadata or compatible with host are considered compatible
                if is_compatible_with_host(metadata, host):
                    # Cache positive result
                    if use_cache:
                        cache_manager.cache_data(cache_key, True, ttl_seconds=600)
                    return True
        
        # Cache negative result
        if use_cache:
            cache_manager.cache_data(cache_key, False, ttl_seconds=600)
        return False
    except Exception as e:
        system_error(f"Error checking folder compatibility for {folder_path}: {str(e)}")
        return False


def check_folder_compatibility_lazy(folder_path, host="None"):
    """
    Lazy version that returns True immediately and checks asynchronously.
    Used for initial display before real compatibility is known.
    """
    # For initial display, assume compatible
    # Real check will happen in background
    return True

@functools.lru_cache(maxsize=10000)
def get_galt_config(script_path):
    """
    Load metadata for the given workflow/script directory.
    Prefers `.charon.json`, but supports `.galt.json` for legacy content.
    """
    charon_meta = load_charon_metadata(script_path)
    if charon_meta is not None:
        return charon_meta

    meta_path = os.path.join(script_path, GALT_METADATA_FILENAME)
    if not os.path.exists(meta_path):
        if os.path.exists(os.path.join(script_path, "main.py")):
            # Create default metadata file
            return cleanUpMetadata(script_path)
        return None

    # File exists, load it without automatic cleanup
    try:
        with open(meta_path, 'r', encoding='utf-8') as f:
            metadata = json.load(f)
        return metadata if isinstance(metadata, dict) else None
    except (json.JSONDecodeError, IOError):
        # Only cleanup if file is corrupted
        return cleanUpMetadata(script_path)

def clear_metadata_cache():
    """Clear the entire metadata cache. Use when metadata has changed."""
    get_galt_config.cache_clear()

def invalidate_metadata_path(script_path):
    """Invalidate cache for a specific script path only."""
    # This is a workaround since lru_cache doesn't support selective invalidation
    # We'll clear the entire cache but this will be called less frequently
    # In the future, we could implement a custom cache with selective invalidation
    get_galt_config.cache_clear()
    # Also clear folder tags cache if it exists
    if hasattr(get_folder_tags, 'cache_clear'):
        get_folder_tags.cache_clear()
    
    # Also invalidate persistent cache
    try:
        from .cache_manager import get_cache_manager
        cache_manager = get_cache_manager()
        cache_manager.invalidate_script(script_path)
    except ImportError:
        pass  # Cache manager not available

@functools.lru_cache(maxsize=1000)
def get_folder_tags(folder_path):
    """
    Get all unique tags from all scripts in a folder.
    Cached to avoid re-scanning on every folder switch.
    
    Args:
        folder_path: Path to the folder to scan
        
    Returns:
        list: Sorted list of unique tags
    """
    all_tags = set()
    
    try:
        # Use the cached folder modification time to detect changes
        folder_mtime = os.path.getmtime(folder_path)
        
        with os.scandir(folder_path) as entries:
            for entry in entries:
                if entry.is_dir() and not entry.name.startswith('.'):
                    # Use the already cached metadata
                    metadata = get_galt_config(entry.path)
                    if metadata:
                        tags = metadata.get('tags', [])
                        if isinstance(tags, list):
                            all_tags.update(tags)
    except Exception as e:
        system_error(f"Error getting folder tags for {folder_path}: {e}")
    
    return sorted(all_tags)

def cleanUpMetadata(script_path):
    """
    Ensure metadata file has all required fields with correct defaults.
    This function is called whenever Galt touches a .galt.json file.
    
    Args:
        script_path (str): Path to the script folder
        
    Returns:
        dict: The cleaned up metadata
    """
    meta_path = get_metadata_path(script_path)

    if meta_path.endswith(CHARON_METADATA_FILENAME):
        metadata = load_charon_metadata(script_path)
        if metadata is None:
            metadata = write_charon_metadata(script_path)
            if metadata is None:
                system_warning(f"Could not initialize {meta_path}")
        if metadata:
            invalidate_metadata_path(script_path)
        return metadata
    
    # Start with default metadata
    metadata = config.DEFAULT_METADATA.copy()
    
    # If metadata file exists, load and merge it
    if os.path.exists(meta_path):
        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                existing_metadata = json.load(f)
            
            # Update defaults with existing values
            if isinstance(existing_metadata, dict):
                metadata.update(existing_metadata)
        except (json.JSONDecodeError, IOError):
            # If there's an error reading, we'll just use defaults
            pass
    
    # Handle backward compatibility: intercept_prints -> mirror_prints
    if "intercept_prints" in metadata and "mirror_prints" not in metadata:
        metadata["mirror_prints"] = metadata["intercept_prints"]
    
    # Clean up to current shape - only include supported fields
    cleaned_metadata = {
        "software": metadata.get("software", config.DEFAULT_METADATA["software"]),
        "entry": metadata.get("entry", config.DEFAULT_METADATA["entry"]),
        "script_type": metadata.get("script_type", config.DEFAULT_METADATA["script_type"]),
        "run_on_main": metadata.get("run_on_main", config.DEFAULT_METADATA["run_on_main"]),
        "mirror_prints": metadata.get("mirror_prints", config.DEFAULT_METADATA["mirror_prints"]),
        "tags": metadata.get("tags", config.DEFAULT_METADATA["tags"])
    }
    
    # Write back the cleaned metadata using robust method
    if not _write_json_file(meta_path, cleaned_metadata):
        system_warning(f"Could not write cleaned metadata to {meta_path}")
    
    # Only invalidate this specific path in the cache
    # For now this clears the entire cache, but it's called less frequently
    invalidate_metadata_path(script_path)
    
    return cleaned_metadata

def refresh_metadata(target="current", script_path=None, folder_path=None, clear_cache=True):
    """
    Centralized metadata refresh function.
    
    Args:
        target (str): "current", "script", "folder", "all"
        script_path (str): Specific script path to refresh (for target="script")
        folder_path (str): Specific folder path to refresh (for target="folder")
        clear_cache (bool): Whether to clear the LRU cache
    """
    # For performance: only clear cache when absolutely necessary
    # Most of the time we don't need to clear the entire cache
    if clear_cache and target == "all":
        clear_metadata_cache()
    
    # Force reload of metadata by calling get_galt_config
    # This will repopulate the cache with fresh data
    if target == "script" and script_path:
        # For a single script, we could invalidate just that path
        # but for now we'll just re-read it to warm the cache
        get_galt_config(script_path)
    elif target == "folder" and folder_path:
        # For folders, we don't need to clear cache anymore
        # The parallel loading will handle getting fresh data
        pass
    elif target == "all":
        # For "all", we already cleared the cache above
        pass

def create_default_galt_file(script_path, default_config=None):
    meta_path = get_metadata_path(script_path)
    if meta_path.endswith(CHARON_METADATA_FILENAME):
        metadata = write_charon_metadata(script_path)
        if metadata:
            invalidate_metadata_path(script_path)
            return True
        return False

    if default_config is None:
        default_config = config.DEFAULT_METADATA.copy()
    
    if _write_json_file(meta_path, default_config):
        # Only invalidate this specific path
        invalidate_metadata_path(script_path)
        return True
    return False

def update_galt_config(script_path, new_config):
    meta_path = get_metadata_path(script_path)

    if meta_path.endswith(CHARON_METADATA_FILENAME):
        data = None
        if isinstance(new_config, dict) and "workflow_file" in new_config:
            data = new_config
        metadata = write_charon_metadata(script_path, data)
        if metadata:
            invalidate_metadata_path(script_path)
            return True
        return False
    
    if _write_json_file(meta_path, new_config):
        # Only invalidate this specific path
        invalidate_metadata_path(script_path)
        return True
    return False
