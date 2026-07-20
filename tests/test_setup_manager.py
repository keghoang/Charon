import os
import tempfile
import unittest
from pathlib import Path

from charon.setup_manager import SetupManager


class SetupManagerTests(unittest.TestCase):
    def _portable_layout(self, root: str, *, with_main: bool = True) -> str:
        portable = Path(root) / "portable"
        comfy_dir = portable / "ComfyUI"
        python_exe = portable / "python_embeded" / "python.exe"
        launcher = portable / "run_nvidia_gpu.bat"
        comfy_dir.mkdir(parents=True)
        python_exe.parent.mkdir(parents=True)
        python_exe.write_text("", encoding="utf-8")
        launcher.write_text("", encoding="utf-8")
        if with_main:
            (comfy_dir / "main.py").write_text("", encoding="utf-8")
        return str(launcher)

    def test_environment_requires_comfy_main(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = SetupManager(self._portable_layout(tmp, with_main=False))

            self.assertIn("main.py", manager._environment_error())
            self.assertEqual(manager.check_dependencies(), {"environment": "error"})

    def test_custom_node_destination_cannot_escape_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = SetupManager(self._portable_layout(tmp))
            inside = os.path.join(manager.custom_nodes_dir, "ComfyUI-Charon")
            outside = os.path.join(tmp, "outside")

            self.assertEqual(manager._safe_custom_node_destination(inside), os.path.abspath(inside))
            with self.assertRaises(ValueError):
                manager._safe_custom_node_destination(outside)

    def test_partial_custom_node_clone_is_not_reported_as_installed(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = SetupManager(self._portable_layout(tmp))
            partial = Path(manager.custom_nodes_dir) / "ComfyUI-Manager"
            (partial / ".git").mkdir(parents=True)

            self.assertFalse(manager._has_folder(manager.custom_nodes_dir, "ComfyUI-Manager"))

            (partial / "__init__.py").write_text("", encoding="utf-8")
            self.assertTrue(manager._has_folder(manager.custom_nodes_dir, "ComfyUI-Manager"))

    def test_clone_retry_removes_only_contained_incomplete_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = SetupManager(self._portable_layout(tmp))
            partial = Path(manager.custom_nodes_dir) / "ComfyUI-Manager"
            (partial / ".git").mkdir(parents=True)

            destination = manager._prepare_clone_destination(str(partial))

            self.assertEqual(destination, str(partial.resolve()))
            self.assertFalse(partial.exists())


if __name__ == "__main__":
    unittest.main()
