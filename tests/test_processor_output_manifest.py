import json
import os
import tempfile
import unittest

from charon.processor_output import (
    allocate_result_manifest_path,
    cleanup_result_handoff,
    limit_output_entries,
    read_result_manifest,
    resolve_result_entries,
    run_auto_contact_sheet,
    sanitize_output_name,
    write_result_manifest,
)


class ProcessorOutputManifestTests(unittest.TestCase):
    def test_sanitizes_output_name(self):
        self.assertEqual(sanitize_output_name(" LTX / Preview "), "LTX___Preview")
        self.assertEqual(sanitize_output_name("", "Output"), "Output")

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

    def test_result_manifest_is_unavailable_until_non_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "result.json")

            self.assertIsNone(read_result_manifest(path))
            open(path, "w", encoding="utf-8").close()
            self.assertIsNone(read_result_manifest(path))

    def test_reads_published_result_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "result.json")
            write_result_manifest(path, {"success": True, "outputs": []})

            self.assertEqual(
                read_result_manifest(path),
                {"success": True, "outputs": []},
            )

    def test_rejects_non_object_result_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "result.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(["unexpected"], handle)

            with self.assertRaisesRegex(ValueError, "JSON object"):
                read_result_manifest(path)

    def test_normalizes_batched_and_legacy_result_entries(self):
        batch_entries = [{"output_path": "one.png"}, {"output_path": "two.png"}]

        self.assertEqual(
            resolve_result_entries({"outputs": batch_entries, "batch_total": 4}),
            (batch_entries, 4),
        )
        legacy = {"success": True, "output_path": "one.png"}
        self.assertEqual(resolve_result_entries(legacy), ([legacy], 1))

    def test_limits_auto_import_to_newest_entries(self):
        entries = ["one", "two", "three"]

        self.assertEqual(limit_output_entries(entries, 2), (["two", "three"], 1))
        self.assertEqual(limit_output_entries(entries, 0), (entries, 0))

    def test_cleanup_consumes_manifest_and_preserves_rendered_debug_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            result_path = os.path.join(tmp, "result.json")
            rendered_path = os.path.join(tmp, "rendered.exr")
            write_result_manifest(result_path, {"success": True})
            open(rendered_path, "w", encoding="utf-8").close()
            messages = []

            cleanup_result_handoff(
                result_path,
                [rendered_path],
                lambda *args: messages.append(args),
            )

            self.assertFalse(os.path.exists(result_path))
            self.assertTrue(os.path.exists(rendered_path))
            self.assertIn("Preserved temp file", messages[0][0])

    def test_auto_contact_sheet_persists_entries_and_runs_builder(self):
        writes = []
        created = []
        traces = []
        node = object()

        result = run_auto_contact_sheet(
            node,
            [{"output_path": "result.png"}],
            enabled=True,
            write_metadata=lambda *args: writes.append(args),
            create_contact_sheet=created.append,
            log_debug=lambda *_args: None,
            trace_step=lambda event, **_fields: traces.append(event),
        )

        self.assertTrue(result)
        self.assertEqual(created, [node])
        self.assertEqual(json.loads(writes[0][1])[0]["output_path"], "result.png")
        self.assertEqual(
            traces,
            ["mainthread_contact_sheet_enter", "mainthread_contact_sheet_completed"],
        )

    def test_disabled_auto_contact_sheet_skips_builder(self):
        created = []
        traces = []

        result = run_auto_contact_sheet(
            object(),
            [],
            enabled=False,
            write_metadata=lambda *_args: None,
            create_contact_sheet=created.append,
            log_debug=lambda *_args: None,
            trace_step=lambda event, **_fields: traces.append(event),
        )

        self.assertFalse(result)
        self.assertEqual(created, [])
        self.assertEqual(
            traces,
            ["mainthread_contact_sheet_enter", "mainthread_contact_sheet_skipped"],
        )


if __name__ == "__main__":
    unittest.main()
