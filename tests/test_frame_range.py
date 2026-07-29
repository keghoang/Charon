import os
import tempfile
import unittest

from charon.paths import allocate_custom_output_path
from charon.processor_context import resolve_frame_range
from charon.processor_output import summarize_sequence_entries


class _FakeKnob:
    def __init__(self, value):
        self._value = value

    def value(self):
        return self._value


class _FakeNode:
    def __init__(self, knobs):
        self._knobs = knobs

    def knob(self, name):
        return self._knobs.get(name)


class ResolveFrameRangeTests(unittest.TestCase):
    def test_disabled_returns_none(self):
        node = _FakeNode(
            {
                "charon_use_frame_range": _FakeKnob(0),
                "charon_frame_first": _FakeKnob(1001),
                "charon_frame_last": _FakeKnob(1010),
            }
        )
        self.assertIsNone(resolve_frame_range(node))

    def test_enabled_returns_range(self):
        node = _FakeNode(
            {
                "charon_use_frame_range": _FakeKnob(True),
                "charon_frame_first": _FakeKnob(1001),
                "charon_frame_last": _FakeKnob(1010),
            }
        )
        self.assertEqual(resolve_frame_range(node), (1001, 1010))

    def test_inverted_range_is_swapped(self):
        node = _FakeNode(
            {
                "charon_use_frame_range": _FakeKnob(1),
                "charon_frame_first": _FakeKnob(1010),
                "charon_frame_last": _FakeKnob(1001),
            }
        )
        self.assertEqual(resolve_frame_range(node), (1001, 1010))

    def test_legacy_node_without_knobs_returns_none(self):
        self.assertIsNone(resolve_frame_range(_FakeNode({})))


class FrameOutputAllocationTests(unittest.TestCase):
    def test_frames_share_one_pinned_version(self):
        with tempfile.TemporaryDirectory() as root:
            registry = {}
            first = allocate_custom_output_path(
                root, ".png", "Output", frame=1001, version_registry=registry
            )
            second = allocate_custom_output_path(
                root, ".png", "Output", frame=1002, version_registry=registry
            )
            self.assertEqual(os.path.basename(first), "CharonOutput_v001.1001.png")
            self.assertEqual(os.path.basename(second), "CharonOutput_v001.1002.png")

    def test_sequence_version_advances_past_existing_stills(self):
        with tempfile.TemporaryDirectory() as root:
            still = allocate_custom_output_path(root, ".png", "Output")
            self.assertEqual(os.path.basename(still), "CharonOutput_v001.png")
            registry = {}
            frame_path = allocate_custom_output_path(
                root, ".png", "Output", frame=1001, version_registry=registry
            )
            self.assertEqual(os.path.basename(frame_path), "CharonOutput_v002.1001.png")

    def test_plain_allocation_unchanged(self):
        with tempfile.TemporaryDirectory() as root:
            first = allocate_custom_output_path(root, ".png", "Output")
            second = allocate_custom_output_path(root, ".png", "Output")
            self.assertEqual(os.path.basename(first), "CharonOutput_v001.png")
            self.assertEqual(os.path.basename(second), "CharonOutput_v002.png")


class SummarizeSequenceEntriesTests(unittest.TestCase):
    def _entry(self, frame, path):
        return {"frame": frame, "output_path": path}

    def test_frame_entries_form_sequence(self):
        entries = [
            self._entry(1001, "D:/out/CharonOutput_v001.1001.png"),
            self._entry(1002, "D:/out/CharonOutput_v001.1002.png"),
            self._entry(1003, "D:/out/CharonOutput_v001.1003.png"),
        ]
        info = summarize_sequence_entries(entries)
        self.assertIsNotNone(info)
        self.assertEqual(info["pattern"], "D:/out/CharonOutput_v001.####.png")
        self.assertEqual(info["first"], 1001)
        self.assertEqual(info["last"], 1003)
        self.assertEqual(info["count"], 3)

    def test_backslash_paths_are_normalized(self):
        entries = [
            self._entry(1, "D:\\out\\CharonOutput_v001.0001.png"),
            self._entry(2, "D:\\out\\CharonOutput_v001.0002.png"),
        ]
        info = summarize_sequence_entries(entries)
        self.assertEqual(info["pattern"], "D:/out/CharonOutput_v001.####.png")

    def test_entry_without_frame_disables_sequence(self):
        entries = [
            self._entry(1001, "D:/out/CharonOutput_v001.1001.png"),
            self._entry(None, "D:/out/CharonOutput_v002.png"),
        ]
        self.assertIsNone(summarize_sequence_entries(entries))

    def test_single_frame_is_a_still(self):
        entries = [self._entry(1001, "D:/out/CharonOutput_v001.1001.png")]
        self.assertIsNone(summarize_sequence_entries(entries))

    def test_path_without_frame_suffix_disables_sequence(self):
        entries = [
            self._entry(1001, "D:/out/CharonOutput_v001.png"),
            self._entry(1002, "D:/out/CharonOutput_v002.png"),
        ]
        self.assertIsNone(summarize_sequence_entries(entries))


if __name__ == "__main__":
    unittest.main()
