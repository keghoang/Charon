import json
import os
import tempfile
import unittest

from charon.json_io import atomic_write_json
from charon.workflow_publication import (
    create_staging_directory,
    discard_staging_directory,
    publish_staged_directory,
)


class AtomicPublicationTests(unittest.TestCase):
    def test_atomic_json_write_replaces_destination(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "workflow.json")
            atomic_write_json(path, {"value": 1})
            atomic_write_json(path, {"value": 2})

            with open(path, "r", encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), {"value": 2})
            self.assertEqual(os.listdir(root), ["workflow.json"])

    def test_staged_directory_is_hidden_until_publish(self):
        with tempfile.TemporaryDirectory() as root:
            target = os.path.join(root, "workflow")
            staging = create_staging_directory(target)
            self.addCleanup(discard_staging_directory, staging)

            self.assertFalse(os.path.exists(target))
            self.assertTrue(os.path.basename(staging).startswith(".workflow."))
            with open(os.path.join(staging, "workflow.json"), "w", encoding="utf-8") as handle:
                json.dump({"nodes": []}, handle)

            publish_staged_directory(staging, target)
            self.assertTrue(os.path.isfile(os.path.join(target, "workflow.json")))

    def test_publish_does_not_overwrite_existing_workflow(self):
        with tempfile.TemporaryDirectory() as root:
            target = os.path.join(root, "workflow")
            os.makedirs(target)
            staging = create_staging_directory(target)
            self.addCleanup(discard_staging_directory, staging)

            with self.assertRaises(FileExistsError):
                publish_staged_directory(staging, target)

