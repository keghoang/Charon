import json
import time
import uuid
from typing import Any, Dict, List

from .utilities import status_to_gl_color, status_to_tile_color


def sanitize_name(name):
    return "".join(c if c.isalnum() or c == "_" else "_" for c in name)


def _generate_charon_node_id() -> str:
    """Return a short, human-friendly identifier for Charon nodes."""
    return uuid.uuid4().hex[:12].lower()


def create_charon_group_node(
    nuke,
    workflow_name,
    workflow_data,
    inputs,
    temp_dir,
    process_script,
    workflow_path=None,
    parameters=None,
    import_script=None,
    auto_import_default=True,
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

    node_id_value = _generate_charon_node_id()
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

    setup_label = nuke.Text_Knob("charon_setup_label", "Processing Controls", "")
    node.addKnob(setup_label)

    import_knob = nuke.PyScript_Knob("import_output", "Import Output")
    import_knob.setCommand(import_script or "nuke.message('Import script unavailable.')")
    import_knob.setFlag(nuke.STARTLINE)
    node.addKnob(import_knob)

    process_knob = nuke.PyScript_Knob("process", "Process with ComfyUI")
    process_knob.setCommand(process_script)
    process_knob.setFlag(nuke.STARTLINE)
    node.addKnob(process_knob)

    reuse_knob = nuke.Boolean_Knob(
        "charon_reuse_output",
        "Update future iteration in the same Read node",
        True,
    )
    reuse_knob.setFlag(nuke.NO_ANIMATION)
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
    node.addKnob(batch_knob)

    info_tab = nuke.Tab_Knob("charon_info_tab", "Info")
    node.addKnob(info_tab)

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
    debug_text = f"Status=Ready | tile=0x{ready_tile:08X} | gl=" + ",".join(f"{channel:.3f}" for channel in ready_gl)
    color_debug_knob = nuke.Text_Knob("charon_color_debug", "Color Debug", debug_text)
    node.addKnob(color_debug_knob)

    status_payload = {
        "status": "Ready",
        "progress": 0.0,
        "message": "Awaiting processing",
        "updated_at": time.time(),
        "workflow_name": workflow_name,
        "workflow_path": workflow_path or "",
        "auto_import": bool(auto_import_default),
        "runs": [],
        "node_id": node_id_value,
        "read_node_id": "",
    }
    try:
        node.setMetaData("charon/status_payload", json.dumps(status_payload))
    except Exception:
        pass
    try:
        node.setMetaData("charon/auto_import", "1" if auto_import_default else "0")
    except Exception:
        pass
    try:
        node.setMetaData("charon/workflow_name", workflow_name)
        node.setMetaData("charon/workflow_path", workflow_path or "")
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

def _create_parameter_knob(nuke_module, name, label, value_type, default):
    try:
        if value_type == "boolean":
            knob = nuke_module.Boolean_Knob(name, label)
            knob.setValue(1 if _coerce_bool(default) else 0)
        elif value_type == "integer":
            knob = nuke_module.Int_Knob(name, label)
            coerced = _coerce_int(default)
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
                knob.setHeight(3)
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



