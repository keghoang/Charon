from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import preferences
from .charon_logger import system_debug, system_error, system_info, system_warning
from .comfy_client import ComfyUIClient
from .paths import resolve_comfy_environment
from .validation_cache import load_validation_log


DEFAULT_PING_URL = "http://127.0.0.1:8188"
CACHE_KEY = "comfy_validation_cache"
BANNER_PREF_KEY = "comfy_validator_banner_dismissed"
CACHE_TTL_SECONDS = 900  # 15 minutes
MODEL_EXTENSIONS = (".ckpt", ".safetensors", ".pth", ".pt", ".bin", ".onnx", ".yaml")
IGNORED_NODE_TYPES = {
    "",
    "note",
    "note node",
    "routetopreview",
    "primitive",
    "primitivenode",
    "reroute",
    "setnode",
    "getnode",
}
VALIDATOR_SCRIPT = """import json
import os
import sys
import traceback

input_path = sys.argv[1]
output_path = sys.argv[2]
comfy_dir = sys.argv[3]

result = {
    "ok": False,
    "missing": [],
    "errors": [],
    "traceback": "",
}

try:
    sys.path.insert(0, comfy_dir)

    # Ensure Comfy's utils module resolves correctly
    if "utils" in sys.modules:
        del sys.modules["utils"]

    import importlib.util

    utils_dir = os.path.join(comfy_dir, "utils")
    utils_init = os.path.join(utils_dir, "__init__.py")
    if os.path.exists(utils_init):
        utils_spec = importlib.util.spec_from_file_location(
            "utils", utils_init, submodule_search_locations=[utils_dir]
        )
        utils_module = importlib.util.module_from_spec(utils_spec)
        utils_spec.loader.exec_module(utils_module)
        sys.modules["utils"] = utils_module

    import comfy.options

    comfy.options.enable_args_parsing(False)

    from comfy.cli_args import args  # noqa: F401
    import folder_paths  # noqa: F401
    import nodes
    import server

    class _StubRoute:
        def __getattr__(self, _name):
            def decorator(*_args, **_kwargs):
                def passthrough(func):
                    return func

                return passthrough

            return decorator

    class _StubRouter:
        def add_static(self, *args, **kwargs):
            return None

    class _StubApp:
        def __init__(self):
            self.router = _StubRouter()

        def add_routes(self, *args, **kwargs):
            return None

    class _StubPromptServer:
        def __init__(self):
            self.routes = _StubRoute()
            self.app = _StubApp()
            self.supports = []

        def send_sync(self, *args, **kwargs):
            return None

        def __getattr__(self, _name):
            def _noop(*_args, **_kwargs):
                return None

            return _noop

    if not hasattr(getattr(server, "PromptServer", object), "instance"):
        server.PromptServer.instance = _StubPromptServer()

    nodes.init_extra_nodes(init_custom_nodes=True, init_api_nodes=False)

    with open(input_path, "r", encoding="utf-8") as handle:
        required = json.load(handle)

    available = set(nodes.NODE_CLASS_MAPPINGS.keys())
    missing = [name for name in required if name not in available]
    result["missing"] = missing
    result["ok"] = not missing
except Exception as exc:  # pragma: no cover - defensive path
    result["errors"].append(f"{exc.__class__.__name__}: {exc}")
    result["traceback"] = traceback.format_exc()

with open(output_path, "w", encoding="utf-8") as handle:
    json.dump(result, handle, indent=2)
"""


MODEL_RESOLVER_SCRIPT = """import json
import os
import sys
import traceback

input_path = sys.argv[1]
output_path = sys.argv[2]
comfy_dir = sys.argv[3]

payload = {
    "resolved": [],
    "missing": [],
    "errors": [],
    "traceback": "",
}

try:
    sys.path.insert(0, comfy_dir)

    if "utils" in sys.modules:
        del sys.modules["utils"]

    import importlib.util

    utils_dir = os.path.join(comfy_dir, "utils")
    utils_init = os.path.join(utils_dir, "__init__.py")
    if os.path.exists(utils_init):
        utils_spec = importlib.util.spec_from_file_location(
            "utils", utils_init, submodule_search_locations=[utils_dir]
        )
        utils_module = importlib.util.module_from_spec(utils_spec)
        utils_spec.loader.exec_module(utils_module)
        sys.modules["utils"] = utils_module

    import comfy.options

    comfy.options.enable_args_parsing(False)

    from comfy.cli_args import args  # noqa: F401
    import folder_paths

    models_dir = os.path.join(comfy_dir, "models")

    with open(input_path, "r", encoding="utf-8") as handle:
        references = json.load(handle)

    def _normalize(name):
        return name.replace("/", os.sep).replace("\\\\", os.sep)

    def _iter_folder_entries(category):
        mapping = getattr(folder_paths, "folder_names_and_paths", {})
        entry = mapping.get(category)
        if isinstance(entry, dict):
            for key in ("folders", "paths", "path"):
                values = entry.get(key)
                if isinstance(values, str):
                    yield values
                elif isinstance(values, (list, tuple, set)):
                    for value in values:
                        if isinstance(value, str):
                            yield value
        elif isinstance(entry, (list, tuple, set)):
            for value in entry:
                if isinstance(value, str):
                    yield value
                elif isinstance(value, (list, tuple, set)):
                    for sub in value:
                        if isinstance(sub, str):
                            yield sub

    def _iter_folder_paths(category):
        seen = set()
        candidate_getters = (
            "get_folder_paths",
            "get_folder_paths_for",
            "get_input_directory",
        )
        for attr in candidate_getters:
            getter = getattr(folder_paths, attr, None)
            if callable(getter):
                try:
                    paths = getter(category)
                except TypeError:
                    try:
                        paths = getter(category, "")
                    except Exception:
                        paths = None
                except Exception:
                    paths = None
                if isinstance(paths, str):
                    paths = [paths]
                if isinstance(paths, (list, tuple, set)):
                    for path in paths:
                        if isinstance(path, str):
                            norm = os.path.abspath(path)
                            if norm not in seen and os.path.isdir(norm):
                                seen.add(norm)
                                yield norm
        for path in _iter_folder_entries(category):
            if isinstance(path, str):
                norm = os.path.abspath(path)
                if norm not in seen and os.path.isdir(norm):
                    seen.add(norm)
                    yield norm

    def _try_resolve(category, name, attempted, attempted_dirs):
        category = (category or "").strip()
        if not category:
            return None
        if category not in attempted:
            attempted.append(category)
        getter = getattr(folder_paths, "get_full_path", None)
        if callable(getter):
            try:
                candidate = getter(category, name)
                if candidate and os.path.exists(candidate):
                    directory = os.path.dirname(candidate)
                    if directory:
                        abs_dir = os.path.abspath(directory)
                        if abs_dir not in attempted_dirs:
                            attempted_dirs.append(abs_dir)
                    return os.path.abspath(candidate)
            except Exception:
                pass
        getter = getattr(folder_paths, "get_file_path", None)
        if callable(getter):
            try:
                candidate = getter(category, name)
                if candidate and os.path.exists(candidate):
                    directory = os.path.dirname(candidate)
                    if directory:
                        abs_dir = os.path.abspath(directory)
                        if abs_dir not in attempted_dirs:
                            attempted_dirs.append(abs_dir)
                    return os.path.abspath(candidate)
            except Exception:
                pass
        normalized = _normalize(name)
        basename = os.path.basename(normalized)
        for base in _iter_folder_paths(category):
            abs_base = os.path.abspath(base)
            if abs_base not in attempted_dirs:
                attempted_dirs.append(abs_base)
            candidate = os.path.join(abs_base, normalized)
            if os.path.exists(candidate):
                return os.path.abspath(candidate)
            candidate = os.path.join(abs_base, basename)
            if os.path.exists(candidate):
                return os.path.abspath(candidate)
        return None

    for entry in references:
        index = entry.get("index")
        name = entry.get("name") or ""
        category = entry.get("category") or ""
        node_type = entry.get("node_type") or ""
        attempted_dirs = []
        attempted = []

        if not name:
            payload["missing"].append(
                {
                    "index": index,
                    "reason": "empty",
                    "category": category,
                    "node_type": node_type,
                    "attempted": list(attempted),
                }
            )
            continue

        resolved_path = None
        resolved_category = None

        if category:
            resolved_path = _try_resolve(category, name, attempted, attempted_dirs)
            if resolved_path:
                resolved_category = category

        if resolved_path:
            payload["resolved"].append(
                {
                    "index": index,
                    "path": resolved_path,
                    "category": resolved_category,
                    "node_type": node_type,
                }
            )
        else:
            payload["missing"].append(
                {
                    "index": index,
                    "name": name,
                    "category": resolved_category or category,
                    "node_type": node_type,
                    "attempted": list(attempted),
                    "searched": [os.path.abspath(path) for path in attempted_dirs],
                }
            )
except Exception as exc:  # pragma: no cover - defensive path
    payload["errors"].append(f"{exc.__class__.__name__}: {exc}")
    payload["traceback"] = traceback.format_exc()

with open(output_path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2)
"""


@dataclass
class ValidationIssue:
    key: str
    label: str
    ok: bool
    summary: str
    details: List[str] = field(default_factory=list)
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "ok": self.ok,
            "summary": self.summary,
            "details": list(self.details),
            "data": dict(self.data),
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "ValidationIssue":
        return cls(
            key=str(payload.get("key") or ""),
            label=str(payload.get("label") or ""),
            ok=bool(payload.get("ok")),
            summary=str(payload.get("summary") or ""),
            details=list(payload.get("details") or []),
            data=dict(payload.get("data") or {}),
        )


@dataclass
class ValidationResult:
    comfy_path: str
    issues: List[ValidationIssue]
    started_at: float
    finished_at: float
    cache_key: str = ""
    workflow_folder: Optional[str] = None
    workflow_name: Optional[str] = None
    used_cache: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": 1,
            "comfy_path": self.comfy_path,
            "issues": [issue.to_dict() for issue in self.issues],
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "cache_key": self.cache_key,
            "workflow": {
                "folder": self.workflow_folder,
                "name": self.workflow_name,
            },
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "ValidationResult":
        workflow = payload.get("workflow") or {}
        issues = [
            ValidationIssue.from_dict(raw)
            for raw in payload.get("issues") or []
        ]
        return cls(
            comfy_path=str(payload.get("comfy_path") or ""),
            issues=issues,
            started_at=float(payload.get("started_at") or 0.0),
            finished_at=float(payload.get("finished_at") or 0.0),
            cache_key=str(payload.get("cache_key") or ""),
            workflow_folder=workflow.get("folder"),
            workflow_name=workflow.get("name"),
        )

    @property
    def ok(self) -> bool:
        return all(issue.ok for issue in self.issues)

    def age_seconds(self) -> float:
        if not self.finished_at:
            return float("inf")
        return max(0.0, time.time() - self.finished_at)

    def is_stale(self, ttl: float = CACHE_TTL_SECONDS) -> bool:
        return self.age_seconds() > ttl


def validate_comfy_environment(
    comfy_path: str,
    workflow_bundle: Optional[Dict[str, Any]] = None,
    *,
    ping_url: str = DEFAULT_PING_URL,
    use_cache: bool = True,
    force: bool = False,
) -> ValidationResult:
    comfy_path = (comfy_path or "").strip()
    started = time.time()
    cache_key = _cache_key_for_path(comfy_path)

    if use_cache and not force and comfy_path:
        cached = get_cached_result(comfy_path)
        if cached and not cached.is_stale():
            system_debug("Using cached Comfy validation result.")
            cached.used_cache = True
            return cached

    workflow_info = _extract_workflow_context(workflow_bundle)
    issues: List[ValidationIssue] = []

    if not comfy_path:
        issues.append(
            ValidationIssue(
                key="environment",
                label="Comfy path configured",
                ok=False,
                summary="No ComfyUI launch path is set.",
                details=[
                    "Open the ComfyUI settings gear and select run_nvidia_gpu.bat "
                    "or main.py from your Comfy install.",
                ],
            )
        )
        finished = time.time()
        result = ValidationResult(
            comfy_path=comfy_path,
            issues=issues,
            started_at=started,
            finished_at=finished,
            cache_key=cache_key,
            workflow_folder=workflow_info.get("folder"),
            workflow_name=workflow_info.get("name"),
        )
        return result

    env_info = resolve_comfy_environment(comfy_path)
    issues.append(_validate_environment(comfy_path, env_info))
    issues.append(_validate_runtime(ping_url, env_info))
    issues.append(_validate_models(env_info, workflow_bundle))
    issues.append(_validate_custom_nodes(env_info, workflow_bundle))

    finished = time.time()
    result = ValidationResult(
        comfy_path=comfy_path,
        issues=issues,
        started_at=started,
        finished_at=finished,
        cache_key=cache_key,
        workflow_folder=workflow_info.get("folder"),
        workflow_name=workflow_info.get("name"),
    )

    if comfy_path:
        store_validation_result(result)
    return result


def get_cached_result(comfy_path: str) -> Optional[ValidationResult]:
    comfy_path = (comfy_path or "").strip()
    if not comfy_path:
        return None
    cache = _load_cache()
    cache_key = _cache_key_for_path(comfy_path)
    payload = cache.get(cache_key)
    if not isinstance(payload, dict):
        return None
    try:
        return ValidationResult.from_dict(payload)
    except Exception as exc:  # pragma: no cover - defensive path
        system_warning(f"Failed to parse cached validation result: {exc}")
        return None


def store_validation_result(result: ValidationResult) -> None:
    cache = _load_cache()
    payload = result.to_dict()
    cache[result.cache_key] = payload
    _write_cache(cache)


def is_banner_dismissed() -> bool:
    prefs = preferences.load_preferences()
    return bool(prefs.get(BANNER_PREF_KEY, False))


def set_banner_dismissed(flag: bool) -> None:
    prefs = preferences.load_preferences()
    prefs[BANNER_PREF_KEY] = bool(flag)
    preferences.save_preferences(prefs)


def _validate_environment(comfy_path: str, env_info: Dict[str, Any]) -> ValidationIssue:
    base_exists = os.path.exists(comfy_path)
    comfy_dir = env_info.get("comfy_dir")
    python_exe = env_info.get("python_exe")
    comfy_dir_ok = bool(comfy_dir and os.path.isdir(comfy_dir))
    python_ok = bool(python_exe and os.path.exists(python_exe))

    details: List[str] = []
    if not base_exists:
        details.append(f"Launch file not found: {comfy_path}")
    if not comfy_dir_ok:
        details.append("ComfyUI directory missing (expected 'ComfyUI' next to the launch script).")
    if not python_ok:
        details.append("Embedded python not found (expected python_embeded/python.exe).")

    summary = (
        "ComfyUI installation looks valid."
        if base_exists and comfy_dir_ok and python_ok
        else "ComfyUI installation is incomplete."
    )

    data = {
        "base_exists": base_exists,
        "comfy_dir": comfy_dir,
        "comfy_dir_ok": comfy_dir_ok,
        "python_exe": python_exe,
        "python_ok": python_ok,
    }

    return ValidationIssue(
        key="environment",
        label="Comfy install located",
        ok=base_exists and comfy_dir_ok and python_ok,
        summary=summary,
        details=details,
        data=data,
    )


def _validate_runtime(ping_url: str, env_info: Dict[str, Any]) -> ValidationIssue:
    comfy_dir = env_info.get("comfy_dir")
    python_ok = bool(env_info.get("python_exe"))
    comfy_dir_ok = bool(comfy_dir and os.path.isdir(comfy_dir))
    details: List[str] = []

    if not (python_ok and comfy_dir_ok):
        return ValidationIssue(
            key="runtime",
            label="Runtime reachable",
            ok=False,
            summary="Skipped because the Comfy installation is incomplete.",
            details=["Fix the installation path before checking the runtime."],
        )

    client = ComfyUIClient(ping_url)
    started = time.time()
    try:
        reachable = bool(client.test_connection())
    except Exception as exc:  # pragma: no cover - defensive path
        details.append(f"Error while pinging ComfyUI: {exc}")
        reachable = False

    elapsed_ms = int((time.time() - started) * 1000)
    if reachable:
        summary = f"ComfyUI responded at {ping_url} ({elapsed_ms} ms)."
    else:
        summary = f"No response from {ping_url}."
        details.append("Launch ComfyUI or adjust its port in Preferences > ComfyUI Path.")

    return ValidationIssue(
        key="runtime",
        label="Runtime reachable",
        ok=reachable,
        summary=summary,
        details=details,
    )


def _validate_models(
    env_info: Dict[str, Any],
    workflow_bundle: Optional[Dict[str, Any]],
) -> ValidationIssue:
    comfy_dir = env_info.get("comfy_dir")
    if not comfy_dir or not os.path.isdir(comfy_dir):
        return ValidationIssue(
            key="models",
            label="Models available",
            ok=False,
            summary="Cannot inspect models without a valid ComfyUI directory.",
            details=["Fix the ComfyUI path first."],
        )

    references = _collect_model_references(workflow_bundle)
    models_root = os.path.join(comfy_dir, "models")
    data: Dict[str, Any] = {"models_root": models_root}

    if not references:
        summary = (
            "Select a workflow to verify its required models."
            if workflow_bundle is None
            else "No model references detected in this workflow."
        )
        ok = True
        return ValidationIssue(
            key="models",
            label="Models available",
            ok=ok,
            summary=summary,
            details=[],
            data=data,
        )

    python_exe = env_info.get("python_exe")
    enumerated_refs = [
        {
            "index": idx,
            "name": reference.get("name"),
            "category": reference.get("category"),
            "node_type": reference.get("node_type"),
        }
        for idx, reference in enumerate(references)
    ]

    resolver_result = _resolve_models_with_comfy(python_exe, comfy_dir, enumerated_refs)
    resolver_result = resolver_result or {}
    resolved_by_comfy = resolver_result.get("resolved") or {}
    resolved_categories = resolver_result.get("categories") or {}
    resolver_errors = resolver_result.get("errors") or []

    resolver_missing_entries = resolver_result.get("missing") or []
    cleaned_missing_entries: List[Dict[str, Any]] = []
    missing_by_index = {}
    for entry in resolver_missing_entries:
        if not isinstance(entry, dict):
            continue
        entry = dict(entry)
        entry.pop("resolved_path", None)
        idx = entry.get("index")
        if isinstance(idx, int):
            missing_by_index[idx] = entry
        cleaned_missing_entries.append(entry)
    resolver_missing_entries = cleaned_missing_entries

    workflow_folder = None
    if isinstance(workflow_bundle, dict):
        workflow_folder = workflow_bundle.get("folder")

    cached_resolved_entries: List[Dict[str, Any]] = []
    if workflow_folder:
        try:
            cached_payload = load_validation_log(workflow_folder)
            if isinstance(cached_payload, dict):
                models_cache = cached_payload.get("models")
                if isinstance(models_cache, dict):
                    cached_entries = models_cache.get("resolved_entries") or []
                    if isinstance(cached_entries, list):
                        cached_resolved_entries = [
                            entry for entry in cached_entries if isinstance(entry, dict)
                        ]
        except Exception:
            cached_resolved_entries = []

    invalid_resolutions: List[Dict[str, Any]] = []
    if resolved_by_comfy:
        filtered_resolved: Dict[int, str] = {}
        for idx, path in list(resolved_by_comfy.items()):
            if not isinstance(idx, int) or not isinstance(path, str):
                continue
            reference = references[idx] if idx < len(references) else None
            reference_name = reference.get("name") if isinstance(reference, dict) else ""
            if _resolved_path_matches_reference(reference_name, path, models_root):
                filtered_resolved[idx] = path
            else:
                invalid_resolutions.append(
                    {
                        "index": idx,
                        "path": path,
                        "reference": reference_name,
                    }
                )
                missing_entry = dict(missing_by_index.get(idx) or {})
                missing_entry.setdefault("index", idx)
                if reference_name:
                    missing_entry.setdefault("name", reference_name)
                missing_entry.setdefault("reason", "mismatched_path")
                missing_by_index[idx] = missing_entry
        resolver_missing_entries = [
            missing_by_index[idx] for idx in sorted(missing_by_index.keys())
        ]
        resolved_by_comfy = filtered_resolved

    if resolver_result:
        data["resolver"] = {
            "resolved": [
                {
                    "index": idx,
                    "path": resolved_by_comfy[idx],
                    "category": resolved_categories.get(idx),
                }
                for idx in sorted(resolved_by_comfy.keys())
            ],
            "missing": resolver_missing_entries,
        }
        if invalid_resolutions:
            data["resolver"]["invalid"] = invalid_resolutions
        if resolver_errors:
            data["resolver_errors"] = list(resolver_errors)
        traceback_text = resolver_result.get("traceback")
        if traceback_text:
            data["resolver_traceback"] = traceback_text

    missing: List[Dict[str, Any]] = []
    found_paths: List[str] = []
    found_set: set = set()
    index_cache: Optional[Dict[str, List[str]]] = None

    applied_replacements: List[Dict[str, Any]] = []
    if cached_resolved_entries:
        for entry in cached_resolved_entries:
            if not isinstance(entry, dict):
                continue
            path_value = entry.get("path")
            if not isinstance(path_value, str) or not path_value:
                continue
            abs_path = os.path.abspath(path_value)
            if os.path.exists(abs_path) and abs_path not in found_set:
                found_set.add(abs_path)
                found_paths.append(abs_path)

        signature_lookup: Dict[Tuple[Optional[str], Optional[str], Optional[str]], str] = {}
        name_lookup: Dict[str, str] = {}
        for entry in cached_resolved_entries:
            if not isinstance(entry, dict):
                continue
            path_value = entry.get("path")
            workflow_value = entry.get("workflow_value")
            if not isinstance(path_value, str) or not path_value:
                continue
            signature = entry.get("signature")
            if isinstance(signature, (list, tuple)) and len(signature) == 3:
                signature_tuple = tuple(signature)  # type: ignore[arg-type]
            else:
                signature_tuple = None
            effective_value = workflow_value if isinstance(workflow_value, str) and workflow_value else _derive_workflow_value_from_path(path_value, signature_tuple, models_root, comfy_dir)
            if not effective_value:
                continue
            if signature_tuple:
                signature_lookup[signature_tuple] = effective_value
            reference_name = entry.get("reference")
            if isinstance(reference_name, str) and reference_name:
                name_lookup[reference_name] = effective_value

        for ref_index, reference in enumerate(references):
            if not isinstance(reference, dict):
                continue
            signature = (
                reference.get("name"),
                reference.get("category"),
                reference.get("node_type"),
            )
            replacement = signature_lookup.get(signature)
            if not replacement:
                ref_name = reference.get("name")
                if isinstance(ref_name, str):
                    replacement = name_lookup.get(ref_name)
            if replacement:
                original_value = reference.get("name")
                reference["name"] = replacement
                if original_value != replacement:
                    applied_replacements.append(
                        {
                            "index": ref_index,
                            "original": original_value,
                            "replacement": replacement,
                            "source": "cached_reference",
                        }
                    )

        for entry in enumerated_refs:
            if not isinstance(entry, dict):
                continue
            signature = (
                entry.get("name"),
                entry.get("category"),
                entry.get("node_type"),
            )
            replacement = signature_lookup.get(signature)
            if not replacement:
                ref_name = entry.get("name")
                if isinstance(ref_name, str):
                    replacement = name_lookup.get(ref_name)
            if replacement:
                original_value = entry.get("name")
                entry["name"] = replacement
                if original_value != replacement:
                    applied_replacements.append(
                        {
                            "index": entry.get("index"),
                            "original": original_value,
                            "replacement": replacement,
                            "source": "cached_enumerated",
                        }
                    )
        if applied_replacements:
            system_debug(
                "[Validation] Cached model replacements applied: " +
                json.dumps(applied_replacements, indent=2)
            )
    for idx, reference in enumerate(references):
        resolved_path = resolved_by_comfy.get(idx)
        if resolved_path:
            if resolved_path not in found_set:
                found_set.add(resolved_path)
                found_paths.append(resolved_path)
            continue

        located, resolved = _find_model_file(models_root, comfy_dir, reference)
        if not located and index_cache is None and os.path.isdir(models_root):
            index_cache = _build_model_index(models_root)
            located, resolved = _lookup_model_in_index(index_cache, reference)
        if located and resolved:
            if resolved not in found_set:
                found_set.add(resolved)
                found_paths.append(resolved)
        else:
            resolver_info = missing_by_index.get(idx)
            if resolver_info:
                resolver_category = resolver_info.get("category")
                if resolver_category:
                    reference["category"] = resolver_category
                attempted = resolver_info.get("attempted") or []
                if attempted:
                    # Preserve order while removing duplicates
                    unique_attempted = []
                    for value in attempted:
                        if value and value not in unique_attempted:
                            unique_attempted.append(value)
                    if unique_attempted:
                        reference["attempted_categories"] = unique_attempted
                searched_dirs = resolver_info.get("searched") or []
                if searched_dirs:
                    normalized_dirs: List[str] = []
                    for directory in searched_dirs:
                        if not isinstance(directory, str):
                            continue
                        abs_dir = os.path.abspath(directory)
                        if abs_dir not in normalized_dirs:
                            normalized_dirs.append(abs_dir)
                    if normalized_dirs:
                        reference["attempted_directories"] = normalized_dirs
            missing.append(reference)

    if cached_resolved_entries:
        missing = _filter_missing_with_resolved_cache(missing, cached_resolved_entries)

    data["found"] = found_paths
    data["resolved_entries"] = cached_resolved_entries
    final_reference_log = [
        {
            'index': i,
            'name': reference.get('name'),
            'category': reference.get('category'),
            'node_type': reference.get('node_type'),
        }
        for i, reference in enumerate(references)
        if isinstance(reference, dict)
    ]
    system_debug(
        "[Validation] Final model references for " +
        f"{workflow_folder or 'unknown workflow'}: " +
        json.dumps(final_reference_log, indent=2)
    )
    if missing:
        summary = f"Missing {len(missing)} model file(s)."
        detail_lines = []
        for item in missing:
            attempted_dirs = item.get("attempted_directories") or []
            search_directories: List[str] = []
            for directory in attempted_dirs:
                if not isinstance(directory, str):
                    continue
                abs_dir = os.path.abspath(directory)
                if not os.path.isdir(abs_dir):
                    continue
                try:
                    if os.path.commonpath([abs_dir, models_root]) != os.path.abspath(models_root):
                        continue
                except ValueError:
                    continue
                if abs_dir not in search_directories:
                    search_directories.append(abs_dir)

            attempted = item.get("attempted_categories") or []
            unique_attempted: List[str] = []
            for entry in attempted:
                entry = (entry or "").strip()
                if entry and entry not in unique_attempted:
                    unique_attempted.append(entry)

            for category in unique_attempted:
                if not category:
                    continue
                directory = os.path.abspath(os.path.join(models_root, category))
                if not os.path.isdir(directory):
                    continue
                if directory not in search_directories:
                    search_directories.append(directory)

            display_paths: List[str] = []
            for directory in search_directories:
                display_value = None
                try:
                    rel_models = os.path.relpath(directory, models_root)
                    if not rel_models.startswith(".."):
                        rel_models = rel_models.replace("\\", "/")
                        display_value = f"models/{rel_models}" if rel_models else "models"
                except Exception:
                    pass

                if display_value is None and comfy_dir:
                    try:
                        rel_comfy = os.path.relpath(directory, comfy_dir)
                        if not rel_comfy.startswith(".."):
                            rel_comfy = rel_comfy.replace("\\", "/")
                            display_value = rel_comfy
                    except Exception:
                        pass

                if display_value is None:
                    display_value = directory.replace("\\", "/")

                if display_value and display_value not in display_paths:
                    display_paths.append(display_value)

            locations = ", ".join(display_paths) if display_paths else "models"
            detail_lines.append(f"Cannot find <b>{item['name']}</b> under <b>{locations}</b>")

        detail_lines.append("Confirm the files exist under the appropriate ComfyUI/models subfolder.")
        return ValidationIssue(
            key="models",
            label="Models available",
            ok=False,
            summary=summary,
            details=detail_lines,
            data=data,
        )

    summary = f"All {len(found_paths)} model file(s) found."
    return ValidationIssue(
        key="models",
        label="Models available",
        ok=True,
        summary=summary,
        details=[],
        data=data,
    )


def _resolve_models_with_comfy(
    python_exe: Optional[str],
    comfy_dir: Optional[str],
    references: List[Dict[str, Any]],
) -> Dict[str, Any]:
    if not python_exe or not os.path.exists(python_exe):
        return {}
    if not comfy_dir or not os.path.isdir(comfy_dir):
        return {}
    if not references:
        return {}

    temp_dir = tempfile.mkdtemp(prefix="charon_comfy_models_")
    try:
        input_path = os.path.join(temp_dir, "models.json")
        output_path = os.path.join(temp_dir, "result.json")
        script_path = os.path.join(temp_dir, "resolver.py")

        with open(input_path, "w", encoding="utf-8") as handle:
            json.dump(references, handle)
        with open(script_path, "w", encoding="utf-8") as handle:
            handle.write(MODEL_RESOLVER_SCRIPT)

        command = [python_exe, script_path, input_path, output_path, comfy_dir]
        system_debug(f"Running model resolver: {command}")
        completed = subprocess.run(
            command,
            cwd=comfy_dir,
            capture_output=True,
            timeout=60,
            text=True,
        )

        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            system_warning(f"Model resolver returned code {completed.returncode}: {detail}")
            message = detail or f"Model resolver exited with code {completed.returncode}"
            return {"errors": [message]}

        if not os.path.exists(output_path):
            system_warning("Model resolver did not produce a result file.")
            return {"errors": ["Model resolver produced no output."]}

        with open(output_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except subprocess.TimeoutExpired:
        system_warning("Model resolver timed out.")
        return {"errors": ["Model resolver timed out."]}
    except Exception as exc:  # pragma: no cover - defensive path
        system_warning(f"Model resolver failed: {exc}")
        return {"errors": [str(exc)]}
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    resolved_map: Dict[int, str] = {}
    category_map: Dict[int, str] = {}
    missing_map: Dict[int, Dict[str, Any]] = {}
    missing_entries: List[Dict[str, Any]] = []
    errors = payload.get("errors") or []
    traceback_text = payload.get("traceback") or ""

    for item in payload.get("resolved") or []:
        if not isinstance(item, dict):
            continue
        idx = item.get("index")
        path = item.get("path")
        category = item.get("category")
        if isinstance(idx, int) and isinstance(path, str) and path:
            resolved_map[idx] = path
            if isinstance(category, str) and category:
                category_map[idx] = category

    for item in payload.get("missing") or []:
        if not isinstance(item, dict):
            continue
        idx = item.get("index")
        if isinstance(idx, int):
            missing_map[idx] = item
            missing_entries.append(item)

    result: Dict[str, Any] = {
        "resolved": resolved_map,
        "categories": category_map,
        "missing": missing_entries,
        "errors": errors,
    }
    if traceback_text:
        result["traceback"] = traceback_text
    return result


def _validate_custom_nodes(
    env_info: Dict[str, Any],
    workflow_bundle: Optional[Dict[str, Any]],
) -> ValidationIssue:
    python_exe = env_info.get("python_exe")
    comfy_dir = env_info.get("comfy_dir")
    if not python_exe or not os.path.exists(python_exe):
        return ValidationIssue(
            key="custom_nodes",
            label="Custom nodes loaded",
            ok=False,
            summary="Embedded python not found; cannot validate custom nodes.",
            details=["Repair the embedded python environment and retry."],
        )
    if not comfy_dir or not os.path.isdir(comfy_dir):
        return ValidationIssue(
            key="custom_nodes",
            label="Custom nodes loaded",
            ok=False,
            summary="ComfyUI directory missing; cannot validate custom nodes.",
            details=["Fix the ComfyUI path first."],
        )

    required = sorted(_collect_node_types(workflow_bundle))
    if not required:
        return ValidationIssue(
            key="custom_nodes",
            label="Custom nodes loaded",
            ok=True,
            summary="No custom nodes referenced by the selected workflow.",
        )

    temp_dir = tempfile.mkdtemp(prefix="charon_comfy_validate_")
    try:
        input_path = os.path.join(temp_dir, "nodes.json")
        output_path = os.path.join(temp_dir, "result.json")
        script_path = os.path.join(temp_dir, "validator.py")

        with open(input_path, "w", encoding="utf-8") as handle:
            json.dump(required, handle)
        with open(script_path, "w", encoding="utf-8") as handle:
            handle.write(VALIDATOR_SCRIPT)

        command = [python_exe, script_path, input_path, output_path, comfy_dir]
        system_debug(f"Running custom node validation: {command}")
        completed = subprocess.run(
            command,
            cwd=comfy_dir,
            capture_output=True,
            timeout=60,
            text=True,
        )

        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            system_warning(f"Custom node validator returned code {completed.returncode}: {detail}")
            return ValidationIssue(
                key="custom_nodes",
                label="Custom nodes loaded",
                ok=False,
                summary="Custom node check failed to run.",
                details=[detail or "Check the console for details."],
            )

        if not os.path.exists(output_path):
            system_warning("Custom node validator did not produce a result file.")
            return ValidationIssue(
                key="custom_nodes",
                label="Custom nodes loaded",
                ok=False,
                summary="Custom node checker did not produce a result.",
                details=["Inspect the console output for errors."],
            )

        with open(output_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)

        missing = payload.get("missing") or []
        errors = payload.get("errors") or []
        data = {
            "missing": missing,
            "errors": errors,
            "required": required,
        }

        if errors:
            detail = payload.get("traceback") or errors[0]
            system_warning(f"Custom node validation errors: {detail}")
            return ValidationIssue(
                key="custom_nodes",
                label="Custom nodes loaded",
                ok=False,
                summary="Unable to load custom nodes. See traceback for details.",
                details=errors,
                data=data,
            )

        if missing:
            detail_lines = [
                f"{name} (missing from ComfyUI/custom_nodes)"
                for name in missing
            ]
            return ValidationIssue(
                key="custom_nodes",
                label="Custom nodes loaded",
                ok=False,
                summary=f"{len(missing)} custom node type(s) not found.",
                details=detail_lines,
                data=data,
            )

        return ValidationIssue(
            key="custom_nodes",
            label="Custom nodes loaded",
            ok=True,
            summary="All referenced custom nodes loaded successfully.",
            details=[],
            data=data,
        )
    except subprocess.TimeoutExpired:
        return ValidationIssue(
            key="custom_nodes",
            label="Custom nodes loaded",
            ok=False,
            summary="Custom node validation timed out.",
            details=["Ensure the embedded python environment can launch within 60 seconds."],
        )
    except Exception as exc:  # pragma: no cover - defensive path
        system_error(f"Custom node validation failed: {exc}")
        return ValidationIssue(
            key="custom_nodes",
            label="Custom nodes loaded",
            ok=False,
            summary="Custom node check crashed.",
            details=[str(exc)],
        )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _collect_model_references(
    workflow_bundle: Optional[Dict[str, Any]],
) -> List[Dict[str, str]]:
    if not isinstance(workflow_bundle, dict):
        return []

    workflow = workflow_bundle.get("workflow")
    if not isinstance(workflow, dict):
        return []

    references: Dict[Tuple[str, str], Dict[str, str]] = {}

    if "nodes" in workflow and isinstance(workflow["nodes"], list):
        nodes_iter = workflow["nodes"]
        for node in nodes_iter:
            _collect_references_from_node(node, references)
    else:
        for node in workflow.values():
            _collect_references_from_node(node, references)

    return list(references.values())


def _collect_references_from_node(
    node: Any,
    references: Dict[Tuple[str, str], Dict[str, str]],
) -> None:
    if not isinstance(node, dict):
        return
    node_type = str(node.get("type") or node.get("class_type") or "").strip()
    if not node_type:
        return

    widget_values = node.get("widgets_values") or []
    for value in _iterate_strings(widget_values):
        if _looks_like_model_file(value):
            _store_model_reference(references, value, node_type)

    inputs = node.get("inputs")
    if isinstance(inputs, list):
        for entry in inputs:
            if isinstance(entry, dict):
                default = entry.get("default")
                for value in _iterate_strings(default):
                    if _looks_like_model_file(value):
                        _store_model_reference(references, value, node_type)
    elif isinstance(inputs, dict):
        for value in inputs.values():
            for string in _iterate_strings(value):
                if _looks_like_model_file(string):
                    _store_model_reference(references, string, node_type)


def _collect_node_types(
    workflow_bundle: Optional[Dict[str, Any]],
) -> List[str]:
    if not isinstance(workflow_bundle, dict):
        return []

    workflow = workflow_bundle.get("workflow")
    if not isinstance(workflow, dict):
        return []

    names: List[str] = []
    seen: set[str] = set()

    if "nodes" in workflow and isinstance(workflow["nodes"], list):
        iterator: Iterable[Any] = workflow["nodes"]
        for node in iterator:
            node_type = str(node.get("type") or "").strip()
            normalized = node_type.lower()
            if normalized in IGNORED_NODE_TYPES:
                continue
            if node_type and node_type not in seen:
                seen.add(node_type)
                names.append(node_type)
    else:
        for node in workflow.values():
            if not isinstance(node, dict):
                continue
            node_type = str(node.get("class_type") or "").strip()
            normalized = node_type.lower()
            if normalized in IGNORED_NODE_TYPES:
                continue
            if node_type and node_type not in seen:
                seen.add(node_type)
                names.append(node_type)

    return names


def _store_model_reference(
    storage: Dict[Tuple[str, str], Dict[str, str]],
    file_name: str,
    node_type: str,
) -> None:
    category = _category_for_node(node_type, file_name)
    key = (file_name.lower(), category)
    if key in storage:
        return
    storage[key] = {
        "name": file_name,
        "category": category,
        "node_type": node_type,
    }


def _iterate_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        trimmed = value.strip()
        if trimmed:
            yield trimmed
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _iterate_strings(item)


def _looks_like_model_file(value: str) -> bool:
    lowered = value.lower()
    if lowered in {"none", "null"}:
        return False
    return any(lowered.endswith(ext) for ext in MODEL_EXTENSIONS)


def _category_for_node(node_type: str, file_name: str) -> str:
    token = node_type.lower()
    name_lower = file_name.lower()
    if "unet" in token or "unet" in name_lower:
        return "diffusion_models"
    if "lora" in token or "lora" in name_lower:
        return "loras"
    if "control" in token or "controlnet" in name_lower:
        return "controlnet"
    if "vae" in token or "vae" in name_lower:
        return "vae"
    if "clip" in token or "clip" in name_lower:
        return "clip"
    if "embedding" in token or "embedding" in name_lower:
        return "embeddings"
    return "checkpoints"


def _find_model_file(
    models_root: str,
    comfy_dir: str,
    reference: Dict[str, str],
) -> Tuple[bool, Optional[str]]:
    name = reference.get("name") or ""
    if not name:
        return False, None
    normalized = name.replace("/", os.sep).replace("\\", os.sep)
    base_name = os.path.basename(normalized)
    has_subdirectories = base_name != normalized

    if os.path.isabs(normalized) and os.path.exists(normalized):
        return True, os.path.abspath(normalized)

    candidate = os.path.join(comfy_dir, normalized)
    if os.path.exists(candidate):
        return True, os.path.abspath(candidate)

    if has_subdirectories:
        trimmed = normalized
        if normalized.lower().startswith(f"models{os.sep}"):
            trimmed = normalized[len("models") + 1 :]
        candidate = os.path.join(models_root, trimmed)
        if os.path.exists(candidate):
            return True, os.path.abspath(candidate)
        return False, None

    category = reference.get("category") or ""
    if category:
        direct = os.path.join(models_root, category, base_name)
        if os.path.exists(direct):
            return True, os.path.abspath(direct)

    fallback = os.path.join(models_root, base_name)
    if os.path.exists(fallback):
        return True, os.path.abspath(fallback)

    return False, None


def _build_model_index(models_root: str) -> Dict[str, List[str]]:
    index: Dict[str, List[str]] = {}
    for root, _dirs, files in os.walk(models_root):
        rel_root = os.path.relpath(root, models_root)
        if rel_root == ".":
            depth = 0
        else:
            depth = rel_root.count(os.sep) + 1
        if depth > 3:
            continue
        for file_name in files:
            lowered = file_name.lower()
            index.setdefault(lowered, []).append(os.path.join(root, file_name))
    return index


def _lookup_model_in_index(
    index: Optional[Dict[str, List[str]]],
    reference: Dict[str, str],
) -> Tuple[bool, Optional[str]]:
    if not index:
        return False, None
    name = reference.get("name") or ""
    normalized = name.replace("/", os.sep).replace("\\", os.sep)
    base_name = os.path.basename(normalized)
    if base_name != normalized:
        return False, None
    lowered = base_name.lower()
    matches = index.get(lowered)
    if matches:
        return True, os.path.abspath(matches[0])
    return False, None



def _normalize_workflow_entry(value: str) -> str:
    normalized = (value or "").replace("\\", "/")
    if os.sep == "\\":
        return normalized.replace("/", "\\")
    return normalized

def _derive_workflow_value_from_path(
    path_value: Optional[str],
    signature: Optional[Tuple[Optional[str], Optional[str], Optional[str]]],
    models_root: str,
    comfy_dir: Optional[str],
) -> Optional[str]:
    if not path_value:
        return None
    abs_path = os.path.abspath(path_value)
    category = None
    if signature and len(signature) >= 2:
        category = signature[1]
    if category:
        category_root = os.path.join(models_root, category)
        if os.path.isdir(category_root):
            try:
                rel = os.path.relpath(abs_path, category_root)
                if not rel.startswith('..'):
                    return _normalize_workflow_entry(rel)
            except ValueError:
                pass
    if models_root and os.path.isdir(models_root):
        try:
            rel = os.path.relpath(abs_path, models_root)
            if not rel.startswith('..'):
                return _normalize_workflow_entry(rel)
        except ValueError:
            pass
    if comfy_dir:
        try:
            rel = os.path.relpath(abs_path, comfy_dir)
            if not rel.startswith('..'):
                return _normalize_workflow_entry(rel)
        except ValueError:
            pass
    return _normalize_workflow_entry(abs_path)

def _filter_missing_with_resolved_cache(
    missing: Iterable[Dict[str, Any]],
    resolved_entries: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    resolved_signatures: set[Tuple[Optional[str], Optional[str], Optional[str]]] = set()
    resolved_names: set[str] = set()

    for entry in resolved_entries or []:
        if not isinstance(entry, dict):
            continue
        signature = entry.get("signature")
        if isinstance(signature, (list, tuple)) and len(signature) == 3:
            resolved_signatures.add(tuple(signature))  # type: ignore[arg-type]
        reference_name = entry.get("reference")
        if isinstance(reference_name, str) and reference_name:
            resolved_names.add(reference_name)
        workflow_value = entry.get("workflow_value")
        if isinstance(workflow_value, str) and workflow_value:
            resolved_names.add(workflow_value)

    filtered: List[Dict[str, Any]] = []
    for item in missing or []:
        if not isinstance(item, dict):
            continue
        signature = (
            item.get("name"),
            item.get("category"),
            item.get("node_type"),
        )
        if signature in resolved_signatures:
            continue
        name_value = item.get("name")
        if isinstance(name_value, str) and name_value in resolved_names:
            continue
        filtered.append(item)
    return filtered


def _resolved_path_matches_reference(
    reference_name: Optional[str],
    resolved_path: str,
    models_root: str,
) -> bool:
    reference_name = (reference_name or "").strip()
    if not reference_name:
        return True

    normalized = reference_name.replace("\\", "/").strip("/")
    if not normalized:
        return True

    if normalized.lower().startswith("models/"):
        normalized = normalized[7:].strip("/")

    # Only enforce subdirectory matches when the reference includes a slash.
    if "/" not in normalized:
        return True

    if not models_root:
        return True

    resolved_path = os.path.abspath(resolved_path)
    models_root_abs = os.path.abspath(models_root)

    try:
        reference_rel = os.path.relpath(resolved_path, models_root_abs)
    except ValueError:
        reference_rel = resolved_path

    reference_rel = reference_rel.replace("\\", "/").strip("/")
    return reference_rel.lower().endswith(normalized.lower())


def _extract_workflow_context(
    workflow_bundle: Optional[Dict[str, Any]],
) -> Dict[str, Optional[str]]:
    if not isinstance(workflow_bundle, dict):
        return {"folder": None, "name": None}
    folder = workflow_bundle.get("folder")
    metadata = workflow_bundle.get("metadata") or {}
    workflow_name = None
    if isinstance(metadata, dict):
        charon_meta = metadata.get("charon_meta") or {}
        if isinstance(charon_meta, dict):
            workflow_name = charon_meta.get("workflow_file")
    if not workflow_name and folder:
        workflow_name = os.path.basename(folder)
    return {"folder": folder, "name": workflow_name}


def _cache_key_for_path(path: str) -> str:
    normalized = os.path.normpath(path.strip()) if path else ""
    return hashlib.sha1(normalized.encode("utf-8", errors="ignore")).hexdigest()


def _load_cache() -> Dict[str, Any]:
    prefs = preferences.load_preferences()
    cache = prefs.get(CACHE_KEY)
    if isinstance(cache, dict):
        return dict(cache)
    return {}


def _write_cache(cache: Dict[str, Any]) -> None:
    prefs = preferences.load_preferences()
    prefs[CACHE_KEY] = cache
    preferences.save_preferences(prefs)
