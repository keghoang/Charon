from __future__ import annotations

import os
import json
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
import nuke

def import_output():
    node = nuke.thisNode()
    knob = node.knob('charon_last_output')
    output_path = knob.value().strip() if knob else ''
    if not output_path:
        nuke.message('No output available yet.')
        return

    normalized = os.path.normpath(output_path)
    if not os.path.exists(normalized):
        nuke.message(f'Output file not found: {normalized}')
        return

    read_node = None
    existing_name = ''
    try:
        read_knob = node.knob('charon_read_node')
        if read_knob is not None:
            existing_name = read_knob.value().strip()
    except Exception:
        existing_name = ''

    if existing_name:
        candidate = nuke.toNode(existing_name)
        if candidate is not None and getattr(candidate, 'Class', lambda: '')() == 'Read':
            read_node = candidate

    try:
        if read_node is None:
            parent_group = node.parent() or nuke.root()
            try:
                parent_group.begin()
                read_node = nuke.createNode('Read', inpanel=False)
            finally:
                try:
                    parent_group.end()
                except Exception:
                    pass
            try:
                read_node.setName(f\"{node.name()}_Import\")
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

    try:
        store_knob = node.knob('charon_read_node')
        if store_knob is not None:
            store_knob.setValue(read_node.name())
    except Exception:
        pass
    try:
        node.setMetaData('charon/read_node', read_node.name())
    except Exception:
        pass

import_output()
"""
