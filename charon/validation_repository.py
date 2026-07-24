"""Validation state ownership shared by presentation and runtime callers."""

from __future__ import annotations

import copy
import os
import time
from typing import Any, Dict, Optional

from .workflow_local_store import (
    compute_validation_signature,
    load_validation_resolve_status,
)


VALIDATION_STATES = frozenset(
    {"idle", "validating", "installing", "validated", "needs_resolve"}
)


def build_validation_override(
    payload: Optional[Dict[str, Any]],
    *,
    comfy_path: str = "",
) -> Dict[str, Any]:
    """Preserve diagnostics while allowing only non-runtime validation overrides."""
    result = copy.deepcopy(payload) if isinstance(payload, dict) else {}
    for issue in result.get("issues") or []:
        if not isinstance(issue, dict) or issue.get("ok", False):
            continue
        data = issue.get("data") if isinstance(issue.get("data"), dict) else {}
        prompt_export = data.get("prompt_export")
        export_failed = isinstance(prompt_export, dict) and not prompt_export.get("ok", False)
        if issue.get("key") == "runtime_identity" or export_failed:
            raise ValueError(
                "ComfyUI runtime identity and workflow export failures cannot be overridden."
            )
    result.update(
        {
            "state": "validated",
            "message": "Validation overridden",
            "timestamp": time.time(),
            "overridden": True,
            "comfy_path": comfy_path,
        }
    )
    return result


def derive_validation_state(
    payload: Optional[Dict[str, Any]],
    fallback: str = "idle",
) -> str:
    """Infer the presentation state represented by a validation payload."""
    if not isinstance(payload, dict):
        return fallback

    auto_state = payload.get("auto_resolve_state")
    if isinstance(auto_state, dict) and auto_state.get("running"):
        return "installing"

    explicit_state = str(payload.get("state") or "").strip().lower()
    if explicit_state in VALIDATION_STATES:
        inferred = explicit_state
    else:
        inferred = "validated"
        for issue in payload.get("issues") or []:
            if isinstance(issue, dict) and not issue.get("ok", False):
                inferred = "needs_resolve"
                break

    restart_required = bool(
        payload.get("restart_required") or payload.get("requires_restart")
    )
    if restart_required and inferred == "validated":
        return "needs_resolve"
    return inferred or fallback


class WorkflowValidationRepository:
    """Coordinates transient validation state with the durable workflow store."""

    def __init__(self) -> None:
        self._entries: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def _key(workflow_path: str) -> str:
        return os.path.normpath(workflow_path or "").lower()

    def load_persisted(self, workflow_path: str) -> Optional[Dict[str, Any]]:
        payload = load_validation_resolve_status(workflow_path or "")
        return payload if isinstance(payload, dict) else None

    def read(self, workflow_path: str) -> Optional[Dict[str, Any]]:
        key = self._key(workflow_path)
        signature = compute_validation_signature(workflow_path)
        entry = self._entries.get(key)
        if isinstance(entry, dict) and entry.get("validation_signature") == signature:
            return entry
        self._entries.pop(key, None)

        payload = self.load_persisted(workflow_path)
        if payload is None:
            return None
        entry = {
            "state": derive_validation_state(payload, fallback="needs_resolve"),
            "payload": payload,
            "validation_signature": signature,
        }
        self._entries[key] = entry
        return entry

    def write(
        self,
        workflow_path: str,
        state: str,
        payload: Optional[Dict[str, Any]],
    ) -> None:
        self._entries[self._key(workflow_path)] = {
            "state": state,
            "payload": payload,
            "validation_signature": compute_validation_signature(workflow_path),
        }

    def clear(self, workflow_path: str) -> None:
        self._entries.pop(self._key(workflow_path), None)
