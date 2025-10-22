"""
Charon Prototype Entry Point

Launches the Galt-based CharonBoard interface from within Nuke (or other
hosts) without needing the helper script. Intended to be run from the
Script Editor, just like the legacy panel.
"""

import argparse
import importlib
import inspect
import logging
import os
import sys
from typing import Iterable, Optional


def _resolve_source_path() -> str:
    """Return the absolute path to this script, even when executed via exec()."""
    module = sys.modules.get(__name__)
    candidate = getattr(module, "__file__", None) if module else None
    if candidate:
        return os.path.abspath(candidate)

    frame = inspect.currentframe()
    while frame:
        info = inspect.getframeinfo(frame, context=0)
        if info.filename and info.filename != "<string>":
            return os.path.abspath(info.filename)
        frame = frame.f_back
    raise RuntimeError("Could not determine main.py location; please run via file path.")


def _ensure_repo_on_path() -> str:
    """Guarantee the repository root is present on sys.path."""
    source_path = _resolve_source_path()
    repo_root = os.path.dirname(source_path)
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
        # When running via exec(), __file__ may be undefined for downstream imports.
        module = sys.modules.get(__name__)
        if module is not None and not getattr(module, "__file__", None):
            module.__file__ = source_path
    return repo_root


def _clear_modules(prefixes: Iterable[str]) -> None:
    """Drop cached modules so reloads pick up fresh changes."""
    for name in list(sys.modules):
        if any(name.startswith(prefix) for prefix in prefixes):
            sys.modules.pop(name, None)


def _coerce_debug(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    lowered = value.strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    return default


def main(*, host: Optional[str] = None, repository: Optional[str] = None, debug: Optional[bool] = None):
    """
    Launch the prototype CharonBoard UI.

    Parameters:
        host: Optional host override (e.g. "nuke").
        repository: Optional workflow repository override.
        debug: Optional flag enabling verbose logging.
    """
    repo_root = _ensure_repo_on_path()
    _clear_modules(("prototypes.galt_clone",))
    importlib.invalidate_caches()

    env_debug = _coerce_debug(os.getenv("CHARON_DEBUG"))
    debug_flag = debug if debug is not None else env_debug

    logging.basicConfig(level=logging.DEBUG if debug_flag else logging.INFO)

    from prototypes.galt_clone.galt import main as galt_main

    window = galt_main.launch(
        host_override=host,
        global_path=repository,
        debug=bool(debug_flag),
    )

    if window:
        print("CharonBoard ready.")
        print("=" * 60)
        print("Workflows tab: manage repository folders and spawn CharonOps.")
        print("CharonBoard tab: monitor spawned nodes, trigger runs, and import outputs.")
        print("=" * 60)
    return window


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Launch the CharonBoard prototype UI.")
    parser.add_argument("--host", help="Override host detection (e.g. nuke)")
    parser.add_argument("--repository", help="Override workflow repository root")
    parser.add_argument("--debug", action="store_true", help="Enable verbose debug logging")
    args = parser.parse_args()

    try:
        main(host=args.host, repository=args.repository, debug=args.debug)
    except Exception as exc:
        print(f"Error launching CharonBoard: {exc}")
        raise
