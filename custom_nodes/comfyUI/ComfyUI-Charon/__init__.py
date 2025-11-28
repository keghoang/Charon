"""
ComfyUI_CHARON: CHARON 3D Auto Align node
"""

import os
import traceback

WEB_DIRECTORY = None  # no frontend assets

try:
    from .nodes.auto_align import NODE_CLASS_MAPPINGS as ALIGN_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS as ALIGN_DISPLAY
    from .nodes.charon_camera import NODE_CLASS_MAPPINGS as CAMERA_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS as CAMERA_DISPLAY
    NODE_CLASS_MAPPINGS = {}
    NODE_CLASS_MAPPINGS.update(ALIGN_MAPPINGS)
    NODE_CLASS_MAPPINGS.update(CAMERA_MAPPINGS)
    NODE_DISPLAY_NAME_MAPPINGS = {}
    NODE_DISPLAY_NAME_MAPPINGS.update(ALIGN_DISPLAY)
    NODE_DISPLAY_NAME_MAPPINGS.update(CAMERA_DISPLAY)
    print("[ComfyUI_CHARON] Loaded CHARON nodes.")
except Exception as e:
    print("[ComfyUI_CHARON] Failed to load nodes:", e)
    print(traceback.format_exc())
    NODE_CLASS_MAPPINGS = {}
    NODE_DISPLAY_NAME_MAPPINGS = {}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
