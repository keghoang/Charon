import json
import unittest
from unittest import mock

from charon.comfy_client import ComfyUIClient


class _Response:
    def __init__(self, payload, status=200):
        self._payload = payload
        self._status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def getcode(self):
        return self._status

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


class ComfyClientTests(unittest.TestCase):
    def test_connection_accepts_comfy_system_stats(self):
        client = ComfyUIClient()
        with mock.patch.object(
            client,
            "_urlopen_with_retry",
            return_value=_Response({"system": {}, "devices": []}),
        ):
            self.assertTrue(client.test_connection())

    def test_connection_rejects_non_comfy_json_service(self):
        client = ComfyUIClient()
        with mock.patch.object(
            client,
            "_urlopen_with_retry",
            return_value=_Response({"status": "ok"}),
        ):
            self.assertFalse(client.test_connection())


if __name__ == "__main__":
    unittest.main()
