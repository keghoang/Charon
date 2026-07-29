import os
from typing import Iterable, Optional

from . import preferences

_COLOR_MANAGEMENT_KNOBS: Iterable[str] = (
    "colorManagement",
    "color_management",
)

_WORKING_SPACE_KNOBS: Iterable[str] = (
    "workingSpaceLUT",
    "workingSpace",
    "working_space",
)

_OCIO_CONFIG_KNOBS: Iterable[str] = (
    "OCIO_config",
    "ocio_config",
)

_CUSTOM_OCIO_PATH_KNOBS: Iterable[str] = (
    "customOCIOConfigPath",
    "custom_ocio_config_path",
)

_NON_ACES_WORKING_SPACE_TOKENS = ("rec.709", "rec709", "srgb")


def _read_root_knob(names: Iterable[str]) -> str:
    try:
        import nuke  # type: ignore
    except Exception:
        return ""

    try:
        root = nuke.root()
    except Exception:
        return ""

    for name in names:
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


def resolve_aces_decision(
    color_management: str,
    working_space: str,
    config_descriptor: str,
) -> Optional[bool]:
    """Decide whether the session is ACES from root colour settings.

    OCIO mode alone does not imply ACES: Nuke's default OCIO config works in
    scene-linear Rec.709-sRGB, which needs the sRGB pipeline. The working
    space is the ground truth for what the pixels are; the config name/path
    (including $OCIO) breaks ties. Returns ``None`` when the setup cannot be
    identified so the caller can fall back to the saved preference.
    """
    mode = (color_management or "").upper()
    if not mode:
        return None
    if "OCIO" not in mode:
        return False

    working = (working_space or "").lower()
    if "aces" in working:
        return True
    if any(token in working for token in _NON_ACES_WORKING_SPACE_TOKENS):
        return False

    descriptor = (config_descriptor or "").lower()
    if "aces" in descriptor:
        return True
    if "nuke-default" in descriptor or "nuke_default" in descriptor:
        return False
    return None


def is_aces_enabled() -> bool:
    config_descriptor = " ".join(
        part
        for part in (
            _read_root_knob(_OCIO_CONFIG_KNOBS),
            _read_root_knob(_CUSTOM_OCIO_PATH_KNOBS),
            os.environ.get("OCIO", ""),
        )
        if part
    )
    decision = resolve_aces_decision(
        _read_root_knob(_COLOR_MANAGEMENT_KNOBS),
        _read_root_knob(_WORKING_SPACE_KNOBS),
        config_descriptor,
    )
    if decision is not None:
        return decision
    try:
        return bool(preferences.get_preference("aces_mode_enabled", False))
    except Exception:
        return False


def current_color_mode() -> str:
    return "ACES" if is_aces_enabled() else "sRGB"
