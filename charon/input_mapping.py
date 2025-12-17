from __future__ import annotations

import json
import os
import subprocess
import tempfile
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import preferences, paths
from .node_introspection import (
    NodeLibraryUnavailable,
    collect_workflow_widget_bindings,
)


@dataclass(frozen=True)
class ExposableAttribute:
    """Individual attribute candidate discovered on a workflow node."""

    key: str
    label: str
    value: Any
    value_type: str
    preview: str
    aliases: Tuple[str, ...] = field(default_factory=tuple)
    node_default: Any = None


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

    Preference is given to ComfyUI's live node definitions when available so parameter
    names and types remain deterministic. When the node library cannot be reached, the
    function falls back to scanning ``widgets_values`` for simple scalar values.

    Args:
        workflow_document: Parsed workflow JSON content.

    Returns:
        Tuple of :class:`ExposableNode` entries. Empty when nothing matches.
    """

    resolved = _discover_with_node_library(workflow_document)
    if resolved:
        return resolved

    resolved = _discover_with_external_process(workflow_document)
    if resolved:
        return resolved

    return _discover_with_widget_heuristic(workflow_document)


def _discover_with_node_library(
    workflow_document: Dict[str, Any]
) -> Tuple[ExposableNode, ...]:
    try:
        bindings = collect_workflow_widget_bindings(workflow_document)
    except NodeLibraryUnavailable:
        return tuple()
    except Exception:
        # Any unexpected error should fall back to the legacy heuristic.
        return tuple()

    if not bindings:
        return tuple()

    node_lookup: Dict[str, Dict[str, Any]] = {
        node_id: node_data for node_id, node_data in _iter_workflow_nodes(workflow_document)
    }
    aggregated: Dict[str, Dict[str, Any]] = {}

    for binding in bindings:
        spec = binding.spec
        key = (spec.name or "").strip()
        if not key:
            continue

        entry = aggregated.setdefault(
            binding.node_id,
            {"attributes": OrderedDict(), "node_type": spec.node_type},
        )
        attributes: OrderedDict[str, ExposableAttribute] = entry["attributes"]
        if key in attributes:
            continue

        aliases: Tuple[str, ...] = ()
        if binding.source == "widgets_values" and binding.source_index is not None:
            aliases = (f"widgets_values[{binding.source_index}]",)

        value_type = spec.value_type or "string"
        label = _format_binding_label(spec.name, value_type)
        attributes[key] = ExposableAttribute(
            key=key,
            label=label,
            value=binding.value,
            value_type=value_type,
            preview=_format_attribute_preview(binding.value),
            aliases=aliases,
            node_default=spec.default,
        )

    nodes: List[ExposableNode] = []
    for node_id, entry in aggregated.items():
        attr_map = entry.get("attributes")
        if not attr_map:
            continue
        node_data = node_lookup.get(node_id) or {}
        node_name = _resolve_node_name(node_id, node_data, entry.get("node_type"))
        nodes.append(
            ExposableNode(
                node_id=node_id,
                name=node_name,
                attributes=tuple(attr_map.values()),
            )
        )

    nodes.sort(key=lambda item: item.name.lower())
    return tuple(nodes)


def _format_binding_label(name: str, value_type: str) -> str:
    if not name:
        return value_type or "Value"
    display = name
    if "_" in name and name.islower():
        display = name.replace("_", " ").title()
    if value_type:
        return f"{display} ({value_type})"
    return display


def _discover_with_external_process(
    workflow_document: Dict[str, Any]
) -> Tuple[ExposableNode, ...]:
    comfy_path = preferences.get_preference("comfyui_launch_path", "") or paths.get_default_comfy_launch_path()
    if not comfy_path:
        return tuple()

    env_info = paths.resolve_comfy_environment(comfy_path)
    python_exe = env_info.get("python_exe")
    comfy_dir = env_info.get("comfy_dir")
    if not python_exe or not comfy_dir or not os.path.exists(python_exe):
        return tuple()

    script_path = Path(__file__).resolve().parents[1] / "tools" / "inspect_workflow_widgets.py"
    if not script_path.exists():
        return tuple()

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
        json.dump(workflow_document, handle)
        temp_input = handle.name

    repo_root = Path(__file__).resolve().parents[1]
    extra_paths = [str(comfy_dir), str(repo_root)]
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [existing, *extra_paths]))

    command = [python_exe, str(script_path), "--json", temp_input]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            cwd=str(repo_root),
            env=env,
            check=False,
        )
    finally:
        try:
            os.remove(temp_input)
        except OSError:
            pass

    if result.returncode != 0:
        return tuple()

    stdout = (result.stdout or "").strip()
    if not stdout:
        return tuple()

    payload = None
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        for line in reversed(stdout.splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
    if not isinstance(payload, list):
        return tuple()

    node_lookup: Dict[str, Dict[str, Any]] = {
        node_id: node_data for node_id, node_data in _iter_workflow_nodes(workflow_document)
    }
    aggregated: Dict[str, Dict[str, Any]] = {}

    for entry in payload:
        if not isinstance(entry, dict):
            continue
        node_id = str(entry.get("node_id") or "")
        key = str(entry.get("name") or "").strip()
        if not node_id or not key:
            continue

        value_type = str(entry.get("value_type") or "string")
        entry_bucket = aggregated.setdefault(
            node_id,
            {"attributes": OrderedDict(), "node_type": entry.get("node_type")},
        )
        attributes: OrderedDict[str, ExposableAttribute] = entry_bucket["attributes"]
        if key in attributes:
            continue

        aliases: Tuple[str, ...] = ()
        source = entry.get("source")
        source_index = entry.get("source_index")
        if source == "widgets_values" and isinstance(source_index, int):
            aliases = (f"widgets_values[{source_index}]",)

        label = _format_binding_label(key, value_type)
        attributes[key] = ExposableAttribute(
            key=key,
            label=label,
            value=entry.get("value"),
            value_type=value_type,
            preview=_format_attribute_preview(entry.get("value")),
            aliases=aliases,
            node_default=entry.get("default"),
        )

    nodes: List[ExposableNode] = []
    for node_id, entry in aggregated.items():
        attr_map = entry.get("attributes")
        if not attr_map:
            continue
        node_data = node_lookup.get(node_id) or {}
        node_name = _resolve_node_name(node_id, node_data, entry.get("node_type"))
        nodes.append(
            ExposableNode(
                node_id=node_id,
                name=node_name,
                attributes=tuple(attr_map.values()),
            )
        )

    nodes.sort(key=lambda item: item.name.lower())
    return tuple(nodes)


def _discover_with_widget_heuristic(
    workflow_document: Dict[str, Any]
) -> Tuple[ExposableNode, ...]:
    candidates: List[ExposableNode] = []
    for node_id, node_data in _iter_workflow_nodes(workflow_document):
        widgets_values = node_data.get("widgets_values")
        if not isinstance(widgets_values, list):
            continue

        attributes: List[ExposableAttribute] = []
        for index, value in enumerate(widgets_values):
            if not _is_supported_widget_value(value):
                continue
            if isinstance(value, str) and not value.strip():
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
            node_name = _resolve_node_name(node_id, node_data, node_data.get("type") or node_data.get("class_type"))
            candidates.append(
                ExposableNode(
                    node_id=node_id,
                    name=node_name,
                    attributes=tuple(attributes),
                )
            )

    return tuple(candidates)


def _resolve_node_name(node_id: str, node_data: Dict[str, Any], node_type_hint: Any) -> str:
    title = node_data.get("title") or node_data.get("name")
    if isinstance(title, str) and title.strip():
        return title.strip()

    type_name = node_data.get("type") or node_data.get("class_type") or node_type_hint
    if isinstance(type_name, str) and type_name.strip():
        return type_name.strip()

    return f"Node {node_id}"


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


def _is_supported_widget_value(value: Any) -> bool:
    """Return True when the widget value can be exposed to the user."""
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        return True
    return False


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
