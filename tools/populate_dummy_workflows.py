"""
Populate the `workflows/` directory with richer dummy data for the Galt clone.

Each workflow folder receives:
  - `.charon.json` metadata describing the preset
  - `workflow.json` with a small illustrative node graph
  - `README.md` summarizing usage and tags

Run this script once after cloning or whenever you want to refresh the samples.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List


BASE_PATH = Path(r"C:\Users\kien\git\Charon\workflows")

# Minimal dependency shortcuts so the metadata feels real without being verbose.
DEPENDENCIES: Dict[str, Dict[str, str]] = {
    "charon-core": {"name": "charon-core", "repo": "https://github.com/example/charon-core", "ref": "main"},
    "denoise-suite": {"name": "denoise-suite", "repo": "https://github.com/example/denoise-suite", "ref": "v0.9.2"},
    "depth-labs": {"name": "depth-labs", "repo": "https://github.com/example/depth-labs", "ref": "release/2.0"},
    "stylebank": {"name": "stylebank", "repo": "https://github.com/example/stylebank", "ref": "v1.4.1"},
    "prompt-tools": {"name": "prompt-tools", "repo": "https://github.com/example/prompt-tools", "ref": "main"},
    "cleanup-tools": {"name": "cleanup-tools", "repo": "https://github.com/example/cleanup-tools", "ref": "v2.1.0"},
    "stereo-kit": {"name": "stereo-kit", "repo": "https://github.com/example/stereo-kit", "ref": "v0.4.0"},
    "hdr-kit": {"name": "hdr-kit", "repo": "https://github.com/example/hdr-kit", "ref": "main"},
    "ai-keyer": {"name": "ai-keyer", "repo": "https://github.com/example/ai-keyer", "ref": "v1.1.0"},
    "look-pack": {"name": "look-pack", "repo": "https://github.com/example/look-pack", "ref": "main"},
    "benchmark-suite": {"name": "benchmark-suite", "repo": "https://github.com/example/benchmark-suite", "ref": "v0.2.0"},
    "tween-lab": {"name": "tween-lab", "repo": "https://github.com/example/tween-lab", "ref": "v1.0.0"},
    "camera-tools": {"name": "camera-tools", "repo": "https://github.com/example/camera-tools", "ref": "v3.3.1"},
    "weather-pack": {"name": "weather-pack", "repo": "https://github.com/example/weather-pack", "ref": "main"},
    "grain-library": {"name": "grain-library", "repo": "https://github.com/example/grain-library", "ref": "v1.0.5"},
}


USERS: Dict[str, List[Dict[str, str]]] = {
    "alice": [
        {
            "slug": "speed_grade",
            "display_name": "Speed Grade Diffusion",
            "description": "Grades a plate using tone curves and writes a single preview frame.",
            "tags": ["comfy", "grading", "FLUX"],
            "deps": ["charon-core", "comfy-colors"],
            "last_changed": "2025-10-18T16:32:00Z",
        },
        {
            "slug": "texture_magic",
            "display_name": "Texture Magic Atlas",
            "description": "Builds a texture UDIM atlas and saves a high-res preview.",
            "tags": ["comfy", "textures", "Nano-Banana"],
            "deps": ["charon-core", "texture-baker"],
            "last_changed": "2025-10-12T09:05:30Z",
        },
    ],
    "bob": [
        {
            "slug": "deep_composite",
            "display_name": "Deep Composite Merge",
            "description": "Merges deep EXR layers using front compositing.",
            "tags": ["comfy", "deep", "MergeMaster"],
            "deps": ["charon-core", "deep-toolkit"],
            "last_changed": "2025-09-28T21:11:45Z",
        },
        {
            "slug": "roto_helper",
            "display_name": "Roto Mask Helper",
            "description": "Smooths roto mattes and outputs sanitized masks for keyers.",
            "tags": ["comfy", "mask", "Nano-Banana"],
            "deps": ["charon-core"],
            "last_changed": "2025-10-01T11:24:00Z",
        },
    ],
    "carol": [
        {
            "slug": "lighting_suite",
            "display_name": "Lighting Suite Batch",
            "description": "Applies a studio lighting preset to a USD layout and renders a preview.",
            "tags": ["comfy", "lighting", "FLUX"],
            "deps": ["charon-core", "usd-preset-pack"],
            "last_changed": "2025-10-15T05:56:10Z",
        },
        {
            "slug": "fx_batch",
            "display_name": "FX Batch Runner",
            "description": "Post-processes a VDB cache, renders a few frames, and stores the sequence.",
            "tags": ["comfy", "fx", "InfernoXL"],
            "deps": ["charon-core", "fx-library"],
            "last_changed": "2025-10-19T14:45:00Z",
        },
    ],
    "david": [
        {
            "slug": "denoise_batch",
            "display_name": "Denoise Batch Frames",
            "description": "Runs SDXL denoising on an image sequence and saves previews.",
            "tags": ["comfy", "denoise", "SDXL"],
            "deps": ["charon-core", "denoise-suite"],
            "last_changed": "2025-10-10T08:15:00Z",
        },
        {
            "slug": "depth_matting",
            "display_name": "Depth Aware Matting",
            "description": "Generates depth-driven mattes for green screen plates.",
            "tags": ["comfy", "depth", "matte"],
            "deps": ["charon-core", "depth-labs"],
            "last_changed": "2025-10-11T12:05:30Z",
        },
    ],
    "ella": [
        {
            "slug": "style_transfer",
            "display_name": "Stylized Transfer Pack",
            "description": "Applies curated style prompts to key art assets for look exploration.",
            "tags": ["comfy", "style", "FLUX"],
            "deps": ["stylebank"],
            "last_changed": "2025-10-05T18:40:00Z",
        },
        {
            "slug": "prompt_variations",
            "display_name": "Prompt Variation Sweep",
            "description": "Generates a grid of prompt variations for internal reviews.",
            "tags": ["comfy", "prompt", "Nano-Banana"],
            "deps": ["prompt-tools"],
            "last_changed": "2025-10-03T09:32:14Z",
        },
    ],
    "frank": [
        {
            "slug": "cleanup_suite",
            "display_name": "Cleanup Suite",
            "description": "Performs plate cleanup with inpainting and grain restore.",
            "tags": ["comfy", "cleanup", "InfernoXL"],
            "deps": ["cleanup-tools"],
            "last_changed": "2025-09-29T22:10:00Z",
        },
        {
            "slug": "stereo_align",
            "display_name": "Stereo Alignment Helper",
            "description": "Aligns stereo pairs using disparity estimation.",
            "tags": ["comfy", "stereo", "depth"],
            "deps": ["stereo-kit"],
            "last_changed": "2025-10-08T15:47:00Z",
        },
    ],
    "gina": [
        {
            "slug": "hdr_merger",
            "display_name": "HDR Merge Toolkit",
            "description": "Combines exposure brackets into a single HDR preview.",
            "tags": ["comfy", "hdr", "MergeMaster"],
            "deps": ["hdr-kit"],
            "last_changed": "2025-10-16T07:25:00Z",
        },
        {
            "slug": "ai_keying",
            "display_name": "AI Keying Batch",
            "description": "Runs AI keyer presets across multiple plates for QC.",
            "tags": ["comfy", "keying", "Nano-Banana"],
            "deps": ["ai-keyer"],
            "last_changed": "2025-10-14T19:20:45Z",
        },
    ],
    "harper": [
        {
            "slug": "lookdev_compare",
            "display_name": "Lookdev Compare Board",
            "description": "Generates a contact sheet comparing multiple look presets.",
            "tags": ["comfy", "lookdev", "FLUX"],
            "deps": ["look-pack"],
            "last_changed": "2025-10-18T10:00:00Z",
        },
        {
            "slug": "model_benchmarks",
            "display_name": "Model Benchmark Runner",
            "description": "Benchmarks favorite diffusion models on a standard prompt list.",
            "tags": ["comfy", "benchmark", "InfernoXL"],
            "deps": ["benchmark-suite"],
            "last_changed": "2025-10-09T13:12:00Z",
        },
    ],
    "ivan": [
        {
            "slug": "animation_keyframes",
            "display_name": "Animation Keyframe Expander",
            "description": "Interpolates keyframes into in-between frames using AI tweening.",
            "tags": ["comfy", "animation", "Nano-Banana"],
            "deps": ["tween-lab"],
            "last_changed": "2025-10-07T17:55:00Z",
        },
        {
            "slug": "camera_match",
            "display_name": "Camera Match Visualizer",
            "description": "Shows lineup of CG renders with the live-action plate for quick QC.",
            "tags": ["comfy", "camera", "FX"],
            "deps": ["camera-tools"],
            "last_changed": "2025-10-04T20:05:00Z",
        },
    ],
    "jamal": [
        {
            "slug": "weather_adjust",
            "display_name": "Weather Adjustment Toolkit",
            "description": "Adds rain and fog overlays to plates for concept previews.",
            "tags": ["comfy", "fx", "FLUX"],
            "deps": ["weather-pack"],
            "last_changed": "2025-10-02T11:25:00Z",
        },
        {
            "slug": "grain_profiles",
            "display_name": "Film Grain Profiles",
            "description": "Applies film grain presets and exports side-by-side comparisons.",
            "tags": ["comfy", "grain", "InfernoXL"],
            "deps": ["grain-library"],
            "last_changed": "2025-10-13T14:18:00Z",
        },
    ],
}


def resolve_dependencies(keys: List[str]) -> List[Dict[str, str]]:
    result = []
    for key in keys:
        dep = DEPENDENCIES.get(key)
        if dep:
            result.append(dep)
        else:
            result.append(
                {
                    "name": key,
                    "repo": f"https://github.com/example/{key}",
                    "ref": "main",
                }
            )
    return result


def build_graph(slug: str, tags: List[str]) -> Dict[str, object]:
    primary_tag = tags[0] if tags else "comfy"
    nodes = {
        "1": {"class_type": "LoadWorkflowPreset", "inputs": {"path": f"presets/{slug}.json"}},
        "2": {"class_type": "CharonAnnotate", "inputs": {"preset": ["1", "PRESET"], "label": primary_tag}},
        "3": {"class_type": "SaveWorkflowSummary", "inputs": {"preset": ["2", "PRESET"], "filename": f"exports/{slug}_summary.json"}},
    }
    links = [
        ["1", "PRESET", "2", "preset"],
        ["2", "PRESET", "3", "preset"],
    ]
    return {"workflow_name": slug.replace("_", " ").title(), "nodes": nodes, "links": links}


def write_workflow(user: str, entry: Dict[str, str]) -> None:
    workflow_dir = BASE_PATH / user / entry["slug"]
    workflow_dir.mkdir(parents=True, exist_ok=True)

    metadata = {
        "workflow_file": "workflow.json",
        "description": entry["description"],
        "dependencies": resolve_dependencies(entry["deps"]),
        "last_changed": entry["last_changed"],
        "tags": entry["tags"],
    }
    (workflow_dir / ".charon.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    workflow_payload = build_graph(entry["slug"], entry["tags"])
    (workflow_dir / "workflow.json").write_text(json.dumps(workflow_payload, indent=2), encoding="utf-8")

    readme = (
        f"# {entry['display_name']}\n\n"
        f"{entry['description']}\n\n"
        f"**Tags:** {', '.join(entry['tags'])}\n"
        f"**Last Changed:** {entry['last_changed']}\n"
    )
    (workflow_dir / "README.md").write_text(readme, encoding="utf-8")


def main() -> None:
    for user, workflows in USERS.items():
        for entry in workflows:
            write_workflow(user, entry)
    timestamp = datetime.now().isoformat(timespec="seconds")
    print(f"Dummy workflows refreshed at {timestamp}")


if __name__ == "__main__":
    main()
