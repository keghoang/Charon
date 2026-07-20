import unittest

from charon.processor_submission import build_batch_prompt, submit_prompt_or_raise


class _Client:
    def __init__(self, prompt_id):
        self.prompt_id = prompt_id

    def submit_workflow(self, _payload):
        return self.prompt_id


class ProcessorSubmissionTests(unittest.TestCase):
    def test_build_batch_prompt_applies_seed_and_normalizes(self):
        calls = []

        def apply_seed(payload, records, offset):
            calls.append((records, offset))
            payload["seeded"] = offset

        def normalize(payload):
            payload["normalized"] = True
            return 1

        payload, normalized, serialized = build_batch_prompt(
            {"1": {"inputs": {}}},
            seed_records=[{"node": "1"}],
            seed_offset=7,
            apply_seed_offset=apply_seed,
            normalize_model_paths=normalize,
        )

        self.assertEqual(payload["seeded"], 7)
        self.assertTrue(payload["normalized"])
        self.assertEqual(normalized, 1)
        self.assertIn('"seeded":7', serialized)
        self.assertEqual(calls[0][1], 7)

    def test_submit_prompt_or_raise(self):
        self.assertEqual(submit_prompt_or_raise(_Client("abc"), {"1": {}}), "abc")
        with self.assertRaises(RuntimeError):
            submit_prompt_or_raise(_Client(""), {"1": {}}, converted_prompt_path="prompt.json")


if __name__ == "__main__":
    unittest.main()
