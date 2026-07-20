import os
import tempfile
import unittest
from unittest import mock

from charon.parameter_cache import parameter_cache_path


class ParameterCacheTests(unittest.TestCase):
    def test_shared_workflow_cache_is_redirected_to_local_mirror(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = os.path.join(tmp, "workflows")
            workflow_dir = os.path.join(repo_root, "artist", "example")
            workflow_path = os.path.join(workflow_dir, "workflow.json")
            prefs_root = os.path.join(tmp, "prefs")
            os.makedirs(workflow_dir)

            with mock.patch("charon.workflow_local_store.config.WORKFLOW_REPOSITORY_ROOT", repo_root):
                with mock.patch.dict(os.environ, {"GALT_PLUGIN_DIR": prefs_root}):
                    cache_path = parameter_cache_path(workflow_path, ensure_parent=True)

            self.assertTrue(cache_path.startswith(prefs_root))
            self.assertNotEqual(
                os.path.normpath(cache_path),
                os.path.normpath(os.path.join(workflow_dir, ".charon_cache", "input_mapping_cache.json")),
            )


if __name__ == "__main__":
    unittest.main()
