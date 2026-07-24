import json
import os
import tempfile
import unittest

from charon.conversion_cache import (
    clear_conversion_cache,
    compute_comfy_cache_identity,
    load_cached_conversion,
    write_conversion_cache,
)


class ConversionCacheTests(unittest.TestCase):
    def test_clear_conversion_cache_preserves_workflow_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = os.path.join(temp_dir, ".charon_cache")
            os.makedirs(cache_dir)
            state_path = os.path.join(cache_dir, "workflow_state.json")
            prompt_path = os.path.join(cache_dir, "prompt.json")
            with open(state_path, "w", encoding="utf-8") as handle:
                json.dump({"validated": True}, handle)
            with open(prompt_path, "w", encoding="utf-8") as handle:
                json.dump({}, handle)

            clear_conversion_cache(temp_dir)

            self.assertTrue(os.path.exists(state_path))
            self.assertFalse(os.path.exists(prompt_path))

    def test_cache_identity_changes_with_frontend_version(self):
        first = compute_comfy_cache_identity(
            {"system": {"comfyui_version": "0.26.0", "required_frontend_version": "1.45.19"}},
            r"D:\Comfy\ComfyUI",
        )
        second = compute_comfy_cache_identity(
            {"system": {"comfyui_version": "0.26.0", "required_frontend_version": "1.46.0"}},
            r"D:\Comfy\ComfyUI",
        )

        self.assertNotEqual(first, second)

    def test_cache_rejects_different_comfy_identity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            prompt_path = os.path.join(temp_dir, "prompt.json")
            with open(prompt_path, "w", encoding="utf-8") as handle:
                json.dump({"1": {"class_type": "Test"}}, handle)
            write_conversion_cache(
                temp_dir,
                "workflow.json",
                "workflow-hash",
                prompt_path,
                "identity-a",
            )

            self.assertIsNotNone(
                load_cached_conversion(temp_dir, "workflow-hash", "identity-a")
            )
            self.assertIsNone(
                load_cached_conversion(temp_dir, "workflow-hash", "identity-b")
            )

    def test_legacy_unversioned_cache_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_dir = os.path.join(temp_dir, ".charon_cache")
            os.makedirs(cache_dir)
            prompt_path = os.path.join(cache_dir, "prompt.json")
            with open(prompt_path, "w", encoding="utf-8") as handle:
                json.dump({"1": {"class_type": "Test"}}, handle)
            with open(os.path.join(cache_dir, "conversion_log.md"), "w", encoding="utf-8") as handle:
                handle.write(
                    "# Conversion Cache\n"
                    "- workflow_hash: workflow-hash\n"
                    "- prompt_file: prompt.json\n"
                )

            self.assertIsNone(load_cached_conversion(temp_dir, "workflow-hash"))


if __name__ == "__main__":
    unittest.main()
