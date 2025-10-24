# Charon Testing Guide

Charon's automated checks are organised into tiers so you can run the right amount of coverage for the task at hand.

## Fast reference

| Tier | Command | What it covers |
|------|---------|----------------|
| `unit` | `python tools/run_tests.py --tier unit` | Pure-Python helpers, metadata utilities, validators |
| `headless` | `python tools/run_tests.py --tier headless` | Qt-backed execution paths that can run without showing windows |
| `scenario` | `python tools/run_tests.py --tier scenario` | Fixture-based smoke flows that resemble how artists launch scripts |
| `all` | `python tools/run_tests.py --tier all` | Runs every tier sequentially |

Running a tier prints a short success/failure summary so you can paste results directly into a code review or chat.

## Fixtures

Sample repositories live under `tests/fixtures/scripts/` and are shared across tiers:

- `background_python/` exercises background execution and stdout capture.
- `main_thread_qt/` verifies Qt widgets run safely on the main thread.
- `no_metadata_script/` ensures default metadata is created when `.charon.json` is missing.
- `bad_entry_script/` intentionally references a missing entry file so validators report the failure.

When you need another scenario, add it to this directory and reuse it from multiple tests rather than creating bespoke data per module.

## Writing new tests

### Unit tests (`tests/unit/`)
- Use `unittest.TestCase`.
- Copy fixture scripts into a temporary directory before mutating them (`tempfile.mkdtemp` + `shutil.copytree`).
- Clear metadata caches (`metadata_manager.clear_metadata_cache()`) between tests to avoid cross-test pollution.

### Headless UI tests (`tests/headless_ui/`)
- Always create or reuse a `QApplication` via `QtWidgets.QApplication.instance()`.
- Use a `QEventLoop` or `QSignalSpy` to wait for asynchronous completions from the execution engine.
- Keep timeouts short (2–3 seconds) and bail with a clear assertion message if the signal never arrives.

### Scenario tests (`tests/scenario/`)
- Treat these as smoke tests: load fixtures with `utilities.load_scripts_for_folder`, invoke the execution engine, or validate tag/metadata aggregation.
- If you need UI confirmation, stop at a deterministic state and document a manual checklist in `tests/manual/` so a human can finish the verification.

## Manual assistance

Some interactions (window docking inside Maya, tiny-mode resizing, platform theming) still need a human. Keep short, ordered instructions in `tests/manual/` and reference them from `AGENTS.md` so you know exactly what to request.

## Troubleshooting

- **Qt crashes**: ensure `QT_QPA_PLATFORM=offscreen` is set (the test runner handles this automatically).
- **Stuck event loop**: check that you quit the `QEventLoop` on both success and timeout paths.
- **Cache leakage**: clear caches between tests when copying fixtures or adjusting metadata.

Happy testing!
