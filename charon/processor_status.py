from __future__ import annotations

import time
from typing import Any, Dict, Optional


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
