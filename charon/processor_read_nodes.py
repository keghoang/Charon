"""Nuke Read/ReadGeo presentation helpers used by processor ingestion."""

from __future__ import annotations

import os
import uuid
from typing import Callable, Dict, Iterable, Optional


def assign_read_file(read_node, path: str) -> None:
    """Assign a Read file through Nuke's native user-text parsing path.

    ``setValue`` only changes the file string.  In particular, it does not
    make an existing Read re-probe a movie and update its frame range.  Nuke
    uses ``fromUserText`` for file-browser and drag/drop assignments; using
    the same API keeps CR2D imports consistent with native Reads.
    """
    normalized_path = str(path or "").replace("\\", "/")
    file_knob = read_node["file"]
    from_user_text = getattr(file_knob, "fromUserText", None)
    if callable(from_user_text):
        from_user_text(normalized_path)
        return
    file_knob.setValue(normalized_path)


def batch_navigation_controls(_read_node):
    """Return optional batch controls when that UI is available.

    Batch navigation has never been enabled for imported Read nodes, but the
    ingestion path still uses this hook while preparing grouped outputs.  Keep
    the compatibility boundary explicit so extracting the Read-link helpers
    cannot turn an optional UI feature into a fatal import error.
    """
    return None, None, None


def index_grouped_read_nodes(
    candidates: Iterable,
    *,
    parent_id: str,
    parent_id_resolver: Callable,
    normalize_id: Callable[[str], str],
) -> Dict[str, object]:
    """Index linked Read nodes by their stable, case-insensitive output label."""
    expected_parent = normalize_id(parent_id)
    if not expected_parent:
        return {}
    label_map: Dict[str, object] = {}
    for candidate in candidates:
        try:
            candidate_parent = normalize_id(parent_id_resolver(candidate))
        except Exception:
            candidate_parent = ""
        if candidate_parent != expected_parent:
            continue
        try:
            output_label = str(candidate.metadata("charon/output_label") or "").strip()
        except Exception:
            output_label = ""
        if not output_label:
            try:
                knob = candidate.knob("charon_output_label")
                output_label = str(knob.value() or "").strip() if knob is not None else ""
            except Exception:
                output_label = ""
        normalized_label = output_label.lower()
        if normalized_label and normalized_label not in label_map:
            label_map[normalized_label] = candidate
    return label_map


def set_output_label(nuke_module, read_node, label_text: str) -> None:
    """Persist a grouped output label in both metadata and a hidden knob."""
    try:
        read_node.setMetaData("charon/output_label", label_text or "")
    except Exception:
        pass
    label_knob = _ensure_hidden_string_knob(
        nuke_module,
        read_node,
        "charon_output_label",
        "Charon Output Label",
    )
    if label_knob is not None:
        try:
            label_knob.setValue(label_text or "")
        except Exception:
            pass


def remove_linked_placeholder_nodes(
    nuke_module,
    candidates: Iterable,
    *,
    parent_id: str,
    placeholder_path: str,
    parent_id_resolver: Callable,
    normalize_id: Callable[[str], str],
    unlink_node: Callable,
    log_debug: Callable,
) -> int:
    """Unlink and delete placeholder Reads owned by one CharonOp."""
    expected_parent = normalize_id(parent_id)
    normalized_placeholder = str(placeholder_path or "").replace("\\", "/").lower()
    if not expected_parent or not normalized_placeholder:
        return 0
    removed = 0
    for candidate in candidates:
        if candidate is None:
            continue
        try:
            candidate_parent = normalize_id(parent_id_resolver(candidate))
        except Exception:
            candidate_parent = ""
        if candidate_parent != expected_parent:
            continue
        try:
            file_value = str(candidate["file"].value() or "").strip()
        except Exception:
            file_value = ""
        if file_value.replace("\\", "/").lower() != normalized_placeholder:
            continue
        try:
            unlink_node(candidate)
        except Exception:
            pass
        try:
            nuke_module.delete(candidate)
            removed += 1
            log_debug("Removed placeholder CharonRead node before importing outputs.")
        except Exception:
            pass
    return removed


def update_read_label(
    read_node,
    *,
    parent_id: str,
    read_id: str,
    label_text: Optional[str] = None,
) -> None:
    if read_node is None:
        return
    if label_text is None:
        try:
            output_label = str(read_node.metadata("charon/output_label") or "").strip()
        except Exception:
            output_label = ""
        if not output_label:
            try:
                knob = read_node.knob("charon_output_label")
                output_label = str(knob.value() or "").strip() if knob is not None else ""
            except Exception:
                output_label = ""
        try:
            file_display = os.path.basename(str(read_node["file"].value() or "").strip())
        except Exception:
            file_display = ""
        parts = []
        if output_label:
            parts.append(f"Output: {output_label}")
        if file_display:
            parts.append(f"File: {file_display}")
        parts.append(f"Charon Parent: {parent_id or 'N/A'}")
        parts.append(f"Read ID: {read_id or 'N/A'}")
        label_text = "\n".join(parts)
    try:
        label_knob = read_node["label"]
    except Exception:
        label_knob = None
    if label_knob is not None:
        try:
            label_knob.setValue(label_text or "")
        except Exception:
            pass


def update_read_info(
    nuke_module,
    read_node,
    *,
    parent_id: str,
    read_id: str,
    state: str,
    color_hex: Optional[str],
) -> None:
    if read_node is None:
        return
    created_info_tab = False
    try:
        info_tab = read_node.knob("charon_info_tab")
    except Exception:
        info_tab = None
    if info_tab is None:
        try:
            info_tab = nuke_module.Tab_Knob("charon_info_tab", "Charon Info")
            read_node.addKnob(info_tab)
            created_info_tab = True
        except Exception:
            info_tab = None
    try:
        info_text = read_node.knob("charon_info_text")
    except Exception:
        info_text = None
    if info_text is None and info_tab is not None:
        try:
            info_text = nuke_module.Text_Knob("charon_info_text", "Metadata", "")
            read_node.addKnob(info_text)
        except Exception:
            info_text = None
    summary = [
        f"Parent ID: {parent_id or 'N/A'}",
        f"Read Node ID: {read_id or 'N/A'}",
        f"Status: {state or 'N/A'}",
    ]
    if color_hex:
        summary.append(f"Color: {color_hex.upper()}")
    if info_text is not None:
        try:
            info_text.setValue("\n".join(summary))
        except Exception:
            pass
    if created_info_tab:
        try:
            read_node.setControlPanelTab("Read")
        except Exception:
            pass


def link_read_node(
    nuke_module,
    source_node,
    read_node,
    *,
    parent_id: str,
    link_anchor_value: float,
    current_state: str,
    write_metadata,
    read_id_resolver,
    update_info,
    update_label,
    apply_status,
    refresh_linked_info,
    load_status_payload,
    save_status_payload,
) -> str:
    """Link an imported Read/ReadGeo node to its CharonOp and persist the link."""
    if read_node is None:
        return ""
    read_id = read_id_resolver(read_node) or uuid.uuid4().hex[:12].lower()

    if parent_id:
        try:
            read_node.setMetaData("charon/parent_id", parent_id)
        except Exception:
            pass
        parent_knob = _ensure_hidden_string_knob(
            nuke_module,
            read_node,
            "charon_parent_id",
            "Charon Parent ID",
        )
        if parent_knob is not None:
            try:
                parent_knob.setValue(parent_id)
            except Exception:
                pass

    try:
        read_node.setMetaData("charon/read_id", read_id)
    except Exception:
        pass
    read_id_knob = _ensure_hidden_string_knob(
        nuke_module,
        read_node,
        "charon_read_id",
        "Charon Read ID",
    )
    if read_id_knob is not None:
        try:
            read_id_knob.setValue(read_id)
        except Exception:
            pass

    try:
        anchor_knob = read_node.knob("charon_link_anchor")
    except Exception:
        anchor_knob = None
    if anchor_knob is None:
        try:
            anchor_knob = nuke_module.Double_Knob("charon_link_anchor", "Charon Link Anchor")
            anchor_knob.setFlag(nuke_module.NO_ANIMATION)
            anchor_knob.setFlag(nuke_module.INVISIBLE)
            read_node.addKnob(anchor_knob)
        except Exception:
            anchor_knob = None
    if anchor_knob is not None:
        try:
            anchor_knob.setExpression(f"{source_node.fullName()}.charon_link_anchor")
        except Exception:
            try:
                anchor_knob.clearAnimated()
            except Exception:
                pass
            try:
                anchor_knob.setValue(link_anchor_value)
            except Exception:
                pass

    _set_knob_value(source_node, "charon_read_node", read_node.name())
    try:
        write_metadata("charon/read_node", read_node.name())
    except Exception:
        pass
    _set_knob_value(source_node, "charon_read_node_id", read_id)
    try:
        write_metadata("charon/read_node_id", read_id)
    except Exception:
        pass

    # Presentation is best-effort.  Identity and the anchor above are the
    # durable link; a label, info panel, or color failure must not orphan an
    # otherwise valid imported output.
    for callback, args in (
        (update_info, (read_node, read_id, current_state)),
        (update_label, (read_node,)),
        (apply_status, (current_state, read_node)),
        (refresh_linked_info, ()),
    ):
        try:
            callback(*args)
        except Exception:
            pass
    try:
        recreate_knob = source_node.knob("charon_recreate_read")
        if recreate_knob is not None:
            recreate_knob.setEnabled(True)
    except Exception:
        pass

    try:
        payload = load_status_payload()
    except Exception:
        payload = None
    if isinstance(payload, dict) and payload.get("read_node_id") != read_id:
        payload["read_node_id"] = read_id
        try:
            save_status_payload(payload)
        except Exception:
            pass
    return read_id


def unlink_read_node(
    source_node,
    read_node,
    *,
    current_state: str,
    write_metadata,
    update_info,
    update_label,
    apply_status,
    refresh_linked_info,
    load_status_payload,
    save_status_payload,
) -> None:
    """Clear a Read/ReadGeo link and all persisted source-node references."""
    if read_node is None:
        return
    for metadata_key in ("charon/parent_id", "charon/read_id"):
        try:
            read_node.setMetaData(metadata_key, "")
        except Exception:
            pass
    for knob_name, value in (
        ("charon_parent_id", ""),
        ("charon_read_id", ""),
        ("charon_batch_outputs", ""),
        ("charon_batch_index", 0),
        ("charon_batch_label", ""),
    ):
        _set_knob_value(read_node, knob_name, value)

    update_info(read_node, "", current_state)
    update_label(read_node, "")
    _set_knob_value(source_node, "charon_read_node_id", "")
    write_metadata("charon/read_node_id", "")
    refresh_linked_info()
    _set_knob_value(source_node, "charon_read_node", "")
    write_metadata("charon/read_node", "")

    try:
        last_output = source_node.knob("charon_last_output")
        last_output_value = last_output.value() if last_output is not None else ""
    except Exception:
        last_output_value = ""
    if not last_output_value:
        try:
            last_output_value = source_node.metadata("charon/last_output")
        except Exception:
            last_output_value = ""
    try:
        recreate_knob = source_node.knob("charon_recreate_read")
        if recreate_knob is not None:
            recreate_knob.setEnabled(bool(str(last_output_value or "").strip()))
    except Exception:
        pass
    apply_status(current_state)

    try:
        anchor_knob = read_node.knob("charon_link_anchor")
    except Exception:
        anchor_knob = None
    if anchor_knob is not None:
        try:
            anchor_knob.clearAnimated()
        except Exception:
            pass
        try:
            anchor_knob.setValue(0.0)
        except Exception:
            pass

    try:
        payload = load_status_payload()
    except Exception:
        payload = None
    if isinstance(payload, dict) and payload.get("read_node_id"):
        payload["read_node_id"] = ""
        try:
            save_status_payload(payload)
        except Exception:
            pass


def ensure_placeholder_read_node(
    nuke_module,
    source_node,
    *,
    parent_id: str,
    workflow_display_name: str,
    placeholder_path: str,
    find_linked_read,
    mark_read,
    sanitize_name,
    log_debug,
) -> None:
    """Create or safely refresh the placeholder Read for a CharonOp."""
    if not placeholder_path or not parent_id:
        return
    placeholder_normalized = placeholder_path.replace("\\", "/").lower()
    existing_node = find_linked_read()
    if existing_node is not None:
        try:
            current_file = str(existing_node["file"].value() or "").strip()
        except Exception:
            current_file = ""
        current_normalized = current_file.replace("\\", "/").lower()
        if not current_normalized or current_normalized == placeholder_normalized:
            try:
                assign_read_file(existing_node, placeholder_path)
                log_debug("Updated existing Read node with placeholder preview.")
            except Exception as exc:
                log_debug(f"Failed to assign placeholder to existing Read node: {exc}", "WARNING")
        else:
            log_debug("Existing Read node already has rendered output; skipping placeholder update.")
        mark_read(existing_node)
        return

    creator_group = source_node.parent() or nuke_module.root()
    try:
        creator_group.begin()
        read_node = nuke_module.createNode("Read", inpanel=False)
    finally:
        try:
            creator_group.end()
        except Exception:
            pass
    read_base = sanitize_name(workflow_display_name, "Workflow")
    try:
        read_node.setName(f"CR2D_{read_base}")
    except Exception:
        try:
            read_node.setName(f"CR2D_{read_base}_{parent_id}")
        except Exception:
            try:
                read_node.setName("CR2D")
            except Exception:
                pass
    try:
        assign_read_file(read_node, placeholder_path)
    except Exception as exc:
        log_debug(f"Failed to assign placeholder file: {exc}", "WARNING")
    try:
        read_node.setXpos(source_node.xpos())
        read_node.setYpos(source_node.ypos() + 60)
    except Exception:
        pass
    try:
        read_node.setSelected(False)
    except Exception:
        pass
    mark_read(read_node)
    log_debug("Created placeholder Read node.")


def _ensure_hidden_string_knob(nuke_module, node, name: str, label: str):
    try:
        knob = node.knob(name)
    except Exception:
        knob = None
    if knob is not None:
        return knob
    try:
        knob = nuke_module.String_Knob(name, label, "")
        knob.setFlag(nuke_module.NO_ANIMATION)
        knob.setFlag(nuke_module.INVISIBLE)
        node.addKnob(knob)
        return knob
    except Exception:
        return None


def _set_knob_value(node, name: str, value) -> None:
    try:
        knob = node.knob(name)
        if knob is not None:
            knob.setValue(value)
    except Exception:
        pass
