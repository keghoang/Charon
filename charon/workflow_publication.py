"""Helpers for publishing complete workflow folders atomically."""

from __future__ import annotations

import os
import shutil
import uuid


def create_staging_directory(target_folder: str) -> str:
    """Create a hidden sibling staging directory for a workflow publication."""
    target = os.path.abspath(target_folder)
    parent = os.path.dirname(target)
    name = os.path.basename(target)
    os.makedirs(parent, exist_ok=True)
    staging = os.path.join(parent, f".{name}.{uuid.uuid4().hex}.charon-staging")
    os.makedirs(staging)
    return staging


def publish_staged_directory(staging_folder: str, target_folder: str) -> None:
    """Publish a complete workflow folder without overwriting existing content."""
    staging = os.path.abspath(staging_folder)
    target = os.path.abspath(target_folder)
    if os.path.exists(target):
        raise FileExistsError(f"Workflow folder already exists: {target}")
    os.replace(staging, target)


def discard_staging_directory(staging_folder: str) -> None:
    """Remove an unpublished workflow staging folder."""
    shutil.rmtree(staging_folder, ignore_errors=True)

