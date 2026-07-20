"""Canonical ComfyUI filesystem and server configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from . import config, preferences
from .paths import resolve_comfy_environment as resolve_comfy_filesystem


COMFY_PATH_PREFERENCE = "comfyui_launch_path"
COMFY_URL_PREFERENCE = "comfyui_url_base"
COMFY_URL_ENVIRONMENT = "CHARON_COMFY_URL"


def normalize_comfy_url(value: Optional[str]) -> str:
    """Normalize a ComfyUI HTTP base URL without adding endpoint paths."""
    candidate = str(value or "").strip() or config.COMFY_URL_BASE
    if "://" not in candidate:
        candidate = f"http://{candidate}"
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"Invalid ComfyUI URL: {value!r}")
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def _coerce_configured_path(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)):
        return "".join(str(part) for part in value if part).strip()
    return ""


@dataclass(frozen=True)
class ComfyEnvironment:
    """Resolved identity of one configured ComfyUI runtime."""

    configured_path: str
    base_url: str
    base_dir: str = ""
    comfy_dir: str = ""
    models_dir: str = ""
    python_exe: Optional[str] = None
    embedded_root: Optional[str] = None

    @property
    def server_address(self) -> str:
        return urlparse(self.base_url).netloc

    def as_path_info(self) -> Dict[str, Any]:
        """Provide the legacy mapping used by incremental migration callers."""
        return {
            "configured_path": self.configured_path,
            "base_dir": self.base_dir,
            "comfy_dir": self.comfy_dir,
            "models_dir": self.models_dir,
            "python_exe": self.python_exe,
            "embedded_root": self.embedded_root,
        }

    def diagnostics(self) -> Dict[str, Any]:
        return {
            **self.as_path_info(),
            "base_url": self.base_url,
            "server_address": self.server_address,
            "configured_path_exists": bool(
                self.configured_path and os.path.exists(self.configured_path)
            ),
            "comfy_dir_exists": bool(self.comfy_dir and os.path.isdir(self.comfy_dir)),
            "models_dir_exists": bool(self.models_dir and os.path.isdir(self.models_dir)),
            "python_exe_exists": bool(self.python_exe and os.path.isfile(self.python_exe)),
        }


def resolve_comfy_runtime(
    comfy_path: Optional[str] = None,
    base_url: Optional[str] = None,
    *,
    use_preferences: bool = True,
) -> ComfyEnvironment:
    """Resolve explicit, deployment, and persisted ComfyUI configuration."""
    prefs: Dict[str, Any] = preferences.load_preferences() if use_preferences else {}
    configured_path = _coerce_configured_path(comfy_path)
    if not configured_path and use_preferences:
        configured_path = _coerce_configured_path(prefs.get(COMFY_PATH_PREFERENCE))

    configured_url = str(base_url or "").strip()
    if not configured_url:
        configured_url = str(os.getenv(COMFY_URL_ENVIRONMENT) or "").strip()
    if not configured_url and use_preferences:
        configured_url = str(prefs.get(COMFY_URL_PREFERENCE) or "").strip()
    normalized_url = normalize_comfy_url(configured_url or config.COMFY_URL_BASE)

    path_info = resolve_comfy_filesystem(configured_path)
    return ComfyEnvironment(
        configured_path=configured_path,
        base_url=normalized_url,
        base_dir=str(path_info.get("base_dir") or ""),
        comfy_dir=str(path_info.get("comfy_dir") or ""),
        models_dir=str(path_info.get("models_dir") or ""),
        python_exe=path_info.get("python_exe"),
        embedded_root=path_info.get("embedded_root"),
    )
