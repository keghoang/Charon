"""
Main entry point for CharonBoard.

Intended to be executed directly from Nuke's Script Editor via:
    import runpy
    runpy.run_path(r"...\\Charon\\main.py", run_name="__main__")
"""

import logging
import sys
from pathlib import Path


def main():
    repo = Path(__file__).resolve().parent
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))

    logging.basicConfig(level=logging.INFO)

    from prototypes.galt_clone.galt import main as galt_main

    window = galt_main.launch()
    if window:
        print("CharonBoard ready.")
        print("=" * 60)
        print("Workflows tab: manage repository folders and spawn CharonOps.")
        print("CharonBoard tab: monitor spawned nodes, trigger runs, and import outputs.")
        print("=" * 60)
    return window


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Error launching CharonBoard: {exc}")
        raise
