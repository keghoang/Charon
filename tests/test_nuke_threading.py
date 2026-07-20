import unittest

from charon.nuke_threading import (
    run_on_main_thread,
    run_on_main_thread_async,
    run_on_nuke_main_thread_blocking,
)


class _BlockingNuke:
    @staticmethod
    def executeInMainThread(callback):
        callback()


class _StalledNuke:
    @staticmethod
    def executeInMainThread(_callback):
        pass


class NukeThreadingTests(unittest.TestCase):
    def test_blocking_dispatch_returns_callback_value(self):
        result = run_on_nuke_main_thread_blocking(
            lambda: "done",
            nuke_module=_BlockingNuke(),
            label="test callback",
        )

        self.assertEqual(result, "done")

    def test_blocking_dispatch_propagates_callback_error(self):
        def fail():
            raise RuntimeError("failed")

        with self.assertRaisesRegex(RuntimeError, "failed"):
            run_on_nuke_main_thread_blocking(
                fail,
                nuke_module=_BlockingNuke(),
                label="test callback",
            )

    def test_blocking_dispatch_times_out(self):
        with self.assertRaisesRegex(TimeoutError, "stalled callback"):
            run_on_nuke_main_thread_blocking(
                lambda: None,
                nuke_module=_StalledNuke(),
                label="stalled callback",
                timeout=0.01,
            )

    def test_runs_directly_outside_nuke(self):
        self.assertEqual(run_on_main_thread(lambda value: value + 1, 2), 3)

    def test_async_runs_directly_outside_nuke(self):
        seen = []

        run_on_main_thread_async(lambda: seen.append("ran"))

        self.assertEqual(seen, ["ran"])


if __name__ == "__main__":
    unittest.main()
