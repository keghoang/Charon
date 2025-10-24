from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple


class NodeLibraryUnavailable(RuntimeError):
    """Raised when the ComfyUI node registry cannot be imported."""


class NodeTypeNotFound(KeyError):
    """Raised when a requested node type is missing from the registry."""


@dataclass(frozen=True)
class NodeWidgetSpec:
    """Describes a widget-style input exposed by a ComfyUI node."""

    node_type: str
    name: str
    value_type: str
    section: str
    index: int
    default: Any
    choices: Tuple[Any, ...]
    config: Dict[str, Any]


@dataclass(frozen=True)
class NodeWidgetBinding:
    """Maps a widget spec to an actual value on a workflow node."""

    node_id: str
    spec: NodeWidgetSpec
    source: str
    value: Any
    source_index: Optional[int] = None


_WIDGET_TYPE_ALIASES: Dict[str, str] = {
    "INT": "integer",
    "FLOAT": "float",
    "BOOLEAN": "boolean",
    "STRING": "string",
    "NUMBER": "float",
    "SEED": "integer",
    "FILE": "string",
    "PATH": "string",
    "TEXT": "string",
    "VEC2": "float",
    "VEC3": "float",
    "VEC4": "float",
    "COLOR": "string",
}


def _import_nodes_module():
    try:
        import nodes  # type: ignore
    except ImportError as exc:  # pragma: no cover - relies on ComfyUI runtime
        raise NodeLibraryUnavailable(
            "ComfyUI node registry is not available. "
            "Run this helper inside the ComfyUI embedded interpreter."
        ) from exc
    return nodes  # type: ignore


def get_node_widget_specs(node_type: str) -> Tuple[NodeWidgetSpec, ...]:
    """
    Return ordered widget specifications for the given node type.

    This inspects the live ComfyUI node class via ``INPUT_TYPES`` and filters
    out connection-style inputs so only true widget parameters are returned.
    """
    nodes = _import_nodes_module()
    node_class = getattr(nodes, "NODE_CLASS_MAPPINGS", {}).get(node_type)
    if node_class is None:
        raise NodeTypeNotFound(node_type)
    if not hasattr(node_class, "INPUT_TYPES"):
        return tuple()

    input_types = node_class.INPUT_TYPES()
    if not isinstance(input_types, dict):
        return tuple()

    specs: List[NodeWidgetSpec] = []
    index = 0
    for section in ("required", "optional", "hidden"):
        entries = input_types.get(section)
        if not isinstance(entries, dict):
            continue
        for name, raw_spec in entries.items():
            spec = _normalize_widget_spec(node_type, name, raw_spec, section, index)
            if spec is None:
                continue
            specs.append(spec)
            index += 1
    return tuple(specs)


def map_node_widgets(node_id: str, node_data: Dict[str, Any]) -> Tuple[NodeWidgetBinding, ...]:
    """
    Map widget specs to the concrete values present on a workflow node.

    Supports both UI-formatted nodes (``widgets_values`` list) and API-formatted
    nodes (scalar entries living under ``inputs``).
    """
    node_type = node_data.get("type") or node_data.get("class_type")
    if not node_type:
        return tuple()

    try:
        specs = get_node_widget_specs(str(node_type))
    except NodeTypeNotFound:
        return tuple()
    if not specs:
        return tuple()

    bindings: List[NodeWidgetBinding] = []

    widget_values = node_data.get("widgets_values")
    if isinstance(widget_values, list):
        for index, (spec, value) in enumerate(zip(specs, widget_values)):
            bindings.append(
                NodeWidgetBinding(
                    node_id=str(node_id),
                    spec=spec,
                    source="widgets_values",
                    value=value,
                    source_index=index,
                )
            )

    scalar_inputs = _extract_scalar_inputs(node_data)
    if scalar_inputs:
        for spec in specs:
            if spec.name in scalar_inputs:
                bindings.append(
                    NodeWidgetBinding(
                        node_id=str(node_id),
                        spec=spec,
                        source="inputs",
                        value=scalar_inputs[spec.name],
                    )
                )

    return tuple(bindings)


def collect_workflow_widget_bindings(workflow_document: Dict[str, Any]) -> Tuple[NodeWidgetBinding, ...]:
    """
    Walk the workflow document and return bindings for every node that exposes
    widget-style inputs in the active ComfyUI environment.
    """
    bindings: List[NodeWidgetBinding] = []
    for node_id, node_data in _iter_workflow_nodes(workflow_document):
        node_bindings = map_node_widgets(node_id, node_data)
        bindings.extend(node_bindings)
    return tuple(bindings)


def _normalize_widget_spec(
    node_type: str,
    name: str,
    raw_spec: Any,
    section: str,
    index: int,
) -> Optional[NodeWidgetSpec]:
    if not isinstance(raw_spec, tuple) or not raw_spec:
        return None

    raw_type = raw_spec[0]
    config = raw_spec[1] if len(raw_spec) > 1 and isinstance(raw_spec[1], dict) else {}
    value_type: Optional[str]
    choices: Tuple[Any, ...] = tuple()
    default: Any = config.get("default")

    if isinstance(raw_type, (list, tuple)):
        # Enumeration / combo input.
        choices = tuple(raw_type)
        value_type = "string"
        if default is None and choices:
            default = choices[0]
    elif isinstance(raw_type, str):
        normalized = raw_type.strip()
        alias = _WIDGET_TYPE_ALIASES.get(normalized)
        if alias:
            value_type = alias
        elif normalized.upper() != normalized:
            value_type = "string"
        else:
            # Uppercase values typically represent connection sockets.
            return None
    else:
        return None

    return NodeWidgetSpec(
        node_type=node_type,
        name=str(name),
        value_type=value_type or "string",
        section=section,
        index=index,
        default=default,
        choices=choices,
        config=config,
    )


def _iter_workflow_nodes(document: Dict[str, Any]) -> Iterable[Tuple[str, Dict[str, Any]]]:
    if not isinstance(document, dict):
        return

    nodes = document.get("nodes")
    if isinstance(nodes, list):
        for node in nodes:
            if isinstance(node, dict):
                node_id = node.get("id")
                yield str(node_id) if node_id is not None else "", node
        return

    for node_id, node_data in document.items():
        if isinstance(node_data, dict):
            yield str(node_id), node_data


def _extract_scalar_inputs(node_data: Dict[str, Any]) -> Dict[str, Any]:
    inputs = node_data.get("inputs")
    if isinstance(inputs, dict):
        return {k: v for k, v in inputs.items() if _is_scalar(v)}
    return {}


def _is_scalar(value: Any) -> bool:
    return isinstance(value, (str, int, float, bool)) or value is None
