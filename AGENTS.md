# Repository Guidelines

## Project Structure & Module Organization
`main.py` remains the Nuke entry point that boots the production Charon panel. Conversion logic still lives under ``charon_core`/` (`ui.py`, `workflow_pipeline.py`, `workflow_analysis.py`, `workflow_loader.py`, `comfy_client.py`, `node_factory.py`, `processor_script.py`), but workflow–UI prototyping now happens in `prototypes/galt_clone/`, a standalone Galt-based browser focused on Comfy workflows:

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
  python -c "from `charon_core`.workflow_loader import load_workflow; \
from `charon_core`.workflow_pipeline import convert_workflow; \
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
      if name.split('.', 1)[0] in {"`charon_core`", "charon"}:
          sys.modules.pop(name, None)
  runpy.run_path(os.path.join(repo, "main.py"), run_name="__main__")
  ```

## Coding Style & Naming Conventions
Follow PEP 8 with 4-space indentation, a 100-character soft limit, and snake_case identifiers. Module constants stay in UPPER_SNAKE_CASE, PySide classes in PascalCase. Use explicit relative imports inside packages and emit messages through each module’s `logger`.

Prototype-specific guidance:
- Treat `prototypes/galt_clone/` as a standalone Python package; avoid leaking dependencies into ``charon_core``.
- All workflow-facing strings should say “workflow” (no residual “script” wording).
- `.charon.json` metadata stores only `workflow_file`, `description`, `dependencies`, `last_changed`, and `tags`; display names derive from folder names.
- `.gitignore` blocks `__pycache__/` and `*.pyc`.

## Testing Guidelines
There is no automated suite. Rely on manual runs:
- Production: use real workflows under `workflows/`, create a CharonOp, hit “Process”, and verify prompt conversion plus result ingestion. Inspect `D:\Nuke\charon\debug` for prompt dumps and `...\results` for outputs. After touching `workflow_pipeline.py` or `workflow_analysis.py`, rerun the smoke test with Set/Get-heavy presets and capture stdout/stderr.
- Prototype: launch via ``galt_clone_launch.py``, ensure the list populates, create a new workflow via the “+” button (select an existing `workflow.json`), and confirm metadata edits update `.charon.json` immediately. Regenerate samples with `python tools\populate_dummy_workflows.py` whenever you need a clean slate.

## Commit & Pull Request Guidelines
Write imperative, scoped commits (e.g., “Improve Set/Get flattening logs” or “Prototype workflow metadata editor”). Pull requests should summarize changes, list manual tests (panel run, conversion script, prototype flow), attach relevant screenshots or debug snippets, and note workflow migration steps or environment prerequisites. Update this document whenever you add commands, directories, or operational caveats future contributors must know.

## Architecture & Integration Notes
The converter enforces an external execution path: it launches ComfyUI’s embedded interpreter, loads custom nodes, and raises on any failure while saving debug context. Each generated CharonOp includes a hidden `charon_status` knob that the processor script updates (`Ready`, `Processing`, `Completed`, `Error`); the Scene Nodes tab depends on that knob, so keep it in sync when adding features. `paths.py` remains the single source of truth for filesystem locations—extend it rather than hard-coding paths. Ensure the ComfyUI path knob points to the portable install so `resolve_comfy_environment` discovers `python_embeded`. When adding dependencies, install them into that ComfyUI bundle; `nodes.init_extra_nodes(init_custom_nodes=True)` runs during conversion and expects a complete environment.

Prototype-specific architecture notes:
- `.charon.json` replaces `.galt.json`; legacy files are ignored by the prototype. Creation and editing always flow through `CharonMetadataDialog`, which writes only the Charon schema and updates the `last_changed` timestamp on save. Converting old metadata is handled manually—if a folder only contains `.galt.json`, the panel will show the read-only empty state until a `.charon.json` file is authored.
- The workflow list only supports Nuke/PySide6. Host-awareness logic in `qt_compat.py` still exists but the prototype assumes Nuke. We now treat every workflow as compatible, so software-specific filtering and iconography have been removed.
- Tag editing runs through the Charon metadata path; the tag manager ensures a `.charon.json` file exists before it attempts to mutate tags.

## Charon/Prototype Integration Plan (2025-10-21)
We are folding the prototype into the production Charon flow in measured stages. The checklist below is ordered, annotated with current status, and scoped so any engineer can pick up the next item without extra context. All workflows now live in `\\buck\globalprefs\SHARED\CODE\Galt_repo\kien\Charon\workflows`; never create or mutate folders above that root.

1. **Metadata Alignment — ? Complete**  
   - `charon_metadata.py`, dialogs, seeding script trimmed to `workflow_file`, `description`, `dependencies`, `last_changed`, `tags`.  
   - Sample workflows regenerated; `run_on_main` exposed only to the UI.

2. **Repository Hardening — ? Complete**  
   - Prototype derives its base path from `config.WORKFLOW_REPOSITORY_ROOT` (shared UNC).  
   - Folder loader invalidates caches before rescan, injects the current user’s slugged folder, and refuses to browse outside the Charon tree.  
   - Workflow creation always writes into `\\...\\<user>` and refreshes the view so the new folder appears immediately.

3. **Runtime Helper Module — ? Complete**  
   - `workflow_runtime.py` (headless) now exposes `discover_workflows`, `load_workflow_bundle`, `convert_workflow`, and `spawn_charon_node`.  
   - Supporting copies of `workflow_pipeline.py`, `workflow_converter.py`, `workflow_analysis.py`, `node_factory.py`, `paths.py` live under `prototypes/galt_clone/galt/` with relative imports.

4. **UI Wiring to Runtime Helpers — ? Complete**  
   - Script panel uses `workflow_runtime.load_workflow_bundle()`; the new Grab button (and double-click) loads bundles and creates CharonOps via `spawn_charon_node`.  
   - `main_window.execute_script()` delegates to the same helper so keyboard shortcuts behave identically.

5. **CharonOp Node Creation — ? Complete**  
   - Node creation logic from ``charon_core`/node_factory.py` ported to `prototypes/.../node_factory.py`.  
   - Grab action now spawns a CharonOp in Nuke; auto-import knob defaults to on.

6. **Processor Flow Port — ? Not Started**  
   - Next engineer should copy the minimal path from ``charon_core`/processor_script.py` into the prototype, adjusting imports to use the new runtime helpers.  
   - Goal: on “Process,” convert only if the stored workflow isn’t API formatted, then drive ComfyUI submission using the same prompt data.  
   - After porting, wire `spawn_charon_node` to use the prototype processor script instead of the legacy version.

7. **Shared Output Management — ? Not Started**  
   - Decide on output directory convention (reuse the new `paths.py`) and expose utilities to write `.nk` files / prompt dumps.  
   - Log the destination path for each generated artifact.

8. **Instrumentation & Manual QA — ? Not Started**  
   - Add log statements (`metadata_read`, `conversion_start`, `conversion_success`, `output_written`).  
   - Before enabling the new process path by default, run: prototype launch ? Grab workflow ? Process ? verify node executes and status transitions (`Ready ? Processing ? Completed`).  
   - Capture failure scenarios (missing repo, invalid JSON, conversion errors) and surface clear error dialogs.

### Guardrails & Notes
- Never touch directories above `\\buck\globalprefs\SHARED\CODE\Galt_repo\kien\Charon\workflows`. The script panel already blocks this; keep new code consistent.
- All modules under `prototypes/galt_clone/galt/` must continue using relative imports (`from ..foo import bar`).
- When introducing configuration, prefer `config.py`; avoid scattering new constants.
- Record manual verification steps (launcher run, empty-repo test, Grab/Process) in commit messages.

---

### Handoff Checklist (October 21, 2025)
You are taking over after Step 5 (CharonOp node creation) is complete. Focus on **Step 6: Processor Flow Port** next:

1. [x] Copied the processor logic into `prototypes/galt_clone/galt/processor.py`, trimming it to the conversion/submission path and routing conversions through `workflow_runtime.convert_workflow()`.
2. [x] Processor script reads the workflow bundle from the CharonOp knob and converts only when the payload is still in UI format.
3. [x] `workflow_runtime.spawn_charon_node()` now injects the prototype processor script.
4. [ ] Manual test: launch the prototype -> grab a workflow -> press `Process with ComfyUI` on the spawned node. Verify the processor executes without touching `charon_core`.
5. [x] Documentation updated. After running the manual test above, record the outcome (success/failure, notable logs, next steps).

Manual QA to run next:
- Launch via `galt_clone_launch.py`, grab any sample workflow, and trigger `Process with ComfyUI` on the created CharonOp.
- Confirm image uploads, prompt submission, and downloads succeed; inspect the node status payload and `D:\Nuke\charon\results` for outputs.
- If conversion fails, confirm the Comfy path is configured in the prototype footer (preferences stored under `%LOCALAPPDATA%\Galt\plugins\charon\preferences.json`).

Open questions / follow-up:
- Once the manual run is validated, consider wiring status telemetry into the prototype logger (mirroring the planned instrumentation in Step 8).
- Keep an eye on _API_conversion/conversion_log.md; expand to multi-entry history only if single-entry storage becomes limiting.
- Future work: port the processor output management (Step 7) and instrumentation/error surfacing (Step 8).

Thanks for keeping all shared logic in prototypes/galt_clone/galt/. Push only once Step 6 is fully verified and documented.
