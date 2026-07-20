import os
import tempfile
import unittest
import urllib.error
from unittest import mock

from charon.comfy_restart import (
    RESTART_SIGNAL_REBOOT,
    RESTART_SIGNAL_SHUTDOWN,
    process_matches_configured_paths,
    request_restart_signal,
)


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class ProcessMatchTests(unittest.TestCase):
    def test_matches_configured_child_path(self):
        with tempfile.TemporaryDirectory() as root:
            exe = os.path.join(root, "python_embeded", "python.exe")
            self.assertTrue(process_matches_configured_paths(exe, [], [root]))

    def test_rejects_sibling_prefix_path(self):
        with tempfile.TemporaryDirectory() as parent:
            root = os.path.join(parent, "ComfyUI")
            sibling = os.path.join(parent, "ComfyUI_evil", "python.exe")
            self.assertFalse(process_matches_configured_paths(sibling, [], [root]))

    def test_rejects_process_without_configured_paths(self):
        self.assertFalse(process_matches_configured_paths("python.exe", [], []))

    def test_restart_prefers_manager_reboot(self):
        with mock.patch("charon.comfy_restart.urllib.request.urlopen", return_value=_Response()) as urlopen:
            result = request_restart_signal()

        self.assertEqual(RESTART_SIGNAL_REBOOT, result)
        self.assertEqual("/manager/reboot", urlopen.call_args.args[0].full_url.rsplit("8188", 1)[-1])

    def test_restart_falls_back_to_shutdown_when_manager_is_unavailable(self):
        manager_error = urllib.error.HTTPError(
            "http://127.0.0.1:8188/manager/reboot",
            404,
            "Not Found",
            None,
            None,
        )
        with mock.patch(
            "charon.comfy_restart.urllib.request.urlopen",
            side_effect=[manager_error, _Response()],
        ) as urlopen:
            result = request_restart_signal()

        self.assertEqual(RESTART_SIGNAL_SHUTDOWN, result)
        self.assertEqual(2, urlopen.call_count)
