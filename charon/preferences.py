import json
import os
from typing import Any, Dict, Optional, Tuple

from .charon_logger import system_warning

try:  # Qt may not be available in headless contexts
    from .qt_compat import QtWidgets, QtCore  # type: ignore
except Exception:  # pragma: no cover - defensive import
    QtWidgets = None  # type: ignore
    QtCore = None  # type: ignore

_DEFAULT_FILENAME = "preferences.json"
_WARNING_SHOWN = False


def _default_plugin_dir() -> str:
    return os.path.join(
        os.path.expanduser("~"),
        "AppData",
        "Local",
        "Galt",
        "plugins",
        "charon",
    )


def _resolve_plugin_dir() -> Tuple[str, bool]:
    plugin_dir = os.environ.get("GALT_PLUGIN_DIR")
    if plugin_dir:
        return plugin_dir, False
    return _default_plugin_dir(), True


def _notify_missing(parent: Optional[object]) -> None:
    global _WARNING_SHOWN
    if _WARNING_SHOWN:
        return
    _WARNING_SHOWN = True

    fallback, _ = _resolve_plugin_dir()
    message = (
        "Environment variable GALT_PLUGIN_DIR is not set. "
        f"Preferences will be stored in {fallback}."
    )
    system_warning(message)


def preferences_path(
    filename: str = _DEFAULT_FILENAME,
    *,
    parent: Optional[object] = None,
    ensure_dir: bool = False,
) -> str:
    root, missing = _resolve_plugin_dir()
    if missing:
        _notify_missing(parent)
    if ensure_dir:
        os.makedirs(root, exist_ok=True)
    return os.path.join(root, filename)


def load_preferences(
    *,
    filename: str = _DEFAULT_FILENAME,
    parent: Optional[object] = None,
) -> Dict[str, Any]:
    path = preferences_path(filename, parent=parent, ensure_dir=False)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            return data
    except Exception as exc:  # pragma: no cover - defensive path
        system_warning(f"Could not load preferences from {path}: {exc}")
    return {}


def save_preferences(
    data: Dict[str, Any],
    *,
    filename: str = _DEFAULT_FILENAME,
    parent: Optional[object] = None,
) -> None:
    path = preferences_path(filename, parent=parent, ensure_dir=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)


def get_preference(
    key: str,
    default: Any = None,
    *,
    filename: str = _DEFAULT_FILENAME,
    parent: Optional[object] = None,
) -> Any:
    prefs = load_preferences(filename=filename, parent=parent)
    return prefs.get(key, default)


def set_preference(
    key: str,
    value: Any,
    *,
    filename: str = _DEFAULT_FILENAME,
    parent: Optional[object] = None,
) -> None:
    prefs = load_preferences(filename=filename, parent=parent)
    prefs[key] = value
    save_preferences(prefs, filename=filename, parent=parent)


