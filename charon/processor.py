# CharonOp Node Processing Script
import copy
import json
import os
import subprocess
import threading
import time
import uuid
import zlib
import shutil
import random
from typing import Any, Dict, List, Optional, Tuple

from .conversion_cache import (
    compute_workflow_hash,
    desired_prompt_path,
    load_cached_conversion,
    write_conversion_cache,
)
from .paths import (
    allocate_charon_output_path,
    get_default_comfy_launch_path,
    get_placeholder_image_path,
    _normalize_charon_root,
    resolve_comfy_environment,
)
from .workflow_runtime import convert_workflow as runtime_convert_workflow
from .workflow_overrides import apply_validation_model_overrides
from .comfy_client import ComfyUIClient
from . import config, preferences
from .node_factory import reset_charon_node_state
from .utilities import (
    get_current_user_slug,
    status_to_gl_color,
    status_to_tile_color,
    resolve_status_color_hex,
)

CONTROL_VALUE_TOKENS = {"fixed", "increment", "decrement", "randomize"}
MODEL_OUTPUT_EXTENSIONS = {".obj", ".fbx", ".abc", ".gltf", ".glb", ".usd", ".usdz"}
CAMERA_OUTPUT_EXTENSIONS = {".nukecam"}
THREE_D_OUTPUT_EXTENSIONS = MODEL_OUTPUT_EXTENSIONS | CAMERA_OUTPUT_EXTENSIONS
CAMERA_OUTPUT_LABEL = "BUCK_Camera_from_DA3"
IGNORE_OUTPUT_PREFIX = "charoninput_ignore"
IMAGE_OUTPUT_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".exr",
    ".bmp",
    ".tga",
    ".webp",
}

INVERSE_VIEW_TRANSFORM_GROUP = """set cut_paste_input [stack 0]
version 16.0 v3
push $cut_paste_input
Group {
 name InverseViewTransform1
 selected true
 xpos 1274
 ypos 1193
 addUserKnob {20 User}
 addUserKnob {26 viewTransform l "View Transform" T "Driven by Root > Color > Thumbnails setting\\n\\nAutomatic alpha channel detection"}
 addUserKnob {41 view l "view transform" T OCIODisplayLinked1.view}
 addUserKnob {41 display l "display device" T OCIODisplayLinked1.display}
}
 Input {
  inputs 0
  name Input1
  xpos -468
  ypos 495
 }
 OCIOColorSpace {
  in_colorspace compositing_linear
  out_colorspace default
  name OCIOColorSpace2
  xpos -468
  ypos 626
 }
 OCIODisplay {
  colorspace compositing_linear
  display "sRGB Display"
  view {{root.monitorLut x1002 1 x1023 1}}
  invert true
  name OCIODisplayLinked1
  note_font Verdana
  note_font_size 12
  xpos -468
  ypos 652
  addUserKnob {20 User}
  addUserKnob {26 viewer_note l "View Transform" T "Driven by Root > Color > Thumbnails setting"}
 }
 Output {
  name Output1
  xpos -468
  ypos 776
 }
end_group
"""


def _allocate_output_path(
    node_id: Optional[str],
    script_name: Optional[str],
    extension: str,
    user_slug: Optional[str],
    workflow_name: Optional[str],
    category: str,
    output_name: Optional[str] = None,
) -> str:
    """
    Wrap allocate_charon_output_path to remain compatible with older signatures.
    """
    try:
        return allocate_charon_output_path(
            node_id,
            script_name,
            extension,
            user_slug=user_slug,
            workflow_name=workflow_name,
            category=category,
            output_name=output_name,
        )
    except TypeError:
        return allocate_charon_output_path(
            node_id,
            script_name,
            extension,
            user_slug=user_slug,
            workflow_name=workflow_name,
            category=category,
        )


def _load_parameter_specs(node) -> List[Dict[str, Any]]:
    """Return parameter specs stored on the CharonOp knob."""
    try:
        knob = node.knob("charon_parameters")
    except Exception:
        knob = None
    if knob is None:
        return []
    try:
        raw = knob.value()
    except Exception:
        raw = ""
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except Exception:
        log_debug("Failed to parse charon_parameters knob; resetting", "WARNING")
        return []
    if isinstance(payload, list):
        normalized: List[Dict[str, Any]] = []
        for entry in payload:
            if isinstance(entry, dict):
                normalized.append(dict(entry))
        return normalized
    return []


def _write_parameter_specs(node, specs: List[Dict[str, Any]]) -> None:
    """Persist updated parameter specs back onto the CharonOp knob."""
    try:
        knob = node.knob("charon_parameters")
    except Exception:
        knob = None
    if knob is None:
        return
    try:
        knob.setValue(json.dumps(specs))
    except Exception as exc:
        log_debug(f"Failed to store parameter specs: {exc}", "WARNING")


def _coerce_parameter_value(value_type: str, value: Any) -> Any:
    """Convert raw parameter values into prompt-friendly types."""
    kind = (value_type or "").lower()
    if kind == "boolean":
        if isinstance(value, str):
            lowered = value.strip().lower()
            return lowered in {"1", "true", "yes", "on"}
        return bool(value)
    if kind == "integer":
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0
    if kind == "float":
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
    # Default to string
    if value is None:
        return ""
    return str(value)


def _ensure_trimesh():
    """
    Ensure trimesh is available in the current (Nuke) Python environment.
    Installation is handled on Charon launch; if missing, instruct the user.
    """
    try:
        import trimesh  # type: ignore

        return trimesh
    except ImportError as exc:
        raise RuntimeError(
            "GLB to OBJ conversion requires the 'trimesh' module in the Nuke Python environment. "
            "Launch Charon and accept the dependency install prompt to add it."
        ) from exc


def _convert_glb_to_obj(glb_path: str, obj_path: str) -> str:
    """Convert a GLB asset to OBJ using the ComfyUI embedded Python (trimesh)."""
    comfy_path = _read_comfy_preferences_path()
    if not comfy_path:
        comfy_path = get_default_comfy_launch_path()
    env = resolve_comfy_environment(comfy_path)
    python_exe = env.get("python_exe")
    if not python_exe or not os.path.exists(python_exe):
        raise RuntimeError(
            "ComfyUI embedded Python not found; cannot convert GLB to OBJ. "
            "Set a valid ComfyUI launch path and reinstall dependencies."
        )

    try:
        os.makedirs(os.path.dirname(obj_path), exist_ok=True)
    except Exception:
        pass

    script = r"""
import sys, os
import trimesh
glb_path, obj_path = sys.argv[1], sys.argv[2]
scene = trimesh.load(glb_path, force="scene")
if scene is None:
    raise SystemExit(1)
scene.export(obj_path)
if not os.path.exists(obj_path):
    raise SystemExit(2)
"""
    try:
        subprocess.check_call([python_exe, "-c", script, glb_path, obj_path])
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"GLB to OBJ conversion failed via ComfyUI Python: {exc}") from exc
    if not os.path.exists(obj_path):
        raise RuntimeError(f"OBJ export did not produce a file: {obj_path}")
    return obj_path


def _lookup_ui_nodes(ui_workflow: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Build a dictionary of UI nodes keyed by stringified id."""
    if not isinstance(ui_workflow, dict):
        return {}
    result: Dict[str, Dict[str, Any]] = {}
    nodes = ui_workflow.get("nodes")
    if isinstance(nodes, list):
        for node in nodes:
            if not isinstance(node, dict):
                continue
            node_id = node.get("id")
            if node_id is None:
                continue
            result[str(node_id)] = node
    return result


def _filtered_widget_index(widget_values: Any, original_index: int) -> Optional[int]:
    """
    Replicate the converter's filtering to map original widget indices to the
    filtered order used when assigning API inputs.
    """
    if not isinstance(widget_values, list):
        return None
    filtered_index = 0
    for idx, value in enumerate(widget_values):
        if value in CONTROL_VALUE_TOKENS:
            continue
        if idx == original_index:
            return filtered_index
        filtered_index += 1
    return None


def _extract_widget_index(attribute: str) -> Optional[int]:
    """Return the numeric index for attributes like 'widgets_values[3]'."""
    if not attribute or not isinstance(attribute, str):
        return None
    attribute = attribute.strip()
    if not attribute.startswith("widgets_values[") or not attribute.endswith("]"):
        return None
    slice_text = attribute[len("widgets_values[") : -1]
    try:
        return int(slice_text)
    except (TypeError, ValueError):
        return None


def _compute_parameter_binding(
    spec: Dict[str, Any],
    ui_nodes: Dict[str, Dict[str, Any]],
    api_workflow: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Identify the API node/input that corresponds to the UI parameter."""
    node_id = str(spec.get("node_id") or "").strip()
    if not node_id:
        return None
    api_node = api_workflow.get(node_id)
    if not isinstance(api_node, dict):
        return None

    ui_node = ui_nodes.get(node_id)
    attribute = str(spec.get("attribute") or "")
    widget_index = _extract_widget_index(attribute)
    candidate_input = None

    if ui_node and widget_index is not None:
        filtered_index = _filtered_widget_index(ui_node.get("widgets_values"), widget_index)
        if filtered_index is not None:
            node_type = ui_node.get("type") or ui_node.get("class_type") or ""
            widget_mappings = _get_widget_mappings(node_type, ui_node)
            if (
                isinstance(widget_mappings, list)
                and filtered_index < len(widget_mappings)
                and widget_mappings[filtered_index]
            ):
                candidate_input = widget_mappings[filtered_index]

    if not candidate_input and attribute and widget_index is None:
        candidate_input = attribute

    inputs = api_node.get("inputs")
    if not isinstance(inputs, dict):
        return None

    expected_value = _coerce_parameter_value(spec.get("type") or "", spec.get("default"))

    def _values_match(current):
        if isinstance(current, list):
            return False
        if current == expected_value:
            return True
        # String comparison as fallback to handle float/int serialization differences
        return str(current) == str(expected_value)

    if candidate_input:
        current_value = inputs.get(candidate_input)
        if current_value is not None or candidate_input in inputs:
            if not isinstance(current_value, list):
                return {"api_node": node_id, "api_input": candidate_input}

    for input_name, current_value in inputs.items():
        if _values_match(current_value):
            return {"api_node": node_id, "api_input": input_name}

    return None


def _ensure_parameter_bindings(
    node,
    specs: List[Dict[str, Any]],
    ui_workflow: Dict[str, Any],
    api_workflow: Dict[str, Any],
    workflow_hash: Optional[str],
) -> List[Dict[str, Any]]:
    """Compute missing bindings and refresh the knob when updates occur."""
    if not specs:
        return specs

    ui_nodes = _lookup_ui_nodes(ui_workflow)
    updated_specs: List[Dict[str, Any]] = []
    changed = False

    for spec in specs:
        spec_copy = dict(spec)
        binding = spec_copy.get("binding")
        if (
            isinstance(binding, dict)
            and binding.get("api_node")
            and binding.get("api_input")
            and binding.get("hash") == workflow_hash
        ):
            updated_specs.append(spec_copy)
            continue

        computed = _compute_parameter_binding(spec_copy, ui_nodes, api_workflow)
        if computed:
            computed["hash"] = workflow_hash
            spec_copy["binding"] = computed
            changed = True
            log_debug(
                f"Parameter binding resolved: node={computed['api_node']} input={computed['api_input']}"
            )
        else:
            attribute_name = spec_copy.get('attribute')
            if attribute_name == "control_after_generate":
                # This is expected for client-side control widgets not in the API schema
                log_debug(
                    f"Skipping binding for client-side control widget {attribute_name}",
                    "INFO",
                )
            else:
                log_debug(
                    f"Failed to resolve parameter binding for node {spec_copy.get('node_id')} attribute {attribute_name}",
                    "WARNING",
                )
        updated_specs.append(spec_copy)

    if changed:
        _write_parameter_specs(node, updated_specs)

    return updated_specs


def _is_ignored_output(path: Optional[str]) -> bool:
    """
    Determine whether a file should be ignored based on the configured prefix.
    """
    if not path:
        return False
    base = os.path.basename(str(path)).strip().lower()
    return base.startswith(IGNORE_OUTPUT_PREFIX)


def _apply_parameter_overrides(
    node,
    workflow_copy: Dict[str, Any],
    parameter_specs: List[Dict[str, Any]],
    knob_values: Optional[Dict[str, Any]] = None,
) -> List[Tuple[str, str]]:
    """Write knob values into the converted prompt using stored bindings."""
    applied: List[Tuple[str, str]] = []
    if not parameter_specs or not isinstance(workflow_copy, dict):
        return applied
    
    overrides = knob_values or {}

    for spec in parameter_specs:
        if not isinstance(spec, dict):
            continue
        binding = spec.get("binding") or {}
        knob_name = spec.get("knob")
        if not binding or not knob_name:
            continue
        api_node_id = str(binding.get("api_node") or "").strip()
        api_input = binding.get("api_input")
        if not api_node_id or not api_input:
            continue
        target_node = workflow_copy.get(api_node_id)
        if not isinstance(target_node, dict):
            log_debug(
                f"Cannot apply parameter; API node {api_node_id} missing from prompt", "WARNING"
            )
            continue
        inputs = target_node.setdefault("inputs", {})
        if not isinstance(inputs, dict):
            log_debug(
                f"Cannot apply parameter; inputs for node {api_node_id} not a dict", "WARNING"
            )
            continue

        try:
            knob = node.knob(knob_name)
        except Exception:
            knob = None
        if knob is None:
            log_debug(f"Knob {knob_name} not found on node; skipping override", "WARNING")
            continue
            
        if knob_name in overrides:
            raw_value = overrides[knob_name]
        else:
            try:
                raw_value = knob.value()
            except Exception as exc:
                log_debug(f"Failed to read knob {knob_name}: {exc}", "WARNING")
                continue

        coerced = _coerce_parameter_value(spec.get("type") or "", raw_value)
        
        # If this is the control widget and we are handling logic client-side,
        # force it to "fixed" so ComfyUI respects the seed we send.
        if spec.get("attribute") == "control_after_generate":
             # We assume client-side logic has already updated the seed knob if needed.
             # By sending "fixed", we ensure Comfy uses that explicit seed.
             coerced = "fixed"
             log_debug(f"Forcing {api_input} to 'fixed' for API submission to respect client-side seed.")

        inputs[api_input] = coerced
        applied.append((api_node_id, api_input))
        log_debug(
            f"Applied parameter override: node={api_node_id} input={api_input} value={coerced!r}"
        )

    return applied


def _get_widget_mappings(node_type: str, ui_node: Dict[str, Any]) -> List[Optional[str]]:
    """
    Attempt to retrieve widget-to-input mappings using UI hints only.
    This avoids importing ComfyUI modules inside the host application.
    """
    if not isinstance(ui_node, dict):
        return []

    widget_values = ui_node.get("widgets_values")
    if not isinstance(widget_values, list) or not widget_values:
        return []

    properties = ui_node.get("properties") or {}
    if isinstance(properties, dict):
        ue_properties = properties.get("ue_properties") or {}
        if isinstance(ue_properties, dict):
            widget_connectable = ue_properties.get("widget_ue_connectable")
            if isinstance(widget_connectable, dict):
                names = list(widget_connectable.keys())
                if names and len(names) >= len(widget_values):
                    return names[: len(widget_values)]

    all_inputs = []
    connected_inputs = set()
    widget_flagged_inputs = []
    for input_info in ui_node.get("inputs") or []:
        name = input_info.get("name")
        if not name:
            continue
        all_inputs.append(name)
        if input_info.get("link") is not None:
            connected_inputs.add(name)
        if input_info.get("widget"):
            widget_flagged_inputs.append(name)

    if widget_flagged_inputs:
        if len(widget_values) > len(widget_flagged_inputs):
            potentials = [
                candidate
                for candidate in all_inputs
                if candidate not in connected_inputs and candidate not in widget_flagged_inputs
            ]
            return widget_flagged_inputs + potentials[: len(widget_values) - len(widget_flagged_inputs)]
        return widget_flagged_inputs

    unconnected = [inp for inp in all_inputs if inp not in connected_inputs]
    if unconnected and len(unconnected) >= len(widget_values):
        return unconnected[: len(widget_values)]

    return []


def _get_qt_application():
    """Return the active Qt application instance if available."""
    try:
        from PySide6.QtWidgets import QApplication  # type: ignore
    except ImportError:
        try:
            from PySide2.QtWidgets import QApplication  # type: ignore
        except ImportError:
            return None
    return QApplication.instance()


def _find_charon_window():
    """Locate the active Charon/Charon window to access Comfy context."""
    app = _get_qt_application()
    if not app:
        return None

    for widget in app.topLevelWidgets():
        if getattr(widget, "_charon_is_charon_window", False):
            return widget

    for widget in app.topLevelWidgets():
        if hasattr(widget, "comfy_client"):
            return widget

    return None


def _read_comfy_preferences_path() -> Optional[str]:
    prefs = preferences.load_preferences()
    path = prefs.get("comfyui_launch_path")
    if isinstance(path, str):
        path = path.strip()
        if path:
            return path
    elif isinstance(path, (list, tuple)):
        # Defensive: handle legacy structures accidentally persisted
        flattened = "".join(str(part) for part in path if part)
        if flattened:
            return flattened
    return None


def _resolve_comfy_environment() -> Tuple[Optional[object], Optional[object], Optional[str]]:
    """
    Return (window, client, comfy_path) from the active Charon UI context.
    """
    window = _find_charon_window()
    client = getattr(window, "comfy_client", None) if window else None

    if client is None and window is not None:
        connection = getattr(window, "comfy_connection_widget", None)
        if connection is not None:
            getter = getattr(connection, "current_client", None)
            if callable(getter):
                try:
                    client = getter()
                except Exception:
                    client = None
            if client is None:
                property_value = getattr(connection, "client", None)
                if property_value is not None and not callable(property_value):
                    client = property_value
            if client is None and hasattr(connection, "_client"):
                client = getattr(connection, "_client", None)

    comfy_path = None
    if window is not None:
        connection = getattr(window, "comfy_connection_widget", None)
        if connection is not None:
            path_attr = getattr(connection, "current_comfy_path", None)
            if callable(path_attr):
                try:
                    comfy_path = path_attr()
                except Exception:
                    comfy_path = None
            elif isinstance(path_attr, str):
                comfy_path = path_attr
            elif hasattr(connection, "_comfy_path"):
                comfy_path = getattr(connection, "_comfy_path", None)

    if not comfy_path:
        comfy_path = _read_comfy_preferences_path()

    if not comfy_path:
        default_path = get_default_comfy_launch_path()
        if default_path and os.path.exists(default_path):
            comfy_path = default_path

    if client is None:
        try:
            tentative_client = ComfyUIClient()
            if tentative_client.test_connection():
                client = tentative_client
        except Exception:
            client = None

    return window, client, comfy_path


def is_api_prompt(data):
    if not isinstance(data, dict):
        return False
    if not data:
        return False
    for value in data.values():
        if not isinstance(value, dict) or 'class_type' not in value:
            return False
    return True

def normalize_identifier(value):
    if value is None:
        return ''
    text = str(value).strip()
    lowered = text.lower()
    if lowered.startswith('set_'):
        text = text[4:]
    elif lowered.startswith('get_'):
        text = text[4:]
    return text.lower()

def extract_ui_identifier(node):
    title = str(node.get('title') or '').strip()
    if title:
        return title
    widgets = node.get('widgets_values', [])
    if widgets:
        return str(widgets[0])
    properties = node.get('properties', {})
    if isinstance(properties, dict):
        prev = properties.get('previousName')
        if prev:
            return str(prev)
    return ''

def build_set_targets(ui_workflow):
    targets = {}
    if not isinstance(ui_workflow, dict):
        return targets
    links = ui_workflow.get('links', [])
    link_lookup = {}
    for link in links:
        if isinstance(link, list) and len(link) >= 3:
            link_lookup[link[0]] = (str(link[1]), link[2])
    for node in ui_workflow.get('nodes', []):
        if not isinstance(node, dict):
            continue
        if node.get('type') != 'SetNode':
            continue
        identifier = extract_ui_identifier(node)
        if not identifier:
            continue
        normalized = normalize_identifier(identifier)
        for input_slot in node.get('inputs', []):
            link_id = input_slot.get('link')
            if link_id in link_lookup:
                targets[normalized] = link_lookup[link_id]
                break
    return targets

def log_debug(message, level='INFO'):
    level_text = (str(level) or 'INFO').upper()
    if level_text == 'INFO' and not getattr(config, "DEBUG_MODE", False):
        return
    timestamp = time.strftime('%H:%M:%S')
    print(f'[{timestamp}] [CHARONOP] [{level_text}] {message}')


def _inject_png_text_chunk(image_path: str, key: str, text: str) -> None:
    if not image_path or not os.path.exists(image_path):
        return
    try:
        with open(image_path, 'rb') as handle:
            data = handle.read()
    except Exception as exc:
        log_debug(f'Could not read PNG for metadata injection: {exc}', 'WARNING')
        return

    if len(data) < 12 or data[:8] != b'\x89PNG\r\n\x1a\n':
        log_debug('File is not a PNG; skipping metadata injection.', 'WARNING')
        return

    cursor = 8
    iend_index = None
    while cursor + 8 <= len(data):
        length = int.from_bytes(data[cursor:cursor + 4], 'big')
        chunk_type = data[cursor + 4:cursor + 8]
        total_length = 12 + length
        if cursor + total_length > len(data):
            break
        if chunk_type == b'IEND':
            iend_index = cursor
            break
        cursor += total_length

    if iend_index is None:
        log_debug('Could not locate IEND chunk; skipping metadata injection.', 'WARNING')
        return

    signature = data[:8]
    before_iend = data[8:iend_index]
    after_iend = data[iend_index:]

    try:
        payload = key.encode('latin-1') + b'\x00' + text.encode('latin-1')
    except UnicodeEncodeError:
        payload = key.encode('latin-1', errors='ignore') + b'\x00' + text.encode('utf-8', errors='ignore')

    chunk = bytearray()
    chunk.extend(len(payload).to_bytes(4, 'big'))
    chunk.extend(b'tEXt')
    chunk.extend(payload)
    crc = zlib.crc32(b'tEXt' + payload) & 0xFFFFFFFF
    chunk.extend(crc.to_bytes(4, 'big'))

    try:
        with open(image_path, 'wb') as handle:
            handle.write(signature + before_iend + chunk + after_iend)
    except Exception as exc:
        log_debug(f'Failed to write PNG metadata: {exc}', 'WARNING')


def embed_png_metadata(image_path: str, metadata: Dict[str, Any]) -> None:
    if not image_path or not image_path.lower().endswith('.png'):
        return
    try:
        payload = json.dumps(metadata, separators=(',', ':'), ensure_ascii=True)
    except Exception as exc:
        log_debug(f'Could not serialize metadata for PNG: {exc}', 'WARNING')
        return
    _inject_png_text_chunk(image_path, 'CharonMetadata', payload)


def embed_png_workflow(image_path: str, workflow_payload: str) -> None:
    if not image_path or not image_path.lower().endswith('.png'):
        return
    if not workflow_payload:
        return
    try:
        _inject_png_text_chunk(image_path, 'workflow', workflow_payload)
    except Exception as exc:
        log_debug(f'Failed to embed workflow metadata: {exc}', 'WARNING')


def _batch_nav_command(step: int) -> str:
    return (
        "import json, nuke\n"
        "node = nuke.thisNode()\n"
        "outputs_knob = node.knob('charon_batch_outputs')\n"
        "index_knob = node.knob('charon_batch_index')\n"
        "if outputs_knob is None or index_knob is None:\n"
        "    nuke.message('Batch outputs unavailable.')\n"
        "    return\n"
        "try:\n"
        "    raw = outputs_knob.value()\n"
        "except Exception:\n"
        "    raw = ''\n"
        "try:\n"
        "    data = json.loads(raw) if raw else []\n"
        "except Exception:\n"
        "    data = []\n"
        "outputs = []\n"
        "if isinstance(data, list):\n"
        "    for entry in data:\n"
        "        if isinstance(entry, str):\n"
        "            outputs.append(entry)\n"
        "        elif isinstance(entry, dict):\n"
        "            path = entry.get('output_path')\n"
        "            if path:\n"
        "                outputs.append(path)\n"
        "if not outputs:\n"
        "    nuke.message('No batch outputs stored yet.')\n"
        "    return\n"
        "try:\n"
        "    idx = int(index_knob.value())\n"
        "except Exception:\n"
        "    idx = 0\n"
        "idx = max(0, min(len(outputs)-1, idx + ({step})))\n"
        "index_knob.setValue(idx)\n"
        "path = outputs[idx]\n"
        "try:\n"
        "    node['file'].setValue(path)\n"
        "except Exception:\n"
        "    pass\n"
"label_knob = node.knob('charon_batch_label')\n"
"if label_knob is not None:\n"
"    try:\n"
"        label_knob.setValue('')\n"
"    except Exception:\n"
"        pass\n"
    ).format(step=step)


SEED_INPUT_KEYS = (
    'seed',
    'noise_seed',
    'control_seed',
    'seed_control',
    'seed_noise',
)


def _capture_seed_inputs(prompt: Dict[str, Any]) -> List[Tuple[str, str, int]]:
    records: List[Tuple[str, str, int]] = []
    for node_id, node_data in prompt.items():
        inputs = node_data.get('inputs')
        if not isinstance(inputs, dict):
            continue
        for key in SEED_INPUT_KEYS:
            value = inputs.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                try:
                    records.append((node_id, key, int(value)))
                except Exception:
                    continue
    return records


def _apply_seed_offset(prompt: Dict[str, Any], records: List[Tuple[str, str, int]], offset: int) -> None:
    if not offset:
        return
    for node_id, key, base_value in records:
        node_data = prompt.get(node_id)
        if not isinstance(node_data, dict):
            continue
        inputs = node_data.get('inputs')
        if not isinstance(inputs, dict):
            continue
        inputs[key] = (base_value + offset) & 0xFFFFFFFF


def _resolve_client_side_logic(node, parameter_specs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Execute client-side parameter logic (Seed Control) before submission.
    Returns a dictionary of {knob_name: value} to overlap read values.
    """
    overrides = {}
    if not parameter_specs:
        return overrides

    # Group specs by node_id
    by_node = {}
    for spec in parameter_specs:
        node_id = spec.get('node_id')
        if node_id:
            by_node.setdefault(node_id, []).append(spec)

    for node_id, specs in by_node.items():
        seed_spec = None
        control_spec = None
        
        for spec in specs:
            knob_name = spec.get('knob')
            if not knob_name:
                continue
            
            # Identify by attribute name
            attr = str(spec.get('attribute') or "").lower()
            
            # Standard ComfyUI seed parameter names
            if attr in ('seed', 'noise_seed', 'seed_noise'):
                 seed_spec = spec
            # Standard ComfyUI control widget names
            elif attr in ('control_after_generate', 'control', 'seed_control'):
                 control_spec = spec
        
        if seed_spec and control_spec:
            updates = _apply_seed_control(node, seed_spec, control_spec)
            if updates:
                overrides.update(updates)
                
    return overrides


def _apply_seed_control(node, seed_spec, control_spec) -> Dict[str, Any]:
    seed_knob_name = seed_spec.get('knob')
    control_knob_name = control_spec.get('knob')
    updates = {}
    
    try:
        seed_knob = node.knob(seed_knob_name)
        control_knob = node.knob(control_knob_name)
    except Exception:
        return updates

    if not seed_knob or not control_knob:
        return updates
        
    try:
        raw_mode = control_knob.value()
        # Handle Enumeration_Knob potentially returning index (float/int) instead of string
        if isinstance(raw_mode, (int, float)):
            try:
                # Attempt to get the string label from the enumeration values
                # This relies on the knob having a 'values' method or similar, which Nuke Python API varies on.
                # Safer: assume standard order if index.
                # But safer still: rely on Nuke casting?
                # Actually, standard Nuke Enumeration_Knob.value() returns string name.
                # Only if it's not setup right does it return index.
                # Let's try to interpret common indices if string fails?
                # No, let's just cast to string and clean.
                mode = str(raw_mode)
            except Exception:
                mode = ""
        else:
            mode = str(raw_mode).lower().strip()
    except Exception:
        return updates
    
    # If mode is numeric (e.g. "3.0"), map it to the choices list if possible
    # Choices order: fixed, increment, decrement, randomize
    if mode.replace(".", "", 1).isdigit():
        try:
            idx = int(float(mode))
            choices = ["fixed", "increment", "decrement", "randomize"]
            if 0 <= idx < len(choices):
                mode = choices[idx]
        except Exception:
            pass
            
    try:
        current_seed = int(seed_knob.value())
    except Exception:
        current_seed = 0

    log_debug(f"Seed control logic: mode='{mode}', current_seed={current_seed}")
    
    new_seed = current_seed
    
    if mode == 'fixed':
        pass
    elif mode == 'increment':
        new_seed = current_seed + 1
    elif mode == 'decrement':
        new_seed = current_seed - 1
    elif mode == 'randomize':
        # Generate a random 15-digit integer (similar magnitude to user preference)
        new_seed = random.randint(100_000_000_000_000, 999_999_999_999_999)
        
    if new_seed != current_seed:
        # DATA: Store the new seed in updates so submission uses it immediately
        updates[seed_knob_name] = str(new_seed)
        
        # UI: Queue a visual update for the user
        def _force_redraw():
            try:
                # Re-setting the value in the main thread event loop helps wake up the UI
                seed_knob.setValue(str(new_seed))
                # Toggling visibility forces Nuke to repaint the widget layout
                seed_knob.setVisible(False)
                seed_knob.setVisible(True)
            except Exception:
                pass
        try:
            import nuke
            nuke.executeInMainThread(_force_redraw)
        except Exception:
            pass

        log_debug(f"Client-side logic: Calculated seed {current_seed} -> {new_seed} (Mode: {mode})")
        
    return updates


def _apply_aces_pre_write_transform(node_to_render, aces_enabled: bool):
    """
    Apply ACEScg pre-write transform if enabled.
    Returns the node that should be connected to the Write node input.
    """
    if not aces_enabled:
        return node_to_render

    import nuke
    ocm_display = nuke.createNode("OCIODisplay")
    ocm_display.setInput(0, node_to_render)
    ocm_display['colorspace'].setValue("scene_linear")
    ocm_display['display'].setValue("sRGB Display")
    ocm_display['view'].setValue("ACES 1.0 SDR-video")
    ocm_display.setName("OCIODisplay_ACEScg_PreWrite")
    # Position relative to input_node for cleaner graph
    ocm_display.setXpos(node_to_render.xpos())
    ocm_display.setYpos(node_to_render.ypos() + 50)

    return ocm_display

def _run_3d_texturing_step2_logic(
    node,
    workflow_data: Dict[str, Any],
    comfy_client: ComfyUIClient,
    update_progress,
    temp_dir: str,
    connected_inputs: Dict[int, Any],
):
    try:
        import nuke
    except ImportError:
        raise RuntimeError('Nuke is required for 3D Texturing Step 2.')

    log_debug('Starting 3D Texturing - Step 2 logic...')
    
    # 1. Locate Resources
    rig_group = nuke.toNode("Charon_Coverage_Rig")
    if not rig_group:
        raise RuntimeError("Charon_Coverage_Rig not found. Please run Step 1 (Generate Coverage) first.")
        
    contact_sheet = None
    with rig_group:
        contact_sheet = nuke.toNode("ContactSheet1")
        if not contact_sheet:
            for n in nuke.allNodes("ContactSheet"):
                contact_sheet = n
                break
    
    if not contact_sheet:
        raise RuntimeError("ContactSheet not found inside Charon_Coverage_Rig.")
        
    camera_views = []
    for i in range(contact_sheet.inputs()):
        inp = contact_sheet.input(i)
        if inp:
            camera_views.append((i, inp))
            
    if not camera_views:
        raise RuntimeError("No camera views found connected to ContactSheet in rig.")
        
    # 2. Identify Init Image
    init_image_node = connected_inputs.get(0)
    if not init_image_node:
        raise RuntimeError("Input 0 (Init Image) must be connected for Step 2.")
        
    update_progress(0.1, "Rendering init image")
    init_image_path = os.path.join(temp_dir, f'step2_init_{str(uuid.uuid4())[:8]}.png').replace('\\', '/')
    _render_nuke_node(init_image_node, init_image_path)
    init_image_upload = comfy_client.upload_image(init_image_path)
    
    # 3. Identify Workflow Targets
    set_targets = build_set_targets(workflow_data)
    target_init = set_targets.get('charoninput_init_image')
    target_coverage = set_targets.get('charoninput_coverage_rig')
    
    # Fallback to LoadImage nodes if SetNodes not found (simplified heuristic)
    load_images = []
    if not target_init or not target_coverage:
        for nid, ndata in workflow_data.items():
            if ndata.get('class_type') == 'LoadImage':
                load_images.append(nid)
        if len(load_images) >= 2:
            if not target_init: target_init = (load_images[0], 'image')
            if not target_coverage: target_coverage = (load_images[1], 'image')

    if not target_init or not target_coverage:
        raise RuntimeError("Could not identify CharonInput_init_image or CharonInput_coverage_rig targets in workflow.")

    results = []
    
    for idx, (cam_index, view_node) in enumerate(camera_views):
        progress_base = 0.2 + (0.8 * (idx / len(camera_views)))
        update_progress(progress_base, f"Processing view {idx+1}/{len(camera_views)}")
        log_debug(f"Starting execution for camera view {idx}...")
        
        # Render View
        view_path = os.path.join(temp_dir, f'step2_view_{idx}_{str(uuid.uuid4())[:8]}.png').replace('\\', '/')
        with rig_group:
            _render_nuke_node(view_node, view_path)
        view_upload = comfy_client.upload_image(view_path)
        
        # Prepare Workflow
        prompt = copy.deepcopy(workflow_data)
        _assign_to_workflow(prompt, target_init[0], init_image_upload)
        _assign_to_workflow(prompt, target_coverage[0], view_upload)
        
        # Execute
        prompt_id = comfy_client.submit_workflow(prompt)
        if not prompt_id:
            raise Exception("Failed to submit workflow to ComfyUI")
        log_debug(f"Submitted view {idx}, prompt_id: {prompt_id}")
            
        # Wait for result (Simplified wait loop)
        output_file = _wait_for_single_image(comfy_client, prompt_id, timeout=300)
        if output_file:
            # Download/Copy result
            ext = os.path.splitext(output_file)[1]
            local_out = allocate_charon_output_path(
                _normalize_node_id(_safe_knob_value(node, "charon_node_id")),
                "step2",
                ext,
                "user",
                "TexturingStep2",
                "2D",
                f"View_{idx}"
            )
            success = comfy_client.download_file(output_file, local_out)
            if success:
                results.append(local_out)
            else:
                log_debug(f"Failed to download result for view {idx}", "WARNING")
        else:
            log_debug(f"No output for view {idx}", "WARNING")

    if results:
        update_progress(1.0, "Creating Contact Sheet", extra={'batch_outputs': results}) # Store results in extra for potential use
        nuke.executeInMainThread(lambda: _create_step2_result_group(node, results))
    else:
        raise Exception("No results generated from Step 2 execution.")

def _render_nuke_node(node_to_render, path):
    import nuke
    from . import preferences
    aces_enabled = preferences.get_preference("aces_mode_enabled", False)
    
    transformed_node = _apply_aces_pre_write_transform(node_to_render, aces_enabled)

    w = nuke.createNode("Write", inpanel=False)
    w.setInput(0, transformed_node)
    if aces_enabled:
        w['raw'].setValue(True)
    w['file'].setValue(path)
    w['file_type'].setValue("png")
    # Ensure alpha is handled if needed, but assuming standard render
    try:
        nuke.execute(w, nuke.frame(), nuke.frame())
    finally:
        nuke.delete(w)
        if transformed_node != node_to_render:
            try:
                nuke.delete(transformed_node)
            except Exception:
                pass

def _assign_to_workflow(workflow, node_id, filename):
    node = workflow.get(str(node_id))
    if node:
        inputs = node.setdefault('inputs', {})
        inputs['image'] = filename

def _wait_for_single_image(client, prompt_id, timeout=300):
    start = time.time()
    while time.time() - start < timeout:
        history = client.get_history(prompt_id)
        if history and prompt_id in history:
            outputs = history[prompt_id].get('outputs', {})
            for nid, out_data in outputs.items():
                images = out_data.get('images', [])
                if images:
                    return images[0].get('filename')
            return None
        time.sleep(1.0)
    return None

def _create_step2_result_group(charon_node, image_paths):
    import nuke
    
    # Deselect all to prevent auto-connection
    for n in nuke.selectedNodes():
        n.setSelected(False)
    
    start_x = charon_node.xpos()
    start_y = charon_node.ypos() + 200
    
    safe_name = "".join(c if c.isalnum() else "_" for c in charon_node.name())
    group_name = f"Charon_Step2_Output_{safe_name}"
    
    group = nuke.createNode("Group")
    group.setName(group_name)
    group.setInput(0, None)
    group.setXYpos(start_x, start_y)
    
    # Link to parent CharonOp
    charon_node_id = ""
    try:
        knob = charon_node.knob('charon_node_id')
        if knob:
            charon_node_id = knob.value()
    except Exception: pass
    
    if not charon_node_id:
        try:
            charon_node_id = charon_node.metadata('charon/node_id')
        except Exception: pass
        
    import uuid
    read_id = uuid.uuid4().hex[:12].lower()
    
    parent_knob = nuke.String_Knob('charon_parent_id', 'Charon Parent ID', charon_node_id or "")
    parent_knob.setFlag(nuke.NO_ANIMATION)
    parent_knob.setFlag(nuke.INVISIBLE)
    group.addKnob(parent_knob)
    
    read_id_knob = nuke.String_Knob('charon_read_id', 'Charon Read ID', read_id)
    read_id_knob.setFlag(nuke.NO_ANIMATION)
    read_id_knob.setFlag(nuke.INVISIBLE)
    group.addKnob(read_id_knob)
    
    info_tab = nuke.Tab_Knob('charon_info_tab', 'Charon Info')
    group.addKnob(info_tab)
    
    info_text = nuke.Text_Knob('charon_info_text', 'Metadata', '')
    group.addKnob(info_text)
    
    summary = [
        f"Parent ID: {charon_node_id or 'N/A'}",
        f"Read Node ID: {read_id or 'N/A'}",
        f"Status: Completed",
    ]
    info_text.setValue("\n".join(summary))
    
    anchor_knob = nuke.Double_Knob('charon_link_anchor', 'Charon Link Anchor')
    anchor_knob.setFlag(nuke.NO_ANIMATION)
    anchor_knob.setFlag(nuke.INVISIBLE)
    group.addKnob(anchor_knob)
    
    try:
        parent_name = charon_node.fullName()
        anchor_knob.setExpression(f"{parent_name}.charon_link_anchor")
    except Exception:
        pass
    
    try:
        group.setMetaData('charon/parent_id', charon_node_id or "")
        group.setMetaData('charon/read_id', read_id)
    except: pass
    
    group.begin()
    
    reads = []
    inner_x = 0
    inner_y = 0
    
    for idx, path in enumerate(image_paths):
        r = nuke.createNode("Read")
        r['file'].setValue(path.replace('\\', '/'))
        r.setXYpos(inner_x + (idx * 150), inner_y)
        reads.append(r)
        r.setSelected(False)
        
    for n in nuke.selectedNodes():
        n.setSelected(False)
        
    cs = nuke.createNode("ContactSheet")
    cs.setInput(0, None)
    cs.setXYpos(inner_x, inner_y + 200)
    cs['width'].setValue(3072)
    cs['height'].setValue(2048)
    cs['rows'].setValue(2)
    cs['columns'].setValue(3)
    cs['gap'].setValue(10)
    cs['roworder'].setValue("TopBottom")
    
    for i, r in enumerate(reads):
        # Create Text node for label
        txt = nuke.createNode("Text2")
        txt.setInput(0, r)
        try:
            filename = os.path.basename(r['file'].value())
            txt['message'].setValue(filename)
            txt['box'].setValue([0, 0, 1000, 100]) # Bottom left box
            txt['yjustify'].setValue("bottom")
            txt['global_font_scale'].setValue(0.5)
        except Exception:
            pass
        txt.setXYpos(r.xpos(), r.ypos() + 100)
        
        cs.setInput(i, txt)
    
    for n in nuke.selectedNodes():
        n.setSelected(False)
        
    output = nuke.createNode("Output")
    output.setInput(0, cs)
    output.setXYpos(cs.xpos(), cs.ypos() + 100)
    
    group.end()
    
    from . import preferences
    aces_enabled = preferences.get_preference("aces_mode_enabled", False)
    
    if aces_enabled:
        # Use existing helper or reimplement safely? 
        # INVERSE_VIEW_TRANSFORM_GROUP is available globally
        from .paths import get_charon_temp_dir
        ivt_temp = os.path.join(get_charon_temp_dir(), f"ivt_step2_{str(uuid.uuid4())[:8]}.nk").replace("\\", "/")
        try:
            with open(ivt_temp, "w") as f:
                f.write(INVERSE_VIEW_TRANSFORM_GROUP)
            
            # Deselect group so paste doesn't auto-connect wrong or something?
            # nodePaste connects to selected?
            # We want to connect to 'group'.
            # If we select 'group', nodePaste might connect input 0 to it.
            group.setSelected(True)
            
            nuke.nodePaste(ivt_temp)
            ivt_node = nuke.selectedNode()
            ivt_node.setInput(0, group)
            ivt_node.setXpos(group.xpos())
            ivt_node.setYpos(group.ypos() + 200)
            
        except Exception as e:
            log_debug(f"Failed to create Step 2 IVT node: {e}", "WARNING")
        finally:
            if os.path.exists(ivt_temp):
                try: os.remove(ivt_temp)
                except: pass




def process_charonop_node():
    try:
        import nuke  # type: ignore
    except ImportError as exc:  # pragma: no cover - guarded for testing
        raise RuntimeError('Nuke is required to process CharonOp nodes.') from exc

    try:
        log_debug('Starting CharonOp node processing...')
        node = nuke.thisNode()

        if hasattr(node, 'setMetaData'):
            metadata_writer = node.setMetaData
        elif hasattr(node, 'setMetadata'):
            metadata_writer = node.setMetadata
        else:
            metadata_writer = None

        metadata_warning_emitted = False

        def write_metadata(key, value):
            nonlocal metadata_warning_emitted
            if not metadata_writer:
                metadata_warning_emitted = True
                return False
            try:
                metadata_writer(key, value)
                return True
            except Exception as exc:
                if not metadata_warning_emitted:
                    log_debug(f"Failed to persist metadata '{key}': {exc}", 'WARNING')
                    metadata_warning_emitted = True
                return False
        def read_cached_prompt():
            path_value = ""
            try:
                knob = node.knob('charon_prompt_path')
                if knob is not None:
                    path_value = str(knob.value()).strip()
            except Exception:
                path_value = ""
            hash_value = ""
            try:
                meta_val = node.metadata('charon/prompt_hash')
                if meta_val is not None:
                    hash_value = str(meta_val).strip()
            except Exception:
                hash_value = ""
            return path_value, hash_value

        def store_cached_prompt(path_value, hash_value):
            normalized_path = path_value.replace('\\', '/') if isinstance(path_value, str) else ''
            try:
                knob = node.knob('charon_prompt_path')
                if knob is not None:
                    knob.setValue(normalized_path)
            except Exception:
                pass
            write_metadata('charon/prompt_hash', hash_value or '')
            if hash_value:
                log_debug(f'Stored prompt cache hash {hash_value}')
            if normalized_path:
                log_debug(f'Stored prompt cache path {normalized_path}')
        
        # Set initial status
        try:
            node.knob('charon_status').setValue('Preparing node')
            node.knob('charon_progress').setValue(0.0)
        except Exception:
            pass

        try:
            status_payload_knob = node.knob('charon_status_payload')
        except Exception:
            status_payload_knob = None

        def resolve_auto_import():
            try:
                knob = node.knob('charon_auto_import')
                if knob is not None:
                    try:
                        return bool(int(knob.value()))
                    except Exception:
                        return bool(knob.value())
            except Exception:
                pass
            try:
                meta = node.metadata('charon/auto_import')
                if isinstance(meta, str):
                    lowered = meta.strip().lower()
                    if lowered in {'0', 'false', 'off', 'no'}:
                        return False
                    if lowered in {'1', 'true', 'on', 'yes'}:
                        return True
                elif meta is not None:
                    return bool(meta)
            except Exception:
                pass
            return True

        current_run_id = str(uuid.uuid4())
        run_started_at = time.time()

        def load_status_payload():
            raw = None
            try:
                raw = node.metadata("charon/status_payload")
            except Exception:
                pass
            if not raw and status_payload_knob:
                try:
                    raw = status_payload_knob.value()
                except Exception:
                    raw = None
            if not raw:
                return {}
            try:
                return json.loads(raw)
            except Exception:
                return {}

        def save_status_payload(payload):
            serialized = json.dumps(payload)
            write_metadata("charon/status_payload", serialized)
            if status_payload_knob:
                try:
                    status_payload_knob.setValue(serialized)
                except Exception as payload_error:
                    log_debug(f'Failed to store status payload knob: {payload_error}', 'WARNING')

        def ensure_history(payload):
            runs = payload.get('runs')
            if not isinstance(runs, list):
                runs = []
            payload['runs'] = runs
            return runs

        def update_last_output(path_value):
            try:
                knob = node.knob('charon_last_output')
                if knob is not None:
                    knob.setValue(path_value or "")
            except Exception:
                pass
            write_metadata('charon/last_output', path_value or "")
            try:
                recreate_knob = node.knob('charon_recreate_read')
            except Exception:
                recreate_knob = None
            if recreate_knob is not None:
                try:
                    linked = find_linked_read_node()
                except Exception:
                    linked = None
                has_output = bool(path_value)
                try:
                    recreate_knob.setEnabled(has_output)
                except Exception:
                    pass

        def _normalize_node_id(value: Optional[str]) -> str:
            if not value:
                return ""
            text = str(value).strip().lower()
            if not text:
                return ""
            return text[:12]

        def _safe_knob_value(owner, knob_name: str) -> Optional[str]:
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

        def _deduplicate_node_id(candidate: str) -> str:
            normalized = _normalize_node_id(candidate)
            if not normalized:
                return ""
            try:
                nodes_with_id: List[Any] = []
                for other in nuke.allNodes("Group"):
                    other_id = _normalize_node_id(_safe_knob_value(other, "charon_node_id"))
                    if not other_id:
                        try:
                            meta_val = other.metadata("charon/node_id")
                        except Exception:
                            meta_val = ""
                        other_id = _normalize_node_id(meta_val)
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

            nodes_with_id.sort(key=_node_sort_key)
            keeper = nodes_with_id[0]
            for duplicate in nodes_with_id[1:]:
                try:
                    new_identifier = reset_charon_node_state(duplicate) or ""
                except Exception:
                    new_identifier = ""
                if duplicate is node:
                    normalized = _normalize_node_id(new_identifier)

            if keeper is node:
                refreshed = _normalize_node_id(_safe_knob_value(node, "charon_node_id"))
                return refreshed or normalized

            if node in nodes_with_id[1:]:
                refreshed = _normalize_node_id(_safe_knob_value(node, "charon_node_id"))
                if refreshed:
                    return refreshed
                try:
                    regenerated = reset_charon_node_state(node) or ""
                except Exception:
                    regenerated = ""
                return _normalize_node_id(regenerated)

            return normalized

        def ensure_charon_node_id():
            node_id = _normalize_node_id(_safe_knob_value(node, 'charon_node_id'))
            if not node_id:
                try:
                    meta_val = node.metadata('charon/node_id')
                    node_id = _normalize_node_id(meta_val)
                except Exception:
                    node_id = ""
                if node_id:
                    try:
                        knob = node.knob('charon_node_id')
                        if knob is not None:
                            knob.setValue(node_id)
                    except Exception:
                        pass
            node_id = _deduplicate_node_id(node_id)
            if not node_id:
                node_id = uuid.uuid4().hex[:12].lower()
                try:
                    knob = node.knob('charon_node_id')
                    if knob is not None:
                        knob.setValue(node_id)
                except Exception:
                    pass
            try:
                info_knob = node.knob('charon_node_id_info')
                if info_knob is not None:
                    info_knob.setValue(node_id or "Unknown")
            except Exception:
                pass
            write_metadata('charon/node_id', node_id or "")
            return node_id

        def _collect_linked_read_ids(parent_id: str) -> List[str]:
            normalized_parent = _normalize_node_id(parent_id)
            if not normalized_parent:
                return []
            try:
                candidates = list(nuke.allNodes())
            except Exception:
                return []
            ids: List[str] = []
            for candidate in candidates:
                parent_match = ""
                try:
                    parent_match = _normalize_node_id(candidate.metadata('charon/parent_id'))
                except Exception:
                    parent_match = ""
                if parent_match != normalized_parent:
                    try:
                        parent_match = _normalize_node_id(_safe_knob_value(candidate, 'charon_parent_id'))
                    except Exception:
                        parent_match = ""
                if parent_match != normalized_parent:
                    continue
                read_identifier = ""
                for getter in (
                    lambda: candidate.metadata('charon/read_id'),
                    lambda: candidate.metadata('charon/read_node_id'),
                    lambda: _safe_knob_value(candidate, 'charon_read_id'),
                    lambda: _safe_knob_value(candidate, 'charon_read_node_id'),
                    lambda: candidate.name(),
                ):
                    try:
                        candidate_val = getter()
                    except Exception:
                        candidate_val = ""
                    read_identifier = _normalize_node_id(candidate_val)
                    if read_identifier:
                        break
                if read_identifier and read_identifier not in ids:
                    ids.append(read_identifier)
            return ids

        def _refresh_linked_read_info():
            try:
                info_knob = node.knob('charon_read_id_info')
            except Exception:
                info_knob = None
            if info_knob is None:
                return
            linked_ids = _collect_linked_read_ids(charon_node_id)
            display = "\n".join(linked_ids) if linked_ids else "Not linked"
            try:
                info_knob.setValue(display)
            except Exception:
                try:
                    info_knob.setText(display)  # type: ignore
                except Exception:
                    pass

        charon_node_id = ensure_charon_node_id()
        _refresh_linked_read_info()
        user_slug = get_current_user_slug()
        def resolve_batch_count() -> int:
            try:
                knob = node.knob('charon_batch_count')
                if knob is not None:
                    return max(1, int(knob.value()))
            except Exception:
                pass
            return 1

        batch_count = resolve_batch_count()
        _cached_script_name: Optional[str] = None

        def _resolve_nuke_script_name() -> str:
            nonlocal _cached_script_name
            if _cached_script_name is not None:
                return _cached_script_name
            script_reference = ""
            try:
                root = nuke.root()
            except Exception:
                root = None
            if root is not None:
                try:
                    script_reference = root.name()
                except Exception:
                    script_reference = ""
                if not script_reference:
                    try:
                        name_knob = root.knob("name")
                        if name_knob is not None:
                            script_reference = str(name_knob.value() or "")
                    except Exception:
                        script_reference = ""
            if script_reference:
                base = os.path.splitext(os.path.basename(script_reference))[0]
                _cached_script_name = base or "untitled"
            else:
                _cached_script_name = "untitled"
            return _cached_script_name

        def ensure_link_anchor_value():
            try:
                anchor_knob = node.knob('charon_link_anchor')
            except Exception:
                anchor_knob = None
            anchor_value = None
            if anchor_knob is not None:
                try:
                    anchor_value = float(anchor_knob.value())
                except Exception:
                    anchor_value = None
            if not anchor_value:
                try:
                    anchor_value = int(charon_node_id, 16) / float(16 ** len(charon_node_id))
                except Exception:
                    anchor_value = (time.time() % 1.0) or 0.5
                if anchor_knob is not None:
                    try:
                        anchor_knob.setValue(anchor_value)
                    except Exception:
                        pass
            write_metadata('charon/link_anchor', anchor_value or "")
            return anchor_value or 0.0

        def _coerce_crop_box(raw) -> Optional[Tuple[float, float, float, float]]:
            if raw is None:
                return None

            coords: List[Optional[float]] = []
            if isinstance(raw, (list, tuple)):
                coords.extend(raw[:4])
            else:
                for attr in ('x', 'y', 'r', 't'):
                    try:
                        candidate = getattr(raw, attr)
                        candidate = candidate() if callable(candidate) else candidate
                    except Exception:
                        candidate = None
                    coords.append(candidate)

            if len(coords) < 4:
                return None

            numeric: List[float] = []
            for coord in coords[:4]:
                if coord is None:
                    return None
                try:
                    numeric.append(float(coord))
                except Exception:
                    return None

            return tuple(numeric)

        def resolve_crop_settings() -> Optional[Tuple[float, float, float, float]]:
            enabled = False
            try:
                knob = node.knob('charon_use_crop')
                if knob is not None:
                    try:
                        enabled = bool(int(knob.value()))
                    except Exception:
                        enabled = bool(knob.value())
            except Exception:
                enabled = False

            if not enabled:
                return None

            try:
                bbox_knob = node.knob('charon_crop_bbox')
            except Exception:
                bbox_knob = None
            if bbox_knob is None:
                return None

            try:
                raw_box = bbox_knob.value()
            except Exception:
                try:
                    raw_box = bbox_knob.getValue()  # type: ignore[attr-defined]
                except Exception:
                    raw_box = None

            crop_box = _coerce_crop_box(raw_box)
            if not crop_box:
                log_debug('Use Crop enabled but crop box is invalid; skipping crop', 'WARNING')
                return None

            x, y, r, t = crop_box
            if r <= x or t <= y:
                log_debug('Use Crop enabled but crop box is empty; skipping crop', 'WARNING')
                return None

            log_debug(f'Using crop box {crop_box} for CharonOp inputs')
            return crop_box

        link_anchor_value = ensure_link_anchor_value()
        current_node_state = 'Ready'

        def iter_candidate_read_nodes():
            candidates: List[Any] = []
            try:
                candidates.extend(list(nuke.allNodes('Read')))
            except Exception:
                pass
            try:
                candidates.extend(list(nuke.allNodes('ReadGeo2')))
            except Exception:
                pass
            return candidates

        def read_node_parent_id(candidate):
            try:
                meta_val = candidate.metadata('charon/parent_id')
            except Exception:
                meta_val = None
            if isinstance(meta_val, str):
                value = _normalize_node_id(meta_val)
            elif meta_val is not None:
                try:
                    value = _normalize_node_id(str(meta_val))
                except Exception:
                    value = ""
            else:
                value = ""
            if value:
                return value
            parent_knob_value = _safe_knob_value(candidate, 'charon_parent_id')
            return _normalize_node_id(parent_knob_value)

        def read_node_unique_id(candidate):
            try:
                meta_val = candidate.metadata('charon/read_id')
            except Exception:
                meta_val = None
            read_id = _normalize_node_id(meta_val)
            if not read_id:
                knob_value = _safe_knob_value(candidate, 'charon_read_id')
                read_id = _normalize_node_id(knob_value)
            return read_id

        def find_read_node_by_id(read_id: str):
            if not read_id:
                return None
            for candidate in iter_candidate_read_nodes():
                if read_node_unique_id(candidate) == read_id:
                    return candidate
            return None

        def _stored_read_node_id():
            value = _normalize_node_id(_safe_knob_value(node, 'charon_read_node_id'))
            if value:
                return value
            try:
                meta_val = node.metadata('charon/read_node_id')
                return _normalize_node_id(meta_val)
            except Exception:
                return ""

        def find_read_node_for_parent():
            if not charon_node_id:
                return None
            stored = _stored_read_node_id()
            candidate = find_read_node_by_id(stored)
            if candidate is not None:
                return candidate
            for option in iter_candidate_read_nodes():
                if read_node_parent_id(option) == charon_node_id:
                    return option
            fallback_name = _safe_knob_value(node, 'charon_read_node')
            if fallback_name:
                try:
                    fallback = nuke.toNode(str(fallback_name))
                except Exception:
                    fallback = None
                if fallback is not None and getattr(fallback, "Class", lambda: "")() in {"Read", "ReadGeo2"}:
                    return fallback
            return None

        def find_linked_read_node():
            stored = _stored_read_node_id()
            candidate = find_read_node_by_id(stored)
            if candidate is not None:
                return candidate
            return find_read_node_for_parent()

        def _collect_target_reads():
            targets = []
            try:
                norm_parent = _normalize_node_id(charon_node_id)
                if not norm_parent:
                    return targets
                for candidate in iter_candidate_read_nodes():
                    try:
                        parent_val = _normalize_node_id(read_node_parent_id(candidate))
                    except Exception:
                        parent_val = ""
                    raw_parent = ""
                    try:
                        raw_parent = _normalize_node_id(candidate.metadata('charon/parent_id'))
                    except Exception:
                        raw_parent = ""
                    try:
                        knob_parent = _normalize_node_id(candidate.knob('charon_parent_id').value())
                    except Exception:
                        knob_parent = ""
                    if parent_val == norm_parent or raw_parent == norm_parent or knob_parent == norm_parent:
                        targets.append(candidate)
            except Exception:
                pass
            return targets

        def apply_status_color(state: str, read_node_override=None):
            tile_color = status_to_tile_color(state)
            gl_color = status_to_gl_color(state)

            def _is_read_node(target) -> bool:
                try:
                    return target.Class() in {"Read", "ReadGeo2"}
                except Exception:
                    return False

            def _apply_to_target(target):
                if target is None:
                    return
                try:
                    target.setMetaData('charon/status', state or "")
                except Exception:
                    pass
                try:
                    color_knob = target["tile_color"]
                except Exception:
                    color_knob = None
                if color_knob is not None:
                    try:
                        try:
                            color_knob.clearAnimated()
                        except Exception:
                            pass
                        color_knob.setValue(tile_color)
                    except Exception:
                        pass
                if gl_color is not None:
                    try:
                        gl_knob = target["gl_color"]
                    except Exception:
                        gl_knob = None
                    if gl_knob is not None:
                        try:
                            try:
                                gl_knob.clearAnimated()
                            except Exception:
                                pass
                            gl_knob.setValue(list(gl_color))
                        except Exception:
                            pass
                if _is_read_node(target):
                    try:
                        ensure_read_node_info(target, read_node_unique_id(target), state)
                    except Exception:
                        pass

            def _apply_all():
                _apply_to_target(node)

            try:
                nuke.executeInMainThread(_apply_all)
            except Exception:
                _apply_all()

            targets = []
            if read_node_override is not None:
                targets.append(read_node_override)
            else:
                candidate = find_linked_read_node()
                if candidate is not None:
                    targets.append(candidate)
            for candidate in _collect_target_reads():
                if candidate not in targets:
                    targets.append(candidate)

            try:
                target_names = []
                for t in targets:
                    try:
                        target_names.append(f"{t.name()}[{read_node_parent_id(t)}]")
                    except Exception:
                        target_names.append("unknown")
                log_debug(f"Apply status {state} to reads: {', '.join(target_names) or 'none'}")
            except Exception:
                pass

            try:
                recreate_knob = node.knob('charon_recreate_read')
            except Exception:
                recreate_knob = None
            if recreate_knob is not None:
                linked_node = targets[0] if targets else find_linked_read_node()
                has_read = linked_node is not None
                last_output_value = _safe_knob_value(node, 'charon_last_output')
                if not last_output_value:
                    try:
                        last_output_value = node.metadata('charon/last_output')
                    except Exception:
                        last_output_value = ""
                has_output = bool(str(last_output_value or "").strip())
                try:
                    recreate_knob.setEnabled(has_output)
                except Exception:
                    pass

            def _apply_all_targets():
                _apply_to_target(node)
                for target in targets:
                    _apply_to_target(target)

            try:
                nuke.executeInMainThread(_apply_all_targets)
            except Exception:
                _apply_all_targets()

        try:
            initial_payload = load_status_payload()
        except Exception:
            initial_payload = None
        if isinstance(initial_payload, dict):
            initial_state = initial_payload.get('state') or initial_payload.get('status')
            if initial_state:
                current_node_state = initial_state
        apply_status_color(current_node_state)

        def assign_read_label(read_node, label_text=None):
            if read_node is None:
                return
            output_label = ""
            try:
                output_label = (read_node.metadata('charon/output_label') or "").strip()
            except Exception:
                output_label = ""
            if not output_label:
                try:
                    knob_val = read_node.knob('charon_output_label')
                    if knob_val:
                        output_label = str(knob_val.value() or "").strip()
                except Exception:
                    output_label = ""
            file_display = ""
            try:
                file_display = os.path.basename(str(read_node['file'].value() or "").strip())
            except Exception:
                file_display = ""
            if label_text is None:
                parts = []
                if output_label:
                    parts.append(f"Output: {output_label}")
                if file_display:
                    parts.append(f"File: {file_display}")
                parent_text = read_node_parent_id(read_node) or 'N/A'
                read_id_text = read_node_unique_id(read_node) or 'N/A'
                parts.append(f"Charon Parent: {parent_text}")
                parts.append(f"Read ID: {read_id_text}")
                label_text = "\n".join(parts)
        try:
            label_knob = read_node['label']
        except Exception:
            label_knob = None
        if label_knob is not None:
            try:
                label_knob.setValue(label_text or "")
            except Exception:
                pass

        def ensure_batch_navigation_controls(read_node):
            return None, None, None

        def ensure_read_node_info(read_node, read_id: str, state: Optional[str] = None):
            if read_node is None:
                return
            try:
                info_tab = read_node.knob('charon_info_tab')
            except Exception:
                info_tab = None
            if info_tab is None:
                try:
                    info_tab = nuke.Tab_Knob('charon_info_tab', 'Charon Info')
                    read_node.addKnob(info_tab)
                except Exception:
                    info_tab = None
            try:
                info_text = read_node.knob('charon_info_text')
            except Exception:
                info_text = None
            if info_text is None and info_tab is not None:
                try:
                    info_text = nuke.Text_Knob('charon_info_text', 'Metadata', '')
                    read_node.addKnob(info_text)
                except Exception:
                    info_text = None
            parent_display = read_node_parent_id(read_node) or 'N/A'
            status_display = state or current_node_state
            color_hex = resolve_status_color_hex(status_display)
            summary = [
                f"Parent ID: {parent_display}",
                f"Read Node ID: {read_id or 'N/A'}",
            ]
            summary.append(f"Status: {status_display or 'N/A'}")
            if color_hex:
                summary.append(f"Color: {color_hex.upper()}")
            if info_text is not None:
                try:
                    info_text.setValue("\n".join(summary))
                except Exception:
                    pass
            ensure_batch_navigation_controls(read_node)

        def mark_read_node(read_node):
            nonlocal current_node_state
            if read_node is None:
                return
            read_id = read_node_unique_id(read_node)
            if not read_id:
                read_id = uuid.uuid4().hex[:12].lower()
            if charon_node_id:
                try:
                    read_node.setMetaData('charon/parent_id', charon_node_id)
                except Exception:
                    pass
                try:
                    parent_knob = read_node.knob('charon_parent_id')
                except Exception:
                    parent_knob = None
                if parent_knob is None:
                    try:
                        parent_knob = nuke.String_Knob('charon_parent_id', 'Charon Parent ID', '')
                        parent_knob.setFlag(nuke.NO_ANIMATION)
                        parent_knob.setFlag(nuke.INVISIBLE)
                        read_node.addKnob(parent_knob)
                    except Exception:
                        parent_knob = None
                if parent_knob is not None:
                    try:
                        parent_knob.setValue(charon_node_id)
                    except Exception:
                        pass
            try:
                read_node.setMetaData('charon/read_id', read_id)
            except Exception:
                pass
            try:
                read_id_knob = read_node.knob('charon_read_id')
            except Exception:
                read_id_knob = None
            if read_id_knob is None:
                try:
                    read_id_knob = nuke.String_Knob('charon_read_id', 'Charon Read ID', '')
                    read_id_knob.setFlag(nuke.NO_ANIMATION)
                    read_id_knob.setFlag(nuke.INVISIBLE)
                    read_node.addKnob(read_id_knob)
                except Exception:
                    read_id_knob = None
            if read_id_knob is not None:
                try:
                    read_id_knob.setValue(read_id)
                except Exception:
                    pass
            ensure_read_node_info(read_node, read_id, current_node_state)
            assign_read_label(read_node)
            apply_status_color(current_node_state, read_node)

            try:
                read_anchor_knob = read_node.knob('charon_link_anchor')
            except Exception:
                read_anchor_knob = None
            if read_anchor_knob is None:
                try:
                    read_anchor_knob = nuke.Double_Knob('charon_link_anchor', 'Charon Link Anchor')
                    read_anchor_knob.setFlag(nuke.NO_ANIMATION)
                    read_anchor_knob.setFlag(nuke.INVISIBLE)
                    read_node.addKnob(read_anchor_knob)
                except Exception:
                    read_anchor_knob = None
            if read_anchor_knob is not None:
                try:
                    read_anchor_knob.setExpression(f"{node.fullName()}.charon_link_anchor")
                except Exception:
                    try:
                        read_anchor_knob.clearAnimated()
                    except Exception:
                        pass
                    try:
                        read_anchor_knob.setValue(link_anchor_value)
                    except Exception:
                        pass
            try:
                knob = node.knob('charon_read_node')
                if knob is not None:
                    knob.setValue(read_node.name())
            except Exception:
                pass
            write_metadata('charon/read_node', read_node.name())
            try:
                read_id_knob = node.knob('charon_read_node_id')
                if read_id_knob is not None:
                    read_id_knob.setValue(read_id or "")
            except Exception:
                pass
            write_metadata('charon/read_node_id', read_id or "")
            _refresh_linked_read_info()
            try:
                recreate_knob = node.knob('charon_recreate_read')
                if recreate_knob is not None:
                    recreate_knob.setEnabled(True)
            except Exception:
                pass
            try:
                payload = load_status_payload()
            except Exception:
                payload = None
            if isinstance(payload, dict):
                if payload.get('read_node_id') != read_id:
                    payload['read_node_id'] = read_id
                    try:
                        save_status_payload(payload)
                    except Exception:
                        pass

        def unlink_read_node(read_node):
            nonlocal current_node_state
            if read_node is None:
                return
            try:
                read_node.setMetaData('charon/parent_id', "")
            except Exception:
                pass
            try:
                read_node.setMetaData('charon/read_id', "")
            except Exception:
                pass
            try:
                parent_knob = read_node.knob('charon_parent_id')
            except Exception:
                parent_knob = None
            if parent_knob is not None:
                try:
                    parent_knob.setValue("")
                except Exception:
                    pass
            try:
                read_id_knob = read_node.knob('charon_read_id')
            except Exception:
                read_id_knob = None
            if read_id_knob is not None:
                try:
                    read_id_knob.setValue("")
                except Exception:
                    pass
            try:
                outputs_knob = read_node.knob('charon_batch_outputs')
            except Exception:
                outputs_knob = None
            if outputs_knob is not None:
                try:
                    outputs_knob.setValue("")
                except Exception:
                    pass
            try:
                index_knob = read_node.knob('charon_batch_index')
            except Exception:
                index_knob = None
            if index_knob is not None:
                try:
                    index_knob.setValue(0)
                except Exception:
                    pass
            try:
                label_knob = read_node.knob('charon_batch_label')
            except Exception:
                label_knob = None
            if label_knob is not None:
                try:
                    label_knob.setValue('')
                except Exception:
                    pass
            ensure_read_node_info(read_node, "", current_node_state)
            assign_read_label(read_node, "")
            try:
                knob = node.knob('charon_read_node_id')
                if knob is not None:
                    knob.setValue("")
            except Exception:
                pass
            write_metadata('charon/read_node_id', "")
            _refresh_linked_read_info()
            try:
                name_knob = node.knob('charon_read_node')
                if name_knob is not None:
                    name_knob.setValue("")
            except Exception:
                pass
            write_metadata('charon/read_node', "")
            has_output_value = _safe_knob_value(node, 'charon_last_output')
            if not has_output_value:
                try:
                    has_output_value = node.metadata('charon/last_output')
                except Exception:
                    has_output_value = ""
            try:
                recreate_knob = node.knob('charon_recreate_read')
                if recreate_knob is not None:
                    recreate_knob.setEnabled(bool(str(has_output_value or "").strip()))
            except Exception:
                pass
            apply_status_color(current_node_state)
            try:
                anchor_knob = read_node.knob('charon_link_anchor')
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
            if isinstance(payload, dict) and payload.get('read_node_id'):
                payload['read_node_id'] = ""
                try:
                    save_status_payload(payload)
                except Exception:
                    pass

        def _sanitize_name(value: str, default: str = "Workflow") -> str:
            text = (value or "").strip()
            if not text:
                text = default
            sanitized = "".join(c if c.isalnum() or c in {"_", "-"} else "_" for c in text)
            sanitized = sanitized.strip("_") or default
            return sanitized[:64]

        def _resolve_workflow_display_name() -> str:
            candidate = _safe_knob_value(node, 'charon_workflow_name')
            if candidate:
                return str(candidate).strip()
            try:
                meta_val = node.metadata('charon/workflow_name')
                if isinstance(meta_val, str) and meta_val.strip():
                    return meta_val.strip()
            except Exception:
                pass
            path_candidate = _safe_knob_value(node, 'workflow_path')
            if path_candidate:
                basename = os.path.basename(str(path_candidate).strip())
                if basename:
                    return basename.rsplit(".", 1)[0]
            return "Workflow"

        def ensure_placeholder_read_node():
            placeholder_path = get_placeholder_image_path()
            if not placeholder_path or not charon_node_id:
                return

            placeholder_norm = placeholder_path.replace("\\", "/").lower()
            existing_node = find_linked_read_node()

            if existing_node is not None:
                try:
                    current_file = str(existing_node['file'].value() or "").strip()
                except Exception:
                    current_file = ""
                current_norm = current_file.replace("\\", "/").lower()
                if not current_norm or current_norm == placeholder_norm:
                    try:
                        existing_node['file'].setValue(placeholder_path.replace("\\", "/"))
                        log_debug('Updated existing Read node with placeholder preview.')
                    except Exception as assign_error:
                        log_debug(f'Failed to assign placeholder to existing Read node: {assign_error}', 'WARNING')
                else:
                    log_debug('Existing Read node already has rendered output; skipping placeholder update.')
                mark_read_node(existing_node)
                return

            creator_group = node.parent() or nuke.root()
            try:
                creator_group.begin()
                read_node = nuke.createNode('Read', inpanel=False)
            finally:
                try:
                    creator_group.end()
                except Exception:
                    pass

            read_base = _sanitize_name(_resolve_workflow_display_name(), "Workflow")
            target_read_name = f"CR2D_{read_base}"
            try:
                read_node.setName(target_read_name)
            except Exception:
                try:
                    read_node.setName(f"CR2D_{read_base}_{charon_node_id}")
                except Exception:
                    try:
                        read_node.setName("CR2D")
                    except Exception:
                        pass
            try:
                read_node['file'].setValue(placeholder_path.replace("\\", "/"))
            except Exception as assign_error:
                log_debug(f'Failed to assign placeholder file: {assign_error}', 'WARNING')
            try:
                read_node.setXpos(node.xpos())
                read_node.setYpos(node.ypos() + 60)
            except Exception:
                pass
            try:
                read_node.setSelected(False)
            except Exception:
                pass
            mark_read_node(read_node)
            log_debug('Created placeholder Read node.')

        def initialize_status(message='Initializing'):
            payload = load_status_payload()
            runs = ensure_history(payload)
            now = run_started_at
            auto_flag = resolve_auto_import()
            payload['current_run'] = {
                'id': current_run_id,
                'status': 'Processing',
                'message': message,
                'progress': 0.0,
                'started_at': now,
                'updated_at': now,
                'auto_import': auto_flag,
            }
            payload.update({
                'status': message,
                'state': 'Processing',
                'message': message,
                'progress': 0.0,
                'run_id': current_run_id,
                'started_at': now,
                'updated_at': now,
                'auto_import': auto_flag,
            })
            payload['runs'] = runs
            save_status_payload(payload)

        initialize_status('Preparing node')

        workflow_data_str = node.knob('workflow_data').value()
        input_mapping_str = node.knob('input_mapping').value()
        temp_root = node.knob('charon_temp_dir').value()
        normalized_root = _normalize_charon_root(temp_root)
        if normalized_root != temp_root:
            temp_root = normalized_root
            try:
                node.knob('charon_temp_dir').setValue(temp_root)
            except Exception:
                pass
        try:
            workflow_path = node.knob('workflow_path').value()
        except Exception:
            workflow_path = ''

        workflow_display_name = _resolve_workflow_display_name()

        if not workflow_data_str or not input_mapping_str:
            log_debug('No workflow data found on CharonOp node', 'ERROR')
            raise RuntimeError('Missing workflow data on CharonOp node')

        workflow_data = json.loads(workflow_data_str)

        is_step2 = False
        try:
            from .metadata_manager import get_charon_config
            source_path = _safe_knob_value(node, 'charon_source_workflow_path')
            check_path = source_path or workflow_path or node.metadata('charon/workflow_path')
            
            log_debug(f"Checking Step 2 status for path: {check_path}")
            if check_path and os.path.exists(check_path):
                target_dir = os.path.dirname(check_path) if os.path.isfile(check_path) else check_path
                conf = get_charon_config(target_dir)
                is_step2 = bool(conf and conf.get('is_3d_texturing_step2'))
                log_debug(f"Step 2 detected: {is_step2} (from {target_dir})")
        except Exception as step2_err:
            log_debug(f"Step 2 check failed: {step2_err}", "WARNING")



        input_mapping = json.loads(input_mapping_str)
        parameter_specs = _load_parameter_specs(node)
        workflow_is_api = is_api_prompt(workflow_data)
        try:
            workflow_hash = compute_workflow_hash(workflow_data)
        except Exception as exc:
            workflow_hash = None
            log_debug(f"Failed to compute workflow hash: {exc}", "WARNING")

        cached_prompt_path, cached_prompt_hash = read_cached_prompt()
        cached_prompt_path = cached_prompt_path.strip() if isinstance(cached_prompt_path, str) else ""
        cached_prompt_hash = cached_prompt_hash.strip() if isinstance(cached_prompt_hash, str) else ""
        if (
            cached_prompt_path
            and cached_prompt_hash
            and workflow_hash
            and cached_prompt_hash != workflow_hash
        ):
            log_debug('Cached prompt hash differs from workflow hash; clearing stored prompt')
            store_cached_prompt('', '')
            cached_prompt_path = ''
            cached_prompt_hash = ''
        cached_prompt_data = None
        if (
            workflow_hash
            and cached_prompt_path
            and cached_prompt_hash
            and cached_prompt_hash == workflow_hash
        ):
            if os.path.exists(cached_prompt_path):
                try:
                    with open(cached_prompt_path, 'r', encoding='utf-8') as cached_handle:
                        candidate = json.load(cached_handle)
                    if is_api_prompt(candidate):
                        cached_prompt_data = candidate
                        log_debug(f'Loaded cached API prompt from {cached_prompt_path}')
                    else:
                        log_debug('Cached prompt is not API formatted; ignoring stored prompt', 'WARNING')
                except Exception as exc:
                    log_debug(f'Failed to read cached prompt: {exc}', 'WARNING')
            else:
                log_debug(f'Cached prompt path missing: {cached_prompt_path}', 'WARNING')
                store_cached_prompt('', '')

        if workflow_is_api and cached_prompt_data is None:
            cached_prompt_data = workflow_data

        needs_conversion = cached_prompt_data is None
        ui_workflow_source = workflow_data if isinstance(workflow_data, dict) else {}
        set_targets = build_set_targets(ui_workflow_source) if ui_workflow_source else {}
        initial_prompt_data = cached_prompt_data if cached_prompt_data is not None else None
        initial_prompt_path = cached_prompt_path if cached_prompt_data is not None else ""

        if not temp_root:
            log_debug('Temp directory not configured', 'ERROR')
            raise RuntimeError('Charon temp directory is not configured')

        temp_root = temp_root.replace('\\', '/')
        temp_dir = os.path.join(temp_root, 'temp')
        os.makedirs(temp_dir, exist_ok=True)

        converted_prompt_path = None
        workflow_folder = ''
        candidate_paths = [workflow_path]
        try:
            source_candidate = node.knob('charon_source_workflow_path').value()
        except Exception:
            source_candidate = ''
        if source_candidate and source_candidate not in candidate_paths:
            candidate_paths.append(source_candidate)
        try:
            meta_path = node.metadata('charon/workflow_path')
            if meta_path and meta_path not in candidate_paths:
                candidate_paths.append(meta_path)
        except Exception:
            pass
        try:
            meta_source_path = node.metadata('charon/source_workflow_path')
            if meta_source_path and meta_source_path not in candidate_paths:
                candidate_paths.append(meta_source_path)
        except Exception:
            pass

        for candidate in candidate_paths:
            if not candidate:
                continue
            folder_candidate = candidate if os.path.isdir(candidate) else os.path.dirname(candidate)
            if folder_candidate and os.path.isdir(folder_candidate):
                workflow_folder = folder_candidate
                break

        connected_inputs = {}
        total_inputs = node.inputs()
        for index in range(total_inputs):
            input_node = node.input(index)
            if input_node is not None:
                connected_inputs[index] = input_node

        crop_box = resolve_crop_settings()
        render_jobs = []
        ensure_placeholder_read_node()
        if isinstance(input_mapping, list):
            for mapping in input_mapping:
                if not isinstance(mapping, dict):
                    continue
                index = mapping.get('index')
                if index is None or index not in connected_inputs:
                    continue
                render_jobs.append({
                    'index': index,
                    'mapping': mapping,
                    'node': connected_inputs[index]
                })

        expected_inputs = len(input_mapping) if isinstance(input_mapping, list) else 0
        if not render_jobs and connected_inputs:
            first_index, first_node = next(iter(connected_inputs.items()))
            render_jobs.append({
                'index': first_index,
                'mapping': {'name': f'Input {first_index + 1}', 'type': 'image'},
                'node': first_node
            })
        elif not render_jobs and expected_inputs > 0:
            log_debug('Expected input nodes but none are connected', 'ERROR')
            raise RuntimeError('Please connect the required input nodes before processing')

        primary_job = None
        for job in render_jobs:
            mapping = job.get('mapping', {})
            if isinstance(mapping, dict) and mapping.get('type') == 'image':
                primary_job = job
                break
        if not primary_job and render_jobs:
            primary_job = render_jobs[0]
        primary_index = primary_job['index'] if primary_job else None

        rendered_files = {}
        if render_jobs:
            current_frame = int(nuke.frame())
            for job in render_jobs:
                idx = job['index']
                mapping = job.get('mapping', {})
                input_node = job['node']
                friendly_name = mapping.get('name', f'Input {idx + 1}') if isinstance(mapping, dict) else f'Input {idx + 1}'
                safe_tag = ''.join(c if c.isalnum() else '_' for c in friendly_name).strip('_') or f'input_{idx + 1}'
                temp_path = os.path.join(temp_dir, f'charon_{safe_tag}_{str(uuid.uuid4())[:8]}.png')
                temp_path_nuke = temp_path.replace('\\', '/')

                source_node = input_node
                shuffle_node = None
                crop_node = None
                try:
                    channels = source_node.channels()
                except Exception:
                    channels = []
                has_rgb = any(
                    ch.endswith(".red") or ch.endswith(".green") or ch.endswith(".blue")
                    for ch in channels or []
                )
                has_alpha = any(ch.endswith(".alpha") for ch in channels or [])
                if not has_rgb and has_alpha:
                    try:
                        shuffle_node = nuke.createNode('Shuffle', inpanel=False)
                        shuffle_node.setInput(0, source_node)
                        for channel in ("red", "green", "blue", "alpha"):
                            try:
                                shuffle_node[channel].setValue("alpha")
                            except Exception:
                                pass
                        source_node = shuffle_node
                        log_debug(f"Inserted Shuffle to promote alpha for '{friendly_name}'")
                    except Exception as shuffle_error:
                        log_debug(f"Failed to insert Shuffle for '{friendly_name}': {shuffle_error}", 'WARNING')
                        if shuffle_node:
                            try:
                                nuke.delete(shuffle_node)
                            except Exception:
                                pass
                        shuffle_node = None

                if crop_box:
                    try:
                        crop_node = nuke.createNode('Crop', inpanel=False)
                        crop_node.setInput(0, source_node)
                        try:
                            crop_node['box'].setValue(crop_box)
                        except Exception:
                            for index, coord in enumerate(crop_box):
                                try:
                                    crop_node['box'].setValue(coord, index)
                                except Exception:
                                    pass
                        try:
                            crop_node['reformat'].setValue(True)
                        except Exception:
                            pass
                        try:
                            crop_node['label'].setValue("CharonOp Crop")
                        except Exception:
                            pass
                        source_node = crop_node
                    except Exception as crop_error:
                        log_debug(f"Failed to apply crop for '{friendly_name}': {crop_error}", 'WARNING')
                        if crop_node:
                            try:
                                nuke.delete(crop_node)
                            except Exception:
                                pass
                        crop_node = None

                write_node = nuke.createNode('Write', inpanel=False)
                from . import preferences
                aces_enabled = preferences.get_preference("aces_mode_enabled", False)
                
                transformed_source_node = _apply_aces_pre_write_transform(source_node, aces_enabled)
                write_node.setInput(0, transformed_source_node)
                if aces_enabled:
                    write_node['raw'].setValue(True)
                write_node['file'].setValue(temp_path_nuke)
                write_node['file_type'].setValue('png')
                try:
                    nuke.execute(write_node, current_frame, current_frame)
                finally:
                    try:
                        nuke.delete(write_node)
                    except Exception:
                        pass
                    if transformed_source_node != source_node:
                        try:
                            nuke.delete(transformed_source_node)
                        except Exception:
                            pass
                    if shuffle_node:
                        try:
                            nuke.delete(shuffle_node)
                        except Exception:
                            pass
                    if crop_node:
                        try:
                            nuke.delete(crop_node)
                        except Exception:
                            pass

                rendered_files[idx] = temp_path
                log_debug(f"Rendered '{friendly_name}' to {temp_path_nuke}")

        _charon_window, comfy_client, comfy_path = _resolve_comfy_environment()
        if not comfy_client:
            log_debug('ComfyUI client not available', 'ERROR')
            try:
                import nuke  # type: ignore
                nuke.message("ComfyUI is not running or unreachable. Launch ComfyUI from the Charon panel and try again.")
            except Exception:
                pass
            raise RuntimeError('ComfyUI client is not available')

        results_dir = os.path.join(temp_root, 'results')
        os.makedirs(results_dir, exist_ok=True)
        result_file = os.path.join(results_dir, f"charon_result_{int(time.time())}.json")

        def update_progress(progress, status='Processing', error=None, extra=None):
            nonlocal current_node_state
            try:
                numeric_progress = float(progress)
            except Exception:
                numeric_progress = 0.0
            clamped_progress = max(-1.0, min(numeric_progress, 1.0))
            if clamped_progress >= 0.999:
                clamped_progress = 1.0

            try:
                node.knob('charon_progress').setValue(clamped_progress)
                node.knob('charon_status').setValue(status)
            except Exception:
                pass

            lifecycle = 'Processing'
            normalized = (status or '').lower()
            if clamped_progress < 0 or normalized.startswith('error'):
                lifecycle = 'Error'
            elif clamped_progress >= 0.999:
                lifecycle = 'Completed'

            current_node_state = lifecycle
            apply_status_color(current_node_state)
            for candidate in _collect_target_reads():
                apply_status_color(current_node_state, candidate)

            payload = load_status_payload()
            runs = ensure_history(payload)
            current_run = payload.get('current_run')
            if not isinstance(current_run, dict) or current_run.get('id') != current_run_id:
                current_run = {
                    'id': current_run_id,
                    'started_at': run_started_at,
                }
            now = time.time()
            auto_import_flag = resolve_auto_import()
            current_run.update({
                'status': lifecycle,
                'message': status,
                'progress': clamped_progress,
                'updated_at': now,
                'auto_import': auto_import_flag,
            })
            if extra and isinstance(extra, dict):
                current_run.update(extra)
                if 'output_path' in extra:
                    update_last_output(extra.get('output_path'))
            if lifecycle == 'Completed':
                current_run['completed_at'] = now
            if error:
                current_run['error'] = error

            payload.update({
                'status': status,
                'state': lifecycle,
                'message': status,
                'progress': clamped_progress,
                'run_id': current_run_id,
                'updated_at': now,
                'current_run': current_run,
                'auto_import': auto_import_flag,
            })
            if extra and isinstance(extra, dict):
                payload.update(extra)
            if error:
                payload['last_error'] = error

            if lifecycle in ('Completed', 'Error'):
                if lifecycle == 'Error':
                    update_last_output(None)
                summary = {
                    'id': current_run_id,
                    'status': lifecycle,
                    'message': status,
                    'progress': clamped_progress,
                    'started_at': current_run.get('started_at', run_started_at),
                    'completed_at': current_run.get('completed_at', now),
                    'error': current_run.get('error'),
                    'auto_import': auto_import_flag,
                }
                for key in ('output_path', 'elapsed_time', 'prompt_id'):
                    if key in current_run:
                        summary[key] = current_run[key]
                runs.append(summary)
                payload['runs'] = runs[-10:]
                payload.pop('current_run', None)
            else:
                payload['runs'] = runs
                payload['current_run'] = current_run

            save_status_payload(payload)

            log_debug(f'Updated progress: {clamped_progress:.1%} - {status}')

        def _safe_node_coords():
            """Return node x/y positions without raising if the node was deleted."""
            try:
                return node.xpos(), node.ypos()
            except Exception as exc:
                log_debug(f"Node position unavailable: {exc}", "WARNING")
                return 0, 0

        def background_process():
            nonlocal batch_count
            try:
                update_progress(0.05, 'Starting processing')
                conversion_extra = {}
                cache_hit = None
                parameter_specs_local = parameter_specs
                prompt_data = initial_prompt_data if initial_prompt_data is not None else workflow_data
                converted_prompt_path = initial_prompt_path or None
                needs_conversion_local = needs_conversion

                if initial_prompt_data is not None:
                    if converted_prompt_path:
                        conversion_extra.update({
                            'converted_prompt_path': converted_prompt_path,
                            'conversion_cached': True,
                        })
                        update_progress(0.1, 'Using cached prompt', extra=conversion_extra)
                        if workflow_hash:
                            store_cached_prompt(converted_prompt_path, workflow_hash)
                    needs_conversion_local = False

                if needs_conversion_local and workflow_hash and workflow_folder:
                    try:
                        cache_hit = load_cached_conversion(workflow_folder, workflow_hash)
                    except Exception as exc:
                        log_debug(f'Conversion cache read failed: {exc}', 'WARNING')
                        cache_hit = None

                if needs_conversion_local:
                    if cache_hit:
                        try:
                            with open(cache_hit['prompt_path'], 'r', encoding='utf-8') as handle:
                                prompt_data = json.load(handle)
                            converted_prompt_path = cache_hit['prompt_path'].replace('\\', '/')
                            conversion_extra.update({
                                'converted_prompt_path': converted_prompt_path,
                                'conversion_cached': True,
                            })
                            update_progress(0.1, 'Using cached conversion', extra=conversion_extra)
                            if workflow_hash:
                                store_cached_prompt(converted_prompt_path, workflow_hash)
                        except Exception as exc:
                            log_debug(f'Failed to read cached conversion: {exc}', 'WARNING')
                            cache_hit = None
                            converted_prompt_path = None

                    if not cache_hit:
                        update_progress(0.1, 'Converting workflow')
                        if not comfy_path:
                            raise RuntimeError(
                                'ComfyUI path is not configured. Open the Charon panel and set the launch path.'
                            )
                        try:
                            converted_prompt = runtime_convert_workflow(workflow_data, comfy_path)
                        except Exception as exc:
                            log_debug(f'Workflow conversion failed: {exc}', 'ERROR')
                            raise
                        if not is_api_prompt(converted_prompt):
                            raise Exception('Converted workflow is invalid')
                        prompt_data = converted_prompt

                        if workflow_hash and workflow_folder:
                            try:
                                target_path = desired_prompt_path(workflow_folder, workflow_path or '', workflow_hash)
                                target_path.parent.mkdir(parents=True, exist_ok=True)
                                with open(target_path, 'w', encoding='utf-8') as handle:
                                    json.dump(converted_prompt, handle, indent=2)
                                stored_path = write_conversion_cache(
                                    workflow_folder,
                                    workflow_path or '',
                                    workflow_hash,
                                    str(target_path),
                                )
                                converted_prompt_path = stored_path.replace('\\', '/')
                            except Exception as exc:
                                log_debug(f'Failed to cache converted workflow: {exc}', 'WARNING')
                                debug_dir = os.path.join(temp_root, 'debug')
                                os.makedirs(debug_dir, exist_ok=True)
                                fallback_path = os.path.join(
                                    debug_dir,
                                    f'converted_{current_run_id}.json',
                                )
                                with open(fallback_path, 'w', encoding='utf-8') as handle:
                                    json.dump(converted_prompt, handle, indent=2)
                                converted_prompt_path = fallback_path.replace('\\', '/')
                        else:
                            debug_dir = os.path.join(temp_root, 'debug')
                            os.makedirs(debug_dir, exist_ok=True)
                            fallback_path = os.path.join(
                                debug_dir,
                                f'converted_{current_run_id}.json',
                            )
                            with open(fallback_path, 'w', encoding='utf-8') as handle:
                                json.dump(converted_prompt, handle, indent=2)
                            converted_prompt_path = fallback_path.replace('\\', '/')

                        conversion_extra.update({
                            'converted_prompt_path': converted_prompt_path,
                            'conversion_cached': False,
                        })
                        if workflow_hash and converted_prompt_path:
                            store_cached_prompt(converted_prompt_path, workflow_hash)

                model_replacements: List[Tuple[str, str]] = []
                replacements_applied = False
                if workflow_folder and isinstance(prompt_data, dict):
                    try:
                        replacements_applied, model_replacements = apply_validation_model_overrides(
                            prompt_data, workflow_folder
                        )
                    except Exception as exc:
                        log_debug(f"Failed to apply cached model replacements: {exc}", "WARNING")
                    else:
                        if model_replacements:
                            verb = "Applied" if replacements_applied else "Loaded"
                            log_debug(
                                f"{verb} {len(model_replacements)} model path adjustment(s) from validation cache."
                            )
                        if replacements_applied and converted_prompt_path:
                            try:
                                with open(converted_prompt_path, 'w', encoding='utf-8') as handle:
                                    json.dump(prompt_data, handle, indent=2)
                            except Exception as exc:  # pragma: no cover - defensive
                                log_debug(
                                    f"Failed to refresh cached converted workflow after applying model replacements: {exc}",
                                    "WARNING",
                                )

                if (
                    isinstance(ui_workflow_source, dict)
                    and ui_workflow_source
                    and isinstance(prompt_data, dict)
                ):
                    parameter_specs_local = _ensure_parameter_bindings(
                        node,
                        parameter_specs,
                        ui_workflow_source,
                        prompt_data,
                        workflow_hash,
                    )
                else:
                    parameter_specs_local = parameter_specs

                # Apply client-side logic (e.g. seed randomization)
                # This returns explicit values to use, decoupling data from UI lag
                parameter_overrides = _resolve_client_side_logic(node, parameter_specs_local)

                if render_jobs:
                    update_progress(0.2, 'Uploading images', extra=conversion_extra or None)
                else:
                    update_progress(0.2, 'Preparing submission', extra=conversion_extra or None)

                workflow_copy = copy.deepcopy(prompt_data)
                applied_overrides = _apply_parameter_overrides(
                    node,
                    workflow_copy,
                    parameter_specs_local,
                    knob_values=parameter_overrides,
                )
                if applied_overrides:
                    log_debug(
                        f'Parameter overrides updated {len(applied_overrides)} inputs before submission.'
                    )

                uploaded_assets = {}
                for job in render_jobs:
                    idx = job['index']
                    temp_path = rendered_files.get(idx)
                    mapping = job.get('mapping', {})
                    friendly_name = mapping.get('name', f'Input {idx + 1}') if isinstance(mapping, dict) else f'Input {idx + 1}'
                    if not temp_path or not os.path.exists(temp_path):
                        raise Exception(f"Temp file missing for '{friendly_name}'")
                    uploaded_filename = comfy_client.upload_image(temp_path)
                    if not uploaded_filename:
                        raise Exception(f"Failed to upload '{friendly_name}' to ComfyUI")
                    uploaded_assets[idx] = uploaded_filename
                    log_debug(f"Uploaded '{friendly_name}' as {uploaded_filename}")
                    progress = 0.2 + (0.2 * (len(uploaded_assets) / len(render_jobs)))
                    update_progress(progress, f'Uploaded {len(uploaded_assets)}/{len(render_jobs)} images')

                def assign_to_node(target_node_id, filename, target_socket=None):
                    node_key = str(target_node_id)
                    node_entry = workflow_copy.get(node_key)
                    if not isinstance(node_entry, dict):
                        return
                    inputs_dict = node_entry.setdefault('inputs', {})
                    if not isinstance(inputs_dict, dict):
                        return
                    if target_socket and target_socket in inputs_dict:
                        inputs_dict[target_socket] = filename
                        return
                    if 'image' in inputs_dict and not isinstance(inputs_dict.get('image'), list):
                        inputs_dict['image'] = filename
                    elif 'input' in inputs_dict and not isinstance(inputs_dict.get('input'), list):
                        inputs_dict['input'] = filename
                    elif 'mask' in inputs_dict and not isinstance(inputs_dict.get('mask'), list):
                        inputs_dict['mask'] = filename
                    else:
                        inputs_dict['image'] = filename

                if isinstance(input_mapping, list):
                    for job in render_jobs:
                        mapping = job.get('mapping', {})
                        idx = job['index']
                        uploaded_filename = uploaded_assets.get(idx)
                        if not uploaded_filename:
                            continue
                        node_id = mapping.get('node_id')
                        source = mapping.get('source')
                        if source == 'set_node':
                            identifier = mapping.get('identifier')
                            normalized = normalize_identifier(identifier)
                            target = set_targets.get(normalized)
                            if target:
                                assign_to_node(target[0], uploaded_filename)
                                continue
                            if node_id is not None:
                                set_entry = workflow_copy.get(str(node_id))
                                if isinstance(set_entry, dict):
                                    for value in set_entry.get('inputs', {}).values():
                                        if isinstance(value, list) and len(value) >= 1:
                                            assign_to_node(value[0], uploaded_filename)
                        elif node_id is not None:
                            assign_to_node(node_id, uploaded_filename)
                        else:
                            for target_id, target_data in workflow_copy.items():
                                if isinstance(target_data, dict) and target_data.get('class_type') == 'LoadImage':
                                    assign_to_node(target_id, uploaded_filename)
                                    break
                elif render_jobs:
                    filename = uploaded_assets.get(primary_index)
                    if filename:
                        for target_id, target_data in workflow_copy.items():
                            if isinstance(target_data, dict) and target_data.get('class_type') == 'LoadImage':
                                assign_to_node(target_id, filename)
                                break

                step2_views = []
                target_coverage_node_id = None
                
                if is_step2:
                    setup_result = {}
                    import threading
                    setup_event = threading.Event()

                    def _step2_setup_task():
                        try:
                            import nuke
                            rig = nuke.toNode("Charon_Coverage_Rig")
                            if not rig:
                                log_debug("Step 2: Charon_Coverage_Rig node not found.", "WARNING")
                                return
                            sheet = None
                            with rig:
                                sheet = nuke.toNode("ContactSheet1")
                                if not sheet:
                                    for n in nuke.allNodes("ContactSheet"):
                                        sheet = n
                                        break
                            if not sheet:
                                log_debug("Step 2: ContactSheet node not found inside rig.", "WARNING")
                                return
                                
                            views = []
                            log_debug(f"Step 2: ContactSheet inputs count: {sheet.inputs()}")
                            for i in range(sheet.inputs()):
                                inp = sheet.input(i)
                                if inp:
                                    views.append({'index': i, 'node': inp, 'group': rig})
                                else:
                                    log_debug(f"Step 2: ContactSheet input {i} is None.", "WARNING")
                            setup_result['views'] = views
                        except Exception as e:
                            log_debug(f"Step 2 setup task error: {e}", "WARNING")
                        finally:
                            setup_event.set()

                    try:
                        import nuke
                        nuke.executeInMainThread(_step2_setup_task)
                        setup_event.wait()
                        step2_views = setup_result.get('views', [])
                        
                        if step2_views:
                            batch_count = len(step2_views)
                            log_debug(f"Step 2: Found {batch_count} camera views. Overriding batch count.")
                            
                            set_targets_local = build_set_targets(workflow_copy)
                            target_info = set_targets_local.get('charoninput_coverage_rig')
                            
                            if not target_info:
                                load_images = []
                                for nid, ndata in workflow_copy.items():
                                    if ndata.get('class_type') == 'LoadImage':
                                        load_images.append(nid)
                                if len(load_images) >= 2:
                                    target_coverage_node_id = load_images[1]
                            else:
                                target_coverage_node_id = target_info[0]
                                
                            if not target_coverage_node_id:
                                log_debug("Step 2: Could not identify Coverage Rig input node.", "WARNING")
                    except Exception as exc:
                        log_debug(f"Step 2 setup failed: {exc}", "WARNING")

                base_prompt = copy.deepcopy(workflow_copy)
                seed_records = _capture_seed_inputs(base_prompt)
                batch_outputs: List[Dict[str, Any]] = []
                timeout = 300
                per_batch_progress = 0.5 / max(1, batch_count)

                def _progress_for(batch_index: int, local: float) -> float:
                    local_clamped = max(0.0, min(1.0, local))
                    base_value = 0.5 + per_batch_progress * batch_index
                    return min(base_value + per_batch_progress * local_clamped, 1.0)

                def _collect_output_artifacts(outputs_map, prompt_lookup):
                    """
                    Extract all available output artifacts (images/files/meshes).
                    Returns list of dicts with filename, subfolder, type, extension, node_id, class_type, kind.
                    """
                    artifacts = []
                    if not isinstance(outputs_map, dict):
                        return artifacts
                    for node_id, output_data in outputs_map.items():
                        if not isinstance(output_data, dict):
                            continue
                        class_type = (prompt_lookup.get(node_id) or {}).get("class_type") or ""

                        def _append_artifact(path: str, kind: str = "output"):
                            if not path:
                                return
                            ext_local = (os.path.splitext(path)[1] or "").lower()
                            artifacts.append(
                                {
                                    "filename": path,
                                    "subfolder": output_data.get("subfolder") or "",
                                    "type": output_data.get("type") or "output",
                                    "extension": ext_local,
                                    "node_id": node_id,
                                    "class_type": class_type,
                                    "kind": kind,
                                }
                            )

                        for key in ("images", "files", "meshes"):
                            entries = output_data.get(key)
                            if not isinstance(entries, list) or not entries:
                                continue
                            for entry in entries:
                                filename = entry.get("filename")
                                if not filename:
                                    continue
                                if _is_ignored_output(filename):
                                    continue
                                ext = (entry.get("extension") or os.path.splitext(filename)[1] or "").lower()
                                artifacts.append(
                                    {
                                        "filename": filename,
                                        "subfolder": entry.get("subfolder") or "",
                                        "type": entry.get("type") or "output",
                                        "extension": ext,
                                        "node_id": node_id,
                                        "class_type": class_type,
                                        "kind": key,
                                    }
                                )
                        for value in output_data.values():
                            if isinstance(value, str):
                                candidate = value.strip()
                                if _is_ignored_output(candidate):
                                    continue
                                ext_local = os.path.splitext(candidate)[1].lower()
                                if ext_local in CAMERA_OUTPUT_EXTENSIONS:
                                    _append_artifact(candidate, "camera")
                                elif ext_local in MODEL_OUTPUT_EXTENSIONS:
                                    _append_artifact(candidate, "meshes")
                            elif isinstance(value, list):
                                for item in value:
                                    if isinstance(item, str):
                                        candidate = item.strip()
                                        if _is_ignored_output(candidate):
                                            continue
                                        ext_local = os.path.splitext(candidate)[1].lower()
                                        if ext_local in CAMERA_OUTPUT_EXTENSIONS:
                                            _append_artifact(candidate, "camera")
                                        elif ext_local in MODEL_OUTPUT_EXTENSIONS:
                                            _append_artifact(candidate, "meshes")
                    return artifacts

                def _recover_cached_artifacts(prompt_payload: Dict[str, Any], current_prompt_id: Optional[str]) -> List[Dict[str, Any]]:
                    """
                    When ComfyUI serves a fully cached execution without outputs, try to reuse
                    outputs from the most recent matching prompt in history.
                    """
                    try:
                        prompt_hash = compute_workflow_hash(prompt_payload)
                    except Exception as exc:
                        log_debug(f"Could not hash prompt for cache lookup: {exc}", "WARNING")
                        return []

                    try:
                        history_map = comfy_client.get_full_history()
                    except Exception as exc:
                        log_debug(f"Failed to read ComfyUI history for cache reuse: {exc}", "WARNING")
                        return []

                    if not isinstance(history_map, dict):
                        return []

                    def _completion_timestamp(entry: Dict[str, Any]) -> int:
                        messages = entry.get("status", {}).get("messages") or []
                        for name, payload in reversed(messages):
                            if isinstance(payload, dict) and "timestamp" in payload:
                                try:
                                    return int(payload["timestamp"])
                                except Exception:
                                    continue
                        return 0

                    sorted_history = sorted(
                        history_map.items(),
                        key=lambda item: _completion_timestamp(item[1]) if isinstance(item[1], dict) else 0,
                        reverse=True,
                    )

                    for candidate_id, entry in sorted_history:
                        if candidate_id == current_prompt_id or not isinstance(entry, dict):
                            continue

                        prompt_field = entry.get("prompt")
                        candidate_prompt = None
                        if isinstance(prompt_field, list) and len(prompt_field) >= 3:
                            candidate_prompt = prompt_field[2]
                        elif isinstance(prompt_field, dict):
                            candidate_prompt = prompt_field

                        if not isinstance(candidate_prompt, dict):
                            continue

                        try:
                            candidate_hash = compute_workflow_hash(candidate_prompt)
                        except Exception:
                            continue

                        if candidate_hash != prompt_hash:
                            continue

                        candidate_outputs = entry.get("outputs") or {}
                        recovered = _collect_output_artifacts(candidate_outputs, candidate_prompt)
                        if recovered:
                            log_debug(f"Reused cached ComfyUI outputs from prompt {candidate_id}")
                            return recovered

                    return []

                def _recover_artifacts_by_prefix(expected_prefixes: List[str]) -> List[Dict[str, Any]]:
                    """
                    Secondary recovery path: reuse any recent outputs whose filenames match
                    the expected SaveImage filename prefixes.
                    """
                    if not expected_prefixes:
                        return []
                    try:
                        history_map = comfy_client.get_full_history()
                    except Exception as exc:
                        log_debug(f"Failed to read ComfyUI history for prefix-based reuse: {exc}", "WARNING")
                        return []
                    if not isinstance(history_map, dict):
                        return []

                    def _completion_timestamp(entry: Dict[str, Any]) -> int:
                        messages = entry.get("status", {}).get("messages") or []
                        for name, payload in reversed(messages):
                            if isinstance(payload, dict) and "timestamp" in payload:
                                try:
                                    return int(payload["timestamp"])
                                except Exception:
                                    continue
                        return 0

                    sorted_history = sorted(
                        history_map.items(),
                        key=lambda item: _completion_timestamp(item[1]) if isinstance(item[1], dict) else 0,
                        reverse=True,
                    )
                    lowered_prefixes = [p.lower() for p in expected_prefixes if p]

                    for candidate_id, entry in sorted_history:
                        if not isinstance(entry, dict):
                            continue
                        prompt_field = entry.get("prompt")
                        if isinstance(prompt_field, list) and len(prompt_field) >= 3:
                            candidate_prompt = prompt_field[2]
                        elif isinstance(prompt_field, dict):
                            candidate_prompt = prompt_field
                        else:
                            candidate_prompt = {}

                        candidate_outputs = entry.get("outputs") or {}
                        recovered = _collect_output_artifacts(candidate_outputs, candidate_prompt)
                        if not recovered:
                            continue

                        for artifact in recovered:
                            filename = str(artifact.get("filename") or "").lower()
                            for prefix in lowered_prefixes:
                                if prefix and filename.startswith(prefix):
                                    log_debug(
                                        f"Reused cached ComfyUI outputs with prefix match from prompt {candidate_id}"
                                    )
                                    return recovered

                    return []


                for batch_index in range(batch_count):
                    seed_offset = batch_index * 9973
                    prompt_payload = copy.deepcopy(base_prompt)
                    
                    if is_step2 and target_coverage_node_id:
                        if batch_index >= len(step2_views):
                            log_debug(f"Step 2: batch_index {batch_index} out of range ({len(step2_views)}). Stopping.", "ERROR")
                            break

                        view_info = step2_views[batch_index]
                        view_node = view_info['node']
                        rig_group_ref = view_info['group']
                        
                        view_filename = f'step2_view_{batch_index}_{str(uuid.uuid4())[:8]}.png'
                        view_path = os.path.join(temp_root, view_filename).replace('\\', '/')
                        
                        try:
                            render_event = threading.Event()
                            def _step2_render_task():
                                try:
                                    with rig_group_ref:
                                        _render_nuke_node(view_node, view_path)
                                finally:
                                    render_event.set()
                            
                            import nuke
                            nuke.executeInMainThread(_step2_render_task)
                            render_event.wait()
                            
                            view_upload = comfy_client.upload_image(view_path)
                            if view_upload:
                                t_node = prompt_payload.get(str(target_coverage_node_id))
                                if t_node:
                                    t_inputs = t_node.setdefault('inputs', {})
                                    t_inputs['image'] = view_upload
                                    log_debug(f"Step 2: Injected view {batch_index} into node {target_coverage_node_id}")
                                    
                                angle_desc = ""
                                override_prompt = ""
                                if batch_index == 0: 
                                    angle_desc = "0 degrees"
                                    override_prompt = "Align features. Keep everything else the same"
                                elif batch_index == 1: angle_desc = "90 degrees to the right"
                                elif batch_index == 2: angle_desc = "180 degrees"
                                elif batch_index == 3: angle_desc = "90 degrees to the left"
                                elif batch_index == 4: angle_desc = "to view from top"
                                elif batch_index == 5: angle_desc = "to view from bottom"
                                
                                if angle_desc or override_prompt:
                                    # Try to get template from knob
                                    prompt_template = ""
                                    target_spec = None
                                    for spec in parameter_specs_local:
                                        if spec.get('attribute') == 'prompt':
                                            target_spec = spec
                                            knob_name = spec.get('knob')
                                            if knob_name:
                                                try:
                                                    prompt_template = node.knob(knob_name).value()
                                                except: pass
                                            break
                                    
                                    injected_via_template = False
                                    if prompt_template and "*charon_angle*" in prompt_template:
                                        if override_prompt:
                                            final_prompt = override_prompt
                                        else:
                                            final_prompt = prompt_template.replace("*charon_angle*", angle_desc)
                                        log_debug(f"Step 2: Using prompt template: {final_prompt}")
                                        
                                        if target_spec:
                                            binding = target_spec.get('binding')
                                            if binding and binding.get('api_node') and binding.get('api_input'):
                                                api_node_id = str(binding['api_node'])
                                                api_input = binding['api_input']
                                                target_node = prompt_payload.get(api_node_id)
                                                if target_node:
                                                    inputs = target_node.setdefault('inputs', {})
                                                    inputs[api_input] = final_prompt
                                                    injected_via_template = True
                                                    log_debug(f"Step 2: Injected prompt into node {api_node_id} input '{api_input}'")
                                    
                                    if not injected_via_template:
                                        log_debug(f"Step 2: Attempting to inject angle '{angle_desc}' via token replacement (fallback)...")
                                        for nid, ndata in prompt_payload.items():
                                            inputs = ndata.get('inputs', {})
                                            if isinstance(inputs, dict):
                                                keys = list(inputs.keys())
                                                
                                                for key in keys:
                                                    val = inputs[key]
                                                    if isinstance(val, str) and "*charon_angle*" in val:
                                                        if override_prompt:
                                                            inputs[key] = override_prompt
                                                        else:
                                                            inputs[key] = val.replace("*charon_angle*", angle_desc)
                                                        log_debug(f"Step 2: Injected prompt into node {nid} input {key} (fallback)")

                        except Exception as render_err:
                            log_debug(f"Step 2 Render failed for view {batch_index}: {render_err}", "ERROR")

                    if seed_records:
                        _apply_seed_offset(prompt_payload, seed_records, seed_offset)

                    batch_label = f'Batch {batch_index + 1}/{batch_count}' if batch_count > 1 else 'Run'
                    
                    debug_file = os.path.join(temp_root, 'debug', f'prompt_step2_batch_{batch_index}.json').replace('\\', '/')
                    try:
                        os.makedirs(os.path.dirname(debug_file), exist_ok=True)
                        with open(debug_file, 'w', encoding='utf-8') as df:
                            json.dump(prompt_payload, df, indent=2)
                        log_debug(f"Debug: Wrote prompt payload to {debug_file}")
                    except Exception as de:
                        log_debug(f"Debug: Failed to write payload file: {de}", "WARNING")
                    
                    update_progress(
                        _progress_for(batch_index, 0.0),
                        f'Submitting {batch_label.lower()}',
                    )
                    prompt_id = comfy_client.submit_workflow(prompt_payload)
                    if not prompt_id:
                        save_hint = ''
                        if converted_prompt_path:
                            save_hint = f' (converted prompt saved to {converted_prompt_path})'
                        log_debug(f'ComfyUI did not return a prompt id{save_hint}', 'ERROR')
                        raise Exception(f'Failed to submit workflow{save_hint}')

                    try:
                        node.knob('charon_prompt_id').setValue(prompt_id)
                    except Exception:
                        pass

                    start_time = time.time()
                    update_progress(
                        _progress_for(batch_index, 0.1),
                        f'{batch_label}: queued on ComfyUI',
                        extra={
                            'prompt_id': prompt_id,
                            'prompt_submitted_at': start_time,
                            'batch_index': batch_index + 1,
                            'batch_total': batch_count,
                        },
                    )

                    while time.time() - start_time < timeout:
                        status_str = None
                        if hasattr(comfy_client, 'get_progress_for_prompt'):
                            progress_val = comfy_client.get_progress_for_prompt(prompt_id)
                            if progress_val > 0:
                                mapped_progress = _progress_for(batch_index, 0.2 + (progress_val * 0.6))
                                update_progress(
                                    mapped_progress,
                                    f'{batch_label}: processing',
                                    extra={
                                        'prompt_id': prompt_id,
                                        'batch_index': batch_index + 1,
                                        'batch_total': batch_count,
                                        'comfy_progress': float(progress_val),
                                    },
                                )

                            history = comfy_client.get_history(prompt_id)
                            if history and prompt_id in history:
                                history_data = history[prompt_id]
                                status_str = history_data.get('status', {}).get('status_str')
                                if status_str == 'success':
                                    outputs = history_data.get('outputs', {})
                                    artifacts = _collect_output_artifacts(outputs, base_prompt) if outputs else []
                                    if not artifacts:
                                        artifacts = _recover_cached_artifacts(prompt_payload, prompt_id)
                                    if not artifacts:
                                        # Attempt prefix-based recovery using any SaveImage filename prefixes
                                        prefixes = []
                                        for node_entry in prompt_payload.values():
                                            if not isinstance(node_entry, dict):
                                                continue
                                            if (node_entry.get("class_type") or "").lower() == "saveimage":
                                                prefix_val = node_entry.get("inputs", {}).get("filename_prefix")
                                                if isinstance(prefix_val, str):
                                                    prefixes.append(prefix_val)
                                        if prefixes:
                                            artifacts = _recover_artifacts_by_prefix(prefixes)
                                    if not artifacts:
                                        raise Exception('ComfyUI did not return an output file')

                                    for artifact_index, artifact in enumerate(artifacts):
                                        artifact_progress = 0.8 + (0.2 * ((artifact_index + 1) / len(artifacts)))
                                        update_progress(
                                            _progress_for(batch_index, artifact_progress),
                                            f'{batch_label}: downloading result ({artifact_index + 1}/{len(artifacts)})',
                                            extra={
                                                'prompt_id': prompt_id,
                                                'batch_index': batch_index + 1,
                                                'batch_total': batch_count,
                                            },
                                        )
                                        raw_extension = artifact.get("extension") or ""
                                        if not raw_extension:
                                            raw_extension = os.path.splitext(artifact.get("filename") or "")[1] or ".png"
                                        raw_extension_lower = raw_extension.lower()
                                        category = (
                                            "3D" if raw_extension_lower in THREE_D_OUTPUT_EXTENSIONS else "2D"
                                        )
                                        output_label = (
                                            artifact.get("comfy_node_class")
                                            or artifact.get("class_type")
                                            or "Output"
                                        )
                                        if (raw_extension_lower in CAMERA_OUTPUT_EXTENSIONS) or (
                                            artifact.get("kind") == "camera"
                                        ):
                                            output_label = CAMERA_OUTPUT_LABEL
                                        output_node_name = output_label
                                        if artifact.get("node_id"):
                                            output_node_name = f"{output_label}_{artifact.get('node_id')}"
                                        allocated_output_path = _allocate_output_path(
                                            charon_node_id,
                                            _resolve_nuke_script_name(),
                                            raw_extension_lower,
                                            user_slug,
                                            workflow_display_name,
                                            category,
                                            output_node_name,
                                        )
                                        log_debug(f'Resolved output path: {allocated_output_path}')
                                        source_filename = artifact.get("filename")
                                        source_is_abs = isinstance(source_filename, str) and os.path.isabs(source_filename)
                                        source_exists = source_is_abs and os.path.exists(source_filename)
                                        if source_exists:
                                            try:
                                                os.makedirs(os.path.dirname(allocated_output_path), exist_ok=True)
                                                shutil.copyfile(source_filename, allocated_output_path)
                                                success = True
                                                log_debug(f'Copied absolute output {source_filename} -> {allocated_output_path}')
                                            except Exception as copy_error:
                                                log_debug(f'Failed to copy absolute output {source_filename}: {copy_error}', 'WARNING')
                                                success = False
                                        else:
                                            success = comfy_client.download_file(
                                                source_filename,
                                                allocated_output_path,
                                                subfolder=artifact.get("subfolder", ""),
                                                file_type=artifact.get("type", "output"),
                                            )
                                        if not success:
                                            raise Exception('Failed to download result file from ComfyUI')

                                        final_output_path = allocated_output_path
                                        converted_from = None
                                        if raw_extension_lower == ".glb":
                                            obj_target = os.path.splitext(allocated_output_path)[0] + ".obj"
                                            log_debug(f'Converting GLB to OBJ: {allocated_output_path} -> {obj_target}')
                                            final_output_path = _convert_glb_to_obj(allocated_output_path, obj_target)
                                            converted_from = allocated_output_path

                                        elapsed = time.time() - start_time
                                        normalized_output_path = final_output_path.replace('\\', '/')
                                        if _is_ignored_output(final_output_path):
                                            log_debug(f'Skipping ignored output: {final_output_path}')
                                            continue
                                        if category == "2D":
                                            metadata_payload = {
                                                'charon_node_id': charon_node_id,
                                                'prompt_id': prompt_id,
                                                'run_id': current_run_id,
                                                'script_name': _resolve_nuke_script_name(),
                                                'user': user_slug,
                                                'workflow_path': workflow_path or '',
                                                'timestamp': time.time(),
                                                'batch_index': batch_index + 1,
                                                'batch_total': batch_count,
                                                'seed_offset': seed_offset,
                                            }
                                            embed_png_metadata(normalized_output_path, metadata_payload)
                                            if workflow_data_str:
                                                embed_png_workflow(normalized_output_path, workflow_data_str)
                                        batch_entry = {
                                            'batch_index': batch_index + 1,
                                            'batch_total': batch_count,
                                            'prompt_id': prompt_id,
                                            'output_path': normalized_output_path,
                                            'elapsed_time': elapsed,
                                            'output_kind': category,
                                            'original_filename': artifact.get("filename"),
                                            'download_path': allocated_output_path.replace('\\', '/'),
                                            'comfy_node_id': artifact.get("node_id"),
                                            'comfy_node_class': artifact.get("class_type"),
                                            'comfy_output_kind': artifact.get("kind"),
                                        }
                                        if converted_from:
                                            batch_entry['converted_from'] = converted_from.replace('\\', '/')
                                        if _is_ignored_output(batch_entry.get('original_filename')):
                                            log_debug(f"Skipped recording ignored output: {batch_entry['original_filename']}")
                                            continue
                                        batch_outputs.append(batch_entry)

                                    if batch_outputs:
                                        last_entry = batch_outputs[-1]
                                        extra_payload = {
                                            'output_path': last_entry.get('output_path'),
                                            'elapsed_time': last_entry.get('elapsed_time'),
                                            'prompt_id': prompt_id,
                                            'batch_index': batch_index + 1,
                                            'batch_total': batch_count,
                                            'batch_outputs': batch_outputs.copy(),
                                            'output_kind': last_entry.get('output_kind'),
                                        }
                                        update_progress(
                                            _progress_for(batch_index, 1.0),
                                            f'{batch_label}: completed',
                                            extra=extra_payload,
                                        )
                                    break
                            elif status_str == 'error':
                                error_msg = history_data.get('status', {}).get('status_message', 'Unknown error')
                                raise Exception(f'ComfyUI failed: {error_msg}')
                            else:
                                status_str = None
                        time.sleep(1.0)
                    else:
                        raise Exception('Processing timed out')

                if not batch_outputs and not is_step2:
                    raise Exception('No outputs were generated by ComfyUI')

                if is_step2 and batch_outputs:
                    image_paths = [e.get('download_path') for e in batch_outputs if e.get('download_path')]
                    if image_paths:
                        try:
                            import nuke
                            nuke.executeInMainThread(lambda: _create_step2_result_group(node, image_paths))
                        except Exception as cs_err:
                            log_debug(f"Step 2 Result Group failed: {cs_err}", "WARNING")
                    batch_outputs = []

                node_x, node_y = _safe_node_coords()
                
                last_out = batch_outputs[-1]['output_path'] if batch_outputs else ""
                last_kind = batch_outputs[-1].get('output_kind') if batch_outputs else ""
                last_time = batch_outputs[-1].get('elapsed_time', 0) if batch_outputs else 0
                
                result_data = {
                    'success': True,
                    'outputs': batch_outputs,
                    'node_x': node_x,
                    'node_y': node_y,
                    'batch_total': batch_count,
                    'output_path': last_out,
                    'elapsed_time': last_time,
                    'output_kind': last_kind,
                }
                with open(result_file, 'w') as fp:
                    json.dump(result_data, fp)
                return

            except Exception as exc:
                message = f'Error: {exc}'
                update_progress(-1.0, message, error=str(exc))
                node_x, node_y = _safe_node_coords()
                result_data = {
                    'success': False,
                    'error': str(exc),
                    'node_x': node_x,
                    'node_y': node_y,
                }
                with open(result_file, 'w') as fp:
                    json.dump(result_data, fp)

        bg_thread = threading.Thread(target=background_process)
        bg_thread.daemon = True
        bg_thread.start()

        def result_watcher():
            for _ in range(300):
                if os.path.exists(result_file):
                    try:
                        with open(result_file, 'r') as fp:
                            result_data = json.load(fp)
                        if result_data.get('success'):
                            def cleanup_files():
                                try:
                                    if os.path.exists(result_file):
                                        os.remove(result_file)
                                except Exception as cleanup_error:
                                    log_debug(f'Could not remove result file: {cleanup_error}', 'WARNING')
                                try:
                                    for temp_path in list(rendered_files.values()):
                                        if os.path.exists(temp_path):
                                            os.remove(temp_path)
                                            log_debug(f'Cleaned up temp file: {temp_path}')
                                except Exception as cleanup_error:
                                    log_debug(f'Could not clean up files: {cleanup_error}', 'WARNING')

                            entries = result_data.get('outputs')
                            if not isinstance(entries, list) or not entries:
                                entries = [result_data]
                            total_batches = result_data.get('batch_total') or len(entries)
                            if 'node_x' in result_data and 'node_y' in result_data:
                                node_x = result_data.get('node_x')
                                node_y = result_data.get('node_y')
                            else:
                                node_x, node_y = _safe_node_coords()

                            if resolve_auto_import():
                                def update_or_create_read_nodes():
                                    reuse_existing = True
                                    try:
                                        reuse_knob = node.knob('charon_reuse_output')
                                        if reuse_knob is not None:
                                            reuse_existing = bool(int(reuse_knob.value()))
                                    except Exception:
                                        reuse_existing = False

                                    def _matches_parent(candidate):
                                        normalized_parent = (charon_node_id or "").strip().lower()
                                        if not normalized_parent:
                                            return False
                                        try:
                                            meta_parent = (candidate.metadata('charon/parent_id') or "").strip().lower()
                                        except Exception:
                                            meta_parent = ""
                                        if meta_parent == normalized_parent:
                                            return True
                                        try:
                                            knob_parent = (candidate.knob('charon_parent_id').value() or "").strip().lower()
                                        except Exception:
                                            knob_parent = ""
                                        if knob_parent == normalized_parent:
                                            return True
                                        try:
                                            meta_charon = (candidate.metadata('charon/node_id') or "").strip().lower()
                                        except Exception:
                                            meta_charon = ""
                                        return meta_charon == normalized_parent

                                    def _remove_mismatched_reads(required_class: str):
                                        try:
                                            candidates = list(nuke.allNodes("Read")) + list(nuke.allNodes("ReadGeo2"))
                                        except Exception:
                                            candidates = []
                                        for candidate in candidates:
                                            if not _matches_parent(candidate):
                                                continue
                                            try:
                                                current_class = getattr(candidate, "Class", lambda: "")()
                                            except Exception:
                                                current_class = ""
                                            if current_class and current_class != required_class:
                                                try:
                                                    nuke.delete(candidate)
                                                    log_debug(f'Removed outdated CharonRead node ({current_class}) for 3D output.')
                                                except Exception:
                                                    pass

                                    def _is_mesh_entry(entry: Dict[str, Any]) -> bool:
                                        output_kind = (entry.get('output_kind') or '').upper()
                                        kind = (entry.get('comfy_output_kind') or '').lower()
                                        path = entry.get('output_path') or ''
                                        ext = os.path.splitext(str(path))[1].lower()
                                        if ext in CAMERA_OUTPUT_EXTENSIONS:
                                            return False
                                        if output_kind == '3D':
                                            return True
                                        return kind == 'meshes' or ext in MODEL_OUTPUT_EXTENSIONS

                                    def _is_image_entry(entry: Dict[str, Any]) -> bool:
                                        if _is_mesh_entry(entry):
                                            return False
                                        output_kind = (entry.get('output_kind') or '').upper()
                                        if output_kind == '2D':
                                            return True
                                        kind = (entry.get('comfy_output_kind') or '').lower()
                                        if kind == 'images':
                                            return True
                                        path = entry.get('output_path') or ''
                                        ext = os.path.splitext(str(path))[1].lower()
                                        return ext in IMAGE_OUTPUT_EXTENSIONS

                                    def _is_camera_entry(entry: Dict[str, Any]) -> bool:
                                        path = (
                                            entry.get('output_path')
                                            or entry.get('download_path')
                                            or entry.get('original_filename')
                                            or entry.get('extension')
                                            or ''
                                        )
                                        ext = os.path.splitext(str(path))[1].lower()
                                        return ext in CAMERA_OUTPUT_EXTENSIONS

                                    def _output_label(entry: Dict[str, Any], default_prefix: str = "Output") -> str:
                                        ext_local = os.path.splitext(
                                            entry.get('output_path')
                                            or entry.get('download_path')
                                            or entry.get('original_filename')
                                            or ''
                                        )[1].lower()
                                        if ext_local in CAMERA_OUTPUT_EXTENSIONS:
                                            return CAMERA_OUTPUT_LABEL
                                        label = (
                                            entry.get('comfy_node_class')
                                            or entry.get('class_type')
                                            or entry.get('original_filename')
                                            or default_prefix
                                        )
                                        node_id_val = entry.get('comfy_node_id') or entry.get('node_id')
                                        base = _sanitize_name(str(label), default_prefix)
                                        if node_id_val:
                                            base = f"{base}_{_sanitize_name(str(node_id_val), '')}"
                                        return base

                                    def _find_grouped_read(required_class: str, parent_norm: str, group_label: str):
                                        try:
                                            candidates = list(nuke.allNodes(required_class))
                                        except Exception:
                                            candidates = []
                                        for candidate in candidates:
                                            if not _matches_parent(candidate):
                                                continue
                                            try:
                                                current_label = (candidate.metadata('charon/output_label') or "").strip().lower()
                                            except Exception:
                                                current_label = ""
                                            if not current_label:
                                                try:
                                                    knob_val = candidate.knob('charon_output_label')
                                                    if knob_val:
                                                        current_label = str(knob_val.value() or "").strip().lower()
                                                except Exception:
                                                    current_label = ""
                                            if current_label == group_label.lower():
                                                return candidate
                                        return None

                                    parent_norm = _normalize_node_id(charon_node_id)
                                    placeholder_norm = ""
                                    try:
                                        placeholder_norm = (get_placeholder_image_path() or "").replace("\\", "/").lower()
                                    except Exception:
                                        placeholder_norm = ""
                                    if placeholder_norm:
                                        try:
                                            candidates = list(iter_candidate_read_nodes())
                                        except Exception:
                                            candidates = []
                                        for candidate in candidates:
                                            if candidate is None:
                                                continue
                                            try:
                                                parent_val = _normalize_node_id(read_node_parent_id(candidate))
                                            except Exception:
                                                parent_val = ""
                                            if parent_val != parent_norm:
                                                continue
                                            try:
                                                file_val = (candidate["file"].value() or "").strip()
                                            except Exception:
                                                file_val = ""
                                            if file_val.replace("\\", "/").lower() == placeholder_norm:
                                                try:
                                                    unlink_read_node(candidate)
                                                except Exception:
                                                    pass
                                                try:
                                                    nuke.delete(candidate)
                                                    log_debug("Removed placeholder CharonRead node before importing outputs.")
                                                except Exception:
                                                    pass

                                    image_entries = [e for e in entries if _is_image_entry(e)]
                                    mesh_entries = [e for e in entries if _is_mesh_entry(e)]
                                    camera_entries = [e for e in entries if _is_camera_entry(e)]

                                    if not image_entries and not mesh_entries and not camera_entries:
                                        log_debug('No output paths available for Read update.', 'WARNING')
                                        cleanup_files()
                                        return
                                        
                                    if is_step2 and image_entries:
                                        image_paths = [e.get('output_path') for e in image_entries if e.get('output_path')]
                                        if image_paths:
                                            try:
                                                _create_step2_result_group(node, image_paths)
                                            except Exception as cs_err:
                                                log_debug(f"Step 2 Result Group creation failed: {cs_err}", "ERROR")
                                        cleanup_files()
                                        return

                                    if camera_entries:
                                        for camera_entry in camera_entries:
                                            camera_path = (
                                                camera_entry.get('output_path')
                                                or camera_entry.get('download_path')
                                                or camera_entry.get('original_filename')
                                            )
                                            if camera_path:
                                                log_debug(f'Camera output stored at: {camera_path}')

                                    def _ensure_output_label_metadata(read_node, label_text: str):
                                        try:
                                            read_node.setMetaData('charon/output_label', label_text or "")
                                        except Exception:
                                            pass
                                        try:
                                            label_knob = read_node.knob('charon_output_label')
                                        except Exception:
                                            label_knob = None
                                        if label_knob is None:
                                            try:
                                                label_knob = nuke.String_Knob('charon_output_label', 'Charon Output Label', '')
                                                label_knob.setFlag(nuke.NO_ANIMATION)
                                                label_knob.setFlag(nuke.INVISIBLE)
                                                read_node.addKnob(label_knob)
                                            except Exception:
                                                label_knob = None
                                        if label_knob is not None:
                                            try:
                                                label_knob.setValue(label_text or "")
                                            except Exception:
                                                pass

                                    grouped_images: Dict[str, List[Dict[str, Any]]] = {}
                                    for entry in image_entries:
                                        label = _output_label(entry, "Output2D")
                                        grouped_images.setdefault(label, []).append(entry)

                                    x_offset_step = 140
                                    layout_index = 0
                                    y_base = node_y + 60

                                    for group_index, (label, group_entries) in enumerate(grouped_images.items()):
                                        group_paths = [e.get('output_path') for e in group_entries if e.get('output_path')]
                                        if not group_paths:
                                            continue
                                        required_class = "Read"
                                        read_node = _find_grouped_read(required_class, parent_norm, label)
                                        if read_node is None:
                                            try:
                                                read_node = nuke.createNode(required_class)
                                                read_node.setXpos(node_x + (layout_index * x_offset_step))
                                                read_node.setYpos(y_base)
                                                try:
                                                    read_node.setInput(0, None)
                                                except Exception:
                                                    pass
                                                read_node.setSelected(True)
                                            except Exception as create_error:
                                                log_debug(f'Failed to create CharonRead2D node: {create_error}', 'ERROR')
                                                continue
                                            read_base = _sanitize_name(_resolve_workflow_display_name(), "Workflow")
                                            label_base = _sanitize_name(label, "Output2D")
                                            try:
                                                read_node.setName(f"CR2D_{read_base}_{label_base}")
                                            except Exception:
                                                try:
                                                    read_node.setName("CR2D")
                                                except Exception:
                                                    pass
                                            log_debug(f'Created CharonRead2D for output group: {label}')
                                        else:
                                            try:
                                                read_node.setSelected(True)
                                            except Exception:
                                                pass
                                            try:
                                                read_node.setXpos(node_x + (layout_index * x_offset_step))
                                                read_node.setYpos(y_base)
                                            except Exception:
                                                pass

                                        try:
                                            navigation_json = json.dumps(group_entries)
                                        except Exception as serialize_error:
                                            log_debug(f'Could not serialize 2D outputs for {label}: {serialize_error}', 'WARNING')
                                            navigation_json = json.dumps([{'output_path': path} for path in group_paths])
                                        try:
                                            all_outputs_json = json.dumps(entries)
                                        except Exception:
                                            all_outputs_json = navigation_json

                                        outputs_knob, index_knob, label_knob = ensure_batch_navigation_controls(read_node)
                                        default_index = len(group_paths) - 1
                                        if reuse_existing and index_knob is not None:
                                            try:
                                                existing_index = int(index_knob.value())
                                            except Exception:
                                                existing_index = default_index
                                            if 0 <= existing_index < len(group_paths):
                                                default_index = existing_index

                                        try:
                                            read_node['file'].setValue(group_paths[default_index])
                                        except Exception as assign_error:
                                            log_debug(f'Could not assign output path to CharonRead2D ({label}): {assign_error}', 'ERROR')
                                        if outputs_knob is not None:
                                            try:
                                                outputs_knob.setValue(navigation_json)
                                            except Exception:
                                                pass
                                        if index_knob is not None:
                                            try:
                                                index_knob.setValue(default_index)
                                            except Exception:
                                                pass
                                        try:
                                            read_node.setMetaData('charon/batch_outputs', all_outputs_json)
                                        except Exception:
                                            pass
                                        try:
                                            write_metadata('charon/batch_outputs', all_outputs_json)
                                        except Exception:
                                            pass

                                        _ensure_output_label_metadata(read_node, label)
                                        mark_read_node(read_node)
                                        try:
                                            apply_status_color(current_node_state, read_node)
                                        except Exception:
                                            pass
                                        layout_index += 1

                                        # --- NEW CODE START ---
                                        from . import preferences
                                        aces_enabled = preferences.get_preference("aces_mode_enabled", False)
                                        
                                        if aces_enabled:
                                            ivt_temp = os.path.join(temp_root, f"ivt_{str(uuid.uuid4())[:8]}.nk").replace("\\", "/")
                                            try:
                                                with open(ivt_temp, "w") as f:
                                                    f.write(INVERSE_VIEW_TRANSFORM_GROUP)
                                                
                                                ivt_node = None
                                                try:
                                                    for dep in read_node.dependent():
                                                        if "InverseViewTransform" in dep.name() and dep.knob("viewTransform"):
                                                            ivt_node = dep
                                                            break
                                                except: pass
                                                
                                                if not ivt_node:
                                                    nuke.nodePaste(ivt_temp)
                                                    ivt_node = nuke.selectedNode()
                                                
                                                if ivt_node:
                                                    ivt_node.setInput(0, read_node)
                                                    ivt_node.setXpos(read_node.xpos())
                                                    ivt_node.setYpos(read_node.ypos() + 200)
                                                    try:
                                                        ivt_node['tile_color'].setValue(0x0000FFFF)
                                                        ivt_node['gl_color'].setValue(0x0000FFFF)
                                                    except: pass
                                                    
                                            except Exception as paste_error:
                                                log_debug(f"Failed to paste InverseViewTransform: {paste_error}", "WARNING")
                                            finally:
                                                if os.path.exists(ivt_temp):
                                                    try:
                                                        os.remove(ivt_temp)
                                                    except: pass
                                        # --- NEW CODE END ---

                                    grouped_meshes: Dict[str, List[Dict[str, Any]]] = {}
                                    for entry in mesh_entries:
                                        label = _output_label(entry, "Output3D")
                                        grouped_meshes.setdefault(label, []).append(entry)

                                    # Align 3D and camera nodes horizontally with the same step
                                    mesh_x_offset_step = 140

                                    for group_index, (label, group_entries) in enumerate(grouped_meshes.items()):
                                        group_paths = [e.get('output_path') for e in group_entries if e.get('output_path')]
                                        if not group_paths:
                                            continue
                                        required_class = "ReadGeo2"
                                        read_node = _find_grouped_read(required_class, parent_norm, label)
                                        if read_node is None:
                                            try:
                                                read_node = nuke.createNode(required_class)
                                                read_node.setXpos(node_x + (layout_index * mesh_x_offset_step))
                                                read_node.setYpos(y_base)
                                                try:
                                                    read_node.setInput(0, None)
                                                except Exception:
                                                    pass
                                            except Exception as mesh_error:
                                                log_debug(f'Failed to create mesh Read node ({label}): {mesh_error}', 'ERROR')
                                                continue
                                        else:
                                            try:
                                                read_node.setXpos(node_x + (layout_index * mesh_x_offset_step))
                                                read_node.setYpos(y_base)
                                            except Exception:
                                                pass
                                        try:
                                            read_base = _sanitize_name(_resolve_workflow_display_name(), "Workflow")
                                            label_base = _sanitize_name(label, "Output3D")
                                            read_node.setName(f"CR3D_{read_base}_{label_base}")
                                        except Exception:
                                            try:
                                                read_node.setName("CR3D")
                                            except Exception:
                                                pass
                                        try:
                                            navigation_json = json.dumps(group_entries)
                                        except Exception as serialize_error:
                                            log_debug(f'Could not serialize 3D outputs for {label}: {serialize_error}', 'WARNING')
                                            navigation_json = json.dumps([{'output_path': path} for path in group_paths])

                                        parent_norm_local = _normalize_node_id(charon_node_id)
                                        try:
                                            read_node['file'].setValue(group_paths[-1])
                                        except Exception as assign_error:
                                            log_debug(f'Could not assign mesh output to ReadGeo2 ({label}): {assign_error}', 'ERROR')
                                        try:
                                            read_id_mesh = (read_node.metadata('charon/read_id') or "").strip()
                                        except Exception:
                                            read_id_mesh = ""
                                        try:
                                            read_node.setMetaData('charon/parent_id', parent_norm_local or "")
                                        except Exception:
                                            pass
                                        try:
                                            parent_knob = read_node.knob('charon_parent_id')
                                        except Exception:
                                            parent_knob = None
                                        if parent_knob is None:
                                            try:
                                                parent_knob = nuke.String_Knob('charon_parent_id', 'Charon Parent ID', '')
                                                parent_knob.setFlag(nuke.NO_ANIMATION)
                                                parent_knob.setFlag(nuke.INVISIBLE)
                                                read_node.addKnob(parent_knob)
                                            except Exception:
                                                parent_knob = None
                                        if parent_knob is not None:
                                            try:
                                                parent_knob.setValue(parent_norm_local or "")
                                            except Exception:
                                                pass
                                        try:
                                            existing_read_id_knob = read_node.knob('charon_read_id')
                                        except Exception:
                                            existing_read_id_knob = None
                                        if not read_id_mesh and existing_read_id_knob is not None:
                                            try:
                                                read_id_mesh = (existing_read_id_knob.value() or "").strip()
                                            except Exception:
                                                read_id_mesh = ""
                                        if not read_id_mesh:
                                            read_id_mesh = uuid.uuid4().hex[:12].lower()
                                        try:
                                            read_node.setMetaData('charon/read_id', read_id_mesh)
                                        except Exception:
                                            pass
                                        if existing_read_id_knob is None:
                                            try:
                                                existing_read_id_knob = nuke.String_Knob('charon_read_id', 'Charon Read ID', '')
                                                existing_read_id_knob.setFlag(nuke.NO_ANIMATION)
                                                existing_read_id_knob.setFlag(nuke.INVISIBLE)
                                                read_node.addKnob(existing_read_id_knob)
                                            except Exception:
                                                existing_read_id_knob = None
                                        if existing_read_id_knob is not None:
                                            try:
                                                existing_read_id_knob.setValue(read_id_mesh)
                                            except Exception:
                                                pass

                                        try:
                                            outputs_knob_mesh, index_knob_mesh, label_knob_mesh = ensure_batch_navigation_controls(read_node)
                                            if outputs_knob_mesh is not None:
                                                outputs_knob_mesh.setValue(navigation_json)
                                            if index_knob_mesh is not None:
                                                index_knob_mesh.setValue(len(group_paths) - 1)
                                            if label_knob_mesh is not None:
                                                label_knob_mesh.setValue(f'Mesh {len(group_paths)}/{len(group_paths)}')
                                        except Exception:
                                            pass
                                        try:
                                            assign_read_label(read_node)
                                        except Exception:
                                            pass
                                        try:
                                            ensure_read_node_info(read_node, read_id_mesh, current_node_state)
                                        except Exception:
                                            pass

                                        try:
                                            read_base = _sanitize_name(_resolve_workflow_display_name(), "Workflow")
                                            label_base = _sanitize_name(label, "Output3D")
                                            read_node.setName(f"CR3D_{read_base}_{label_base}")
                                        except Exception:
                                            try:
                                                read_node.setName("CR3D")
                                            except Exception:
                                                pass

                                        try:
                                            color_value = status_to_tile_color(current_node_state)
                                            read_node['tile_color'].setValue(color_value)
                                        except Exception:
                                            pass
                                        mesh_gl_color = status_to_gl_color(current_node_state)
                                        if mesh_gl_color is not None:
                                            try:
                                                read_node['gl_color'].setValue(mesh_gl_color)
                                            except Exception:
                                                try:
                                                    read_node['gl_color'].setValue(list(mesh_gl_color))
                                                except Exception:
                                                    pass
                                        try:
                                            apply_status_color(current_node_state, read_node)
                                        except Exception:
                                            pass
                                        layout_index += 1
                                        _ensure_output_label_metadata(read_node, label)
                                        try:
                                            read_node.setMetaData('charon/batch_outputs', navigation_json)
                                        except Exception:
                                            pass
                                        try:
                                            write_metadata('charon/batch_outputs', navigation_json)
                                        except Exception:
                                            pass
                                        try:
                                            mark_read_node(read_node)
                                        except Exception:
                                            pass

                                    if camera_entries:
                                        parent_norm_local = _normalize_node_id(charon_node_id)
                                        for camera_entry in camera_entries:
                                            camera_path = (
                                                camera_entry.get('output_path')
                                                or camera_entry.get('download_path')
                                                or camera_entry.get('original_filename')
                                                or ''
                                            )
                                            camera_path_norm = os.path.normpath(camera_path)
                                            if not camera_path or not os.path.exists(camera_path_norm):
                                                log_debug(f'Skipping camera import; file missing: {camera_path}', 'WARNING')
                                                continue

                                            def _already_imported(target: str) -> bool:
                                                try:
                                                    nodes = list(nuke.allNodes())
                                                except Exception:
                                                    nodes = []
                                                for candidate in nodes:
                                                    try:
                                                        meta_path = (candidate.metadata('charon/camera_path') or '').strip()
                                                    except Exception:
                                                        meta_path = ''
                                                    if os.path.normpath(meta_path).lower() == os.path.normpath(target).lower():
                                                        return True
                                                return False

                                            if _already_imported(camera_path_norm):
                                                log_debug(f'Camera already imported: {camera_path_norm}')
                                                continue

                                            try:
                                                pre_nodes = set(nuke.allNodes())
                                            except Exception:
                                                pre_nodes = set()
                                            try:
                                                nuke.nodePaste(camera_path_norm)
                                                log_debug(f'Imported camera from {camera_path_norm}')
                                            except Exception as paste_error:
                                                log_debug(f'Failed to import camera file: {paste_error}', 'ERROR')
                                                continue
                                            try:
                                                post_nodes = set(nuke.allNodes())
                                            except Exception:
                                                post_nodes = pre_nodes
                                            new_nodes = list(post_nodes.difference(pre_nodes))
                                            if not new_nodes:
                                                log_debug('No new nodes detected after camera paste.', 'WARNING')
                                                continue

                                            for cam_index, cam_node in enumerate(new_nodes):
                                                try:
                                                    cam_node.setMetaData('charon/camera_path', camera_path_norm.replace('\\', '/'))
                                                except Exception:
                                                    pass
                                                try:
                                                    cam_node.setMetaData('charon/parent_id', parent_norm_local or '')
                                                except Exception:
                                                    pass
                                                try:
                                                    cam_node.setMetaData('charon/output_label', CAMERA_OUTPUT_LABEL)
                                                except Exception:
                                                    pass
                                                try:
                                                    parent_knob = cam_node.knob('charon_parent_id')
                                                except Exception:
                                                    parent_knob = None
                                                if parent_knob is None:
                                                    try:
                                                        parent_knob = nuke.String_Knob('charon_parent_id', 'Charon Parent ID', '')
                                                        parent_knob.setFlag(nuke.NO_ANIMATION)
                                                        parent_knob.setFlag(nuke.INVISIBLE)
                                                        cam_node.addKnob(parent_knob)
                                                    except Exception:
                                                        parent_knob = None
                                                if parent_knob is not None:
                                                    try:
                                                        parent_knob.setValue(parent_norm_local or '')
                                                    except Exception:
                                                        pass
                                                try:
                                                    anchor_knob = cam_node.knob('charon_link_anchor')
                                                except Exception:
                                                    anchor_knob = None
                                                if anchor_knob is None:
                                                    try:
                                                        anchor_knob = nuke.Double_Knob('charon_link_anchor', 'Charon Link Anchor')
                                                        anchor_knob.setFlag(nuke.NO_ANIMATION)
                                                        anchor_knob.setFlag(nuke.INVISIBLE)
                                                        cam_node.addKnob(anchor_knob)
                                                    except Exception:
                                                        anchor_knob = None
                                                if anchor_knob is not None:
                                                    try:
                                                        anchor_knob.setExpression(f"{node.fullName()}.charon_link_anchor")
                                                    except Exception:
                                                        try:
                                                            anchor_knob.clearAnimated()
                                                        except Exception:
                                                            pass
                                                        try:
                                                            anchor_knob.setValue(link_anchor_value)
                                                        except Exception:
                                                            pass
                                                try:
                                                    cam_node.setMetaData('charon/link_anchor', link_anchor_value)
                                                except Exception:
                                                    pass
                                                try:
                                                    info_tab = cam_node.knob('charon_info_tab')
                                                except Exception:
                                                    info_tab = None
                                                if info_tab is None:
                                                    try:
                                                        info_tab = nuke.Tab_Knob('charon_info_tab', 'Charon Info')
                                                        cam_node.addKnob(info_tab)
                                                    except Exception:
                                                        info_tab = None
                                                try:
                                                    info_text = cam_node.knob('charon_info_text')
                                                except Exception:
                                                    info_text = None
                                                if info_text is None and info_tab is not None:
                                                    try:
                                                        info_text = nuke.Text_Knob('charon_info_text', 'Metadata', '')
                                                        cam_node.addKnob(info_text)
                                                    except Exception:
                                                        info_text = None
                                                if info_text is not None:
                                                    summary_lines = [
                                                        f"Parent ID: {parent_norm_local or 'N/A'}",
                                                        f"Camera Path: {camera_path_norm}",
                                                    ]
                                                    try:
                                                        info_text.setValue("\n".join(summary_lines))
                                                    except Exception:
                                                        pass
                                                try:
                                                    camera_folder = os.path.basename(os.path.dirname(camera_path_norm)) or ""
                                                    camera_label = _sanitize_name(camera_folder, 'Cam')
                                                    cam_node.setName(f"CRCAM_{camera_label}")
                                                except Exception:
                                                    try:
                                                        cam_node.setName('CRCAM')
                                                    except Exception:
                                                        pass
                                                try:
                                                    cam_node['label'].setValue("")
                                                except Exception:
                                                    pass
                                                try:
                                                    cam_node.setXpos(int(node.xpos()) + (layout_index * 140))
                                                    cam_node.setYpos(y_base)
                                                except Exception:
                                                    pass
                                                layout_index += 1

                                    cleanup_files()

                                nuke.executeInMainThread(update_or_create_read_nodes)

                                def check_auto_contact_sheet():
                                    try:
                                        if entries:
                                            write_metadata('charon/batch_outputs', json.dumps(entries))
                                    except Exception as meta_err:
                                        log_debug(f"Failed to write batch outputs metadata: {meta_err}", "WARNING")

                                    try:
                                        create_contact_sheet_from_charonop(node)
                                    except Exception as cs_err:
                                        log_debug(f"Contact Sheet creation failed: {cs_err}", "WARNING")
                                
                                nuke.executeInMainThread(check_auto_contact_sheet)
                            else:
                                log_debug('Auto import disabled; skipping Read node creation.')
                                for idx, entry in enumerate(entries, start=1):
                                    output_path = entry.get('output_path')
                                    if output_path:
                                        batch_label = f'Batch {idx}/{total_batches}' if total_batches > 1 else 'Run'
                                        log_debug(f'{batch_label} output located at: {output_path}')
                                try:
                                    write_metadata('charon/batch_outputs', json.dumps(entries))
                                except Exception:
                                    pass
                                cleanup_files()
                        else:
                            error_msg = result_data.get('error', 'Unknown error')
                            log_debug(f'Processing failed: {error_msg}', 'ERROR')
                            try:
                                for temp_path in list(rendered_files.values()):
                                    if os.path.exists(temp_path):
                                        os.remove(temp_path)
                                        log_debug(f'Cleaned up temp file: {temp_path}')
                            except Exception as cleanup_error:
                                log_debug(f'Could not clean up files after failure: {cleanup_error}', 'WARNING')
                    except Exception as exc:
                        log_debug(f'Error reading result: {exc}', 'ERROR')
                    break
                time.sleep(1.0)

        watcher_thread = threading.Thread(target=result_watcher)
        watcher_thread.daemon = True
        watcher_thread.start()

        log_debug('Processing started in background')

    except Exception as exc:
        log_debug(f'Error: {exc}', 'ERROR')
        message = f'Error: {exc}'
        try:
            node.knob('charon_status').setValue(message)
            node.knob('charon_progress').setValue(-1.0)
        except Exception:
            pass
        if 'load_status_payload' in locals() and 'save_status_payload' in locals():
            try:
                payload = load_status_payload()
                runs = ensure_history(payload) if 'ensure_history' in locals() else payload.setdefault('runs', [])
                now = time.time()
                payload.update({
                    'status': message,
                    'state': 'Error',
                    'message': message,
                    'progress': -1.0,
                    'run_id': locals().get('current_run_id'),
                    'updated_at': now,
                    'last_error': str(exc),
                })
                runs.append({
                    'id': locals().get('current_run_id'),
                    'status': 'Error',
                    'message': message,
                    'progress': -1.0,
                    'started_at': locals().get('run_started_at'),
                    'completed_at': now,
                    'error': str(exc),
                })
                payload['runs'] = runs[-10:] if isinstance(runs, list) else runs
                payload.pop('current_run', None)
                save_status_payload(payload)
            except Exception as payload_error:
                log_debug(f'Failed to persist error payload: {payload_error}', 'WARNING')


def create_contact_sheet_from_charonop(node_override=None):
    """Create a Contact Sheet group from all outputs of the current CharonOp."""
    try:
        import nuke
        import json
    except ImportError:
        return

    node = node_override
    if node is None:
        try:
            node = nuke.thisNode()
        except Exception:
            pass
    if node is None:
        return

    outputs = []
    try:
        raw = node.metadata('charon/batch_outputs')
        if raw:
            outputs = json.loads(raw)
    except Exception:
        pass
    
    if not outputs:
        try:
            raw_payload = node.metadata("charon/status_payload")
            if raw_payload:
                payload = json.loads(raw_payload)
                runs = payload.get('runs', [])
                if runs:
                    last_run = runs[-1]
                    outputs = last_run.get('batch_outputs', [])
        except Exception:
            pass

    if not outputs:
        try:
            last = node.knob('charon_last_output').value()
            if last:
                outputs = [{'output_path': last}]
        except Exception:
            pass

    image_paths = []
    if isinstance(outputs, list):
        for o in outputs:
            path = ""
            if isinstance(o, dict):
                path = o.get('output_path') or o.get('download_path')
            elif isinstance(o, str):
                path = o
            
            if path:
                ext = os.path.splitext(path)[1].lower()
                if ext in IMAGE_OUTPUT_EXTENSIONS:
                    image_paths.append(path)

    # Fallback: Scan directory if we have a hint but missing items
    # This helps when metadata is truncated or lost but files exist
    if len(image_paths) > 0:
        ref_path = image_paths[0]
        parent_dir = os.path.dirname(ref_path)
        
        if parent_dir and os.path.isdir(parent_dir):
            scanned = []
            try:
                for fname in os.listdir(parent_dir):
                    ext = os.path.splitext(fname)[1].lower()
                    if ext in IMAGE_OUTPUT_EXTENSIONS:
                        if fname.startswith("."): continue
                        full_path = os.path.join(parent_dir, fname).replace('\\', '/')
                        scanned.append(full_path)
            except: pass
            
            # If scanning found more files, use them
            if len(scanned) > len(image_paths):
                image_paths = sorted(scanned)

    if not image_paths:
        if node_override is None:
            nuke.message("No image outputs found.")
        return

    _create_generic_result_group(node, image_paths)

def _create_generic_result_group(charon_node, image_paths):
    import nuke
    import uuid
    
    node_id = ""
    try:
        node_id = charon_node.knob('charon_node_id').value()
    except: pass
    
    # Cleanup existing by knob
    try:
        existing_name = charon_node.knob('charon_contact_sheet').value()
        if existing_name:
            existing = nuke.toNode(existing_name)
            if existing:
                nuke.delete(existing)
    except: pass
    
    # Cleanup existing by metadata (fallback)
    if node_id:
        for n in nuke.allNodes("Group"):
            try:
                parent_id = n.metadata('charon/parent_id')
                if parent_id == node_id and "ContactSheet" in n.name():
                    nuke.delete(n)
            except: pass

    for n in nuke.selectedNodes():
        n.setSelected(False)
        
    safe_name = "".join(c if c.isalnum() else "_" for c in charon_node.name())
    group = nuke.createNode("Group")
    group.setName(f"Charon_ContactSheet_{safe_name}")
    group.setXYpos(charon_node.xpos() + 200, charon_node.ypos() + 100)
    
    # Register new name on parent
    try:
        k = charon_node.knob('charon_contact_sheet')
        if not k:
            k = nuke.String_Knob('charon_contact_sheet', 'Contact Sheet', '')
            k.setFlag(nuke.NO_ANIMATION | nuke.INVISIBLE)
            charon_node.addKnob(k)
        k.setValue(group.name())
    except: pass
    
    read_id = uuid.uuid4().hex[:12].lower()
    
    setter = getattr(group, 'setMetaData', getattr(group, 'setMetadata', None))
    if setter:
        setter('charon/parent_id', node_id)
        setter('charon/read_id', read_id)
    
    pk = nuke.String_Knob('charon_parent_id', 'Parent ID', node_id)
    pk.setFlag(nuke.NO_ANIMATION | nuke.INVISIBLE)
    group.addKnob(pk)
    
    rk = nuke.String_Knob('charon_read_id', 'Read ID', read_id)
    rk.setFlag(nuke.NO_ANIMATION | nuke.INVISIBLE)
    group.addKnob(rk)
    
    ak = nuke.Double_Knob('charon_link_anchor', 'Anchor')
    ak.setFlag(nuke.NO_ANIMATION | nuke.INVISIBLE)
    group.addKnob(ak)
    try:
        ak.setExpression(f"{charon_node.fullName()}.charon_link_anchor")
    except: pass
    
    tab = nuke.Tab_Knob('charon_info_tab', 'Charon Info')
    group.addKnob(tab)
    info = nuke.Text_Knob('charon_info_text', 'Info', f"Parent: {node_id}\nImages: {len(image_paths)}")
    group.addKnob(info)
    
    group.begin()
    
    cols = min(len(image_paths), 4)
    rows = (len(image_paths) + cols - 1) // cols
    
    cs = nuke.createNode("ContactSheet")
    cs['width'].setValue(cols * 1024)
    cs['height'].setValue(rows * 1024)
    cs['rows'].setValue(rows)
    cs['columns'].setValue(cols)
    cs['roworder'].setValue("TopBottom")
    cs['gap'].setValue(10)
    cs['center'].setValue(True)
    
    for i, path in enumerate(image_paths):
        r = nuke.createNode("Read")
        r['file'].setValue(path.replace('\\', '/'))
        r['on_error'].setValue("nearest frame")
        r.setXYpos(i * 150, -300) # Spacing adjustment
        
        # Create Text node for label
        txt = nuke.createNode("Text2")
        txt.setInput(0, r)
        try:
            filename = os.path.basename(path)
            txt['message'].setValue(filename)
            txt['box'].setValue([0, 0, 1000, 100])
            txt['yjustify'].setValue("bottom")
            txt['global_font_scale'].setValue(0.5)
        except Exception:
            pass
        txt.setXYpos(r.xpos(), r.ypos() + 150)
        
        cs.setInput(i, txt)
        r.setSelected(False)
        txt.setSelected(False)
        
    last_node = cs
    
    # Apply ACES if enabled (Inside Group)
    from . import preferences
    aces_enabled = preferences.get_preference("aces_mode_enabled", False)
    if aces_enabled:
        from .paths import get_charon_temp_dir
        ivt_temp = os.path.join(get_charon_temp_dir(), f"ivt_cs_{str(uuid.uuid4())[:8]}.nk").replace("\\", "/")
        try:
            with open(ivt_temp, "w") as f:
                f.write(INVERSE_VIEW_TRANSFORM_GROUP)
            
            for n in nuke.selectedNodes(): n.setSelected(False)
            cs.setSelected(True)
            
            nuke.nodePaste(ivt_temp)
            ivt_node = nuke.selectedNode()
            if ivt_node:
                ivt_node.setInput(0, cs)
                ivt_node.setXpos(cs.xpos())
                ivt_node.setYpos(cs.ypos() + 200)
                
                # Set blue color
                try:
                    ivt_node['tile_color'].setValue(0x0000FFFF) # Blue
                    ivt_node['gl_color'].setValue(0x0000FFFF)
                except: pass



                last_node = ivt_node
        except: pass
        finally:
            if os.path.exists(ivt_temp):
                try: os.remove(ivt_temp)
                except: pass
    
    for n in nuke.selectedNodes():
        n.setSelected(False)
        
    out = nuke.createNode("Output")
    out.setInput(0, last_node)
    out.setXYpos(last_node.xpos(), last_node.ypos() + 200)
    
    group.end()
