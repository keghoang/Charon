import json
import os
import tempfile
import unittest

from charon.processor_output import allocate_result_manifest_path, write_result_manifest


class ProcessorOutputManifestTests(unittest.TestCase):
    def test_allocates_manifest_under_results_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = allocate_result_manifest_path(
                tmp,
                timestamp=123,
                manifest_id="abcdefgh-extra",
            )

            self.assertEqual(
                path,
                os.path.join(tmp, "results", "charon_result_123_abcdefgh.json"),
            )
            self.assertTrue(os.path.isdir(os.path.dirname(path)))

    def test_atomically_writes_manifest_and_removes_temporary_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "nested", "result.json")

            write_result_manifest(path, {"success": True, "outputs": ["result.png"]})

            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            self.assertTrue(payload["success"])
            self.assertFalse(os.path.exists(f"{path}.tmp"))


if __name__ == "__main__":
    unittest.main()
