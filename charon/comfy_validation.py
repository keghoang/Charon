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
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from . import preferences
from .charon_logger import system_debug, system_error, system_info, system_warning
from .comfy_client import ComfyUIClient
from .paths import get_charon_temp_dir, resolve_comfy_environment
from .validation_resolver import locate_manager_cli
from .validation_cache import load_validation_log


DEFAULT_PING_URL = "http://127.0.0.1:8188"
CACHE_KEY = "comfy_validation_cache"
BANNER_PREF_KEY = "comfy_validator_banner_dismissed"
CACHE_TTL_SECONDS = 900  # 15 minutes
MODEL_EXTENSIONS = (".ckpt", ".safetensors", ".pth", ".pt", ".bin", ".onnx", ".yaml")
MODEL_CATEGORY_PREFIXES = {
    "diffusion_models",
    "checkpoints",
    "unet",
    "unets",
    "text_encoders",
    "text-encoders",
    "clip",
    "clip_vision",
    "clip-vision",
    "loras",
    "vae",
    "vae_approx",
    "vae-approx",
    "embeddings",
    "controlnet",
    "hypernetworks",
    "upscale_models",
    "upscale",
    "motion_models",
    "motion_loras",
    "styles",
    "style_models",
    "ipadapter",
}
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

BROWSER_VALIDATOR_SCRIPT = r"""import asyncio
import json
import sys

WORKFLOW_PATH = sys.argv[1]
MODE = sys.argv[2] if len(sys.argv) > 2 else "cache"

async def main():
    try:
        from pathlib import Path
        from playwright.async_api import async_playwright
    except Exception as exc:
        print(json.dumps({"error": f"Playwright import failed: {exc}"}))
        return

    try:
        workflow = json.loads(Path(WORKFLOW_PATH).read_text(encoding="utf-8"))
    except Exception as exc:
        print(json.dumps({"error": f"Workflow read failed: {exc}"}))
        return

    result = {
        "missing": [],
        "registered_count": 0,
        "nodepack_count": 0,
        "missing_models": [],
        "model_paths": {},
        "model_capture": {"invoked": False},
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto("http://127.0.0.1:8188", wait_until="load", timeout=120000)
            await page.wait_for_function(
                "window.comfyAPI && window.comfyAPI.app && window.comfyAPI.app.app && window.comfyAPI.app.app.graph",
                timeout=120000,
            )
            await page.wait_for_function(
                "window.LiteGraph && window.LiteGraph.registered_node_types && Object.keys(window.LiteGraph.registered_node_types).length > 0",
                timeout=240000,
            )
            # Allow extensions to finish wiring up.
            await page.wait_for_timeout(1000)

            payload = await page.evaluate(
                '''async ({ workflow, mode }) => {
                    const app = window.comfyAPI.app.app;

                    const capturedModels = { items: null, paths: null, seen: false };
                    const clone = (value) => {
                        try {
                            return JSON.parse(JSON.stringify(value));
                        } catch (err) {
                            return value;
                        }
                    };
                    const captureMissing = (missingModels, paths) => {
                        capturedModels.seen = true;
                        if (capturedModels.items === null && Array.isArray(missingModels)) {
                            capturedModels.items = missingModels.map((item) => ({ ...(item || {}) }));
                        }
                        if (capturedModels.paths === null && paths && typeof paths === "object") {
                            capturedModels.paths = clone(paths);
                        }
                    };
                    const wrapMissing = (owner, attr) => {
                        if (!owner || typeof owner[attr] !== "function") return;
                        const original = owner[attr].bind(owner);
                        owner[attr] = (...args) => {
                            try {
                                captureMissing(args[0], args[1]);
                            } catch (err) {}
                            try {
                                return original(...args);
                            } catch (err) {
                                return undefined;
                            }
                        };
                    };

                    const dialogService = app?.dialogService || window.comfyAPI?.app?.dialogService || null;
                    wrapMissing(dialogService, "showMissingModelsWarning");
                    wrapMissing(app, "showMissingModelsError");
                    wrapMissing(app, "showMissingModelsWarning");

                    const graphData = await app.loadGraphData(workflow, true);

                    let resolvedMissingModels = capturedModels.items;
                    let resolvedPaths = capturedModels.paths;
                    if (!resolvedMissingModels && graphData && Array.isArray(graphData?.missing_models)) {
                        resolvedMissingModels = graphData.missing_models;
                    } else if (!resolvedMissingModels && graphData && Array.isArray(graphData?.models_missing)) {
                        resolvedMissingModels = graphData.models_missing;
                    }
                    if (!resolvedPaths && graphData && graphData?.model_paths && typeof graphData.model_paths === "object") {
                        resolvedPaths = graphData.model_paths;
                    }
                    if (!resolvedMissingModels && typeof app.getMissingModelsFromGraph === "function") {
                        try {
                            const data = await app.getMissingModelsFromGraph(workflow);
                            if (data) {
                                if (!resolvedMissingModels && Array.isArray(data.missing)) {
                                    resolvedMissingModels = data.missing.map((item) => ({ ...(item || {}) }));
                                }
                                if (!resolvedPaths && data.paths && typeof data.paths === "object") {
                                    resolvedPaths = clone(data.paths);
                                }
                            }
                        } catch (err) {}
                    }

                    const registry = window.LiteGraph?.registered_node_types || {};
                    const registered = new Set(Object.keys(registry));

                    const nodesArray = Array.isArray(workflow?.nodes)
                        ? workflow.nodes
                        : Array.isArray(workflow)
                            ? workflow
                            : Object.values(workflow?.nodes || workflow || {});

                    let nodePacks = {};
                    try {
                        const res = await fetch(`/customnode/getlist?mode=${mode}`);
                        if (res.ok) {
                            const data = await res.json();
                            if (data && data.node_packs) nodePacks = data.node_packs;
                        }
                    } catch (err) {}

                    let packMeta = {};
                    for (const packId in nodePacks) {
                        const pack = nodePacks[packId];
                        packMeta[packId] = {
                            title: pack?.title || pack?.name || packId,
                            author: pack?.author || "",
                            last_update: pack?.last_update || "",
                        };
                    }

                    let mappings = {};
                    try {
                        const res = await fetch(`/customnode/getmappings?mode=${mode}`);
                        if (res.ok) {
                            mappings = await res.json();
                        }
                    } catch (err) {}

                    // Build name -> packIds from mappings
                    const nameToPacks = {};
                    for (const url in mappings) {
                        const names = mappings[url];
                        if (Array.isArray(names) && names.length > 0) {
                            const arr = names[0];
                            if (Array.isArray(arr)) {
                                for (const n of arr) {
                                    if (typeof n === "string") {
                                        if (!nameToPacks[n]) nameToPacks[n] = [];
                                        nameToPacks[n].push(url);
                                    }
                                }
                            }
                        }
                    }

                    // Build regex -> pack from nodename_pattern
                    const regexToPack = [];
                    for (const packId in nodePacks) {
                        const pack = nodePacks[packId];
                        if (pack?.nodename_pattern) {
                            try {
                                regexToPack.push({
                                    regex: new RegExp(pack.nodename_pattern),
                                    url: pack.files?.[0] || pack.repository || packId,
                                });
                            } catch (err) {}
                        }
                    }

                    const packToRepo = {};
                    const auxToRepo = {};
                    for (const packId in nodePacks) {
                        const pack = nodePacks[packId];
                        const repo = pack?.repository || pack?.files?.[0];
                        if (repo) {
                            packToRepo[packId] = repo;
                            if (repo.startsWith("https://github.com/")) {
                                const parts = repo.split("/").filter(Boolean);
                                const org = parts[parts.length - 2];
                                const name = parts[parts.length - 1];
                                if (org && name) auxToRepo[`${org}/${name}`] = repo;
                            }
                        }
                    }

                    const missing = [];
                    for (const node of nodesArray) {
                        if (!node || typeof node !== "object") continue;
                        const cls = node.type || node.class_type;
                        if (!cls) continue;
                        if (!registered.has(cls)) {
                            const aux = node.properties?.aux_id || node.properties?.cnr_id || null;
                            let packIds = nameToPacks[cls] || [];
                            if (packIds.length === 0) {
                                for (const entry of regexToPack) {
                                    try {
                                        if (entry.regex.test(cls)) {
                                            packIds.push(entry.url);
                                        }
                                    } catch (err) {}
                                }
                            }
                            const repos = [];
                            for (const pid of packIds) {
                                const repo = packToRepo[pid] || pid;
                                if (repo) repos.push(repo);
                            }
                            let repo = aux ? auxToRepo[aux] || null : null;
                            if (!repo && repos.length) repo = repos[0];
                            missing.push({
                                id: node.id ?? null,
                                class_type: cls,
                                aux_id: aux,
                                repo,
                                pack_ids: packIds,
                                pack_meta: packIds.map(pid => packMeta[pid] || {}),
                            });
                        }
                    }

                    return {
                        missing,
                        registered_count: registered.size,
                        nodepack_count: Object.keys(nodePacks).length,
                        pack_meta: packMeta,
                        missing_models: resolvedMissingModels || [],
                        model_paths: resolvedPaths || {},
                        model_capture: {
                            invoked: capturedModels.seen || Array.isArray(resolvedMissingModels),
                        },
                    };
                }''',
                {"workflow": workflow, "mode": MODE},
            )
            result.update(payload or {})
        except Exception as exc:
            result["error"] = str(exc)
        finally:
            await browser.close()

    print(json.dumps(result, indent=2))

asyncio.run(main())
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
            "comfy_path": self.comfy_path,
            "issues": [issue.to_dict() for issue in self.issues],
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
            started_at=0.0,
            finished_at=0.0,
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
    include_environment: bool = True,
) -> ValidationResult:
    comfy_path = (comfy_path or "").strip()
    started = time.time()
    cache_key = _cache_key_for_path(comfy_path)
    result_comfy_path = comfy_path if include_environment else ""

    workflow_info = _extract_workflow_context(workflow_bundle)
    issues: List[ValidationIssue] = []

    if include_environment and not comfy_path:
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
        result = ValidationResult(
            comfy_path=result_comfy_path,
            issues=issues,
            started_at=0.0,
            finished_at=0.0,
            cache_key=cache_key,
            workflow_folder=workflow_info.get("folder"),
            workflow_name=workflow_info.get("name"),
        )
        _write_validation_debug_payload(result)
        return result

    env_info = resolve_comfy_environment(comfy_path)
    if include_environment:
        result_comfy_path = env_info.get("comfy_dir") or result_comfy_path
    if include_environment:
        issues.append(_validate_environment(comfy_path, env_info))
    custom_nodes_issue, browser_payload = _validate_custom_nodes_browser(env_info, workflow_bundle)
    issues.append(custom_nodes_issue)
    issues.append(_validate_models_browser(env_info, workflow_bundle, browser_payload))

    result = ValidationResult(
        comfy_path=result_comfy_path,
        issues=issues,
        started_at=0.0,
        finished_at=0.0,
        cache_key=cache_key,
        workflow_folder=workflow_info.get("folder"),
        workflow_name=workflow_info.get("name"),
    )

    if comfy_path:
        store_validation_result(result)
    _write_validation_debug_payload(result)
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


def _write_validation_debug_payload(result: ValidationResult) -> None:
    """Persist the full validation payload for troubleshooting."""
    try:
        base_dir = get_charon_temp_dir()
        debug_dir = os.path.join(base_dir, "debug")
        os.makedirs(debug_dir, exist_ok=True)
        timestamp = int(time.time())
        slug = result.cache_key[:12] or "no_path"
        path = os.path.join(debug_dir, f"validation_payload_{timestamp}_{slug}.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(result.to_dict(), handle, indent=2)
        system_debug(f"Wrote validation payload to {path}")
    except Exception as exc:  # pragma: no cover - defensive logging
        system_warning(f"Failed to write validation payload: {exc}")


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


def _validate_custom_nodes_browser(
    env_info: Dict[str, Any],
    workflow_bundle: Optional[Dict[str, Any]],
    *,
    mode: str = "cache",
) -> Tuple[ValidationIssue, Optional[Dict[str, Any]]]:
    python_exe = env_info.get("python_exe")
    comfy_dir = env_info.get("comfy_dir")
    payload: Optional[Dict[str, Any]] = None
    if not python_exe or not os.path.exists(python_exe):
        return ValidationIssue(
            key="custom_nodes",
            label="Custom nodes loaded",
            ok=False,
            summary="Embedded python not found; cannot validate custom nodes.",
            details=["Repair the embedded python environment and retry."],
        ), payload
    if not comfy_dir or not os.path.isdir(comfy_dir):
        return ValidationIssue(
            key="custom_nodes",
            label="Custom nodes loaded",
            ok=False,
            summary="ComfyUI directory missing; cannot validate custom nodes.",
            details=["Fix the ComfyUI path first."],
        ), payload

    workflow = workflow_bundle.get("workflow") if isinstance(workflow_bundle, dict) else None
    if not isinstance(workflow, dict):
        return ValidationIssue(
            key="custom_nodes",
            label="Custom nodes loaded",
            ok=True,
            summary="No workflow selected; skipping custom node validation.",
            details=[],
        ), payload

    temp_dir = tempfile.mkdtemp(prefix="charon_browser_validate_")
    try:
        workflow_path = os.path.join(temp_dir, "workflow.json")
        script_path = os.path.join(temp_dir, "browser_validate.py")

        with open(workflow_path, "w", encoding="utf-8") as handle:
            json.dump(workflow, handle)
        with open(script_path, "w", encoding="utf-8") as handle:
            handle.write(BROWSER_VALIDATOR_SCRIPT)

        command = [python_exe, script_path, workflow_path, mode]
        system_debug(f"Running browser validator: {command}")
        try:
            completed = subprocess.run(
                command,
                cwd=comfy_dir,
                capture_output=True,
                text=True,
                timeout=180,
            )
        except subprocess.TimeoutExpired:
            return ValidationIssue(
                key="custom_nodes",
                label="Custom nodes loaded",
                ok=False,
                summary="Playwright validation timed out.",
                details=["Ensure ComfyUI is running and reachable on 127.0.0.1:8188."],
            ), payload

        stdout = completed.stdout.strip()
        stderr = completed.stderr.strip()
        if completed.returncode != 0:
            detail = stderr or stdout or f"Exited with code {completed.returncode}"
            system_warning(f"Browser validator failed: {detail}")
            return ValidationIssue(
                key="custom_nodes",
                label="Custom nodes loaded",
                ok=False,
                summary="Playwright validation failed.",
                details=[detail],
            ), payload

        try:
            payload = json.loads(stdout or "{}")
        except json.JSONDecodeError:
            system_warning("Browser validator returned non-JSON output.")
            return ValidationIssue(
                key="custom_nodes",
                label="Custom nodes loaded",
                ok=False,
                summary="Playwright validation returned invalid JSON.",
                details=[stdout[:500]],
            ), payload

        if payload.get("error"):
            return ValidationIssue(
                key="custom_nodes",
                label="Custom nodes loaded",
                ok=False,
                summary="Playwright validation errored.",
                details=[str(payload.get("error"))],
                data=payload,
            ), payload

        missing = payload.get("missing") or []
        registered = payload.get("registered_count")
        nodepack_count = payload.get("nodepack_count")
        pack_meta = payload.get("pack_meta") or {}
        # Normalize data for UI expectations.
        missing_nodes: List[str] = []
        node_repos: Dict[str, str] = {}
        node_packages: Dict[str, str] = {}
        missing_repos: List[str] = []
        node_meta: Dict[str, Dict[str, Any]] = {}
        unique_missing: List[Dict[str, Any]] = []
        pack_blocks: Dict[str, Dict[str, Any]] = {}
        seen_classes: set[str] = set()
        for entry in missing:
            cls = str(entry.get("class_type") or "").strip()
            if not cls:
                continue
            lowered = cls.lower()
            if lowered in seen_classes:
                continue
            seen_classes.add(lowered)
            unique_missing.append(entry)
        for entry in unique_missing:
            cls = str(entry.get("class_type") or "").strip()
            if not cls:
                continue
            missing_nodes.append(cls)
            repo = entry.get("repo")
            pack_ids = entry.get("pack_ids") or []
            pack_metas = entry.get("pack_meta") or []
            meta_entry: Dict[str, Any] = {}
            if pack_ids:
                meta_entry["pack_ids"] = list(pack_ids)
            # Prefer meta passed per-entry, fallback to pack_meta mapping.
            candidate_meta = None
            for meta in pack_metas:
                if isinstance(meta, dict):
                    candidate_meta = meta
                    break
            if not candidate_meta:
                for pid in pack_ids:
                    meta = pack_meta.get(pid) if isinstance(pack_meta, dict) else None
                    if isinstance(meta, dict):
                        candidate_meta = meta
                        break
            if isinstance(candidate_meta, dict):
                meta_entry["package_display"] = candidate_meta.get("title") or ""
                meta_entry["author"] = candidate_meta.get("author") or ""
                meta_entry["last_update"] = candidate_meta.get("last_update") or ""
            if repo:
                lower = cls.lower()
                node_repos[lower] = repo
                node_packages[lower] = meta_entry.get("package_display") or _display_name_for_repo(repo)
                if repo not in missing_repos:
                    missing_repos.append(repo)
            if meta_entry:
                node_meta[cls.lower()] = meta_entry

            pack_id = pack_ids[0] if pack_ids else ""
            pack_key = pack_id or repo or cls
            pack_block = pack_blocks.get(pack_key)
            if not pack_block:
                pack_block = {
                    "pack": pack_id,
                    "repo": repo,
                    "pack_meta": candidate_meta if isinstance(candidate_meta, dict) else {},
                    "resolve_status": "",
                    "resolve_method": "",
                    "resolve_failed": "",
                    "nodes": [],
                }
                pack_blocks[pack_key] = pack_block
            pack_block["nodes"].append(
                {
                    "class_type": cls,
                    "id": entry.get("id"),
                }
            )

        data = {
            "missing": list(pack_blocks.values()),
            "registered_count": registered,
            "nodepack_count": nodepack_count,
        }

        if missing_nodes:
            detail_lines = []
            for entry in unique_missing:
                cls = entry.get("class_type") or "Unknown node"
                repo = entry.get("repo")
                pack_ids = entry.get("pack_ids") or []
                aux_id = entry.get("aux_id")
                detail = f"{cls}"
                if repo:
                    detail += f" -> {repo}"
                elif pack_ids:
                    detail += f" -> {', '.join(pack_ids)}"
                if aux_id:
                    detail += f" (aux_id: {aux_id})"
                detail_lines.append(detail)
            return ValidationIssue(
                key="custom_nodes",
                label="Custom nodes loaded",
                ok=False,
                summary=f"Missing {len(missing_nodes)} custom node(s).",
                details=detail_lines,
                data=data,
            ), payload

        summary = "All custom nodes registered in the active ComfyUI session."
        if registered:
            summary += f" ({registered} node types loaded.)"
        return ValidationIssue(
            key="custom_nodes",
            label="Custom nodes loaded",
            ok=True,
            summary=summary,
            details=[],
            data=data,
        ), payload
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _validate_models_browser(
    env_info: Dict[str, Any],
    workflow_bundle: Optional[Dict[str, Any]],
    browser_payload: Optional[Dict[str, Any]],
) -> ValidationIssue:
    def _normalize_model_paths(raw_paths: Dict[str, Any], models_root: str, comfy_dir: Optional[str]) -> Dict[str, List[str]]:
        expected = {
            "audio_encoders",
            "checkpoints",
            "classifiers",
            "clip_vision",
            "configs",
            "controlnet",
            "custom_nodes",
            "diffusers",
            "diffusion_models",
            "embeddings",
            "gligen",
            "hypernetworks",
            "latent_upscale_models",
            "loras",
            "model_patches",
            "photomaker",
            "style_models",
            "text_encoders",
            "upscale_models",
            "vae",
            "vae_approx",
        }
        comfy_dir = comfy_dir or ""
        models_root_abs = os.path.abspath(models_root) if models_root else ""
        normalized: Dict[str, List[str]] = {}
        for key, value in (raw_paths or {}).items():
            if not isinstance(key, str) or key not in expected:
                continue
            if isinstance(value, (list, tuple, set)):
                paths: List[str] = []
                for item in value:
                    if not isinstance(item, str):
                        continue
                    abs_item = os.path.abspath(item if os.path.isabs(item) else os.path.join(models_root_abs, item))
                    try:
                        rel = os.path.relpath(abs_item, models_root_abs)
                        if models_root_abs and rel and not rel.startswith(".."):
                            paths.append(rel.replace("\\", "/"))
                            continue
                    except ValueError:
                        pass
                    paths.append(abs_item)
                if paths:
                    normalized[key] = paths
        # Fallback: scan models_root for subdirectories when browser payload is sparse.
        if models_root_abs and os.path.isdir(models_root_abs):
            try:
                for entry in os.scandir(models_root_abs):
                    if entry.is_dir():
                        rel = os.path.relpath(entry.path, models_root_abs).replace("\\", "/")
                        normalized.setdefault(entry.name, [rel])
            except Exception:
                pass

        # Ensure custom_nodes root is present if it exists
        custom_nodes_root = os.path.join(comfy_dir, "custom_nodes")
        if os.path.isdir(custom_nodes_root):
            normalized.setdefault("custom_nodes", [os.path.abspath(custom_nodes_root)])
        return normalized

    comfy_dir = env_info.get("comfy_dir")
    python_exe = env_info.get("python_exe")
    models_root = os.path.join(comfy_dir, "models") if comfy_dir else ""
    data: Dict[str, Any] = {
        "models_root": models_root,
        "found": [],
    }

    ignored_roots: List[str] = []
    if comfy_dir:
        # Avoid surfacing transient output directories as attempted search paths.
        ignored_roots.append(os.path.abspath(os.path.join(comfy_dir, "output")))

    def _is_within_roots(candidate: str, roots: Iterable[str]) -> bool:
        candidate = (candidate or "").strip()
        if not candidate:
            return False
        try:
            candidate_abs = os.path.abspath(candidate)
        except Exception:
            return False
        for root in roots or []:
            if not root:
                continue
            try:
                root_abs = os.path.abspath(root)
                if os.path.commonpath([candidate_abs, root_abs]) == root_abs:
                    return True
            except Exception:
                continue
        return False

    def _is_ignored_dir(candidate: str) -> bool:
        candidate = (candidate or "").strip()
        if not candidate:
            return False
        try:
            candidate_abs = os.path.abspath(candidate)
        except Exception:
            return False
        for root in ignored_roots:
            if not root:
                continue
            try:
                root_abs = os.path.abspath(root)
                if os.path.commonpath([candidate_abs, root_abs]) == root_abs:
                    return True
            except Exception:
                continue
        return False

    allowed_roots = [models_root, comfy_dir]

    if not python_exe or not os.path.exists(python_exe):
        return ValidationIssue(
            key="models",
            label="Models available",
            ok=False,
            summary="Embedded python not found; cannot validate models.",
            details=["Repair the embedded python environment and retry."],
            data=data,
        )
    if not comfy_dir or not os.path.isdir(comfy_dir):
        return ValidationIssue(
            key="models",
            label="Models available",
            ok=False,
            summary="ComfyUI directory missing; cannot validate models.",
            details=["Fix the ComfyUI path first."],
            data=data,
        )

    workflow = workflow_bundle.get("workflow") if isinstance(workflow_bundle, dict) else None
    if not isinstance(workflow, dict):
        return ValidationIssue(
            key="models",
            label="Models available",
            ok=True,
            summary="No workflow selected; skipping model validation.",
            details=[],
            data=data,
        )

    if not browser_payload:
        return _validate_models(env_info, workflow_bundle)

    capture_info = browser_payload.get("model_capture") if isinstance(browser_payload, dict) else {}
    capture_invoked = bool(capture_info.get("invoked")) if isinstance(capture_info, dict) else False
    missing_models = browser_payload.get("missing_models") if isinstance(browser_payload, dict) else None
    if missing_models is None and not capture_invoked:
        return _validate_models(env_info, workflow_bundle)

    raw_model_paths = browser_payload.get("model_paths") if isinstance(browser_payload, dict) else {}
    normalized_paths = _normalize_model_paths(raw_model_paths if isinstance(raw_model_paths, dict) else {}, models_root, comfy_dir)
    data["model_paths"] = normalized_paths
    data["model_capture"] = capture_info if isinstance(capture_info, dict) else {}

    if not isinstance(missing_models, list):
        missing_models = []

    missing_entries: List[Dict[str, Any]] = []
    for model_entry in missing_models:
        if not isinstance(model_entry, dict):
            continue
        raw_entry = dict(model_entry)
        name_value = str(
            raw_entry.get("name")
            or raw_entry.get("path")
            or raw_entry.get("file")
            or ""
        ).strip()
        directory_value = str(raw_entry.get("directory") or raw_entry.get("folder") or "").strip()
        folder_path = raw_entry.get("folder_path") or raw_entry.get("resolved_path") or raw_entry.get("path")

        entry: Dict[str, Any] = {
            "name": name_value,
            "category": directory_value or None,
            "node_type": raw_entry.get("node_type") or raw_entry.get("node"),
        }
        url_value = raw_entry.get("url")
        if isinstance(url_value, str) and url_value:
            entry["url"] = url_value

        attempted_dirs: List[str] = []
        if isinstance(folder_path, str) and folder_path:
            attempted_dirs.append(folder_path)
        if directory_value:
            entry["category"] = directory_value
            attempted_dirs.extend(normalized_paths.get(directory_value, []))
        if attempted_dirs:
            filtered_dirs = []
            for path in attempted_dirs:
                abs_path = os.path.abspath(path if os.path.isabs(path) else os.path.join(models_root, path))
                if _is_within_roots(abs_path, allowed_roots) and not _is_ignored_dir(abs_path):
                    filtered_dirs.append(abs_path)
            if filtered_dirs:
                entry["attempted_directories"] = filtered_dirs
        if raw_entry.get("directory_invalid") is True:
            entry["directory_invalid"] = True

        missing_entries.append(entry)

    workflow_folder = workflow_bundle.get("folder") if isinstance(workflow_bundle, dict) else None
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

    if cached_resolved_entries:
        data["resolved_entries"] = list(cached_resolved_entries)
        found = data.get("found") or []
        for entry in cached_resolved_entries:
            path_value = entry.get("path")
            if isinstance(path_value, str) and path_value and path_value not in found:
                found.append(path_value)
        data["found"] = found
        missing_entries = _filter_missing_with_resolved_cache(missing_entries, cached_resolved_entries)

    data["missing"] = missing_entries

    if missing_entries:
        detail_lines = []
        for entry in missing_entries:
            name_value = entry.get("name") or entry.get("folder_path") or "Model file"
            directory_value = entry.get("category") or ""
            folder_hint = entry.get("folder_path")
            url_value = entry.get("url")
            parts = [str(name_value)]
            if directory_value:
                parts.append(f"folder: {directory_value}")
            if folder_hint:
                parts.append(f"path: {folder_hint}")
            if entry.get("directory_invalid"):
                parts.append("directory invalid")
            if url_value:
                parts.append(f"url: {url_value}")
            detail_lines.append(" | ".join(parts))
        return ValidationIssue(
            key="models",
            label="Models available",
            ok=False,
            summary=f"Missing {len(missing_entries)} model file(s).",
            details=detail_lines,
            data=data,
        )

    return ValidationIssue(
        key="models",
        label="Models available",
        ok=True,
        summary="All required model files reported by ComfyUI.",
        details=[],
        data=data,
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

    located_cli = locate_manager_cli(comfy_dir)
    if not located_cli:
        return ValidationIssue(
            key="custom_nodes",
            label="Custom nodes loaded",
            ok=False,
            summary="ComfyUI Manager is not installed.",
            details=["Install comfyui-manager to enable dependency inspection."],
        )
    manager_cli, manager_root = located_cli
    _refresh_manager_catalog(manager_root)

    workflow = workflow_bundle.get("workflow") if isinstance(workflow_bundle, dict) else None
    if not isinstance(workflow, dict):
        return ValidationIssue(
            key="custom_nodes",
            label="Custom nodes loaded",
            ok=True,
            summary="Workflow structure missing; skipping custom node validation.",
        )

    temp_dir = tempfile.mkdtemp(prefix="charon_manager_validate_")
    try:
        workflow_path = os.path.join(temp_dir, "workflow.json")
        output_path = os.path.join(temp_dir, "dependencies.json")

        with open(workflow_path, "w", encoding="utf-8") as handle:
            json.dump(workflow, handle)

        command = [
            python_exe,
            manager_cli,
            "deps-in-workflow",
            "--workflow",
            workflow_path,
            "--output",
            output_path,
            "--mode",
            "local",
        ]
        env = os.environ.copy()
        env.setdefault("COMFYUI_PATH", comfy_dir)
        env.setdefault("COMFYUI_FOLDERS_BASE_PATH", comfy_dir)
        system_debug(f"Running ComfyUI Manager dependency scan: {command}")
        completed = subprocess.run(
            command,
            cwd=comfy_dir,
            capture_output=True,
            timeout=180,
            text=True,
            env=env,
        )

        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            system_warning(
                f"ComfyUI Manager dependency scan returned code {completed.returncode}: {detail}"
            )
            return ValidationIssue(
                key="custom_nodes",
                label="Custom nodes loaded",
                ok=False,
                summary="ComfyUI Manager failed to inspect dependencies.",
                details=[detail or "Check the console for details."],
            )

        if not os.path.exists(output_path):
            system_warning("ComfyUI Manager dependency scan did not produce a result file.")
            return ValidationIssue(
                key="custom_nodes",
                label="Custom nodes loaded",
                ok=False,
                summary="ComfyUI Manager did not produce dependency results.",
                details=["Inspect the console output for errors."],
            )

        with open(output_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)

        dependencies = payload.get("custom_nodes") or {}
        unknown_nodes = sorted(payload.get("unknown_nodes") or [])
        aux_repos = _collect_aux_repos(workflow_bundle)
        unknown_matches = _match_unknown_nodes_to_installed(unknown_nodes, comfy_dir)
        catalog_matches = _match_unknown_nodes_to_catalog(unknown_nodes, manager_root)
        aux_matches = _match_unknown_nodes_to_aux(unknown_nodes, aux_repos)
        if unknown_matches:
            resolved = set(unknown_matches.keys())
            unknown_nodes = [name for name in unknown_nodes if name not in resolved]
        if catalog_matches:
            resolved = set(catalog_matches.keys())
            unknown_nodes = [name for name in unknown_nodes if name not in resolved]
        if aux_matches:
            resolved = set(aux_matches.keys())
            unknown_nodes = [name for name in unknown_nodes if name not in resolved]
        missing = []
        disabled = []
        for repo, meta in dependencies.items():
            state = (meta or {}).get("state", "").lower()
            if state == "not-installed":
                missing.append(repo)
            elif state == "disabled":
                disabled.append(repo)

        extension_map = _load_manager_extension_map(manager_root)
        node_repo_map = _build_node_repo_map(required, extension_map)
        # Use catalog matches to map unknown classes to known repositories.
        for node_name, repo in catalog_matches.items():
            key = str(node_name or "").strip().lower()
            if not key:
                continue
            node_repo_map.setdefault(
                key,
                {
                    "repo": repo,
                    "display": _display_name_for_repo(repo),
                },
            )
            missing.append(repo)
        for node_name, repo in aux_matches.items():
            key = str(node_name or "").strip().lower()
            if not key:
                continue
            node_repo_map.setdefault(
                key,
                {
                    "repo": repo,
                    "display": _display_name_for_repo(repo),
                },
            )
            missing.append(repo)
        # Also seed mappings directly from aux_id hints even if cm-cli didn't flag the node as unknown.
        for node_name, repo in aux_repos.items():
            key = str(node_name or "").strip().lower()
            if not key:
                continue
            node_repo_map.setdefault(
                key,
                {
                    "repo": repo,
                    "display": _display_name_for_repo(repo),
                },
            )
            missing.append(repo)
        # Preserve inferred mappings for unknown nodes that match installed folders.
        for node_name, folder in unknown_matches.items():
            key = str(node_name or "").strip().lower()
            if key and key not in node_repo_map:
                node_repo_map[key] = {
                    "repo": folder,
                    "display": folder,
                }
        package_overrides = {
            key: entry.get("display")
            for key, entry in node_repo_map.items()
            if entry.get("display")
        }
        node_repo_lookup = {
            key: entry.get("repo")
            for key, entry in node_repo_map.items()
            if entry.get("repo")
        }
        missing_repo_keys = {_normalize_repo_url(repo) for repo in missing}
        disabled_repo_keys = {_normalize_repo_url(repo) for repo in disabled}
        missing_node_types = _derive_missing_node_types(
            required,
            node_repo_map,
            missing_repo_keys,
            disabled_repo_keys,
            unknown_nodes,
            IGNORED_NODE_TYPES,
        )

        data = {
            "dependencies": dependencies,
            "unknown_nodes": unknown_nodes,
            "required": required,
            "missing": missing_node_types,
            "missing_repos": missing,
            "disabled_repos": disabled,
            "node_packages": package_overrides,
            "node_repos": node_repo_lookup,
            "aux_repos": aux_repos,
        }

        detail_lines: List[str] = []
        if missing:
            detail_lines.append("Missing custom node repositories:")
            for repo in missing:
                detail_lines.append(f"  - {_display_name_for_repo(repo)} ({repo})")
        if disabled:
            detail_lines.append("Disabled custom node repositories:")
            for repo in disabled:
                detail_lines.append(f"  - {_display_name_for_repo(repo)} ({repo})")
        if missing:
            detail_lines.append("  Use ComfyUI Manager (cm-cli install <repo>) to install missing repositories.")
        if disabled:
            detail_lines.append("  Enable disabled custom nodes inside ComfyUI Manager.")
        if unknown_matches:
            detail_lines.append("Resolved unknown node classes to installed custom node folders:")
            for node_name, folder in unknown_matches.items():
                detail_lines.append(f"  - {node_name} -> {folder}")
        if catalog_matches:
            detail_lines.append("Mapped unknown node classes to catalog entries:")
            for node_name, repo in catalog_matches.items():
                detail_lines.append(f"  - {node_name} -> {_display_name_for_repo(repo)} ({repo})")
        if aux_matches:
            detail_lines.append("Mapped unknown node classes via workflow aux_id:")
            for node_name, repo in aux_matches.items():
                detail_lines.append(f"  - {node_name} -> {_display_name_for_repo(repo)} ({repo})")
        if unknown_nodes:
            detail_lines.append("Unknown node classes:")
            detail_lines.extend(f"  - {name}" for name in unknown_nodes)
        if missing_node_types:
            detail_lines.append("Missing node classes:")
            detail_lines.extend(f"  - {name}" for name in missing_node_types)

        if missing or disabled or unknown_nodes:
            has_missing_repos = bool(missing_node_types or missing or disabled)
            summary_text = (
                f"Missing {len(missing_node_types)} custom node type(s)."
                if missing_node_types
                else (
                    "ComfyUI Manager detected missing custom node repositories."
                    if (missing or disabled)
                    else f"{len(unknown_nodes)} unknown custom node class(es) detected."
                )
            )
            issue_ok = not has_missing_repos
            return ValidationIssue(
                key="custom_nodes",
                label="Custom nodes loaded",
                ok=issue_ok,
                summary=summary_text,
                details=detail_lines,
                data=data,
            )

        return ValidationIssue(
            key="custom_nodes",
            label="Custom nodes loaded",
            ok=True,
            summary="ComfyUI Manager reports all custom nodes available.",
            details=[],
            data=data,
        )
    except subprocess.TimeoutExpired:
        return ValidationIssue(
            key="custom_nodes",
            label="Custom nodes loaded",
            ok=False,
            summary="ComfyUI Manager dependency scan timed out.",
            details=["Ensure the embedded python environment can launch within 60 seconds."],
        )
    except Exception as exc:  # pragma: no cover - defensive path
        system_error(f"ComfyUI Manager dependency scan failed: {exc}")
        return ValidationIssue(
            key="custom_nodes",
            label="Custom nodes loaded",
            ok=False,
            summary="ComfyUI Manager dependency scan crashed.",
            details=[str(exc)],
        )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _load_manager_extension_map(manager_root: str) -> Dict[str, Any]:
    if not manager_root:
        return {}
    candidate = os.path.join(manager_root, "node_db", "new", "extension-node-map.json")
    if not os.path.exists(candidate):
        return {}
    try:
        with open(candidate, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception as exc:  # pragma: no cover - defensive guard
        system_warning(f"Failed to read ComfyUI Manager extension map: {exc}")
        return {}
    return payload if isinstance(payload, dict) else {}


def _build_node_repo_map(
    required: Iterable[str],
    extension_map: Dict[str, Any],
) -> Dict[str, Dict[str, str]]:
    repo_lookup: Dict[str, str] = {}
    for repo_url, payload in (extension_map or {}).items():
        nodes: Iterable[Any] = []
        if isinstance(payload, list) and payload:
            nodes = payload[0] or []
        elif isinstance(payload, dict):
            nodes = payload.get("nodes") or []
        for node_name in nodes:
            key = str(node_name or "").strip().lower()
            if not key or key in repo_lookup:
                continue
            repo_lookup[key] = str(repo_url or "").strip()

    node_map: Dict[str, Dict[str, str]] = {}
    for node_name in required:
        normalized = str(node_name or "").strip()
        if not normalized:
            continue
        key = normalized.lower()
        repo_url = repo_lookup.get(key)
        if repo_url:
            node_map[key] = {
                "repo": repo_url,
                "display": _display_name_for_repo(repo_url),
            }
    return node_map


def _derive_missing_node_types(
    required: Iterable[str],
    node_repo_map: Dict[str, Dict[str, str]],
    missing_repo_keys: Iterable[str],
    disabled_repo_keys: Iterable[str],
    unknown_nodes: Iterable[str],
    ignored_nodes: Optional[Iterable[str]] = None,
) -> List[str]:
    missing_nodes: List[str] = []
    seen: set[str] = set()
    missing_repos = {repo for repo in missing_repo_keys if repo}
    disabled_repos = {repo for repo in disabled_repo_keys if repo}
    ignored = {str(item).strip().lower() for item in ignored_nodes or []}

    for node_name in required:
        normalized = str(node_name or "").strip()
        if not normalized:
            continue
        key = normalized.lower()
        repo_entry = node_repo_map.get(key) or {}
        repo_url = repo_entry.get("repo") or ""
        repo_key = _normalize_repo_url(repo_url)
        if repo_key and (repo_key in missing_repos or repo_key in disabled_repos):
            if normalized not in seen:
                missing_nodes.append(normalized)
                seen.add(normalized)

    for node_name in unknown_nodes or []:
        normalized = str(node_name or "").strip()
        key = normalized.lower()
        if normalized and key not in ignored and normalized not in seen:
            missing_nodes.append(normalized)
            seen.add(normalized)
    return missing_nodes


def _normalize_token(value: str) -> str:
    if not isinstance(value, str):
        return ""
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _refresh_manager_catalog(manager_root: str) -> None:
    """Ensure custom-node-list.json is refreshed from the upstream catalog."""
    if not manager_root:
        return
    local_path = os.path.join(manager_root, "custom-node-list.json")
    remote_url = "https://raw.githubusercontent.com/ltdrdata/ComfyUI-Manager/main/custom-node-list.json"
    try:
        req = Request(remote_url, headers={"User-Agent": "charon-validator/1.0"})
        with urlopen(req, timeout=15) as resp:
            if getattr(resp, "status", 200) != 200:
                return
            payload = resp.read()
            if not payload:
                return
        os.makedirs(manager_root, exist_ok=True)
        with open(local_path, "wb") as handle:
            handle.write(payload)
        system_debug("Updated ComfyUI Manager catalog from upstream.")
    except Exception as exc:  # pragma: no cover - best-effort fetch
        system_warning(f"Failed to refresh Manager catalog: {exc}")


def _match_unknown_nodes_to_installed(
    unknown_nodes: Iterable[str],
    comfy_dir: str,
) -> Dict[str, str]:
    """Best-effort matching of unknown node classes to installed custom_nodes folders."""
    matches: Dict[str, str] = {}
    if not comfy_dir:
        return matches

    custom_nodes_dir = os.path.join(comfy_dir, "custom_nodes")
    if not os.path.isdir(custom_nodes_dir):
        return matches

    folder_tokens: Dict[str, str] = {}
    try:
        for entry in os.listdir(custom_nodes_dir):
            path = os.path.join(custom_nodes_dir, entry)
            if os.path.isdir(path):
                token = _normalize_token(entry)
                if token:
                    folder_tokens[token] = entry
    except OSError:
        return matches

    for node_name in unknown_nodes or []:
        normalized = _normalize_token(node_name)
        if not normalized:
            continue
        for token, folder in folder_tokens.items():
            if token in normalized or normalized in token:
                matches[str(node_name)] = folder
                break
    return matches


def _load_manager_catalog(manager_root: str) -> List[Dict[str, Any]]:
    if not manager_root:
        return []
    candidate = os.path.join(manager_root, "custom-node-list.json")
    try:
        with open(candidate, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, dict):
            items = payload.get("custom_nodes")
            return items if isinstance(items, list) else []
    except Exception:
        return []
    return []


def _match_unknown_nodes_to_catalog(
    unknown_nodes: Iterable[str],
    manager_root: str,
) -> Dict[str, str]:
    """Match unknown classes to catalog entries by name/repo tokens."""
    matches: Dict[str, str] = {}
    catalog = _load_manager_catalog(manager_root)
    if not catalog:
        return matches

    tokenized_catalog: List[Tuple[str, str]] = []
    for entry in catalog:
        if not isinstance(entry, dict):
            continue
        title = entry.get("title") or entry.get("name") or ""
        repo = entry.get("repository") or entry.get("reference") or entry.get("repo") or ""
        token = _normalize_token(title) or _normalize_token(repo)
        if token and repo:
            tokenized_catalog.append((token, repo))

    for node_name in unknown_nodes or []:
        normalized = _normalize_token(node_name)
        if not normalized:
            continue
        for token, repo in tokenized_catalog:
            if token in normalized or normalized in token:
                matches[str(node_name)] = repo
                break
    return matches


def _collect_aux_repos(workflow_bundle: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """Collect aux_id hints from workflow nodes."""
    mapping: Dict[str, str] = {}
    if not isinstance(workflow_bundle, dict):
        return mapping
    workflow = workflow_bundle.get("workflow")
    nodes = []
    if isinstance(workflow, dict):
        if isinstance(workflow.get("nodes"), list):
            nodes = workflow["nodes"]
        else:
            nodes = list(workflow.values())
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_type = str(node.get("type") or node.get("class_type") or "").strip()
        if not node_type:
            continue
        props = node.get("properties") or {}
        if isinstance(props, dict):
            aux_id = props.get("aux_id")
            if isinstance(aux_id, str) and aux_id.strip():
                repo = _repo_from_aux(aux_id)
                if repo:
                    mapping[node_type.lower()] = repo
    return mapping


def _repo_from_aux(aux_id: str) -> str:
    aux = (aux_id or "").strip()
    if not aux:
        return ""
    if aux.lower().startswith("http://") or aux.lower().startswith("https://"):
        return aux
    # Assume GitHub shorthand org/repo
    return f"https://github.com/{aux}"


def _match_unknown_nodes_to_aux(
    unknown_nodes: Iterable[str],
    aux_repos: Dict[str, str],
) -> Dict[str, str]:
    matches: Dict[str, str] = {}
    for node_name in unknown_nodes or []:
        repo = aux_repos.get(str(node_name) or "")
        if repo:
            matches[str(node_name)] = repo
    return matches


def _display_name_for_repo(repo: str) -> str:
    repo = (repo or "").strip()
    if not repo:
        return "Custom node"
    parsed = urlparse(repo)
    path = (parsed.path or "").rstrip("/")
    if path:
        name = path.split("/")[-1]
    else:
        name = os.path.basename(repo.rstrip("/"))
    if name.endswith(".git"):
        name = name[:-4]
    return name or repo


def _normalize_repo_url(value: str) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().rstrip("/").lower()


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


def _value_has_path_component(value: Optional[str]) -> bool:
    if not value:
        return False
    return "/" in str(value).replace("\\", "/")


def _strip_category_prefix(value: str) -> str:
    normalized = (value or "").replace("\\", "/").lstrip("/")
    if not normalized:
        return normalized
    lowered = normalized.lower()
    if lowered.startswith("models/"):
        parts = normalized.split("/", 1)
        normalized = parts[1] if len(parts) > 1 else ""
    segments = [segment for segment in normalized.split("/") if segment]
    if len(segments) <= 1:
        return normalized
    first_lower = segments[0].lower()
    if first_lower in MODEL_CATEGORY_PREFIXES:
        trimmed = "/".join(segments[1:])
        if trimmed:
            return trimmed
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
    original_name = None
    category = None
    if signature and len(signature) >= 2:
        original_name = signature[0]
        category = signature[1]
    prefer_simple_name = bool(original_name) and not _value_has_path_component(original_name)
    simple_value = _normalize_workflow_entry(os.path.basename(abs_path))

    def _finalize(candidate: str) -> str:
        stripped = _strip_category_prefix(candidate)
        normalized_candidate = _normalize_workflow_entry(stripped)
        if prefer_simple_name and simple_value:
            if _value_has_path_component(stripped) or _value_has_path_component(normalized_candidate):
                return simple_value
        return normalized_candidate

    if category:
        category_root = os.path.join(models_root, category)
        if os.path.isdir(category_root):
            try:
                rel = os.path.relpath(abs_path, category_root)
                if not rel.startswith('..'):
                    return _finalize(rel)
            except ValueError:
                pass
    if models_root and os.path.isdir(models_root):
        try:
            rel = os.path.relpath(abs_path, models_root)
            if not rel.startswith('..'):
                return _finalize(rel)
        except ValueError:
            pass
    if comfy_dir:
        try:
            rel = os.path.relpath(abs_path, comfy_dir)
            if not rel.startswith('..'):
                return _finalize(rel)
        except ValueError:
            pass
    return _finalize(abs_path)

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
