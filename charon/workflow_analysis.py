import json


CHARON_INPUT_PREFIX = "charoninput"

TYPE_LOOKUP = {
    "image": "image",
    "img": "image",
    "mask": "mask",
    "alpha": "mask",
    "matte": "mask",
    "depth": "depth",
    "normal": "normal",
    "normals": "normal",
    "height": "height",
    "bump": "height",
    "roughness": "roughness",
    "metal": "metallic",
    "metallic": "metallic",
    "specular": "specular",
    "latent": "latent",
    "conditioning": "conditioning",
    "control": "control",
    "controlnet": "controlnet",
}


def analyze_workflow_inputs(workflow_data):
    inputs = []
    if not workflow_data:
        return inputs

    set_identifiers = set()

    for node_id, node_data in workflow_data.items():
        if not isinstance(node_data, dict):
            continue

        class_type = node_data.get("class_type", "")
        node_inputs = node_data.get("inputs", {})

        if isinstance(class_type, str) and class_type.lower().endswith("setnode"):
            identifier = _extract_identifier(node_data)
            if identifier and identifier.lower().startswith(CHARON_INPUT_PREFIX):
                remainder = identifier[len(CHARON_INPUT_PREFIX):]
                if remainder.startswith("_"):
                    remainder = remainder[1:]
                if not remainder:
                    continue
                token = remainder.split("_")[0].lower()
                input_type = TYPE_LOOKUP.get(token, "image")
                friendly = remainder.replace("_", " ").title()
                if identifier.lower() not in set_identifiers:
                    set_identifiers.add(identifier.lower())
                    inputs.append(
                        {
                            "name": friendly,
                            "type": input_type,
                            "node_id": node_id,
                            "description": f"Charon input '{friendly}'",
                            "identifier": identifier,
                            "source": "set_node",
                        }
                    )
            continue

        if class_type == "LoadImage":
            inputs.append(
                {
                    "name": "Primary Image",
                    "type": "image",
                    "node_id": node_id,
                    "description": "Main input image",
                    "source": "load_image",
                }
            )
        elif class_type == "ControlNetLoader":
            inputs.append(
                {
                    "name": "ControlNet",
                    "type": "controlnet",
                    "node_id": node_id,
                    "description": "ControlNet conditioning",
                    "source": "controlnet_loader",
                }
            )
        elif class_type == "ControlNetApply":
            for value in node_inputs.values():
                if isinstance(value, list) and len(value) == 2:
                    inputs.append(
                        {
                            "name": "ControlNet Image",
                            "type": "image",
                            "node_id": str(value[0]),
                            "description": "Image for ControlNet conditioning",
                            "source": "controlnet_apply",
                        }
                    )
        elif class_type == "VAEDecode":
            for name, value in node_inputs.items():
                if name == "samples" and isinstance(value, list):
                    inputs.append(
                        {
                            "name": "Latent Input",
                            "type": "latent",
                            "node_id": node_id,
                            "description": "Latent space input",
                            "source": "vae_decode",
                        }
                    )

    if set_identifiers:
        inputs = [
            inp
            for inp in inputs
            if not (inp.get("source") == "load_image" and inp.get("type") == "image")
        ]

    unique = []
    seen = set()
    for item in inputs:
        key = (item.get("node_id"), item.get("identifier", item.get("name")))
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def analyze_ui_workflow_inputs(ui_workflow):
    inputs = []
    if not isinstance(ui_workflow, dict):
        return inputs

    nodes = ui_workflow.get("nodes", [])
    set_identifiers = set()

    for node in nodes:
        node_type = node.get("type", "")
        identifier = _extract_ui_identifier(node)

        if node_type == "SetNode":
            if identifier and identifier.lower().startswith(CHARON_INPUT_PREFIX):
                remainder = identifier[len(CHARON_INPUT_PREFIX):]
                if remainder.startswith("_"):
                    remainder = remainder[1:]
                if not remainder:
                    continue
                token = remainder.split("_")[0].lower()
                input_type = TYPE_LOOKUP.get(token, "image")
                friendly = remainder.replace("_", " ").title()
                norm_key = identifier.lower()
                if norm_key not in set_identifiers:
                    set_identifiers.add(norm_key)
                    inputs.append({
                        "name": friendly,
                        "type": input_type,
                        "node_id": str(node.get("id")),
                        "description": f"Charon input '{friendly}'",
                        "identifier": identifier,
                        "source": "set_node",
                    })
            continue

        if node_type == "LoadImage":
            inputs.append({
                "name": "Primary Image",
                "type": "image",
                "node_id": str(node.get("id")),
                "description": "Main input image",
                "source": "load_image",
            })

    if set_identifiers:
        inputs = [
            inp for inp in inputs
            if not (inp.get("source") == "load_image" and inp.get("type") == "image")
        ]

    unique = []
    seen = set()
    for item in inputs:
        key = (item.get("node_id"), item.get("identifier", item.get("name")))
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def validate_workflow(workflow_data):
    if not isinstance(workflow_data, dict):
        return False, "No workflow data loaded"

    has_save = any(
        isinstance(node_data, dict) and node_data.get("class_type") == "SaveImage"
        for node_data in workflow_data.values()
    )
    if has_save:
        return True, "Workflow validation passed"
    return False, "Workflow requires a SaveImage node"


def validate_ui_workflow(ui_workflow):
    if not isinstance(ui_workflow, dict):
        return False, "No workflow data loaded"

    nodes = ui_workflow.get("nodes", [])
    has_load = any(node.get("type") == "LoadImage" for node in nodes)
    has_save = any(node.get("type") == "SaveImage" for node in nodes)

    if has_load and has_save:
        return True, "Workflow validation passed"

    messages = []
    if not has_load:
        messages.append("Missing LoadImage node")
    if not has_save:
        messages.append("Missing SaveImage node")
    return False, " / ".join(messages)


def workflow_display_text_ui(name, filename, ui_workflow):
    nodes = ui_workflow.get("nodes", []) if isinstance(ui_workflow, dict) else []
    node_count = len(nodes)
    counts = {}
    for node in nodes:
        node_type = node.get("type", "Unknown")
        counts[node_type] = counts.get(node_type, 0) + 1

    lines = [
        f"Workflow: {name}",
        f"File: {filename}",
        f"Nodes: {node_count}",
        "",
        "Node Types:",
    ]
    for node_type, count in sorted(counts.items()):
        lines.append(f"  - {node_type}: {count}")

    has_load = any(node.get("type") == "LoadImage" for node in nodes)
    has_save = any(node.get("type") == "SaveImage" for node in nodes)
    lines.extend(["", "Validation:"])
    lines.append("  - LoadImage node found" if has_load else "  - WARNING: No LoadImage node")
    lines.append("  - SaveImage node found" if has_save else "  - WARNING: No SaveImage node")
    return "\n".join(lines)


def workflow_display_text(name, filename, api_workflow):
    node_count = len(api_workflow) if isinstance(api_workflow, dict) else 0
    lines = [
        f"Workflow: {name}",
        f"File: {filename}",
        f"Nodes: {node_count}",
        "",
        "Validation:",
        "  - Ready for conversion",
    ]
    return "\n".join(lines)


def _extract_identifier(node):
    title = (node.get("_meta", {}) or {}).get("title", "")
    if title:
        return _normalize_identifier(title)
    data = node.get("inputs", {})
    widget_values = node.get("widgets_values", [])
    if widget_values:
        return _normalize_identifier(str(widget_values[0]))
    if data:
        for key, value in data.items():
            if key.lower() == "identifier" and isinstance(value, str):
                return _normalize_identifier(value)
    return ""


def _normalize_identifier(value):
    if not value:
        return value
    lowered = value.lower()
    if lowered.startswith("set_"):
        return value[4:]
    if lowered.startswith("get_"):
        return value[4:]
    return value


def _extract_ui_identifier(node):
    title = str(node.get("title") or "").strip()
    if title:
        return _normalize_ui_identifier(title)
    widgets = node.get("widgets_values", [])
    if widgets:
        return _normalize_ui_identifier(str(widgets[0]))
    properties = node.get("properties", {})
    if isinstance(properties, dict):
        prev = properties.get("previousName")
        if prev:
            return _normalize_ui_identifier(str(prev))
    return ""


def _normalize_ui_identifier(value):
    if not value:
        return value
    lowered = value.lower()
    if lowered.startswith("set_"):
        return value[4:]
    if lowered.startswith("get_"):
        return value[4:]
    return value
