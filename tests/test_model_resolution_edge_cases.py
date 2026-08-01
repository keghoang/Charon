"""Edge-case tests for the model *location* pipeline.

Companion to test_model_transfer_edge_cases.py: these pin down the ways
Charon could fail to locate a model that actually exists (or invent a
missing model that ComfyUI would load fine).
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

from charon.comfy_validation import (
    MODEL_EXTENSIONS,
    _build_model_index,
    _category_for_node,
    _find_model_file,
    _looks_like_model_file,
    _lookup_model_in_index,
    _resolved_path_matches_reference,
    _validate_models,
)
from charon.model_manifest import (
    category_from_shared_path,
    manifest_entry_for_name,
    write_model_manifest,
)


class ModelExtensionCoverageTests(unittest.TestCase):
    def test_gguf_models_are_detected_as_model_references(self):
        # Quantized Flux/Wan models ship as .gguf; validation must see them.
        self.assertIn(".gguf", MODEL_EXTENSIONS)
        self.assertTrue(_looks_like_model_file("flux1-dev-Q8_0.gguf"))

    def test_sft_models_are_detected_as_model_references(self):
        # .sft is an alternate safetensors extension used by published models.
        self.assertIn(".sft", MODEL_EXTENSIONS)
        self.assertTrue(_looks_like_model_file("ae.sft"))

    def test_yaml_counts_as_a_model_file(self):
        # Documents intent: .yaml is treated as a model reference (control
        # net configs).
        self.assertTrue(_looks_like_model_file("anything.yaml"))


class CategoryHeuristicTests(unittest.TestCase):
    def test_filename_substring_misclassifies_unrelated_models(self):
        # CHARACTERIZATION: category inference uses substring checks on the
        # file name, so unrelated names land in the wrong category.  This is
        # tolerated because the heuristic is only a starting guess: when
        # ComfyUI's resolver finds the file in another category,
        # _validate_models trusts the resolver (see
        # ValidateModelsCategoryTrustTests).
        cases = {
            "flora_portrait_v2.safetensors": "loras",       # "lora" in "flora"
            "eclipse_render_photo.safetensors": "clip",      # "clip" in "eclipse"
            "brunette_hair_detail.safetensors": "diffusion_models",  # "unet"
        }
        for file_name, wrong_category in cases.items():
            with self.subTest(file_name=file_name):
                self.assertEqual(
                    wrong_category,
                    _category_for_node("SomeCustomNode", file_name),
                )

    def test_unknown_loader_defaults_to_checkpoints(self):
        self.assertEqual(
            "checkpoints",
            _category_for_node("NunchakuQwenImageDiTLoader", "qwen_image.safetensors"),
        )


class ResolvedPathMatchTests(unittest.TestCase):
    def test_extra_model_paths_locations_are_accepted_by_name(self):
        # Models served through extra_model_paths.yaml live outside
        # models_root; ComfyUI loads them fine, so a matching file name is
        # accepted rather than reported missing.
        with tempfile.TemporaryDirectory() as tmp:
            models_root = os.path.join(tmp, "ComfyUI", "models")
            external = os.path.join(tmp, "shared_drive", "checkpoints", "model.safetensors")
            self.assertTrue(
                _resolved_path_matches_reference(
                    "model.safetensors",
                    external,
                    models_root,
                    reference_category="checkpoints",
                )
            )

    def test_external_path_with_wrong_name_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            models_root = os.path.join(tmp, "ComfyUI", "models")
            external = os.path.join(tmp, "shared_drive", "other_model.safetensors")
            self.assertFalse(
                _resolved_path_matches_reference(
                    "model.safetensors",
                    external,
                    models_root,
                    reference_category="checkpoints",
                )
            )

    def test_wrong_category_inside_models_root_is_rejected(self):
        # Inside models_root the category still matters: a checkpoint value
        # pointing at a file that only exists in diffusion_models/ would fail
        # ComfyUI prompt validation, so the strict check stands.  Callers are
        # responsible for passing an authoritative category (manifest or the
        # resolver's own result) rather than a heuristic guess.
        with tempfile.TemporaryDirectory() as tmp:
            models_root = os.path.join(tmp, "models")
            resolved = os.path.join(models_root, "diffusion_models", "qwen_image.safetensors")
            self.assertFalse(
                _resolved_path_matches_reference(
                    "qwen_image.safetensors",
                    resolved,
                    models_root,
                    reference_category="checkpoints",
                )
            )

    def test_known_aliases_are_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            models_root = os.path.join(tmp, "models")
            resolved = os.path.join(models_root, "text_encoders", "clip_l.safetensors")
            self.assertTrue(
                _resolved_path_matches_reference(
                    "clip_l.safetensors",
                    resolved,
                    models_root,
                    reference_category="clip",
                )
            )


class ValidateModelsCategoryTrustTests(unittest.TestCase):
    """The heuristic category guess must not override ComfyUI's resolver."""

    def _make_env(self, tmp):
        comfy_dir = os.path.join(tmp, "ComfyUI")
        models_root = os.path.join(comfy_dir, "models")
        target_dir = os.path.join(models_root, "diffusion_models")
        os.makedirs(target_dir)
        target = os.path.join(target_dir, "qwen_image.safetensors")
        with open(target, "wb") as handle:
            handle.write(b"x")
        env_info = {
            "comfy_dir": comfy_dir,
            "models_dir": models_root,
            "python_exe": sys.executable,
        }
        workflow = {
            "nodes": [
                {
                    "id": 1,
                    "type": "NunchakuQwenImageDiTLoader",
                    "widgets_values": ["qwen_image.safetensors"],
                }
            ]
        }
        return env_info, models_root, target, workflow

    def test_resolver_fallback_category_is_trusted_without_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_info, _root, target, workflow = self._make_env(tmp)
            bundle = {"workflow": workflow, "folder": None}
            resolver = {
                "resolved": {0: target},
                "categories": {0: "diffusion_models"},
                "missing": [],
                "errors": [],
            }
            with mock.patch(
                "charon.comfy_validation._resolve_models_with_comfy",
                return_value=resolver,
            ):
                issue = _validate_models(env_info, bundle)
            self.assertTrue(
                issue.ok,
                f"resolver-found model must not be reported missing: {issue.summary}",
            )

    def test_manifest_backed_category_stays_authoritative(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_info, _root, target, workflow = self._make_env(tmp)
            workflow_folder = os.path.join(tmp, "workflow")
            os.makedirs(workflow_folder)
            write_model_manifest(
                workflow_folder,
                [
                    {
                        "name": "qwen_image.safetensors",
                        "category": "checkpoints",
                        "shared_path": "checkpoints/qwen_image.safetensors",
                    }
                ],
            )
            bundle = {"workflow": workflow, "folder": workflow_folder}
            resolver = {
                "resolved": {0: target},
                "categories": {0: "diffusion_models"},
                "missing": [],
                "errors": [],
            }
            with mock.patch(
                "charon.comfy_validation._resolve_models_with_comfy",
                return_value=resolver,
            ):
                issue = _validate_models(env_info, bundle)
            self.assertFalse(
                issue.ok,
                "a manifest-backed category mismatch is a real misplacement",
            )


class FallbackSearchTests(unittest.TestCase):
    def test_find_model_file_does_not_know_category_aliases(self):
        # _find_model_file only checks the literal category folder; the
        # aliased folder is covered by the index fallback.  Document that
        # reliance so a regression in the index lookup is caught.
        with tempfile.TemporaryDirectory() as tmp:
            models_root = os.path.join(tmp, "models")
            target_dir = os.path.join(models_root, "diffusion_models")
            os.makedirs(target_dir)
            target = os.path.join(target_dir, "model.safetensors")
            with open(target, "wb") as handle:
                handle.write(b"x")

            reference = {"name": "model.safetensors", "category": "unet"}
            located, _path = _find_model_file(models_root, tmp, reference)
            self.assertFalse(located, "direct lookup misses the aliased folder")

            index = _build_model_index(models_root)
            located, resolved = _lookup_model_in_index(index, reference, models_root)
            self.assertTrue(located, "index fallback must cover category aliases")
            self.assertEqual(os.path.abspath(target), resolved)

    def test_model_index_covers_deeply_nested_models(self):
        # Users organize loras several folders deep; the fallback index must
        # still find them (bounded at depth 6 to keep huge trees walkable).
        with tempfile.TemporaryDirectory() as tmp:
            models_root = os.path.join(tmp, "models")
            nested_dir = os.path.join(models_root, "loras", "artist", "style", "pack")
            too_deep_dir = os.path.join(models_root, "a", "b", "c", "d", "e", "f", "g")
            os.makedirs(nested_dir)
            os.makedirs(too_deep_dir)
            nested = os.path.join(nested_dir, "nested.safetensors")
            too_deep = os.path.join(too_deep_dir, "too_deep.safetensors")
            for path in (nested, too_deep):
                with open(path, "wb") as handle:
                    handle.write(b"x")

            index = _build_model_index(models_root)
            self.assertIn("nested.safetensors", index)
            self.assertNotIn("too_deep.safetensors", index)


class SharedRepoCategoryTests(unittest.TestCase):
    def test_file_at_shared_root_has_no_category(self):
        # A model dropped directly at the shared repo root must not turn its
        # own file name into a category (models/<file>/<file> destinations).
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "model.safetensors")
            self.assertIsNone(category_from_shared_path(path, tmp))

    def test_file_in_category_folder_yields_that_category(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "checkpoints", "model.safetensors")
            self.assertEqual("checkpoints", category_from_shared_path(path, tmp))


class ManifestAmbiguityTests(unittest.TestCase):
    def test_duplicate_basenames_without_category_hint_resolve_to_nothing(self):
        manifest = {
            "schema": 1,
            "models": [
                {"name": "model.safetensors", "category": "loras", "shared_path": "loras/model.safetensors"},
                {"name": "model.safetensors", "category": "vae", "shared_path": "vae/model.safetensors"},
            ],
        }
        self.assertIsNone(manifest_entry_for_name(manifest, "model.safetensors"))
        entry = manifest_entry_for_name(manifest, "model.safetensors", category="vae")
        self.assertEqual("vae", entry["category"])


if __name__ == "__main__":
    unittest.main()
