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

## Charon/Prototype Integration Plan
We are beginning to merge the Galt prototype into the main Charon experience, starting with “Create CharonOp from selected workflow.” Because this touches both UI and conversion logic, the work is staged carefully:

1. **Confirm Metadata Parity**  
   - Audit the `.charon.json` schema produced by the prototype and ensure it satisfies `charon_core`’s loader requirements (`workflow_file`, dependencies, tags, etc.).  
   - Document any missing fields (or defaults) so we know what the integration layer must fill.

2. **Define the UI Trigger**  
   - Decide where the user initiates the action (context menu, toolbar button, or dedicated panel control).  
   - Mock the interaction by emitting a signal that contains the workflow path and current metadata; do not call into the backend yet.

3. **Introduce an Integration Bridge**  
   - Add a new helper module (e.g., `prototypes/galt_clone/galt/charon_bridge.py`) that prepares workflow metadata and delegates to the existing conversion pipeline.  
   - Keep this module headless—no UI logic—so it can be unit-tested or reused by other entry points.

4. **Reuse Existing Conversion Pipeline**  
   - Inside the bridge, call `charon_core.workflow_loader.load_workflow()` and `charon_core.workflow_pipeline.convert_workflow()`.  
   - Validate the call stack with a known workflow before wiring it to the UI. Log the conversion path, Comfy entry point, and resulting output.

5. **UI ↔ Bridge Wiring**  
   - Once the bridge is reliable, connect the UI signal to a slot that invokes the bridge and handles progress, success, and error states.  
   - Use non-blocking calls (QFuture or a background thread) so the prototype remains responsive while conversion runs.  
   - Surface the generated CharonOp location, and optionally open it in Nuke if `main.py` can ingest it immediately.

6. **Output Management**  
   - Ensure the generated `.nk` (or node graph) lands in the same directories the production panel expects (`paths.py`).  
   - Consider adding a dedicated “exports” subfolder for prototype-driven conversions to keep work-in-progress separate from production submissions.

7. **Instrumentation & Testing**  
   - Add log statements around metadata preparation, conversion start/finish, and file writes.  
   - Manually test at least one workflow end-to-end: select in prototype, run conversion, open resulting CharonOp, and confirm `charon_status` transitions correctly once the production pipeline sees the op.  
   - Capture failure cases (missing workflow file, conversion errors, file write issues) and surface them via the UI.

This staged plan lets us merge functionality incrementally: metadata parity first, then a dedicated bridge, and finally UI wiring. During each stage we can ship smaller commits without destabilizing the current panel. Document progress and any new commands here as integration expands.
