import os
import tempfile
import unittest
from unittest import mock

from charon import preferences
from charon.first_time_setup import (
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


if __name__ == "__main__":
    unittest.main()
