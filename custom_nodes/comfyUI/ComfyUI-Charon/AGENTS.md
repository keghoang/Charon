# Repository Guidelines

## Project Structure & Module Organization
- Root `__init__.py` wires ComfyUI node registrations and prints load status; `WEB_DIRECTORY` is intentionally `None` (no frontend assets).
- `nodes/auto_align.py`: `CHARON_3D_Auto_Align` mesh aligner that can infer symmetry and ground contact, writes aligned OBJ plus a transform JSON.
- `nodes/charon_camera.py`: `CHARON_Camera_From_DA3` converts DA3 intrinsics/extrinsics to a Nuke Camera3 snippet, optionally composes the align transform.
- `requirements.txt`: runtime deps (only `trimesh` beyond ComfyUI/NumPy).
- Place the whole folder under `ComfyUI/custom_nodes/ComfyUI_CHARON` (name is flexible but keep internal labels stable).

## Build, Test, and Development Commands
- Install deps inside the ComfyUI Python env: `pip install -r requirements.txt`.
- Smoke-test node import from the repo root (no ComfyUI needed): 
  ```bash
  python - <<'PY'
  import sys, pathlib; sys.path.insert(0, str(pathlib.Path('.').resolve()))
  import __init__ as plugin
  print("Loaded nodes:", list(plugin.NODE_CLASS_MAPPINGS))
  PY
  ```
- Run ComfyUI after placing this folder in `custom_nodes/`; watch the console for the `[ComfyUI_CHARON]` log line and ensure the nodes appear under `CHARON/3D`.

## Coding Style & Naming Conventions
- Python 3.10+, PEP 8 spacing (4-space indents), prefer explicit imports and small helpers for parsing/validation.
- Use type hints for function signatures where practical; raise `ValueError` for user-facing validation errors.
- Node classes should expose `INPUT_TYPES`, `RETURN_TYPES/RETURN_NAMES`, `FUNCTION`, `OUTPUT_NODE`, and `CATEGORY="CHARON/..."`. Keep node labels consistent with existing `CHARON_*` prefixing.
- Avoid broad exception swallowing; keep error messages actionable for ComfyUI users.

## Testing Guidelines
- No formal test suite yet; rely on smoke import (above) plus a quick ComfyUI graph: feed a mesh into `CHARON_3D_Auto_Align`, then pass its `transform_json` to `CHARON_Camera_From_DA3`.
- When adding math changes, validate with small matrices/meshes and compare against expected rotations/translations; add inline asserts in helpers if they reduce risk without hurting runtime.

## Commit & Pull Request Guidelines
- Use concise, imperative commit titles (e.g., `Add symmetry bucketing guard`); keep to ~72 chars and group related edits.
- In PRs, include: summary of behavior change, how you verified (commands/graph screenshots), and any DA3/mesh fixtures used. Link issues when applicable.
- Flag breaking changes to node names, inputs, or outputs clearly; include migration notes if users need to adjust saved workflows.

## Security & Configuration Tips
- Keep dependencies minimal; avoid adding heavy/binary libs unless required. Pin versions in `requirements.txt` when upgrading to stabilize ComfyUI installs.
- Do not bundle large assets or datasets; use temporary directories via `folder_paths.get_temp_directory()` for exports, as done in `auto_align`.
