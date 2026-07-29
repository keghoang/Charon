import os
import tempfile
import unittest
from unittest import mock

from charon.comfy_validation import (
    _collect_model_references,
    _resolved_path_matches_reference,
)
from charon.model_manifest import (
    load_model_manifest,
    manifest_entry_for_name,
    model_manifest_hash,
    write_model_manifest,
)
from charon.validation_resolver import reference_for_shared_model


class ModelManifestTests(unittest.TestCase):
    def test_round_trip_preserves_authoritative_shared_category(self):
        with tempfile.TemporaryDirectory() as workflow_folder:
            path = write_model_manifest(
                workflow_folder,
                [
                    {
                        "name": "gemma.safetensors",
                        "category": "clip",
                        "shared_path": "clip/gemma.safetensors",
                        "size": 123,
                    }
                ],
            )

            payload = load_model_manifest(workflow_folder)

            self.assertTrue(os.path.isfile(path))
            self.assertEqual(
                manifest_entry_for_name(payload, "gemma.safetensors"),
                {
                    "name": "gemma.safetensors",
                    "category": "clip",
                    "shared_path": "clip/gemma.safetensors",
                    "size": 123,
                },
            )
            self.assertTrue(model_manifest_hash(workflow_folder))

    def test_manifest_and_input_fields_classify_compound_ltx_loader(self):
        with tempfile.TemporaryDirectory() as workflow_folder:
            write_model_manifest(
                workflow_folder,
                [
                    {
                        "name": "gemma.safetensors",
                        "category": "clip",
                        "shared_path": "clip/gemma.safetensors",
                    }
                ],
            )
            bundle = {
                "folder": workflow_folder,
                "workflow": {
                    "320:317": {
                        "class_type": "LTXAVTextEncoderLoader",
                        "inputs": {
                            "text_encoder": "gemma.safetensors",
                            "ckpt_name": "ltx.safetensors",
                        },
                    }
                },
            }

            references = _collect_model_references(bundle)
            by_name = {entry["name"]: entry for entry in references}

            self.assertEqual(by_name["gemma.safetensors"]["category"], "clip")
            self.assertEqual(by_name["gemma.safetensors"]["input_name"], "text_encoder")
            self.assertEqual(by_name["ltx.safetensors"]["category"], "checkpoints")
            self.assertEqual(by_name["ltx.safetensors"]["input_name"], "ckpt_name")

    def test_frontend_ltx_widget_order_uses_distinct_categories(self):
        bundle = {
            "workflow": {
                "nodes": [
                    {
                        "id": "320:317",
                        "type": "LTXAVTextEncoderLoader",
                        "widgets_values": [
                            "gemma.safetensors",
                            "ltx.safetensors",
                            "default",
                        ],
                    },
                    {
                        "id": "320:311",
                        "type": "LatentUpscaleModelLoader",
                        "widgets_values": ["upscaler.safetensors"],
                    },
                ]
            }
        }

        references = _collect_model_references(bundle)
        by_name = {entry["name"]: entry for entry in references}

        self.assertEqual(by_name["gemma.safetensors"]["category"], "text_encoders")
        self.assertEqual(by_name["ltx.safetensors"]["category"], "checkpoints")
        self.assertEqual(
            by_name["upscaler.safetensors"]["category"],
            "latent_upscale_models",
        )

    def test_shared_clip_category_maps_to_target_text_encoders_alias(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            shared_root = os.path.join(temp_dir, "shared")
            models_root = os.path.join(temp_dir, "models")
            shared_path = os.path.join(shared_root, "clip", "gemma.safetensors")
            os.makedirs(os.path.dirname(shared_path))
            os.makedirs(os.path.join(models_root, "text_encoders"))
            with open(shared_path, "wb") as handle:
                handle.write(b"model")

            with mock.patch(
                "charon.validation_resolver.SHARED_MODELS_ROOT",
                shared_root,
            ):
                reference = reference_for_shared_model(
                    {"name": "gemma.safetensors", "category": "checkpoints"},
                    shared_path,
                    models_root,
                )

            self.assertEqual(reference["shared_category"], "clip")
            self.assertEqual(reference["category"], "text_encoders")

    def test_resolved_model_rejects_wrong_category_but_accepts_alias(self):
        with tempfile.TemporaryDirectory() as models_root:
            wrong_path = os.path.join(
                models_root,
                "checkpoints",
                "gemma.safetensors",
            )
            alias_path = os.path.join(
                models_root,
                "clip",
                "gemma.safetensors",
            )

            self.assertFalse(
                _resolved_path_matches_reference(
                    "gemma.safetensors",
                    wrong_path,
                    models_root,
                    reference_category="text_encoders",
                )
            )
            self.assertTrue(
                _resolved_path_matches_reference(
                    "gemma.safetensors",
                    alias_path,
                    models_root,
                    reference_category="text_encoders",
                )
            )


if __name__ == "__main__":
    unittest.main()
