import os
import tempfile
import unittest

from charon.model_paths import (
    derive_workflow_value_from_path,
    normalize_workflow_model_value,
    strip_model_category_prefix,
)
from charon.comfy_validation import _validate_models_browser
from charon.paths import resolve_comfy_environment


class ModelPathTests(unittest.TestCase):
    def test_strips_models_and_category_prefixes(self):
        self.assertEqual(
            strip_model_category_prefix("models/diffusion_models/ltx/model.safetensors"),
            "ltx/model.safetensors",
        )
        self.assertEqual(
            strip_model_category_prefix("text_encoders/ltx/text_encoder.safetensors"),
            "ltx/text_encoder.safetensors",
        )

    def test_preserves_simple_workflow_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            comfy_dir = os.path.join(tmp, "ComfyUI")
            models_root = os.path.join(comfy_dir, "models")
            category_root = os.path.join(models_root, "diffusion_models", "ltx")
            os.makedirs(category_root)
            resolved_path = os.path.join(category_root, "model.safetensors")

            value = derive_workflow_value_from_path(
                resolved_path,
                ("model.safetensors", "diffusion_models", "UNETLoader"),
                models_root,
                comfy_dir,
            )

            self.assertEqual(value, "model.safetensors")

    def test_preserves_subfolder_below_model_category(self):
        with tempfile.TemporaryDirectory() as tmp:
            comfy_dir = os.path.join(tmp, "ComfyUI")
            models_root = os.path.join(comfy_dir, "models")
            category_root = os.path.join(models_root, "diffusion_models", "ltx")
            os.makedirs(category_root)
            resolved_path = os.path.join(category_root, "model.safetensors")

            value = derive_workflow_value_from_path(
                resolved_path,
                ("ltx/model.safetensors", "diffusion_models", "UNETLoader"),
                models_root,
                comfy_dir,
            )

            expected = normalize_workflow_model_value("ltx/model.safetensors")
            self.assertEqual(value, expected)

    def test_does_not_treat_similarly_named_external_path_as_a_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            comfy_dir = os.path.join(tmp, "ComfyUI")
            models_root = os.path.join(comfy_dir, "models")
            external_root = os.path.join(tmp, "models_backup")
            os.makedirs(models_root)
            os.makedirs(external_root)
            resolved_path = os.path.join(external_root, "model.safetensors")

            value = derive_workflow_value_from_path(
                resolved_path,
                ("folder/model.safetensors", "checkpoints", "CheckpointLoaderSimple"),
                models_root,
                comfy_dir,
            )

            self.assertEqual(value, normalize_workflow_model_value(resolved_path))

    def test_validation_uses_resolved_models_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            portable_root = os.path.join(tmp, "ComfyUI_windows_portable")
            comfy_dir = os.path.join(portable_root, "ComfyUI")
            models_dir = os.path.join(comfy_dir, "models")
            embedded_root = os.path.join(portable_root, "python_embeded")
            os.makedirs(models_dir)
            os.makedirs(embedded_root)
            open(os.path.join(embedded_root, "python.exe"), "wb").close()
            env_info = resolve_comfy_environment(models_dir)

            issue = _validate_models_browser(env_info, None, None)

            self.assertTrue(issue.ok)
            self.assertEqual(issue.data["models_root"], models_dir)


if __name__ == "__main__":
    unittest.main()
