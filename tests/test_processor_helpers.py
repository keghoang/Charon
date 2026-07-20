import unittest

from charon.processor_output import (
    collect_output_artifacts,
    is_camera_output_entry,
    is_ignored_output_path,
    is_image_output_entry,
    is_mesh_output_entry,
    normalize_download_target,
    output_entry_label,
    progress_for_batch,
    resolve_local_output_candidate,
)
from charon.processor_status import lifecycle_from_progress, update_status_payload


class ProcessorHelperTests(unittest.TestCase):
    def test_lifecycle_from_progress(self):
        self.assertEqual(lifecycle_from_progress(-1, "Error"), "Error")
        self.assertEqual(lifecycle_from_progress(1.0, "Completed"), "Completed")
        self.assertEqual(lifecycle_from_progress(0.5, "Processing"), "Processing")

    def test_status_payload_moves_completed_run_into_history(self):
        payload = update_status_payload(
            {},
            lifecycle="Completed",
            message="Complete",
            progress=1.0,
            run_id="run-1",
            run_started_at=10.0,
            auto_import=True,
            extra={"output_path": "result.png", "prompt_id": "prompt-1"},
            now=20.0,
        )

        self.assertNotIn("current_run", payload)
        self.assertEqual(payload["state"], "Completed")
        self.assertEqual(payload["runs"][0]["output_path"], "result.png")

    def test_ignored_output_path(self):
        self.assertTrue(is_ignored_output_path("C:/tmp/charoninput_ignore_preview.png", "charoninput_ignore"))
        self.assertFalse(is_ignored_output_path("C:/tmp/final.png", "charoninput_ignore"))

    def test_output_path_helpers(self):
        self.assertEqual(normalize_download_target("nested/result.png", ""), ("result.png", "nested"))
        self.assertEqual(
            resolve_local_output_candidate("C:/ComfyUI/output", "result.png", "nested"),
            "C:\\ComfyUI\\output\\nested\\result.png",
        )
        self.assertEqual(progress_for_batch(1, 0.5, 0.25), 0.875)

    def test_collect_and_classify_output_artifacts(self):
        artifacts = collect_output_artifacts(
            {"1": {"images": [{"filename": "result.png"}], "camera": "camera.nukecam"}},
            {"1": {"class_type": "SaveImage"}},
            ignored_output=lambda path: False,
            camera_extensions={".nukecam"},
            model_extensions={".glb"},
        )

        self.assertEqual(artifacts[0]["kind"], "images")
        self.assertEqual(artifacts[1]["kind"], "camera")
        self.assertTrue(
            is_image_output_entry(
                {"output_path": "result.png"},
                camera_extensions={".nukecam"},
                model_extensions={".glb"},
                image_extensions={".png"},
            )
        )
        self.assertTrue(
            is_mesh_output_entry(
                {"output_path": "mesh.glb"},
                camera_extensions={".nukecam"},
                model_extensions={".glb"},
            )
        )
        self.assertTrue(
            is_camera_output_entry(
                {"output_path": "camera.nukecam"},
                camera_extensions={".nukecam"},
            )
        )
        self.assertTrue(
            is_camera_output_entry(
                {"extension": ".nukecam"},
                camera_extensions={".nukecam"},
            )
        )
        self.assertEqual(
            output_entry_label(
                {"output_path": "camera.nukecam"},
                camera_extensions={".nukecam"},
                camera_label="Camera",
                sanitize_name=lambda value, default: value or default,
            ),
            "Camera",
        )


if __name__ == "__main__":
    unittest.main()
