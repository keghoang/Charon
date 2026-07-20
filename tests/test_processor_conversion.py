import json
import os
import tempfile
import unittest

from charon.processor_conversion import load_cached_prompt_payload, write_converted_prompt_payload


class ProcessorConversionTests(unittest.TestCase):
    def test_load_cached_prompt_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            prompt_path = os.path.join(tmp, "prompt.json")
            with open(prompt_path, "w", encoding="utf-8") as handle:
                json.dump({"1": {"class_type": "Test", "inputs": {}}}, handle)

            payload, normalized_path = load_cached_prompt_payload({"prompt_path": prompt_path})

            self.assertIn("1", payload)
            self.assertEqual(normalized_path, prompt_path.replace("\\", "/"))

    def test_write_converted_prompt_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_converted_prompt_payload(
                {"1": {"class_type": "Test", "inputs": {}}},
                workflow_cache_folder="",
                workflow_path="",
                workflow_hash=None,
                temp_root=tmp,
                current_run_id="run123",
            )

            self.assertTrue(os.path.exists(path))
            self.assertTrue(path.endswith("converted_run123.json"))


if __name__ == "__main__":
    unittest.main()
