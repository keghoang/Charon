# Charon Testing Guide

## Current Reality
There is no automated test suite in this repository right now. Validation is
manual and should be recorded when making runtime changes.

Use the code and these manual flows as the source of truth. Older docs that
mention `tests/` tiers are stale.

## Fast Commands

### Launch from Nuke
Run in Nuke's Script Editor:

```python
import sys
repo = r"C:\Users\kien\git\Charon"
if repo not in sys.path:
    sys.path.insert(0, repo)
exec(open(r"C:\Users\kien\git\Charon\main.py").read(), globals())
```

### Reload in place without restarting Nuke
```python
import sys, importlib, os, runpy
repo = r"C:\Users\kien\git\Charon"
if repo not in sys.path:
    sys.path.insert(0, repo)
importlib.invalidate_caches()
for name in list(sys.modules):
    if name.split('.', 1)[0] == "charon":
        sys.modules.pop(name, None)
runpy.run_path(os.path.join(repo, "main.py"), run_name="__main__")
```

### Conversion smoke test
Requires ComfyUI's embedded Python and a valid workflow folder:

```powershell
python -c "from charon.workflow_runtime import load_workflow_bundle, convert_workflow; bundle = load_workflow_bundle(r'workflows\rgb2x_albedo_GET'); convert_workflow(bundle['workflow'], comfy_path=r'<path-to-your-ComfyUI-launcher>')"
```

### Inspect workflow debug payload
```powershell
python -m json.tool debug\workflow_debug.json
```

## Manual QA Checklist

### 1. Startup / setup
Use this after touching:

- `main.py`
- `first_time_setup.py`
- `setup_manager.py`
- `dependency_check.py`
- `comfy_connection_widget.py`

Checklist:

1. Launch Charon from Nuke.
2. Confirm the first-time setup flow only appears when expected.
3. Confirm the ComfyUI path is remembered.
4. Confirm the footer reaches a stable connected/offline state.
5. Confirm ComfyUI-Manager security level is forced to `weak`.
6. Enable **Force First Time Setup**, relaunch, and confirm Step 2 reaches **Next** without a host crash.
7. While Step 2 is actively installing, confirm closing the wizard is blocked until the worker thread exits.
8. Select an invalid launcher layout and confirm setup reports the missing ComfyUI `main.py` instead of copying custom nodes.

### 2. Workflow browse / validate / grab
Use this after touching:

- `workflow_runtime.py`
- `metadata_manager.py`
- `workflow_local_store.py`
- `comfy_validation.py`
- `ui/script_panel.py`
- `ui/validation_dialog.py`

Checklist:

1. Open a folder under the shared workflow repository.
2. Select a workflow and confirm metadata, tags, dependencies, and timestamps
   appear in the metadata panel.
3. Run validation.
4. Confirm the action column transitions through the expected state:
   `Validate`, `Resolve`, `Installing`, `Check for Restart`, `Passed`.
5. If validation resolves model paths or node installs, confirm artifacts are
   written under the local mirror's `.charon_cache/validation/`.
6. Grab the workflow and confirm a CharonOp is created in the Nuke script.

### 3. Execute a CharonOp
Use this after touching:

- `node_factory.py`
- `processor.py`
- `workflow_pipeline.py`
- `workflow_browser_exporter.py`
- `paths.py`
- `comfy_client.py`
- `scene_nodes_runtime.py`

Checklist:

1. Spawn a CharonOp from a validated workflow.
2. Press `Execute`.
3. Confirm `charon_status` transitions through `Ready -> Processing -> Completed`
   or an expected error state.
4. Confirm converted prompt data is generated when the workflow is still in UI
   JSON format.
5. Confirm input uploads, Comfy submission, and history polling succeed.
6. Confirm outputs land in the expected `_CHARON` or fallback results location.
7. Confirm Read / ReadGeo creation and optional contact sheet behavior.
8. Confirm the `CharonBoard` tab reflects the updated node state.

### 4. 3D output path
Use this after touching:

- `processor.py`
- `paths.py`
- `custom_nodes/comfyUI/ComfyUI-Charon/nodes/glb_to_obj.py`

Checklist:

1. Run a workflow that emits `.glb` or camera data.
2. Confirm outputs land under the `3D` branch of the Charon output tree.
3. Confirm `.glb` outputs are converted to `.obj` when expected.
4. Confirm Charon imports them as geometry nodes, not image reads.

### 5. Refresh / selection / caching behavior
Use this after touching:

- `workflow_model.py`
- `folder_loader.py`
- `cache_manager.py`
- `ui/main_window.py`
- `ui/folder_panel.py`

Checklist:

1. Refresh the repository.
2. Confirm folder selection is preserved when possible.
3. Confirm validation state is not accidentally dropped on a soft refresh.
4. Confirm stale caches are invalidated when metadata or workflows change.

## Useful Artifact Locations
- Runtime temp/export/result/debug root:
  `CHARON_RUNTIME_ROOT`, otherwise `D:\Nuke\charon`, otherwise
  `%LOCALAPPDATA%\Charon\runtime`
- Local mirror and validation cache:
  `GALT_PLUGIN_DIR` or
  `%USERPROFILE%\AppData\Local\Galt\plugins\charon\Charon_repo_local`
- ComfyUI-side setup log:
  `<ComfyUI>\user\default\charon_log.json`

## What To Capture In A Change Note
When you change runtime behavior, record:

1. Which workflow was used for QA.
2. Whether validation was exercised.
3. Whether the workflow required conversion.
4. Whether outputs were 2D or 3D.
5. Where artifacts were written.
6. Any restart/setup preconditions.
