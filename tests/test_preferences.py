import json
import os
import tempfile
import unittest
from unittest import mock

from charon import preferences


class PreferencesTests(unittest.TestCase):
    def test_set_preference_preserves_existing_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"GALT_PLUGIN_DIR": tmp}):
                preferences.save_preferences({"first": 1})
                preferences.set_preference("second", 2)

                self.assertEqual(preferences.load_preferences(), {"first": 1, "second": 2})

    def test_save_preferences_replaces_file_without_temp_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"GALT_PLUGIN_DIR": tmp}):
                preferences.save_preferences({"status": "complete"})
                path = preferences.preferences_path()

                with open(path, "r", encoding="utf-8") as handle:
                    self.assertEqual(json.load(handle), {"status": "complete"})
                self.assertEqual(os.listdir(tmp), ["preferences.json"])


if __name__ == "__main__":
    unittest.main()
