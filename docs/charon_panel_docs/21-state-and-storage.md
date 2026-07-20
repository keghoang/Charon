# State and Storage

## Sources of Truth

| State | Authoritative source | Cached or projected copies |
|---|---|---|
| Shared workflow | Approved workflow repository | Local workflow mirror |
| Workflow metadata | `.charon.json` in shared workflow folder | Metadata LRU and persistent cache |
| Validated workflow | Per-user `workflow_validated.json` | CharonOp embedded workflow payload |
| Validation result | Per-workflow local validation status | `ScriptTableModel` state and preferences cache |
| ComfyUI configuration | `comfyui_launch_path` preference | Derived `ComfyEnvironment` paths |
| User settings | SQLite `settings.db` | Widget state |
| Lightweight preferences | `preferences.json` | In-memory values read by widgets/services |
| Run state | CharonOp knobs and status payload | CharonBoard and Tiny Mode projections |
| Output artifacts | Allocated result/project folders | `charon_last_output` and scene Read nodes |

## Storage Roots

### Shared repository
`config.WORKFLOW_REPOSITORY_ROOT` is read-only during normal browsing and
execution. Creation and publication are explicit authoring operations.

### Per-user workflow mirror
Rooted beneath `preferences.get_preferences_root()`:

```text
Charon_repo_local/workflow/<relative workflow path>/
    workflow.json
    workflow_validated.json
    .charon_cache/
        workflow_state.json
        validation/
```

### Runtime artifacts
Managed by `paths.py`. `CHARON_RUNTIME_ROOT` overrides the studio default;
otherwise an inaccessible default falls back to `%LOCALAPPDATA%/Charon/runtime`.

### ComfyUI environment identity
`paths.resolve_comfy_environment()` returns the canonical filesystem projection:

- `configured_path`: the exact normalized user/deployment input
- `base_dir`: the portable launcher root when one exists
- `comfy_dir`: the directory containing ComfyUI
- `models_dir`: the model root used by validation and cache invalidation
- `python_exe` and `embedded_root`: the portable Python runtime

Callers must consume these fields instead of rebuilding `ComfyUI/models` from
the configured string. Supported inputs include a launcher batch file, portable
root, `ComfyUI` directory, `ComfyUI/models` directory, and embedded `python.exe`.

## State Ownership Rules

1. Widgets may cache display state but cannot become the durable source of
   workflow or validation truth.
2. Local validation writes flow through `workflow_local_store.py`.
3. Nuke knob updates flow through Nuke adapter helpers on the main thread.
4. Cache entries require a documented key, lifetime, invalidation event, and
   authoritative reload path.
5. A configured ComfyUI launcher, derived paths, and active HTTP server must be
   represented and validated as one environment identity.
6. Presentation code accesses validation state through
   `WorkflowValidationRepository`; it does not own signature or durable-load
   policy.

## Invalidation Events

- Shared workflow hash changes: invalidate validated override and validation
  status for that workflow.
- `.charon.json` changes: invalidate metadata and folder/tag projections.
- ComfyUI launch path changes: invalidate environment and validation caches.
- Model resolution changes: refresh model validation and persist the resulting
  workflow override.
- CharonOp status changes: refresh CharonBoard/Tiny Mode projections without
  rescanning the workflow repository.
