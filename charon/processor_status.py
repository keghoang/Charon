from __future__ import annotations

import time
import json
import threading
from typing import Any, Callable, Dict, List, Optional


class StatusPayloadRepository:
    """Persist structured processor status through a Nuke node and fallback knob."""

    def __init__(
        self,
        node,
        status_knob,
        *,
        write_metadata: Callable[[str, str], bool],
        log_warning: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._node = node
        self._status_knob = status_knob
        self._write_metadata = write_metadata
        self._log_warning = log_warning

    def load(self) -> Dict[str, Any]:
        raw = None
        try:
            raw = self._node.metadata("charon/status_payload")
        except Exception:
            pass
        if not raw and self._status_knob is not None:
            try:
                raw = self._status_knob.value()
            except Exception:
                raw = None
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def save(self, payload: Dict[str, Any]) -> None:
        serialized = json.dumps(payload)
        self._write_metadata("charon/status_payload", serialized)
        if self._status_knob is None:
            return
        try:
            self._status_knob.setValue(serialized)
        except Exception as exc:
            if self._log_warning:
                self._log_warning(f"Failed to store status payload knob: {exc}")

    @staticmethod
    def ensure_history(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        runs = payload.get("runs")
        if not isinstance(runs, list):
            runs = []
        payload["runs"] = runs
        return runs


class ProcessorStatusController:
    """Own progress dispatch, lifecycle state, colors, and durable status updates."""

    def __init__(
        self,
        node,
        nuke_module,
        repository: StatusPayloadRepository,
        *,
        run_id: str,
        run_started_at: float,
        resolve_auto_import,
        update_last_output,
        apply_status_color,
        log_debug,
        initial_state: str = "Ready",
    ) -> None:
        self._node = node
        self._nuke = nuke_module
        self._repository = repository
        self._run_id = run_id
        self._run_started_at = run_started_at
        self._resolve_auto_import = resolve_auto_import
        self._update_last_output = update_last_output
        self._apply_status_color = apply_status_color
        self._log_debug = log_debug
        self.current_state = initial_state
        self._last_color_state = initial_state

    def update(self, progress, status="Processing", error=None, extra=None) -> str:
        try:
            numeric_progress = float(progress)
        except Exception:
            numeric_progress = 0.0
        clamped_progress = max(-1.0, min(numeric_progress, 1.0))
        if clamped_progress >= 0.999:
            clamped_progress = 1.0

        if threading.current_thread() is not threading.main_thread():
            safe_extra = dict(extra) if isinstance(extra, dict) else extra
            try:
                self._nuke.executeInMainThread(
                    lambda: self.update(clamped_progress, status, error, safe_extra)
                )
            except Exception as exc:
                try:
                    self._log_debug(
                        f"Failed to dispatch progress update to main thread: {exc}",
                        "WARNING",
                    )
                except Exception:
                    pass
            return self.current_state

        try:
            self._node.knob("charon_progress").setValue(clamped_progress)
            self._node.knob("charon_status").setValue(status)
        except Exception:
            pass

        lifecycle = lifecycle_from_progress(clamped_progress, status)
        self.current_state = lifecycle
        if lifecycle != self._last_color_state:
            self._last_color_state = lifecycle
            self._apply_status_color(lifecycle)

        payload = self._repository.load()
        if isinstance(extra, dict) and "output_path" in extra:
            self._update_last_output(extra.get("output_path"))
        if lifecycle == "Error":
            self._update_last_output(None)
        payload = update_status_payload(
            payload,
            lifecycle=lifecycle,
            message=status,
            progress=clamped_progress,
            run_id=self._run_id,
            run_started_at=self._run_started_at,
            auto_import=self._resolve_auto_import(),
            extra=extra,
            error=error,
        )
        self._repository.save(payload)
        self._log_debug(f"Updated progress: {clamped_progress:.1%} - {status}")
        return lifecycle


def initialize_status_payload(
    payload: Dict[str, Any],
    *,
    message: str,
    run_id: str,
    run_started_at: float,
    auto_import: bool,
) -> Dict[str, Any]:
    """Initialize a processor run while retaining valid prior run history."""
    initialized = dict(payload or {})
    runs = initialized.get("runs")
    if not isinstance(runs, list):
        runs = []
    current_run = {
        "id": run_id,
        "status": "Processing",
        "message": message,
        "progress": 0.0,
        "started_at": run_started_at,
        "updated_at": run_started_at,
        "auto_import": auto_import,
    }
    initialized.update(
        {
            "status": message,
            "state": "Processing",
            "message": message,
            "progress": 0.0,
            "run_id": run_id,
            "started_at": run_started_at,
            "updated_at": run_started_at,
            "auto_import": auto_import,
            "current_run": current_run,
            "runs": runs,
        }
    )
    return initialized


def lifecycle_from_progress(progress: float, status: str) -> str:
    """Map numeric progress and status text to a Charon node lifecycle."""
    normalized = (status or "").lower()
    if progress < 0 or normalized.startswith("error"):
        return "Error"
    if progress >= 0.999:
        return "Completed"
    return "Processing"


def update_status_payload(
    payload: Dict[str, Any],
    *,
    lifecycle: str,
    message: str,
    progress: float,
    run_id: str,
    run_started_at: float,
    auto_import: bool,
    extra: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Apply one processing status update without touching Nuke state."""
    updated = dict(payload or {})
    runs = updated.get("runs")
    if not isinstance(runs, list):
        runs = []
    current_run = updated.get("current_run")
    if not isinstance(current_run, dict) or current_run.get("id") != run_id:
        current_run = {"id": run_id, "started_at": run_started_at}
    else:
        current_run = dict(current_run)
    timestamp = time.time() if now is None else now
    current_run.update(
        {
            "status": lifecycle,
            "message": message,
            "progress": progress,
            "updated_at": timestamp,
            "auto_import": auto_import,
        }
    )
    if isinstance(extra, dict):
        current_run.update(extra)
    if lifecycle == "Completed":
        current_run["completed_at"] = timestamp
    if error:
        current_run["error"] = error

    updated.update(
        {
            "status": message,
            "state": lifecycle,
            "message": message,
            "progress": progress,
            "run_id": run_id,
            "updated_at": timestamp,
            "current_run": current_run,
            "auto_import": auto_import,
        }
    )
    if isinstance(extra, dict):
        updated.update(extra)
    if error:
        updated["last_error"] = error

    if lifecycle in {"Completed", "Error"}:
        summary = {
            "id": run_id,
            "status": lifecycle,
            "message": message,
            "progress": progress,
            "started_at": current_run.get("started_at", run_started_at),
            "completed_at": current_run.get("completed_at", timestamp),
            "error": current_run.get("error"),
            "auto_import": auto_import,
        }
        for key in ("output_path", "elapsed_time", "prompt_id"):
            if key in current_run:
                summary[key] = current_run[key]
        runs.append(summary)
        updated["runs"] = runs[-10:]
        updated.pop("current_run", None)
    else:
        updated["runs"] = runs
        updated["current_run"] = current_run
    return updated
