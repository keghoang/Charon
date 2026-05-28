# Charon Current-State Refresher

## What Charon Is Now
Charon is a Nuke panel for browsing workflow folders, validating them against a
real ComfyUI installation, spawning CharonOp nodes into the script, and
submitting runs to ComfyUI without leaving Nuke.

The current product is workflow-first. A lot of module names still say "script"
because they were carried forward from an older tool shape, but in practice the
runtime revolves around workflow folders containing:

- `workflow.json`
- `.charon.json`
- optional local validation overrides and cached artifacts

## End-to-End Runtime Flow
1. `main.py` adds the repo to `sys.path` and calls `charon.main.launch()`.
2. `charon.main.launch()` runs first-time setup, checks dependencies, enforces
   ComfyUI-Manager security settings, and creates `CharonWindow`.
3. `CharonWindow` builds the Workflows tab, the CharonBoard tab, and the Comfy
   footer widget.
4. The workflow browser loads folders from
   `config.WORKFLOW_REPOSITORY_ROOT`, reads `.charon.json`, and loads
   `workflow.json` through `workflow_runtime.load_workflow_bundle()`.
5. Validation runs through `comfy_validation.validate_comfy_environment()`.
   Results are cached in the user's local mirror and surfaced in
   `ValidationResolveDialog`.
6. Grabbing a workflow calls `workflow_runtime.spawn_charon_node()`, which uses
   `node_factory.create_charon_group_node()` to build a CharonOp group.
7. Executing the node runs `processor.process_charonop_node()`, which:
   - converts UI JSON to API JSON when needed
   - uploads input images
   - submits the prompt to ComfyUI
   - watches status/history
   - downloads outputs
   - creates Read / ReadGeo nodes and optional contact sheets

## The Modules That Matter Most
- `charon/main.py`
  Launcher, first-time setup, and window creation.
- `charon/ui/main_window.py`
  Main panel composition. The key tabs are `Workflows` and `CharonBoard`.
- `charon/ui/script_panel.py`
  Workflow list, validation actions, drag/drop, metadata handoff, and spawn.
- `charon/workflow_runtime.py`
  Headless discovery/loading/conversion/spawn helpers shared by UI and runtime.
- `charon/workflow_pipeline.py`
  Conversion bridge that shells into ComfyUI's embedded Python.
- `charon/workflow_browser_exporter.py`
  Playwright harness that loads the real ComfyUI frontend and calls
  `graphToPrompt()`.
- `charon/comfy_validation.py`
  Environment, custom node, and model validation.
- `charon/workflow_local_store.py`
  Per-user local mirror plus validation cache and override files.
- `charon/node_factory.py`
  CharonOp creation, hidden knobs, status payload initialization, recursive
  controls, and UI-facing node actions.
- `charon/processor.py`
  The core submission and output-ingestion path.
- `charon/scene_nodes_runtime.py`
  Reads CharonOp status back out of the Nuke script for the CharonBoard tab.

## Panel Anatomy
- `Workflows` tab
  Folder tree, workflow table, metadata panel, validation controls, tag bar,
  settings/actions row.
- `CharonBoard` tab
  Live view of CharonOp nodes already in the scene. This is implemented by
  `SceneNodesPanel` and fed by `scene_nodes_runtime.py`.
- Footer
  Resource widget on the left, `ComfyConnectionWidget` on the right.

## Workflow State and Local Storage
Charon keeps three storage surfaces in play:

1. Shared source workflows
   `config.WORKFLOW_REPOSITORY_ROOT`
2. User preferences and local workflow mirror
   `GALT_PLUGIN_DIR` if set, otherwise
   `%USERPROFILE%\AppData\Local\Galt\plugins\charon`
3. Runtime temp/export/result/debug artifacts
   `D:\Nuke\charon\...` by default, plus project-rooted output paths when
   `BUCK_PROJECT_PATH` or `BUCK_WORK_ROOT` is available

Important local mirror files:

- `workflow_validated.json`
  User-local validated/overridden workflow payload.
- `.charon_cache/workflow_state.json`
  Source hash, validated hash, sync timestamps.
- `.charon_cache/validation/validation_result_raw.json`
  Raw validation payload.
- `.charon_cache/validation/validation_resolve_status.json`
  Current resolve/install state shown in the UI.

## Output Behavior
- 2D outputs are versioned under `_CHARON/2D/<workflow>/CharonOp_<id>/...`
- 3D outputs are versioned under `_CHARON/3D/<workflow>/CharonOp_<id>/...`
- When `.glb` assets are returned, Charon can convert them to `.obj` through
  ComfyUI's embedded Python with `trimesh`.
- CharonOp nodes track status through hidden knobs and metadata such as
  `charon_status`, `charon_status_payload`, `charon_last_output`, and
  `charon_auto_import`.

## What Still Looks Legacy In Code
- `script_panel.py`, `script_table_model.py`, and `workflow_model.py` still use
  "script" naming even though they are handling workflows.
- `execution/` and `ExecutionHistoryPanel` remain from the older architecture.
  They are still wired into `CharonWindow`, but they are no longer the center of
  the workflow processing path.
- Some docstrings and comments still say "script manager". The runtime behavior
  is workflow-oriented despite the naming drift.

## Practical Refresher Checklist
If you are re-entering the codebase, read in this order:

1. `PROJECT_SUMMARY.md`
2. `docs/charon_panel_docs/01-architecture.md`
3. `docs/charon_panel_docs/PROJECT_STRUCTURE.md`
4. `charon/workflow_runtime.py`
5. `charon/ui/script_panel.py`
6. `charon/processor.py`

## Current Risks / Review Notes
- The codebase is functionally consolidated under `charon/`, but naming cleanup
  is incomplete.
- Validation and local workflow override behavior are now core to daily use.
  Any workflow-loading change needs to be checked against `workflow_local_store`.
- There is still no automated test suite in-repo. Manual QA is the real gate.
