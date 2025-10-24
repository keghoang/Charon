from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from .charon_logger import system_debug, system_warning

STATUS_PAYLOAD_META = "charon/status_payload"
AUTO_IMPORT_META = "charon/auto_import"
WORKFLOW_NAME_META = "charon/workflow_name"
WORKFLOW_PATH_META = "charon/workflow_path"
NODE_CLASS = "Group"
NODE_PREFIX = "CharonOp_"

__all__ = [
    "SceneNodeInfo",
    "list_scene_nodes",
    "read_status_payload",
    "write_status_payload",
    "read_auto_import",
    "set_auto_import",
]


@dataclass
class SceneNodeInfo:
    node: Any
    name: str
    status: str
    state: str
    progress: float
    workflow_name: str
    workflow_path: str
    payload: Dict[str, Any]
    updated_at: Optional[float]
    output_path: Optional[str]
    auto_import: bool


def list_scene_nodes(nuke_module=None) -> List[SceneNodeInfo]:
    """
    Return SceneNodeInfo entries for each CharonOp group currently in the script.
    Falls back to an empty list when the `nuke` module is unavailable.
    """
    nuke = _require_nuke(nuke_module)
    if nuke is None:
        return []

    nodes: List[SceneNodeInfo] = []
    for node in _iter_charon_nodes(nuke):
        info = _build_scene_node_info(node)
        if info:
            nodes.append(info)
    return nodes


def read_status_payload(node) -> Dict[str, Any]:
    """
    Read and deserialize the stored status payload for a CharonOp node.
    Returns an empty dict when the payload is missing or invalid.
    """
    raw_value: Optional[str] = None
    try:
        raw_value = node.metadata(STATUS_PAYLOAD_META)
    except Exception:
        raw_value = None
    if not raw_value:
        knob_value = _read_knob_value(node, "charon_status_payload")
        if knob_value:
            raw_value = knob_value
    if not raw_value:
        return {}
    try:
        return json.loads(raw_value)
    except Exception as exc:
        system_warning(f"Failed to parse status payload for {node.name()}: {exc}")
        return {}


def write_status_payload(node, payload: Dict[str, Any]) -> None:
    """Persist the status payload onto the node metadata (and knob if present)."""
    try:
        serialized = json.dumps(payload)
    except Exception as exc:
        system_warning(f"Could not serialize status payload for {getattr(node, 'name', lambda: '?')()}: {exc}")
        return

    try:
        node.setMetaData(STATUS_PAYLOAD_META, serialized)
    except Exception as exc:
        system_warning(f"Could not set metadata for {node.name()}: {exc}")
    knob = _safe_knob(node, "charon_status_payload")
    if knob is not None:
        try:
            knob.setValue(serialized)
        except Exception as exc:
            system_warning(f"Could not update status knob for {node.name()}: {exc}")


def read_auto_import(node, payload: Optional[Dict[str, Any]] = None) -> bool:
    """Read the auto-import toggle from knobs/metadata or fallback to payload."""
    knob = _safe_knob(node, "charon_auto_import")
    if knob is not None:
        try:
            return bool(int(knob.value()))
        except Exception:
            try:
                return bool(knob.value())
            except Exception:
                pass

    try:
        meta_val = node.metadata(AUTO_IMPORT_META)
        if isinstance(meta_val, str):
            lowered = meta_val.strip().lower()
            if lowered in {"0", "false", "off", "no"}:
                return False
            if lowered in {"1", "true", "on", "yes"}:
                return True
        elif meta_val is not None:
            return bool(meta_val)
    except Exception:
        pass

    payload = payload or read_status_payload(node)
    if payload:
        value = payload.get("auto_import")
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)

    return True


def set_auto_import(node, enabled: bool, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Persist the auto-import toggle to both knob and metadata.
    Returns the payload that was written (ensuring the `auto_import` flag matches).
    """
    knob = _safe_knob(node, "charon_auto_import")
    if knob is not None:
        try:
            knob.setValue(1 if enabled else 0)
        except Exception:
            pass
    try:
        node.setMetaData(AUTO_IMPORT_META, "1" if enabled else "0")
    except Exception:
        pass

    payload = dict(payload or read_status_payload(node))
    if payload.get("auto_import") != enabled:
        payload["auto_import"] = enabled
        write_status_payload(node, payload)
    return payload


# Internal helpers -----------------------------------------------------------------


def _require_nuke(nuke_module=None):
    if nuke_module is not None:
        return nuke_module
    try:
        import nuke  # type: ignore
    except Exception:
        system_warning("Nuke module unavailable; Scene Nodes runtime cannot enumerate nodes.")
        return None
    return nuke


def _iter_charon_nodes(nuke_module) -> Iterable[Any]:
    for node in nuke_module.allNodes():
        try:
            if node.Class() == NODE_CLASS and node.name().startswith(NODE_PREFIX):
                yield node
        except Exception:
            continue


def _build_scene_node_info(node) -> Optional[SceneNodeInfo]:
    payload = read_status_payload(node)

    progress = _coerce_float(_read_knob_value(node, "charon_progress"), default=0.0)
    status_raw = _coerce_str(_read_knob_value(node, "charon_status"), default="Ready")

    status = payload.get("message") or status_raw
    state = payload.get("state") or _infer_state(status, progress)

    workflow_path = _resolve_workflow_path(node)
    workflow_name = _resolve_workflow_name(node, payload, workflow_path)

    auto_import = read_auto_import(node, payload)
    output_path = _resolve_output_path(node, payload)
    updated_at = _coerce_optional_float(
        payload.get("updated_at") or (payload.get("current_run") or {}).get("updated_at")
    )

    info = SceneNodeInfo(
        node=node,
        name=node.name(),
        status=status,
        state=state,
        progress=progress,
        workflow_name=workflow_name,
        workflow_path=workflow_path,
        payload=payload,
        updated_at=updated_at,
        output_path=output_path,
        auto_import=auto_import,
    )

    system_debug(
        f"Scene node snapshot: {info.name} status={info.status!r} "
        f"state={info.state} progress={info.progress:.02f}"
    )
    return info


def _read_knob_value(node, name: str):
    knob = _safe_knob(node, name)
    if knob is None:
        return None
    try:
        return knob.value()
    except Exception:
        return None


def _safe_knob(node, name: str):
    try:
        return node.knob(name)
    except Exception:
        return None


def _coerce_float(value, default: float) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _coerce_str(value, default: str) -> str:
    if value is None:
        return default
    try:
        return str(value)
    except Exception:
        return default


def _coerce_optional_float(value) -> Optional[float]:
    if value in (None, "", False):
        return None
    try:
        return float(value)
    except Exception:
        return None


def _infer_state(status: str, progress: float) -> str:
    normalized = (status or "").strip().lower()
    if progress < 0 or normalized.startswith("error"):
        return "Error"
    if progress >= 1.0:
        return "Completed"
    if "process" in normalized or "upload" in normalized:
        return "Processing"
    return status or "Ready"


def _resolve_workflow_path(node) -> str:
    path = _coerce_str(_read_knob_value(node, "workflow_path"), "")
    if path:
        return path
    try:
        meta = node.metadata(WORKFLOW_PATH_META)
        if isinstance(meta, str):
            return meta
    except Exception:
        pass
    return ""


def _resolve_workflow_name(node, payload: Dict[str, Any], workflow_path: str) -> str:
    for source in (
        payload.get("workflow_name"),
        _coerce_str(_read_knob_value(node, "charon_workflow_name"), ""),
        _read_metadata_str(node, WORKFLOW_NAME_META),
    ):
        if source:
            return source
    if workflow_path:
        return workflow_path.split("\\")[-1].split("/")[-1].rsplit(".", 1)[0]
    return node.name()


def _read_metadata_str(node, key: str) -> str:
    try:
        value = node.metadata(key)
    except Exception:
        return ""
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    try:
        return str(value)
    except Exception:
        return ""


def _resolve_output_path(node, payload: Dict[str, Any]) -> Optional[str]:
    candidate = payload.get("output_path")
    if not candidate:
        candidate = _read_knob_value(node, "charon_last_output")
    if not candidate:
        candidate = _read_metadata_str(node, "charon/last_output")
    if not candidate:
        return None
    return str(candidate).strip() or None
