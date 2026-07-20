import os
import tempfile
import unittest

from charon.processor_recovery import (
    download_with_timeout,
    find_output_by_basename,
    recover_matching_history_artifacts,
    recover_prefixed_history_artifacts,
    recover_artifacts_from_output_dir,
    resolve_batch_timeout,
    resolve_result_watch_timeout,
)


class _QueueClient:
    def __init__(self, payload):
        self.payload = payload

    def get_queue_status(self):
        return self.payload


class _DownloadClient:
    def __init__(self, result=True, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def download_file(self, filename, destination_path, **kwargs):
        self.calls.append((filename, destination_path, kwargs))
        if self.error:
            raise self.error
        return self.result


class _HistoryClient:
    def __init__(self, history):
        self.history = history

    def get_full_history(self):
        return self.history


class ProcessorRecoveryTests(unittest.TestCase):
    def test_recovers_newest_matching_prompt_history(self):
        prompt = {"1": {"class_type": "SaveImage", "inputs": {}}}
        history = {
            "current": {"prompt": [None, None, prompt], "outputs": {}},
            "older": {
                "prompt": [None, None, prompt],
                "outputs": {"1": {"images": [{"filename": "result.png"}]}},
                "status": {"messages": [["done", {"timestamp": 10}]]},
            },
        }

        result = recover_matching_history_artifacts(
            _HistoryClient(history),
            prompt,
            "current",
            ignored_output=lambda _path: False,
            camera_extensions={".nukecam"},
            model_extensions={".glb"},
        )

        self.assertEqual(result.prompt_id, "older")
        self.assertEqual(result.artifacts[0]["filename"], "result.png")

    def test_recovers_history_by_expected_prefix(self):
        history = {
            "prompt-1": {
                "prompt": {},
                "outputs": {
                    "1": {"images": [{"filename": "charon_run_0001.png"}]}
                },
            }
        }

        result = recover_prefixed_history_artifacts(
            _HistoryClient(history),
            ["charon_run"],
            ignored_output=lambda _path: False,
            camera_extensions=set(),
            model_extensions=set(),
        )

        self.assertEqual(result.prompt_id, "prompt-1")
        self.assertEqual(len(result.artifacts), 1)
    def test_download_uses_bounded_job_and_preserves_client_options(self):
        client = _DownloadClient()

        result = download_with_timeout(
            client,
            filename="result.png",
            destination_path="target.png",
            subfolder="nested",
            file_type="output",
            retries=4,
            retry_delay=0.5,
            min_bytes=1,
            hard_timeout=2,
        )

        self.assertTrue(result.success)
        self.assertFalse(result.timed_out)
        self.assertEqual(client.calls[0][2]["subfolder"], "nested")

    def test_download_reports_client_error(self):
        result = download_with_timeout(
            _DownloadClient(error=RuntimeError("network failed")),
            filename="result.png",
            destination_path="target.png",
            subfolder="",
            file_type="output",
            retries=1,
            retry_delay=0,
            min_bytes=1,
            hard_timeout=2,
        )

        self.assertFalse(result.success)
        self.assertEqual(result.error, "network failed")
    def test_batch_timeout_includes_running_and_pending_jobs(self):
        client = _QueueClient(
            {
                "queue_pending": [["one"], ["two"]],
                "queue_running": [["three"]],
            }
        )

        timeout = resolve_batch_timeout(
            client,
            base_timeout=300,
            grace_per_job=15,
        )

        self.assertEqual(timeout, 345.0)
        self.assertEqual(
            resolve_result_watch_timeout(3, base_timeout=300, grace=60),
            960.0,
        )

    def test_finds_newest_matching_output_after_start_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            first_dir = os.path.join(tmp, "first")
            second_dir = os.path.join(tmp, "second")
            os.makedirs(first_dir)
            os.makedirs(second_dir)
            first = os.path.join(first_dir, "result.png")
            second = os.path.join(second_dir, "RESULT.PNG")
            open(first, "wb").close()
            open(second, "wb").close()
            os.utime(first, (10, 10))
            os.utime(second, (20, 20))

            result = find_output_by_basename(
                tmp,
                "nested/result.png",
                15,
                scan_limit=100,
            )

            self.assertEqual(result, second)

    def test_recovers_and_classifies_prefixed_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = [
                os.path.join(tmp, "charon_run_image.png"),
                os.path.join(tmp, "charon_run_camera.nukecam"),
                os.path.join(tmp, "charon_run_mesh.glb"),
                os.path.join(tmp, "other.png"),
                os.path.join(tmp, ".charon_run_hidden.png"),
            ]
            for path in paths:
                open(path, "wb").close()

            artifacts = recover_artifacts_from_output_dir(
                ["charon_run"],
                tmp,
                0,
                scan_limit=100,
                image_extensions={".png"},
                camera_extensions={".nukecam"},
                model_extensions={".glb"},
            )

            self.assertEqual(
                {entry["kind"] for entry in artifacts},
                {"images", "camera", "meshes"},
            )
            self.assertEqual(len(artifacts), 3)


if __name__ == "__main__":
    unittest.main()
