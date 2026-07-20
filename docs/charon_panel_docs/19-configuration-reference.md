# Charon Configuration Reference

This document reflects the configuration surfaces that are active in the code
today. Older docs that mention `CHARON_*` override variables, test tiers, or a
different preference root are stale.

## Core Runtime Settings (`charon/config.py`)

### ComfyUI / processing
- `COMFY_URL_BASE`
  Default API endpoint. Currently `http://127.0.0.1:8188`.
- `COMFY_BATCH_TIMEOUT_SEC`
- `COMFY_QUEUE_GRACE_SEC`
- `COMFY_RESULT_WATCH_TIMEOUT_SEC`
- `COMFY_RESULT_WATCH_GRACE_SEC`
- `COMFY_DOWNLOAD_RETRIES`
- `COMFY_UPLOAD_RETRIES`
- `COMFY_OUTPUT_SCAN_LIMIT`
- `COMFY_ENABLE_HISTORY_RECOVERY`

These values shape how long `processor.py` waits for queue progress, result
files, and transient upload/download failures.

### Output behavior
- `AUTO_IMPORT_MAX_OUTPUTS`
- `AUTO_IMPORT_MAX_PER_GROUP`
- `AUTO_CREATE_CONTACT_SHEET`
- `AUTO_IMPORT_ATTACH_IVT`
- `CONTACT_SHEET_MAX_IMAGES`
- `CONTACT_SHEET_SCAN_OUTPUT_DIR`
- `CONTACT_SHEET_MAX_SCAN_FILES`

These directly influence how Charon imports results back into Nuke.

### Node identity / tracing
- `DEBUG_STEP_TRACE`
- `CHARON_NODE_ID_LENGTH`
- `CHARON_NODE_ID_SCRIPT_HASH_PREFIX`

These are used in `node_factory.py`, `processor.py`, and
`scene_nodes_runtime.py`.

## Repository Root

### Shared workflow root
Defined in `config.py`:

```python
DEFAULT_WORKFLOW_REPOSITORY_ROOT = r"\\buck\globalprefs\SHARED\CODE\Charon_repo\workflows"
WORKFLOW_REPOSITORY_ROOT = os.path.abspath(
    os.environ.get("CHARON_REPO") or DEFAULT_WORKFLOW_REPOSITORY_ROOT
)
REPOSITORY_SEARCH_PATHS = [WORKFLOW_REPOSITORY_ROOT]
GLOBAL_REPO_PATH = WORKFLOW_REPOSITORY_ROOT
```

Behavior:

- `workflow_runtime.load_workflow_bundle()` rejects folders outside this root.
- `workflow_local_store.py` mirrors workflow folders relative to this root.
- `FolderPanel` and folder loaders should never traverse above this root.
- Launch-time `global_path` overrides call `config.set_workflow_repository_root()`
  so model search, uploads, local mirrors, and node helpers share one active root.

## Preference Storage

### JSON preferences
`charon/preferences.py` stores `preferences.json` in:

1. `GALT_PLUGIN_DIR` if the environment variable is set
2. otherwise `%USERPROFILE%\AppData\Local\Galt\plugins\charon`

Important keys currently used by the runtime:

- `comfyui_launch_path`
- `comfyui_url_base` (optional; defaults to `COMFY_URL_BASE`)
- `first_time_setup_complete`
- `force_first_time_setup`
- `dependencies_verified`

### SQLite-backed user settings
`charon/settings/user_settings_db.py` stores per-host UI settings and bookmarks.
These are initialized from the active repository path during launch.

Important app settings defined in `config.APP_SETTING_DEFINITIONS`:

- `run_at_startup`
- `startup_mode`
- `always_on_top`
- `advanced_user_mode`
- `debug_logging`
- `tiny_offset_x`
- `tiny_offset_y`

## Output Roots (`charon/paths.py`)

### Runtime artifact root
Default root:

```text
D:\Nuke\charon
```

Set `CHARON_RUNTIME_ROOT` to override this location. If the default root cannot
be created, Charon falls back to `%LOCALAPPDATA%\Charon\runtime`.

`get_charon_temp_dir()` ensures these subfolders exist:

- `temp`
- `exports`
- `results`
- `debug`

### Final output root selection
`allocate_charon_output_path()` resolves outputs in this order:

1. `BUCK_PROJECT_PATH\Production\Work\<user>\_CHARON\...`
2. `BUCK_WORK_ROOT\Work\<user>\_CHARON\...`
3. fallback `<runtime root>\results\...`

Versioned filenames are emitted as:

```text
CharonOutput_v001.ext
CharonOutput_v002.ext
...
```

### Output directory structure
The directory template is:

```text
<root>\<user>\_CHARON\<category>\<workflow>\CharonOp_<node_id>\
```

Where:

- `<category>` is typically `2D` or `3D`
- `<workflow>` comes from the workflow folder name
- `<node_id>` comes from the CharonOp hidden id

## Local Workflow Mirror (`charon/workflow_local_store.py`)

The local mirror lives beneath the preferences root:

```text
Charon_repo_local\workflow\<relative workflow path>\
```

Important files:

- `workflow_validated.json`
- `.charon_cache\workflow_state.json`
- `.charon_cache\validation\validation_result_raw.json`
- `.charon_cache\validation\validation_resolve_status.json`
- `.charon_cache\validation\validation_resolve_log.json`

Behavior:

- Source workflow hash changes invalidate the validated override and validation
  cache.
- A validated local payload can replace the shared `workflow.json` for runtime
  loading.

## ComfyUI Environment Resolution
`comfy_environment.resolve_comfy_runtime()` is the application-level identity
for the configured installation and server. Resolution order for the endpoint is:

1. an explicitly supplied URL
2. `CHARON_COMFY_URL`
3. the `comfyui_url_base` preference
4. `config.COMFY_URL_BASE`

The resulting `ComfyEnvironment` binds `base_url` and `server_address` to these
filesystem fields:

- `configured_path`
- `base_dir`
- `comfy_dir`
- `models_dir`
- `python_exe`
- `embedded_root`

`paths.resolve_comfy_environment()` remains the lower-level filesystem resolver.
It accepts a launcher, portable root, ComfyUI root, models root, or embedded
Python executable.

`paths.extend_sys_path_with_comfy()` also adds the relevant ComfyUI and embedded
Python directories to `sys.path` for hosted runtime use.

The workflow conversion exporter intentionally remains a local conversion
harness on port 8188 because it may launch and own a temporary ComfyUI process.

## Dependency Bootstrap

### First-time setup
`first_time_setup.ensure_requirements_with_log()`:

- checks whether setup has already completed
- uses `SetupManager` to probe required dependencies
- forces setup if `charon_log.json` is missing or dependencies are absent
- rewrites `charon_log.json` after the probe/setup pass

### Required dependencies currently checked
`SetupManager.check_dependencies()` probes:

- Python packages:
  - `playwright`
  - `trimesh`
  - `hf_xet`
  - `psutil`
  - `pynvml`
- custom nodes:
  - `ComfyUI-Manager`
  - `ComfyUI-KJNodes`
  - `ComfyUI-Charon`

### Manager security
`dependency_check.ensure_manager_security_level()` forces
`security_level=weak` in the detected ComfyUI-Manager config.

## UI Settings

### Window sizing
- `WINDOW_WIDTH`
- `WINDOW_HEIGHT`
- `TINY_MODE_WIDTH`
- `TINY_MODE_HEIGHT`
- `TINY_MODE_MIN_WIDTH`
- `TINY_MODE_MIN_HEIGHT`

### Layout ratios
- `UI_FOLDER_PANEL_RATIO`
- `UI_CENTER_PANEL_RATIO`
- `UI_HISTORY_PANEL_RATIO`

These are validated to sum to `1.0`.

### Header and button sizing
- `UI_PANEL_HEADER_HEIGHT`
- `UI_BUTTON_WIDTH`
- `UI_SMALL_BUTTON_WIDTH`

### Keybind defaults
`config.DEFAULT_LOCAL_KEYBINDS` currently defines:

- `F4` quick search
- `Ctrl+Return` run/grab action
- `Ctrl+R` refresh
- `Ctrl+O` open folder
- `Ctrl+,` settings
- `F3` tiny mode

## Metadata Schema
`.charon.json` is normalized by `charon_metadata.py`. Current supported fields:

```json
{
  "workflow_file": "workflow.json",
  "description": "Short summary shown in the metadata pane.",
  "min_vram_gb": "24",
  "dependencies": [],
  "last_changed": "2025-10-18T16:32:00Z",
  "tags": [],
  "parameters": [],
  "is_3d_texturing": false
}
```

Legacy execution fields such as `entry`, `script_type`, `mirror_prints`, and
`run_on_main` are stripped or ignored for persisted Charon metadata.

## Environment Variables That Matter
- `GALT_PLUGIN_DIR`
  Overrides the preference and local-mirror root.
- `BUCK_PROJECT_PATH`
  Preferred project-rooted output location.
- `BUCK_WORK_ROOT`
  Secondary project-rooted output location.

Those are the environment variables with active meaning in the current runtime.
