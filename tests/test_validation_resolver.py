import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from charon.comfy_environment import ComfyEnvironment
from charon.validation_resolver import (
    install_custom_nodes_via_playwright,
    relocate_model_to_category,
)


class ValidationResolverTests(unittest.TestCase):
    def test_playwright_install_uses_runtime_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            comfy_dir = os.path.join(tmp, "ComfyUI")
            embedded_root = os.path.join(tmp, "python_embeded")
            os.makedirs(comfy_dir)
            os.makedirs(embedded_root)
            python_exe = os.path.join(embedded_root, "python.exe")
            open(python_exe, "wb").close()
            runtime = ComfyEnvironment(
                configured_path=tmp,
                base_url="http://render-node:9000",
                base_dir=tmp,
                comfy_dir=comfy_dir,
                models_dir=os.path.join(comfy_dir, "models"),
                python_exe=python_exe,
                embedded_root=embedded_root,
            )
            completed = SimpleNamespace(
                returncode=0,
                stdout='{"installed": [], "skipped": [], "failed": []}',
                stderr="",
            )

            with mock.patch(
                "charon.validation_resolver.resolve_comfy_runtime",
                return_value=runtime,
            ):
                with mock.patch(
                    "charon.validation_resolver.ComfyUIClient.test_connection",
                    return_value=True,
                ):
                    with mock.patch(
                        "charon.validation_resolver.subprocess.run",
                        return_value=completed,
                    ) as run:
                        result = install_custom_nodes_via_playwright(
                            tmp,
                            ["https://example.com/custom-node.git"],
                        )

            self.assertFalse(result.failed)
            self.assertEqual(run.call_args.args[0][-1], runtime.base_url)


class RelocateModelToCategoryTests(unittest.TestCase):
    def _make_model(self, models_root, category, name):
        folder = os.path.join(models_root, category)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name)
        with open(path, "wb") as handle:
            handle.write(b"weights")
        return path

    def test_moves_misplaced_model_into_expected_category(self):
        with tempfile.TemporaryDirectory() as models_root:
            stray = self._make_model(models_root, "vae", "ltx-checkpoint.safetensors")
            reference = {"name": "ltx-checkpoint.safetensors", "category": "checkpoints", "manifest_category": "checkpoints"}

            final_path, moved = relocate_model_to_category(stray, reference, models_root)

            self.assertTrue(moved)
            self.assertEqual(
                os.path.normcase(final_path),
                os.path.normcase(
                    os.path.join(models_root, "checkpoints", "ltx-checkpoint.safetensors")
                ),
            )
            self.assertTrue(os.path.isfile(final_path))
            self.assertFalse(os.path.exists(stray))

    def test_does_not_move_without_manifest_backing(self):
        # A category that was only inferred from node names is not authoritative:
        # two workflows with conflicting inferences must not ping-pong the file.
        with tempfile.TemporaryDirectory() as models_root:
            stray = self._make_model(models_root, "vae", "model.safetensors")
            reference = {"name": "model.safetensors", "category": "checkpoints"}

            final_path, moved = relocate_model_to_category(stray, reference, models_root)

            self.assertFalse(moved)
            self.assertEqual(os.path.normcase(final_path), os.path.normcase(stray))
            self.assertTrue(os.path.isfile(stray))

    def test_leaves_correctly_placed_model_alone(self):
        with tempfile.TemporaryDirectory() as models_root:
            path = self._make_model(models_root, "checkpoints", "model.safetensors")
            reference = {"name": "model.safetensors", "category": "checkpoints", "manifest_category": "checkpoints"}

            final_path, moved = relocate_model_to_category(path, reference, models_root)

            self.assertFalse(moved)
            self.assertEqual(os.path.normcase(final_path), os.path.normcase(path))

    def test_leaves_alias_category_alone(self):
        with tempfile.TemporaryDirectory() as models_root:
            path = self._make_model(models_root, "clip", "encoder.safetensors")
            reference = {"name": "encoder.safetensors", "category": "text_encoders", "manifest_category": "text_encoders"}

            final_path, moved = relocate_model_to_category(path, reference, models_root)

            self.assertFalse(moved)
            self.assertEqual(os.path.normcase(final_path), os.path.normcase(path))

    def test_never_moves_files_outside_models_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            models_root = os.path.join(tmp, "models")
            os.makedirs(os.path.join(models_root, "checkpoints"))
            outside = os.path.join(tmp, "elsewhere", "model.safetensors")
            os.makedirs(os.path.dirname(outside))
            with open(outside, "wb") as handle:
                handle.write(b"weights")
            reference = {"name": "model.safetensors", "category": "checkpoints", "manifest_category": "checkpoints"}

            final_path, moved = relocate_model_to_category(outside, reference, models_root)

            self.assertFalse(moved)
            self.assertEqual(os.path.normcase(final_path), os.path.normcase(outside))
            self.assertTrue(os.path.isfile(outside))

    def test_prefers_existing_copy_at_destination(self):
        with tempfile.TemporaryDirectory() as models_root:
            stray = self._make_model(models_root, "vae", "model.safetensors")
            existing = self._make_model(models_root, "checkpoints", "model.safetensors")
            reference = {"name": "model.safetensors", "category": "checkpoints", "manifest_category": "checkpoints"}

            final_path, moved = relocate_model_to_category(stray, reference, models_root)

            self.assertFalse(moved)
            self.assertEqual(os.path.normcase(final_path), os.path.normcase(existing))
            self.assertTrue(os.path.isfile(stray))


if __name__ == "__main__":
    unittest.main()
