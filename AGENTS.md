# Repository Guidelines

## Project Structure & Module Organization
`main.py` is the Nuke entry point that registers the Charon panel. Core logic now lives in the `charon_core/` package: `ui.py` renders the two-tab panel (workflow controls plus the Scene Nodes tracker), `workflow_pipeline.py` shells into ComfyUI's embedded Python for strict conversion, `workflow_analysis.py` derives knob metadata, `workflow_loader.py` discovers presets, `comfy_client.py` wraps HTTP calls, and `node_factory.py` plus `processor_script.py` build CharonOp nodes and their embedded execution script. Preset workflows reside in `workflows/`, while runtime artifacts land in `D:\Nuke\charon\{temp,exports,results,status,debug}`. Only commit debug dumps if they document a regression.

## Build, Test, and Development Commands
- Launch the panel from Nuke's Script Editor:
  ```python
  import sys
  sys.path.insert(0, r"D:\Coding\Nuke_ComfyUI")
  exec(open(r"D:\Coding\Nuke_ComfyUI\main.py").read(), globals())
  ```
- Conversion smoke test (requires ComfyUI's embedded Python):
  ```powershell
  python -c "from charon_core.workflow_loader import load_workflow; \
from charon_core.workflow_pipeline import convert_workflow; \
data = load_workflow('workflows/rgb2x_albedo_GET.json'); \
convert_workflow(data, comfy_path=r'D:\ComfyUI_windows_portable_nvidia\ComfyUI_windows_portable\run_nvidia_gpu.bat')"
  ```
- Inspect prompt dumps: `python -m json.tool debug\workflow_debug.json`
- Reload the latest code inside Nuke without restarting:
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
Follow PEP 8 with 4-space indentation, a 100-character soft limit, and snake_case identifiers. Module constants stay in UPPER_SNAKE_CASE, PySide classes in PascalCase. Use explicit relative imports inside `charon_core` and emit messages through each module's `logger`. Keep new knob names aligned with the `CR_input_*` convention so the UI summaries derived in `workflow_analysis` remain accurate.

## Testing Guidelines
No automated suite exists; rely on manual runs. Use workflows under `workflows/` to validate new features, generate a CharonOp node, and trigger `Process` to confirm prompt conversion, upload, and result ingestion. Check converted prompts in `D:\Nuke\charon\debug` and output assets under `...\results`. After modifying `workflow_pipeline.py` or `workflow_analysis.py`, rerun the smoke test against presets heavy in `SetNode/GetNode` usage (as documented in `PROJECT_SUMMARY.md`) and capture stdout/stderr for the pull request.

## Commit & Pull Request Guidelines
Write imperative, scoped commits (e.g., "Improve Set/Get flattening logs"). Pull requests should summarize the change, list manual tests (panel run, conversion script), include relevant screenshots or debug snippets, and link issues. Note any workflow migration steps or environment prerequisites. Update this document whenever you add commands, directories, or operational caveats that future contributors must know.

## Architecture & Integration Notes
The converter enforces an external execution path: it launches ComfyUI's embedded interpreter, loads custom nodes, and raises on any failure while saving debug context. Each generated CharonOp includes a hidden `charon_status` knob that the processor script updates (`Ready`, `Processing`, `Completed`, `Error`); the UI's Scene Nodes tab depends on that knob, so keep it in sync when adding features. `paths.py` must remain the single source of truth for filesystem locations—extend it rather than hard-coding paths. Ensure the ComfyUI path knob points to the portable install so `resolve_comfy_environment` discovers `python_embeded`. When adding dependencies, install them into that ComfyUI bundle; `nodes.init_extra_nodes(init_custom_nodes=True)` runs during conversion and expects the environment to be complete.
