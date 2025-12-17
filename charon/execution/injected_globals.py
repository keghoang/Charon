"""Globals injected into script execution namespaces."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Any

from ..settings import user_settings_db


def collect_globals(script_name: str) -> Dict[str, Any]:
    """Return a mapping of globals shared with executed scripts."""
    if not script_name:
        script_name = "unnamed"

    base_dir = Path(user_settings_db.get_storage_directory()).parent
    plugins_dir = (base_dir / "plugins" / script_name).resolve()
    # Leave directory creation to scripts that actually need it

    return {
        "GALT_PLUGIN_DIR": str(plugins_dir),
    }
