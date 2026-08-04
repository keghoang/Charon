"""Tests for the ComfyUI-Manager git-URL install opt-in.

Newer ComfyUI-Manager versions refuse /customnode/install/git_url unless
config.ini has `allow_git_url_install = true` in [default]; Charon enables
the flag when it detects that failure.
"""

import configparser
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from charon.validation_resolver import (
    enable_manager_git_url_install,
    existing_custom_node_conflict,
)


def _read_config(path):
    parser = configparser.ConfigParser()
    parser.read(path, encoding="utf-8")
    return parser


class EnableManagerGitUrlInstallTests(unittest.TestCase):
    def test_updates_existing_config_preserving_other_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = os.path.join(tmp, "user", "default", "ComfyUI-Manager")
            os.makedirs(config_dir)
            config_path = os.path.join(config_dir, "config.ini")
            with open(config_path, "w", encoding="utf-8") as handle:
                handle.write("[default]\nsecurity_level = normal\nchannel_url = https://x\n")

            updated = enable_manager_git_url_install(tmp)

            self.assertEqual(config_path, updated)
            parser = _read_config(config_path)
            self.assertEqual("true", parser.get("default", "allow_git_url_install"))
            self.assertEqual("normal", parser.get("default", "security_level"))
            self.assertEqual("https://x", parser.get("default", "channel_url"))

    def test_seeds_config_when_manager_has_not_written_one_yet(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "user", "default"))

            updated = enable_manager_git_url_install(tmp)

            expected = os.path.join(
                tmp, "user", "default", "ComfyUI-Manager", "config.ini"
            )
            self.assertEqual(expected, updated)
            parser = _read_config(expected)
            self.assertEqual("true", parser.get("default", "allow_git_url_install"))

    def test_falls_back_to_legacy_custom_nodes_location(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = os.path.join(tmp, "custom_nodes", "ComfyUI-Manager")
            os.makedirs(config_dir)
            config_path = os.path.join(config_dir, "config.ini")
            with open(config_path, "w", encoding="utf-8") as handle:
                handle.write("[default]\nsecurity_level = normal\n")

            self.assertEqual(config_path, enable_manager_git_url_install(tmp))
            parser = _read_config(config_path)
            self.assertEqual("true", parser.get("default", "allow_git_url_install"))

    def test_noop_when_flag_already_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = os.path.join(tmp, "user", "default", "ComfyUI-Manager")
            os.makedirs(config_dir)
            config_path = os.path.join(config_dir, "config.ini")
            with open(config_path, "w", encoding="utf-8") as handle:
                handle.write("[default]\nallow_git_url_install = true\n")

            self.assertIsNone(enable_manager_git_url_install(tmp))

    def test_noop_without_a_recognizable_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(enable_manager_git_url_install(tmp))
        self.assertIsNone(enable_manager_git_url_install(None))


class ExistingCustomNodeConflictTests(unittest.TestCase):
    """A node folder already on disk makes Manager reinstalls fail with a
    bare 400; Charon must explain that state instead of retrying forever."""

    REPO = "https://github.com/DemonGatanjieu/Anomalous_Model_Browser"

    def test_installed_but_not_loading_is_explained(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = os.path.join(tmp, "custom_nodes", "Anomalous_Model_Browser")
            os.makedirs(plugin_dir)
            with open(os.path.join(plugin_dir, "__init__.py"), "w", encoding="utf-8") as handle:
                handle.write("boom")

            message = existing_custom_node_conflict(tmp, self.REPO)
            self.assertIsNotNone(message)
            self.assertIn("already installed", message)
            self.assertIn("import error", message)

    def test_disabled_install_is_explained(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "custom_nodes", ".disabled", "Anomalous_Model_Browser"))
            message = existing_custom_node_conflict(tmp, self.REPO)
            self.assertIsNotNone(message)
            self.assertIn("disabled", message)

    def test_legacy_disabled_suffix_is_explained(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "custom_nodes", "Anomalous_Model_Browser.disabled"))
            message = existing_custom_node_conflict(tmp, self.REPO)
            self.assertIsNotNone(message)
            self.assertIn("disabled", message)

    def test_empty_leftover_folder_is_removed_so_install_can_proceed(self):
        # The Manager refuses to clone over any existing folder, even an
        # empty husk; the pre-flight clears the husk instead of reporting a
        # conflict so the clean install goes through.
        with tempfile.TemporaryDirectory() as tmp:
            leftover = os.path.join(tmp, "custom_nodes", "Anomalous_Model_Browser")
            os.makedirs(leftover)
            self.assertIsNone(existing_custom_node_conflict(tmp, self.REPO))
            self.assertFalse(os.path.exists(leftover))

    def test_absent_folder_is_no_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "custom_nodes"))
            self.assertIsNone(existing_custom_node_conflict(tmp, self.REPO))
        self.assertIsNone(existing_custom_node_conflict(None, self.REPO))
        self.assertIsNone(existing_custom_node_conflict("C:/x", ""))

    def _make_broken_install(self, tmp, with_requirements=True):
        plugin_dir = os.path.join(tmp, "custom_nodes", "Anomalous_Model_Browser")
        os.makedirs(plugin_dir)
        with open(os.path.join(plugin_dir, "__init__.py"), "w", encoding="utf-8") as handle:
            handle.write("import missing_dependency")
        if with_requirements:
            with open(os.path.join(plugin_dir, "requirements.txt"), "w", encoding="utf-8") as handle:
                handle.write("missing_dependency\n")
        return plugin_dir

    def test_broken_install_with_requirements_is_auto_repaired(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = self._make_broken_install(tmp)
            calls = []

            def fake_run(command, **kwargs):
                calls.append(command)
                return SimpleNamespace(returncode=0, stdout="ok", stderr="")

            with mock.patch("charon.validation_resolver.subprocess.run", side_effect=fake_run):
                message = existing_custom_node_conflict(
                    tmp, self.REPO, python_exe=sys.executable
                )

            self.assertIsNotNone(message)
            self.assertIn("reinstalled its Python dependencies", message)
            self.assertIn("restart", message.lower())
            self.assertEqual(1, len(calls))
            self.assertIn("pip", calls[0])
            self.assertIn(os.path.join(plugin_dir, "requirements.txt"), calls[0])

    def test_failed_repair_reports_pip_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_broken_install(tmp)

            def fake_run(command, **kwargs):
                return SimpleNamespace(
                    returncode=1,
                    stdout="",
                    stderr="ERROR: No matching distribution found for missing_dependency",
                )

            with mock.patch("charon.validation_resolver.subprocess.run", side_effect=fake_run):
                message = existing_custom_node_conflict(
                    tmp, self.REPO, python_exe=sys.executable
                )

            self.assertIsNotNone(message)
            self.assertIn("Automatic dependency repair failed", message)
            self.assertIn("No matching distribution", message)

    def test_broken_install_without_requirements_keeps_manual_guidance(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._make_broken_install(tmp, with_requirements=False)
            message = existing_custom_node_conflict(
                tmp, self.REPO, python_exe=sys.executable
            )
            self.assertIsNotNone(message)
            self.assertIn("already installed", message)
            self.assertNotIn("Automatic dependency repair", message)

    def test_git_suffix_maps_to_same_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            plugin_dir = os.path.join(tmp, "custom_nodes", "Anomalous_Model_Browser")
            os.makedirs(plugin_dir)
            with open(os.path.join(plugin_dir, "nodes.py"), "w", encoding="utf-8") as handle:
                handle.write("x")
            message = existing_custom_node_conflict(tmp, self.REPO + ".git")
            self.assertIsNotNone(message)


if __name__ == "__main__":
    unittest.main()
