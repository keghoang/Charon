# Repository Guidelines

## Project Structure & Module Organization
- `main.py` is the Nuke entry point and bootstraps the unified `charon/` package.
- `charon/` owns every runtime component:
  - `main.py`, `__init__.py` - launch helpers for embedding or standalone use.
  - `workflow_runtime.py`, `workflow_pipeline.py`, `workflow_analysis.py`, `workflow_browser_exporter.py` - discovery, conversion, prompt analysis, and the browser-based converter harness.
  - `processor.py`, `node_factory.py`, `scene_nodes_runtime.py` - CharonOp creation plus ComfyUI processing.
  - `paths.py`, `preferences.py`, `config.py` - filesystem and configuration single sources of truth.
  - `ui/` - PySide6 widgets for the production panel.
  - `execution/`, `settings/` - script engine helpers and persisted preferences.
- Documentation lives under `docs/charon_panel_docs/`; runtime assets are in `charon/resources/`.
- Runtime artifacts continue to land in `D:\Nuke\charon\{temp,exports,results,status,debug}`. Only check in debug dumps when they document regressions.

## Build, Test, and Development Commands
- Launch the production panel from Nuke's Script Editor:
  ```python
  import sys
  repo = r"D:\Coding\Nuke_ComfyUI"
  if repo not in sys.path:
      sys.path.insert(0, repo)
  exec(open(r"D:\Coding\Nuke_ComfyUI\main.py").read(), globals())
  ```
- Reload the panel in place without restarting Nuke:
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
- Conversion smoke test (requires ComfyUI's embedded Python):
  ```powershell
  python -c "from charon.workflow_runtime import load_workflow_bundle, convert_workflow;  bundle = load_workflow_bundle(r'workflows\rgb2x_albedo_GET');  convert_workflow(bundle['workflow'], comfy_path=r'D:\ComfyUI_windows_portable_nvidia\ComfyUI_windows_portable\run_nvidia_gpu.bat')"
  ```
- Inspect prompt dumps: `python -m json.tool debug\workflow_debug.json`

## Coding Style & Naming Conventions
- Follow PEP 8 (4-space indent, 100-column soft limit, snake_case identifiers).
- Module constants stay UPPER_SNAKE_CASE; PySide classes use PascalCase.
- Use explicit relative imports inside `charon/` and route user-visible strings through `charon.charon_logger`.
- Workflow-facing copy must use "workflow" (no residual "script" wording).
- `.charon.json` stores only `workflow_file`, `description`, `dependencies`, `last_changed`, `tags`, and `cm-cli` now populates `dependencies` from workflow metadata (don't hand-enter Git URLs).
- `.gitignore` must exclude `__pycache__/` and `*.pyc`.

## Testing Guidelines
- No automated suite exists yet; rely on manual verification:
  - Panel flow: load a preset under `workflows/`, spawn a CharonOp, press **Execute**, confirm conversion, submission, status transitions (`Ready -> Processing -> Completed`), and asset ingestion. Inspect `D:\Nuke\charon\debug` and `...\results` as needed.
  - Conversion path: after touching `workflow_pipeline.py` or `workflow_analysis.py`, rerun the smoke test with Set/Get heavy presets and capture stdout/stderr.
  - Sample data: no longer includes a seeding script; pull sample workflows from version control if you need a clean slate.

## Commit & Pull Request Guidelines
- **Critical Guardrail**: Never amend an existing commit, and never create a new commit unless the user explicitly instructs you to do so.
- Do not run `git commit` (or `git push`) unless the user explicitly asks for a commit at that moment; default stance is to avoid committing.
- Write imperative, scoped commits (e.g., "Consolidate workflow runtime helpers").
- Pull requests must summarize changes, list manual tests (panel run, conversion script), attach relevant screenshots or debug snippets, and call out migration steps or environment prerequisites.
- Update this document whenever you add commands, directories, or operational caveats future contributors should know.
- Team convention: obtain explicit approval from the requester before running `git commit` or `git push`.

## Architecture & Integration Notes
- `workflow_pipeline.convert_workflow` launches ComfyUI's embedded interpreter, loads custom nodes, and raises on failure while persisting debug context.
- CharonOp nodes include a hidden `charon_status` knob (`Ready`, `Processing`, `Completed`, `Error`); keep it in sync with the processor script so the Scene Nodes tab stays accurate.
- `paths.py` governs filesystem locations - extend it rather than hard-coding paths. Ensure the ComfyUI knob points to the portable install so `resolve_comfy_environment` finds `python_embeded`.
- Dependencies must be installed into the ComfyUI bundle; `nodes.init_extra_nodes(init_custom_nodes=True)` expects a complete environment.
- Preferences and caches persist under `%LOCALAPPDATA%\Charon\plugins\charon\`.
- Workflow conversion drives the real ComfyUI frontend via Playwright (`workflow_browser_exporter.py`). The embedded Python auto-installs Playwright/Chromium on first run; it reuses an existing ComfyUI on port 8188 when running and only launches a headless instance if the port is free.
- Workflows that emit 3D outputs (e.g., `.glb`) are stored under the `_CHARON/3D` tree; `.glb` assets are auto-converted to `.obj` via `trimesh` using the ComfyUI embedded Python. On launch, Charon checks the ComfyUI env for `trimesh` and Playwright and prompts to install if missing. CharonRead nodes will use ReadGeo for these assets.

## Consolidation Status (2025-10-24)
The legacy `charon_core` package has been retired. All runtime code now lives in `charon/`.

1. Metadata Alignment - complete
   - `.charon.json` handling (metadata manager, dialogs, seeding script) trimmed to the supported schema; samples regenerated.
2. Repository Hardening - complete
   - `config.WORKFLOW_REPOSITORY_ROOT` anchors discovery to `\buck\globalprefs\SHARED\CODE\Charon_repo\workflows`. Folder loader injects the user slug, invalidates caches, and blocks traversal outside the Charon tree.
3. Runtime Helpers - complete
   - `workflow_runtime.py` exposes `discover_workflows`, `load_workflow_bundle`, `convert_workflow`, and `spawn_charon_node`; conversion helpers live alongside it.
4. UI Wiring - complete
   - Script panel and main window delegate to the runtime helpers. Double-click and the Grab button create CharonOps through `spawn_charon_node`.
5. CharonOp Node Creation - complete
   - Node factory reuses the unified helpers; Grab defaults auto-import to enabled.
6. Processor Flow Port - complete
   - `charon.processor` owns ComfyUI submission. Workflows convert only when still in UI format, then submit via shared helpers. `spawn_charon_node` injects this processor.
7. Shared Output Management - not started
   - Next step: codify output layout helpers, log artifact destinations, and align with project storage conventions.
8. Instrumentation & Manual QA - not started
   - Pending: add structured logs (`metadata_read`, `conversion_start`, etc.), exercise the full Grab/Process loop, and document failure handling (missing repo, invalid JSON, conversion errors).

### Guardrails & Notes
- Never touch directories above `\buck\globalprefs\SHARED\CODE\Charon_repo\workflows`.
- Centralize configuration in `charon/config.py` instead of scattering constants.
- Record manual verification (launcher run, empty-repo test, Grab/Process flow) in commit messages for traceability.
