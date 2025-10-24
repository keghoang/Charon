"""
Main entry point for the Charon panel.

Run from Nuke's Script Editor:
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

    from charon import main as charon_main

    window = charon_main.launch()
    if window:
        print("Charon panel ready.")
        print("=" * 60)
        print("Workflows tab: manage repository folders and spawn CharonOps.")
        print("Charon tab: monitor spawned nodes, trigger runs, and import outputs.")
        print("=" * 60)
    return window


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Error launching Charon panel: {exc}")
        raise
