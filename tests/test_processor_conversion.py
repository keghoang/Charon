import json
import os
import tempfile
import unittest

from charon.processor_conversion import (
    load_cached_prompt_payload,
    resolve_cached_prompt,
    resolve_existing_folder,
    write_converted_prompt_payload,
)


class ProcessorConversionTests(unittest.TestCase):
    def test_resolves_existing_folder_from_file_or_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = os.path.join(tmp, "workflow.json")
            with open(file_path, "w", encoding="utf-8") as handle:
                handle.write("{}")

            self.assertEqual(resolve_existing_folder(tmp), tmp)
            self.assertEqual(resolve_existing_folder(file_path), tmp)
            self.assertEqual(resolve_existing_folder(os.path.join(tmp, "missing.json")), tmp)

    @staticmethod
    def _is_api_prompt(payload):
        return isinstance(payload, dict) and bool(payload) and all(
            isinstance(value, dict) and "class_type" in value for value in payload.values()
        )

    def test_resolve_cached_prompt_invalidates_stale_hash(self):
        stores = []
        resolution = resolve_cached_prompt(
            {"1": {"class_type": "Current"}},
            workflow_hash="current-hash",
            cached_path="missing.json",
            cached_hash="stale-hash",
            is_api_prompt=self._is_api_prompt,
            store_cache=lambda path, value: stores.append((path, value)),
            log_debug=lambda *_args: None,
        )

        self.assertEqual(stores, [("", "")])
        self.assertEqual(resolution.path, "")
        self.assertEqual(resolution.payload, {"1": {"class_type": "Current"}})

    def test_resolve_cached_prompt_loads_matching_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            prompt_path = os.path.join(tmp, "prompt.json")
            payload = {"1": {"class_type": "Cached"}}
            with open(prompt_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)

            resolution = resolve_cached_prompt(
                {"1": {"class_type": "Cached"}},
                workflow_hash="workflow-hash",
                cached_path=prompt_path,
                cached_hash="workflow-hash",
                is_api_prompt=self._is_api_prompt,
                store_cache=lambda *_args: None,
                log_debug=lambda *_args: None,
            )

        self.assertEqual(resolution.payload, payload)

    def test_resolve_cached_prompt_does_not_reuse_node_cache_for_ui_workflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            prompt_path = os.path.join(tmp, "prompt.json")
            with open(prompt_path, "w", encoding="utf-8") as handle:
                json.dump({"1": {"class_type": "Cached"}}, handle)

            resolution = resolve_cached_prompt(
                {"nodes": [{"id": 1, "type": "Current"}]},
                workflow_hash="workflow-hash",
                cached_path=prompt_path,
                cached_hash="workflow-hash",
                is_api_prompt=self._is_api_prompt,
                store_cache=lambda *_args: None,
                log_debug=lambda *_args: None,
            )

        self.assertIsNone(resolution.payload)

    def test_resolve_cached_prompt_clears_missing_file(self):
        stores = []
        resolution = resolve_cached_prompt(
            {"ui": {}},
            workflow_hash="workflow-hash",
            cached_path="Z:/missing/prompt.json",
            cached_hash="workflow-hash",
            is_api_prompt=self._is_api_prompt,
            store_cache=lambda path, value: stores.append((path, value)),
            log_debug=lambda *_args: None,
        )

        self.assertIsNone(resolution.payload)
        self.assertEqual((resolution.path, resolution.workflow_hash), ("", ""))
        self.assertEqual(stores, [("", "")])

    def test_resolve_cached_prompt_rejects_source_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            prompt_path = os.path.join(tmp, "prompt.json")
            with open(prompt_path, "w", encoding="utf-8") as handle:
                json.dump({"9": {"class_type": "SaveImage"}}, handle)
            stores = []

            resolution = resolve_cached_prompt(
                {"nodes": [{"id": 75, "type": "SaveVideo"}]},
                workflow_hash="workflow-hash",
                cached_path=prompt_path,
                cached_hash="workflow-hash",
                is_api_prompt=self._is_api_prompt,
                validate_prompt=lambda _source, _prompt: (_ for _ in ()).throw(
                    RuntimeError("source mismatch")
                ),
                store_cache=lambda path, value: stores.append((path, value)),
                log_debug=lambda *_args: None,
            )

        self.assertIsNone(resolution.payload)
        self.assertEqual((resolution.path, resolution.workflow_hash), ("", ""))
        self.assertEqual(stores, [("", "")])

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
