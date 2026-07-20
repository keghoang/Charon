"""Structured step tracing for processor runs."""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass
from typing import Callable, Optional

from .paths import _normalize_charon_root, get_charon_temp_dir


@dataclass
class ExecutionTrace:
    """Emit ordered execution steps to the logger and an optional trace file."""

    enabled: bool
    log_debug: Callable[[str], None]
    log_path: str = ""
    step: int = 0

    def emit(self, message: str, **fields) -> None:
        if not self.enabled:
            return
        self.step += 1
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        line = f"[{timestamp}] step={self.step:04d} {message}"
        if fields:
            serialized = ", ".join(f"{key}={fields[key]}" for key in sorted(fields))
            if serialized:
                line = f"{line} | {serialized}"
        try:
            self.log_debug(f"[STEP] {line}")
        except Exception:
            pass
        if not self.log_path:
            return
        try:
            with open(self.log_path, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except Exception:
            pass


def create_execution_trace(
    temp_root: str,
    node_id: str,
    *,
    enabled: bool,
    log_debug: Callable[[str], None],
    timestamp: Optional[int] = None,
    trace_id: Optional[str] = None,
) -> ExecutionTrace:
    """Create a trace with a deployment-safe path under the runtime debug root."""
    if not enabled:
        return ExecutionTrace(enabled=False, log_debug=log_debug)
    try:
        debug_root = get_charon_temp_dir(temp_root)
    except Exception:
        debug_root = _normalize_charon_root(temp_root)
        try:
            os.makedirs(debug_root, exist_ok=True)
            for subdirectory in ("temp", "exports", "results", "debug"):
                os.makedirs(os.path.join(debug_root, subdirectory), exist_ok=True)
        except Exception:
            pass
    debug_dir = os.path.join(debug_root, "debug")
    try:
        os.makedirs(debug_dir, exist_ok=True)
    except Exception:
        pass
    current_timestamp = int(time.time()) if timestamp is None else int(timestamp)
    unique_id = (trace_id or str(uuid.uuid4()))[:8]
    filename = f"charon_step_trace_{current_timestamp}_{node_id or 'unknown'}_{unique_id}.log"
    log_path = os.path.join(debug_dir, filename).replace("\\", "/")
    return ExecutionTrace(enabled=True, log_debug=log_debug, log_path=log_path)
