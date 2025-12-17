import json
import os
import functools
from .utilities import is_compatible_with_host
from .charon_logger import system_error, system_warning
from .charon_metadata import load_charon_metadata, write_charon_metadata, CHARON_METADATA_FILENAME
from .conversion_cache import clear_conversion_cache
from .workflow_local_store import (
    get_local_workflow_folder,
    synchronize_remote_payload,
)


def get_metadata_path(script_path):
    """Return the path to the Charon metadata file for a script."""
    return os.path.join(script_path, CHARON_METADATA_FILENAME)


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
                metadata = get_charon_config(entry.path)
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
def get_charon_config(script_path):
    """
    Load Charon metadata for the given workflow directory.
    Returns None when no `.charon.json` file exists.
    """
    return load_charon_metadata(script_path)

def clear_metadata_cache():
    """Clear the entire metadata cache. Use when metadata has changed."""
    get_charon_config.cache_clear()

def invalidate_metadata_path(script_path):
    """Invalidate cache for a specific script path only."""
    # This is a workaround since lru_cache doesn't support selective invalidation
    # We'll clear the entire cache but this will be called less frequently
    # In the future, we could implement a custom cache with selective invalidation
    get_charon_config.cache_clear()
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
                    metadata = get_charon_config(entry.path)
                    if metadata:
                        tags = metadata.get('tags', [])
                        if isinstance(tags, list):
                            all_tags.update(tags)
    except Exception as e:
        system_error(f"Error getting folder tags for {folder_path}: {e}")
    
    return sorted(all_tags)

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
    
    # Force reload of metadata by calling get_charon_config
    # This will repopulate the cache with fresh data
    if target == "script" and script_path:
        # For a single script, we could invalidate just that path
        # but for now we'll just re-read it to warm the cache
        get_charon_config(script_path)
    elif target == "folder" and folder_path:
        # For folders, we don't need to clear cache anymore
        # The parallel loading will handle getting fresh data
        pass
    elif target == "all":
        # For "all", we already cleared the cache above
        pass

def update_charon_config(script_path, new_config):
    """Update Charon metadata on disk."""
    if not isinstance(new_config, dict):
        return False

    existing = load_charon_metadata(script_path) or {}
    payload = existing.get("charon_meta", {}).copy()

    incoming = new_config.get("charon_meta") or {}
    for key, value in incoming.items():
        if value is not None:
            payload[key] = value

    def _apply(key):
        if key in new_config and new_config[key] is not None:
            payload[key] = new_config[key]

    for key in ("workflow_file", "description", "last_changed"):
        _apply(key)

    if "dependencies" in new_config and new_config["dependencies"] is not None:
        payload["dependencies"] = new_config["dependencies"]
    if "tags" in new_config and new_config["tags"] is not None:
        payload["tags"] = new_config["tags"]
    if "parameters" in new_config and new_config["parameters"] is not None:
        payload["parameters"] = new_config["parameters"]

    if not payload.get("workflow_file"):
        payload["workflow_file"] = "workflow.json"

    print(f"[Charon] update_charon_config payload for {script_path}: {payload}")
    metadata = write_charon_metadata(script_path, payload)
    if metadata:
        print(f"[Charon] update_charon_config wrote metadata with parameters: {metadata.get('parameters')}")
        invalidate_metadata_path(script_path)
        try:
            clear_conversion_cache(script_path)
            print(f"[Charon] Cleared conversion cache for {script_path}")
        except Exception as cache_error:
            system_error(f"Failed to clear conversion cache for {script_path}: {cache_error}")
        return True
    print(f"[Charon] update_charon_config failed for {script_path}")
    return False


def load_workflow_data(script_path):
    """
    Load metadata and workflow payload for the given workflow directory.

    Returns a dictionary containing:
      - folder: absolute path to the workflow directory
      - workflow_file: filename declared in metadata (defaults to workflow.json)
      - workflow_path: resolved absolute path to the preferred workflow JSON (local copy)
      - source_workflow_path: path to the workflow JSON inside the shared repository
      - metadata: metadata dictionary (may be empty)
      - workflow: parsed JSON workflow payload
      - local_folder: per-user local mirror directory
      - local_state: cached local state information (validated flag, hashes, timestamps)
      - validated: boolean flag reflecting the local validated state
    """
    metadata = get_charon_config(script_path) or {}
    charon_meta = metadata.get("charon_meta") if isinstance(metadata, dict) else {}
    if not isinstance(charon_meta, dict):
        charon_meta = {}

    workflow_file = (
        charon_meta.get("workflow_file")
        or metadata.get("workflow_file")  # legacy field if present
        or "workflow.json"
    )
    workflow_path = os.path.join(script_path, workflow_file)

    try:
        with open(workflow_path, "r", encoding="utf-8") as handle:
            workflow_payload = json.load(handle)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Workflow file not found: {workflow_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Workflow JSON is invalid: {workflow_path}") from exc

    local_path, local_state = synchronize_remote_payload(
        script_path,
        workflow_payload,
        workflow_path=workflow_path,
    )
    local_folder = get_local_workflow_folder(script_path, ensure=True)
    preferred_path = local_state.get("local_path") or local_path
    validated_flag = bool(local_state.get("validated"))

    if validated_flag and preferred_path and os.path.exists(preferred_path):
        try:
            with open(preferred_path, "r", encoding="utf-8") as handle:
                workflow_payload = json.load(handle)
        except Exception as exc:
            system_warning(
                f"Failed to load validated workflow override for {script_path}: {exc}"
            )

    return {
        "folder": script_path,
        "workflow_file": workflow_file,
        "workflow_path": preferred_path,
        "source_workflow_path": workflow_path,
        "metadata": metadata,
        "workflow": workflow_payload,
        "local_folder": local_folder,
        "local_state": dict(local_state),
        "validated": validated_flag,
    }


