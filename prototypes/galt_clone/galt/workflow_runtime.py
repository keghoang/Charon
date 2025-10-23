from __future__ import annotations

import os
import json
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import config
from . import preferences
from .galt_logger import system_debug, system_warning, system_error
from .metadata_manager import load_workflow_data, get_galt_config
from .utilities import get_current_user_slug
from .workflow_analysis import analyze_ui_workflow_inputs, analyze_workflow_inputs
from .node_factory import create_charon_group_node
from .paths import get_charon_temp_dir
from .workflow_pipeline import convert_workflow as _pipeline_convert_workflow
from .utilities import status_to_tile_color


# NOTE:
# This module intentionally stays headless and free of Qt dependencies.
# It centralizes discovery/loading/conversion so both UI layers and processor
# scripts can reuse the same helpers. Avoid importing PySide modules here.

__all__ = [
    "discover_workflows",
    "load_workflow_bundle",
    "convert_workflow",
    "spawn_charon_node",
]


def _resolve_root(base_path: Optional[str] = None) -> str:
    """Return the absolute workflow root and ensure it exists on disk."""
    root = os.path.abspath(base_path or config.WORKFLOW_REPOSITORY_ROOT)
    if not os.path.exists(root):
        system_warning(f"Workflow repository does not exist: {root}")
    return root


def discover_workflows(base_path: Optional[str] = None) -> List[Tuple[str, str, Optional[Dict[str, Any]]]]:
    """
    Return a list of (folder_name, folder_path, metadata) for each workflow directory.
    Ensures the current user's folder exists so the UI always sees it, even if empty.
    """
    root = _resolve_root(base_path)
    results: List[Tuple[str, str, Optional[Dict[str, Any]]]] = []

    if not os.path.isdir(root):
        return results

    user_slug = get_current_user_slug()
    user_folder = os.path.join(root, user_slug)
    if not os.path.isdir(user_folder):
        try:
            os.makedirs(user_folder, exist_ok=True)
            system_debug(f"Created workflow folder for user: {user_folder}")
        except Exception as exc:
            system_error(f"Could not create workflow folder {user_folder}: {exc}")

    try:
        entries = sorted(
            entry for entry in os.listdir(root)
            if os.path.isdir(os.path.join(root, entry))
        )
    except OSError as exc:
        system_error(f"Failed to enumerate workflow directories in {root}: {exc}")
        return results

    for entry in entries:
        folder_path = os.path.join(root, entry)
        metadata = get_galt_config(folder_path)
        results.append((entry, folder_path, metadata))

    return results


def load_workflow_bundle(folder_path: str) -> Dict[str, Any]:
    """
    Load `.charon.json` metadata and `workflow.json` payload for the given folder.
    Raises ValueError if the folder is outside the configured repository.
    """
    if not folder_path:
        raise ValueError("Workflow folder path is required.")

    root = _resolve_root()
    folder_abs = os.path.abspath(folder_path)
    if not folder_abs.lower().startswith(os.path.abspath(root).lower()):
        raise ValueError(f"Workflow path {folder_abs} is outside the Charon repository.")

    bundle = load_workflow_data(folder_abs)
    system_debug(f"Loaded workflow bundle: {bundle.get('workflow_file')} from {folder_abs}")
    return bundle


def convert_workflow(ui_workflow: Dict[str, Any], comfy_path: str) -> Dict[str, Any]:
    """
    Convert a UI workflow into API format using the existing external pipeline.
    Raises RuntimeError on conversion failure.
    """
    if not isinstance(ui_workflow, dict):
        raise ValueError("Workflow payload must be a dictionary.")
    if not comfy_path:
        raise ValueError("A valid ComfyUI path is required for conversion.")
    if not os.path.exists(comfy_path):
        raise ValueError(f"ComfyUI path does not exist: {comfy_path}")

    system_debug(f"Starting workflow conversion using ComfyUI at {comfy_path}")
    try:
        converted = _pipeline_convert_workflow(ui_workflow, comfy_path=comfy_path)
    except Exception as exc:
        system_error(f"Workflow conversion failed: {exc}")
        raise

    if not isinstance(converted, dict):
        raise RuntimeError("Conversion did not return a workflow dictionary.")

    system_debug(f"Workflow conversion succeeded (nodes: {len(converted)})")
    return converted


def spawn_charon_node(
    workflow_bundle: Dict[str, Any],
    *,
    nuke_module=None,
    auto_import: Optional[bool] = None,
):
    """Create a CharonOp group node in Nuke using the supplied workflow bundle."""
    if not isinstance(workflow_bundle, dict):
        raise ValueError("workflow_bundle must be a dictionary.")

    workflow = workflow_bundle.get("workflow")
    if not isinstance(workflow, dict):
        raise ValueError("workflow_bundle is missing 'workflow' data.")

    metadata = workflow_bundle.get("metadata") or {}
    folder = workflow_bundle.get("folder") or ""
    workflow_name = Path(folder).name or ""
    if not workflow_name:
        workflow_name = metadata.get("charon_meta", {}).get("workflow_file") or "Workflow"

    workflow_path = workflow_bundle.get("workflow_path")

    if "nodes" in workflow:
        inputs = analyze_ui_workflow_inputs(workflow)
    else:
        inputs = analyze_workflow_inputs(workflow)
    if not inputs:
        inputs = _default_inputs()

    temp_dir = get_charon_temp_dir()
    process_script = _build_processor_script()
    import_script = _build_import_output_script()

    charon_meta = metadata.get("charon_meta") or {}
    raw_parameters = (
        charon_meta.get("parameters")
        or metadata.get("parameters")
        or []
    )
    parameter_specs = [
        dict(spec) for spec in raw_parameters if isinstance(spec, dict)
    ]

    if nuke_module is None:
        try:
            import nuke as _nuke  # type: ignore
        except ImportError as exc:
            raise RuntimeError("Nuke is required to spawn CharonOp nodes.") from exc
        nuke = _nuke
    else:
        nuke = nuke_module

    if auto_import is None:
        auto_import = preferences.get_auto_import_default()

    node, _ = create_charon_group_node(
        nuke=nuke,
        workflow_name=workflow_name,
        workflow_data=workflow,
        inputs=inputs,
        temp_dir=temp_dir,
        process_script=process_script,
        import_script=import_script,
        workflow_path=workflow_path,
        parameters=parameter_specs,
        auto_import_default=auto_import,
    )

    try:
        node.knob("charon_auto_import").setValue(1 if auto_import else 0)
    except Exception:
        pass

    return node


def _default_inputs() -> List[Dict[str, Any]]:
    return [
        {
            "name": "Primary Image",
            "type": "image",
            "node_id": "primary",
            "description": "Main input image",
            "source": "default",
        }
    ]


def _build_processor_script() -> str:
    return (
        "try:\n"
        "    from prototypes.galt_clone.galt.processor import process_charonop_node\n"
        "except Exception as exc:\n"
        "    import nuke\n"
        "    nuke.message(f'Charon processor unavailable: {exc}')\n"
        "else:\n"
        "    process_charonop_node()\n"
    )


def _build_import_output_script() -> str:
    return """# CharonOp Import Output
import os
import uuid
import nuke

def _normalize_id(value):
    try:
        text = str(value).strip().lower()
    except Exception:
        return ''
    if not text:
        return ''
    return text[:12]

def _safe_knob_value(owner, name):
    try:
        knob = owner.knob(name)
    except Exception:
        return ''
    if knob is None:
        return ''
    try:
        return knob.value()
    except Exception:
        return ''

def _read_node_parent_id(read_node):
    try:
        meta_val = read_node.metadata('charon/parent_id')
    except Exception:
        meta_val = None
    parent = _normalize_id(meta_val)
    if not parent:
        parent = _normalize_id(_safe_knob_value(read_node, 'charon_parent_id'))
    return parent

def _read_node_unique_id(read_node):
    try:
        meta_val = read_node.metadata('charon/read_id')
    except Exception:
        meta_val = None
    read_id = _normalize_id(meta_val)
    if not read_id:
        read_id = _normalize_id(_safe_knob_value(read_node, 'charon_read_id'))
    return read_id

def _ensure_hidden_string(read_node, name, label):
    try:
        knob = read_node.knob(name)
    except Exception:
        knob = None
    if knob is None:
        try:
            knob = nuke.String_Knob(name, label, '')
            knob.setFlag(nuke.NO_ANIMATION)
            knob.setFlag(nuke.INVISIBLE)
            read_node.addKnob(knob)
        except Exception:
            knob = None
    return knob

def _ensure_info_tab(read_node, parent_id, read_id):
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
    summary = [
        f"Parent ID: {parent_id or 'N/A'}",
        f"Read Node ID: {read_id or 'N/A'}",
    ]
    if info_text is not None:
        try:
            info_text.setValue("\\n".join(summary))
        except Exception:
            pass

def _assign_read_label(read_node, parent_id, read_id):
    try:
        label_knob = read_node['label']
    except Exception:
        label_knob = None
    if label_knob is not None:
        label = f"Charon Parent: {parent_id or 'N/A'}\\nRead ID: {read_id or 'N/A'}"
        try:
            label_knob.setValue(label)
        except Exception:
            pass

def _find_read_node_by_id(read_id):
    if not read_id:
        return None
    try:
        candidates = nuke.allNodes('Read')
    except Exception:
        return None
    for candidate in candidates:
        if _read_node_unique_id(candidate) == read_id:
            return candidate
    return None

def _find_read_node_by_parent(parent_id):
    if not parent_id:
        return None
    try:
        candidates = nuke.allNodes('Read')
    except Exception:
        return None
    for candidate in candidates:
        if _read_node_parent_id(candidate) == parent_id:
            return candidate
    return None

def _sanitize_name(value, default='Workflow'):
    text = str(value).strip() if value else ''
    if not text:
        text = default
    sanitized = ''.join(c if c.isalnum() or c in {'_', '-'} else '_' for c in text)
    sanitized = sanitized.strip('_') or default
    return sanitized[:64]

def _resolve_workflow_name(node):
    candidate = _safe_knob_value(node, 'charon_workflow_name')
    if candidate:
        return candidate
    try:
        meta_val = node.metadata('charon/workflow_name')
        if isinstance(meta_val, str) and meta_val.strip():
            return meta_val
    except Exception:
        pass
    path_candidate = _safe_knob_value(node, 'workflow_path')
    if path_candidate:
        base = os.path.basename(path_candidate.strip())
        if base:
            return base.rsplit('.', 1)[0]
    return 'Workflow'

def import_output():
    node = nuke.thisNode()

    parent_id = _normalize_id(_safe_knob_value(node, 'charon_node_id'))
    if not parent_id:
        try:
            parent_id = _normalize_id(node.metadata('charon/node_id'))
        except Exception:
            parent_id = ''

    stored_read_id = _normalize_id(_safe_knob_value(node, 'charon_read_node_id'))
    if not stored_read_id:
        try:
            stored_read_id = _normalize_id(node.metadata('charon/read_node_id'))
        except Exception:
            stored_read_id = ''

    status_state = 'Ready'
    try:
        payload_raw = node.metadata('charon/status_payload')
    except Exception:
        payload_raw = None
    if payload_raw:
        try:
            payload_data = json.loads(payload_raw)
        except Exception:
            payload_data = None
        if isinstance(payload_data, dict):
            status_state = payload_data.get('state') or payload_data.get('status') or status_state

    knob = node.knob('charon_last_output')
    output_path = knob.value().strip() if knob else ''
    if not output_path:
        nuke.message('No output available yet.')
        return

    normalized = os.path.normpath(output_path)
    if not os.path.exists(normalized):
        nuke.message(f'Output file not found: {normalized}')
        return

    read_node = _find_read_node_by_id(stored_read_id)
    if read_node is None:
        read_node = _find_read_node_by_parent(parent_id)

    if read_node is None:
        existing_name = _safe_knob_value(node, 'charon_read_node').strip()
        if existing_name:
            try:
                candidate = nuke.toNode(existing_name)
            except Exception:
                candidate = None
            if candidate is not None and getattr(candidate, 'Class', lambda: '')() == 'Read':
                read_node = candidate

    if read_node is None:
        try:
            parent_group = node.parent() or nuke.root()
            try:
                parent_group.begin()
                read_node = nuke.createNode('Read', inpanel=False)
            finally:
                try:
                    parent_group.end()
                except Exception:
                    pass
            read_base = _sanitize_name(_resolve_workflow_name(node))
            target_read_name = f"CharonRead_{read_base}"
            try:
                read_node.setName(target_read_name)
            except Exception:
                try:
                    read_node.setName(f"CharonRead_{read_base}_{parent_id}")
                except Exception:
                    try:
                        read_node.setName("CharonRead")
                    except Exception:
                        pass
        except Exception as exc:
            nuke.message(f'Failed to create Read node: {exc}')
            return

    try:
        read_node['file'].setValue(normalized)
    except Exception:
        nuke.message(f'Could not assign output path to Read node: {normalized}')
        return

    read_node.setXpos(node.xpos())
    read_node.setYpos(node.ypos() + 60)
    read_node.setSelected(True)

    read_id = _read_node_unique_id(read_node)
    if not read_id:
        read_id = uuid.uuid4().hex[:12].lower()

    try:
        read_node.setMetaData('charon/read_id', read_id)
    except Exception:
        pass
    try:
        read_node.setMetaData('charon/parent_id', parent_id)
    except Exception:
        pass

    parent_knob = _ensure_hidden_string(read_node, 'charon_parent_id', 'Charon Parent ID')
    if parent_knob is not None:
        try:
            parent_knob.setValue(parent_id)
        except Exception:
            pass
    read_id_knob = _ensure_hidden_string(read_node, 'charon_read_id', 'Charon Read ID')
    if read_id_knob is not None:
        try:
            read_id_knob.setValue(read_id)
        except Exception:
            pass

    _ensure_info_tab(read_node, parent_id, read_id)
    _assign_read_label(read_node, parent_id, read_id)

    tile_color = status_to_tile_color(status_state)
    try:
        node["tile_color"].setValue(tile_color)
    except Exception:
        pass
    try:
        read_node["tile_color"].setValue(tile_color)
    except Exception:
        pass
    try:
        read_node["gl_color"].setValue(tile_color)
    except Exception:
        pass

    try:
        anchor_knob = node.knob('charon_link_anchor')
        anchor_value = anchor_knob.value() if anchor_knob else 0.0
    except Exception:
        anchor_value = 0.0
    try:
        read_anchor = read_node.knob('charon_link_anchor')
    except Exception:
        read_anchor = None
    if read_anchor is None:
        try:
            read_anchor = nuke.Double_Knob('charon_link_anchor', 'Charon Link Anchor')
            read_anchor.setFlag(nuke.NO_ANIMATION)
            read_anchor.setFlag(nuke.INVISIBLE)
            read_node.addKnob(read_anchor)
        except Exception:
            read_anchor = None
    if read_anchor is not None:
        try:
            read_anchor.setExpression(f"{node.fullName()}.charon_link_anchor")
        except Exception:
            try:
                read_anchor.clearAnimated()
            except Exception:
                pass
            try:
                read_anchor.setValue(anchor_value)
            except Exception:
                pass

    try:
        store_knob = node.knob('charon_read_node')
        if store_knob is not None:
            store_knob.setValue(read_node.name())
    except Exception:
        pass
    try:
        read_id_store = node.knob('charon_read_node_id')
        if read_id_store is not None:
            read_id_store.setValue(read_id)
    except Exception:
        pass
    try:
        info_knob = node.knob('charon_read_id_info')
        if info_knob is not None:
            info_knob.setValue(read_id)
    except Exception:
        pass

    try:
        node.setMetaData('charon/read_node', read_node.name())
        node.setMetaData('charon/read_node_id', read_id)
    except Exception:
        pass

import_output()
"""
