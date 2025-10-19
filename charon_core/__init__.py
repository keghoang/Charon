"""Charon - ComfyUI integration helpers for Nuke."""

_PANEL_INSTANCE = None


def create_charon_panel():
    """Create (or reuse) the singleton Charon panel."""
    global _PANEL_INSTANCE
    from .ui import create_charon_panel as _create_charon_panel

    panel = _create_charon_panel()
    if panel is not None:
        _PANEL_INSTANCE = panel
        return panel

    return _PANEL_INSTANCE
