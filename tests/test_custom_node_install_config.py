"""Tests for the ComfyUI-Manager git-URL install opt-in.

Newer ComfyUI-Manager versions refuse /customnode/install/git_url unless
config.ini has `allow_git_url_install = true` in [default]; Charon enables
the flag when it detects that failure.
"""

import configparser
import os
import tempfile
import unittest

from charon.validation_resolver import enable_manager_git_url_install


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


if __name__ == "__main__":
    unittest.main()
