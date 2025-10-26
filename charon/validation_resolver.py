from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

from .charon_logger import system_debug, system_error, system_info, system_warning
from .paths import resolve_comfy_environment


SHARED_MODELS_ROOT = r"\\buck\globalprefs\SHARED\CODE\Charon_repo\shared_models"


@dataclass
class ResolutionResult:
    """Container describing the outcome of an auto-resolve attempt."""

    resolved: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    failed: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def extend(self, other: "ResolutionResult") -> None:
        self.resolved.extend(other.resolved)
        self.skipped.extend(other.skipped)
        self.failed.extend(other.failed)
        self.notes.extend(other.notes)

    def to_dict(self) -> Dict[str, List[str]]:
        return {
            "resolved": list(self.resolved),
            "skipped": list(self.skipped),
            "failed": list(self.failed),
            "notes": list(self.notes),
        }


def find_local_model_matches(
    reference: Dict[str, Any],
    models_root: str,
    *,
    extra_roots: Optional[Sequence[str]] = None,
) -> List[str]:
    """
    Locate files that match the referenced model name within designated folders.

    Returns a list of candidate absolute paths sorted by preference (nearest
    match first).
    """
    file_name = os.path.basename(_safe_str(reference.get("name")))
    if not file_name:
        return []

    search_roots: List[str] = []
    for root in _iter_designated_roots(reference, models_root):
        if root not in search_roots:
            search_roots.append(root)
    for root in extra_roots or ():
        normalized = os.path.abspath(root)
        if normalized and normalized not in search_roots and os.path.isdir(normalized):
            search_roots.append(normalized)

    if not search_roots:
        return []

    matches: List[str] = []
    seen: set[str] = set()
    for root in search_roots:
        for candidate in _iter_matching_files(root, file_name):
            if candidate in seen:
                continue
            seen.add(candidate)
            matches.append(candidate)
    return matches


def find_shared_model_matches(file_name: str) -> List[str]:
    """Search the global shared models repository for matching files."""
    file_name = os.path.basename(_safe_str(file_name))
    if not file_name or not os.path.isdir(SHARED_MODELS_ROOT):
        return []
    matches: List[str] = []
    for candidate in _iter_matching_files(SHARED_MODELS_ROOT, file_name):
        matches.append(candidate)
    return matches


def format_model_reference_for_workflow(
    candidate_path: str,
    comfy_dir: Optional[str],
) -> str:
    """
    Convert an absolute path into the string representation expected inside a workflow.
    """
    candidate_path = os.path.abspath(candidate_path)
    comfy_dir = os.path.abspath(comfy_dir) if comfy_dir else None
    if comfy_dir:
        try:
            rel = os.path.relpath(candidate_path, comfy_dir)
            if not rel.startswith(".."):
                return rel.replace("\\", "/")
        except ValueError:
            pass
    return candidate_path.replace("\\", "/")


def determine_expected_model_path(
    reference: Dict[str, Any],
    models_root: str,
    comfy_dir: Optional[str],
) -> Optional[str]:
    return _expected_model_path(
        reference,
        models_root,
        comfy_dir,
        attempted_categories=reference.get("attempted_categories"),
        attempted_directories=reference.get("attempted_directories"),
    )


def resolve_missing_models(
    issue_data: Dict[str, Any],
    comfy_path: str,
) -> ResolutionResult:
    """
    Attempt to resolve missing models by looking for matching files in nearby folders.

    When users tuck checkpoints into subdirectories, we try to locate the file with the
    same name under the expected parent folder and copy it into place.
    """
    result = ResolutionResult()

    models_root = _safe_str(issue_data.get("models_root"))
    if not models_root:
        result.failed.append("Model root path was not provided.")
        return result

    comfy_dir = ""
    if comfy_path:
        try:
            env_info = resolve_comfy_environment(comfy_path)
        except Exception as exc:  # pragma: no cover - defensive guard
            system_warning(f"Failed to resolve Comfy environment: {exc}")
            env_info = {}
        comfy_dir = _safe_str(env_info.get("comfy_dir"))
    if not comfy_dir:
        comfy_dir = os.path.dirname(models_root)

    missing_entries = _coerce_sequence(issue_data.get("missing"))
    if not missing_entries:
        result.skipped.append("No missing models were reported.")
        return result

    for entry in missing_entries:
        if not isinstance(entry, dict):
            continue
        name = _safe_str(entry.get("name"))
        if not name:
            result.failed.append("Encountered a model reference without a name.")
            continue
        attempted_categories = entry.get("attempted_categories") or []
        attempted_directories = entry.get("attempted_directories") or []
        target_path = _expected_model_path(
            entry,
            models_root,
            comfy_dir,
            attempted_categories=attempted_categories,
            attempted_directories=attempted_directories,
        )
        if not target_path:
            result.failed.append(f"Unable to determine target path for '{name}'.")
            continue

        dest_dir = os.path.dirname(target_path)
        dest_file = os.path.basename(target_path)
        search_root = dest_dir if dest_dir else models_root
        candidate = _find_matching_file(search_root, dest_file)
        if candidate is None and os.path.abspath(search_root) != os.path.abspath(models_root):
            candidate = _find_matching_file(models_root, dest_file)

        if candidate is None:
            if attempted_directories:
                attempt_hint = ", ".join(sorted(set(attempted_directories)))
            elif attempted_categories:
                attempt_hint = ", ".join(attempted_categories)
            else:
                attempt_hint = "models"
            result.failed.append(
                f"Could not locate '{dest_file}' in categories: {attempt_hint}."
            )
            continue

        # If the located file already matches the destination, mark as resolved.
        if os.path.abspath(candidate) == os.path.abspath(target_path):
            result.resolved.append(f"{dest_file} already present.")
            continue

        try:
            os.makedirs(dest_dir, exist_ok=True)
            system_debug(
                f"Copying model '{dest_file}' from '{candidate}' to '{target_path}'."
            )
            shutil.copy2(candidate, target_path)
            result.resolved.append(f"Copied {dest_file} to models directory.")
        except Exception as exc:  # pragma: no cover - filesystem guard
            message = f"Failed to copy '{dest_file}': {exc}"
            system_warning(message)
            result.failed.append(message)

    if not result.resolved and not result.failed:
        result.notes.append("No model fixes were necessary.")

    return result


def resolve_missing_custom_nodes(
    issue_data: Dict[str, Any],
    comfy_path: str,
    dependencies: Optional[Iterable[Dict[str, Any]]] = None,
) -> ResolutionResult:
    """
    Attempt to resolve missing custom nodes by cloning declared dependencies.

    Dependencies are expected to come from `.charon.json` and include at least the
    repository URL. When multiple missing node types map to the same dependency we only
    clone the repository once.
    """
    result = ResolutionResult()

    try:
        env_info = resolve_comfy_environment(comfy_path)
    except Exception as exc:  # pragma: no cover - defensive guard
        result.failed.append(f"Failed to resolve Comfy environment: {exc}")
        return result

    comfy_dir = _safe_str(env_info.get("comfy_dir"))
    if not comfy_dir:
        result.failed.append("Unable to determine the ComfyUI directory.")
        return result

    custom_nodes_dir = os.path.join(comfy_dir, "custom_nodes")
    os.makedirs(custom_nodes_dir, exist_ok=True)

    missing_nodes = _coerce_sequence(issue_data.get("missing"))
    if not missing_nodes:
        result.skipped.append("No missing custom nodes were reported.")
        return result

    dependency_index = _index_dependencies(dependencies)
    matched_dependencies: Dict[str, Dict[str, Any]] = {}

    for node_name in missing_nodes:
        node_key = _safe_str(node_name).lower()
        if not node_key:
            continue
        dep = _match_dependency(node_key, dependency_index)
        if dep:
            matched_dependencies[dep["name"]] = dep

    # Fallback: clone everything if nothing matched directly.
    if not matched_dependencies and dependency_index:
        matched_dependencies.update(dependency_index)
        result.notes.append(
            "No dependency matched missing nodes directly; cloning declared dependencies."
        )

    if not matched_dependencies:
        result.failed.append(
            "No dependencies declared for missing custom nodes. "
            "Add repository URLs to the workflow metadata."
        )
        return result

    for dep_name, dep in matched_dependencies.items():
        repo = dep.get("repo")
        if not repo:
            result.failed.append(f"Dependency '{dep_name}' does not include a repo URL.")
            continue

        target_dir = os.path.join(custom_nodes_dir, dep_name)
        if os.path.isdir(target_dir) and os.listdir(target_dir):
            result.skipped.append(f"Custom node '{dep_name}' already installed.")
            continue

        try:
            _clone_repository(repo, target_dir, dep.get("ref"))
            result.resolved.append(f"Cloned {dep_name} into custom_nodes.")
        except Exception as exc:  # pragma: no cover - subprocess guard
            message = f"Failed to clone '{dep_name}' ({repo}): {exc}"
            system_error(message)
            result.failed.append(message)

    return result


def _safe_str(value: Any) -> str:
    return str(value).strip() if isinstance(value, str) else ""


def _coerce_sequence(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _expected_model_path(
    reference: Dict[str, Any],
    models_root: str,
    comfy_dir: Optional[str],
    *,
    attempted_categories: Optional[List[str]] = None,
    attempted_directories: Optional[List[str]] = None,
) -> Optional[str]:
    raw_name = _safe_str(reference.get("name"))
    if not raw_name:
        return None

    normalized = raw_name.replace("/", os.sep).replace("\\", os.sep)
    if os.path.isabs(normalized):
        return normalized

    candidate = None
    if comfy_dir:
        candidate = os.path.join(comfy_dir, normalized)
        if os.path.exists(candidate):
            return os.path.abspath(candidate)

    base_name = os.path.basename(normalized)
    categories_to_consider: List[str] = []

    primary_category = _safe_str(reference.get("category"))
    if primary_category:
        categories_to_consider.append(primary_category)

    for candidate in attempted_categories or reference.get("attempted_categories") or []:
        normalized_candidate = _safe_str(candidate)
        if normalized_candidate and normalized_candidate not in categories_to_consider:
            categories_to_consider.append(normalized_candidate)

    # Always include bare models directory as final fallback.
    categories_to_consider.append("")

    candidate_dirs: List[str] = []
    for directory in attempted_directories or reference.get("attempted_directories") or []:
        if not isinstance(directory, str):
            continue
        normalized_dir = os.path.abspath(directory)
        if os.path.isdir(normalized_dir) and normalized_dir not in candidate_dirs:
            candidate_dirs.append(normalized_dir)
    for category in categories_to_consider:
        normalized_category = _safe_str(category)
        if not normalized_category:
            continue
        candidate_dir = os.path.join(models_root, normalized_category)
        if os.path.isdir(candidate_dir):
            candidate_dirs.append(candidate_dir)

    if models_root not in candidate_dirs and os.path.isdir(models_root):
        candidate_dirs.append(models_root)

    for directory in candidate_dirs:
        target = os.path.join(directory, base_name)
        if target:
            return os.path.abspath(target)
    return os.path.abspath(os.path.join(models_root, base_name))


def _find_matching_file(root: str, file_name: str) -> Optional[str]:
    if not root or not file_name:
        return None
    if os.path.isfile(os.path.join(root, file_name)):
        return os.path.abspath(os.path.join(root, file_name))
    if not os.path.isdir(root):
        return None
    for candidate_root, _dirs, files in os.walk(root):
        if file_name in files:
            return os.path.abspath(os.path.join(candidate_root, file_name))
    return None


def _iter_matching_files(root: str, file_name: str) -> Iterator[str]:
    if not root or not file_name:
        return
    normalized_root = os.path.abspath(root)
    if not os.path.isdir(normalized_root):
        return
    direct_candidate = os.path.join(normalized_root, file_name)
    if os.path.isfile(direct_candidate):
        yield os.path.abspath(direct_candidate)
    lowered = file_name.lower()
    for candidate_root, _dirs, files in os.walk(normalized_root):
        for entry in files:
            if entry.lower() == lowered:
                yield os.path.abspath(os.path.join(candidate_root, entry))


def _iter_designated_roots(
    reference: Dict[str, Any],
    models_root: str,
) -> Iterator[str]:
    if models_root:
        models_root = os.path.abspath(models_root)
    seen: set[str] = set()
    attempted_dirs = reference.get("attempted_directories") or []
    for directory in attempted_dirs:
        if not isinstance(directory, str):
            continue
        normalized = os.path.abspath(directory)
        if not os.path.isdir(normalized):
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        yield normalized

    attempted_categories = reference.get("attempted_categories") or []
    for category in attempted_categories:
        category = _safe_str(category)
        if not category:
            continue
        if not models_root:
            continue
        candidate = os.path.join(models_root, category)
        if not os.path.isdir(candidate):
            continue
        normalized = os.path.abspath(candidate)
        if normalized in seen:
            continue
        seen.add(normalized)
        yield normalized

    if models_root and os.path.isdir(models_root) and models_root not in seen:
        seen.add(models_root)
        yield models_root


def _index_dependencies(
    dependencies: Optional[Iterable[Dict[str, Any]]],
) -> Dict[str, Dict[str, Any]]:
    index: Dict[str, Dict[str, Any]] = {}
    for dep in dependencies or []:
        if not isinstance(dep, dict):
            continue
        name = _safe_str(dep.get("name"))
        repo = _safe_str(dep.get("repo"))
        if not name and repo:
            name = _derive_name_from_repo(repo)
        if not name:
            continue
        index[name.lower()] = {"name": name, "repo": repo, "ref": _safe_str(dep.get("ref"))}
    return index


def _match_dependency(
    node_name: str,
    dependency_index: Dict[str, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    for dep_key, dep in dependency_index.items():
        if dep_key in node_name or node_name in dep_key:
            return dep
    return None


def _derive_name_from_repo(repo: str) -> str:
    parts = repo.rstrip("/").split("/")
    candidate = parts[-1] if parts else repo
    if candidate.endswith(".git"):
        candidate = candidate[:-4]
    return candidate


def _clone_repository(repo: str, target_dir: str, ref: Optional[str]) -> None:
    system_info(f"Cloning dependency {repo} into {target_dir}")
    completed = subprocess.run(
        ["git", "clone", repo, target_dir],
        check=True,
        capture_output=True,
        text=True,
    )
    if completed.stdout:
        system_debug(completed.stdout.strip())
    if completed.stderr:
        system_debug(completed.stderr.strip())

    if ref:
        system_info(f"Checking out ref '{ref}' for {repo}")
        completed = subprocess.run(
            ["git", "checkout", ref],
            cwd=target_dir,
            check=True,
            capture_output=True,
            text=True,
        )
        if completed.stdout:
            system_debug(completed.stdout.strip())
        if completed.stderr:
            system_debug(completed.stderr.strip())
