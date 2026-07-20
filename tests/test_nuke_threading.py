import unittest

from charon.nuke_threading import run_on_main_thread, run_on_main_thread_async


class NukeThreadingTests(unittest.TestCase):
    def test_runs_directly_outside_nuke(self):
        self.assertEqual(run_on_main_thread(lambda value: value + 1, 2), 3)

    def test_async_runs_directly_outside_nuke(self):
        seen = []

        run_on_main_thread_async(lambda: seen.append("ran"))

        self.assertEqual(seen, ["ran"])


if __name__ == "__main__":
    unittest.main()
