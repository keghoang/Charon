from typing import Iterable

from . import preferences

_COLOR_MANAGEMENT_KNOBS: Iterable[str] = (
    "colorManagement",
    "OCIO_config",
    "ocio_config",
    "color_management",
)


def _get_root_color_management_value() -> str:
    try:
        import nuke  # type: ignore
    except Exception:
        return ""

    try:
        root = nuke.root()
    except Exception:
        return ""

    for name in _COLOR_MANAGEMENT_KNOBS:
        try:
            knob = root.knob(name)
        except Exception:
            knob = None
        if not knob:
            continue
        try:
            value = knob.value()
        except Exception:
            value = ""
        if value is None:
            continue
        value_str = str(value)
        if value_str:
            return value_str
    return ""


def is_aces_enabled() -> bool:
    value = _get_root_color_management_value()
    if value:
        return "OCIO" in str(value).upper()
    try:
        return bool(preferences.get_preference("aces_mode_enabled", False))
    except Exception:
        return False


def current_color_mode() -> str:
    return "ACES" if is_aces_enabled() else "sRGB"
