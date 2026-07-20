from __future__ import annotations

import os
from typing import Optional


def normalize_for_compare(path: str) -> str:
    """Return an absolute, normalized path suitable for containment checks."""
    if not path:
        return ""
    return os.path.normcase(os.path.abspath(os.path.normpath(str(path))))


def is_path_inside(candidate: str, root: str, *, allow_equal: bool = True) -> bool:
    """Return whether candidate resolves inside root without string-prefix checks."""
    candidate_norm = normalize_for_compare(candidate)
    root_norm = normalize_for_compare(root)
    if not candidate_norm or not root_norm:
        return False
    if not allow_equal and candidate_norm == root_norm:
        return False
    try:
        return os.path.commonpath([candidate_norm, root_norm]) == root_norm
    except ValueError:
        # Different drives on Windows cannot share a common path.
        return False


def ensure_path_inside(
    candidate: str,
    root: str,
    *,
    label: str = "Path",
    allow_equal: bool = True,
) -> str:
    """Return candidate as an absolute path or raise when it escapes root."""
    candidate_abs = os.path.abspath(os.path.normpath(str(candidate or "")))
    if not is_path_inside(candidate_abs, root, allow_equal=allow_equal):
        raise ValueError(f"{label} '{candidate}' is outside the allowed root: {root}")
    return candidate_abs


def resolve_relative_path_inside(
    root: str,
    relative_path: Optional[str],
    *,
    label: str = "Path",
) -> str:
    """
    Resolve a metadata-supplied relative path under root.

    Absolute paths are rejected to keep workflow metadata portable and to avoid
    bypassing repository containment through drive-qualified values.
    """
    value = str(relative_path or "").strip()
    if not value:
        raise ValueError(f"{label} is required.")
    if os.path.isabs(value):
        raise ValueError(f"{label} must be relative: {value}")
    candidate = os.path.join(root, value)
    return ensure_path_inside(candidate, root, label=label)


def relative_path_from_root(candidate: str, root: str, *, label: str = "Path") -> str:
    """Return candidate relative to root after verifying containment."""
    candidate_abs = ensure_path_inside(candidate, root, label=label)
    root_abs = os.path.abspath(os.path.normpath(str(root or "")))
    return os.path.relpath(candidate_abs, root_abs)
