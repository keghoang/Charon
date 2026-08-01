from __future__ import annotations

import os
import posixpath
import shutil
import time
import uuid
from dataclasses import dataclass
from typing import Iterable, List, Optional, Set

from . import preferences
from .charon_logger import system_info, system_warning
from .paths import resolve_comfy_environment


@dataclass(frozen=True)
class CustomNodeRepair:
    plugin_name: str
    shadow_path: str
    backup_path: str


def _tracked_paths(lines: Iterable[str]) -> Set[str]:
    tracked: Set[str] = set()
    for raw_line in lines:
        candidate = str(raw_line or "").strip().replace("\\", "/")
        while candidate.startswith("./"):
            candidate = candidate[2:]
        normalized = posixpath.normpath(candidate)
        if (
            not normalized
            or normalized == "."
            or normalized == ".."
            or normalized.startswith("../")
            or normalized.startswith("/")
            or ":" in normalized.split("/", 1)[0]
        ):
            continue
        tracked.add(normalized)
    return tracked


def _is_path_inside(path: str, root: str) -> bool:
    try:
        return os.path.commonpath(
            [os.path.realpath(path), os.path.realpath(root)]
        ) == os.path.realpath(root)
    except (OSError, ValueError):
        return False


def _backup_destination(
    backup_root: str,
    plugin_name: str,
    module_relative_path: str,
) -> str:
    safe_module_name = module_relative_path.replace("/", "__").replace("\\", "__")
    suffix = f"{int(time.time())}_{uuid.uuid4().hex[:8]}"
    return os.path.join(backup_root, plugin_name, f"{safe_module_name}_{suffix}")


def repair_tracked_module_shadows(
    comfy_path: str,
    *,
    backup_root: Optional[str] = None,
) -> List[CustomNodeRepair]:
    """
    Quarantine stale packages that shadow tracked module files.

    Comfy Registry installations include a ``.tracking`` manifest. Some overlay
    updates leave files from an older package layout in place. If the current
    manifest owns ``path/name.py`` but does not own anything below
    ``path/name/``, an obsolete ``path/name/__init__.py`` wins Python import
    resolution and can break the updated node. Only that contradictory,
    manifest-backed state is repaired; other untracked files are untouched.
    """
    env = resolve_comfy_environment(comfy_path)
    comfy_dir = str(env.get("comfy_dir") or "") if isinstance(env, dict) else ""
    custom_nodes_root = os.path.abspath(os.path.join(comfy_dir, "custom_nodes"))
    if not comfy_dir or not os.path.isdir(custom_nodes_root):
        return []

    if backup_root is None:
        preferences_root = preferences.get_preferences_root(ensure_dir=True)
        backup_root = os.path.join(
            preferences_root,
            "repairs",
            "custom_node_module_shadows",
        )
    backup_root = os.path.abspath(backup_root)

    repairs: List[CustomNodeRepair] = []
    try:
        plugin_names = sorted(os.listdir(custom_nodes_root), key=str.casefold)
    except OSError as exc:
        system_warning(f"Could not inspect ComfyUI custom nodes for stale files: {exc}")
        return repairs

    for plugin_name in plugin_names:
        plugin_root = os.path.join(custom_nodes_root, plugin_name)
        tracking_path = os.path.join(plugin_root, ".tracking")
        if (
            not os.path.isdir(plugin_root)
            or os.path.islink(plugin_root)
            or not os.path.isfile(tracking_path)
        ):
            continue
        try:
            with open(tracking_path, "r", encoding="utf-8") as handle:
                tracked = _tracked_paths(handle)
        except (OSError, UnicodeError) as exc:
            system_warning(f"Could not read custom-node manifest {tracking_path}: {exc}")
            continue

        for tracked_path in sorted(tracked, key=str.casefold):
            if not tracked_path.casefold().endswith(".py"):
                continue
            module_relative_path = tracked_path[:-3]
            package_prefix = f"{module_relative_path}/".casefold()
            if any(path.casefold().startswith(package_prefix) for path in tracked):
                continue

            module_file = os.path.join(plugin_root, *tracked_path.split("/"))
            shadow_path = os.path.join(plugin_root, *module_relative_path.split("/"))
            if (
                not os.path.isfile(module_file)
                or not os.path.isdir(shadow_path)
                or os.path.islink(shadow_path)
                or not os.path.isfile(os.path.join(shadow_path, "__init__.py"))
                or not _is_path_inside(shadow_path, plugin_root)
            ):
                continue

            destination = _backup_destination(
                backup_root,
                plugin_name,
                module_relative_path,
            )
            try:
                os.makedirs(os.path.dirname(destination), exist_ok=True)
                shutil.move(shadow_path, destination)
            except (OSError, shutil.Error) as exc:
                system_warning(
                    "Could not quarantine stale custom-node package "
                    f"{shadow_path}: {exc}"
                )
                continue

            repair = CustomNodeRepair(
                plugin_name=plugin_name,
                shadow_path=shadow_path,
                backup_path=destination,
            )
            repairs.append(repair)
            system_info(
                "Repaired custom-node overlay for "
                f"{plugin_name}: moved {shadow_path} to {destination}"
            )

    return repairs
