import os
import unittest

from charon import paths
from charon.nuke_3d_scripts import (
    coverage_camera_generate_script,
    final_prep_update_script,
)


class Nuke3DScriptsTests(unittest.TestCase):
    def test_coverage_camera_script_preserves_python_indentation(self):
        script = coverage_camera_generate_script()

        self.assertTrue(script.startswith("import math\nimport nuke\n"))
        self.assertIn("def _find_upstream", script)
        self.assertIn("    current = start_node\n", script)
        compile(script, "<coverage-camera-script>", "exec")

    def test_final_prep_script_resolves_template_directory(self):
        script = final_prep_update_script()
        template_dir = os.path.join(paths.RESOURCE_DIR, "nuke_template")

        self.assertNotIn("__TEMPLATE_DIR__", script)
        self.assertIn(f'TEMPLATE_DIR = r"{template_dir}"', script)
        self.assertIn("def _angle_from_name", script)
        compile(script, "<final-prep-script>", "exec")


if __name__ == "__main__":
    unittest.main()
