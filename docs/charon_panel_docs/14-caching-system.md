# Caching System

Charon implements a sophisticated persistent memory cache to minimize network reads and improve performance when browsing script repositories, especially on network drives.

## Overview

The caching system provides:
- In-memory caching of folder contents
- Tag computation caching
- Background pre-fetching of adjacent folders
- Hot folder tracking for optimization
- Automatic memory management with eviction

## Architecture

### PersistentCacheManager

Located in `charon/cache_manager.py`, this singleton class manages all caching:

```python
class PersistentCacheManager:
    def __init__(self):
        self.folder_cache = {}        # Folder contents cache
        self.tag_cache = {}           # Computed tags cache
        self.general_cache = {}       # General purpose cache with TTL
        self.validation_cache = {}    # Script validation results cache
        self.hot_folders = OrderedDict()  # Recently accessed folders (LRU)
        self.prefetch_executor = ThreadPoolExecutor(max_workers=2)
```

### Cache Types

1. **Folder Contents Cache**
   - Stores directory listings: `{folder_path: [(script_path, script_name), ...]}`
   - Eliminates repeated filesystem calls
   - Particularly beneficial for network drives

2. **Tag Cache**
   - Stores computed folder tags: `{folder_path: set(tags)}`
   - Avoids re-scanning metadata files
   - Updated when tags are modified

3. **General Cache**
   - General purpose cache with TTL (Time To Live)
   - Stores batch metadata: `"batch_metadata:{folder_path}"` â†’ metadata map
   - Stores batch readme checks: `"batch_readme:{folder_path}"` â†’ readme set
   - Default TTL: 600 seconds (10 minutes)

4. **Validation Cache**
   - Stores script validation results: `{script_path: validation_data}`
   - Includes entry file validation, icon presence checks, and the live state for the Validation Result dialog
   - Persists raw validation payloads and resolution events under %LOCALAPPDATA%/Charon/plugins/charon/Charon_repo_local/workflow/<user>/<workflow>/.charon_cache/validation/ (per artist)
     - `validation_result_raw.json` preserves the first ComfyUI payload and is never removed automatically
     - `validation_resolve_log.json` appends one entry per resolve action for auditability
   - Reduces repeated filesystem checks for script validity while keeping a canonical paper trail

5. **Workflow Input Cache**
   - Stores per-workflow parameter discovery results
   - Saved as `.charon_cache/input_mapping_cache.json` inside each workflow folder
   - Cache entries include the workflow file hash to guarantee freshness
   - Conversion prompts generated during API export also live in `.charon_cache`
   - Conversion cache cleanup preserves the validation subdirectory so raw payloads and resolve logs remain intact
   - Keeps metadata dialogs snappy on subsequent opens without re-running the scan
   - Local to each workflow folder so artists can diff/inspect if needed

6. **Hot Folders**
   - Tracks recently accessed folders using OrderedDict (LRU)
   - Maximum 20 hot folders maintained
   - Hot folders are protected from eviction

## Key Features

### 1. Background Pre-fetching

The cache system supports two prefetch strategies:

**Alphabetical Pre-fetching** (when `CACHE_PREFETCH_ALL_FOLDERS = True`):
- Loads ALL folders in the repository alphabetically
- Optimized for browsing entire repositories
- Includes batch loading of metadata, readme checks, and validation

**Single Folder Pre-fetching**:
- Loads complete folder data including:
  - Directory contents
  - All script metadata (batch loaded via `network_optimizer`)
  - README file presence checks
  - Tag aggregation
  - Script validation results
  - Custom icon detection

```python
def _prefetch_all_folders(self, base_path: str, host: str = "None"):
    """Pre-fetch all folders in alphabetical order."""
    # Get all folders and sort alphabetically
    all_folders = sorted([entry.path for entry in os.scandir(base_path) 
                         if entry.is_dir() and not entry.name.startswith('.')])
    
    # Process each folder with full metadata loading
    for folder_path in all_folders:
        self._prefetch_folder(folder_path)
```

### 2. Memory Management

- **Memory limit**: 500MB default (configurable)
- **Eviction strategy**: Least Recently Used (LRU)
- **Memory calculation**: Estimates based on data structures

```python
if self._estimate_memory_usage() > self.max_memory_bytes:
    self._evict_old_entries()
```

### 3. Cache Invalidation

Selective invalidation based on context:
- **Script refresh**: Invalidates single script
- **Folder refresh**: Invalidates folder and its contents
- **Global refresh**: Clears entire cache

```python
def invalidate_folder(self, folder_path):
    # Remove folder from all caches
    self.folder_cache.pop(folder_path, None)
    self.tag_cache.pop(folder_path, None)
    self.hot_folders.pop(folder_path, None)
    
    # Remove batch metadata and readme caches
    self.general_cache.pop(f"batch_metadata:{folder_path}", None)
    self.general_cache.pop(f"batch_readme:{folder_path}", None)
    
    # Invalidate validation cache for all scripts in folder
    scripts_to_remove = [path for path in self.validation_cache.keys() 
                        if path.startswith(folder_path + os.sep)]
    for script_path in scripts_to_remove:
        del self.validation_cache[script_path]
```

## Performance Benefits

### Network Drive Optimization
- First visit: Normal speed (network read)
- Subsequent visits: Near-instant (memory read)
- All folders pre-loaded alphabetically (when enabled)
- Batch operations minimize network round trips:
  - Single network read loads all metadata in a folder
  - README checks batched together
  - Validation results cached to avoid repeated checks

### Typical Performance Gains
- **Local drives**: 2-5x faster navigation
- **Network drives**: 10-50x faster navigation
- **Large repositories**: Scales well with thousands of scripts

## User Interface Integration

### Refresh Button Tooltip
Shows cache statistics:
```
"Refresh (Cache: 45 folders, 12 hot, 15.2 MB)"
```

### Loading Indicators
- Background pre-fetch doesn't block UI
- Status updates show cache hits vs network reads

## Configuration

In `config.py`:
```python
# Cache settings
CACHE_MAX_MEMORY_MB = 500          # Maximum memory usage in MB
CACHE_PREFETCH_THREADS = 2         # Background thread count for prefetching
CACHE_PREFETCH_ALL_FOLDERS = True  # If True, prefetch all folders alphabetically
```

Note: Hot folders are hardcoded to 20 maximum in the implementation.

## Cache Behavior

### When Cache is Used
1. **Folder navigation**: Directory listings
2. **Tag computation**: Folder tag aggregation
3. **Script filtering**: Tag-based filtering
4. **Search operations**: Quick lookups

### When Cache is Invalidated
1. **Manual refresh**: User clicks refresh button
2. **File modifications**: Detected changes
3. **Tag updates**: When tags are added/removed
4. **Memory pressure**: Automatic eviction

## Best Practices

### For Users
1. **Trust the cache**: Don't refresh unnecessarily
2. **Use hot folders**: Frequently accessed folders stay cached
3. **Monitor memory**: Check cache size in tooltip

### For Developers
1. **Cache early**: Pre-fetch during idle time
2. **Invalidate precisely**: Don't clear more than needed
3. **Profile performance**: Monitor cache hit rates

## Example: Cache Flow

```python
# User navigates to folder
def load_folder(folder_path):
    # Check cache first
    cached = cache_manager.get_folder_contents(folder_path)
    if cached:
        return cached  # Instant return
    
    # Load from filesystem
    contents = scan_folder(folder_path)
    
    # Cache for next time
    cache_manager.cache_folder_contents(folder_path, contents)
    
    # Pre-fetch siblings
    cache_manager.prefetch_adjacent(folder_path)
    
    return contents
```

## Debugging Cache Issues

### Enable Debug Logging
```python
# In charon_logger.py
DEBUG_MODE = True  # Shows cache hits/misses
```

### Cache Statistics
```python
stats = cache_manager.get_stats()
print(f"Folders cached: {stats['folder_cache_size']}")
print(f"Tags cached: {stats['tag_cache_size']}")
print(f"Validations cached: {stats['validation_cache_size']}")
print(f"General cache entries: {stats['general_cache_size']}")
print(f"Hot folders: {stats['hot_folders']}")
print(f"Memory used: {stats['estimated_memory_mb']} MB")
```

### Force Cache Clear
```python
# Clear entire cache
cache_manager.clear_all_caches()

# Clear specific folder
cache_manager.invalidate_folder("/path/to/folder")
```

## Future Enhancements

1. **Persistent cache**: Save cache between sessions
2. **Smart pre-fetching**: Learn user patterns
3. **Compression**: Reduce memory usage
4. **Network awareness**: Adjust strategy based on latency
5. **Cache warming**: Pre-load on startup
