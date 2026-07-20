import os
import tempfile
import unittest
from unittest import mock

from charon.comfy_environment import (
    ComfyEnvironment,
    normalize_comfy_url,
    resolve_comfy_runtime,
)


class ComfyEnvironmentTests(unittest.TestCase):
    def test_normalizes_host_and_trailing_paths(self):
        self.assertEqual(normalize_comfy_url("render-node:9000"), "http://render-node:9000")
        self.assertEqual(
            normalize_comfy_url("https://render-node:9000/system_stats"),
            "https://render-node:9000",
        )

    def test_rejects_invalid_url(self):
        with self.assertRaises(ValueError):
            normalize_comfy_url("file:///tmp/comfy")

    def test_resolves_preferences_into_one_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            portable_root = os.path.join(tmp, "portable")
            comfy_dir = os.path.join(portable_root, "ComfyUI")
            models_dir = os.path.join(comfy_dir, "models")
            embedded_root = os.path.join(portable_root, "python_embeded")
            os.makedirs(models_dir)
            os.makedirs(embedded_root)
            python_exe = os.path.join(embedded_root, "python.exe")
            open(python_exe, "wb").close()
            prefs = {
                "comfyui_launch_path": models_dir,
                "comfyui_url_base": "render-node:9000",
            }

            with mock.patch(
                "charon.comfy_environment.preferences.load_preferences",
                return_value=prefs,
            ):
                result = resolve_comfy_runtime()

            self.assertIsInstance(result, ComfyEnvironment)
            self.assertEqual(result.comfy_dir, comfy_dir)
            self.assertEqual(result.models_dir, models_dir)
            self.assertEqual(result.python_exe, python_exe)
            self.assertEqual(result.base_url, "http://render-node:9000")
            self.assertEqual(result.server_address, "render-node:9000")

    def test_explicit_values_override_environment_and_preferences(self):
        with mock.patch.dict(os.environ, {"CHARON_COMFY_URL": "env-host:8188"}):
            with mock.patch(
                "charon.comfy_environment.preferences.load_preferences",
                return_value={"comfyui_url_base": "preference-host:8188"},
            ):
                result = resolve_comfy_runtime(
                    comfy_path="configured-path",
                    base_url="explicit-host:9000",
                )

        self.assertEqual(result.base_url, "http://explicit-host:9000")
        self.assertEqual(result.configured_path, "configured-path")


if __name__ == "__main__":
    unittest.main()
