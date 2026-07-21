import unittest

from charon.processor_recursion import handle_recursive_completion


class _Knob:
    def __init__(self, value):
        self._value = value

    def value(self):
        return self._value


class _Node:
    def __init__(self, enabled, iterations=1, current=0):
        self._knobs = {
            "charon_recursive_enable": _Knob(enabled),
            "charon_recursive_iterations": _Knob(iterations),
            "charon_recursive_current": _Knob(current),
        }

    def knob(self, name):
        return self._knobs[name]


class ProcessorRecursionTests(unittest.TestCase):
    def test_dispatches_next_recursive_iteration(self):
        node = _Node(True, iterations=3, current=0)
        updates = []
        processed = []
        sleeps = []
        traces = []

        handle_recursive_completion(
            object(),
            node,
            {"output_path": "result.png"},
            update_recursive_inputs=lambda *args: updates.append(args),
            process_next=lambda: processed.append(node),
            log_debug=lambda *_args: None,
            trace_step=lambda event, **_fields: traces.append(event),
            sleep=sleeps.append,
        )

        self.assertEqual(updates, [(node, "result.png")])
        self.assertEqual(processed, [node])
        self.assertEqual(sleeps, [2.0])
        self.assertEqual(
            traces,
            ["mainthread_recursion_enter", "mainthread_recursion_completed"],
        )

    def test_disabled_recursion_has_no_side_effects(self):
        node = _Node(False)
        processed = []
        traces = []

        handle_recursive_completion(
            object(),
            node,
            {},
            update_recursive_inputs=lambda *_args: None,
            process_next=lambda: processed.append(node),
            log_debug=lambda *_args: None,
            trace_step=lambda event, **_fields: traces.append(event),
            sleep=lambda _seconds: None,
        )

        self.assertEqual(processed, [])
        self.assertEqual(
            traces,
            ["mainthread_recursion_enter", "mainthread_recursion_completed"],
        )


if __name__ == "__main__":
    unittest.main()
