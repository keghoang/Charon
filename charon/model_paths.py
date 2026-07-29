"""Headless rules for converting resolved model files to workflow values."""

from __future__ import annotations

import os
from typing import Optional, Tuple


# Categories ComfyUI treats as the same folder list (legacy/new names).
CATEGORY_ALIASES = {
    "clip": ("clip", "text_encoders"),
    "text_encoders": ("text_encoders", "clip"),
    "unet": ("unet", "diffusion_models"),
    "diffusion_models": ("diffusion_models", "unet"),
}


def category_aliases(category: Optional[str]) -> Tuple[str, ...]:
    """Return the set of folder names ComfyUI accepts for a model category."""
    normalized = (category or "").strip().strip("/\\").lower()
    if not normalized:
        return ()
    return CATEGORY_ALIASES.get(normalized, (normalized,))


MODEL_CATEGORY_PREFIXES = frozenset(
    {
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
        "latent_upscale_models",
        "upscale_models",
        "upscale",
        "motion_models",
        "motion_loras",
        "styles",
        "style_models",
        "ipadapter",
    }
)


def normalize_workflow_model_value(value: str) -> str:
    """Return a workflow model value using separators native to this host."""
    normalized = (value or "").strip().replace("\\", "/")
    if os.sep == "\\":
        return normalized.replace("/", "\\")
    return normalized


def value_has_path_component(value: Optional[str]) -> bool:
    return bool(value) and "/" in str(value).replace("\\", "/")


def strip_model_category_prefix(value: str) -> str:
    """Remove ComfyUI's models/category prefix from a workflow-relative path."""
    normalized = (value or "").replace("\\", "/").lstrip("/")
    if not normalized:
        return normalized
    if normalized.lower().startswith("models/"):
        normalized = normalized.split("/", 1)[1]
    segments = [segment for segment in normalized.split("/") if segment]
    if len(segments) > 1 and segments[0].lower() in MODEL_CATEGORY_PREFIXES:
        return "/".join(segments[1:])
    return normalized


def derive_workflow_value_from_path(
    path_value: Optional[str],
    signature: Optional[Tuple[Optional[str], Optional[str], Optional[str]]],
    models_root: str,
    comfy_dir: Optional[str],
) -> Optional[str]:
    """Convert a resolved model path to the value expected by a workflow node.

    A workflow that originally used only a filename keeps that shape. Workflows
    that intentionally reference subfolders retain the path below the category.
    """
    if not path_value:
        return None

    abs_path = os.path.abspath(path_value)
    original_name = signature[0] if signature and len(signature) >= 1 else None
    category = signature[1] if signature and len(signature) >= 2 else None
    prefer_simple_name = bool(original_name) and not value_has_path_component(original_name)
    simple_value = normalize_workflow_model_value(os.path.basename(abs_path))

    def finalize(candidate: str) -> str:
        stripped = strip_model_category_prefix(candidate)
        normalized = normalize_workflow_model_value(stripped)
        if prefer_simple_name and simple_value and value_has_path_component(normalized):
            return simple_value
        return normalized

    candidate_roots = []
    if category and models_root:
        candidate_roots.append(os.path.join(models_root, category))
    if models_root:
        candidate_roots.append(models_root)
    if comfy_dir:
        candidate_roots.append(comfy_dir)

    for root in candidate_roots:
        if not os.path.isdir(root):
            continue
        try:
            relative = os.path.relpath(abs_path, root)
        except ValueError:
            continue
        if relative != os.pardir and not relative.startswith(os.pardir + os.sep):
            return finalize(relative)
    return finalize(abs_path)
