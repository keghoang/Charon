import json
import unittest
from pathlib import Path
from unittest import mock

from charon.workflow_browser_exporter import _verify_server_identity


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


class WorkflowBrowserExporterTests(unittest.TestCase):
    @mock.patch("charon.workflow_browser_exporter.urllib.request.urlopen")
    def test_accepts_server_from_configured_installation(self, urlopen):
        urlopen.return_value = _Response(
            {"system": {"argv": [r"D:\Comfy\ComfyUI\main.py"]}}
        )

        payload = _verify_server_identity(Path(r"D:\Comfy\ComfyUI"))

        self.assertIn("system", payload)

    @mock.patch("charon.workflow_browser_exporter.urllib.request.urlopen")
    def test_rejects_server_from_different_installation(self, urlopen):
        urlopen.return_value = _Response(
            {"system": {"argv": [r"D:\OtherComfy\ComfyUI\main.py"]}}
        )

        with self.assertRaisesRegex(RuntimeError, "different ComfyUI installation"):
            _verify_server_identity(Path(r"D:\Comfy\ComfyUI"))

    @mock.patch("charon.workflow_browser_exporter.urllib.request.urlopen")
    def test_accepts_portable_launcher_relative_main_path(self, urlopen):
        urlopen.return_value = _Response(
            {"system": {"argv": [r"ComfyUI\main.py"]}}
        )

        payload = _verify_server_identity(Path(r"D:\Comfy\ComfyUI"))

        self.assertIn("system", payload)

    @mock.patch("charon.workflow_browser_exporter.urllib.request.urlopen")
    def test_rejects_different_relative_main_path(self, urlopen):
        urlopen.return_value = _Response(
            {"system": {"argv": [r"OtherComfy\main.py"]}}
        )

        with self.assertRaisesRegex(RuntimeError, "different ComfyUI installation"):
            _verify_server_identity(Path(r"D:\Comfy\ComfyUI"))


if __name__ == "__main__":
    unittest.main()
