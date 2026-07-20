from __future__ import annotations

import threading
from typing import Any, Callable, TypeVar


T = TypeVar("T")


def is_main_thread() -> bool:
    return threading.current_thread() is threading.main_thread()


def run_on_main_thread(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """
    Execute func through Nuke's main-thread dispatcher when available.

    Outside Nuke, or when already on the Python main thread, this executes
    directly so helper code remains testable.
    """
    if is_main_thread():
        return func(*args, **kwargs)

    try:
        import nuke  # type: ignore
    except Exception:
        return func(*args, **kwargs)

    if hasattr(nuke, "executeInMainThreadWithResult"):
        return nuke.executeInMainThreadWithResult(lambda: func(*args, **kwargs))
    if hasattr(nuke, "executeInMainThread"):
        holder = {"value": None, "error": None}

        def _wrapped() -> None:
            try:
                holder["value"] = func(*args, **kwargs)
            except Exception as exc:  # pragma: no cover - requires Nuke host
                holder["error"] = exc

        nuke.executeInMainThread(_wrapped)
        if holder["error"] is not None:
            raise holder["error"]
        return holder["value"]  # type: ignore[return-value]
    return func(*args, **kwargs)


def run_on_main_thread_async(func: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
    """Schedule func on Nuke's main thread when possible; otherwise run directly."""
    if is_main_thread():
        func(*args, **kwargs)
        return

    try:
        import nuke  # type: ignore
    except Exception:
        func(*args, **kwargs)
        return

    if hasattr(nuke, "executeInMainThread"):
        nuke.executeInMainThread(lambda: func(*args, **kwargs))
    else:
        func(*args, **kwargs)


def run_on_nuke_main_thread_blocking(
    callback: Callable[[], T],
    *,
    nuke_module,
    label: str,
    timeout: float = 120.0,
) -> T:
    """Dispatch through Nuke and wait for completion with an explicit timeout."""
    try:
        execute_with_result = getattr(nuke_module, "executeInMainThreadWithResult", None)
    except Exception:
        execute_with_result = None
    if callable(execute_with_result):
        return execute_with_result(callback)

    completed = threading.Event()
    state = {"value": None, "error": None}

    def wrapped() -> None:
        try:
            state["value"] = callback()
        except Exception as exc:
            state["error"] = exc
        finally:
            completed.set()

    nuke_module.executeInMainThread(wrapped)
    if not completed.wait(timeout=max(0.0, float(timeout))):
        raise TimeoutError(f"Timed out waiting for main-thread callback: {label}")
    if state["error"] is not None:
        raise state["error"]
    return state["value"]  # type: ignore[return-value]
