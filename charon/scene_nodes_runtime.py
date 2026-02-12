from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from .charon_logger import system_debug, system_warning
from .node_factory import reset_charon_node_state, sanitize_name

STATUS_PAYLOAD_META = "charon/status_payload"
AUTO_IMPORT_META = "charon/auto_import"
WORKFLOW_NAME_META = "charon/workflow_name"
WORKFLOW_PATH_META = "charon/workflow_path"
SOURCE_WORKFLOW_PATH_META = "charon/source_workflow_path"
NODE_CLASS = "Group"
NODE_PREFIX = "CharonOp_"
_SCENE_NODE_SNAPSHOT_CACHE: Dict[str, tuple[str, str, float]] = {}

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

    candidates = list(_iter_charon_nodes(nuke))
    duplicates: Dict[str, List[Any]] = {}
    for node in candidates:
        node_identifier = _resolve_node_identifier(node)
        if not node_identifier:
            continue
        duplicates.setdefault(node_identifier, []).append(node)

    for node_id, group in duplicates.items():
        if len(group) <= 1:
            continue
        def _has_value(value) -> bool:
            if value in (None, ""):
                return False
            try:
                return bool(str(value).strip())
            except Exception:
                return False

        def _node_has_outputs(target) -> bool:
            if _has_value(_read_knob_value(target, "charon_last_output")):
                return True
            try:
                if _has_value(target.metadata("charon/last_output")):
                    return True
            except Exception:
                pass
            if _has_value(_read_knob_value(target, "charon_read_node")):
                return True
            if _has_value(_read_knob_value(target, "charon_contact_sheet")):
                return True
            try:
                if _has_value(target.metadata("charon/read_node")):
                    return True
            except Exception:
                pass
            try:
                if _has_value(target.metadata("charon/contact_sheet")):
                    return True
            except Exception:
                pass
            return False

        def _node_pos(target):
            try:
                return (float(target.xpos()), float(target.ypos()))
            except Exception:
                return None

        def _distance_sq(a, b):
            if a is None or b is None:
                return None
            dx = a[0] - b[0]
            dy = a[1] - b[1]
            return dx * dx + dy * dy

        def _match_parent(candidate, parent_id: str) -> bool:
            if not parent_id:
                return False
            normalized_parent = parent_id.strip().lower()[:12]
            if not normalized_parent:
                return False
            try:
                meta_val = candidate.metadata("charon/parent_id")
                if isinstance(meta_val, str) and meta_val.strip().lower()[:12] == normalized_parent:
                    return True
            except Exception:
                pass
            knob_val = _read_knob_value(candidate, "charon_parent_id")
            if isinstance(knob_val, str) and knob_val.strip().lower()[:12] == normalized_parent:
                return True
            return False

        def _looks_like_contact_sheet_group(candidate) -> bool:
            try:
                if candidate.Class() != "Group":
                    return False
            except Exception:
                return False
            try:
                if candidate.knob("charon_read_id") is not None:
                    return True
            except Exception:
                pass
            try:
                meta_val = candidate.metadata("charon/read_id")
                if meta_val:
                    return True
            except Exception:
                pass
            try:
                return "ContactSheet" in (candidate.name() or "")
            except Exception:
                return False

        def _reassign_outputs_for_duplicate(duplicate_node, keeper_node, old_id: str, new_id: str) -> None:
            dup_pos = _node_pos(duplicate_node)
            keep_pos = _node_pos(keeper_node)
            try:
                candidates = list(nuke.allNodes("Read")) + list(nuke.allNodes("ReadGeo2")) + list(nuke.allNodes("Group"))
            except Exception:
                candidates = []
            for candidate in candidates:
                if candidate is None or candidate is duplicate_node or candidate is keeper_node:
                    continue
                try:
                    cls_name = candidate.Class()
                except Exception:
                    cls_name = ""
                if cls_name == "Group" and not _looks_like_contact_sheet_group(candidate):
                    continue
                if not _match_parent(candidate, old_id):
                    continue
                cand_pos = _node_pos(candidate)
                if keep_pos is not None and dup_pos is not None:
                    dist_dup = _distance_sq(cand_pos, dup_pos)
                    dist_keep = _distance_sq(cand_pos, keep_pos)
                    if dist_dup is None or dist_keep is None:
                        continue
                    if dist_dup > dist_keep:
                        continue
                try:
                    candidate.setMetaData("charon/parent_id", new_id)
                except Exception:
                    pass
                knob = _safe_knob(candidate, "charon_parent_id")
                if knob is not None:
                    try:
                        knob.setValue(new_id)
                    except Exception:
                        pass
                if cls_name == "Group" and _looks_like_contact_sheet_group(candidate):
                    try:
                        sheet_knob = _safe_knob(duplicate_node, "charon_contact_sheet")
                    except Exception:
                        sheet_knob = None
                    if sheet_knob is not None:
                        try:
                            sheet_knob.setValue(candidate.name())
                        except Exception:
                            pass

        group_with_outputs = [item for item in group if _node_has_outputs(item)]
        if group_with_outputs:
            group_with_outputs = sorted(group_with_outputs, key=_node_sort_key)
            keeper = group_with_outputs[0]
        else:
            group = sorted(group, key=_node_sort_key)
            keeper = group[0]
        for duplicate in group:
            if duplicate is keeper:
                continue
            try:
                new_identifier = reset_charon_node_state(duplicate) or ""
                if new_identifier:
                    _reassign_outputs_for_duplicate(duplicate, keeper, node_id, new_identifier)
                normalized = new_identifier.strip().lower()
                if normalized:
                    system_debug(
                        f"Reset duplicated CharonOp node {duplicate.name()} with new id {normalized} (kept {keeper.name()} for {node_id})."
                    )
                else:
                    system_warning(
                        f"Detected duplicate CharonOp node {duplicate.name()} but could not assign a new id."
                    )
            except Exception as exc:
                system_warning(f"Failed to reset duplicated CharonOp node {duplicate.name()}: {exc}")

    nodes: List[SceneNodeInfo] = []
    for node in candidates:
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
    candidates: List[Any] = []
    for node in nuke_module.allNodes():
        try:
            if node.Class() != NODE_CLASS:
                continue
            if not _has_charon_signature(node):
                continue
            if not node.name().startswith(NODE_PREFIX):
                _ensure_charon_name(node)
            candidates.append(node)
        except Exception:
            continue
    return sorted(candidates, key=_node_sort_key)


def _has_charon_signature(node) -> bool:
    try:
        knob = node.knob("charon_node_id")
    except Exception:
        return False
    return knob is not None


def _ensure_charon_name(node) -> str:
    """Ensure Charon nodes keep the expected prefix even if renamed."""
    original_name = _coerce_str(getattr(node, "name", lambda: "")(), "")
    if original_name.startswith(NODE_PREFIX):
        return original_name

    # Prefer the user's custom suffix if they renamed the node
    name_suffix = original_name
    if NODE_PREFIX in name_suffix:
        name_suffix = name_suffix.split(NODE_PREFIX, 1)[-1]

    candidates = [
        name_suffix,
        _coerce_str(_read_knob_value(node, "charon_workflow_name"), ""),
        _coerce_str(_read_knob_value(node, "charon_node_id"), ""),
        "Charon",
    ]

    safe_suffix = ""
    for candidate in candidates:
        sanitized = sanitize_name(candidate) if candidate else ""
        if sanitized:
            safe_suffix = sanitized
            break

    new_name = f"{NODE_PREFIX}{safe_suffix}" if safe_suffix else NODE_PREFIX.rstrip("_")
    if new_name == original_name:
        return new_name

    try:
        node.setName(new_name)
        system_debug(f"Restored CharonOp prefix for node {original_name!r} -> {new_name!r}")
        return new_name
    except Exception as exc:
        system_warning(f"Failed to restore CharonOp prefix for {original_name!r}: {exc}")
        return original_name



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

    identifier = _resolve_node_identifier(node) or info.name
    signature = (info.status, info.state, round(info.progress, 2))
    last = _SCENE_NODE_SNAPSHOT_CACHE.get(identifier)
    if last != signature:
        _SCENE_NODE_SNAPSHOT_CACHE[identifier] = signature
        system_debug(
            f"Scene node snapshot: {info.name} status={info.status!r} "
            f"state={info.state} progress={info.progress:.02f}"
        )
    return info


def _resolve_node_identifier(node) -> str:
    knob_value = _coerce_str(_read_knob_value(node, "charon_node_id"), "")
    if knob_value:
        return knob_value.strip().lower()[:12]
    try:
        meta_value = node.metadata("charon/node_id")
    except Exception:
        meta_value = ""
    return _coerce_str(meta_value, "").strip().lower()[:12]


def _node_sort_key(node: Any) -> str:
    try:
        return str(node.name() or "").lower()
    except Exception:
        return ""


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
    candidates: List[str] = []
    for value in (
        _coerce_str(_read_knob_value(node, "workflow_path"), ""),
        _read_metadata_str(node, WORKFLOW_PATH_META),
        _coerce_str(_read_knob_value(node, "charon_source_workflow_path"), ""),
        _read_metadata_str(node, SOURCE_WORKFLOW_PATH_META),
    ):
        if value and value not in candidates:
            candidates.append(value)

    for candidate in candidates:
        try:
            if candidate and os.path.exists(candidate):
                return candidate
        except Exception:
            continue

    return candidates[0] if candidates else ""


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
