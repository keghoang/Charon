# Verification Record

## Automated baseline

Recorded 2026-07-20 after the documentation, safe cleanup, and validation-path
foundation passes:

```powershell
python -m unittest discover -s tests
python -m compileall -q charon custom_nodes packaging main.py
git diff --check
```

Initial result: 61 tests passed; compile and diff checks passed.

After the ComfyEnvironment and validation-repository architecture slice:
71 tests passed; compile and diff checks passed.

After the first processor recovery-policy extraction:
74 tests passed; compile and diff checks passed.

After bounded-job, history-recovery, processor-input, and initial Nuke 3D
extractions: 88 tests passed; compile and diff checks passed.

After the Nuke script/resource migration, status and prompt-cache repositories,
and named daemon-job policy: 100 tests passed; compile and diff checks passed.

After typed cache selection, shared result manifests, execution tracing,
main-thread dispatch, and node-link identity helpers: 123 tests passed; compile
and diff checks passed. `CharonWindow` is 3,153 class lines; the processor
coordinator is 3,788 lines.

After full node-identity consolidation, crop/context extraction, and the shared
metadata writer: 134 tests passed; compile and diff checks passed. The processor
coordinator is 3,419 lines.

After linked-read repository and status-color adapter extraction: 139 tests
passed; compile and diff checks passed. The processor coordinator is 3,183 lines
with 13 direct closures remaining (down from 87 nested functions at evaluation).

Regression coverage now includes:

- portable launcher, portable root, `ComfyUI/models`, and embedded Python path
  resolution
- validation using the resolved models root without creating `models/models`
- model category-prefix and workflow-value normalization
- simple-name versus subfolder workflow references
- custom ComfyUI endpoint propagation into browser validation
- validation invalidation when the configured ComfyUI endpoint changes
- validation timestamp serialization
- queue-aware processor timeout calculation
- basename and prefix-based local output recovery/classification
- bounded background-job completion, error, and timeout outcomes
- cached-history output recovery by prompt identity and filename prefix
- crop-box normalization independent of Nuke
- Nuke template parsing, DAG-center fallback, and coverage-group construction
- embedded Nuke callback syntax, packaged camera-rig lookup, and error reporting
- status payload metadata/knob fallback and history normalization
- converted-prompt hash/path persistence, including unavailable host metadata
- named daemon worker launch behavior
- typed converted-prompt cache selection and stale/missing cache invalidation
- result-manifest allocation and atomic JSON publication
- ordered execution trace formatting and runtime debug-path allocation
- timeout-bounded Nuke main-thread callback dispatch
- node auto-import precedence and immutable parameter-context capture
- node ID/script-hash normalization, linked-output discovery, parent migration,
  and anchor/contact-sheet repair through fake-Nuke contracts
- duplicate-ID keeper selection, script-hash identity migration, linked-ID
  display refresh, batch/script context, link-anchor initialization, and
  one-warning host metadata writes
- linked Read/ReadGeo lookup precedence, parent-target collection, and lifecycle
  color/metadata propagation

## Manual verification still required

These checks require the production Windows/Nuke/PySide/ComfyUI environment and
were not simulated by the headless test suite:

1. Grab the workflow, execute it, and confirm status transitions from Ready to
   Processing to Completed.
2. Confirm resolved model overrides retain the workflow's original filename or
   subfolder shape.
3. Verify the configured non-default ComfyUI endpoint if the deployment does
   not use `127.0.0.1:8188`.

Production confirmation received 2026-07-20: validation of
`mab/ltx_ff2v_static_camera` succeeds with the deployed LTX models.

GUI geometry, focus, high-DPI, and visual consistency verification is deferred
until the final GUI foundation and polish phases.
