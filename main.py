"""
Charon - ComfyUI Nuke Integration Tool

Minimal entry point that boots the modular Charon panel when executed
inside Nuke's Script Editor.
"""

import logging

from charon_core import create_charon_panel


def main():
    logging.basicConfig(level=logging.INFO)
    panel = create_charon_panel()
    if panel:
        print("Charon - v1.0 Loaded!")
        print("=" * 60)
        print("Usage Instructions:")
        print("1. Connection is auto-tested on startup.")
        print("2. Select a workflow from presets or load custom JSON.")
        print("3. Click 'Generate CharonOp Node' to create workflow-specific nodes.")
        print("4. Connect inputs and process with ComfyUI.")
        print("5. Results automatically imported as Read nodes.")
        print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Error creating Charon panel: {exc}")
        raise
