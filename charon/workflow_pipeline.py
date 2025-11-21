from __future__ import annotations

import copy
import json
import logging
import os
import subprocess
import uuid
from pathlib import Path

from .paths import get_charon_temp_dir, resolve_comfy_environment


logger = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).resolve().parent


def _is_api_workflow(ui_workflow) -> bool:
    return ui_workflow and all(
        isinstance(value, dict) and "class_type" in value for value in ui_workflow.values()
    )


def convert_workflow(ui_workflow, comfy_path="", comfy_nodes_module=None):
    if not isinstance(ui_workflow, dict):
        return ui_workflow

    if _is_api_workflow(ui_workflow):
        return copy.deepcopy(ui_workflow)

    if not comfy_path:
        raise RuntimeError("ComfyUI path is required for conversion.")

    env_info = resolve_comfy_environment(comfy_path)
    python_exe = env_info.get("python_exe")
    comfy_dir = env_info.get("comfy_dir")
    if not python_exe or not os.path.exists(python_exe):
        raise RuntimeError(f"Embedded Python not found for ComfyUI path: {comfy_path}")
    if not comfy_dir or not os.path.exists(comfy_dir):
        raise RuntimeError(f"ComfyUI directory not found for path: {comfy_path}")
    main_py = Path(comfy_dir) / "main.py"
    if not main_py.exists():
        raise RuntimeError(f"ComfyUI main.py not found under: {comfy_dir}")

    exporter_path = SCRIPT_DIR / "workflow_browser_exporter.py"
    if not exporter_path.exists():
        raise RuntimeError(f"workflow_browser_exporter.py missing in {SCRIPT_DIR}")

    temp_root = Path(get_charon_temp_dir())
    temp_dir = temp_root / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    input_path = temp_dir / f"workflow_input_{uuid.uuid4().hex}.json"
    output_path = temp_dir / f"workflow_output_{uuid.uuid4().hex}.json"
    runner_path = temp_dir / f"workflow_runner_{uuid.uuid4().hex}.py"

    try:
        input_path.write_text(json.dumps(ui_workflow), encoding="utf-8")

        runner_code = """import importlib.util
import sys

workflow_path, output_path, exporter_path, comfy_dir = sys.argv[1:5]

spec = importlib.util.spec_from_file_location("workflow_browser_exporter", exporter_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

module.run_export_sync(workflow_path, output_path, comfy_dir=comfy_dir)
"""
        runner_path.write_text(runner_code, encoding="utf-8")

        command = [
            python_exe,
            str(runner_path),
            str(input_path),
            str(output_path),
            str(exporter_path),
            str(comfy_dir),
        ]
        logger.info("Launching browser export conversion: %s", command)
        subprocess.check_call(command, cwd=str(SCRIPT_DIR))

        if not output_path.exists():
            raise RuntimeError("Browser export did not produce an output file.")

        with output_path.open("r", encoding="utf-8") as handle:
            converted = json.load(handle)
        if not isinstance(converted, dict):
            raise RuntimeError("Browser export returned an unexpected payload.")
        return converted
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"Browser conversion failed: {exc}") from exc
    finally:
        for path in (input_path, output_path, runner_path):
            try:
                if path.exists():
                    path.unlink()
            except Exception:
                pass
