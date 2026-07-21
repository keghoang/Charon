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

After Read/ReadGeo lifecycle and remaining context helper extraction: 148 tests
passed; compile and diff checks passed. The processor coordinator is 2,864 lines
with nine direct closures remaining.

After status-controller, result-watcher protocol, grouped Read indexing, and
placeholder cleanup extraction: 157 tests passed; compile and diff checks
passed. The processor coordinator is 2,730 lines with eight direct closures
remaining.

After result cleanup/contact-sheet policy, upload-input assignment, and recursive
completion extraction: 163 tests passed; compile and diff checks passed. The
processor coordinator is 2,615 lines. The 829-line worker has no internal
closures; output ingestion has only the inverse-view-transform transaction left
as an internal closure.

After browser-conversion startup and source-identity hardening: 167 tests passed;
compile and diff checks passed. A live conversion of
`mab/ltx_ff2v_static_camera/workflow.json` produced 54 API nodes, retained all
four parameter IDs, and exported node `75` as `SaveVideo`.

After repairing the output-label sanitizer wiring discovered in live Nuke
ingestion: 168 tests passed; compile and diff checks passed. The deployed MP4
completed successfully; the missing Read was traced to the retired
`_sanitize_name` callback rather than output generation or media support.

After restoring the extracted batch-navigation compatibility hook and making
Read identity/anchor persistence independent of optional presentation
callbacks: 170 tests passed; compile and diff checks passed. Live Nuke
re-import loaded the deployed H.264 MP4 and displayed its thumbnail. The blank
Read was caused by a `NameError` before file assignment; the same exception had
also prevented the parent ID, link anchor, label, and lifecycle colors from
being applied.

After routing 2D Read assignments through Nuke's native `fromUserText` parser
and restoring the built-in Read tab after Charon metadata controls are added:
172 tests passed; compile and diff checks passed. This keeps movie frame ranges
consistent with drag/drop imports and prevents the custom Charon Info tab from
becoming the initial control-panel tab.

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
- Read label/info rendering, link/unlink transactions, placeholder protection,
  output-name sanitation, node-coordinate capture, and workflow-folder resolution
- result-manifest readiness and schema checks, legacy/batched result
  normalization, newest-entry import caps, grouped Read-node indexing, and
  linked-placeholder removal
- consumed-manifest cleanup with debug-file preservation, contact-sheet dispatch,
  uploaded-input socket assignment, and recursive next-run/disabled behavior
- browser-export source node/type identity, stale prompt-cache rejection, and
  protection against ComfyUI startup overwriting a requested workflow

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
