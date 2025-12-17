# CharonOp Node Processing Script
import copy
import json
import os
import subprocess
import threading
import time
import uuid
import zlib
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
    resolve_comfy_environment,
)
from .workflow_runtime import convert_workflow as runtime_convert_workflow
from .comfy_client import ComfyUIClient
from . import config, preferences
from .node_factory import reset_charon_node_state
from .utilities import get_current_user_slug, status_to_gl_color, status_to_tile_color

CONTROL_VALUE_TOKENS = {"fixed", "increment", "decrement", "randomize"}
MODEL_OUTPUT_EXTENSIONS = {".obj", ".fbx", ".abc", ".gltf", ".glb", ".usd", ".usdz"}


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
            log_debug(
                f"Failed to resolve parameter binding for node {spec_copy.get('node_id')} attribute {spec_copy.get('attribute')}",
                "WARNING",
            )
        updated_specs.append(spec_copy)

    if changed:
        _write_parameter_specs(node, updated_specs)

    return updated_specs


def _apply_parameter_overrides(
    node,
    workflow_copy: Dict[str, Any],
    parameter_specs: List[Dict[str, Any]],
) -> List[Tuple[str, str]]:
    """Write knob values into the converted prompt using stored bindings."""
    applied: List[Tuple[str, str]] = []
    if not parameter_specs or not isinstance(workflow_copy, dict):
        return applied

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
        try:
            raw_value = knob.value()
        except Exception as exc:
            log_debug(f"Failed to read knob {knob_name}: {exc}", "WARNING")
            continue

        coerced = _coerce_parameter_value(spec.get("type") or "", raw_value)
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
        "        label_knob.setValue('Batch %d/%d' % (idx + 1, len(outputs)))\n"
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
                    recreate_knob.setEnabled(has_output and linked is None)
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

        charon_node_id = ensure_charon_node_id()
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

        def apply_status_color(state: str, read_node_override=None):
            tile_color = status_to_tile_color(state)
            gl_color = status_to_gl_color(state)
            debug_line = f"Status={state or 'Unknown'} | tile=0x{tile_color:08X}"
            if gl_color is not None:
                debug_line += " | gl=" + ",".join(f"{channel:.3f}" for channel in gl_color)

            def _apply_to_target(target):
                if target is None:
                    return
                try:
                    color_knob = target["tile_color"]
                except Exception:
                    color_knob = None
                if color_knob is not None:
                    try:
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
                            gl_knob.setValue(gl_color)
                        except Exception:
                            try:
                                gl_knob.setValue(list(gl_color))
                            except Exception:
                                pass

            def _update_debug(target_node):
                try:
                    debug_knob = target_node.knob("charon_color_debug")
                except Exception:
                    debug_knob = None
                if debug_knob is None:
                    try:
                        debug_knob = nuke.Text_Knob("charon_color_debug", "Color Debug", "")
                        debug_knob.setFlag(nuke.NO_ANIMATION)
                        target_node.addKnob(debug_knob)
                    except Exception:
                        debug_knob = None
                if debug_knob is not None:
                    try:
                        debug_knob.setValue(debug_line)
                    except Exception:
                        pass

            def _apply_all():
                _apply_to_target(node)
                _update_debug(node)

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
                    recreate_knob.setEnabled(has_output and not has_read)
                except Exception:
                    pass

            for target in targets:
                def _apply_target():
                    _apply_to_target(target)
                try:
                    nuke.executeInMainThread(_apply_target)
                except Exception:
                    _apply_target()

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
            if label_text is None:
                parent_text = read_node_parent_id(read_node) or 'N/A'
                read_id_text = read_node_unique_id(read_node) or 'N/A'
                label_text = f"Charon Parent: {parent_text}\nRead ID: {read_id_text}"
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
            if read_node is None:
                return None, None, None
            try:
                outputs_knob = read_node.knob('charon_batch_outputs')
            except Exception:
                outputs_knob = None
            if outputs_knob is None:
                try:
                    outputs_knob = nuke.Multiline_Eval_String_Knob('charon_batch_outputs', 'Batch Outputs', '')
                    outputs_knob.setFlag(nuke.NO_ANIMATION)
                    outputs_knob.setFlag(nuke.INVISIBLE)
                    read_node.addKnob(outputs_knob)
                except Exception:
                    outputs_knob = None
            try:
                index_knob = read_node.knob('charon_batch_index')
            except Exception:
                index_knob = None
            if index_knob is None:
                try:
                    index_knob = nuke.Int_Knob('charon_batch_index', 'Batch Index', 0)
                    index_knob.setFlag(nuke.NO_ANIMATION)
                    index_knob.setFlag(nuke.INVISIBLE)
                    read_node.addKnob(index_knob)
                except Exception:
                    index_knob = None
            try:
                label_knob = read_node.knob('charon_batch_label')
            except Exception:
                label_knob = None
            if label_knob is None:
                try:
                    label_knob = nuke.Text_Knob('charon_batch_label', 'Batch', 'No batch outputs yet')
                    read_node.addKnob(label_knob)
                except Exception:
                    label_knob = None
            try:
                prev_knob = read_node.knob('charon_batch_prev')
            except Exception:
                prev_knob = None
            if prev_knob is None:
                try:
                    prev_knob = nuke.PyScript_Knob('charon_batch_prev', 'Prev Batch')
                    prev_knob.setCommand(_batch_nav_command(-1))
                    prev_knob.setFlag(nuke.STARTLINE)
                    read_node.addKnob(prev_knob)
                except Exception:
                    prev_knob = None
            try:
                next_knob = read_node.knob('charon_batch_next')
            except Exception:
                next_knob = None
            if next_knob is None:
                try:
                    next_knob = nuke.PyScript_Knob('charon_batch_next', 'Next Batch')
                    next_knob.setCommand(_batch_nav_command(1))
                    next_knob.setFlag(nuke.STARTLINE)
                    read_node.addKnob(next_knob)
                except Exception:
                    next_knob = None
            return outputs_knob, index_knob, label_knob

        def ensure_read_node_info(read_node, read_id: str):
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
            summary = [
                f"Parent ID: {parent_display}",
                f"Read Node ID: {read_id or 'N/A'}",
            ]
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
            ensure_read_node_info(read_node, read_id)
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
            try:
                info_knob = node.knob('charon_read_id_info')
                if info_knob is not None:
                    info_knob.setValue(read_id or "Not linked")
            except Exception:
                pass
            try:
                recreate_knob = node.knob('charon_recreate_read')
                if recreate_knob is not None:
                    recreate_knob.setEnabled(False)
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
                    label_knob.setValue('No batch outputs yet')
                except Exception:
                    pass
            ensure_read_node_info(read_node, "")
            assign_read_label(read_node, "")
            try:
                knob = node.knob('charon_read_node_id')
                if knob is not None:
                    knob.setValue("")
            except Exception:
                pass
            write_metadata('charon/read_node_id', "")
            try:
                knob = node.knob('charon_read_id_info')
                if knob is not None:
                    knob.setValue("Not linked")
            except Exception:
                pass
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
            target_read_name = f"CharonRead_{read_base}"
            try:
                read_node.setName(target_read_name)
            except Exception:
                try:
                    read_node.setName(f"CharonRead_{read_base}_{charon_node_id}")
                except Exception:
                    try:
                        read_node.setName("CharonRead")
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
        try:
            workflow_path = node.knob('workflow_path').value()
        except Exception:
            workflow_path = ''

        workflow_display_name = _resolve_workflow_display_name()

        if not workflow_data_str or not input_mapping_str:
            log_debug('No workflow data found on CharonOp node', 'ERROR')
            raise RuntimeError('Missing workflow data on CharonOp node')

        workflow_data = json.loads(workflow_data_str)
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

        if not connected_inputs:
            log_debug('Please connect at least one input node', 'ERROR')
            raise RuntimeError('Please connect at least one input node before processing')

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

        if not render_jobs:
            first_index, first_node = next(iter(connected_inputs.items()))
            render_jobs.append({
                'index': first_index,
                'mapping': {'name': f'Input {first_index + 1}', 'type': 'image'},
                'node': first_node
            })

        primary_job = None
        for job in render_jobs:
            mapping = job.get('mapping', {})
            if isinstance(mapping, dict) and mapping.get('type') == 'image':
                primary_job = job
                break
        if not primary_job:
            primary_job = render_jobs[0]
        primary_index = primary_job['index']

        rendered_files = {}
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

            write_node = nuke.createNode('Write', inpanel=False)
            write_node['file'].setValue(temp_path_nuke)
            write_node['file_type'].setValue('png')
            write_node.setInput(0, source_node)
            try:
                nuke.execute(write_node, current_frame, current_frame)
            finally:
                try:
                    nuke.delete(write_node)
                except Exception:
                    pass
                if shuffle_node:
                    try:
                        nuke.delete(shuffle_node)
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

        def background_process():
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

                update_progress(0.2, 'Uploading images', extra=conversion_extra or None)

                workflow_copy = copy.deepcopy(prompt_data)
                applied_overrides = _apply_parameter_overrides(
                    node,
                    workflow_copy,
                    parameter_specs_local,
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
                else:
                    filename = uploaded_assets.get(primary_index)
                    if filename:
                        for target_id, target_data in workflow_copy.items():
                            if isinstance(target_data, dict) and target_data.get('class_type') == 'LoadImage':
                                assign_to_node(target_id, filename)
                                break

                base_prompt = copy.deepcopy(workflow_copy)
                seed_records = _capture_seed_inputs(base_prompt)
                batch_outputs: List[Dict[str, Any]] = []
                timeout = 300
                per_batch_progress = 0.5 / max(1, batch_count)

                def _progress_for(batch_index: int, local: float) -> float:
                    local_clamped = max(0.0, min(1.0, local))
                    base_value = 0.5 + per_batch_progress * batch_index
                    return min(base_value + per_batch_progress * local_clamped, 1.0)

                def _select_output_artifact(outputs_map, prompt_lookup):
                    """
                    Extract the first available output artifact (image/file/mesh).
                    Returns dict with filename, subfolder, type, extension, node_id, class_type.
                    """
                    if not isinstance(outputs_map, dict):
                        return None
                    for node_id, output_data in outputs_map.items():
                        if not isinstance(output_data, dict):
                            continue
                        for key in ("images", "files", "meshes"):
                            entries = output_data.get(key)
                            if not isinstance(entries, list) or not entries:
                                continue
                            entry = entries[0]
                            filename = entry.get("filename")
                            if not filename:
                                continue
                            ext = (os.path.splitext(filename)[1] or "").lower()
                            return {
                                "filename": filename,
                                "subfolder": entry.get("subfolder") or "",
                                "type": entry.get("type") or "output",
                                "extension": ext,
                                "node_id": node_id,
                                "class_type": (prompt_lookup.get(node_id) or {}).get("class_type") or "",
                                "kind": key,
                            }
                    return None

                for batch_index in range(batch_count):
                    seed_offset = batch_index * 9973
                    prompt_payload = copy.deepcopy(base_prompt)
                    if seed_records:
                        _apply_seed_offset(prompt_payload, seed_records, seed_offset)

                    batch_label = f'Batch {batch_index + 1}/{batch_count}' if batch_count > 1 else 'Run'
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
                                    if outputs:
                                        artifact = _select_output_artifact(outputs, base_prompt)
                                        if not artifact:
                                            raise Exception('ComfyUI did not return an output file')
                                        update_progress(
                                            _progress_for(batch_index, 0.9),
                                            f'{batch_label}: downloading result',
                                            extra={
                                                'prompt_id': prompt_id,
                                                'batch_index': batch_index + 1,
                                                'batch_total': batch_count,
                                            },
                                        )
                                        raw_extension = artifact.get("extension") or ".png"
                                        category = "3D" if raw_extension.lower() in MODEL_OUTPUT_EXTENSIONS else "2D"
                                        allocated_output_path = allocate_charon_output_path(
                                            charon_node_id,
                                            _resolve_nuke_script_name(),
                                            raw_extension,
                                            user_slug=user_slug,
                                            workflow_name=workflow_display_name,
                                            category=category,
                                        )
                                        log_debug(f'Resolved output path: {allocated_output_path}')
                                        success = comfy_client.download_file(
                                            artifact["filename"],
                                            allocated_output_path,
                                            subfolder=artifact.get("subfolder", ""),
                                            file_type=artifact.get("type", "output"),
                                        )
                                        if not success:
                                            raise Exception('Failed to download result file from ComfyUI')

                                        final_output_path = allocated_output_path
                                        converted_from = None
                                        if raw_extension.lower() == ".glb":
                                            obj_target = os.path.splitext(allocated_output_path)[0] + ".obj"
                                            log_debug(f'Converting GLB to OBJ: {allocated_output_path} -> {obj_target}')
                                            final_output_path = _convert_glb_to_obj(allocated_output_path, obj_target)
                                            converted_from = allocated_output_path

                                        elapsed = time.time() - start_time
                                        normalized_output_path = final_output_path.replace('\\', '/')
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
                                        }
                                        if converted_from:
                                            batch_entry['converted_from'] = converted_from.replace('\\', '/')
                                        batch_outputs.append(batch_entry)
                                        extra_payload = {
                                            'output_path': normalized_output_path,
                                            'elapsed_time': elapsed,
                                            'prompt_id': prompt_id,
                                            'batch_index': batch_index + 1,
                                            'batch_total': batch_count,
                                            'batch_outputs': batch_outputs.copy(),
                                            'output_kind': category,
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

                if not batch_outputs:
                    raise Exception('No outputs were generated by ComfyUI')

                result_data = {
                    'success': True,
                    'outputs': batch_outputs,
                    'node_x': node.xpos(),
                    'node_y': node.ypos(),
                    'batch_total': batch_count,
                    'output_path': batch_outputs[-1]['output_path'],
                    'elapsed_time': batch_outputs[-1].get('elapsed_time', 0),
                    'output_kind': batch_outputs[-1].get('output_kind'),
                }
                with open(result_file, 'w') as fp:
                    json.dump(result_data, fp)
                return

            except Exception as exc:
                message = f'Error: {exc}'
                update_progress(-1.0, message, error=str(exc))
                result_data = {
                    'success': False,
                    'error': str(exc),
                    'node_x': node.xpos(),
                    'node_y': node.ypos()
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
                            node_x = result_data.get('node_x', node.xpos())
                            node_y = result_data.get('node_y', node.ypos())

                            if resolve_auto_import():
                                def update_or_create_read_nodes():
                                    reuse_existing = True
                                    try:
                                        reuse_knob = node.knob('charon_reuse_output')
                                        if reuse_knob is not None:
                                            reuse_existing = bool(int(reuse_knob.value()))
                                    except Exception:
                                        reuse_existing = False

                                    def _remove_mismatched_reads(required_class: str):
                                        try:
                                            candidates = list(nuke.allNodes("Read")) + list(nuke.allNodes("ReadGeo2"))
                                        except Exception:
                                            candidates = []
                                        for candidate in candidates:
                                            try:
                                                parent_val = candidate.metadata('charon/parent_id')
                                            except Exception:
                                                parent_val = ""
                                            if (parent_val or "").strip().lower() != (charon_node_id or "").strip().lower():
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

                                    outputs = []
                                    for entry in entries:
                                        path = entry.get('output_path')
                                        if path:
                                            outputs.append(path)
                                    if not outputs:
                                        log_debug('No output paths available for Read update.', 'WARNING')
                                        cleanup_files()
                                        return

                                    required_class = "ReadGeo2" if os.path.splitext(outputs[-1])[1].lower() in MODEL_OUTPUT_EXTENSIONS else "Read"
                                    if required_class == "ReadGeo2":
                                        _remove_mismatched_reads(required_class)

                                    read_node = find_linked_read_node()
                                    if read_node is not None and not reuse_existing:
                                        unlink_read_node(read_node)
                                        read_node = None
                                    if read_node is not None:
                                        try:
                                            current_class = getattr(read_node, "Class", lambda: "")()
                                        except Exception:
                                            current_class = ""
                                        if current_class != required_class:
                                            unlink_read_node(read_node)
                                            read_node = None

                                    if read_node is None:
                                        try:
                                            read_node = nuke.createNode(required_class)
                                            read_node.setXpos(node_x)
                                            read_node.setYpos(node_y + 60)
                                            read_node.setSelected(True)
                                        except Exception as create_error:
                                            log_debug(f'Failed to create CharonRead node: {create_error}', 'ERROR')
                                            cleanup_files()
                                            return
                                        read_base = _sanitize_name(_resolve_workflow_display_name(), "Workflow")
                                        target_read_name = f"CharonRead_{read_base}"
                                        try:
                                            read_node.setName(target_read_name)
                                        except Exception:
                                            try:
                                                read_node.setName(f"CharonRead_{read_base}_{charon_node_id}")
                                            except Exception:
                                                try:
                                                    read_node.setName("CharonRead")
                                                except Exception:
                                                    pass
                                        log_debug('Created new Read node for output.')
                                    else:
                                        try:
                                            read_node.setSelected(True)
                                        except Exception:
                                            pass
                                        log_debug('Reusing existing Read node for output update.')

                                    try:
                                        outputs_json = json.dumps(entries)
                                    except Exception as serialize_error:
                                        log_debug(f'Could not serialize batch metadata: {serialize_error}', 'WARNING')
                                        outputs_json = json.dumps([{'output_path': path} for path in outputs])

                                    outputs_knob, index_knob, label_knob = ensure_batch_navigation_controls(read_node)
                                    default_index = len(outputs) - 1
                                    if reuse_existing and index_knob is not None:
                                        try:
                                            existing_index = int(index_knob.value())
                                        except Exception:
                                            existing_index = default_index
                                        if 0 <= existing_index < len(outputs):
                                            default_index = existing_index

                                    try:
                                        read_node['file'].setValue(outputs[default_index])
                                    except Exception as assign_error:
                                        log_debug(f'Could not assign output path to CharonRead node: {assign_error}', 'ERROR')

                                    if outputs_knob is not None:
                                        try:
                                            outputs_knob.setValue(outputs_json)
                                        except Exception:
                                            pass
                                    if index_knob is not None:
                                        try:
                                            index_knob.setValue(default_index)
                                        except Exception:
                                            pass
                                    if label_knob is not None:
                                        try:
                                            label_knob.setValue(f'Batch {default_index + 1}/{len(outputs)}')
                                        except Exception:
                                            pass

                                    try:
                                        read_node.setMetaData('charon/batch_outputs', outputs_json)
                                    except Exception:
                                        pass
                                    try:
                                        write_metadata('charon/batch_outputs', outputs_json)
                                    except Exception:
                                        pass

                                    mark_read_node(read_node)
                                    cleanup_files()

                                nuke.executeInMainThread(update_or_create_read_nodes)
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


def recreate_missing_read_node():
    """Recreate the linked Read node when it has been deleted."""
    try:
        import nuke  # type: ignore
    except ImportError as exc:
        raise RuntimeError('Nuke is required to recreate Charon Read nodes.') from exc

    try:
        node = nuke.thisNode()
    except Exception:
        node = None
    if node is None:
        return

    def _normalize(value) -> str:
        if not value:
            return ""
        text = str(value).strip().lower()
        if not text:
            return ""
        return text[:12]

    def _safe_knob_value(owner, name: str) -> str:
        try:
            knob = owner.knob(name)
        except Exception:
            return ""
        if knob is None:
            return ""
        try:
            return str(knob.value() or "")
        except Exception:
            return ""

    def _node_metadata(name: str) -> str:
        try:
            return str(node.metadata(name) or "")
        except Exception:
            return ""

    def _find_read_by_id(read_id: str):
        normalized = _normalize(read_id)
        if not normalized:
            return None
        candidates = []
        try:
            candidates.extend(list(nuke.allNodes("Read")))
        except Exception:
            pass
        try:
            candidates.extend(list(nuke.allNodes("ReadGeo2")))
        except Exception:
            pass
        for candidate in candidates:
            try:
                candidate_id = candidate.metadata('charon/read_id')
            except Exception:
                candidate_id = ""
            if _normalize(candidate_id) == normalized:
                return candidate
            try:
                knob = candidate.knob('charon_read_id')
                if knob and _normalize(knob.value()) == normalized:
                    return candidate
            except Exception:
                pass
        return None

    def _find_read_by_parent(parent_id: str):
        normalized = _normalize(parent_id)
        if not normalized:
            return None
        candidates = []
        try:
            candidates.extend(list(nuke.allNodes("Read")))
        except Exception:
            pass
        try:
            candidates.extend(list(nuke.allNodes("ReadGeo2")))
        except Exception:
            pass
        for candidate in candidates:
            try:
                parent_val = candidate.metadata('charon/parent_id')
            except Exception:
                parent_val = ""
            if _normalize(parent_val) == normalized:
                return candidate
            try:
                knob = candidate.knob('charon_parent_id')
                if knob and _normalize(knob.value()) == normalized:
                    return candidate
            except Exception:
                pass
        return None

    def _ensure_hidden_string(target, name: str, label: str, value: str):
        try:
            knob = target.knob(name)
        except Exception:
            knob = None
        if knob is None:
            try:
                knob = nuke.String_Knob(name, label, '')
                knob.setFlag(nuke.NO_ANIMATION)
                knob.setFlag(nuke.INVISIBLE)
                target.addKnob(knob)
            except Exception:
                knob = None
        if knob is not None:
            try:
                knob.setValue(value or "")
            except Exception:
                pass

    def _assign_read_label(read_node, parent_id: str, read_id: str):
        if read_node is None:
            return
        summary = f"Charon Parent: {parent_id or 'N/A'}\\nRead ID: {read_id or 'N/A'}"
        try:
            label_knob = read_node['label']
        except Exception:
            label_knob = None
        if label_knob is not None:
            try:
                label_knob.setValue(summary)
            except Exception:
                pass

    read_id = _normalize(_safe_knob_value(node, 'charon_read_node_id'))
    if not read_id:
        read_id = _normalize(_node_metadata('charon/read_node_id'))
    parent_id = _normalize(_safe_knob_value(node, 'charon_node_id'))
    if not parent_id:
        parent_id = _normalize(_node_metadata('charon/node_id'))
    last_output = _safe_knob_value(node, 'charon_last_output').strip()
    if not last_output:
        last_output = _node_metadata('charon/last_output').strip()
    read_hint = _safe_knob_value(node, 'charon_read_node')

    existing = _find_read_by_id(read_id)
    if existing is None and read_hint:
        try:
            candidate = nuke.toNode(read_hint)
        except Exception:
            candidate = None
        if candidate is not None and getattr(candidate, "Class", lambda: "")() in {"Read", "ReadGeo2"}:
            existing = candidate
    if existing is None and parent_id:
        existing = _find_read_by_parent(parent_id)

    try:
        recreate_knob = node.knob('charon_recreate_read')
    except Exception:
        recreate_knob = None

    if existing is not None:
        if recreate_knob is not None:
            try:
                recreate_knob.setEnabled(False)
            except Exception:
                pass
        nuke.message('Linked Read node already exists.')
        return

    if not last_output:
        nuke.message('No output path recorded yet.')
        if recreate_knob is not None:
            try:
                recreate_knob.setEnabled(False)
            except Exception:
                pass
        return

    normalized_output = os.path.normpath(last_output)
    if not os.path.exists(normalized_output):
        nuke.message('Output file not found:\\n{0}'.format(normalized_output))
        if recreate_knob is not None:
            try:
                recreate_knob.setEnabled(True)
            except Exception:
                pass
        return

    if not read_id:
        read_id = uuid.uuid4().hex[:12].lower()

    try:
        creator_group = node.parent()
    except Exception:
        creator_group = None
    if creator_group is None:
        try:
            creator_group = nuke.root()
        except Exception:
            creator_group = None
    began_group = False
    if creator_group is not None:
        try:
            creator_group.begin()
            began_group = True
        except Exception:
            began_group = False
    extension = os.path.splitext(normalized_output)[1].lower()
    read_class = "ReadGeo2" if extension in MODEL_OUTPUT_EXTENSIONS else "Read"
    try:
        read_node = nuke.createNode(read_class, inpanel=False)
    except Exception as creation_error:
        if began_group and creator_group is not None:
            try:
                creator_group.end()
            except Exception:
                pass
        nuke.message('Failed to create CharonRead node: {0}'.format(creation_error))
        return
    finally:
        if began_group and creator_group is not None:
            try:
                creator_group.end()
            except Exception:
                pass

    try:
        read_node['file'].setValue(normalized_output.replace('\\', '/'))
    except Exception:
        pass
    try:
        read_node.setSelected(True)
    except Exception:
        pass
    try:
        read_node.setName("CharonRead")
    except Exception:
        pass
    try:
        read_node.setXY(int(node.xpos()) + 200, int(node.ypos()))
    except Exception:
        try:
            read_node.setXpos(node.xpos() + 200)
            read_node.setYpos(node.ypos())
        except Exception:
            pass

    try:
        read_node.setMetaData('charon/read_id', read_id)
    except Exception:
        pass
    if parent_id:
        try:
            read_node.setMetaData('charon/parent_id', parent_id)
        except Exception:
            pass

    _ensure_hidden_string(read_node, 'charon_read_id', 'Charon Read ID', read_id)
    if parent_id:
        _ensure_hidden_string(read_node, 'charon_parent_id', 'Charon Parent ID', parent_id)

    _assign_read_label(read_node, parent_id, read_id)

    status_value = _safe_knob_value(node, 'charon_status')
    tile_color = status_to_tile_color(status_value or 'Ready')
    gl_color = status_to_gl_color(status_value or 'Ready')
    try:
        read_node['tile_color'].setValue(tile_color)
    except Exception:
        pass
    if gl_color is not None:
        try:
            read_node['gl_color'].setValue(gl_color)
        except Exception:
            try:
                read_node['gl_color'].setValue(list(gl_color))
            except Exception:
                pass

    try:
        node.knob('charon_read_node').setValue(read_node.name())
    except Exception:
        pass
    try:
        node.knob('charon_read_node_id').setValue(read_id)
    except Exception:
        pass
    try:
        info_knob = node.knob('charon_read_id_info')
        if info_knob is not None:
            info_knob.setValue(read_id or "Not linked")
    except Exception:
        pass

    try:
        node.setMetaData('charon/read_node', read_node.name())
    except Exception:
        pass
    try:
        node.setMetaData('charon/read_node_id', read_id)
    except Exception:
        pass

    if recreate_knob is not None:
        try:
            recreate_knob.setEnabled(False)
        except Exception:
            pass
