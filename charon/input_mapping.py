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
from .api_introspection import collect_workflow_widget_bindings_from_api
from .comfy_client import ComfyUIClient
from .charon_logger import system_debug, system_error

_OBJECT_INFO_CACHE_FILE = "object_info_cache.json"


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
    choices: Tuple[Any, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ExposableNode:
    """Workflow node that exposes one or more prompt-style attributes."""

    node_id: str
    name: str
    attributes: Tuple[ExposableAttribute, ...]


def _filter_prompt_nodes(nodes: Iterable[ExposableNode]) -> Tuple[ExposableNode, ...]:
    """Filter out nodes that should not be exposed to the user."""
    filtered: List[ExposableNode] = []
    for node in nodes or ():
        name = (node.name or "").strip().lower()
        normalized = name.replace(" ", "")
        if normalized.startswith("loadimage") or normalized.startswith("saveimage"):
            continue
        if name.startswith("load image") or name.startswith("save image"):
            continue
        filtered.append(node)
    return tuple(filtered)


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
    """
    collected: Dict[str, ExposableNode] = {}
    
    # Priorities:
    # 1. ComfyUI API (Fastest if running, accurate)
    # 2. Playwright Inspection (Slower, launches headless ComfyUI, accurate)
    # 3. Node Library (Only if embedded Python, accurate)
    # 4. Heuristic (Fast, inaccurate names)
    
    # Note: _discover_with_comfy_api handles local caching of object_info.
    
    resolvers = [
        _discover_with_comfy_api,
        _discover_with_playwright, # Robust fallback if API fails (e.g. server closed)
        _discover_with_node_library,
        _discover_with_widget_heuristic,
    ]
    
    for resolver in resolvers:
        try:
            system_debug(f"Attempting parameter discovery with {resolver.__name__}...")
            results = resolver(workflow_document)
            filtered_results = _filter_prompt_nodes(results)
            
            count = 0
            for node in filtered_results:
                if node.node_id in collected:
                    continue
                collected[node.node_id] = node
                count += 1
            
            if count > 0:
                system_debug(f"Resolver {resolver.__name__} found {count} new nodes.")

            # If we found nodes via API/Playwright/Library, we can stop. 
            # Heuristics are only for total failure.
            if collected and resolver != _discover_with_widget_heuristic:
                system_debug(f"Stopping discovery after successful results from {resolver.__name__}.")
                break
        except Exception as exc:
            system_debug(f"Resolver {resolver.__name__} failed: {exc}")

    nodes = list(collected.values())
    nodes.sort(key=lambda item: item.name.lower())
    return tuple(nodes)

def _get_cache_path() -> Path:
    return Path(paths.get_charon_temp_dir()) / _OBJECT_INFO_CACHE_FILE

def _fetch_object_info_with_cache() -> Optional[Dict[str, Any]]:
    """Try to fetch object info from API, update cache. On failure, read from cache."""
    cache_path = _get_cache_path()
    client = ComfyUIClient(timeout=2) # Short timeout to avoid freezing if server down
    
    # Try live fetch first (non-blocking check ideally, but short timeout helps)
    info = client.get_object_info()
    if info:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(info, f)
            system_debug("Updated object info cache from live ComfyUI API.")
            return info
        except Exception as exc:
            system_error(f"Failed to write object info cache: {exc}")
            return info

    # Fallback to cache
    if cache_path.exists():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                info = json.load(f)
            system_debug("Loaded object info from local cache.")
            return info
        except Exception as exc:
            system_error(f"Failed to read object info cache: {exc}")
    
    return None

def _discover_with_comfy_api(
    workflow_document: Dict[str, Any]
) -> Tuple[ExposableNode, ...]:
    object_info = _fetch_object_info_with_cache()
    if not object_info:
        return tuple()

    try:
        bindings = collect_workflow_widget_bindings_from_api(workflow_document, object_info)
    except Exception as exc:
        system_error(f"API-based discovery failed: {exc}")
        return tuple()

    return _aggregate_bindings(bindings, workflow_document)

def _discover_with_playwright(
    workflow_document: Dict[str, Any]
) -> Tuple[ExposableNode, ...]:
    """Launch headless ComfyUI via Playwright to inspect widget names."""
    
    comfy_path = preferences.get_preference("comfyui_launch_path", "") or paths.get_default_comfy_launch_path()
    if not comfy_path:
        return tuple()
        
    env_info = paths.resolve_comfy_environment(comfy_path)
    python_exe = env_info.get("python_exe")
    comfy_dir = env_info.get("comfy_dir")
    
    if not python_exe or not comfy_dir:
        return tuple()
        
    script_path = Path(__file__).resolve().with_name("inspect_workflow_playwright.py")
    if not script_path.exists():
        return tuple()
        
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
        json.dump(workflow_document, handle)
        temp_input = handle.name
        
    repo_root = Path(__file__).resolve().parents[1]
    
    # We run the inspection script using ComfyUI's Python executable.
    # This ensures we access the Playwright installed in that environment.
    command = [python_exe, str(script_path), "--workflow", temp_input, "--comfy-dir", str(comfy_dir)]
    
    system_debug(f"Starting Playwright inspection with command: {command}")
    try:
        # Long timeout because launching ComfyUI takes time (increased to 120s)
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            cwd=str(repo_root),
            timeout=120, 
            check=False
        )
        system_debug(f"Playwright inspection finished with code {result.returncode}")
    except subprocess.TimeoutExpired:
        system_error("Playwright inspection timed out after 120s.")
        return tuple()
    finally:
        try:
            os.remove(temp_input)
        except OSError:
            pass
            
    if result.returncode != 0:
        system_debug(f"Playwright inspection failed (code {result.returncode}): {result.stderr}")
        return tuple()
        
    stdout = (result.stdout or "").strip()
    if not stdout:
        return tuple()
        
    payload = None
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        # Try to find JSON in the last line
        lines = stdout.strip().splitlines()
        if lines:
            try:
                payload = json.loads(lines[-1])
            except:
                pass
                
    if isinstance(payload, dict) and "error" in payload:
        system_debug(f"Playwright inspection error: {payload['error']}")
        return tuple()
        
    if not isinstance(payload, list):
        return tuple()
        
    # Convert Playwright payload to ExposableNodes
    # Payload structure: [{node_id, type, title, widgets: [{name, type, value}, ...]}, ...]
    
    nodes: List[ExposableNode] = []
    for entry in payload:
        node_id = entry.get("node_id")
        if not node_id: 
            continue
            
        widgets = entry.get("widgets") or []
        if not widgets:
            continue
            
        attributes: List[ExposableAttribute] = []
        for idx, w in enumerate(widgets):
            name = w.get("name")
            val = w.get("value")
            w_type = w.get("type") or "string"
            
            # Skip hidden/internal widgets if needed, but generally we expose all
            if not name: continue
            
            # Alias for widgets_values mapping
            aliases = (f"widgets_values[{idx}]",)
            
            label = _format_binding_label(name, w_type)
            
            attr = ExposableAttribute(
                key=name,
                label=label,
                value=val,
                value_type=_infer_value_type(val) if not w_type else str(w_type).lower(),
                preview=_format_attribute_preview(val),
                aliases=aliases
            )
            attributes.append(attr)
            
        if attributes:
            nodes.append(ExposableNode(
                node_id=node_id,
                name=entry.get("title") or entry.get("type") or f"Node {node_id}",
                attributes=tuple(attributes)
            ))
            
    nodes.sort(key=lambda item: item.name.lower())
    return tuple(nodes)

def _aggregate_bindings(bindings, workflow_document):
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
            choices=spec.choices,
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
    return tuple(nodes)

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
    
    return _aggregate_bindings(bindings, workflow_document)


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

    script_path = Path(__file__).resolve().with_name("inspect_workflow_widgets.py")
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

        widget_names = _infer_widget_names(node_data)
        attributes: List[ExposableAttribute] = []
        for index, value in enumerate(widgets_values):
            if not _is_supported_widget_value(value):
                continue

            display_name = widget_names[index] if index < len(widget_names) else f"widgets_values[{index}]"
            key = display_name or f"widgets_values[{index}]"
            is_placeholder = display_name.startswith("widgets_values[") and display_name.endswith("]")
            label_source = display_name if (display_name and not is_placeholder) else f"Value {index + 1}"

            if isinstance(value, str) and not value.strip():
                # Retain empty strings when we have a named widget (e.g. prompt fields).
                if display_name == f"widgets_values[{index}]":
                    continue

            value_type = _infer_value_type(value)
            label = _format_binding_label(label_source, value_type)
            attributes.append(
                ExposableAttribute(
                    key=key,
                    label=label,
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


def _infer_widget_names(node_data: Dict[str, Any]) -> List[str]:
    """
    Attempt to recover widget names so empty string values (e.g. prompt fields)
    can still be exposed with a user-friendly label.
    """
    properties = node_data.get("properties")
    if isinstance(properties, dict):
        ue_props = properties.get("ue_properties")
        if isinstance(ue_props, dict):
            widget_map = ue_props.get("widget_ue_connectable")
            if isinstance(widget_map, dict):
                return list(widget_map.keys())

    inputs = node_data.get("inputs")
    if isinstance(inputs, list):
        flagged = [
            entry.get("name")
            for entry in inputs
            if isinstance(entry, dict) and entry.get("widget") and entry.get("name")
        ]
        if flagged:
            return flagged

        inferred = [
            entry.get("name")
            for entry in inputs
            if isinstance(entry, dict) and entry.get("link") is None and entry.get("name")
        ]
        if inferred:
            return inferred

    inputs = node_data.get("inputs")
    if isinstance(inputs, dict):
        ordered = [str(name) for name in inputs.keys() if name]
        if ordered:
            return ordered

    return []


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
