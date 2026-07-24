import time
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from charon.comfy_validation import (
    ValidationIssue,
    ValidationResult,
    _validate_custom_nodes_browser,
    _validate_server_identity,
    validate_comfy_environment,
)


class ComfyValidationTests(unittest.TestCase):
    def test_browser_validation_rejects_malformed_comfy_prompt_export(self):
        payload = {
            "missing": [],
            "registered_count": 100,
            "nodepack_count": 0,
            "prompt_export": {
                "ok": False,
                "error": "ComfyUI frontend exported malformed API nodes.",
                "mismatches": [
                    {
                        "id": "320:294",
                        "expected": "ComfyMathExpression",
                        "actual": "<missing>",
                    }
                ],
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            python_exe = os.path.join(temp_dir, "python.exe")
            with open(python_exe, "w", encoding="utf-8"):
                pass
            completed = SimpleNamespace(
                returncode=0,
                stdout=json.dumps(payload),
                stderr="",
            )
            with mock.patch(
                "charon.comfy_validation.ComfyUIClient.test_connection",
                return_value=True,
            ), mock.patch(
                "charon.comfy_validation.subprocess.run",
                return_value=completed,
            ):
                issue, returned_payload = _validate_custom_nodes_browser(
                    {"python_exe": python_exe, "comfy_dir": temp_dir},
                    {"workflow": {"nodes": [{"id": "320:294", "type": "ComfyMathExpression"}]}},
                    ping_url="http://127.0.0.1:8188",
                )

        self.assertFalse(issue.ok)
        self.assertEqual(issue.label, "ComfyUI workflow export")
        self.assertIn("320:294: <missing> != ComfyMathExpression", issue.details)
        self.assertEqual(returned_payload, payload)

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
    def test_validation_always_uses_fixed_comfy_endpoint(
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
            "http://127.0.0.1:8188",
        )

    @mock.patch("charon.comfy_validation.ComfyUIClient.get_system_stats")
    def test_runtime_identity_rejects_different_comfy_installation(self, get_stats):
        get_stats.return_value = {
            "system": {
                "argv": [r"D:\OtherComfy\ComfyUI\main.py"],
                "comfyui_version": "0.26.0",
                "required_frontend_version": "1.45.19",
            }
        }

        issue = _validate_server_identity(
            "http://127.0.0.1:8188",
            {"comfy_dir": r"D:\ConfiguredComfy\ComfyUI"},
        )

        self.assertFalse(issue.ok)
        self.assertIn("different ComfyUI installation", issue.summary)

    @mock.patch("charon.comfy_validation.ComfyUIClient.get_system_stats")
    def test_runtime_identity_accepts_configured_comfy_installation(self, get_stats):
        get_stats.return_value = {
            "system": {
                "argv": [r"D:\ConfiguredComfy\ComfyUI\main.py"],
                "comfyui_version": "0.26.0",
                "required_frontend_version": "1.45.19",
            }
        }

        issue = _validate_server_identity(
            "http://127.0.0.1:8188",
            {"comfy_dir": r"D:\ConfiguredComfy\ComfyUI"},
        )

        self.assertTrue(issue.ok)

    @mock.patch("charon.comfy_validation.ComfyUIClient.get_system_stats")
    def test_runtime_identity_accepts_portable_relative_main_path(self, get_stats):
        get_stats.return_value = {
            "system": {
                "argv": [r"ComfyUI\main.py"],
                "comfyui_version": "0.26.0",
            }
        }

        issue = _validate_server_identity(
            "http://127.0.0.1:8188",
            {"comfy_dir": r"D:\ConfiguredComfy\ComfyUI"},
        )

        self.assertTrue(issue.ok)


if __name__ == "__main__":
    unittest.main()
