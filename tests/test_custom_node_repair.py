import os
import tempfile
import unittest
from pathlib import Path

from charon.custom_node_repair import repair_tracked_module_shadows


class CustomNodeRepairTests(unittest.TestCase):
    @staticmethod
    def _portable_layout(root: str) -> tuple[Path, Path]:
        portable = Path(root) / "portable"
        comfy = portable / "ComfyUI"
        custom_nodes = comfy / "custom_nodes"
        custom_nodes.mkdir(parents=True)
        (comfy / "main.py").write_text("", encoding="utf-8")
        launcher = portable / "run_nvidia_gpu.bat"
        launcher.write_text("", encoding="utf-8")
        return launcher, custom_nodes

    @staticmethod
    def _write_plugin(
        custom_nodes: Path,
        tracking_lines: list[str],
    ) -> Path:
        plugin = custom_nodes / "ExampleNode"
        plugin.mkdir()
        (plugin / "__init__.py").write_text("", encoding="utf-8")
        (plugin / ".tracking").write_text(
            "\n".join(tracking_lines),
            encoding="utf-8",
        )
        return plugin

    def test_quarantines_untracked_package_that_shadows_tracked_module(self):
        with tempfile.TemporaryDirectory() as tmp:
            launcher, custom_nodes = self._portable_layout(tmp)
            plugin = self._write_plugin(
                custom_nodes,
                ["nodes/__init__.py", "nodes/model.py"],
            )
            nodes = plugin / "nodes"
            shadow = nodes / "model"
            shadow.mkdir(parents=True)
            (nodes / "__init__.py").write_text("", encoding="utf-8")
            (nodes / "model.py").write_text("VALUE = 'current'\n", encoding="utf-8")
            (shadow / "__init__.py").write_text("VALUE = 'stale'\n", encoding="utf-8")
            backup_root = Path(tmp) / "repairs"

            repairs = repair_tracked_module_shadows(
                str(launcher),
                backup_root=str(backup_root),
            )

            self.assertEqual(len(repairs), 1)
            self.assertEqual(repairs[0].plugin_name, "ExampleNode")
            self.assertFalse(shadow.exists())
            self.assertTrue((nodes / "model.py").is_file())
            self.assertTrue(Path(repairs[0].backup_path, "__init__.py").is_file())
            self.assertTrue(
                os.path.commonpath(
                    [repairs[0].backup_path, str(backup_root)]
                )
                == str(backup_root)
            )

    def test_keeps_package_when_manifest_tracks_package_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            launcher, custom_nodes = self._portable_layout(tmp)
            plugin = self._write_plugin(
                custom_nodes,
                [
                    "nodes/model.py",
                    "nodes/model/__init__.py",
                    "nodes/model/implementation.py",
                ],
            )
            nodes = plugin / "nodes"
            shadow = nodes / "model"
            shadow.mkdir(parents=True)
            (nodes / "model.py").write_text("", encoding="utf-8")
            (shadow / "__init__.py").write_text("", encoding="utf-8")
            (shadow / "implementation.py").write_text("", encoding="utf-8")

            repairs = repair_tracked_module_shadows(
                str(launcher),
                backup_root=str(Path(tmp) / "repairs"),
            )

            self.assertEqual(repairs, [])
            self.assertTrue(shadow.is_dir())

    def test_preserves_manifest_path_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            launcher, custom_nodes = self._portable_layout(tmp)
            plugin = self._write_plugin(
                custom_nodes,
                ["Nodes/Model.py"],
            )
            nodes = plugin / "Nodes"
            shadow = nodes / "Model"
            shadow.mkdir(parents=True)
            (nodes / "Model.py").write_text("", encoding="utf-8")
            (shadow / "__init__.py").write_text("", encoding="utf-8")

            repairs = repair_tracked_module_shadows(
                str(launcher),
                backup_root=str(Path(tmp) / "repairs"),
            )

            self.assertEqual(len(repairs), 1)
            self.assertFalse(shadow.exists())

    def test_leaves_unrelated_untracked_directories_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            launcher, custom_nodes = self._portable_layout(tmp)
            plugin = self._write_plugin(custom_nodes, ["nodes/model.py"])
            nodes = plugin / "nodes"
            nodes.mkdir()
            (nodes / "model.py").write_text("", encoding="utf-8")
            unrelated = plugin / "user_assets"
            unrelated.mkdir()
            (unrelated / "__init__.py").write_text("", encoding="utf-8")

            repairs = repair_tracked_module_shadows(
                str(launcher),
                backup_root=str(Path(tmp) / "repairs"),
            )

            self.assertEqual(repairs, [])
            self.assertTrue(unrelated.is_dir())

    def test_ignores_unsafe_tracking_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            launcher, custom_nodes = self._portable_layout(tmp)
            plugin = self._write_plugin(
                custom_nodes,
                ["../outside.py", "C:/outside.py", "/outside.py"],
            )
            outside_package = Path(tmp) / "outside"
            outside_package.mkdir()
            (outside_package / "__init__.py").write_text("", encoding="utf-8")
            (Path(tmp) / "outside.py").write_text("", encoding="utf-8")

            repairs = repair_tracked_module_shadows(
                str(launcher),
                backup_root=str(Path(tmp) / "repairs"),
            )

            self.assertEqual(repairs, [])
            self.assertTrue(outside_package.is_dir())
            self.assertTrue(plugin.is_dir())
