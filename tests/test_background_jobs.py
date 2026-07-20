import threading
import unittest

from charon.background_jobs import run_blocking_with_timeout, start_daemon_job


class BackgroundJobTests(unittest.TestCase):
    def test_starts_named_daemon_job(self):
        completed = threading.Event()

        worker = start_daemon_job(completed.set, thread_name="charon-test-job")
        worker.join(timeout=1)

        self.assertTrue(completed.is_set())
        self.assertEqual(worker.name, "charon-test-job")
        self.assertTrue(worker.daemon)

    def test_returns_completed_value(self):
        result = run_blocking_with_timeout(
            lambda: "done",
            timeout=1,
            thread_name="test-job",
        )

        self.assertTrue(result.completed)
        self.assertEqual(result.value, "done")
        self.assertIsNone(result.error)

    def test_captures_worker_error(self):
        def fail():
            raise RuntimeError("failed")

        result = run_blocking_with_timeout(
            fail,
            timeout=1,
            thread_name="test-job",
        )

        self.assertTrue(result.completed)
        self.assertIsInstance(result.error, RuntimeError)

    def test_reports_timeout_without_blocking_caller(self):
        release = threading.Event()
        try:
            result = run_blocking_with_timeout(
                release.wait,
                timeout=0.01,
                thread_name="test-timeout",
            )
        finally:
            release.set()

        self.assertTrue(result.timed_out)


if __name__ == "__main__":
    unittest.main()
