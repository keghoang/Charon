import json
import time


def sanitize_name(name):
    return "".join(c if c.isalnum() or c == "_" else "_" for c in name)


def create_charon_group_node(
    nuke,
    workflow_name,
    workflow_data,
    inputs,
    temp_dir,
    process_script,
    menu_script=None,
    workflow_path=None,
):
    inputs = list(inputs or [])
    node = nuke.createNode("Group", inpanel=False)

    safe_name = sanitize_name(workflow_name) or "Charon"
    node.setName(f"CharonOp_{safe_name}")

    try:
        node.setLabel("CharonOp Node\\nWorkflow: {}\\nInputs: {}".format(len(workflow_data), len(inputs)))
    except Exception:
        pass

    node.begin()
    internal_inputs = []
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

    output_node = nuke.nodes.Output()
    if internal_inputs:
        output_node.setInput(0, internal_inputs[0])
    node.end()

    workflow_knob = nuke.Text_Knob("workflow_data", "Workflow Data", json.dumps(workflow_data))
    node.addKnob(workflow_knob)

    inputs_knob = nuke.Text_Knob("input_mapping", "Input Mapping", json.dumps(inputs))
    node.addKnob(inputs_knob)

    temp_knob = nuke.String_Knob("charon_temp_dir", "Temp Directory", temp_dir)
    temp_knob.setFlag(nuke.NO_ANIMATION)
    try:
        temp_knob.setFlag(nuke.INVISIBLE)
    except Exception:
        pass
    node.addKnob(temp_knob)

    status_knob = nuke.String_Knob("charon_status", "Status", "Ready")
    status_knob.setFlag(nuke.NO_ANIMATION)
    try:
        status_knob.setFlag(nuke.INVISIBLE)
    except Exception:
        pass
    node.addKnob(status_knob)

    progress_knob = nuke.Double_Knob("charon_progress", "Progress")
    progress_knob.setFlag(nuke.NO_ANIMATION)
    progress_knob.setRange(0.0, 1.0)
    progress_knob.setValue(0.0)
    try:
        progress_knob.setFlag(nuke.INVISIBLE)
    except Exception:
        pass
    node.addKnob(progress_knob)

    auto_import_knob = nuke.Boolean_Knob("charon_auto_import", "Auto Import Outputs", True)
    auto_import_knob.setFlag(nuke.NO_ANIMATION)
    auto_import_knob.setValue(1)
    try:
        auto_import_knob.setFlag(nuke.INVISIBLE)
    except Exception:
        pass
    node.addKnob(auto_import_knob)

    prompt_id_knob = nuke.String_Knob("charon_prompt_id", "Prompt ID", "")
    prompt_id_knob.setFlag(nuke.NO_ANIMATION)
    try:
        prompt_id_knob.setFlag(nuke.INVISIBLE)
    except Exception:
        pass
    node.addKnob(prompt_id_knob)

    prompt_path_knob = nuke.String_Knob("charon_prompt_path", "Prompt Path", "")
    prompt_path_knob.setFlag(nuke.NO_ANIMATION)
    try:
        prompt_path_knob.setFlag(nuke.INVISIBLE)
    except Exception:
        pass
    node.addKnob(prompt_path_knob)

    last_output_knob = nuke.String_Knob("charon_last_output", "Last Output Path", "")
    last_output_knob.setFlag(nuke.NO_ANIMATION)
    try:
        last_output_knob.setFlag(nuke.INVISIBLE)
    except Exception:
        pass
    node.addKnob(last_output_knob)

    if workflow_path:
        path_knob = nuke.String_Knob("workflow_path", "Workflow Path", workflow_path)
        path_knob.setFlag(nuke.NO_ANIMATION)
        try:
            path_knob.setFlag(nuke.INVISIBLE)
        except Exception:
            pass
        node.addKnob(path_knob)

    process_knob = nuke.PyScript_Knob("process", "Process with ComfyUI")
    process_knob.setCommand(process_script)
    node.addKnob(process_knob)

    if menu_script:
        menu_knob = nuke.PyScript_Knob("menu", "CharonOp Menu")
        menu_knob.setCommand(menu_script)
        node.addKnob(menu_knob)

    info_lines = ["Inputs Required:"]
    for input_def in inputs:
        info_lines.append(f"- {input_def.get('name', 'Input')} : {input_def.get('description', '')}")
    info_knob = nuke.Text_Knob("info", "Workflow Info", "\n".join(info_lines))
    node.addKnob(info_knob)

    status_payload = {
        "status": "Ready",
        "progress": 0.0,
        "message": "Awaiting processing",
        "updated_at": time.time(),
        "auto_import": True,
        "runs": [],
    }
    try:
        node.setMetaData("charon/status_payload", json.dumps(status_payload))
    except Exception:
        pass
    try:
        node.setMetaData("charon/auto_import", "1")
    except Exception:
        pass

    return node, inputs
