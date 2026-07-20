import os
import tempfile
import unittest

from charon import config


class RepositoryConfigTests(unittest.TestCase):
    def test_repository_override_updates_shared_models_root(self):
        original_root = config.WORKFLOW_REPOSITORY_ROOT
        try:
            with tempfile.TemporaryDirectory() as root:
                workflows = os.path.join(root, "workflows")
                config.set_workflow_repository_root(workflows)

                self.assertEqual(config.WORKFLOW_REPOSITORY_ROOT, os.path.abspath(workflows))
                self.assertEqual(config.GLOBAL_REPO_PATH, os.path.abspath(workflows))
                self.assertEqual(config.get_shared_models_root(), os.path.join(root, "shared_models"))
        finally:
            config.set_workflow_repository_root(original_root)

