import logging
import hashlib
import os
import re
import sys
import uuid
from typing import Optional, Tuple

from .utilities import get_current_user_slug


logger = logging.getLogger(__name__)

DEFAULT_CHARON_DIR = r"D:\Nuke\charon"
RESOURCE_DIR = os.path.join(os.path.dirname(__file__), "resources")

WORK_FOLDER_TEMPLATE = "{user}"
CHARON_FOLDER_NAME = "_CHARON"
NUKE_FALLBACK_NAME = "untitled"
NODE_FALLBACK_ID = "unknown"
WORKFLOW_FALLBACK_NAME = "Workflow"
OUTPUT_CATEGORY_2D = "2D"
OUTPUT_CATEGORY_3D = "3D"
OUTPUT_PREFIX = "CharonOutput_v"
OUTPUT_DIRECTORY_TEMPLATE = os.path.join("{category}", "{workflow}", "CharonOp_{node_id}")
_NUKE_SCRIPT_VERSION_RE = re.compile(r"(?i)(?P<stem>.+?)(?:[._-])v\d+$")


def get_default_comfy_launch_path():
    # Default to an empty value; users must supply a ComfyUI launch path in settings.
    return ""


def _strip_nuke_script_version(filename: str) -> str:
    if not filename:
        return filename
    stem, extension = os.path.splitext(filename)
    match = _NUKE_SCRIPT_VERSION_RE.match(stem)
    if match:
        candidate = match.group("stem")
        if candidate:
            stem = candidate
    return f"{stem}{extension}"


def normalize_nuke_script_path(script_path: str) -> str:
    """
    Normalize a Nuke script path for stable hashing.
    Strips version suffixes like _v001 from the filename.
    """
    if not script_path:
        return ""
    cleaned = str(script_path).strip().strip('"')
    if not cleaned:
        return ""
    lowered = cleaned.lower()
    if lowered in {"root", NUKE_FALLBACK_NAME, f"{NUKE_FALLBACK_NAME}.nk"}:
        return ""
    normalized = os.path.normpath(cleaned)
    folder = os.path.dirname(normalized)
    basename = os.path.basename(normalized)
    basename = _strip_nuke_script_version(basename)
    normalized = os.path.normpath(os.path.join(folder, basename)) if folder else basename
    return normalized.replace("\\", "/").lower()


def compute_nuke_script_hash(script_path: str) -> str:
    normalized = normalize_nuke_script_path(script_path)
    if not normalized:
        return ""
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def get_nuke_script_hash(nuke_module=None) -> str:
    module = nuke_module
    if module is None:
        try:
            import nuke as module  # type: ignore
        except Exception:
            module = None
    if module is None:
        return ""
    try:
        root = module.root()
    except Exception:
        root = None
    if root is None:
        return ""
    script_reference = ""
    try:
        script_reference = root.name()
    except Exception:
        script_reference = ""
    if not script_reference:
        try:
            name_knob = root.knob("name")
            if name_knob is not None:
                script_reference = str(name_knob.value() or "")
        except Exception:
            script_reference = ""
    return compute_nuke_script_hash(script_reference)


def _normalize_charon_root(base_dir: Optional[str]) -> str:
    """
    Normalize the Charon root directory and correct common typos.

    In particular, fix paths like ``D:\\Nukecharon`` where the separator between
    ``Nuke`` and ``charon`` is missing.
    """
    normalized = os.path.normpath(base_dir or DEFAULT_CHARON_DIR)
    basename = os.path.basename(normalized).lower()
    if basename == "nukecharon":
        normalized = os.path.join(os.path.dirname(normalized), "Nuke", "charon")
    return os.path.normpath(normalized)


def get_charon_temp_dir(base_dir=DEFAULT_CHARON_DIR):
    base_dir = _normalize_charon_root(base_dir)
    subdirs = ["temp", "exports", "results", "debug"]
    for subdir in subdirs:
        path = os.path.join(base_dir, subdir)
        os.makedirs(path, exist_ok=True)
    return base_dir


def get_temp_file(suffix=".png", subdir="temp", base_dir=DEFAULT_CHARON_DIR):
    root = get_charon_temp_dir(base_dir)
    temp_dir = os.path.join(root, subdir)
    os.makedirs(temp_dir, exist_ok=True)
    unique = str(uuid.uuid4())[:8]
    return os.path.join(temp_dir, f"charon_{unique}{suffix}")


def extend_sys_path_with_comfy(comfy_path):
    if not comfy_path:
        return

    try:
        comfy_path = os.path.abspath(comfy_path)
        if os.path.isdir(comfy_path):
            base_dir = comfy_path
        else:
            base_dir = os.path.dirname(comfy_path)

        candidates = []
        if base_dir and os.path.exists(base_dir):
            candidates.append(base_dir)
            comfy_sub = os.path.join(base_dir, "ComfyUI")
            if os.path.exists(comfy_sub):
                candidates.append(comfy_sub)

        search_dir = base_dir
        for _ in range(4):
            if not search_dir:
                break
            embed_root = os.path.join(search_dir, "python_embeded")
            if os.path.exists(embed_root):
                lib = os.path.join(embed_root, "Lib")
                site = os.path.join(lib, "site-packages")
                for item in (embed_root, lib, site):
                    if os.path.exists(item):
                        candidates.append(item)
                break
            parent = os.path.dirname(search_dir)
            if parent == search_dir:
                break
            search_dir = parent

        for candidate in candidates:
            if candidate and candidate not in sys.path:
                sys.path.insert(0, candidate)
                logger.info("Added to sys.path: %s", candidate)
    except Exception as exc:
        logger.warning("Failed to extend sys.path: %s", exc)


def resolve_comfy_environment(comfy_path):
    comfy_path = comfy_path.strip() if comfy_path else ""
    if not comfy_path:
        return {}

    base_dir = os.path.abspath(comfy_path) if os.path.isdir(comfy_path) else os.path.dirname(os.path.abspath(comfy_path))
    comfy_dir = os.path.join(base_dir, "ComfyUI")
    if not os.path.exists(comfy_dir):
        comfy_dir = base_dir

    python_exe = None
    embedded_root = None
    search_dir = base_dir
    for _ in range(4):
        if not search_dir:
            break
        candidate = os.path.join(search_dir, "python_embeded", "python.exe")
        if os.path.exists(candidate):
            python_exe = candidate
            embedded_root = os.path.join(search_dir, "python_embeded")
            break
        parent = os.path.dirname(search_dir)
        if parent == search_dir:
            break
        search_dir = parent

    return {
        "base_dir": base_dir,
        "comfy_dir": comfy_dir,
        "python_exe": python_exe,
        "embedded_root": embedded_root,
    }


def get_placeholder_image_path():
    candidate = os.path.join(RESOURCE_DIR, "charon_placeholder.png")
    if os.path.exists(candidate):
        return candidate
    return ""


def _read_env_path(name: str) -> str:
    value = os.getenv(name) or ""
    value = value.strip()
    if not value:
        return ""
    normalized = os.path.normpath(value)
    if os.path.exists(normalized):
        return normalized
    return ""


def _sanitize_component(value: Optional[str], default: str) -> str:
    text = (value or "").strip()
    if not text:
        text = default
    sanitized = "".join(
        char if char.isalnum() or char in {"_", "-", ".", " "} else "_"
        for char in text
    )
    sanitized = sanitized.strip("_ ").replace(" ", "_")
    return sanitized or default


def _determine_script_folder(script_name: Optional[str]) -> str:
    base = os.path.splitext(script_name or "")[0]
    return _sanitize_component(base, NUKE_FALLBACK_NAME)


def _determine_node_segment(node_id: Optional[str]) -> Tuple[str, str]:
    normalized = _sanitize_component(node_id, NODE_FALLBACK_ID).lower()
    return f"CharonOp_{normalized}", normalized


def _determine_workflow_segment(workflow_name: Optional[str]) -> str:
    return _sanitize_component(workflow_name, WORKFLOW_FALLBACK_NAME)


def _determine_category_segment(category: Optional[str]) -> str:
    sanitized = _sanitize_component(category, OUTPUT_CATEGORY_2D)
    upper = sanitized.upper()
    if upper in {OUTPUT_CATEGORY_2D, OUTPUT_CATEGORY_3D}:
        return upper
    return sanitized


def _resolve_output_root() -> Tuple[str, bool]:
    project_path = _read_env_path("BUCK_PROJECT_PATH")
    if project_path:
        return os.path.join(project_path, "Production", "Work"), True
    work_root = _read_env_path("BUCK_WORK_ROOT")
    if work_root:
        return os.path.join(work_root, "Work"), False
    fallback = os.path.join(get_charon_temp_dir(), "results")
    return fallback, False


def _ensure_directory(path: str) -> None:
    try:
        os.makedirs(path, exist_ok=True)
    except Exception as exc:
        logger.warning("Could not create directory %s: %s", path, exc)


def allocate_custom_output_path(
    custom_root: str,
    extension: Optional[str] = None,
    output_name: Optional[str] = None,
    output_subfolder: Optional[str] = None,
) -> str:
    extension = (extension or "").strip() or ".png"
    if not extension.startswith("."):
        extension = f".{extension}"

    base_root = os.path.normpath(str(custom_root or ""))
    output_segment = _sanitize_component(output_name, "") if output_name else ""
    output_subfolder_segment = _sanitize_component(output_subfolder, "") if output_subfolder else ""
    segments = [seg for seg in (output_subfolder_segment, output_segment) if seg]
    base_output_dir = os.path.join(base_root, *segments) if segments else base_root

    _ensure_directory(base_output_dir)

    prefix = OUTPUT_PREFIX
    version_pattern = re.compile(rf"{re.escape(prefix)}(\d+)", re.IGNORECASE)
    highest_version = 0
    try:
        for entry in os.listdir(base_output_dir):
            match = version_pattern.match(entry)
            if match:
                try:
                    highest_version = max(highest_version, int(match.group(1)))
                except ValueError:
                    continue
    except FileNotFoundError:
        pass

    next_version = highest_version + 1
    filename = f"{prefix}{next_version:03d}{extension.lower()}"
    return os.path.join(base_output_dir, filename)


def allocate_charon_output_path(
    node_id: Optional[str],
    script_name: Optional[str],
    extension: Optional[str] = None,
    user_slug: Optional[str] = None,
    workflow_name: Optional[str] = None,
    category: Optional[str] = None,
    output_name: Optional[str] = None,
    output_subfolder: Optional[str] = None,
) -> str:
    """
    Determine the versioned output path for a CharonOp run.

    The directory structure follows the BUCK project conventions. When
    BUCK_PROJECT_PATH is available the file is stored under:
        <project>/Production/Work/<user>/_CHARON/<category>/<workflow>/CharonOp_<id>/

    If BUCK_PROJECT_PATH is missing, BUCK_WORK_ROOT is used instead:
        <work_root>/Work/<user>/_CHARON/<category>/<workflow>/CharonOp_<id>/

    When neither environment variable is present, the path falls back to the
    default Charon results directory.

    An optional output_name adds a deeper folder (per Comfy output node) to
    prevent different outputs from stacking in the same directory.
    """
    extension = (extension or "").strip() or ".png"
    if not extension.startswith("."):
        extension = f".{extension}"

    user = _sanitize_component(user_slug or get_current_user_slug(), "user")
    _ = script_name  # script name no longer influences output directory
    _, normalized_node_id = _determine_node_segment(node_id)
    workflow_segment = _determine_workflow_segment(workflow_name)
    category_segment = _determine_category_segment(category)

    root, uses_project = _resolve_output_root()
    if uses_project:
        work_root = os.path.join(root, WORK_FOLDER_TEMPLATE.format(user=user))
    else:
        if root.endswith("results"):
            work_root = root
        else:
            work_root = os.path.join(root, WORK_FOLDER_TEMPLATE.format(user=user))

    directory_suffix = OUTPUT_DIRECTORY_TEMPLATE.format(
        category=category_segment,
        workflow=workflow_segment,
        node_id=normalized_node_id,
    )
    base_output_dir = os.path.join(work_root, CHARON_FOLDER_NAME, directory_suffix)
    output_subfolder_segment = _sanitize_component(output_subfolder, "") if output_subfolder else ""
    if output_subfolder_segment:
        base_output_dir = os.path.join(base_output_dir, output_subfolder_segment)

    output_segment = _sanitize_component(output_name, "") if output_name else ""
    if output_segment:
        base_output_dir = os.path.join(base_output_dir, output_segment)

    _ensure_directory(base_output_dir)

    prefix = OUTPUT_PREFIX
    version_pattern = re.compile(rf"{re.escape(prefix)}(\d+)", re.IGNORECASE)
    highest_version = 0
    try:
        for entry in os.listdir(base_output_dir):
            match = version_pattern.match(entry)
            if match:
                try:
                    highest_version = max(highest_version, int(match.group(1)))
                except ValueError:
                    continue
    except FileNotFoundError:
        pass

    next_version = highest_version + 1
    filename = f"{prefix}{next_version:03d}{extension.lower()}"
    return os.path.join(base_output_dir, filename)
