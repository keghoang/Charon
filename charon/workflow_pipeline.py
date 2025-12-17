import copy
import importlib
import json
import logging
import os
import subprocess
import uuid

from .paths import get_charon_temp_dir, resolve_comfy_environment


logger = logging.getLogger(__name__)


def _discover_script_dir():
    candidates = []
    if "__file__" in globals():
        try:
            candidates.append(os.path.dirname(os.path.abspath(__file__)))
        except Exception:
            pass
    try:
        cwd = os.getcwd()
        if cwd:
            candidates.append(cwd)
    except Exception:
        pass
    for candidate in candidates:
        if candidate and os.path.exists(os.path.join(candidate, "workflow_converter.py")):
            return candidate
    return candidates[0] if candidates else os.getcwd()


SCRIPT_DIR = _discover_script_dir()


def convert_workflow(ui_workflow, comfy_path="", comfy_nodes_module=None):
    if not isinstance(ui_workflow, dict):
        return ui_workflow

    # Already in API format (flat dict with class_type)
    if ui_workflow and all(
        isinstance(value, dict) and "class_type" in value for value in ui_workflow.values()
    ):
        return copy.deepcopy(ui_workflow)

    if not comfy_path:
        raise RuntimeError("ComfyUI path is required for conversion.")

    if comfy_path:
        logger.info("Attempting external conversion using ComfyUI at %s", comfy_path)
        external = convert_with_external_python(ui_workflow, comfy_path, strict=True)
        if isinstance(external, dict):
            logger.info("External conversion succeeded (nodes: %s)", len(external))
            flattened = flatten_set_get_nodes(ui_workflow, external)
            _ensure_widget_inputs_preserved(ui_workflow, flattened)
            return flattened

    raise RuntimeError("External ComfyUI converter could not produce a valid workflow.")


def convert_with_external_python(ui_workflow, comfy_path, strict=False):
    env_info = resolve_comfy_environment(comfy_path)
    python_exe = env_info.get("python_exe")
    comfy_dir = env_info.get("comfy_dir")
    if not python_exe or not os.path.exists(python_exe):
        logger.error("Embedded Python not found for ComfyUI path %s", comfy_path)
        if strict:
            raise RuntimeError("Embedded python executable not found.")
        return None
    if not comfy_dir or not os.path.exists(comfy_dir):
        logger.error("ComfyUI directory not found for path %s", comfy_path)
        if strict:
            raise RuntimeError("ComfyUI directory not found.")
        return None

    converter_path = os.path.join(SCRIPT_DIR, "workflow_converter.py")
    if not os.path.exists(converter_path):
        logger.error(
            "workflow_converter.py not found next to workflow_pipeline.py (expected in %s)", SCRIPT_DIR
        )
        if strict:
            raise RuntimeError("workflow_converter.py missing.")
        return None

    temp_root = get_charon_temp_dir()
    temp_dir = os.path.join(temp_root, "temp")
    os.makedirs(temp_dir, exist_ok=True)

    input_path = os.path.join(temp_dir, f"workflow_input_{uuid.uuid4().hex}.json")
    output_path = os.path.join(temp_dir, f"workflow_output_{uuid.uuid4().hex}.json")
    script_path = os.path.join(temp_dir, f"workflow_runner_{uuid.uuid4().hex}.py")

    try:
        with open(input_path, "w", encoding="utf-8") as handle:
            json.dump(ui_workflow, handle)

        script_contents = """import json
import os
import sys

input_path = sys.argv[1]
output_path = sys.argv[2]
script_dir = sys.argv[3]
comfy_dir = sys.argv[4]

sys.path.insert(0, comfy_dir)

# Ensure UTF-8 console so custom nodes printing emojis don't explode on Windows
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

# Ensure Comfy's utils package is used
if "utils" in sys.modules:
    del sys.modules["utils"]

import importlib.util

utils_dir = os.path.join(comfy_dir, "utils")
utils_init = os.path.join(utils_dir, "__init__.py")
if os.path.exists(utils_init):
    utils_spec = importlib.util.spec_from_file_location(
        "utils", utils_init, submodule_search_locations=[utils_dir]
    )
    utils_module = importlib.util.module_from_spec(utils_spec)
    utils_spec.loader.exec_module(utils_module)
    sys.modules["utils"] = utils_module

import comfy.options
comfy.options.enable_args_parsing(False)

from comfy.cli_args import args  # noqa: F401
import folder_paths  # noqa: F401
import nodes
import server


class _CharonRouteStub:
    def __getattr__(self, name):
        def decorator(*args, **kwargs):
            def passthrough(func):
                return func
            return passthrough
        return decorator


class _CharonRouterStub:
    def add_static(self, *args, **kwargs):
        return None


class _CharonAppStub:
    def __init__(self):
        self.router = _CharonRouterStub()

    def add_routes(self, *args, **kwargs):
        return None


class _CharonPromptServerStub:
    def __init__(self):
        self.routes = _CharonRouteStub()
        self.app = _CharonAppStub()
        self.supports = []

    def send_sync(self, *args, **kwargs):
        return None

    def __getattr__(self, _name):
        def _noop(*args, **kwargs):
            return None
        return _noop


if not hasattr(getattr(server, "PromptServer", object), "instance"):
    server.PromptServer.instance = _CharonPromptServerStub()

nodes.init_extra_nodes(init_custom_nodes=True, init_api_nodes=False)

converter_path = os.path.join(script_dir, "workflow_converter.py")
spec = importlib.util.spec_from_file_location("workflow_converter", converter_path)
workflow_converter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workflow_converter)
WorkflowConverter = workflow_converter.WorkflowConverter

with open(input_path, "r", encoding="utf-8") as fp:
    data = json.load(fp)

converted = WorkflowConverter.convert_to_api(data)

with open(output_path, "w", encoding="utf-8") as fp:
    json.dump(converted, fp, indent=2)
"""

        with open(script_path, "w", encoding="utf-8") as handle:
            handle.write(script_contents)

        command = [python_exe, script_path, input_path, output_path, SCRIPT_DIR, comfy_dir]
        logger.info("Launching external conversion: %s", command)
        subprocess.check_call(command, cwd=SCRIPT_DIR)

        if not os.path.exists(output_path):
            logger.error("External converter did not produce an output file.")
            if strict:
                raise RuntimeError("External converter did not produce an output file.")
            return None

        with open(output_path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except subprocess.CalledProcessError as exc:
        logger.error("External conversion failed: %s", exc)
        if strict:
            raise RuntimeError(f"External conversion failed: {exc}") from exc
        return None
    finally:
        for path in (input_path, output_path, script_path):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass


def flatten_set_get_nodes(ui_workflow, api_workflow):
    if not isinstance(api_workflow, dict):
        return api_workflow

    set_map = {}
    set_node_ids = set()
    get_id_to_title = {}

    links_map = {link[0]: (str(link[1]), link[2]) for link in ui_workflow.get("links", [])}

    for node in ui_workflow.get("nodes", []):
        node_type = node.get("type", "")
        title = _extract_set_get_title(node)
        if not title:
            continue
        if node_type == "SetNode":
            for input_slot in node.get("inputs", []):
                link_id = input_slot.get("link")
                if link_id in links_map:
                    set_map[title] = links_map[link_id]
                    set_node_ids.add(str(node.get("id")))
        elif node_type == "GetNode":
            get_id_to_title[str(node.get("id"))] = title

    if not set_map:
        return api_workflow

    api_workflow = copy.deepcopy(api_workflow)
    get_nodes = {
        node_id: data
        for node_id, data in api_workflow.items()
        if data.get("class_type", "").lower().endswith("getnode") or data.get("class_type") == "GetNode"
    }

    # Map API GetNode to title
    api_get_titles = {}
    for node_id, data in get_nodes.items():
        meta = data.get("_meta", {})
        title = meta.get("title") or get_id_to_title.get(node_id)
        if not title:
            continue
        api_get_titles[node_id] = _normalize_set_get_name(title)

    # Update inputs to bypass GetNodes
    for node_id, data in api_workflow.items():
        inputs = data.get("inputs", {})
        new_inputs = {}
        for name, value in inputs.items():
            if isinstance(value, list) and len(value) == 2:
                src_id, socket = value
                src_id_str = str(src_id)
                title = api_get_titles.get(src_id_str) or get_id_to_title.get(src_id_str)
                if title and title in set_map:
                    new_inputs[name] = [set_map[title][0], set_map[title][1]]
                    continue
            new_inputs[name] = value
        data["inputs"] = new_inputs

    # Remove GetNodes from prompt
    for node_id in api_get_titles:
        api_workflow.pop(node_id, None)

    # Remove SetNodes from prompt if they still exist
    for node_id in set_node_ids:
        api_workflow.pop(node_id, None)

    return api_workflow


def _ensure_widget_inputs_preserved(ui_workflow, api_workflow):
    if not isinstance(ui_workflow, dict) or not isinstance(api_workflow, dict):
        return

    missing = []
    for node in ui_workflow.get("nodes", []):
        node_id = node.get("id")
        if node_id is None:
            continue
        node_id_str = str(node_id)
        api_node = api_workflow.get(node_id_str)
        if not api_node:
            continue
        widget_values = node.get("widgets_values", [])
        if not isinstance(widget_values, list) or not widget_values:
            continue
        api_inputs = api_node.get("inputs", {})
        if not isinstance(api_inputs, dict):
            continue

        scalar_inputs = {
            key: value
            for key, value in api_inputs.items()
            if not (isinstance(value, list) and len(value) == 2)
        }
        if not scalar_inputs:
            missing.append(
                {
                    "node_id": node_id_str,
                    "node_type": api_node.get("class_type") or node.get("type"),
                    "expected_values": len(widget_values),
                }
            )

    if missing:
        details = ", ".join(
            f"{item['node_type']} (id {item['node_id']})"
            for item in missing
        )
        raise RuntimeError(
            f"Converted workflow lost scalar inputs for nodes: {details}. "
            "Check ComfyUI custom nodes and conversion logs."
        )


def find_link_source(ui_workflow, link_id):
    for link in ui_workflow.get("links", []):
        if link[0] == link_id:
            return link[1], link[2]
    return None


def _extract_set_get_title(node):
    title = (node.get("title") or "").strip()
    if title:
        return _normalize_set_get_name(title)
    widgets = node.get("widgets_values", [])
    if widgets:
        return _normalize_set_get_name(str(widgets[0]))
    properties = node.get("properties", {})
    if isinstance(properties, dict):
        prev = properties.get("previousName")
        if prev:
            return _normalize_set_get_name(str(prev))
    return ""


def _normalize_set_get_name(name):
    if not name:
        return name
    lowered = name.lower()
    if lowered.startswith("set_"):
        return name[4:]
    if lowered.startswith("get_"):
        return name[4:]
    return name
