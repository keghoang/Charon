# Charon - ComfyUI x Nuke Integration

## 1. High-Level Overview
Charon is a Nuke add-on that bridges the node graph to ComfyUI's API workflows. The project now consists of a launcher script (`main.py`) and a single `charon/` package that owns every subsystem:

- **UI (`charon/ui/`)** - PySide6 panels and widgets for workflow browsing, metadata editing, and CharonOp orchestration.
- **Workflow runtime (`charon/workflow_runtime.py`)** - Discovers workflows, loads bundles, and spawns CharonOps.
- **Conversion pipeline (`charon/workflow_pipeline.py`, `charon/workflow_converter.py`)** - Shells into ComfyUI's embedded Python, loads custom nodes, flattens Set/Get pairs, and emits API-ready prompts.
- **Analysis helpers (`charon/workflow_analysis.py`)** - Derives knob definitions and summaries for UI and converted graphs.
- **Processing path (`charon/processor.py`, `charon/node_factory.py`, `charon/scene_nodes_runtime.py`)** - Builds CharonOp nodes, drives ComfyUI submissions, and manages result ingestion.
- **Infrastructure (`charon/paths.py`, `charon/preferences.py`, `charon/config.py`, `charon/comfy_client.py`)** - Filesystem resolution, persisted settings, and REST utilities.

Supporting material lives in `docs/charon_panel_docs/`; runtime assets stay under `charon/resources/`.

## 2. Typical Workflow
1. **Launch** - In Nuke's Script Editor run:
   ```python
   import sys; sys.path.insert(0, r"D:\Coding\Nuke_ComfyUI")
   exec(open(r"D:\Coding\Nuke_ComfyUI\main.py").read(), globals())
   ```
   `main.py` ensures the repo is on `sys.path`, configures logging, and calls `charon.main.launch()`.
2. **Panel initialisation** - The panel:
   - Extends `sys.path` with the configured ComfyUI directory via `paths.extend_sys_path_with_comfy`.
   - Caches workflow folders, metadata, and raw JSON in memory.
   - Populates the Workflows tab, Scene Nodes tab, and footer connection controls.
   - Locates or prompts for the ComfyUI launcher, then runs `_check_connection()` with `ComfyUIClient`.
3. **Workflow selection** - Choosing a workflow calls `workflow_runtime.load_workflow_bundle()` which:
   - Validates the folder is inside `config.WORKFLOW_REPOSITORY_ROOT`.
   - Reads `.charon.json` metadata plus `workflow.json` payload.
   - Analyses inputs via `workflow_analysis.analyze_ui_workflow_inputs` to build knob descriptors.
4. **Create CharonOp** - Pressing **Grab Workflow**:
   - Invokes `workflow_runtime.spawn_charon_node()`.
   - `node_factory.create_charon_group_node()` builds a Group node, adds input knobs, stores the raw UI workflow, injects process/recreate scripts, and aligns the node in the graph.
5. **Execute** - The embedded button executes `charon.processor.process_charonop_node()`:
   - Loads the bundle from the node's knobs.
   - Converts to API format when needed via `workflow_runtime.convert_workflow()`.
   - Uploads inputs through `ComfyUIClient`, submits the prompt, polls `/history`, and downloads outputs.
   - Updates `charon_status`, writes prompt dumps, and creates Read nodes for results.

## 3. Key Paths & Directories
- Workflows live under `\buck\globalprefs\SHARED\CODE\Charon_repo\workflows` (per `config.WORKFLOW_REPOSITORY_ROOT`).
- Runtime artifacts are written to `D:\Nuke\charon\{temp,exports,results,status,debug}` via helpers in `charon/paths.py`.
- Preferences persist in `%LOCALAPPDATA%\Charon\plugins\charon\preferences.json`.

## 4. Developing and Testing
- Sample workflows ship in-repo; duplicate from `workflows/` if you need a clean set.
- Reload the panel in-place by clearing cached `charon.*` modules and re-running `main.py`.
- Run the conversion smoke test:
  ```powershell
  python -c "from charon.workflow_runtime import load_workflow_bundle, convert_workflow;  bundle = load_workflow_bundle(r'workflows\rgb2x_albedo_GET');  convert_workflow(bundle['workflow'], comfy_path=r'D:\ComfyUI_windows_portable_nvidia\ComfyUI_windows_portable\run_nvidia_gpu.bat')"
  ```
- Manual QA checklist:
  1. Launch panel from Nuke.
  2. Grab a workflow and spawn a CharonOp.
  3. Press **Execute**; verify status transitions, prompt dump, and Read node creation.
  4. Inspect `D:\Nuke\charon\results` for outputs.

## 5. Packaging Notes
- The repository is now package-ready: importers depend only on `charon/` (no `charon_core` links remain).
- `charon/__main__.py` supports launching via `python -m charon` for quick prototyping outside Nuke.
- When distributing, bundle the `charon` package plus `main.py`; optional docs can ship from `docs/`.

## 6. Next Steps
- Formalise shared output management utilities and log artifact destinations.
- Add instrumentation in the processor path (`metadata_read`, `conversion_start`, `conversion_success`, `output_written`).
- Document failure modes (missing repository, invalid JSON, conversion errors) and surface clear UI messaging.
