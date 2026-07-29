import os
import unittest

from charon.workflow_overrides import (
    _match_found_path,
    _normalize_resolved_value,
    _replacement_for_missing_model,
)


class NormalizeResolvedValueTests(unittest.TestCase):
    """Guards against emitting category-prefixed values ComfyUI rejects.

    Regression tests for the bug where a checkpoint sitting in models/vae was
    rewritten into the workflow as 'vae\\name.safetensors', which fails
    ComfyUI's per-folder prompt validation.
    """

    MODELS_ROOT = os.path.join("D:" + os.sep, "comfy", "models")

    def test_strips_expected_category_prefix(self):
        value = _normalize_resolved_value(
            os.path.join(self.MODELS_ROOT, "checkpoints", "model.safetensors"),
            self.MODELS_ROOT,
            "checkpoints",
        )
        self.assertEqual(value, "model.safetensors")

    def test_strips_alias_category_prefix(self):
        value = _normalize_resolved_value(
            os.path.join(self.MODELS_ROOT, "clip", "encoder.safetensors"),
            self.MODELS_ROOT,
            "text_encoders",
        )
        self.assertEqual(value, "encoder.safetensors")

    def test_rejects_foreign_category_prefix(self):
        value = _normalize_resolved_value(
            os.path.join(self.MODELS_ROOT, "vae", "model.safetensors"),
            self.MODELS_ROOT,
            "checkpoints",
        )
        self.assertEqual(value, "")

    def test_keeps_subfolder_below_expected_category(self):
        value = _normalize_resolved_value(
            os.path.join(self.MODELS_ROOT, "checkpoints", "ltx", "model.safetensors"),
            self.MODELS_ROOT,
            "checkpoints",
        )
        self.assertEqual(value, "ltx\\model.safetensors")


class MatchFoundPathTests(unittest.TestCase):
    MODELS_ROOT = os.path.join("D:" + os.sep, "comfy", "models")

    def test_ignores_wrong_category_match_when_category_known(self):
        found = [os.path.join(self.MODELS_ROOT, "vae", "model.safetensors")]
        self.assertIsNone(
            _match_found_path("model.safetensors", "checkpoints", found, self.MODELS_ROOT)
        )

    def test_accepts_expected_category_match(self):
        found = [
            os.path.join(self.MODELS_ROOT, "vae", "model.safetensors"),
            os.path.join(self.MODELS_ROOT, "checkpoints", "model.safetensors"),
        ]
        match = _match_found_path(
            "model.safetensors", "checkpoints", found, self.MODELS_ROOT
        )
        self.assertEqual(
            os.path.normcase(match),
            os.path.normcase(found[1]),
        )

    def test_accepts_alias_category_match(self):
        found = [os.path.join(self.MODELS_ROOT, "clip", "encoder.safetensors")]
        match = _match_found_path(
            "encoder.safetensors", "text_encoders", found, self.MODELS_ROOT
        )
        self.assertEqual(os.path.normcase(match), os.path.normcase(found[0]))

    def test_falls_back_to_basename_match_without_category(self):
        found = [os.path.join(self.MODELS_ROOT, "vae", "model.safetensors")]
        match = _match_found_path("model.safetensors", "", found, self.MODELS_ROOT)
        self.assertEqual(os.path.normcase(match), os.path.normcase(found[0]))


class ReplacementForMissingModelTests(unittest.TestCase):
    MODELS_ROOT = os.path.join("D:" + os.sep, "comfy", "models")

    def test_no_replacement_for_misplaced_model(self):
        entry = {
            "name": "ltx-2.3-22b-dev-fp8.safetensors",
            "category": "checkpoints",
            "resolve_status": "resolved",
        }
        found = [
            os.path.join(self.MODELS_ROOT, "vae", "ltx-2.3-22b-dev-fp8.safetensors")
        ]
        self.assertIsNone(
            _replacement_for_missing_model(entry, self.MODELS_ROOT, found)
        )


if __name__ == "__main__":
    unittest.main()
