import sys
import unittest

from charon.process_runner import ProcessExecutionError, run_subprocess


class ProcessRunnerTests(unittest.TestCase):
    def test_captures_stdout(self):
        result = run_subprocess(
            [sys.executable, "-c", "print('hello')"],
            check=True,
            timeout=10,
        )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "hello")
        self.assertFalse(result.timed_out)

    def test_raises_on_non_zero_when_checked(self):
        with self.assertRaises(ProcessExecutionError) as ctx:
            run_subprocess(
                [sys.executable, "-c", "import sys; print('bad'); sys.exit(3)"],
                check=True,
                timeout=10,
            )

        self.assertEqual(ctx.exception.result.returncode, 3)
        self.assertIn("bad", ctx.exception.result.stdout)

    def test_raises_on_timeout(self):
        with self.assertRaises(ProcessExecutionError) as ctx:
            run_subprocess(
                [sys.executable, "-c", "import time; time.sleep(2)"],
                check=True,
                timeout=0.2,
            )

        self.assertTrue(ctx.exception.result.timed_out)


if __name__ == "__main__":
    unittest.main()
