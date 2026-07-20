from __future__ import annotations

from typing import Any, Dict, Iterable, Iterator, Tuple


def iter_workflow_nodes(document: Dict[str, Any]) -> Iterator[Tuple[str, Dict[str, Any]]]:
    """Yield workflow nodes from API payloads and nested frontend subgraphs."""
    if not isinstance(document, dict):
        return

    nodes = document.get("nodes")
    if isinstance(nodes, list):
        yield from _iter_frontend_graph_nodes(document)
        return

    for node_id, node_data in document.items():
        if isinstance(node_data, dict) and (
            "class_type" in node_data or "type" in node_data
        ):
            yield str(node_id), node_data


def iter_workflow_node_dicts(document: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    """Yield only node dictionaries for callers that do not need node ids."""
    for _, node in iter_workflow_nodes(document):
        yield node


def _iter_frontend_graph_nodes(graph: Dict[str, Any]) -> Iterator[Tuple[str, Dict[str, Any]]]:
    nodes = graph.get("nodes")
    if isinstance(nodes, list):
        for node in nodes:
            if not isinstance(node, dict):
                continue
            node_id = node.get("id")
            yield str(node_id) if node_id is not None else "", node

    for subgraph in _iter_subgraphs(graph):
        yield from _iter_frontend_graph_nodes(subgraph)


def _iter_subgraphs(graph: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    definitions = graph.get("definitions")
    if isinstance(definitions, dict):
        yield from _coerce_subgraphs(definitions.get("subgraphs"))
    yield from _coerce_subgraphs(graph.get("subgraphs"))


def _coerce_subgraphs(value: Any) -> Iterator[Dict[str, Any]]:
    if isinstance(value, list):
        for subgraph in value:
            if isinstance(subgraph, dict):
                yield subgraph
    elif isinstance(value, dict):
        for subgraph in value.values():
            if isinstance(subgraph, dict):
                yield subgraph
