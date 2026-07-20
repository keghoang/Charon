import os
import tempfile
import unittest
from unittest import mock

from charon.model_transfer_manager import ModelTransferManager, TransferState
from charon.validation_resolver import (
    determine_expected_model_path,
    find_shared_model_matches,
    select_first_model_match,
)


class ModelSafetyTests(unittest.TestCase):
    def test_model_destination_rejects_category_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            models_root = os.path.join(tmp, "models")
            os.makedirs(models_root)

            target = determine_expected_model_path(
                {"name": "model.safetensors", "category": ".."},
                models_root,
                tmp,
            )

            self.assertEqual(os.path.join(models_root, "model.safetensors"), target)

    def test_copy_does_not_overwrite_existing_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "source.bin")
            destination = os.path.join(tmp, "destination.bin")
            with open(source, "wb") as handle:
                handle.write(b"new")
            with open(destination, "wb") as handle:
                handle.write(b"existing")

            state = TransferState(kind="copy", source=source, destination=destination)
            ModelTransferManager()._run_copy(state)

            self.assertIsNotNone(state.error)
            with open(destination, "rb") as handle:
                self.assertEqual(b"existing", handle.read())

    def test_shared_model_match_does_not_duplicate_root_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            model_path = os.path.join(tmp, "model.safetensors")
            with open(model_path, "wb") as handle:
                handle.write(b"model")

            with mock.patch("charon.validation_resolver.SHARED_MODELS_ROOT", tmp):
                matches = find_shared_model_matches("model.safetensors")

            self.assertEqual([model_path], matches)

    def test_first_model_match_is_selected_when_duplicates_exist(self):
        matches = [
            r"C:\models\first\model.safetensors",
            r"C:\models\second\model.safetensors",
        ]

        self.assertEqual(matches[0], select_first_model_match(matches))


if __name__ == "__main__":
    unittest.main()
