"""Headless input-normalization policy used by the processor coordinator."""

from __future__ import annotations

from typing import Any, List, Optional, Tuple


CropBox = Tuple[float, float, float, float]


def coerce_crop_box(raw: Any) -> Optional[CropBox]:
    """Convert Nuke bounding-box values or sequences into numeric coordinates."""
    if raw is None:
        return None
    coords: List[Any] = []
    if isinstance(raw, (list, tuple)):
        coords.extend(raw[:4])
    else:
        for attr in ("x", "y", "r", "t"):
            try:
                candidate = getattr(raw, attr)
                coords.append(candidate() if callable(candidate) else candidate)
            except Exception:
                coords.append(None)
    if len(coords) < 4 or any(coord is None for coord in coords[:4]):
        return None
    try:
        values = tuple(float(coord) for coord in coords[:4])
    except (TypeError, ValueError):
        return None
    return values  # type: ignore[return-value]


def resolve_crop_settings(node, *, log_debug) -> Optional[CropBox]:
    """Read and validate the optional Charon input crop box from a node."""
    try:
        enabled_knob = node.knob("charon_use_crop")
        if enabled_knob is None:
            enabled = False
        else:
            try:
                enabled = bool(int(enabled_knob.value()))
            except Exception:
                enabled = bool(enabled_knob.value())
    except Exception:
        enabled = False
    if not enabled:
        return None

    try:
        box_knob = node.knob("charon_crop_bbox")
    except Exception:
        box_knob = None
    if box_knob is None:
        return None
    try:
        raw_box = box_knob.value()
    except Exception:
        try:
            raw_box = box_knob.getValue()
        except Exception:
            raw_box = None

    crop_box = coerce_crop_box(raw_box)
    if not crop_box:
        log_debug("Use Crop enabled but crop box is invalid; skipping crop", "WARNING")
        return None
    x, y, right, top = crop_box
    if right <= x or top <= y:
        log_debug("Use Crop enabled but crop box is empty; skipping crop", "WARNING")
        return None
    log_debug(f"Using crop box {crop_box} for CharonOp inputs")
    return crop_box
