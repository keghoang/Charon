# Component Map

## Application shell

### `CharonWindow`
Owns window modes, top-level tabs, and application navigation. Transitional
responsibilities to extract: cache orchestration, repository refresh policy,
hardware probing, and 3D Nuke tools.

### `WindowManager`
Owns window reuse, host parenting, and window flags. Current product support is
Nuke; historical Maya branches should remain isolated until removed.

## Workflow browser

### `FolderPanel`
Folder selection and presentation through `FolderTableModel`.

### `ScriptPanel`
Current workflow list feature. It owns `ScriptTableModel`, selection, filtering,
drag/drop, validation launch, and workflow import. Target split:
- workflow browser view
- workflow browser controller
- validation controller
- workflow authoring/import service

### `MetadataPanel`
Displays and edits supported `.charon.json` fields. Durable writes must remain
behind metadata services.

## Validation

### `comfy_validation.py`
Headless environment, custom-node, and model checks.

### `model_paths.py`
Pure normalization rules for resolved model files and workflow model values.
This module is safe to test without Qt, Nuke, or a running ComfyUI instance.

### `ValidationResolveDialog`
Current results and resolution UI. Target: render a `ValidationSession` and
dispatch resolve/install/restart commands to services.

### `validation_resolver.py`
Headless candidate search, copying, and node-install support.

## Execution and scene

### `node_factory.py`
Creates the CharonOp contract in Nuke. Knob names and metadata form a public
runtime schema and require compatibility tests.

### `processor.py`
Current execution coordinator. Target phases: prepare, convert, materialize,
submit, monitor, retrieve, import, and finalize.

### `SceneNodesPanel` and `TinyModeWidget`
Read-only projections of CharonOp scene state plus explicit scene commands.

## ComfyUI integration

- `ComfyUIClient`: HTTP operations
- `ComfyConnectionWidget`: presentation and user commands
- `workflow_browser_exporter`: frontend-backed workflow conversion
- `SetupManager`: dependency installation
- `ModelTransferManager`: long-running model copies/downloads

The filesystem portion of the environment is now normalized by the
`ComfyEnvironment` mapping in `paths.py`. The next boundary is a runtime service
that binds that mapping to the configured HTTP endpoint and active server.
