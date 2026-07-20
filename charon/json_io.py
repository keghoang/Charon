"""Small atomic JSON persistence helpers."""

from __future__ import annotations

import json
import os
import uuid
from typing import Any


def atomic_write_json(path: str, payload: Any, *, indent: int = 2) -> None:
    """Write JSON beside its destination, then publish it with an atomic replace."""
    destination = os.path.abspath(path)
    parent = os.path.dirname(destination)
    os.makedirs(parent, exist_ok=True)
    temp_path = f"{destination}.{uuid.uuid4().hex}.tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=indent)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, destination)
    finally:
        try:
            os.remove(temp_path)
        except FileNotFoundError:
            pass

