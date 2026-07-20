import time
import unittest
from unittest import mock

from charon.comfy_validation import (
    ValidationIssue,
    ValidationResult,
    validate_comfy_environment,
)


class ComfyValidationTests(unittest.TestCase):
    def test_validation_result_round_trip_preserves_cache_timestamps(self):
        result = ValidationResult(
            comfy_path="ComfyUI",
            issues=[],
            started_at=time.time() - 2,
            finished_at=time.time() - 1,
            cache_key="cache-key",
        )

        restored = ValidationResult.from_dict(result.to_dict())

        self.assertEqual(restored.started_at, result.started_at)
        self.assertEqual(restored.finished_at, result.finished_at)
        self.assertFalse(restored.is_stale(ttl=60))

    @mock.patch("charon.comfy_validation.store_validation_result")
    @mock.patch("charon.comfy_validation._validate_models_browser")
    @mock.patch("charon.comfy_validation._validate_custom_nodes_browser")
    @mock.patch("charon.comfy_validation.resolve_comfy_environment")
    def test_custom_endpoint_reaches_browser_validation(
        self,
        resolve_environment,
        validate_custom_nodes,
        validate_models,
        _store_result,
    ):
        issue = ValidationIssue(
            key="test",
            label="Test",
            ok=True,
            summary="ok",
        )
        resolve_environment.return_value = {}
        validate_custom_nodes.return_value = (issue, None)
        validate_models.return_value = issue

        validate_comfy_environment(
            "configured-path",
            ping_url="http://render-node:9000",
            include_environment=False,
            use_cache=False,
            force=True,
        )

        self.assertEqual(
            validate_custom_nodes.call_args.kwargs["ping_url"],
            "http://render-node:9000",
        )


if __name__ == "__main__":
    unittest.main()
