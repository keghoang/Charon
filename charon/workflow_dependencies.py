from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

from .workflow_graph import iter_workflow_node_dicts


IGNORED_REGISTRY_PACKAGES = {"comfy-core"}


def load_workflow_dependencies(workflow_path: str) -> List[Dict[str, str]]:
    """Load a workflow JSON file and derive portable custom-node dependency hints."""
    try:
        with open(workflow_path, "r", encoding="utf-8") as handle:
            workflow = json.load(handle)
    except (OSError, ValueError, json.JSONDecodeError):
        return []
    return collect_workflow_dependencies(workflow)


def collect_workflow_dependencies(workflow: Dict[str, Any]) -> List[Dict[str, str]]:
    """Collect dependency hints serialized by the ComfyUI frontend."""
    dependencies: Dict[str, Dict[str, str]] = {}
    if not isinstance(workflow, dict):
        return []

    for node in iter_workflow_node_dicts(workflow):
        properties = node.get("properties")
        if not isinstance(properties, dict):
            continue
        registry_id = str(properties.get("cnr_id") or "").strip()
        aux_id = str(properties.get("aux_id") or "").strip()
        if registry_id.lower() in IGNORED_REGISTRY_PACKAGES:
            registry_id = ""
        if not registry_id and not aux_id:
            continue

        repo = _repo_from_aux(aux_id)
        name = registry_id or _name_from_repo(repo) or aux_id
        key = (repo or name).lower()
        if not key:
            continue

        dependency = dependencies.setdefault(key, {"name": name})
        if repo:
            dependency["repo"] = repo
        if registry_id:
            dependency["cnr_id"] = registry_id

    return sorted(dependencies.values(), key=lambda entry: entry.get("name", "").lower())


def _repo_from_aux(aux_id: str) -> str:
    aux = (aux_id or "").strip()
    if not aux:
        return ""
    if aux.lower().startswith(("http://", "https://")):
        return aux
    if "/" in aux and " " not in aux:
        return f"https://github.com/{aux}"
    return ""


def _name_from_repo(repo: str) -> str:
    if not repo:
        return ""
    parsed = urlparse(repo)
    tail = Path((parsed.path or "").rstrip("/")).name
    return tail[:-4] if tail.endswith(".git") else tail
