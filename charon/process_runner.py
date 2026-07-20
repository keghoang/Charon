from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence


@dataclass(frozen=True)
class ProcessResult:
    command: Sequence[str]
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False

    def tail(self, limit: int = 4000) -> str:
        combined = "\n".join(part for part in (self.stdout, self.stderr) if part)
        return combined[-limit:]


class ProcessExecutionError(RuntimeError):
    def __init__(self, message: str, result: ProcessResult):
        super().__init__(message)
        self.result = result


def format_command(command: Sequence[str]) -> str:
    return " ".join(str(part) for part in command)


def run_subprocess(
    command: Sequence[str],
    *,
    cwd: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
    timeout: Optional[float] = None,
    check: bool = False,
) -> ProcessResult:
    """Run a subprocess with captured output and deterministic timeout handling."""
    started = time.monotonic()
    try:
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            env=dict(env) if env is not None else None,
            timeout=timeout,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        result = ProcessResult(
            command=list(command),
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            duration_seconds=time.monotonic() - started,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        result = ProcessResult(
            command=list(command),
            returncode=-1,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=time.monotonic() - started,
            timed_out=True,
        )
        raise ProcessExecutionError(
            f"Process timed out after {timeout} seconds: {format_command(command)}",
            result,
        ) from exc

    if check and result.returncode != 0:
        detail = result.tail()
        suffix = f"\n{detail}" if detail else ""
        raise ProcessExecutionError(
            f"Process failed with exit code {result.returncode}: {format_command(command)}{suffix}",
            result,
        )
    return result
