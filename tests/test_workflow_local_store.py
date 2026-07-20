import json
import os
import tempfile
import unittest
from unittest import mock

from charon import preferences
from charon.workflow_local_store import (
    load_validation_resolve_status,
    load_workflow_state,
    mark_validated_workflow,
    synchronize_remote_payload,
    write_validation_resolve_status,
)


class WorkflowLocalStoreTests(unittest.TestCase):
    def test_changed_comfy_path_invalidates_validated_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = os.path.join(tmp, "workflows")
            remote_folder = os.path.join(repo_root, "artist", "workflow")
            prefs_root = os.path.join(tmp, "prefs")
            os.makedirs(remote_folder)
            with open(os.path.join(remote_folder, ".charon.json"), "w", encoding="utf-8") as handle:
                json.dump({"workflow_file": "workflow.json", "dependencies": []}, handle)
            payload = {"1": {"class_type": "LoadImage", "inputs": {}}}

            with mock.patch("charon.workflow_local_store.config.WORKFLOW_REPOSITORY_ROOT", repo_root):
                with mock.patch.dict(os.environ, {"GALT_PLUGIN_DIR": prefs_root}):
                    preferences.set_preference("comfyui_launch_path", os.path.join(tmp, "comfy_a"))
                    synchronize_remote_payload(remote_folder, payload)
                    mark_validated_workflow(remote_folder, payload)
                    self.assertTrue(load_workflow_state(remote_folder).get("validated"))

                    preferences.set_preference("comfyui_launch_path", os.path.join(tmp, "comfy_b"))
                    synchronize_remote_payload(remote_folder, payload)

                    self.assertFalse(load_workflow_state(remote_folder).get("validated"))

    def test_changed_comfy_path_invalidates_resolve_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = os.path.join(tmp, "workflows")
            remote_folder = os.path.join(repo_root, "artist", "workflow")
            prefs_root = os.path.join(tmp, "prefs")
            os.makedirs(remote_folder)
            with open(os.path.join(remote_folder, ".charon.json"), "w", encoding="utf-8") as handle:
                json.dump({"workflow_file": "workflow.json", "dependencies": []}, handle)
            payload = {"state": "validated", "issues": []}

            with mock.patch("charon.workflow_local_store.config.WORKFLOW_REPOSITORY_ROOT", repo_root):
                with mock.patch.dict(os.environ, {"GALT_PLUGIN_DIR": prefs_root}):
                    preferences.set_preference("comfyui_launch_path", os.path.join(tmp, "comfy_a"))
                    write_validation_resolve_status(remote_folder, payload)
                    stored_payload = load_validation_resolve_status(remote_folder)
                    self.assertEqual(stored_payload.get("state"), "validated")
                    self.assertEqual(stored_payload.get("issues"), [])

                    preferences.set_preference("comfyui_launch_path", os.path.join(tmp, "comfy_b"))
                    self.assertIsNone(load_validation_resolve_status(remote_folder))


if __name__ == "__main__":
    unittest.main()
