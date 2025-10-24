from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple


@dataclass(frozen=True)
class ExposableAttribute:
    """Individual attribute candidate discovered on a workflow node."""

    key: str
    label: str
    value: Any
    value_type: str
    preview: str


@dataclass(frozen=True)
class ExposableNode:
    """Workflow node that exposes one or more prompt-style attributes."""

    node_id: str
    name: str
    attributes: Tuple[ExposableAttribute, ...]


class WorkflowLoadError(Exception):
    """Raised when a workflow JSON document cannot be loaded."""


def load_workflow_document(path: str) -> Dict[str, Any]:
    """
    Load and return workflow JSON content from disk.

    Args:
        path: Absolute path to the workflow JSON file.

    Returns:
        Parsed JSON document.

    Raises:
        WorkflowLoadError: When the file does not exist or contains invalid JSON.
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:  # pragma: no cover - depends on disk state
        raise WorkflowLoadError(f"Workflow file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise WorkflowLoadError(f"Workflow JSON is invalid: {exc}") from exc
    except OSError as exc:  # pragma: no cover - environment specific
        raise WorkflowLoadError(f"Could not read workflow file: {exc}") from exc


def discover_prompt_widget_parameters(
    workflow_document: Dict[str, Any],
) -> Tuple[ExposableNode, ...]:
    """
    Return a tuple of nodes containing prompt-style widget values that may be exposed.

    The current heuristic targets nodes whose title includes "Prompt" (case-insensitive)
    and scans their ``widgets_values`` list for string entries.

    Args:
        workflow_document: Parsed workflow JSON content.

    Returns:
        Tuple of :class:`ExposableNode` entries. Empty when nothing matches.
    """

    candidates: List[ExposableNode] = []
    for node_id, node_data in _iter_workflow_nodes(workflow_document):
        widgets_values = node_data.get("widgets_values")
        if not isinstance(widgets_values, list):
            continue

        attributes: List[ExposableAttribute] = []
        for index, value in enumerate(widgets_values):
            if not isinstance(value, str):
                continue
            if not value.strip():
                continue

            value_type = _infer_value_type(value)
            key = f"widgets_values[{index}]"
            attributes.append(
                ExposableAttribute(
                    key=key,
                    label=key,
                    value=value,
                    value_type=value_type,
                    preview=_format_attribute_preview(value),
                )
            )

        if attributes:
            title = node_data.get("title")
            type_name = node_data.get("type") or node_data.get("class_type")
            node_name = (title or type_name or "").strip() or f"Node {node_id}"
            candidates.append(
                ExposableNode(
                    node_id=node_id,
                    name=node_name,
                    attributes=tuple(attributes),
                )
            )

    return tuple(candidates)


def _infer_value_type(value: Any) -> str:
    """Return a simple type identifier for the provided value."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) and not isinstance(value, bool):
        return "integer"
    if isinstance(value, float):
        return "float"
    return "string"


def _format_attribute_preview(value: Any) -> str:
    """Generate a tooltip-friendly string describing the widget value."""
    if isinstance(value, str):
        return value.strip()
    if value is None:
        return ""
    return str(value)


def _iter_workflow_nodes(
    document: Dict[str, Any]
) -> Iterable[Tuple[str, Dict[str, Any]]]:
    """
    Yield ``(node_id, node_data)`` pairs from either ComfyUI editor documents (list-based)
    or API-formatted dictionaries.
    """
    if not isinstance(document, dict):
        return []

    nodes_section = document.get("nodes")
    if isinstance(nodes_section, list):
        for node in nodes_section:
            if isinstance(node, dict):
                node_id = node.get("id")
                yield str(node_id) if node_id is not None else "", node
        return []

    for node_id, node in document.items():
        if isinstance(node, dict):
            yield str(node_id), node
