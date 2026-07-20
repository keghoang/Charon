# Verification Record

## Automated baseline

Recorded 2026-07-20 after the documentation, safe cleanup, and validation-path
foundation passes:

```powershell
python -m unittest discover -s tests
python -m compileall -q charon custom_nodes packaging main.py
git diff --check
```

Result: 61 tests passed; compile and diff checks passed.

Regression coverage now includes:

- portable launcher, portable root, `ComfyUI/models`, and embedded Python path
  resolution
- validation using the resolved models root without creating `models/models`
- model category-prefix and workflow-value normalization
- simple-name versus subfolder workflow references
- custom ComfyUI endpoint propagation into browser validation
- validation timestamp serialization

## Manual verification still required

These checks require the production Windows/Nuke/PySide/ComfyUI environment and
were not simulated by the headless test suite:

1. Configure Charon with the production launcher and separately with
   `D:\ComfyUI_windows_portable_nvidia\ComfyUI_windows_portable\ComfyUI\models`.
2. Validate the `mab/ltx_ff2v_static_camera` workflow and confirm installed LTX
   models resolve from the expected ComfyUI category directories.
3. Grab the workflow, execute it, and confirm status transitions from Ready to
   Processing to Completed.
4. Confirm resolved model overrides retain the workflow's original filename or
   subfolder shape.
5. Verify the configured non-default ComfyUI endpoint if the deployment does
   not use `127.0.0.1:8188`.

GUI geometry, focus, high-DPI, and visual consistency verification is deferred
until the final GUI foundation and polish phases.
