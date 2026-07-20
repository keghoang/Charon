"""Headless accessors for Charon node identity state."""

from __future__ import annotations

import time
from typing import Any, Callable, List, Optional, Tuple

from . import config
from .node_factory import (
    generate_charon_node_id,
    reset_charon_node_state,
    update_charon_node_identity,
)
from .paths import get_nuke_script_hash


class NodeMetadataWriter:
    """Callable metadata adapter that supports both Nuke setter spellings."""

    def __init__(self, node, *, log_warning: Optional[Callable[[str], None]] = None) -> None:
        self._node = node
        self._log_warning = log_warning
        self._warning_emitted = False
        if hasattr(node, "setMetaData"):
            self._writer = node.setMetaData
        elif hasattr(node, "setMetadata"):
            self._writer = node.setMetadata
        else:
            self._writer = None

    def __call__(self, key: str, value: Any) -> bool:
        if self._writer is None:
            self._warning_emitted = True
            return False
        try:
            self._writer(key, value)
            return True
        except Exception as exc:
            if not self._warning_emitted and self._log_warning:
                self._log_warning(f"Failed to persist metadata '{key}': {exc}")
            self._warning_emitted = True
            return False


class LinkedOutputRepository:
    """Resolve Read/ReadGeo nodes linked to one CharonOp."""

    def __init__(self, nuke_module, node, parent_id: str) -> None:
        self._nuke = nuke_module
        self._node = node
        self._parent_id = normalize_node_id(parent_id)

    def iter_candidates(self) -> List[Any]:
        candidates: List[Any] = []
        for class_name in ("Read", "ReadGeo2"):
            try:
                candidates.extend(list(self._nuke.allNodes(class_name)))
            except Exception:
                pass
        return candidates

    @staticmethod
    def parent_id(candidate) -> str:
        try:
            metadata_value = candidate.metadata("charon/parent_id")
        except Exception:
            metadata_value = None
        if metadata_value is not None:
            try:
                value = normalize_node_id(str(metadata_value))
            except Exception:
                value = ""
            if value:
                return value
        return normalize_node_id(safe_knob_value(candidate, "charon_parent_id"))

    @staticmethod
    def read_id(candidate) -> str:
        try:
            metadata_value = candidate.metadata("charon/read_id")
        except Exception:
            metadata_value = None
        read_id = normalize_node_id(metadata_value)
        if read_id:
            return read_id
        return normalize_node_id(safe_knob_value(candidate, "charon_read_id"))

    def find_by_id(self, read_id: str):
        if not read_id:
            return None
        for candidate in self.iter_candidates():
            if self.read_id(candidate) == read_id:
                return candidate
        return None

    def stored_read_id(self) -> str:
        value = normalize_node_id(safe_knob_value(self._node, "charon_read_node_id"))
        if value:
            return value
        try:
            return normalize_node_id(self._node.metadata("charon/read_node_id"))
        except Exception:
            return ""

    def find_for_parent(self):
        if not self._parent_id:
            return None
        stored = self.stored_read_id()
        candidate = self.find_by_id(stored)
        if candidate is not None:
            return candidate
        for option in self.iter_candidates():
            if self.parent_id(option) == self._parent_id:
                return option
        fallback_name = safe_knob_value(self._node, "charon_read_node")
        if fallback_name:
            try:
                fallback = self._nuke.toNode(str(fallback_name))
            except Exception:
                fallback = None
            if fallback is not None and getattr(fallback, "Class", lambda: "")() in {
                "Read",
                "ReadGeo2",
            }:
                return fallback
        return None

    def find_linked(self):
        candidate = self.find_by_id(self.stored_read_id())
        return candidate if candidate is not None else self.find_for_parent()

    def collect_targets(self) -> List[Any]:
        if not self._parent_id:
            return []
        targets = []
        for candidate in self.iter_candidates():
            if self.parent_id(candidate) == self._parent_id:
                targets.append(candidate)
        return targets


def apply_status_to_outputs(
    nuke_module,
    node,
    state: str,
    linked_outputs: LinkedOutputRepository,
    *,
    tile_color: int,
    gl_color=None,
    log_debug: Optional[Callable[[str], None]] = None,
    ensure_read_info: Optional[Callable[[Any, str, str], None]] = None,
    read_node_override=None,
) -> None:
    """Apply lifecycle colors and metadata to a CharonOp and its linked reads."""
    def _apply_to_target(target) -> None:
        if target is None:
            return
        try:
            target.setMetaData("charon/status", state or "")
        except Exception:
            pass
        for knob_name, value in (
            ("tile_color", tile_color),
            ("gl_color", list(gl_color) if gl_color is not None else None),
        ):
            if value is None:
                continue
            try:
                knob = target[knob_name]
            except Exception:
                knob = None
            if knob is not None:
                try:
                    try:
                        knob.clearAnimated()
                    except Exception:
                        pass
                    knob.setValue(value)
                except Exception:
                    pass
        try:
            is_read = target.Class() in {"Read", "ReadGeo2"}
        except Exception:
            is_read = False
        if is_read and ensure_read_info:
            try:
                ensure_read_info(target, linked_outputs.read_id(target), state)
            except Exception:
                pass

    targets = []
    if read_node_override is not None:
        targets.append(read_node_override)
    else:
        candidate = linked_outputs.find_linked()
        if candidate is not None:
            targets.append(candidate)
    for candidate in linked_outputs.collect_targets():
        if candidate not in targets:
            targets.append(candidate)

    if log_debug:
        try:
            target_names = [
                f"{target.name()}[{linked_outputs.parent_id(target)}]"
                for target in targets
            ]
            log_debug(f"Apply status {state} to reads: {', '.join(target_names) or 'none'}")
        except Exception:
            pass

    try:
        recreate_knob = node.knob("charon_recreate_read")
    except Exception:
        recreate_knob = None
    if recreate_knob is not None:
        last_output = safe_knob_value(node, "charon_last_output")
        if not last_output:
            try:
                last_output = node.metadata("charon/last_output")
            except Exception:
                last_output = ""
        try:
            recreate_knob.setEnabled(bool(str(last_output or "").strip()))
        except Exception:
            pass

    def _apply_all() -> None:
        _apply_to_target(node)
        for target in targets:
            _apply_to_target(target)

    try:
        nuke_module.executeInMainThread(_apply_all)
    except Exception:
        _apply_all()


def normalize_node_id(value: Optional[str], *, max_length: Optional[int] = None) -> str:
    if not value:
        return ""
    text = str(value).strip().lower()
    if not text:
        return ""
    configured_length = getattr(config, "CHARON_NODE_ID_LENGTH", 12)
    length = max(4, int(configured_length if max_length is None else max_length))
    return text[:length]


def normalize_script_hash(value: Optional[str]) -> str:
    if not value:
        return ""
    return str(value).strip().lower()


def safe_knob_value(owner, knob_name: str) -> Any:
    try:
        knob = owner.knob(knob_name)
    except Exception:
        return None
    if knob is None:
        return None
    try:
        return knob.value()
    except Exception:
        return None


def read_script_hash(owner) -> str:
    stored = normalize_script_hash(safe_knob_value(owner, "charon_script_hash"))
    if stored:
        return stored
    try:
        return normalize_script_hash(owner.metadata("charon/script_hash"))
    except Exception:
        return ""


def ensure_link_anchor_value(
    node,
    node_id: str,
    *,
    write_metadata: Callable[[str, Any], bool],
) -> float:
    """Ensure a stable numeric anchor used to reconnect copied output nodes."""
    try:
        anchor_knob = node.knob("charon_link_anchor")
    except Exception:
        anchor_knob = None
    anchor_value = None
    if anchor_knob is not None:
        try:
            anchor_value = float(anchor_knob.value())
        except Exception:
            pass
    if not anchor_value:
        try:
            anchor_value = int(node_id, 16) / float(16 ** len(node_id))
        except Exception:
            anchor_value = (time.time() % 1.0) or 0.5
        if anchor_knob is not None:
            try:
                anchor_knob.setValue(anchor_value)
            except Exception:
                pass
    write_metadata("charon/link_anchor", anchor_value or "")
    return anchor_value or 0.0


def update_last_output_state(
    node,
    path_value: Optional[str],
    *,
    write_metadata: Callable[[str, Any], bool],
) -> None:
    """Persist the latest output and enable recreation only when output exists."""
    normalized_path = path_value or ""
    try:
        output_knob = node.knob("charon_last_output")
        if output_knob is not None:
            output_knob.setValue(normalized_path)
    except Exception:
        pass
    write_metadata("charon/last_output", normalized_path)
    try:
        recreate_knob = node.knob("charon_recreate_read")
    except Exception:
        recreate_knob = None
    if recreate_knob is not None:
        try:
            recreate_knob.setEnabled(bool(path_value))
        except Exception:
            pass


def ensure_charon_node_identity(
    nuke_module,
    node,
    *,
    write_metadata: Callable[[str, str], bool],
    generate_id=generate_charon_node_id,
    reset_node_state=reset_charon_node_state,
    update_identity=update_charon_node_identity,
    script_hash_resolver=get_nuke_script_hash,
) -> str:
    """Resolve, migrate, deduplicate, and persist one Charon node identity."""
    node_id = normalize_node_id(safe_knob_value(node, "charon_node_id"))
    if not node_id:
        try:
            node_id = normalize_node_id(node.metadata("charon/node_id"))
        except Exception:
            node_id = ""
        if node_id:
            try:
                knob = node.knob("charon_node_id")
                if knob is not None:
                    knob.setValue(node_id)
            except Exception:
                pass

    current_script_hash = normalize_script_hash(script_hash_resolver(nuke_module))
    stored_script_hash = read_script_hash(node)
    if current_script_hash and stored_script_hash and stored_script_hash != current_script_hash:
        previous_id = node_id
        node_id = generate_id(current_script_hash)
        update_identity(node, node_id, current_script_hash)
        update_linked_parent_ids(nuke_module, previous_id, node_id)
    elif current_script_hash and not stored_script_hash:
        update_identity(node, "", current_script_hash)

    node_id = deduplicate_node_id(
        nuke_module,
        node,
        node_id,
        reset_node_state=reset_node_state,
    )
    if not node_id:
        node_id = generate_id(current_script_hash)
    update_identity(node, node_id, current_script_hash)
    write_metadata("charon/node_id", node_id or "")
    sync_anchored_output_nodes(nuke_module, node, node_id)
    return node_id


def update_linked_parent_ids(nuke_module, old_id: str, new_id: str) -> None:
    """Move linked output nodes from one normalized Charon parent ID to another."""
    normalized_old = normalize_node_id(old_id)
    normalized_new = normalize_node_id(new_id)
    if not normalized_old or not normalized_new or normalized_old == normalized_new:
        return

    for class_name in ("Read", "ReadGeo2", "Group"):
        try:
            candidates = list(nuke_module.allNodes(class_name))
        except Exception:
            continue
        for candidate in candidates:
            try:
                parent_value = normalize_node_id(candidate.metadata("charon/parent_id"))
            except Exception:
                parent_value = ""
            if parent_value != normalized_old:
                parent_value = normalize_node_id(safe_knob_value(candidate, "charon_parent_id"))
            if parent_value != normalized_old:
                continue
            try:
                candidate.setMetaData("charon/parent_id", normalized_new)
            except Exception:
                pass
            try:
                parent_knob = candidate.knob("charon_parent_id")
            except Exception:
                parent_knob = None
            if parent_knob is not None:
                try:
                    parent_knob.setValue(normalized_new)
                except Exception:
                    pass


def collect_linked_output_ids(nuke_module, parent_id: str) -> List[str]:
    """Collect stable linked-output identifiers for one Charon parent node."""
    normalized_parent = normalize_node_id(parent_id)
    if not normalized_parent:
        return []
    try:
        candidates = list(nuke_module.allNodes())
    except Exception:
        return []
    identifiers: List[str] = []
    for candidate in candidates:
        try:
            parent_value = normalize_node_id(candidate.metadata("charon/parent_id"))
        except Exception:
            parent_value = ""
        if parent_value != normalized_parent:
            parent_value = normalize_node_id(safe_knob_value(candidate, "charon_parent_id"))
        if parent_value != normalized_parent:
            continue

        getters = (
            lambda: candidate.metadata("charon/read_id"),
            lambda: candidate.metadata("charon/read_node_id"),
            lambda: safe_knob_value(candidate, "charon_read_id"),
            lambda: safe_knob_value(candidate, "charon_read_node_id"),
            candidate.name,
        )
        identifier = ""
        for getter in getters:
            try:
                identifier = normalize_node_id(getter())
            except Exception:
                identifier = ""
            if identifier:
                break
        if identifier and identifier not in identifiers:
            identifiers.append(identifier)
    return identifiers


def refresh_linked_output_info(nuke_module, node, parent_id: str) -> List[str]:
    """Refresh the node's read-ID information knob and return linked IDs."""
    try:
        info_knob = node.knob("charon_read_id_info")
    except Exception:
        info_knob = None
    identifiers = collect_linked_output_ids(nuke_module, parent_id)
    if info_knob is None:
        return identifiers
    display = "\n".join(identifiers) if identifiers else "Not linked"
    try:
        info_knob.setValue(display)
    except Exception:
        try:
            info_knob.setText(display)
        except Exception:
            pass
    return identifiers


def sync_anchored_output_nodes(nuke_module, node, node_id: str) -> None:
    """Repair parent IDs for outputs whose link-anchor expression targets a node."""
    if not node_id:
        return
    try:
        node_full_name = node.fullName()
    except Exception:
        node_full_name = ""
    try:
        node_name = node.name()
    except Exception:
        node_name = ""
    if not node_full_name and not node_name:
        return

    def _matches_parent(candidate) -> bool:
        try:
            parent_value = normalize_node_id(candidate.metadata("charon/parent_id"))
        except Exception:
            parent_value = ""
        if not parent_value:
            parent_value = normalize_node_id(safe_knob_value(candidate, "charon_parent_id"))
        return parent_value == normalize_node_id(node_id)

    def _set_contact_sheet(candidate_name: str) -> None:
        try:
            knob = node.knob("charon_contact_sheet")
        except Exception:
            knob = None
        if knob is None:
            return
        try:
            current_name = str(knob.value() or "").strip()
        except Exception:
            current_name = ""
        if current_name:
            try:
                current = nuke_module.toNode(current_name)
            except Exception:
                current = None
            if current is not None and _matches_parent(current):
                return
        try:
            knob.setValue(candidate_name)
        except Exception:
            pass

    try:
        candidates = list(nuke_module.allNodes())
    except Exception:
        candidates = []
    for candidate in candidates:
        if candidate is None or candidate is node:
            continue
        try:
            anchor_knob = candidate.knob("charon_link_anchor")
        except Exception:
            anchor_knob = None
        if anchor_knob is None:
            continue
        try:
            expression = anchor_knob.expression()
        except Exception:
            expression = ""
        if not expression or not (
            (node_full_name and node_full_name in expression)
            or (node_name and node_name in expression)
        ):
            continue
        try:
            candidate.setMetaData("charon/parent_id", node_id)
        except Exception:
            pass
        try:
            parent_knob = candidate.knob("charon_parent_id")
        except Exception:
            parent_knob = None
        if parent_knob is not None:
            try:
                parent_knob.setValue(node_id)
            except Exception:
                pass
        try:
            is_contact_sheet = (
                candidate.Class() == "Group"
                and candidate.knob("charon_read_id") is not None
            )
        except Exception:
            is_contact_sheet = False
        if is_contact_sheet:
            _set_contact_sheet(candidate.name())


def deduplicate_node_id(
    nuke_module,
    node,
    candidate: str,
    *,
    reset_node_state,
) -> str:
    normalized = normalize_node_id(candidate)
    if not normalized:
        return ""
    try:
        nodes_with_id: List[Any] = []
        for other in nuke_module.allNodes("Group"):
            other_id = normalize_node_id(safe_knob_value(other, "charon_node_id"))
            if not other_id:
                try:
                    meta_val = other.metadata("charon/node_id")
                except Exception:
                    meta_val = ""
                other_id = normalize_node_id(meta_val)
            if other_id == normalized:
                nodes_with_id.append(other)
    except Exception:
        return normalized

    if len(nodes_with_id) <= 1:
        return normalized

    def _node_sort_key(target) -> str:
        try:
            return str(target.name() or "").lower()
        except Exception:
            return ""

    def _has_value(value: Optional[str]) -> bool:
        if value is None:
            return False
        try:
            return bool(str(value).strip())
        except Exception:
            return False

    def _node_has_outputs(target) -> bool:
        if _has_value(safe_knob_value(target, "charon_last_output")):
            return True
        try:
            if _has_value(target.metadata("charon/last_output")):
                return True
        except Exception:
            pass
        for knob_name in ("charon_read_node", "charon_contact_sheet"):
            if _has_value(safe_knob_value(target, knob_name)):
                return True
        for meta_key in ("charon/read_node", "charon/contact_sheet"):
            try:
                if _has_value(target.metadata(meta_key)):
                    return True
            except Exception:
                pass
        return False

    nodes_with_outputs = [item for item in nodes_with_id if _node_has_outputs(item)]
    if nodes_with_outputs:
        nodes_with_outputs.sort(key=_node_sort_key)
        if node in nodes_with_outputs and len(nodes_with_outputs) == 1:
            keeper = node
        else:
            keeper = nodes_with_outputs[0]
    else:
        if node in nodes_with_id:
            keeper = node
        else:
            nodes_with_id.sort(key=_node_sort_key)
            keeper = nodes_with_id[0]

    def _node_pos(target) -> Optional[Tuple[float, float]]:
        if target is None:
            return None
        try:
            return (float(target.xpos()), float(target.ypos()))
        except Exception:
            return None

    def _distance_sq(a: Optional[Tuple[float, float]], b: Optional[Tuple[float, float]]) -> Optional[float]:
        if a is None or b is None:
            return None
        dx = a[0] - b[0]
        dy = a[1] - b[1]
        return dx * dx + dy * dy

    def _match_parent(candidate_node, parent_id: str) -> bool:
        if not parent_id:
            return False
        normalized_parent = normalize_node_id(parent_id)
        if not normalized_parent:
            return False
        try:
            meta_val = normalize_node_id(candidate_node.metadata("charon/parent_id"))
        except Exception:
            meta_val = ""
        if meta_val == normalized_parent:
            return True
        knob_val = normalize_node_id(safe_knob_value(candidate_node, "charon_parent_id"))
        return knob_val == normalized_parent

    def _looks_like_contact_sheet_group(candidate_node) -> bool:
        try:
            if candidate_node.Class() != "Group":
                return False
        except Exception:
            return False
        try:
            if candidate_node.knob("charon_read_id") is not None:
                return True
        except Exception:
            pass
        try:
            meta_val = candidate_node.metadata("charon/read_id")
            if meta_val:
                return True
        except Exception:
            pass
        try:
            return "ContactSheet" in (candidate_node.name() or "")
        except Exception:
            return False

    def _reassign_outputs_for_duplicate(duplicate_node, keeper_node, old_id: str, new_id: str) -> None:
        if not old_id or not new_id:
            return
        dup_pos = _node_pos(duplicate_node)
        keep_pos = _node_pos(keeper_node)
        try:
            candidates = list(nuke_module.allNodes("Read")) + list(nuke_module.allNodes("ReadGeo2")) + list(nuke_module.allNodes("Group"))
        except Exception:
            candidates = []
        for candidate_node in candidates:
            if candidate_node is None or candidate_node is duplicate_node or candidate_node is keeper_node:
                continue
            try:
                cls_name = candidate_node.Class()
            except Exception:
                cls_name = ""
            if cls_name == "Group" and not _looks_like_contact_sheet_group(candidate_node):
                continue
            if not _match_parent(candidate_node, old_id):
                continue
            cand_pos = _node_pos(candidate_node)
            if keep_pos is not None and dup_pos is not None:
                dist_dup = _distance_sq(cand_pos, dup_pos)
                dist_keep = _distance_sq(cand_pos, keep_pos)
                if dist_dup is None or dist_keep is None:
                    continue
                if dist_dup > dist_keep:
                    continue
            try:
                candidate_node.setMetaData("charon/parent_id", new_id)
            except Exception:
                pass
            try:
                parent_knob = candidate_node.knob("charon_parent_id")
            except Exception:
                parent_knob = None
            if parent_knob is not None:
                try:
                    parent_knob.setValue(new_id)
                except Exception:
                    pass
            if cls_name == "Group" and _looks_like_contact_sheet_group(candidate_node):
                try:
                    sheet_knob = duplicate_node.knob("charon_contact_sheet")
                except Exception:
                    sheet_knob = None
                if sheet_knob is not None:
                    try:
                        sheet_knob.setValue(candidate_node.name())
                    except Exception:
                        pass

    for duplicate in nodes_with_id:
        if duplicate is keeper:
            continue
        try:
            new_identifier = reset_node_state(duplicate) or ""
        except Exception:
            new_identifier = ""
        if new_identifier:
            try:
                _reassign_outputs_for_duplicate(duplicate, keeper, normalized, new_identifier)
            except Exception:
                pass
        if duplicate is node:
            normalized = normalize_node_id(new_identifier)

    if keeper is node:
        refreshed = normalize_node_id(safe_knob_value(node, "charon_node_id"))
        return refreshed or normalized

    if node in nodes_with_id and node is not keeper:
        refreshed = normalize_node_id(safe_knob_value(node, "charon_node_id"))
        if refreshed:
            return refreshed
        try:
            regenerated = reset_node_state(node) or ""
        except Exception:
            regenerated = ""
        return normalize_node_id(regenerated)

    return normalized
