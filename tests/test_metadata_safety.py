import json
import os
import tempfile
import unittest

from charon.metadata_manager import clear_metadata_cache, load_workflow_data


class MetadataSafetyTests(unittest.TestCase):
    def tearDown(self):
        clear_metadata_cache()

    def test_workflow_file_cannot_escape_metadata_folder(self):
        with tempfile.TemporaryDirectory() as root:
            workflow_folder = os.path.join(root, "workflow")
            os.makedirs(workflow_folder)
            with open(os.path.join(root, "outside.json"), "w", encoding="utf-8") as handle:
                json.dump({"nodes": []}, handle)
            with open(os.path.join(workflow_folder, ".charon.json"), "w", encoding="utf-8") as handle:
                json.dump({"workflow_file": "..\\outside.json"}, handle)

            with self.assertRaises(ValueError):
                load_workflow_data(workflow_folder)

    def test_workflow_file_cannot_be_absolute(self):
        with tempfile.TemporaryDirectory() as root:
            workflow_folder = os.path.join(root, "workflow")
            outside_path = os.path.join(root, "outside.json")
            os.makedirs(workflow_folder)
            with open(outside_path, "w", encoding="utf-8") as handle:
                json.dump({"nodes": []}, handle)
            with open(os.path.join(workflow_folder, ".charon.json"), "w", encoding="utf-8") as handle:
                json.dump({"workflow_file": outside_path}, handle)

            with self.assertRaises(ValueError):
                load_workflow_data(workflow_folder)

