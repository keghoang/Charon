from __future__ import annotations

import os
import json
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import config
from .charon_logger import system_debug, system_warning, system_error
from .metadata_manager import load_workflow_data, get_charon_config
from .utilities import get_current_user_slug
from .workflow_analysis import analyze_ui_workflow_inputs, analyze_workflow_inputs
from .node_factory import create_charon_group_node
from .paths import get_charon_temp_dir
from .workflow_pipeline import convert_workflow as _pipeline_convert_workflow
from .utilities import status_to_gl_color, status_to_tile_color


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

# Cache for workflow metadata: folder_path -> (mtime_of_config, metadata)
_WORKFLOW_CACHE: Dict[str, Tuple[float, Optional[Dict[str, Any]]]] = {}


def _resolve_root(base_path: Optional[str] = None) -> str:
    """Return the absolute workflow root and ensure it exists on disk."""
    root = os.path.abspath(base_path or config.WORKFLOW_REPOSITORY_ROOT)
    if not os.path.exists(root):
        system_warning(f"Workflow repository does not exist: {root}")
    return root


def discover_workflows(base_path: Optional[str] = None) -> List[Tuple[str, str, Optional[Dict[str, Any]]]]:
    """
    Return a list of (folder_name, folder_path, metadata) for each workflow directory.
    """
    root = _resolve_root(base_path)
    results: List[Tuple[str, str, Optional[Dict[str, Any]]]] = []

    if not os.path.isdir(root):
        return results

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
        
        # Cache optimization: Check .charon.json mtime to avoid re-parsing unchanged files
        config_path = os.path.join(folder_path, '.charon.json')
        current_mtime = 0.0
        if os.path.exists(config_path):
            try:
                current_mtime = os.path.getmtime(config_path)
            except OSError:
                pass
        
        cached = _WORKFLOW_CACHE.get(folder_path)
        if cached and cached[0] == current_mtime:
            metadata = cached[1]
        else:
            metadata = get_charon_config(folder_path)
            _WORKFLOW_CACHE[folder_path] = (current_mtime, metadata)
            
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
    source_workflow_path = workflow_bundle.get("source_workflow_path")
    local_state = workflow_bundle.get("local_state") or {}
    is_validated = bool(workflow_bundle.get("validated"))

    if "nodes" in workflow:
        inputs = analyze_ui_workflow_inputs(workflow)
        has_load_nodes = _workflow_has_load_nodes_ui(workflow)
    else:
        inputs = analyze_workflow_inputs(workflow)
        has_load_nodes = _workflow_has_load_nodes_api(workflow)

    if not inputs and not has_load_nodes:
        inputs = []
    elif not inputs and has_load_nodes:
        inputs = _default_inputs()

    temp_dir = get_charon_temp_dir()
    process_script = _build_processor_script()
    recreate_script = _build_recreate_read_script()

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

    auto_import = True

    node, _ = create_charon_group_node(
        nuke=nuke,
        workflow_name=workflow_name,
        workflow_data=workflow,
        inputs=inputs,
        temp_dir=temp_dir,
        process_script=process_script,
        recreate_script=recreate_script,
        workflow_path=workflow_path,
        parameters=parameter_specs,
        source_workflow_path=source_workflow_path,
        validated=is_validated,
        local_state=local_state,
    )

    try:
        node.knob("charon_auto_import").setValue(1)
    except Exception:
        pass

    if metadata.get('is_3d_texturing_step2') or charon_meta.get('is_3d_texturing_step2'):
        try:
            footer_knob = nuke.Text_Knob("charon_step2_footer", "", "<b>3D Texturing - Step 2</b>")
            node.addKnob(footer_knob)
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


def _workflow_has_load_nodes_ui(ui_workflow: Dict[str, Any]) -> bool:
    """Return True if the UI workflow declares any load-image style nodes."""
    if not isinstance(ui_workflow, dict):
        return False
    nodes = ui_workflow.get("nodes") or []
    for node in nodes:
        node_type = str(node.get("type") or "").strip()
        if node_type in {"LoadImage", "LoadImageMask", "LoadImageBuiltin", "LoadImageFromBase64", "LoadImageFromURL"}:
            return True
    return False


def _workflow_has_load_nodes_api(api_workflow: Dict[str, Any]) -> bool:
    """Return True if the API workflow declares any load-image style nodes."""
    if not isinstance(api_workflow, dict):
        return False
    for node_data in api_workflow.values():
        if not isinstance(node_data, dict):
            continue
        class_type = str(node_data.get("class_type") or "").strip()
        if class_type in {"LoadImage", "LoadImageMask", "LoadImageBuiltin", "LoadImageFromBase64", "LoadImageFromURL"}:
            return True
    return False


def _build_processor_script() -> str:
    return (
        "try:\n"
        "    from charon.processor import process_charonop_node\n"
        "except Exception as exc:\n"
        "    import nuke\n"
        "    nuke.message('Charon processor unavailable: {0}'.format(exc))\n"
        "else:\n"
        "    process_charonop_node()\n"
    )


def _build_recreate_read_script() -> str:
    return """# CharonOp Create Contact Sheet
try:
    from charon.processor import create_contact_sheet_from_charonop
except Exception as exc:
    import nuke
    nuke.message('Charon processor unavailable: {0}'.format(exc))
else:
    create_contact_sheet_from_charonop()
"""