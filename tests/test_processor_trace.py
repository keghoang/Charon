import os
import tempfile
import unittest

from charon.processor_trace import ExecutionTrace, create_execution_trace


class ProcessorTraceTests(unittest.TestCase):
    def test_disabled_trace_has_no_side_effects(self):
        messages = []
        trace = ExecutionTrace(enabled=False, log_debug=messages.append)

        trace.emit("ignored", run_id="run-1")

        self.assertEqual(trace.step, 0)
        self.assertEqual(messages, [])

    def test_trace_orders_fields_and_persists_steps(self):
        messages = []
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "trace.log")
            trace = ExecutionTrace(enabled=True, log_debug=messages.append, log_path=path)

            trace.emit("submitted", workflow_id="wf-1", run_id="run-1")

            with open(path, "r", encoding="utf-8") as handle:
                line = handle.read()
        self.assertIn("step=0001 submitted | run_id=run-1, workflow_id=wf-1", line)
        self.assertTrue(messages[0].startswith("[STEP] "))

    def test_factory_uses_runtime_debug_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace = create_execution_trace(
                tmp,
                "node-1",
                enabled=True,
                log_debug=lambda _message: None,
                timestamp=123,
                trace_id="abcdefgh-extra",
            )

            self.assertTrue(trace.log_path.endswith("charon_step_trace_123_node-1_abcdefgh.log"))
            self.assertTrue(os.path.isdir(os.path.dirname(trace.log_path)))


if __name__ == "__main__":
    unittest.main()
