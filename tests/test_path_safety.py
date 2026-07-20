import os
import tempfile
import unittest

from charon.path_safety import (
    ensure_path_inside,
    is_path_inside,
    relative_path_from_root,
    resolve_relative_path_inside,
)


class PathSafetyTests(unittest.TestCase):
    def test_rejects_sibling_prefix_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "workflows")
            sibling = os.path.join(tmp, "workflows_evil")
            os.makedirs(root)
            os.makedirs(sibling)

            self.assertFalse(is_path_inside(sibling, root))
            with self.assertRaises(ValueError):
                ensure_path_inside(sibling, root)

    def test_allows_child_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "workflows")
            child = os.path.join(root, "demo", "workflow.json")
            os.makedirs(os.path.dirname(child))

            self.assertTrue(is_path_inside(child, root))
            self.assertEqual(relative_path_from_root(child, root), os.path.join("demo", "workflow.json"))

    def test_resolve_relative_rejects_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "workflow")
            os.makedirs(root)

            with self.assertRaises(ValueError):
                resolve_relative_path_inside(root, "..\\outside.json", label="workflow_file")

    def test_resolve_relative_rejects_absolute(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "workflow")
            os.makedirs(root)
            absolute = os.path.join(root, "workflow.json")

            with self.assertRaises(ValueError):
                resolve_relative_path_inside(root, absolute, label="workflow_file")


if __name__ == "__main__":
    unittest.main()
