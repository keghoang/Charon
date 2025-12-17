"""
Utility script to inspect a workflow JSON against the active ComfyUI node library.

Run using ComfyUI's embedded Python so that the ``nodes`` module is available:

    python_embeded\\python.exe tools\\inspect_workflow_widgets.py path\\to\\workflow.json
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path
from typing import Any, Dict

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

warnings.filterwarnings("ignore", category=SyntaxWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

from charon.node_introspection import (  # noqa: E402
    NodeLibraryUnavailable,
    collect_workflow_widget_bindings,
)


def _load_document(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("Workflow JSON must contain a top-level object.")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect workflow widgets using ComfyUI's node library.")
    parser.add_argument("workflow", help="Path to a workflow JSON file")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON payload instead of formatted text.",
    )
    args = parser.parse_args()

    try:
        document = _load_document(args.workflow)
    except Exception as exc:  # pragma: no cover - CLI helper
        print(f"[Charon] Failed to load workflow JSON: {exc}", file=sys.stderr)
        return 1

    try:
        bindings = collect_workflow_widget_bindings(document)
    except NodeLibraryUnavailable as exc:  # pragma: no cover - runtime guard
        print(f"[Charon] {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[Charon] Failed to inspect workflow widgets: {exc}", file=sys.stderr)
        return 3

    if args.json:
        payload = [
            {
                "node_id": binding.node_id,
                "node_type": binding.spec.node_type,
                "name": binding.spec.name,
                "value_type": binding.spec.value_type,
                "default": binding.spec.default,
                "choices": list(binding.spec.choices),
                "value": binding.value,
                "source": binding.source,
                "source_index": binding.source_index,
            }
            for binding in bindings
        ]
        print(json.dumps(payload, ensure_ascii=False))
        return 0

    if not bindings:
        print("[Charon] No widget inputs detected in the workflow.")
        return 0

    print(f"[Charon] Found {len(bindings)} widget bindings:")
    for binding in bindings:
        spec = binding.spec
        default = spec.default
        choices = ", ".join(str(choice) for choice in spec.choices) if spec.choices else ""
        value_repr = binding.value
        print(
            f"- Node {binding.node_id} ({spec.node_type})\n"
            f"    input: {spec.name} ({spec.value_type})\n"
            f"    source: {binding.source}\n"
            f"    value: {value_repr}\n"
            f"    default: {default}\n"
            f"    choices: {choices}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
