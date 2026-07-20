import os
import tempfile
import unittest
from unittest import mock

from charon import paths
from charon.paths import (
    allocate_custom_output_path,
    get_charon_temp_dir,
    resolve_comfy_environment,
)


class OutputAllocationTests(unittest.TestCase):
    def test_custom_output_allocation_reserves_unique_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = allocate_custom_output_path(tmp, extension=".png")
            second = allocate_custom_output_path(tmp, extension=".png")

            self.assertNotEqual(first, second)
            self.assertTrue(os.path.exists(first))
            self.assertTrue(os.path.exists(second))
            self.assertTrue(first.endswith("CharonOutput_v001.png"))
            self.assertTrue(second.endswith("CharonOutput_v002.png"))

    def test_runtime_root_honors_environment_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = os.path.join(tmp, "runtime")
            with mock.patch.dict(os.environ, {"CHARON_RUNTIME_ROOT": runtime_root}):
                resolved = get_charon_temp_dir()

            self.assertEqual(os.path.normpath(resolved), os.path.normpath(runtime_root))
            for name in ("temp", "exports", "results", "debug"):
                self.assertTrue(os.path.isdir(os.path.join(runtime_root, name)))


class ComfyEnvironmentResolutionTests(unittest.TestCase):
    def _portable_layout(self, root: str):
        portable_root = os.path.join(root, "ComfyUI_windows_portable")
        comfy_dir = os.path.join(portable_root, "ComfyUI")
        models_dir = os.path.join(comfy_dir, "models")
        embedded_root = os.path.join(portable_root, "python_embeded")
        os.makedirs(models_dir)
        os.makedirs(embedded_root)
        open(os.path.join(embedded_root, "python.exe"), "wb").close()
        launcher = os.path.join(portable_root, "run_nvidia_gpu.bat")
        open(launcher, "wb").close()
        return portable_root, comfy_dir, models_dir, launcher

    def test_resolves_portable_launcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            portable_root, comfy_dir, models_dir, launcher = self._portable_layout(tmp)

            result = resolve_comfy_environment(launcher)

            self.assertEqual(result["base_dir"], portable_root)
            self.assertEqual(result["comfy_dir"], comfy_dir)
            self.assertEqual(result["models_dir"], models_dir)

    def test_resolves_comfy_models_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            portable_root, comfy_dir, models_dir, _launcher = self._portable_layout(tmp)

            result = resolve_comfy_environment(models_dir)

            self.assertEqual(result["base_dir"], portable_root)
            self.assertEqual(result["comfy_dir"], comfy_dir)
            self.assertEqual(result["models_dir"], models_dir)
            self.assertNotEqual(result["models_dir"], os.path.join(models_dir, "models"))

    def test_resolves_embedded_python_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            portable_root, comfy_dir, models_dir, _launcher = self._portable_layout(tmp)
            python_exe = os.path.join(portable_root, "python_embeded", "python.exe")

            result = resolve_comfy_environment(python_exe)

            self.assertEqual(result["base_dir"], portable_root)
            self.assertEqual(result["comfy_dir"], comfy_dir)
            self.assertEqual(result["models_dir"], models_dir)

    def test_extends_sys_path_from_models_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            portable_root, comfy_dir, models_dir, _launcher = self._portable_layout(tmp)
            embedded_root = os.path.join(portable_root, "python_embeded")
            original_sys_path = list(paths.sys.path)
            try:
                paths.extend_sys_path_with_comfy(models_dir)
                self.assertIn(comfy_dir, paths.sys.path)
                self.assertIn(portable_root, paths.sys.path)
                self.assertIn(embedded_root, paths.sys.path)
                self.assertNotIn(models_dir, paths.sys.path)
            finally:
                paths.sys.path[:] = original_sys_path


if __name__ == "__main__":
    unittest.main()
