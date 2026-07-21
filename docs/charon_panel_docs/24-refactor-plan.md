# Refactor Plan

## Constraints

- Preserve current artist-visible behavior unless a change is explicitly
  documented and approved.
- Keep each phase independently testable and reversible.
- Add characterization tests before moving high-risk Nuke or processor logic.
- Do not combine broad architecture changes with visual redesign.

## Phase 1: Documentation

- Maintain architecture boundaries, state/storage, GUI system, and component map.
- Mark historical documents as non-authoritative.
- Record manual Nuke smoke-test results for each release candidate.

Exit condition: a new developer can identify the source of truth and correct
module for workflow, validation, execution, UI, and storage changes.

## Phase 2: Safe cleanup

- Remove verified-unreferenced modules and tracked runtime artifacts.
- Remove duplicate definitions and layout blocks.
- Align product naming, version metadata, shortcuts, and host support.
- Retain uncertain Nuke assets until an explicit runtime/package check exists.

## Phase 3: Validation and environment foundation

- Extract model-path and validation rules from dialogs into headless services.
- Introduce one canonical ComfyUI environment identity.
- Accept portable root, launcher, ComfyUI, models, and embedded-Python paths.
- Add deployment-layout and model-resolution regression tests.

## Phase 4: Architecture cleanup

- Extract 3D tools from the application window.
- Replace processor nested functions with phase services and a run context.
- Consolidate caches and background-job ownership.
- Keep Nuke and Qt mutations behind explicit adapters.

Current progress (2026-07-20): 3D Nuke operations, callback scripts, and camera
rig resources are outside `CharonWindow`. Processor recovery, prompt conversion,
status/cache persistence, output manifest publication/readback, tracing, worker
launch, main-thread dispatch, and Read/ReadGeo lifecycle rules have named modules
and headless tests.
Duplicate-node identity policy is now behind fake-Nuke contract tests. Output
lookup and status propagation are also behind a linked-output repository and
fake-Nuke tests. Recursive completion is now an explicit Nuke adapter, and the
worker has no internal closures. Output ingestion plus the worker and watcher
thread bodies remain the largest coordinator sections. Browser conversion now
waits for ComfyUI frontend startup to settle and rejects exports or cached
prompts that do not match the requested UI workflow.

## Phase 5: Operational hardening

- Add structured execution and validation diagnostics.
- Add fake Nuke API contract tests and live Nuke smoke-test checklists.
- Verify local-storage invalidation after environment and model changes.
- Document failure recovery for portable deployments.

## Phase 6: GUI foundation (deferred)

- Add shared tokens, theme construction, and reusable primitives.
- Migrate validation, first-time setup, and model upload dialogs first.
- Add Qt screenshot or geometry tests in a supported PySide environment.

## Phase 7: UI polish (last priority)

- Normalize hierarchy around Browse, Validate, Grab, Execute, and Monitor.
- Remove obsolete affordances and hidden-panel remnants.
- Verify high DPI, narrow layouts, long strings, keyboard focus, and errors.

## Longer-term improvements

- Typed domain models and adapter protocols.
- Dependency-injected application context.
- Structured execution events and durable run diagnostics.
- Fake Nuke API contract tests and live Nuke integration smoke tests.
