import unittest
from unittest import mock

from charon.validation_repository import (
    WorkflowValidationRepository,
    derive_validation_state,
)


class ValidationRepositoryTests(unittest.TestCase):
    def test_derives_issue_and_restart_states(self):
        self.assertEqual(
            derive_validation_state({"issues": [{"ok": False}]}),
            "needs_resolve",
        )
        self.assertEqual(
            derive_validation_state({"issues": [], "restart_required": True}),
            "needs_resolve",
        )
        self.assertEqual(
            derive_validation_state({"auto_resolve_state": {"running": True}}),
            "installing",
        )

    def test_invalid_payload_uses_fallback(self):
        self.assertEqual(derive_validation_state(None, "idle"), "idle")

    @mock.patch(
        "charon.validation_repository.compute_validation_signature",
        return_value="signature",
    )
    @mock.patch("charon.validation_repository.load_validation_resolve_status")
    def test_reads_persisted_payload_once_then_uses_memory(
        self,
        load_status,
        _compute_signature,
    ):
        load_status.return_value = {"issues": []}
        repository = WorkflowValidationRepository()

        first = repository.read("workflow")
        second = repository.read("workflow")

        self.assertEqual(first, second)
        self.assertEqual(first["state"], "validated")
        load_status.assert_called_once_with("workflow")

    @mock.patch(
        "charon.validation_repository.compute_validation_signature",
        side_effect=["old", "new"],
    )
    @mock.patch("charon.validation_repository.load_validation_resolve_status")
    def test_invalidates_memory_when_signature_changes(
        self,
        load_status,
        _compute_signature,
    ):
        load_status.return_value = {"issues": []}
        repository = WorkflowValidationRepository()
        repository.write("workflow", "validating", {"state": "validating"})

        entry = repository.read("workflow")

        self.assertEqual(entry["state"], "validated")
        load_status.assert_called_once_with("workflow")


if __name__ == "__main__":
    unittest.main()
