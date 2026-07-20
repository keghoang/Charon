# Architecture Boundaries

## Purpose
This document defines the intended dependency direction for Charon. It is a
target for incremental refactoring, not a claim that every current module
already follows these boundaries.

## Layer Model

### Domain
Pure workflow, validation, execution-state, and output concepts. Domain code
must not import Qt, Nuke, subprocess, HTTP, or local storage.

Examples:
- workflow metadata and bundle value objects
- validation results and model references
- execution phases and lifecycle states
- output artifact descriptions

### Application
Coordinates use cases through explicit services. Application code may depend
on domain types and adapter interfaces, but not concrete Qt widgets or direct
Nuke calls.

Examples:
- load and validate a workflow
- resolve a missing model
- spawn a CharonOp
- execute and monitor a workflow run

### Infrastructure
Implements external boundaries:
- ComfyUI HTTP, browser, and process control
- Nuke scene and knob access
- workflow repository and local mirror storage
- JSON preferences, SQLite settings, and caches
- filesystem and subprocess execution

### Presentation
Qt widgets, delegates, models, view state, and user interaction. Presentation
may call application services and render domain results. It must not implement
model-path rules, mutate validation files directly, or contain Nuke algorithms.

## Dependency Direction

```text
Presentation -> Application -> Domain
                    |
                    v
             Adapter interfaces
                    ^
                    |
              Infrastructure
```

Infrastructure is supplied to application services. Domain code never imports
upward. Cross-feature communication should use application commands or typed
events rather than reaching through widget attributes.

## Current Transitional Modules

- `workflow_runtime.py` is the closest current application facade.
- `workflow_local_store.py`, `preferences.py`, and `settings/user_settings_db.py`
  are infrastructure stores.
- `comfy_client.py`, `workflow_browser_exporter.py`, and setup/process helpers
  are ComfyUI infrastructure.
- `model_paths.py` owns pure model-reference normalization and path-to-workflow
  conversion rules. Qt code must delegate to it instead of duplicating them.
- `paths.resolve_comfy_environment()` is the canonical filesystem environment
  resolver for launchers, portable roots, ComfyUI roots, model roots, and the
  embedded Python executable.
- `comfy_environment.py` binds the filesystem projection to the configured HTTP
  endpoint. Runtime consumers should resolve this identity instead of reading
  preferences and constants independently.
- `validation_repository.py` owns signature-aware validation state reads and
  transient caching; presentation code only projects its results.
- `node_factory.py` and `scene_nodes_runtime.py` are Nuke infrastructure.
- `processor.py` currently combines application coordination and Nuke
  infrastructure. Recovery, input normalization, prompt-cache persistence,
  status persistence, submission, and bounded background-job policy have moved
  behind named helpers; remaining Nuke mutations should be split by phase.
- `nuke_3d_tools.py`, `nuke_3d_scripts.py`, and packaged `.nk` resources own
  Nuke-specific 3D behavior. `ui/main_window.py` now retains only command
  dispatch and error presentation for those tools.

## Change Rules

1. New filesystem, network, Nuke, or subprocess behavior goes behind a named
   adapter or service.
2. New UI state must have one owner and an explicit idle/loading/success/error
   model.
3. A dialog may collect input and render results; it must not become the only
   implementation of a business rule.
4. Configuration is passed as an immutable context where practical. Avoid new
   mutable module globals.
5. Every extraction preserves behavior and adds characterization tests before
   changing policy.
