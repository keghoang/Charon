# Charon Project Structure

## Repository Root
```text
Charon/
|-- AGENTS.md
|-- PROJECT_SUMMARY.md
|-- main.py
|-- requirements.txt
|-- docs/
|-- charon/
|-- custom_nodes/
`-- packaging/
```

## Top-Level Folders
- `charon/`
  Main runtime package. This is where the current application logic lives.
- `docs/charon_panel_docs/`
  Architecture and maintenance notes. Read the updated files first.
- `custom_nodes/comfyUI/ComfyUI-Charon/`
  Custom node bundle that gets installed into ComfyUI.
- `packaging/`
  Packaging helpers.
- `debug/`
  Local debug artifacts.

## Main Runtime Package
```text
charon/
|-- __init__.py
|-- __main__.py
|-- main.py
|-- config.py
|-- paths.py
|-- preferences.py
|-- charon_logger.py
|-- metadata_manager.py
|-- charon_metadata.py
|-- workflow_runtime.py
|-- workflow_pipeline.py
|-- workflow_browser_exporter.py
|-- workflow_analysis.py
|-- workflow_local_store.py
|-- workflow_overrides.py
|-- comfy_environment.py
|-- comfy_validation.py
|-- comfy_client.py
|-- setup_manager.py
|-- first_time_setup.py
|-- dependency_check.py
|-- node_factory.py
|-- processor.py
|-- processor_context.py
|-- processor_inputs.py
|-- processor_node_state.py
|-- processor_output.py
|-- processor_prompt_cache.py
|-- processor_read_nodes.py
|-- processor_recursion.py
|-- processor_recovery.py
|-- processor_status.py
|-- processor_submission.py
|-- processor_trace.py
|-- background_jobs.py
|-- validation_repository.py
|-- nuke_3d_tools.py
|-- nuke_3d_scripts.py
|-- scene_nodes_runtime.py
|-- conversion_cache.py
|-- resource_monitor.py
|-- ui/
|-- execution/
|-- settings/
`-- resources/
```

## UI Package
```text
charon/ui/
|-- main_window.py
|-- script_panel.py
|-- metadata_panel.py
|-- scene_nodes_panel.py
|-- comfy_connection_widget.py
|-- validation_dialog.py
|-- folder_panel.py
|-- quick_search.py
|-- tag_bar.py
|-- execution_history_panel.py
|-- first_time_setup_dialog.py
|-- resource_widget.py
`-- keybinds/
```

Notes:

- `script_panel.py` still uses legacy naming, but it is the main workflow list
  and validation UI.
- `scene_nodes_panel.py` is presented in the product as the `CharonBoard` tab.
- `execution_history_panel.py` is legacy infrastructure and is hidden in the
  current default layout.

## Workflow Runtime / Validation Files
- `workflow_runtime.py`
  Headless load/convert/spawn helpers shared by UI and node processing.
- `workflow_pipeline.py`
  Conversion bridge into ComfyUI's embedded Python.
- `workflow_browser_exporter.py`
  Playwright exporter that uses the real ComfyUI frontend.
- `workflow_local_store.py`
  Local mirror, cache, validation artifacts, validated workflow payload.
- `workflow_overrides.py`
  Applies resolved model-path replacements from validation cache.
- `comfy_validation.py`
  Environment, custom node, and model validation.
- `comfy_environment.py`
  Canonical filesystem and HTTP identity for a ComfyUI runtime.
- `validation_repository.py`
  Signature-aware transient and durable validation-state access.

## Node / Execution Files
- `node_factory.py`
  Builds CharonOp groups and their knob layout.
- `processor.py`
  Transitional run coordinator; Nuke mutations remain here while headless
  phases move into `processor_*` modules.
- `processor_recovery.py`
  Queue-aware timeouts, bounded downloads, history reuse, and local recovery.
- `processor_output.py`
  Result-manifest allocation and atomic publication, output classification, and
  local-path resolution.
- `processor_trace.py`
  Ordered processor diagnostics and trace-file placement.
- `processor_node_state.py`
  Node identity access plus linked-output discovery, migration, and anchor repair.
- `processor_read_nodes.py`
  Read/ReadGeo labels, grouping, info controls, link/unlink state, and placeholder
  handling.
- `processor_recursion.py`
  Recursive iteration dispatch and final Nuke graph/attribute restoration.
- `processor_prompt_cache.py`
  Node-backed converted-prompt path and workflow-hash persistence.
- `background_jobs.py`
  Named daemon launches and explicit outcomes for bounded blocking work.
- `nuke_3d_tools.py`
  Nuke infrastructure for coverage, final-prep, and texture-bake tools.
- `nuke_3d_scripts.py`
  Embedded Python callback source installed on Nuke 3D helper groups.
- `resources/nuke_template/charon_camera_rig.nk`
  Packaged camera-rig graph pasted by the 3D camera command.
- `scene_nodes_runtime.py`
  Reads CharonOp state from the scene for CharonBoard.
- `conversion_cache.py`
  Cache helpers for converted prompts.

## Support Infrastructure
- `config.py`
  Central constants for UI sizing, repository root, timeouts, output limits, and
  app settings.
- `paths.py`
  Comfy environment resolution, temp/result roots, and output allocation rules.
- `preferences.py`
  JSON-backed preference storage rooted at `GALT_PLUGIN_DIR` or the local Galt
  plugin path.
- `settings/user_settings_db.py`
  SQLite-backed per-host UI/app settings and bookmarks.

## Runtime Assets
```text
charon/resources/
|-- banner.png
|-- charon_placeholder.png
|-- logos/
`-- nuke_template/
```

## Custom Node Bundle
```text
custom_nodes/comfyUI/ComfyUI-Charon/
|-- __init__.py
|-- requirements.txt
|-- README.md
`-- nodes/
    |-- __init__.py
    |-- auto_align.py
    |-- charon_camera.py
    `-- glb_to_obj.py
```

## Documentation Files Worth Keeping Current
- `../../PROJECT_SUMMARY.md`
- `01-architecture.md`
- `18-testing-guide.md`
- `19-configuration-reference.md`
- `PROJECT_STRUCTURE.md`

## Important Naming Reminder
Older filenames often say `script`, but the current product model is workflow
folders plus CharonOp scene nodes. Read those modules through that lens.
