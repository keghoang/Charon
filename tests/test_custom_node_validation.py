"""Regression tests for custom-node validation against aux_id provenance.

Frontend extensions (e.g. model-browser tools with workflow "doctor"
features) stamp ``aux_id`` provenance onto nodes they touch.  A stamp is
metadata about where a node came from, not evidence that the pack is
missing: workflows whose nodes all load must validate clean, otherwise
users loop forever on "Missing node" rows whose install fails with the
Manager's bare 400 ("Already exists").
"""

import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from charon.comfy_validation import _validate_custom_nodes


AUX_REPO = "https://github.com/DemonGatanjieu/Anomalous_Model_Browser"


def _fake_cm_cli(payload):
    """Mock subprocess.run for the cm-cli deps-in-workflow invocation."""
    import json

    def run(command, **_kwargs):
        output_path = command[6]
        with open(output_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    return run


class AuxStampValidationTests(unittest.TestCase):
    def _validate(self, workflow, cm_payload, tmp):
        env_info = {"python_exe": sys.executable, "comfy_dir": tmp}
        bundle = {"workflow": workflow, "folder": None}
        manager_root = os.path.join(tmp, "manager")
        os.makedirs(manager_root, exist_ok=True)
        with mock.patch(
            "charon.comfy_validation.locate_manager_cli",
            return_value=(os.path.join(manager_root, "cm-cli.py"), manager_root),
        ), mock.patch(
            "charon.comfy_validation._refresh_manager_catalog"
        ), mock.patch(
            "charon.comfy_validation.subprocess.run",
            side_effect=_fake_cm_cli(cm_payload),
        ):
            return _validate_custom_nodes(env_info, bundle)

    def test_aux_stamp_on_a_loading_node_is_not_a_missing_pack(self):
        # The exact field failure: every node type is known to ComfyUI, but
        # one node carries an aux_id stamp from a UI-only plugin.  The
        # workflow must validate clean.
        workflow = {
            "nodes": [
                {
                    "id": 1,
                    "type": "KSampler",
                    "properties": {"aux_id": "DemonGatanjieu/Anomalous_Model_Browser"},
                },
                {"id": 2, "type": "VAEDecode", "properties": {"cnr_id": "comfy-core"}},
            ]
        }
        cm_payload = {"custom_nodes": {}, "unknown_nodes": []}
        with tempfile.TemporaryDirectory() as tmp:
            issue = self._validate(workflow, cm_payload, tmp)
        self.assertTrue(
            issue.ok,
            f"aux-stamped but fully loading workflow flagged: {issue.summary}",
        )

    def test_unknown_node_with_aux_hint_is_still_reported(self):
        # A node type ComfyUI does NOT know, carrying an aux hint, is a real
        # missing pack and must keep being flagged (with the repo attached).
        workflow = {
            "nodes": [
                {
                    "id": 1,
                    "type": "AnomalousGallery",
                    "properties": {"aux_id": "DemonGatanjieu/Anomalous_Model_Browser"},
                }
            ]
        }
        cm_payload = {"custom_nodes": {}, "unknown_nodes": ["AnomalousGallery"]}
        with tempfile.TemporaryDirectory() as tmp:
            issue = self._validate(workflow, cm_payload, tmp)
        self.assertFalse(issue.ok)
        self.assertIn(AUX_REPO, (issue.data or {}).get("missing_repos") or [])

    def test_cm_cli_not_installed_state_is_still_reported(self):
        workflow = {
            "nodes": [
                {"id": 1, "type": "SomePackNode", "properties": {}},
            ]
        }
        cm_payload = {
            "custom_nodes": {AUX_REPO: {"state": "not-installed"}},
            "unknown_nodes": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            issue = self._validate(workflow, cm_payload, tmp)
        self.assertFalse(issue.ok)
        self.assertIn(AUX_REPO, (issue.data or {}).get("missing_repos") or [])


if __name__ == "__main__":
    unittest.main()
