from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union


@dataclass(frozen=True)
class NodeWidgetSpec:
    """Describes a widget-style input exposed by a ComfyUI node (API-based)."""

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
    """Maps a widget spec to an actual value on a workflow node (API-based)."""

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

_CONTROL_WIDGET_SENTINELS = {"fixed", "increment", "decrement", "randomize"}


def get_node_widget_specs_from_schema(
    node_type: str,
    object_info: Dict[str, Any]
) -> Tuple[NodeWidgetSpec, ...]:
    """
    Return ordered widget specifications for the given node type using the object_info schema.
    """
    node_def = object_info.get(node_type)
    if not node_def:
        return tuple()

    input_types = node_def.get("input")
    if not isinstance(input_types, dict):
        return tuple()

    specs: List[NodeWidgetSpec] = []
    index = 0
    # The API typically returns "required" and "optional". "hidden" might be there too.
    for section in ("required", "optional", "hidden"):
        entries = input_types.get(section)
        if not isinstance(entries, dict):
            continue
        # In Python 3.7+, dict insertion order is preserved, which matches ComfyUI's definition order.
        for name, raw_spec in entries.items():
            spec = _normalize_widget_spec(node_type, name, raw_spec, section, index)
            if spec is None:
                continue
            specs.append(spec)
            index += 1
    return tuple(specs)


def _normalize_widget_spec(
    node_type: str,
    name: str,
    raw_spec: Any,
    section: str,
    index: int,
) -> Optional[NodeWidgetSpec]:
    # raw_spec is typically ["TYPE", {config}] or ["TYPE"] or ["ENUM", ["a", "b"]]
    if not isinstance(raw_spec, (list, tuple)) or not raw_spec:
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
            # Uppercase values typically represent connection sockets (IMAGE, MODEL, etc.)
            # We don't want to expose these as widgets.
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


def map_node_widgets(
    node_id: str,
    node_data: Dict[str, Any],
    object_info: Dict[str, Any]
) -> Tuple[NodeWidgetBinding, ...]:
    """
    Map widget specs to the concrete values present on a workflow node using schema.
    """
    node_type = node_data.get("type") or node_data.get("class_type")
    if not node_type:
        return tuple()

    specs = get_node_widget_specs_from_schema(str(node_type), object_info)
    if not specs:
        return tuple()

    bindings: List[NodeWidgetBinding] = []

    # 1. Handle widgets_values (Editor format)
    widget_values = node_data.get("widgets_values")
    if isinstance(widget_values, list):
        normalized_values = widget_values
        # Filter control values if the counts mismatch
        if len(widget_values) != len(specs):
             normalized_values = _filter_control_widget_values(widget_values)
        
        # Safety: limit to shortest length
        limit = min(len(specs), len(normalized_values))
        for index in range(limit):
            bindings.append(
                NodeWidgetBinding(
                    node_id=str(node_id),
                    spec=specs[index],
                    source="widgets_values",
                    value=normalized_values[index],
                    source_index=index,
                )
            )

    # 2. Handle inputs (API format or hybrids)
    # In API format, widgets are named in 'inputs'.
    scalar_inputs = _extract_scalar_inputs(node_data)
    if scalar_inputs:
        for spec in specs:
            # If we already found it via widgets_values, skip? 
            # Actually, API format nodes usually don't have widgets_values.
            # If both exist, widgets_values is usually the source of truth for the editor state.
            # But let's check if we missed it.
            
            # Check if we already have a binding for this spec
            already_bound = any(b.spec.name == spec.name for b in bindings)
            if not already_bound and spec.name in scalar_inputs:
                bindings.append(
                    NodeWidgetBinding(
                        node_id=str(node_id),
                        spec=spec,
                        source="inputs",
                        value=scalar_inputs[spec.name],
                    )
                )

    return tuple(bindings)


def collect_workflow_widget_bindings_from_api(
    workflow_document: Dict[str, Any],
    object_info: Dict[str, Any]
) -> Tuple[NodeWidgetBinding, ...]:
    """
    Walk the workflow document and return bindings using the provided object_info schema.
    """
    bindings: List[NodeWidgetBinding] = []
    for node_id, node_data in _iter_workflow_nodes(workflow_document):
        node_bindings = map_node_widgets(node_id, node_data, object_info)
        bindings.extend(node_bindings)
    return tuple(bindings)


def _extract_scalar_inputs(node_data: Dict[str, Any]) -> Dict[str, Any]:
    inputs = node_data.get("inputs")
    if isinstance(inputs, dict):
        return {k: v for k, v in inputs.items() if _is_scalar(v)}
    return {}


def _is_scalar(value: Any) -> bool:
    return isinstance(value, (str, int, float, bool)) or value is None


def _filter_control_widget_values(values: List[Any]) -> List[Any]:
    filtered: List[Any] = []
    total = len(values)
    skip_next = False
    for index, value in enumerate(values):
        if skip_next:
            skip_next = False
            continue
            
        if isinstance(value, str) and value in _CONTROL_WIDGET_SENTINELS:
             continue

        # Look ahead for sentinel
        next_value = values[index + 1] if index + 1 < total else None
        if isinstance(next_value, str) and next_value in _CONTROL_WIDGET_SENTINELS:
            # This value is the seed/value being controlled by the sentinel? 
            # In Comfy, the sentinel usually FOLLOWS the widget it controls (like seed + control_after_generate).
            # Actually, in the list, it's [seed_value, "fixed"].
            # The spec only asks for "seed". So we keep seed_value and drop "fixed".
            filtered.append(value)
            # We don't skip next loop iteration because the next iteration will see the sentinel and drop it.
            continue
            
        filtered.append(value)
    return filtered


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
