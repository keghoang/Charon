from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from .nuke_threading import run_on_main_thread


@dataclass(frozen=True)
class ProcessorRunContext:
    """Main-thread snapshot of Nuke node state needed by worker code."""
    node_x: int
    node_y: int
    parameter_values: Dict[str, Any]


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
