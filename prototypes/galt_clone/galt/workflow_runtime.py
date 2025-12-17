from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import config
from .galt_logger import system_debug, system_warning, system_error
from .metadata_manager import load_workflow_data, get_galt_config
from .utilities import get_current_user_slug
from .workflow_analysis import analyze_ui_workflow_inputs, analyze_workflow_inputs
from .node_factory import create_charon_group_node
from .paths import get_charon_temp_dir
from .workflow_pipeline import convert_workflow as _pipeline_convert_workflow


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


def spawn_charon_node(workflow_bundle: Dict[str, Any], *, nuke_module=None, auto_import=True):
    """Create a CharonOp group node in Nuke using the supplied workflow bundle."""
    if not isinstance(workflow_bundle, dict):
        raise ValueError("workflow_bundle must be a dictionary.")

    workflow = workflow_bundle.get("workflow")
    if not isinstance(workflow, dict):
        raise ValueError("workflow_bundle is missing 'workflow' data.")

    metadata = workflow_bundle.get("metadata") or {}
    folder = workflow_bundle.get("folder") or ""
    workflow_name = metadata.get("charon_meta", {}).get("workflow_file")
    if not workflow_name:
        workflow_name = Path(folder).name or "Workflow"

    workflow_path = workflow_bundle.get("workflow_path")

    if "nodes" in workflow:
        inputs = analyze_ui_workflow_inputs(workflow)
    else:
        inputs = analyze_workflow_inputs(workflow)
    if not inputs:
        inputs = _default_inputs()

    temp_dir = get_charon_temp_dir()
    process_script = _build_processor_script()
    menu_script = _build_menu_script(temp_dir)

    if nuke_module is None:
        try:
            import nuke as _nuke  # type: ignore
        except ImportError as exc:
            raise RuntimeError("Nuke is required to spawn CharonOp nodes.") from exc
        nuke = _nuke
    else:
        nuke = nuke_module

    node, _ = create_charon_group_node(
        nuke=nuke,
        workflow_name=workflow_name,
        workflow_data=workflow,
        inputs=inputs,
        temp_dir=temp_dir,
        process_script=process_script,
        menu_script=menu_script,
        workflow_path=workflow_path,
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


def _build_menu_script(temp_root: str) -> str:
    return f"""# CharonOp Menu Script
import os
import json
import time

def show_info():
    node = nuke.thisNode()
    data = node.knob('workflow_data').value()
    mapping = node.knob('input_mapping').value()
    print('Workflow nodes:', len(json.loads(data)) if data else 0)
    if mapping:
        inputs = json.loads(mapping)
        print('Inputs:')
        for item in inputs:
            print(' -', item.get('name'), ':', item.get('description'))

def monitor_status():
    node = nuke.thisNode()
    payload_raw = None
    try:
        payload_raw = node.metadata('charon/status_payload')
    except Exception:
        payload_raw = None
    if not payload_raw:
        try:
            knob = node.knob('charon_status_payload')
            if knob:
                payload_raw = knob.value()
        except Exception:
            payload_raw = None
    print('Status:', node.knob('charon_status').value())
    if payload_raw:
        try:
            payload = json.loads(payload_raw)
            print('Payload:')
            print(json.dumps(payload, indent=2))
        except Exception:
            print('Payload (raw):', payload_raw)
    else:
        print('Payload: <empty>')
    result_dir = os.path.join({json.dumps(temp_root)}, 'results')
    print('Result files:', os.listdir(result_dir) if os.path.exists(result_dir) else [])

menu = nuke.choice('CharonOp Menu', 'Choose Option', ['Show Workflow Info', 'Monitor Status'])
if menu == 0:
    show_info()
else:
    monitor_status()
"""
