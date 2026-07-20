import os
import tempfile
import unittest
from unittest import mock

from charon.paths import allocate_custom_output_path, get_charon_temp_dir


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


if __name__ == "__main__":
    unittest.main()
