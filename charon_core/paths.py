import os
import sys
import uuid
import logging


logger = logging.getLogger(__name__)

DEFAULT_CHARON_DIR = r"D:\Nuke\charon"


def get_charon_temp_dir(base_dir=DEFAULT_CHARON_DIR):
    subdirs = ["temp", "exports", "results", "status", "debug"]
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
