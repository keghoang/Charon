import urllib.request
import urllib.error

from .charon_logger import system_warning

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
