from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from .nuke_threading import run_on_main_thread


@dataclass(frozen=True)
class ProcessorRunContext:
    """Main-thread snapshot of Nuke node state needed by worker code."""
    node_x: int
    node_y: int
    parameter_values: Dict[str, Any]


def capture_node_coordinates(
    node,
    *,
    log_warning: Optional[Callable[[str], None]] = None,
) -> tuple[int, int]:
    def _capture() -> tuple[int, int]:
        try:
            return int(node.xpos()), int(node.ypos())
        except Exception as exc:
            if log_warning:
                log_warning(f"Node position unavailable: {exc}")
            return 0, 0

    return run_on_main_thread(_capture)


def resolve_node_auto_import(node) -> bool:
    """Resolve auto-import from the node knob, then metadata, defaulting on."""
    def _resolve() -> bool:
        try:
            knob = node.knob("charon_auto_import")
            if knob is not None:
                try:
                    return bool(int(knob.value()))
                except Exception:
                    return bool(knob.value())
        except Exception:
            pass
        try:
            metadata_value = node.metadata("charon/auto_import")
            if isinstance(metadata_value, str):
                lowered = metadata_value.strip().lower()
                if lowered in {"0", "false", "off", "no"}:
                    return False
                if lowered in {"1", "true", "on", "yes"}:
                    return True
            elif metadata_value is not None:
                return bool(metadata_value)
        except Exception:
            pass
        return True

    return run_on_main_thread(_resolve)


def resolve_batch_count(node) -> int:
    try:
        knob = node.knob("charon_batch_count")
        if knob is not None:
            return max(1, int(knob.value()))
    except Exception:
        pass
    return 1


def resolve_nuke_script_name(nuke_module) -> str:
    """Resolve the active Nuke script basename on the host main thread."""
    def _resolve() -> str:
        try:
            root = nuke_module.root()
        except Exception:
            root = None
        script_reference = ""
        if root is not None:
            try:
                script_reference = root.name()
            except Exception:
                pass
            if not script_reference:
                try:
                    name_knob = root.knob("name")
                    if name_knob is not None:
                        script_reference = str(name_knob.value() or "")
                except Exception:
                    pass
        if not script_reference:
            return "untitled"
        basename = os.path.splitext(os.path.basename(script_reference))[0]
        return basename or "untitled"

    return run_on_main_thread(_resolve)


def resolve_workflow_display_name(node) -> str:
    """Resolve workflow display text from node state with stable fallbacks."""
    try:
        name_knob = node.knob("charon_workflow_name")
        candidate = name_knob.value() if name_knob is not None else ""
    except Exception:
        candidate = ""
    if candidate:
        return str(candidate).strip()
    try:
        metadata_value = node.metadata("charon/workflow_name")
        if isinstance(metadata_value, str) and metadata_value.strip():
            return metadata_value.strip()
    except Exception:
        pass
    try:
        path_knob = node.knob("workflow_path")
        path_value = path_knob.value() if path_knob is not None else ""
    except Exception:
        path_value = ""
    if path_value:
        basename = os.path.basename(str(path_value).strip())
        if basename:
            return basename.rsplit(".", 1)[0]
    return "Workflow"


def capture_processor_run_context(
    node,
    parameter_specs: Optional[List[Dict[str, Any]]] = None,
    *,
    log_warning: Optional[Callable[[str], None]] = None,
) -> ProcessorRunContext:
    """Capture node coordinates and parameter knob values on the Nuke main thread."""
    def _warn(message: str) -> None:
        if log_warning:
            log_warning(message)

    def _capture() -> ProcessorRunContext:
        try:
            node_x, node_y = int(node.xpos()), int(node.ypos())
        except Exception as exc:
            _warn(f"Node position unavailable: {exc}")
            node_x, node_y = 0, 0

        values: Dict[str, Any] = {}
        for spec in parameter_specs or []:
            if not isinstance(spec, dict):
                continue
            knob_name = spec.get("knob")
            if not knob_name or knob_name in values:
                continue
            try:
                knob = node.knob(knob_name)
                if knob is not None:
                    values[knob_name] = knob.value()
            except Exception as exc:
                _warn(f"Failed to capture knob {knob_name}: {exc}")
        return ProcessorRunContext(node_x=node_x, node_y=node_y, parameter_values=values)

    return run_on_main_thread(_capture)
