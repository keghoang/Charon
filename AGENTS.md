# Repository Guidelines

## Project Structure & Module Organization
`main.py` remains the Nuke entry point that boots the production Charon panel. Conversion logic still lives under `charon_core/` (`ui.py`, `workflow_pipeline.py`, `workflow_analysis.py`, `workflow_loader.py`, `comfy_client.py`, `node_factory.py`, `processor_script.py`), but workflow–UI prototyping now happens in `prototypes/galt_clone/`, a standalone Galt-based browser focused on Comfy workflows:

- `prototypes/galt_clone/galt/ui/script_panel.py` lists workflows, handles creation, and points to `.charon.json`.
- `prototypes/galt_clone/galt/ui/metadata_panel.py` renders/edits metadata for workflows.
- `prototypes/galt_clone/galt/charon_metadata.py` loads/saves the new `.charon.json` schema.
- `tools/populate_dummy_workflows.py` seeds sample workflows per user.

Runtime artifacts for the production panel still land in `D:\Nuke\charon\{temp,exports,results,status,debug}`. Only check in debug dumps when they document regressions.

## Build, Test, and Development Commands
- Launch the production panel from Nuke’s Script Editor:
  ```python
  import sys
  sys.path.insert(0, r"D:\Coding\Nuke_ComfyUI")
  exec(open(r"D:\Coding\Nuke_ComfyUI\main.py").read(), globals())
  ```
- Launch the workflow prototype without restarting Nuke:
  ```python
  import sys, importlib, os, runpy
  repo = r"C:\Users\kien\git\Charon"
  if repo not in sys.path:
      sys.path.insert(0, repo)
  importlib.invalidate_caches()
  for name in list(sys.modules):
      if name.startswith("prototypes.galt_clone"):
          sys.modules.pop(name, None)
  runpy.run_module("prototypes.galt_clone.galt.main", run_name="__main__", alter_sys=True)
  ```
- Conversion smoke test (requires ComfyUI’s embedded Python):
  ```powershell
  python -c "from charon_core.workflow_loader import load_workflow; \
from charon_core.workflow_pipeline import convert_workflow; \
data = load_workflow('workflows/rgb2x_albedo_GET.json'); \
convert_workflow(data, comfy_path=r'D:\ComfyUI_windows_portable_nvidia\ComfyUI_windows_portable\run_nvidia_gpu.bat')"
  ```
- Inspect prompt dumps: `python -m json.tool debug\workflow_debug.json`
- Reload the production panel in-place:
  ```python
  import sys, importlib, os, runpy
  repo = r"C:\Users\kien\git\Charon"
  if repo not in sys.path:
      sys.path.insert(0, repo)
  importlib.invalidate_caches()
  for name in list(sys.modules):
      if name.split('.', 1)[0] in {"charon_core", "charon"}:
          sys.modules.pop(name, None)
  runpy.run_path(os.path.join(repo, "main.py"), run_name="__main__")
  ```

## Coding Style & Naming Conventions
Follow PEP 8 with 4-space indentation, a 100-character soft limit, and snake_case identifiers. Module constants stay in UPPER_SNAKE_CASE, PySide classes in PascalCase. Use explicit relative imports inside packages and emit messages through each module’s `logger`.

Prototype-specific guidance:
- Treat `prototypes/galt_clone/` as a standalone Python package; avoid leaking dependencies into `charon_core`.
- All workflow-facing strings should say “workflow” (no residual “script” wording).
- `.charon.json` metadata stores only `workflow_file`, `description`, `dependencies`, `last_changed`, and `tags`; display names derive from folder names.
- `.gitignore` blocks `__pycache__/` and `*.pyc`.

## Testing Guidelines
There is no automated suite. Rely on manual runs:
- Production: use real workflows under `workflows/`, create a CharonOp, hit “Process”, and verify prompt conversion plus result ingestion. Inspect `D:\Nuke\charon\debug` for prompt dumps and `...\results` for outputs. After touching `workflow_pipeline.py` or `workflow_analysis.py`, rerun the smoke test with Set/Get-heavy presets and capture stdout/stderr.
- Prototype: launch via `galt_clone_launch.py`, ensure the list populates, create a new workflow via the “+” button (select an existing `workflow.json`), and confirm metadata edits update `.charon.json` immediately. Regenerate samples with `python tools\populate_dummy_workflows.py` whenever you need a clean slate.

## Commit & Pull Request Guidelines
Write imperative, scoped commits (e.g., “Improve Set/Get flattening logs” or “Prototype workflow metadata editor”). Pull requests should summarize changes, list manual tests (panel run, conversion script, prototype flow), attach relevant screenshots or debug snippets, and note workflow migration steps or environment prerequisites. Update this document whenever you add commands, directories, or operational caveats future contributors must know.

## Architecture & Integration Notes
The converter enforces an external execution path: it launches ComfyUI’s embedded interpreter, loads custom nodes, and raises on any failure while saving debug context. Each generated CharonOp includes a hidden `charon_status` knob that the processor script updates (`Ready`, `Processing`, `Completed`, `Error`); the Scene Nodes tab depends on that knob, so keep it in sync when adding features. `paths.py` remains the single source of truth for filesystem locations—extend it rather than hard-coding paths. Ensure the ComfyUI path knob points to the portable install so `resolve_comfy_environment` discovers `python_embeded`. When adding dependencies, install them into that ComfyUI bundle; `nodes.init_extra_nodes(init_custom_nodes=True)` runs during conversion and expects a complete environment.

Prototype-specific architecture notes:
- `.charon.json` replaces `.galt.json`; legacy files are ignored by the prototype. Creation and editing always flow through `CharonMetadataDialog`, which writes only the Charon schema and updates the `last_changed` timestamp on save. Converting old metadata is handled manually—if a folder only contains `.galt.json`, the panel will show the read-only empty state until a `.charon.json` file is authored.
- The workflow list only supports Nuke/PySide6. Host-awareness logic in `qt_compat.py` still exists but the prototype assumes Nuke. We now treat every workflow as compatible, so software-specific filtering and iconography have been removed.
- Tag editing runs through the Charon metadata path; the tag manager ensures a `.charon.json` file exists before it attempts to mutate tags.

## Charon/Prototype Integration Plan (2025-10-21)
We are folding the prototype into the production Charon flow in measured stages. The checklist below is ordered, annotated with current status, and scoped so any engineer can pick up the next item without extra context. All workflows now live in \buck\globalprefs\SHARED\CODE\Galt_repo\kien\Charon\workflows; never create or mutate folders above that root.

1. **Metadata Alignment — ✅ Complete**  
   - `.charon.json` schema is authoritative: `workflow_file`, `description`, `dependencies` (list of `{name, repo, ref}`), `last_changed`, `tags`.  
   - Prototype writers were trimmed to that schema (`charon_metadata.py`, dialogs, seeding script) and sample workflows were regenerated.  
   - `run_on_main` is exposed to the UI only; legacy `display_name`/`entry` flags were removed.

2. **Repository Hardening — ✅ Complete**  
   - Prototype derives its base path from `config.WORKFLOW_REPOSITORY_ROOT` (shared UNC).  
   - Folder loader invalidates caches before rescan, injects the current user’s slugged folder, and refuses to browse outside the Charon tree.  
   - Workflow creation always writes into `\...\<user>` and forces a folder refresh so the new directory appears immediately.

3. **Runtime Helper Module — ✅ Complete**  
   - Add `prototypes/galt_clone/galt/workflow_runtime.py` with:
     - `discover_workflows(base_path)` → summaries for the list view.  
     - `load_workflow(folder_path)` → metadata dict + parsed `workflow.json`.  
     - `convert_workflow(payload, comfy_path)` → thin wrapper around the external conversion logic.  
   - Reuse `metadata_manager.load_workflow_data` and `workflow_pipeline.convert_workflow`.  
   - Log via `galt_logger`; raise structured errors for missing repo/metadata/comfy path.

4. **UI Wiring to Runtime Helpers — ✅ Complete**  
   - Replace `_last_workflow_data` in `script_panel.py` with `workflow_runtime.load_workflow`.  
   - Ensure Grab/double-click stores the raw payload + metadata bundle without converting.  
   - Centralize Comfy path/config and pass it into the runtime helper.

5. **CharonOp Node Creation — ✅ Complete**  
   - Port the relevant logic from `charon_core/node_factory.py` into a helper (e.g., `workflow_runtime.spawn_charon_node`).  
   - Populate all expected knobs (`workflow_data`, `workflow_path`, `charon_status`, etc.) and serialize the raw JSON to the node.  
   - When Nuke is available, spawn the node immediately; otherwise emit a payload for manual import.

6. **Processor Flow Port — ⏳ Not Started**  
   - Copy the minimal path from `charon_core/processor_script.py` to the prototype.  
   - On “Process,” convert only if the stored workflow is not already API format (using `workflow_runtime.convert_workflow`).  
   - Integrate status updates, asset uploads, and skip reconversion when the cached prompt is valid.

7. **Shared Output Management — ⏳ Not Started**  
   - Decide on output directory conventions (reuse `charon_core.paths` helpers) and expose utilities to write `.nk` files / prompt dumps.  
   - Log the destination path for each generated artifact.

8. **Instrumentation & Manual QA — ⏳ Not Started**  
   - Add log statements (`metadata_read`, `conversion_start`, `conversion_success`, `output_written`).  
   - Run an end-to-end test before enabling the UI action: select workflow → Grab → Process → verify node execution and status transitions.  
   - Capture failure scenarios (missing repo, invalid JSON, conversion errors) and surface clear error dialogs.

**Guardrails & Notes**  
- Never touch directories above \buck\globalprefs\SHARED\CODE\Galt_repo\kien\Charon\workflows.  
- New modules under `prototypes/galt_clone/galt/` must use relative imports (`from ..foo import bar`).  
- When introducing configuration, prefer `config.py`; avoid scattering constants.  
- Record manual verification steps (launcher run, empty-repo test, Grab/Process) in commit messages.

Update this section as milestones land: mark steps complete, note key files, and list the manual test performed.
