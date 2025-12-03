import urllib.request
import urllib.error
from urllib.parse import urlparse
from typing import Optional

from .charon_logger import system_warning
from .paths import resolve_comfy_environment

DEFAULT_URL = "http://127.0.0.1:8188"


def send_shutdown_signal(base_url: str = DEFAULT_URL) -> bool:
    """
    Best-effort shutdown/restart request to a running ComfyUI instance.
    Mirrors the logic used by Comfy connection UI and validation flows.
    """
    endpoints = [
        ("POST", f"{base_url}/system/shutdown"),
        ("POST", f"{base_url}/shutdown"),
        ("GET", f"{base_url}/system/shutdown"),
        ("GET", f"{base_url}/shutdown"),
        ("GET", f"{base_url}/manager/reboot"),
    ]
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


def shutdown_or_kill(comfy_path: Optional[str] = None, base_url: str = DEFAULT_URL) -> bool:
    """
    Try graceful shutdown; if that fails, attempt to kill ComfyUI processes by path/port.
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
        port_hint = urlparse(base_url).port or 8188
        name_hints = {"comfyui", "comfy_ui"}

        killed = False
        for proc in psutil.process_iter(["pid", "name", "exe", "cmdline", "connections"]):
            try:
                exe = proc.info.get("exe") or ""
                name = (proc.info.get("name") or "").lower()
                cmdline = proc.info.get("cmdline") or []
                # Match by known paths
                if candidates:
                    if any(str(path) and str(path) in exe for path in candidates):
                        proc.terminate()
                        killed = True
                        continue
                    if any(any(str(path) in (arg or "") for path in candidates) for arg in cmdline):
                        proc.terminate()
                        killed = True
                        continue
                # Match by name/port hints
                if any(hint in name for hint in name_hints):
                    proc.terminate()
                    killed = True
                    continue
                conns = proc.info.get("connections") or []
                if any(getattr(c, "laddr", None) and getattr(c.laddr, "port", None) == port_hint for c in conns):
                    proc.terminate()
                    killed = True
                    continue
            except Exception:
                continue
        return killed
    except Exception:
        return False
