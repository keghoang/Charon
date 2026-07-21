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

### `validation_repository.py`
Owns validation-state derivation, signature-aware transient caching, and durable
status reads for presentation consumers.

## Execution and scene

### `node_factory.py`
Creates the CharonOp contract in Nuke. Knob names and metadata form a public
runtime schema and require compatibility tests.

### `processor.py`
Current execution coordinator. Target phases: prepare, convert, materialize,
submit, monitor, retrieve, import, and finalize.

### Processor phase helpers

- `processor_context.py`: immutable run-context capture
- `processor_node_state.py`: host metadata writes; node identity initialization,
  deduplication, and migration; linked-output lookup, anchor repair, and status
  color propagation
- `processor_read_nodes.py`: Read/ReadGeo labels and info controls, grouped-node
  indexing, and link, unlink, placeholder creation, and placeholder removal
  transactions
- `processor_recursion.py`: recursive next-run dispatch plus final Nuke graph and
  attribute restoration
- `processor_conversion.py`: typed cache resolution and converted-prompt file
  serialization
- `processor_prompt_cache.py`: node-backed converted-prompt path/hash persistence
- `processor_submission.py`: per-batch prompt construction and submission
- `processor_status.py`: lifecycle transitions and node-backed status repository
- `processor_output.py`: result-manifest allocation, atomic publication,
  readiness/schema checks, batch normalization, import caps, output collection,
  classification, cleanup, and contact-sheet dispatch
- `processor_recovery.py`: queue-aware timeouts, bounded downloads, history
  reuse, and local output recovery
- `processor_inputs.py`: crop and input-value normalization
- `processor_trace.py`: ordered execution diagnostics and trace-file placement
- `background_jobs.py`: named daemon launches and explicit completed/error/timeout
  outcomes for bounded blocking operations
- `nuke_threading.py`: direct, asynchronous, and timeout-bounded Nuke main-thread
  dispatch

New headless execution policy belongs in these modules. `processor.py` retains
Nuke mutations and orchestration until each remaining phase has characterization
coverage and an explicit adapter boundary.

### `nuke_3d_tools.py`
Owns coverage-camera group creation, final-prep generation, texture-bake
generation, template parsing, and DAG placement. `nuke_3d_scripts.py` owns the
knob callback source, and `resources/nuke_template/charon_camera_rig.nk` owns
the camera rig payload. `CharonWindow` retains thin command wrappers only.

### `SceneNodesPanel` and `TinyModeWidget`
Read-only projections of CharonOp scene state plus explicit scene commands.

## ComfyUI integration

- `ComfyUIClient`: HTTP operations
- `ComfyConnectionWidget`: presentation and user commands
- `workflow_browser_exporter`: frontend-backed workflow conversion
- `SetupManager`: dependency installation
- `ModelTransferManager`: long-running model copies/downloads

The filesystem portion of the environment is now normalized by the
mapping in `paths.py`. `comfy_environment.py` binds that mapping to the endpoint
used by validation, processor fallback connections, setup, installation, and
connection monitoring. Process ownership remains a later extraction.
