from __future__ import annotations

import configparser
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

from . import config
from .charon_logger import system_debug, system_error, system_info, system_warning
from .comfy_client import ComfyUIClient
from .comfy_environment import resolve_comfy_runtime
from .model_manifest import category_from_shared_path
from .model_paths import category_aliases
from .path_safety import ensure_path_inside
from .paths import resolve_comfy_environment


SHARED_MODELS_ROOT: Optional[str] = None


def get_shared_models_root() -> str:
    """Return the active shared-model root, allowing tests to override it."""
    return SHARED_MODELS_ROOT or config.get_shared_models_root()


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
        system_debug(
            "[Validation] Local match scan skipped | "
            f"name='{file_name}' reason='no search roots' models_root='{models_root}'"
        )
        return []

    system_debug(
        "[Validation] Local match scan starting | "
        f"name='{file_name}' roots={search_roots}"
    )
    matches: List[str] = []
    seen: set[str] = set()
    for root in search_roots:
        for candidate in _iter_matching_files(root, file_name):
            if candidate in seen:
                continue
            seen.add(candidate)
            matches.append(candidate)
    system_debug(
        "[Validation] Local match scan finished | "
        f"name='{file_name}' matches={matches}"
    )
    return matches


def find_shared_model_matches(file_name: str) -> List[str]:
    """Search the global shared models repository for matching files."""
    file_name = os.path.basename(_safe_str(file_name))
    shared_models_root = get_shared_models_root()
    if not file_name or not os.path.isdir(shared_models_root):
        system_debug(
            "[Validation] Shared repo scan skipped | "
            f"name='{file_name}' root_exists={os.path.isdir(shared_models_root)}"
        )
        return []
    matches: List[str] = []
    for candidate in _iter_matching_files(shared_models_root, file_name):
        matches.append(candidate)
    system_debug(
        "[Validation] Shared repo scan finished | "
        f"name='{file_name}' matches={matches}"
    )
    return matches


def select_first_model_match(matches: Sequence[str]) -> Optional[str]:
    """Return the first discovered model match according to resolver search priority."""
    return matches[0] if matches else None


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


def reference_for_shared_model(
    reference: Dict[str, Any],
    shared_model_path: str,
    models_root: str,
) -> Dict[str, Any]:
    """Return a reference whose category preserves the shared repository layout."""
    updated = dict(reference or {})
    shared_category = category_from_shared_path(
        shared_model_path,
        get_shared_models_root(),
    )
    if not shared_category:
        return updated
    updated["shared_category"] = shared_category
    updated["category"] = _target_category_alias(shared_category, models_root)
    attempted = list(updated.get("attempted_categories") or [])
    if updated["category"] not in attempted:
        attempted.insert(0, updated["category"])
    updated["attempted_categories"] = attempted
    return updated


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

    missing_entries = _coerce_sequence(issue_data.get("missing_models"))
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

        candidate_rel = os.path.relpath(os.path.abspath(candidate), os.path.abspath(models_root))
        inside_models_root = candidate_rel != os.pardir and not candidate_rel.startswith(
            os.pardir + os.sep
        )
        try:
            os.makedirs(dest_dir, exist_ok=True)
            if inside_models_root:
                # A misplaced file inside the models tree is moved rather than
                # copied so we don't duplicate multi-GB checkpoints on disk.
                system_debug(
                    f"Moving model '{dest_file}' from '{candidate}' to '{target_path}'."
                )
                shutil.move(candidate, target_path)
                result.resolved.append(f"Moved {dest_file} into place.")
            else:
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


def relocate_model_to_category(
    candidate_path: str,
    reference: Dict[str, Any],
    models_root: str,
) -> Tuple[str, bool]:
    """Move a model found in the wrong category folder into the expected one.

    Returns ``(final_path, moved)``. The file is only moved when the reference's
    category is backed by the workflow's model manifest (``manifest_category``)
    — a category merely inferred from node names is not authoritative enough to
    justify moving files, and two workflows with conflicting inferred
    categories would otherwise move the same model back and forth. Files
    outside ``models_root``, already-correct files, and alias categories
    (clip/text_encoders, unet/diffusion_models) are left untouched. If a
    correctly placed copy already exists, that copy is returned without
    touching the stray.
    """
    category = _safe_str(reference.get("manifest_category")).strip().strip("/\\")
    if not category or not models_root or not candidate_path:
        return candidate_path, False

    models_root_abs = os.path.abspath(models_root)
    candidate_abs = os.path.abspath(candidate_path)
    try:
        rel = os.path.relpath(candidate_abs, models_root_abs)
    except ValueError:
        return candidate_path, False
    if rel == os.pardir or rel.startswith(os.pardir + os.sep) or os.path.isabs(rel):
        # Never move files that live outside the models directory.
        return candidate_path, False

    actual_category = rel.replace("\\", "/").split("/", 1)[0].lower()
    if actual_category in category_aliases(category):
        return candidate_path, False

    target_dir = os.path.join(models_root_abs, _target_category_alias(category, models_root_abs))
    target_path = os.path.join(target_dir, os.path.basename(candidate_abs))
    try:
        target_path = ensure_path_inside(target_path, models_root_abs, label="Model destination")
    except ValueError:
        return candidate_path, False
    if os.path.normcase(target_path) == os.path.normcase(candidate_abs):
        return candidate_path, False
    if os.path.exists(target_path):
        return target_path, False

    os.makedirs(target_dir, exist_ok=True)
    shutil.move(candidate_abs, target_path)
    system_warning(
        f"Relocated model '{os.path.basename(target_path)}' from "
        f"'{os.path.dirname(candidate_abs)}' to '{target_dir}' to match its "
        f"'{category}' category."
    )
    return target_path, True


def _target_category_alias(category: str, models_root: str) -> str:
    aliases = {
        "clip": ("clip", "text_encoders"),
        "text_encoders": ("text_encoders", "clip"),
        "unet": ("unet", "diffusion_models"),
        "diffusion_models": ("diffusion_models", "unet"),
    }
    choices = aliases.get(category, (category,))
    for choice in choices:
        if models_root and os.path.isdir(os.path.join(models_root, choice)):
            return choice
    return choices[0]


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
        runtime = resolve_comfy_runtime(comfy_path)
        env_info = runtime.as_path_info()
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


def repair_custom_node_dependencies(
    python_exe: Optional[str],
    plugin_dir: str,
    timeout: int = 300,
) -> Optional[Tuple[bool, str]]:
    """Reinstall a broken plugin's pip requirements with the embedded python.

    Returns ``None`` when there is nothing to repair with (no interpreter or
    no requirements.txt), otherwise ``(succeeded, detail)``.
    """
    requirements = os.path.join(plugin_dir, "requirements.txt")
    if not python_exe or not os.path.exists(python_exe) or not os.path.isfile(requirements):
        return None
    try:
        completed = subprocess.run(
            [python_exe, "-m", "pip", "install", "-r", requirements],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=plugin_dir,
        )
    except subprocess.TimeoutExpired:
        return False, "pip install timed out"
    except Exception as exc:  # pragma: no cover - subprocess guard
        return False, str(exc)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        return False, detail.splitlines()[-1] if detail else "pip install failed"
    system_info(f"Reinstalled custom-node dependencies from {requirements}")
    return True, requirements


def existing_custom_node_conflict(
    comfy_dir: Optional[str],
    repo: str,
    python_exe: Optional[str] = None,
) -> Optional[str]:
    """Explain why reinstalling ``repo`` via ComfyUI-Manager cannot succeed.

    A node reported missing while its folder already sits in ``custom_nodes``
    means the plugin is installed but failed to load (usually an import error
    or missing pip dependency after an update). ComfyUI-Manager rejects the
    reinstall with a bare HTTP 400, so surface the real state instead — and
    when the embedded python is available, repair the usual cause directly by
    reinstalling the plugin's pip requirements.
    """
    if not comfy_dir or not repo:
        return None
    name = _repo_display_name(repo)
    if not name:
        return None
    custom_nodes_dir = os.path.join(comfy_dir, "custom_nodes")
    installed = os.path.join(custom_nodes_dir, name)
    try:
        if os.path.isdir(installed):
            if os.listdir(installed):
                repair = repair_custom_node_dependencies(python_exe, installed)
                if repair is not None and repair[0]:
                    return (
                        f"'{name}' was installed but its nodes were not loading. "
                        "Charon reinstalled its Python dependencies - restart "
                        "ComfyUI and validate again. If it still fails, check "
                        "the ComfyUI console for the plugin's import error."
                    )
                message = (
                    f"'{name}' is already installed at {installed} but ComfyUI is not "
                    "loading its nodes. Reinstalling cannot fix this - check the "
                    "ComfyUI console for the plugin's import error (missing pip "
                    "dependencies are the usual cause), or delete the folder and "
                    "resolve again for a clean install."
                )
                if repair is not None:
                    message += f" Automatic dependency repair failed: {repair[1]}"
                return message
            # An empty leftover folder would still make the Manager refuse the
            # clone; removing the husk lets the install proceed.
            os.rmdir(installed)
    except OSError:
        pass
    for disabled in (
        os.path.join(custom_nodes_dir, ".disabled", name),
        os.path.join(custom_nodes_dir, f"{name}.disabled"),
    ):
        if os.path.isdir(disabled):
            return (
                f"'{name}' is installed but disabled ({disabled}). Enable it in "
                "ComfyUI-Manager instead of reinstalling."
            )
    return None


def enable_manager_git_url_install(comfy_dir: Optional[str]) -> Optional[str]:
    """Opt in to ComfyUI-Manager's Install-via-Git-URL in its config.ini.

    Recent Manager versions (v4+) refuse ``/customnode/install/git_url``
    unless ``config.ini`` carries ``allow_git_url_install = true`` in the
    ``[default]`` section (this replaced the old ``security_level`` gate for
    git URL installs). Returns the config path that was updated, or ``None``
    when the flag was already set or nothing could be written.
    """
    if not comfy_dir:
        return None
    candidates = [
        os.path.join(comfy_dir, "user", "default", "ComfyUI-Manager", "config.ini"),
        os.path.join(comfy_dir, "custom_nodes", "ComfyUI-Manager", "config.ini"),
        os.path.join(comfy_dir, "custom_nodes", "comfyui-manager", "config.ini"),
    ]
    target = next((path for path in candidates if os.path.isfile(path)), None)
    if target is None:
        # Manager >=3 keeps its config under user/default; seed the flag there
        # when the user directory exists but Manager has not written one yet.
        user_dir = os.path.join(comfy_dir, "user", "default")
        if not os.path.isdir(user_dir):
            return None
        manager_dir = os.path.join(user_dir, "ComfyUI-Manager")
        os.makedirs(manager_dir, exist_ok=True)
        target = os.path.join(manager_dir, "config.ini")
    parser = configparser.ConfigParser()
    try:
        parser.read(target, encoding="utf-8")
    except (OSError, configparser.Error) as exc:
        system_warning(f"Could not read ComfyUI-Manager config '{target}': {exc}")
        return None
    if not parser.has_section("default"):
        parser.add_section("default")
    if parser.get("default", "allow_git_url_install", fallback="").strip().lower() == "true":
        return None
    parser.set("default", "allow_git_url_install", "true")
    try:
        with open(target, "w", encoding="utf-8") as handle:
            parser.write(handle)
    except OSError as exc:
        system_warning(f"Could not update ComfyUI-Manager config '{target}': {exc}")
        return None
    system_info(f"Enabled allow_git_url_install in ComfyUI-Manager config: {target}")
    return target


def locate_manager_cli(comfy_dir: Optional[str]) -> Optional[Tuple[str, str]]:
    if not comfy_dir:
        return None
    custom_nodes_dir = os.path.join(comfy_dir, "custom_nodes")
    candidates: List[str] = []
    for folder in ("comfyui-manager", "ComfyUI-Manager"):
        candidates.append(os.path.join(custom_nodes_dir, folder, "cm-cli.py"))

    if os.path.isdir(custom_nodes_dir):
        try:
            for entry in os.listdir(custom_nodes_dir):
                lower = entry.lower()
                if "manager" in lower:
                    candidates.append(os.path.join(custom_nodes_dir, entry, "cm-cli.py"))
        except OSError:
            pass

    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate, os.path.dirname(candidate)
    return None


def install_custom_nodes_via_playwright(
    comfy_path: str,
    repos: Sequence[str],
) -> ResolutionResult:
    result = ResolutionResult()
    if not repos:
        result.skipped.append("No repository URLs were provided.")
        return result

    try:
        runtime = resolve_comfy_runtime(comfy_path)
        env_info = runtime.as_path_info()
    except Exception as exc:  # pragma: no cover - defensive guard
        result.failed.append(f"Failed to resolve Comfy environment: {exc}")
        return result

    python_exe = _safe_str(env_info.get("python_exe"))
    comfy_dir = _safe_str(env_info.get("comfy_dir"))
    if not python_exe or not os.path.exists(python_exe):
        result.failed.append("Embedded Python runtime not found; cannot run Playwright install.")
        return result
    if not comfy_dir or not os.path.isdir(comfy_dir):
        result.failed.append("ComfyUI directory missing; cannot run Playwright install.")
        return result
    if not ComfyUIClient(runtime.base_url, connect_timeout=3).test_connection():
        result.failed.append(
            f"No valid ComfyUI server is responding at {runtime.base_url}. "
            "Start ComfyUI and wait for it to finish loading before installing custom nodes."
        )
        return result

    unique_repos: List[str] = []
    seen: set[str] = set()
    for repo in repos:
        normalized = _normalize_repo_url(repo)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        # ComfyUI-Manager refuses to clone over an existing folder with a bare
        # HTTP 400, hiding the real problem. Detect that state up front,
        # repair the plugin's pip dependencies when possible, and explain the
        # outcome instead of looping through doomed reinstalls.
        conflict = existing_custom_node_conflict(comfy_dir, repo, python_exe=python_exe)
        if conflict:
            result.failed.append(conflict)
            continue
        unique_repos.append(repo)

    if not unique_repos:
        if not result.failed:
            result.skipped.append("No unique repository URLs to install.")
        return result

    temp_dir = tempfile.mkdtemp(prefix="charon_playwright_install_")
    script_path = os.path.join(temp_dir, "install_custom_nodes.py")
    payload = json.dumps(unique_repos)
    install_script = r'''import asyncio
import json
import sys

REPOS = json.loads(sys.argv[1]) if len(sys.argv) > 1 else []
COMFY_URL = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8188"

async def main():
    result = {"installed": [], "skipped": [], "failed": [], "error": ""}
    try:
        from playwright.async_api import async_playwright
    except Exception as exc:
        result["error"] = f"Playwright import failed: {exc}"
        print(json.dumps(result))
        return

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto(COMFY_URL, wait_until="load", timeout=120000)
        except Exception as exc:
            result["error"] = (
                "Please start ComfyUI server first. "
                f"(Cannot reach ComfyUI at {COMFY_URL}: {exc})"
            )
            print(json.dumps(result))
            await browser.close()
            return

        for repo in REPOS:
            if not repo:
                result["skipped"].append("Skipped empty repository entry.")
                continue
            try:
                response = await page.evaluate(
                    """async (repo) => {
                        const attempt = async (body, contentType) => {
                            const options = { method: 'POST', body };
                            if (contentType) {
                                options.headers = { 'Content-Type': contentType };
                            }
                            const res = await fetch('/customnode/install/git_url', options);
                            let text = '';
                            try { text = await res.text(); } catch (err) {}
                            return { status: res.status, ok: res.ok, text };
                        };
                        // Classic Manager expects the raw URL as the body;
                        // newer Manager requires JSON {"url": ...} and answers
                        // 400 "Invalid request body" to the raw form.
                        let response = await attempt(repo);
                        if (!response.ok && response.text && response.text.indexOf('Invalid request body') !== -1) {
                            response = await attempt(JSON.stringify({ url: repo }), 'application/json');
                        }
                        return response;
                    }""",
                    repo,
                )
                if response.get("ok"):
                    result["installed"].append(repo)
                else:
                    detail = response.get("text") or f"status={response.get('status')}"
                    result["failed"].append(f"{repo}: {detail}")
            except Exception as exc:
                result["failed"].append(f"{repo}: {exc}")

        await browser.close()
        print(json.dumps(result))

asyncio.run(main())
'''

    completed = None
    try:
        with open(script_path, "w", encoding="utf-8") as handle:
            handle.write(install_script)

        command = [python_exe, script_path, payload, runtime.base_url]
        env = os.environ.copy()
        env.setdefault("COMFYUI_PATH", comfy_dir)
        env.setdefault("COMFYUI_FOLDERS_BASE_PATH", comfy_dir)

        system_debug(f"[Validation] Running Playwright install: {command}")
        completed = subprocess.run(
            command,
            cwd=comfy_dir,
            capture_output=True,
            timeout=240,
            text=True,
            env=env,
        )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    if completed is None or completed.returncode != 0:
        if completed is None:
            detail = "Playwright install command did not run."
        else:
            detail = completed.stderr.strip() or completed.stdout.strip() or "Playwright install command failed."
        result.failed.append(detail)
        return result

    try:
        payload = json.loads(completed.stdout.strip() or "{}")
    except json.JSONDecodeError:
        detail = completed.stdout.strip() or "Playwright install returned non-JSON output."
        result.failed.append(detail)
        return result

    if payload.get("error"):
        result.failed.append(str(payload["error"]))

    for entry in payload.get("installed") or []:
        result.resolved.append(f"Installed via Playwright: {_repo_display_name(entry)}.")
    for entry in payload.get("skipped") or []:
        result.skipped.append(entry)
    for entry in payload.get("failed") or []:
        entry = str(entry)
        if entry.endswith("status=400"):
            # ComfyUI-Manager reports clone failures as a bare 400 and only
            # logs the reason (bad URL, git failure, already exists) to its
            # own console.
            entry += (
                " - ComfyUI-Manager rejected the install; the reason is in "
                "the ComfyUI console log."
            )
        result.failed.append(entry)

    failure_text = " ".join(str(entry) for entry in result.failed)
    if "allow_git_url_install" in failure_text:
        # Newer ComfyUI-Manager gates git URL installs behind an explicit
        # config flag; enable it so the install works after a restart.
        updated = enable_manager_git_url_install(comfy_dir)
        if updated:
            result.failed.append(
                "ComfyUI-Manager was blocking Git URL installs; Charon enabled "
                f"'allow_git_url_install' in {updated}. Restart ComfyUI and resolve again."
            )
        else:
            result.failed.append(
                "ComfyUI-Manager blocks Git URL installs. Set 'allow_git_url_install = true' "
                "under [default] in its config.ini and restart ComfyUI."
            )
    elif "security_level" in failure_text:
        result.failed.append(
            "ComfyUI-Manager's security_level blocks this install. Set 'security_level = weak' "
            "in its config.ini, restart ComfyUI, retry, then restore the previous level."
        )

    if not result.resolved and not result.failed and not result.skipped:
        result.notes.append("No installation actions were performed.")

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
    if not raw_name or not models_root:
        return None

    models_root = os.path.abspath(models_root)
    normalized = raw_name.replace("/", os.sep).replace("\\", os.sep)
    if os.path.isabs(normalized):
        try:
            return ensure_path_inside(normalized, models_root, label="Model destination")
        except ValueError:
            normalized = os.path.basename(normalized)

    candidate = None
    if comfy_dir:
        candidate = os.path.join(comfy_dir, normalized)
        if os.path.exists(candidate):
            try:
                return ensure_path_inside(candidate, models_root, label="Model destination")
            except ValueError:
                pass

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
    for category in categories_to_consider:
        normalized_category = _safe_str(category)
        if not normalized_category:
            continue
        candidate_dir = os.path.join(models_root, normalized_category)
        try:
            candidate_dir = ensure_path_inside(
                candidate_dir,
                models_root,
                label="Model category",
            )
        except ValueError:
            continue
        if os.path.isdir(candidate_dir) and candidate_dir not in candidate_dirs:
            candidate_dirs.append(candidate_dir)

    for directory in attempted_directories or reference.get("attempted_directories") or []:
        normalized_directory = _safe_str(directory)
        if not normalized_directory:
            continue
        try:
            candidate_dir = ensure_path_inside(
                normalized_directory,
                models_root,
                label="ComfyUI model directory",
            )
        except ValueError:
            continue
        if os.path.isdir(candidate_dir) and candidate_dir not in candidate_dirs:
            candidate_dirs.append(candidate_dir)

    if models_root not in candidate_dirs and os.path.isdir(models_root):
        candidate_dirs.append(models_root)

    for directory in candidate_dirs:
        target = os.path.join(directory, base_name)
        if target:
            return ensure_path_inside(target, models_root, label="Model destination")
    return ensure_path_inside(
        os.path.join(models_root, base_name),
        models_root,
        label="Model destination",
    )


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
    seen: set[str] = set()
    direct_candidate = os.path.join(normalized_root, file_name)
    if os.path.isfile(direct_candidate):
        direct_candidate = os.path.abspath(direct_candidate)
        seen.add(os.path.normcase(direct_candidate))
        yield direct_candidate
    lowered = file_name.lower()
    for candidate_root, _dirs, files in os.walk(normalized_root):
        for entry in files:
            if entry.lower() == lowered:
                candidate = os.path.abspath(os.path.join(candidate_root, entry))
                normalized = os.path.normcase(candidate)
                if normalized in seen:
                    continue
                seen.add(normalized)
                yield candidate


def _normalize_repo_url(value: str) -> str:
    return value.strip().rstrip("/").lower() if isinstance(value, str) else ""


def _repo_display_name(repo: str) -> str:
    repo = _safe_str(repo)
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

    if not seen and models_root and os.path.isdir(models_root):
        yield os.path.abspath(models_root)


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
