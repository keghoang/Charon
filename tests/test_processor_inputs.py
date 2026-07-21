import unittest

from charon.processor_inputs import assign_uploaded_input, coerce_crop_box, resolve_crop_settings


class _BoundingBox:
    x = 1
    y = 2

    def r(self):
        return 11

    def t(self):
        return 12


class _Knob:
    def __init__(self, value):
        self._value = value

    def value(self):
        return self._value


class _Node:
    def __init__(self, enabled, box):
        self.knobs = {
            "charon_use_crop": _Knob(enabled),
            "charon_crop_bbox": _Knob(box),
        }

    def knob(self, name):
        return self.knobs.get(name)


class ProcessorInputTests(unittest.TestCase):
    def test_assigns_uploaded_input_to_requested_or_compatible_socket(self):
        workflow = {
            "1": {"inputs": {"custom": "old", "image": "fallback"}},
            "2": {"inputs": {"mask": "old"}},
            "3": {"inputs": {}},
        }

        self.assertTrue(assign_uploaded_input(workflow, 1, "one.png", "custom"))
        self.assertTrue(assign_uploaded_input(workflow, 2, "two.png"))
        self.assertTrue(assign_uploaded_input(workflow, 3, "three.png"))
        self.assertFalse(assign_uploaded_input(workflow, 4, "missing.png"))

        self.assertEqual(workflow["1"]["inputs"]["custom"], "one.png")
        self.assertEqual(workflow["2"]["inputs"]["mask"], "two.png")
        self.assertEqual(workflow["3"]["inputs"]["image"], "three.png")

    def test_resolves_enabled_non_empty_crop(self):
        messages = []

        result = resolve_crop_settings(
            _Node(True, [1, 2, 11, 12]),
            log_debug=lambda *args: messages.append(args),
        )

        self.assertEqual(result, (1.0, 2.0, 11.0, 12.0))
        self.assertIn("Using crop box", messages[0][0])

    def test_rejects_disabled_and_empty_crop(self):
        self.assertIsNone(
            resolve_crop_settings(_Node(False, [1, 2, 11, 12]), log_debug=lambda *_: None)
        )
        self.assertIsNone(
            resolve_crop_settings(_Node(True, [1, 2, 1, 12]), log_debug=lambda *_: None)
        )

    def test_coerces_sequence_and_nuke_style_object(self):
        self.assertEqual(coerce_crop_box([1, 2, 11, 12]), (1.0, 2.0, 11.0, 12.0))
        self.assertEqual(coerce_crop_box(_BoundingBox()), (1.0, 2.0, 11.0, 12.0))

    def test_rejects_missing_and_non_numeric_boxes(self):
        self.assertIsNone(coerce_crop_box([1, 2, 3]))
        self.assertIsNone(coerce_crop_box([1, 2, "right", 4]))


if __name__ == "__main__":
    unittest.main()
