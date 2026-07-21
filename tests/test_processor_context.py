import unittest

from charon.processor_context import (
    capture_node_coordinates,
    capture_processor_run_context,
    resolve_batch_count,
    resolve_node_auto_import,
    resolve_nuke_script_name,
    resolve_workflow_display_name,
)


class _Knob:
    def __init__(self, value):
        self._value = value

    def value(self):
        return self._value


class _Node:
    def __init__(self, knobs=None, metadata=None):
        self._knobs = knobs or {}
        self._metadata = metadata

    def knob(self, name):
        return self._knobs.get(name)

    def metadata(self, _key):
        return self._metadata

    def xpos(self):
        return 10

    def ypos(self):
        return 20


class _Root:
    def __init__(self, name):
        self._name = name

    def name(self):
        return self._name


class _Nuke:
    def __init__(self, root_name):
        self._root = _Root(root_name)

    def root(self):
        return self._root


class ProcessorContextTests(unittest.TestCase):
    def test_captures_node_coordinates(self):
        self.assertEqual(capture_node_coordinates(_Node()), (10, 20))

    def test_resolves_workflow_name_from_knob_then_path(self):
        named = _Node(
            {
                "charon_workflow_name": _Knob(" LTX Video "),
                "workflow_path": _Knob("D:/workflows/fallback.json"),
            }
        )
        path_only = _Node({"workflow_path": _Knob("D:/workflows/fallback.json")})

        self.assertEqual(resolve_workflow_display_name(named), "LTX Video")
        self.assertEqual(resolve_workflow_display_name(path_only), "fallback")

    def test_resolves_batch_count_with_minimum_one(self):
        self.assertEqual(resolve_batch_count(_Node({"charon_batch_count": _Knob(4)})), 4)
        self.assertEqual(resolve_batch_count(_Node({"charon_batch_count": _Knob(0)})), 1)

    def test_resolves_nuke_script_basename(self):
        self.assertEqual(resolve_nuke_script_name(_Nuke("D:/shots/example_v001.nk")), "example_v001")
        self.assertEqual(resolve_nuke_script_name(_Nuke("")), "untitled")

    def test_auto_import_knob_takes_precedence(self):
        node = _Node({"charon_auto_import": _Knob(0)}, metadata="true")

        self.assertFalse(resolve_node_auto_import(node))

    def test_auto_import_supports_string_metadata(self):
        self.assertFalse(resolve_node_auto_import(_Node(metadata="off")))
        self.assertTrue(resolve_node_auto_import(_Node(metadata="yes")))

    def test_auto_import_defaults_to_enabled(self):
        self.assertTrue(resolve_node_auto_import(_Node()))

    def test_capture_context_collects_unique_parameter_knobs(self):
        node = _Node({"strength": _Knob(0.75)})

        context = capture_processor_run_context(
            node,
            [{"knob": "strength"}, {"knob": "strength"}, {"invalid": True}],
        )

        self.assertEqual((context.node_x, context.node_y), (10, 20))
        self.assertEqual(context.parameter_values, {"strength": 0.75})


if __name__ == "__main__":
    unittest.main()
