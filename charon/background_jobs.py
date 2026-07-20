"""Small headless primitives for bounded background work."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass(frozen=True)
class BlockingJobResult:
    """Outcome of work executed on a bounded daemon thread."""

    completed: bool
    value: Any = None
    error: Optional[BaseException] = None

    @property
    def timed_out(self) -> bool:
        return not self.completed


def start_daemon_job(operation: Callable[[], Any], *, thread_name: str) -> threading.Thread:
    """Start named background work that cannot hold the host process open."""
    worker = threading.Thread(target=operation, name=thread_name, daemon=True)
    worker.start()
    return worker


def run_blocking_with_timeout(
    operation: Callable[[], Any],
    *,
    timeout: float,
    thread_name: str,
) -> BlockingJobResult:
    """Run blocking work without allowing it to stall the coordinator forever.

    Python cannot safely terminate an arbitrary blocking thread. Timed-out work
    therefore remains a daemon, matching the processor's historical behavior,
    while callers receive an explicit timeout outcome.
    """
    completed = threading.Event()
    state = {"value": None, "error": None}

    def runner() -> None:
        try:
            state["value"] = operation()
        except BaseException as exc:  # preserve worker failures for the caller
            state["error"] = exc
        finally:
            completed.set()

    worker = start_daemon_job(runner, thread_name=thread_name)
    if not completed.wait(timeout=max(0.0, float(timeout))):
        return BlockingJobResult(completed=False)
    return BlockingJobResult(
        completed=True,
        value=state["value"],
        error=state["error"],
    )
