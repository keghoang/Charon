import hashlib
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

LOG_FILENAME = "conversion_log.md"
CONVERTED_SUFFIX = "_converted.json"
CACHE_FOLDER_NAME = ".charon_cache"
LEGACY_CACHE_FOLDER_NAME = "_API_conversion"


def _conversion_dir(folder_path: str) -> Path:
    base = Path(folder_path)
    new_dir = base / CACHE_FOLDER_NAME
    legacy_dir = base / LEGACY_CACHE_FOLDER_NAME
    if legacy_dir.exists() and not new_dir.exists():
        try:
            shutil.move(str(legacy_dir), str(new_dir))
        except OSError:
            return legacy_dir
    return new_dir


def _log_path(folder_path: str) -> Path:
    return _conversion_dir(folder_path) / LOG_FILENAME


def _default_prompt_name(workflow_path: str, hash_value: str) -> str:
    base = Path(workflow_path).stem or "workflow"
    return f"{base}_{hash_value[:8]}{CONVERTED_SUFFIX}"


def compute_workflow_hash(workflow_payload: Dict[str, Any]) -> str:
    """
    Compute a stable SHA256 hash for the workflow payload.
    We sort keys to avoid ordering differences.
    """
    serialized = json.dumps(workflow_payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def load_cached_conversion(folder_path: str, workflow_hash: str) -> Optional[Dict[str, str]]:
    """
    Return info about a cached conversion if the stored hash matches and the prompt exists.
    """
    log_file = _log_path(folder_path)
    if not log_file.exists():
        return None

    try:
        content = log_file.read_text(encoding="utf-8")
    except Exception:
        return None

    hash_line = None
    prompt_line = None
    for line in content.splitlines():
        striped = line.strip()
        if striped.startswith("- workflow_hash:"):
            hash_line = striped.split(":", 1)[1].strip()
        elif striped.startswith("- prompt_file:"):
            prompt_line = striped.split(":", 1)[1].strip()

    if not hash_line or not prompt_line:
        return None
    if hash_line != workflow_hash:
        return None

    prompt_path = _conversion_dir(folder_path) / prompt_line
    if not prompt_path.exists():
        return None

    return {
        "prompt_path": str(prompt_path),
        "prompt_filename": prompt_line,
        "workflow_hash": workflow_hash,
    }


def write_conversion_cache(folder_path: str, workflow_path: str, workflow_hash: str, prompt_path: str) -> str:
    """
    Record the conversion info and ensure the converted prompt lives under .charon_cache.
    Returns the stored prompt path.
    """
    conversion_dir = _conversion_dir(folder_path)
    conversion_dir.mkdir(parents=True, exist_ok=True)

    prompt_filename = Path(prompt_path).name
    target_path = conversion_dir / prompt_filename

    # Ensure prompt lives under the cache directory
    if Path(prompt_path) != target_path:
        try:
            os.replace(prompt_path, target_path)
        except FileNotFoundError:
            raise

    timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    log_lines = [
        "# Conversion Cache",
        f"- workflow_hash: {workflow_hash}",
        f"- converted_at: {timestamp}",
        f"- prompt_file: {target_path.name}",
    ]

    log_file = _log_path(folder_path)
    log_file.write_text("\n".join(log_lines) + "\n", encoding="utf-8")

    return str(target_path)


def desired_prompt_path(folder_path: str, workflow_path: str, workflow_hash: str) -> Path:
    conversion_dir = _conversion_dir(folder_path)
    filename = _default_prompt_name(workflow_path, workflow_hash)
    return conversion_dir / filename


def clear_conversion_cache(folder_path: str) -> None:
    """
    Remove cached conversion artifacts for the given workflow directory.
    Safe to call even when the cache is already empty.
    """
    conversion_dir = _conversion_dir(folder_path)
    if not conversion_dir.exists():
        return

    try:
        import shutil

        shutil.rmtree(conversion_dir)
    except OSError:
        pass
