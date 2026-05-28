# Charon Architecture Overview

## Purpose
Charon is a Nuke-side workflow browser and execution bridge for ComfyUI. Its
job is to:

1. discover workflow folders from the approved repository root
2. validate a workflow against the user's ComfyUI install
3. create a CharonOp node in Nuke
4. convert UI-format workflows to API prompts when required
5. submit runs to ComfyUI and ingest the results back into the script

## Product Model
The runtime is built around workflow folders, not loose scripts. A typical
workflow folder contains:

- `workflow.json`
- `.charon.json`
- optional user-local validation caches and validated overrides

`.charon.json` is intentionally lightweight. The current supported fields are:

- `workflow_file`
- `description`
- `min_vram_gb`
- `dependencies`
- `last_changed`
- `tags`
- `parameters`
- `is_3d_texturing`

## High-Level Flow
1. Launch
   `main.py` or `charon.Go()` calls `charon.main.launch()`.
2. Setup
   `charon.main.launch()` runs first-time setup and dependency checks.
3. UI bootstrap
   `CharonWindow` builds the Workflows tab, CharonBoard tab, and footer widgets.
4. Discovery
   Folder and workflow loaders enumerate folders beneath
   `config.WORKFLOW_REPOSITORY_ROOT`.
5. Bundle load
   `workflow_runtime.load_workflow_bundle()` loads metadata and workflow JSON,
   synchronizes the local mirror, and prefers a validated local override when
   one exists.
6. Validation
   `comfy_validation.validate_comfy_environment()` probes custom nodes, models,
   and runtime readiness. Results are shown in `ValidationResolveDialog`.
7. Spawn
   `workflow_runtime.spawn_charon_node()` analyzes inputs and creates a CharonOp
   through `node_factory.create_charon_group_node()`.
8. Execute
   `processor.process_charonop_node()` converts when needed, uploads inputs,
   submits the prompt, watches history/status, downloads results, and updates
   the scene.

## Core Layers

### 1. Launch / bootstrap
- `main.py`
  Thin repo bootstrap for Nuke Script Editor usage.
- `charon/__init__.py`
  Exposes `charon.Go()`.
- `charon/main.py`
  Entry point for startup, first-time setup, and window creation.
- `charon/first_time_setup.py`
  Decides whether the setup dialog must run and writes `charon_log.json` into
  the ComfyUI user tree.
- `charon/setup_manager.py`
  Detects and installs required Python packages and custom nodes into the
  ComfyUI environment.

### 2. Workflow runtime
- `charon/workflow_runtime.py`
  Canonical headless helpers for discovery, bundle loading, conversion, and
  node spawning.
- `charon/metadata_manager.py`
  Reads `.charon.json`, writes metadata, and constructs the bundle payload.
- `charon/charon_metadata.py`
  Normalizes Charon metadata fields.
- `charon/workflow_analysis.py`
  Extracts exposed inputs and basic workflow validation signals.

### 3. Validation and local override system
- `charon/comfy_validation.py`
  Main validation engine. This is where environment, custom node, and model
  checks live.
- `charon/workflow_local_store.py`
  Maintains the per-user mirror, workflow hashes, validation artifacts, and
  validated workflow payload.
- `charon/workflow_overrides.py`
  Applies model-path replacements derived from validation results.
- `charon/validation_resolver.py`
  Support utilities for the resolve/install path.

### 4. Conversion pipeline
- `charon/workflow_pipeline.py`
  Sends UI workflow JSON through ComfyUI's embedded Python.
- `charon/workflow_browser_exporter.py`
  Uses Playwright against the real ComfyUI frontend and calls `graphToPrompt()`.

This is an important design choice: Charon does not maintain its own UI-to-API
workflow converter. It reuses ComfyUI's real graph export behavior.

### 5. Node creation and execution
- `charon/node_factory.py`
  Builds CharonOp group nodes, hidden status knobs, parameter controls,
  recursive controls, and helper buttons.
- `charon/processor.py`
  The main execution path. Handles conversion caching, prompt overrides, upload,
  submit, poll, download, import, recursion, and contact-sheet generation.
- `charon/scene_nodes_runtime.py`
  Reads CharonOp state back out of the current Nuke scene.

### 6. UI composition
- `charon/ui/main_window.py`
  Top-level window, tab wiring, footer wiring, refresh flow, and overall layout.
- `charon/ui/script_panel.py`
  Workflow table, validation actions, drag/drop, metadata handoff, and
  CharonOp spawning.
- `charon/ui/metadata_panel.py`
  Displays `.charon.json` fields, dependencies, tags, and timestamps.
- `charon/ui/scene_nodes_panel.py`
  The live "CharonBoard" view of existing CharonOps.
- `charon/ui/comfy_connection_widget.py`
  Monitors server connectivity, starts/stops ComfyUI, and stores the configured
  launch path.
- `charon/ui/validation_dialog.py`
  Validation results, resolve actions, model downloads/copies, and restart flow.

## Data Surfaces

### Shared repository
`config.WORKFLOW_REPOSITORY_ROOT` is the authoritative source for workflow
folders. `workflow_runtime.load_workflow_bundle()` rejects folders outside this
root.

### Local mirror
The per-user mirror lives under the preferences root:

- `GALT_PLUGIN_DIR` when set
- otherwise `%USERPROFILE%\AppData\Local\Galt\plugins\charon`

Important artifacts:

- `Charon_repo_local/workflow/.../workflow_validated.json`
- `Charon_repo_local/workflow/.../.charon_cache/workflow_state.json`
- `Charon_repo_local/workflow/.../.charon_cache/validation/...`

### Runtime artifacts
`paths.py` manages temp/export/result/debug paths. Default root:

- `D:\Nuke\charon`

Final outputs prefer BUCK project paths when available:

- `BUCK_PROJECT_PATH\Production\Work\<user>\_CHARON\...`
- or `BUCK_WORK_ROOT\Work\<user>\_CHARON\...`

## CharonOp State Model
Every CharonOp stores execution state in hidden knobs and metadata. The most
important fields are:

- `charon_status`
- `charon_status_payload`
- `charon_auto_import`
- `charon_last_output`
- `charon_node_id`
- `charon_script_hash`

`scene_nodes_runtime.py` reads these surfaces to drive the CharonBoard tab.

## UI Tabs

### Workflows
This is the authoring/browsing surface:

- folder navigation
- workflow list
- validation state column
- metadata panel
- tag filtering
- quick search
- create/grab actions

### CharonBoard
This is a scene-state surface showing existing CharonOps, their progress,
output availability, and import actions.

## Legacy Naming Drift
The consolidation is real, but the naming cleanup is unfinished. Examples:

- `ScriptPanel` displays workflows
- `ScriptTableModel` stores workflow rows and validation state
- `workflow_model.py` still names row items `ScriptItem`
- `ExecutionHistoryPanel` is legacy infrastructure and is hidden in the current
  default layout

Treat the behavior as authoritative, not the class names.

## Architectural Implications For Changes
- If you change workflow loading, verify behavior in `metadata_manager.py`,
  `workflow_runtime.py`, and `workflow_local_store.py` together.
- If you change validation, verify both the UI state machine in
  `script_panel.py` and the persisted cache in `workflow_local_store.py`.
- If you change outputs, verify `paths.py`, `processor.py`, and
  `scene_nodes_runtime.py`.
- If you change spawn-time knobs, verify both `node_factory.py` and the
  processor's readback path.
