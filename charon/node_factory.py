import json
import time
import uuid
from typing import Any, Dict, List, Tuple

from .utilities import status_to_gl_color, status_to_tile_color


def sanitize_name(name):
    return "".join(c if c.isalnum() or c == "_" else "_" for c in name)


def _generate_charon_node_id() -> str:
    """Return a short, human-friendly identifier for Charon nodes."""
    return uuid.uuid4().hex[:12].lower()


def _build_default_status_payload(
    workflow_name: str,
    workflow_path: str,
    node_id: str,
) -> Dict[str, Any]:
    """Return the default status payload stored on freshly created nodes."""
    return {
        "status": "Ready",
        "progress": 0.0,
        "message": "Awaiting processing",
        "updated_at": time.time(),
        "workflow_name": workflow_name,
        "workflow_path": workflow_path or "",
        "auto_import": True,
        "runs": [],
        "node_id": node_id,
        "read_node_id": "",
    }


def _default_crop_box(nuke_module=None) -> Tuple[float, float, float, float]:
    """
    Return a best-effort default crop box using the current root format.
    Falls back to a 1920x1080 frame when the format is unavailable.
    """
    module = nuke_module
    if module is None:
        try:
            import nuke as module  # type: ignore
        except Exception:
            module = None

    width = 1920.0
    height = 1080.0
    if module is not None:
        try:
            root = module.root()
        except Exception:
            root = None
        try:
            fmt = root.format() if root else None
        except Exception:
            fmt = None
        if fmt is not None:
            try:
                width = float(fmt.width())
                height = float(fmt.height())
            except Exception:
                pass

    return (0.0, 0.0, width, height)


def create_charon_group_node(
    nuke,
    workflow_name,
    workflow_data,
    inputs,
    temp_dir,
    process_script,
    workflow_path=None,
    parameters=None,
    recreate_script=None,
    source_workflow_path=None,
    validated=False,
    local_state=None,
):
    inputs = list(inputs or [])
    node = nuke.createNode("Group", inpanel=False)

    safe_name = sanitize_name(workflow_name) or "Charon"
    node.setName(f"CharonOp_{safe_name}")

    try:
        node.setLabel("CharonOp Node\nWorkflow: {}\\nInputs: {}".format(len(workflow_data), len(inputs)))
    except Exception:
        pass

    node.begin()
    internal_inputs = []
    image_fallback_index = None
    for index, input_def in enumerate(inputs):
        input_clone = dict(input_def)
        input_clone["index"] = index
        inputs[index] = input_clone

        input_node = nuke.nodes.Input()
        input_node.setName(f"Input_{index + 1}")
        socket_name = sanitize_name(input_clone.get("name", f"Input_{index + 1}"))
        if not socket_name:
            socket_name = f"Input_{index + 1}"
        try:
            input_node["name"].setValue(socket_name)
        except Exception:
            pass
        try:
            input_node["label"].setValue(input_clone.get("name", socket_name))
        except Exception:
            pass
        internal_inputs.append(input_node)
        if (
            image_fallback_index is None
            and str(input_clone.get("type", "")).lower() == "image"
        ):
            image_fallback_index = len(internal_inputs) - 1

    output_node = nuke.nodes.Output()
    if internal_inputs:
        target_index = 0
        if image_fallback_index is not None:
            target_index = image_fallback_index
        output_node.setInput(0, internal_inputs[target_index])
    node.end()

    parameter_knobs, normalized_parameters = _prepare_parameter_controls(nuke, parameters or [])

    try:
        setup_tab = node.knob("User")
    except Exception:
        setup_tab = None
    if setup_tab is not None:
        try:
            setup_tab.setName("charon_setup_tab")
        except Exception:
            pass
        try:
            setup_tab.setLabel("Setup")
        except Exception:
            pass
    else:
        setup_tab = nuke.Tab_Knob("charon_setup_tab", "Setup")
        node.addKnob(setup_tab)

    if parameter_knobs:
        for knob in parameter_knobs:
            node.addKnob(knob)
    else:
        placeholder = nuke.Text_Knob(
            "charon_param_placeholder",
            "",
            "No exposed parameters yet.\nUse Edit Workflow Metadata to add parameters."
        )
        node.addKnob(placeholder)

    read_store_knob = nuke.String_Knob("charon_read_node", "Read Node", "")
    _hide_knob(read_store_knob, nuke)
    node.addKnob(read_store_knob)

    cs_store_knob = nuke.String_Knob("charon_contact_sheet", "Contact Sheet", "")
    _hide_knob(cs_store_knob, nuke)
    node.addKnob(cs_store_knob)

    setup_label = nuke.Text_Knob("charon_setup_label", "Processing Controls", "")
    node.addKnob(setup_label)

    batch_knob = nuke.Int_Knob("charon_batch_count", "Batch Count", 1)
    batch_knob.setFlag(nuke.NO_ANIMATION)
    try:
        batch_knob.setRange(1, 64)
    except Exception:
        pass
    try:
        batch_knob.setValue(1)
    except Exception:
        pass
    try:
        batch_knob.setTooltip("Number of times to submit the workflow (unique seed per batch).")
    except Exception:
        pass
    batch_knob.setFlag(nuke.STARTLINE)
    node.addKnob(batch_knob)

    use_crop_knob = nuke.Boolean_Knob("charon_use_crop", "Use Crop", False)
    use_crop_knob.setFlag(nuke.NO_ANIMATION)
    use_crop_knob.setFlag(nuke.STARTLINE)
    try:
        use_crop_knob.setTooltip("Enable cropping inputs to the bounding box before submission.")
    except Exception:
        pass
    node.addKnob(use_crop_knob)

    crop_bbox_knob = nuke.BBox_Knob("charon_crop_bbox", "Crop Box")
    crop_bbox_knob.setFlag(nuke.NO_ANIMATION)
    try:
        crop_bbox_knob.setTooltip("Bounding box applied when Use Crop is enabled.")
    except Exception:
        pass
    try:
        crop_bbox_knob.setValue(_default_crop_box(nuke))
    except Exception:
        pass
    node.addKnob(crop_bbox_knob)

    process_knob = nuke.PyScript_Knob("process", "Execute")
    process_knob.setCommand(process_script)
    process_knob.setFlag(nuke.STARTLINE)
    try:
        process_knob.setColor(0x2E8BFEFF)
    except Exception:
        pass
    node.addKnob(process_knob)

    select_board_knob = nuke.PyScript_Knob(
        "charon_focus_board",
        "Select in CharonBoard",
        "\n".join(
            (
                "import nuke",
                "try:",
                "    from charon.ui.window_manager import WindowManager",
                "    current_node = nuke.thisNode()",
                "    WindowManager.focus_charon_board_node(current_node.name())",
                "except Exception:",
                "    pass",
            )
        ),
    )
    try:
        select_board_knob.setTooltip("Highlight this node inside CharonBoard.")
    except Exception:
        pass
    select_board_knob.clearFlag(nuke.STARTLINE)
    node.addKnob(select_board_knob)

    open_input_knob = nuke.PyScript_Knob(
        "charon_open_input_folder",
        "Open Output Folder",
        "\n".join(
            (
                "import os",
                "import nuke",
                "",
                "node = nuke.thisNode()",
                "output_path = ''",
                "try:",
                "    knob = node.knob('charon_last_output')",
                "    if knob:",
                "        output_path = knob.value() or ''",
                "except Exception:",
                "    output_path = ''",
                "if not output_path:",
                "    try:",
                "        output_path = node.metadata('charon/last_output') or ''",
                "    except Exception:",
                "        output_path = ''",
                "",
                "if not output_path:",
                "    nuke.message('No output has been generated for this CharonOp yet.')",
                "    output_path = ''",
                "",
                "folder = output_path",
                "if folder and os.path.isfile(folder):",
                "    folder = os.path.dirname(folder)",
                "",
                "if not folder:",
                "    pass",
                "else:",
                "    folder = os.path.abspath(folder)",
                "    if not os.path.isdir(folder):",
                "        nuke.message('Output folder not found:\\n{}'.format(folder or output_path))",
                "    else:",
                "        opened = False",
                "        try:",
                "            from PySide6 import QtGui as _QtGui, QtCore as _QtCore  # type: ignore",
                "            opened = _QtGui.QDesktopServices.openUrl(_QtCore.QUrl.fromLocalFile(folder))",
                "        except Exception:",
                "            try:",
                "                from PySide2 import QtGui as _QtGui, QtCore as _QtCore  # type: ignore",
                "                opened = _QtGui.QDesktopServices.openUrl(_QtCore.QUrl.fromLocalFile(folder))",
                "            except Exception:",
                "                opened = False",
                "        if not opened:",
                "            try:",
                "                os.startfile(folder)",
                "                opened = True",
                "            except Exception:",
                "                opened = False",
                "        if not opened:",
                "            nuke.message('Could not open folder:\\n{}'.format(folder))",
            )
        ),
    )
    open_input_knob.setTooltip("Open the latest output folder generated by this CharonOp.")
    open_input_knob.setFlag(nuke.STARTLINE)
    node.addKnob(open_input_knob)

    recreate_knob = nuke.PyScript_Knob("charon_recreate_read", "Create Contact Sheet")
    recreate_knob.setCommand(recreate_script or "nuke.message('Recreate helper unavailable.')")
    try:
        recreate_knob.setEnabled(False)
    except Exception:
        pass
    node.addKnob(recreate_knob)



    reuse_knob = nuke.Boolean_Knob(
        "charon_reuse_output",
        "Update future iteration in the same Read node",
        True,
    )
    reuse_knob.setFlag(nuke.NO_ANIMATION)
    reuse_knob.setFlag(nuke.STARTLINE)
    try:
        reuse_knob.setValue(1)
    except Exception:
        pass
    try:
        reuse_knob.setTooltip(
            "When enabled, successful runs update the last Read node instead of creating a new one."
        )
    except Exception:
        pass
    node.addKnob(reuse_knob)

    info_tab = nuke.Tab_Knob("charon_info_tab", "Info")
    node.addKnob(info_tab)

    node_id_value = _generate_charon_node_id()

    workflow_knob = nuke.Text_Knob("workflow_data", "Workflow Data", json.dumps(workflow_data))
    _hide_knob(workflow_knob, nuke)
    node.addKnob(workflow_knob)

    inputs_knob = nuke.Text_Knob("input_mapping", "Input Mapping", json.dumps(inputs))
    _hide_knob(inputs_knob, nuke)
    node.addKnob(inputs_knob)

    parameters_knob = nuke.Text_Knob("charon_parameters", "Parameter Mapping", json.dumps(normalized_parameters))
    _hide_knob(parameters_knob, nuke)
    node.addKnob(parameters_knob)

    temp_knob = nuke.String_Knob("charon_temp_dir", "Temp Directory", temp_dir)
    _hide_knob(temp_knob, nuke)
    node.addKnob(temp_knob)

    status_knob = nuke.String_Knob("charon_status", "Status", "Ready")
    _hide_knob(status_knob, nuke)
    node.addKnob(status_knob)

    progress_knob = nuke.Double_Knob("charon_progress", "Progress")
    progress_knob.setRange(0.0, 1.0)
    progress_knob.setValue(0.0)
    _hide_knob(progress_knob, nuke)
    node.addKnob(progress_knob)

    prompt_id_knob = nuke.String_Knob("charon_prompt_id", "Prompt ID", "")
    _hide_knob(prompt_id_knob, nuke)
    node.addKnob(prompt_id_knob)

    prompt_path_knob = nuke.String_Knob("charon_prompt_path", "Prompt Path", "")
    _hide_knob(prompt_path_knob, nuke)
    node.addKnob(prompt_path_knob)

    last_output_knob = nuke.String_Knob("charon_last_output", "Last Output Path", "")
    _hide_knob(last_output_knob, nuke)
    node.addKnob(last_output_knob)

    workflow_name_knob = nuke.String_Knob("charon_workflow_name", "Workflow Name", workflow_name)
    _hide_knob(workflow_name_knob, nuke)
    node.addKnob(workflow_name_knob)

    path_value = workflow_path or ""
    path_knob = nuke.String_Knob("workflow_path", "Workflow Path", path_value)
    _hide_knob(path_knob, nuke)
    node.addKnob(path_knob)

    source_path_value = source_workflow_path or path_value
    source_path_knob = nuke.String_Knob(
        "charon_source_workflow_path",
        "Source Workflow Path",
        source_path_value or "",
    )
    _hide_knob(source_path_knob, nuke)
    node.addKnob(source_path_knob)

    validated_knob = nuke.Int_Knob("charon_validated", "Validated", 1 if validated else 0)
    validated_knob.setFlag(nuke.NO_ANIMATION)
    _hide_knob(validated_knob, nuke)
    node.addKnob(validated_knob)

    try:
        local_state_payload = json.dumps(local_state or {})
    except Exception:
        local_state_payload = "{}"
    local_state_knob = nuke.Text_Knob("charon_local_state", "Local Workflow State", local_state_payload)
    _hide_knob(local_state_knob, nuke)
    node.addKnob(local_state_knob)

    node_id_knob = nuke.String_Knob("charon_node_id", "Node ID", node_id_value)
    _hide_knob(node_id_knob, nuke)
    node.addKnob(node_id_knob)

    try:
        link_anchor_value = int(node_id_value, 16) / float(16 ** len(node_id_value))
    except Exception:
        link_anchor_value = time.time() % 1.0
    link_anchor_knob = nuke.Double_Knob("charon_link_anchor", "Charon Link Anchor")
    link_anchor_knob.setValue(link_anchor_value)
    _hide_knob(link_anchor_knob, nuke)
    node.addKnob(link_anchor_knob)

    read_id_knob = nuke.String_Knob("charon_read_node_id", "Linked Read Node ID", "")
    _hide_knob(read_id_knob, nuke)
    node.addKnob(read_id_knob)

    info_lines = ["Inputs Required:"]
    for input_def in inputs:
        info_lines.append(f"- {input_def.get('name', 'Input')} : {input_def.get('description', '')}")
    info_knob = nuke.Text_Knob("info", "Workflow Info", "\n".join(info_lines))
    node.addKnob(info_knob)

    node_id_info_knob = nuke.Text_Knob("charon_node_id_info", "Charon Node ID", node_id_value)
    node.addKnob(node_id_info_knob)

    read_id_info_knob = nuke.Text_Knob("charon_read_id_info", "Linked Read Node ID", "Not linked")
    node.addKnob(read_id_info_knob)

    ready_tile = status_to_tile_color("Ready")
    ready_gl = status_to_gl_color("Ready") or (0.0, 0.0, 0.0)

    status_payload = _build_default_status_payload(
        workflow_name=workflow_name,
        workflow_path=workflow_path or "",
        node_id=node_id_value,
    )
    try:
        node.setMetaData("charon/status_payload", json.dumps(status_payload))
    except Exception:
        pass
    try:
        node.setMetaData("charon/auto_import", "1")
    except Exception:
        pass
    try:
        node.setMetaData("charon/workflow_name", workflow_name)
        node.setMetaData("charon/workflow_path", workflow_path or "")
        node.setMetaData("charon/source_workflow_path", source_path_value or "")
        node.setMetaData("charon/is_validated", "1" if validated else "0")
        if local_state_payload:
            node.setMetaData("charon/local_state", local_state_payload)
        node.setMetaData("charon/node_id", node_id_value)
        node.setMetaData("charon/read_node_id", "")
    except Exception:
        pass

    try:
        node["tile_color"].setValue(ready_tile)
    except Exception:
        pass

    return node, inputs


def _prepare_parameter_controls(nuke_module, parameters):
    knobs = []
    normalized = []
    used_names = set()

    groups: List[Dict[str, Any]] = []
    group_map: Dict[str, Dict[str, Any]] = {}
    for raw_spec in parameters or []:
        if not isinstance(raw_spec, dict):
            continue

        node_id = str(raw_spec.get('node_id') or '').strip()
        attribute = str(
            raw_spec.get('attribute')
            or raw_spec.get('attribute_key')
            or ''
        ).strip()
        if not node_id or not attribute:
            continue

        node_name = str(raw_spec.get('node_name') or '').strip()
        key = f"{node_id}:{node_name}"
        group = group_map.get(key)
        if group is None:
            group = {
                'node_id': node_id,
                'node_name': node_name,
                'attributes': [],
            }
            group_map[key] = group
            groups.append(group)
        group['attributes'].append(raw_spec)

    attribute_index = 0
    for group_index, group in enumerate(groups):
        if not group['attributes']:
            continue

        group_label = group['node_name'] or f"Node {group['node_id']}"
        header_name = sanitize_name(f"charon_param_group_{group_index + 1}_{group_label}") or f"charon_param_group_{group_index + 1}"
        header_knob = nuke_module.Text_Knob(header_name, group_label, "")
        try:
            header_knob.setFlag(nuke_module.NO_ANIMATION)
        except Exception:
            pass
        knobs.append(header_knob)

        for raw_spec in group['attributes']:
            attribute_index += 1

            attribute = str(
                raw_spec.get('attribute')
                or raw_spec.get('attribute_key')
                or ''
            ).strip()
            label = str(raw_spec.get('label') or '').strip() or attribute
            value_type = str(raw_spec.get('type') or 'string').lower()
            default = raw_spec.get('default')

            base_name = sanitize_name(f"charon_param_{attribute_index}_{label}") or f"charon_param_{attribute_index}"
            knob_name = base_name.lower()
            while knob_name in used_names:
                knob_name = f"{knob_name}_"
            used_names.add(knob_name)

            knob = _create_parameter_knob(
                nuke_module,
                knob_name,
                label,
                value_type,
                default,
                raw_spec.get('choices'),
            )
            if knob is None:
                continue

            tooltip_parts = []
            if group['node_name']:
                tooltip_parts.append(group['node_name'])
            if attribute:
                tooltip_parts.append(attribute)
            try:
                knob.setTooltip(' - '.join(tooltip_parts))
            except Exception:
                pass

            knobs.append(knob)
            normalized.append(
                {
                    'node_id': group['node_id'],
                    'node_name': group['node_name'],
                    'attribute': attribute,
                    'label': label,
                    'type': value_type,
                    'default': default,
                    'value': raw_spec.get('value'),
                    'aliases': list(raw_spec.get('aliases') or []),
                    'group': group_label,
                    'knob': knob_name,
                }
            )

    return knobs, normalized

def _create_parameter_knob(nuke_module, name, label, value_type, default, choices=None):
    try:
        if choices and isinstance(choices, (list, tuple)) and len(choices) > 0:
            knob = nuke_module.Enumeration_Knob(name, label, list(choices))
            if default in choices:
                knob.setValue(default)
            else:
                knob.setValue(choices[0])
        elif value_type == "boolean":
            knob = nuke_module.Boolean_Knob(name, label)
            knob.setValue(1 if _coerce_bool(default) else 0)
        elif value_type == "integer":
            coerced = _coerce_int(default)
            # Try standard Int_Knob first
            try:
                knob = nuke_module.Int_Knob(name, label)
                knob.setValue(coerced)
                try:
                    span = max(abs(coerced), 10)
                    min_val = coerced - span
                    max_val = coerced + span
                    if min_val == max_val:
                        max_val += 1
                    knob.setSliderFlag(True)
                    knob.setRange(min_val, max_val)
                except Exception:
                    pass
            except Exception:
                # Fallback for large integers (e.g. 64-bit seeds) that overflow Nuke's Int_Knob
                knob = nuke_module.String_Knob(name, label)
                knob.setValue(str(coerced))
        elif value_type == "float":
            knob = nuke_module.Double_Knob(name, label)
            coerced = _coerce_float(default)
            knob.setValue(coerced)
            try:
                span = max(abs(coerced), 1.0)
                min_val = coerced - span
                max_val = coerced + span
                if min_val == max_val:
                    max_val += 1.0
                knob.setRange(min_val, max_val)
            except Exception:
                pass
        else:
            knob = nuke_module.Multiline_Eval_String_Knob(name, label)
            knob.setValue(_coerce_string(default))
            try:
                knob.setHeight(60)
            except Exception:
                pass
        knob.setFlag(nuke_module.NO_ANIMATION)
        return knob
    except Exception:
        return None


def _hide_knob(knob, nuke_module):
    try:
        knob.setFlag(nuke_module.NO_ANIMATION)
    except Exception:
        pass
    try:
        knob.setFlag(nuke_module.INVISIBLE)
    except Exception:
        pass


def reset_charon_node_state(node, node_id: str = "") -> str:
    """
    Reset the supplied CharonOp group to its default Ready state.

    Returns the node identifier applied to the node (empty string on failure).
    """
    if node is None:
        return ""

    def _read_str_knob(knob_name: str) -> str:
        try:
            knob = node.knob(knob_name)
        except Exception:
            knob = None
        if knob is None:
            return ""
        try:
            value = knob.value()
        except Exception:
            return ""
        if value is None:
            return ""
        try:
            return str(value)
        except Exception:
            return ""

    def _set_knob_value(knob_name: str, value) -> None:
        try:
            knob = node.knob(knob_name)
        except Exception:
            knob = None
        if knob is None:
            return
        try:
            knob.setValue(value)
        except Exception:
            pass

    def _coerce_flag(value) -> bool:
        if value in (None, "", False):
            return False
        try:
            text = str(value).strip().lower()
        except Exception:
            return False
        return text in {"1", "true", "yes", "on"}

    node_id_value = (node_id or "").strip().lower()[:12]
    if not node_id_value:
        node_id_value = _generate_charon_node_id()

    workflow_name = _read_str_knob("charon_workflow_name") or ""
    if not workflow_name:
        try:
            meta_name = node.metadata("charon/workflow_name")
        except Exception:
            meta_name = ""
        if meta_name:
            workflow_name = str(meta_name)
    if not workflow_name:
        try:
            workflow_name = node.name()
        except Exception:
            workflow_name = "Charon"

    workflow_path = _read_str_knob("workflow_path") or ""
    if not workflow_path:
        try:
            meta_path = node.metadata("charon/workflow_path")
        except Exception:
            meta_path = ""
        if meta_path:
            workflow_path = str(meta_path)

    source_workflow_path = _read_str_knob("charon_source_workflow_path") or ""
    if not source_workflow_path:
        try:
            meta_source = node.metadata("charon/source_workflow_path")
        except Exception:
            meta_source = ""
        if meta_source:
            source_workflow_path = str(meta_source)
    if not source_workflow_path:
        source_workflow_path = workflow_path

    raw_validated = _read_str_knob("charon_validated")
    is_validated = _coerce_flag(raw_validated)
    if raw_validated == "":
        try:
            meta_validated = node.metadata("charon/is_validated")
        except Exception:
            meta_validated = ""
        if meta_validated not in (None, ""):
            is_validated = _coerce_flag(meta_validated)

    local_state_payload = _read_str_knob("charon_local_state")
    if not local_state_payload:
        try:
            meta_state = node.metadata("charon/local_state")
        except Exception:
            meta_state = ""
        if isinstance(meta_state, str) and meta_state.strip():
            local_state_payload = meta_state
    if not local_state_payload:
        local_state_payload = "{}"

    auto_import_enabled = True
    status_payload = _build_default_status_payload(
        workflow_name=workflow_name,
        workflow_path=workflow_path,
        node_id=node_id_value,
    )
    serialized_payload = json.dumps(status_payload)

    # Update knobs
    _set_knob_value("charon_status", "Ready")
    _set_knob_value("charon_progress", 0.0)
    _set_knob_value("charon_status_payload", serialized_payload)
    _set_knob_value("charon_auto_import", 1)
    _set_knob_value("charon_prompt_id", "")
    _set_knob_value("charon_prompt_path", "")
    _set_knob_value("charon_last_output", "")
    _set_knob_value("charon_read_node_id", "")
    _set_knob_value("charon_read_node", "")
    _set_knob_value("charon_node_id", node_id_value)
    _set_knob_value("charon_node_id_info", node_id_value)
    _set_knob_value("charon_read_id_info", "Not linked")
    _set_knob_value("charon_source_workflow_path", source_workflow_path or workflow_path)
    _set_knob_value("charon_validated", 1 if is_validated else 0)
    _set_knob_value("charon_local_state", local_state_payload)
    _set_knob_value("charon_use_crop", 0)

    crop_box_default = _default_crop_box()
    try:
        bbox_knob = node.knob("charon_crop_bbox")
    except Exception:
        bbox_knob = None
    if bbox_knob is not None:
        try:
            bbox_knob.setValue(crop_box_default)
        except Exception:
            for index, coord in enumerate(crop_box_default):
                try:
                    bbox_knob.setValue(coord, index)
                except Exception:
                    pass

    ready_tile = status_to_tile_color("Ready")
    ready_gl = status_to_gl_color("Ready") or (0.0, 0.0, 0.0)
    debug_text = f"Status=Ready | tile=0x{ready_tile:08X} | gl=" + ",".join(f"{channel:.3f}" for channel in ready_gl)
    _set_knob_value("charon_color_debug", debug_text)

    try:
        node["tile_color"].setValue(ready_tile)
    except Exception:
        pass
    try:
        node["gl_color"].setValue(ready_gl)
    except Exception:
        try:
            node["gl_color"].setValue(list(ready_gl))
        except Exception:
            pass

    # Persist metadata mirrors
    try:
        node.setMetaData("charon/status_payload", serialized_payload)
    except Exception:
        pass
    try:
        node.setMetaData("charon/auto_import", "1")
    except Exception:
        pass
    try:
        node.setMetaData("charon/workflow_name", workflow_name)
        node.setMetaData("charon/workflow_path", workflow_path or "")
        node.setMetaData("charon/source_workflow_path", source_workflow_path or workflow_path or "")
        node.setMetaData("charon/is_validated", "1" if is_validated else "0")
        node.setMetaData("charon/local_state", local_state_payload or "")
        node.setMetaData("charon/node_id", node_id_value)
        node.setMetaData("charon/read_node_id", "")
        node.setMetaData("charon/read_node", "")
        node.setMetaData("charon/last_output", "")
        node.setMetaData("charon/prompt_hash", "")
    except Exception:
        pass

    return node_id_value


def _coerce_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(value, (int, float)):
        return bool(value)
    return False


def _coerce_int(value):
    if isinstance(value, bool):
        return 1 if value else 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _coerce_float(value):
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _coerce_string(value):
    if value is None:
        return ""
    return str(value)



