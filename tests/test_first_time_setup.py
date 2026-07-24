import os
import tempfile
import unittest
from unittest import mock

from charon import preferences
from charon.first_time_setup import (
    ensure_requirements_with_log,
    is_first_time_setup_complete,
    is_force_first_time_setup_enabled,
    mark_first_time_setup_complete,
    set_force_first_time_setup,
)


class FirstTimeSetupStateTests(unittest.TestCase):
    def test_mark_complete_clears_force_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"GALT_PLUGIN_DIR": tmp}):
                set_force_first_time_setup(True)
                self.assertTrue(is_force_first_time_setup_enabled())
                self.assertFalse(is_first_time_setup_complete())

                mark_first_time_setup_complete()

                self.assertFalse(is_force_first_time_setup_enabled())
                self.assertTrue(is_first_time_setup_complete())
                self.assertTrue(preferences.get_preference("dependencies_verified", False))

    def test_verified_fast_path_rechecks_playwright_browser(self):
        manager = mock.Mock()
        manager._playwright_available.return_value = False
        manager.comfy_dir = None
        manager.check_dependencies.return_value = {"playwright": "missing"}

        with mock.patch("charon.first_time_setup.preferences.load_preferences", return_value={}), \
             mock.patch("charon.first_time_setup.preferences.get_preference") as get_pref, \
             mock.patch("charon.first_time_setup.SetupManager", return_value=manager), \
             mock.patch("charon.first_time_setup.ensure_manager_security_level"), \
             mock.patch("charon.first_time_setup.run_first_time_setup_if_needed", return_value=False) as setup:
            get_pref.side_effect = lambda key, default=False: key in {
                "dependencies_verified",
                "first_time_setup_complete",
            }

            self.assertFalse(ensure_requirements_with_log())

        manager._playwright_available.assert_called_once_with()
        setup.assert_called_once_with(parent=None, force=True)


if __name__ == "__main__":
    unittest.main()
