import os
import urllib.request
import urllib.error
from typing import Iterable, Optional, Sequence

from .charon_logger import system_warning
from .path_safety import is_path_inside
from .paths import resolve_comfy_environment

DEFAULT_URL = "http://127.0.0.1:8188"
RESTART_SIGNAL_REBOOT = "reboot"
RESTART_SIGNAL_SHUTDOWN = "shutdown"


def process_matches_configured_paths(
    exe: str,
    cmdline: Sequence[str],
    candidates: Iterable[str],
) -> bool:
    """Return whether a process executable or absolute argument is under a configured path."""
    roots = [path for path in candidates if path]
    if not roots:
        return False
    for value in [exe, *(cmdline or [])]:
        raw_value = str(value or "").strip().strip('"')
        if raw_value.startswith("--") and "=" in raw_value:
            raw_value = raw_value.split("=", 1)[1].strip().strip('"')
        if not raw_value or not os.path.isabs(raw_value):
            continue
        if any(is_path_inside(raw_value, root) for root in roots):
            return True
    return False


def send_shutdown_signal(base_url: str = DEFAULT_URL, *, allow_manager_reboot: bool = True) -> bool:
    """
    Best-effort shutdown/restart request to a running ComfyUI instance.
    Mirrors the logic used by Comfy connection UI and validation flows.
    """
    endpoints = [
        ("POST", f"{base_url}/system/shutdown"),
        ("POST", f"{base_url}/shutdown"),
        ("GET", f"{base_url}/system/shutdown"),
        ("GET", f"{base_url}/shutdown"),
    ]
    if allow_manager_reboot:
        endpoints.append(("GET", f"{base_url}/manager/reboot"))
    last_error = None
    for method, url in endpoints:
        try:
            req = urllib.request.Request(url, method=method)
            with urllib.request.urlopen(req, timeout=5):
                return True
        except urllib.error.HTTPError as exc:  # pragma: no cover - defensive
            # 404/405 just mean the endpoint isn't supported; try next.
            if exc.code in (404, 405):
                continue
            last_error = exc
        except Exception as exc:  # pragma: no cover - defensive
            last_error = exc
            msg = str(exc).lower()
            # Manager reboot may close the connection early; treat connection reset as success.
            if "/manager/reboot" in url and (
                "connection reset" in msg or "forcibly closed" in msg
            ):
                return True
            continue
    if last_error and not (
        isinstance(last_error, urllib.error.HTTPError) and last_error.code in (404, 405)
    ):
        system_warning(f"ComfyUI shutdown request failed: {last_error}")
    return False


def request_restart_signal(base_url: str = DEFAULT_URL) -> Optional[str]:
    """
    Request a restart and report whether ComfyUI will reboot itself.

    ComfyUI Manager's reboot endpoint is preferred because it owns the relaunch.
    If it is unavailable, fall back to shutdown and let Charon launch the
    configured instance after the process exits.
    """
    reboot_url = f"{base_url}/manager/reboot"
    try:
        req = urllib.request.Request(reboot_url, method="GET")
        with urllib.request.urlopen(req, timeout=5):
            return RESTART_SIGNAL_REBOOT
    except urllib.error.HTTPError as exc:
        if exc.code not in (404, 405):
            system_warning(f"ComfyUI Manager reboot request failed: {exc}")
    except Exception as exc:  # pragma: no cover - defensive
        msg = str(exc).lower()
        if "connection reset" in msg or "forcibly closed" in msg:
            return RESTART_SIGNAL_REBOOT

    if send_shutdown_signal(base_url, allow_manager_reboot=False):
        return RESTART_SIGNAL_SHUTDOWN
    return None


def shutdown_or_kill(comfy_path: Optional[str] = None, base_url: str = DEFAULT_URL) -> bool:
    """
    Try graceful shutdown; if that fails, terminate processes under the configured ComfyUI path.
    Mirrors the ComfyConnectionWidget restart/terminate behavior.
    """
    if send_shutdown_signal(base_url):
        return True

    # Fallback: best-effort process kill using psutil if available.
    try:
        import psutil  # type: ignore
    except Exception:
        return False

    try:
        comfy_env = resolve_comfy_environment(comfy_path or "")
        comfy_dir = comfy_env.get("comfy_dir") or ""
        base_dir = comfy_env.get("base_dir") or ""
        candidates = {c for c in (comfy_dir, base_dir) if c}

        killed = False
        for proc in psutil.process_iter(["pid", "exe", "cmdline"]):
            try:
                exe = proc.info.get("exe") or ""
                cmdline = proc.info.get("cmdline") or []
                if process_matches_configured_paths(exe, cmdline, candidates):
                    proc.terminate()
                    killed = True
            except Exception:
                continue
        return killed
    except Exception:
        return False
