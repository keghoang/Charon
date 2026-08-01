"""Edge-case tests for model copy/download transfers.

These cover the machine-specific conditions behind the "download shows
progress but never moves" field report: stale lock files left by crashed
sessions, servers that stall or omit Content-Length, transfers that
outlive their dialog, and the singleton shutdown flag.
"""

import os
import tempfile
import threading
import time
import unittest
from unittest import mock

from charon.model_transfer_manager import ModelTransferManager


class FakeHTTPResponse:
    """Stand-in for urllib's HTTPResponse supporting scripted bodies."""

    def __init__(self, chunks, content_length=None, block_event=None):
        self._chunks = list(chunks)
        self._content_length = content_length
        self._block_event = block_event
        self._closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def close(self):
        self._closed = True
        if self._block_event is not None:
            self._block_event.set()

    def getheader(self, name):
        if name.lower() == "content-length" and self._content_length is not None:
            return str(self._content_length)
        return None

    def read(self, amt=None):
        if self._block_event is not None:
            # Simulates a read blocked on a stalled server / dead SMB session.
            self._block_event.wait()
        if self._closed:
            raise OSError("read on closed connection")
        if self._chunks:
            return self._chunks.pop(0)
        return b""


def wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def collect_states(state_log):
    def listener(state):
        state_log.append(
            {
                "percent": state.percent,
                "copied": state.copied_bytes,
                "total": state.total_bytes,
                "in_progress": state.in_progress,
                "error": state.error,
            }
        )

    return listener


class DownloadProgressTests(unittest.TestCase):
    def _run_download(self, manager, destination, response, listener=None):
        with mock.patch("urllib.request.urlopen", return_value=response):
            state = manager.start_download("http://example.test/model.bin", destination)
            if listener is not None:
                manager.subscribe(destination, 1, listener)
            self.assertTrue(wait_for(lambda: not state.in_progress))
            if state.thread:
                state.thread.join(timeout=5)
        return state

    def test_download_success_publishes_file_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = os.path.join(tmp, "model.bin")
            response = FakeHTTPResponse([b"a" * 10, b"b" * 10], content_length=20)
            state = self._run_download(ModelTransferManager(), destination, response)

            self.assertIsNone(state.error)
            self.assertEqual(100, state.percent)
            self.assertTrue(os.path.exists(destination))
            leftovers = [n for n in os.listdir(tmp) if n != "model.bin"]
            self.assertEqual([], leftovers, "temp/lock files must not survive success")

    def test_missing_content_length_still_reports_copied_bytes(self):
        # Servers that omit Content-Length leave percent at 0 (no total to
        # compute against); copied_bytes still advances so the UI can render
        # byte progress instead of a frozen percentage.
        with tempfile.TemporaryDirectory() as tmp:
            destination = os.path.join(tmp, "model.bin")
            states = []
            response = FakeHTTPResponse([b"a" * 10, b"b" * 10], content_length=None)
            state = self._run_download(
                ModelTransferManager(), destination, response, collect_states(states)
            )

            self.assertIsNone(state.error)
            mid_flight = [s for s in states if s["in_progress"] and s["copied"] > 0]
            self.assertTrue(mid_flight, "expected progress callbacks while copying")

    def test_content_length_mismatch_never_exceeds_100_percent(self):
        # A server/proxy that under-reports Content-Length must not push the
        # progress bar past 100%.
        with tempfile.TemporaryDirectory() as tmp:
            destination = os.path.join(tmp, "model.bin")
            states = []
            response = FakeHTTPResponse([b"a" * 20, b"b" * 20], content_length=10)
            state = self._run_download(
                ModelTransferManager(), destination, response, collect_states(states)
            )

            self.assertIsNone(state.error)
            self.assertTrue(all(s["percent"] <= 100 for s in states))

    def test_cancel_between_chunks_stops_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = os.path.join(tmp, "model.bin")
            manager = ModelTransferManager()

            def cancel_after_first_chunk(state):
                if state.copied_bytes > 0:
                    state.cancelled = True

            response = FakeHTTPResponse([b"a" * 10, b"b" * 10, b"c" * 10])
            state = self._run_download(
                manager, destination, response, cancel_after_first_chunk
            )

            self.assertEqual("Transfer cancelled", state.error)
            self.assertFalse(os.path.exists(destination))
            self.assertEqual([], os.listdir(tmp), "cancel must remove temp and lock")

    def test_cancel_interrupts_a_blocked_read(self):
        # cancel_all() closes the response handle, which makes a read blocked
        # on a stalled server raise so the worker can exit and clean up.
        with tempfile.TemporaryDirectory() as tmp:
            destination = os.path.join(tmp, "model.bin")
            manager = ModelTransferManager()
            gate = threading.Event()
            response = FakeHTTPResponse([b"a" * 10], block_event=gate)

            with mock.patch("urllib.request.urlopen", return_value=response):
                state = manager.start_download("http://example.test/model.bin", destination)
                self.assertTrue(wait_for(lambda: state.closer is not None))
                manager.cancel_all()
                self.assertTrue(wait_for(lambda: not state.in_progress))
                state.thread.join(timeout=5)

            self.assertEqual("Transfer cancelled", state.error)
            self.assertFalse(os.path.exists(destination))
            self.assertEqual([], os.listdir(tmp), "cancel must remove temp and lock")

    def test_watchdog_fails_a_stalled_transfer(self):
        # A transfer with no byte progress is failed by the watchdog so the
        # UI and the transfer queue are never wedged behind it.
        with tempfile.TemporaryDirectory() as tmp:
            destination = os.path.join(tmp, "model.bin")
            manager = ModelTransferManager()
            manager.stall_timeout = 0.3
            manager.watchdog_interval = 0.05
            gate = threading.Event()
            response = FakeHTTPResponse([b"a" * 10], block_event=gate)

            with mock.patch("urllib.request.urlopen", return_value=response):
                state = manager.start_download("http://example.test/model.bin", destination)
                self.assertTrue(wait_for(lambda: not state.in_progress))
                self.assertIn("stalled", state.error or "")
                state.thread.join(timeout=5)


class LockFileTests(unittest.TestCase):
    def _write_lock(self, destination, age_seconds=0.0):
        lock_path = destination + ".charon.lock"
        with open(lock_path, "w", encoding="utf-8") as handle:
            handle.write("pid=other host=other-machine\n")
        if age_seconds:
            stamp = time.time() - age_seconds
            os.utime(lock_path, (stamp, stamp))
        return lock_path

    def test_fresh_foreign_lock_blocks_transfer_and_is_preserved(self):
        # A recently refreshed lock belongs to a live transfer on another
        # workstation: the attempt must fail AND must not delete that lock.
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "src.bin")
            destination = os.path.join(tmp, "model.bin")
            with open(source, "wb") as handle:
                handle.write(b"payload")
            lock_path = self._write_lock(destination)

            manager = ModelTransferManager()
            state = manager.start_copy(source, destination)
            self.assertTrue(wait_for(lambda: not state.in_progress))
            state.thread.join(timeout=5)

            self.assertIn("Another workstation", state.error or "")
            self.assertFalse(os.path.exists(destination))
            self.assertTrue(
                os.path.exists(lock_path),
                "a live foreign lock must never be deleted by a failed attempt",
            )

    def test_stale_lock_from_crashed_session_is_reclaimed(self):
        # A lock whose owner stopped refreshing it (crashed/killed session)
        # must not block the model forever.
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "src.bin")
            destination = os.path.join(tmp, "model.bin")
            with open(source, "wb") as handle:
                handle.write(b"payload")
            manager = ModelTransferManager()
            self._write_lock(destination, age_seconds=manager.stale_lock_seconds + 60)

            state = manager.start_copy(source, destination)
            self.assertTrue(wait_for(lambda: not state.in_progress))
            state.thread.join(timeout=5)

            self.assertIsNone(state.error)
            self.assertTrue(os.path.exists(destination))

    def test_existing_destination_counts_as_delivered(self):
        # If another workstation already delivered the model, retrying is a
        # success, not a "Destination already exists" error.
        with tempfile.TemporaryDirectory() as tmp:
            destination = os.path.join(tmp, "model.bin")
            with open(destination, "wb") as handle:
                handle.write(b"already here")

            manager = ModelTransferManager()
            response = FakeHTTPResponse([b"a" * 10], content_length=10)
            with mock.patch("urllib.request.urlopen", return_value=response):
                state = manager.start_download("http://example.test/model.bin", destination)
                self.assertTrue(wait_for(lambda: not state.in_progress))
                state.thread.join(timeout=5)

            self.assertIsNone(state.error)
            self.assertEqual(100, state.percent)

    def test_copy_rejects_existing_destination_with_different_size(self):
        # Same name, different size: refuse rather than pretend it matches.
        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "src.bin")
            destination = os.path.join(tmp, "model.bin")
            with open(source, "wb") as handle:
                handle.write(b"new payload bytes")
            with open(destination, "wb") as handle:
                handle.write(b"old")

            manager = ModelTransferManager()
            state = manager.start_copy(source, destination)
            self.assertTrue(wait_for(lambda: not state.in_progress))
            state.thread.join(timeout=5)

            self.assertIn("different size", state.error or "")
            with open(destination, "rb") as handle:
                self.assertEqual(b"old", handle.read())

    def test_destination_appearing_mid_download_with_same_size_is_success(self):
        # A second machine publishing the identical model mid-download must
        # not turn our fully downloaded transfer into an error.
        with tempfile.TemporaryDirectory() as tmp:
            destination = os.path.join(tmp, "model.bin")
            manager = ModelTransferManager()

            def plant_destination(state):
                if state.copied_bytes and not os.path.exists(destination):
                    with open(destination, "wb") as handle:
                        handle.write(b"x" * 20)

            response = FakeHTTPResponse([b"a" * 10, b"b" * 10], content_length=20)
            with mock.patch("urllib.request.urlopen", return_value=response):
                state = manager.start_download("http://example.test/model.bin", destination)
                manager.subscribe(destination, 1, plant_destination)
                self.assertTrue(wait_for(lambda: not state.in_progress))
                state.thread.join(timeout=5)

            self.assertIsNone(state.error)
            self.assertTrue(os.path.exists(destination))


class ListenerLifecycleTests(unittest.TestCase):
    def test_fast_failure_is_delivered_to_a_late_subscriber(self):
        # A transfer that fails before the UI subscribes must keep its
        # terminal state so subscribe() can still deliver the outcome
        # (otherwise the row shows "Downloading..." forever).
        with tempfile.TemporaryDirectory() as tmp:
            destination = os.path.join(tmp, "model.bin")
            manager = ModelTransferManager()
            state = manager.start_copy(os.path.join(tmp, "missing-src.bin"), destination)
            self.assertTrue(wait_for(lambda: not state.in_progress))
            state.thread.join(timeout=5)

            calls = []
            result = manager.subscribe(destination, 1, calls.append)
            self.assertIs(state, result)
            self.assertEqual(1, len(calls))
            self.assertIsNotNone(calls[0].error)
            # Once delivered and unsubscribed, the state is pruned.
            manager.unsubscribe(destination, 1)
            self.assertEqual({}, manager.active_states())

    def test_listener_attached_mid_flight_receives_terminal_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = os.path.join(tmp, "model.bin")
            manager = ModelTransferManager()
            gate = threading.Event()
            states = []
            response = FakeHTTPResponse([b"a" * 10], content_length=10, block_event=gate)

            with mock.patch("urllib.request.urlopen", return_value=response):
                state = manager.start_download("http://example.test/model.bin", destination)
                self.assertIsNotNone(manager.subscribe(destination, 1, collect_states(states)))
                gate.set()
                self.assertTrue(wait_for(lambda: not state.in_progress))
                state.thread.join(timeout=5)

            self.assertTrue(states)
            self.assertFalse(states[-1]["in_progress"])
            self.assertIsNone(states[-1]["error"])

    def test_listener_exception_does_not_abort_transfer_or_caller(self):
        # Both the initial subscribe() replay and worker-thread emits must
        # shield the transfer (and the UI caller) from a raising listener.
        with tempfile.TemporaryDirectory() as tmp:
            destination = os.path.join(tmp, "model.bin")
            manager = ModelTransferManager()

            def bad_listener(_state):
                raise RuntimeError("UI blew up")

            response = FakeHTTPResponse([b"a" * 10], content_length=10)
            with mock.patch("urllib.request.urlopen", return_value=response):
                state = manager.start_download("http://example.test/model.bin", destination)
                manager.subscribe(destination, 1, bad_listener)  # must not raise
                self.assertTrue(wait_for(lambda: not state.in_progress))
                state.thread.join(timeout=5)

            self.assertIsNone(state.error)
            self.assertTrue(os.path.exists(destination))

    def test_destination_keys_normalize_case_and_slashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = os.path.join(tmp, "Model.BIN")
            manager = ModelTransferManager()
            spelled_differently = destination.replace("\\", "/").lower()
            self.assertEqual(
                manager._key(destination), manager._key(spelled_differently)
            )


class SingletonShutdownTests(unittest.TestCase):
    def test_new_transfer_revives_a_shut_down_manager(self):
        # The singleton lives for the whole host session; closing the main
        # window once must not leave every later panel with dead transfers.
        with tempfile.TemporaryDirectory() as tmp:
            destination = os.path.join(tmp, "model.bin")
            manager = ModelTransferManager()
            manager.shutdown()

            response = FakeHTTPResponse([b"a" * 10], content_length=10)
            with mock.patch("urllib.request.urlopen", return_value=response):
                state = manager.start_download("http://example.test/model.bin", destination)
                self.assertTrue(wait_for(lambda: not state.in_progress))
                state.thread.join(timeout=5)

            self.assertIsNone(state.error)
            self.assertTrue(os.path.exists(destination))

    def test_shutdown_unblocks_a_stuck_worker_and_cleans_up(self):
        # shutdown() cancels transfers and closes their handles, so a worker
        # blocked in read() exits promptly and its finally block removes the
        # lock -- no stranded .charon.lock on shared storage.
        with tempfile.TemporaryDirectory() as tmp:
            destination = os.path.join(tmp, "model.bin")
            manager = ModelTransferManager()
            gate = threading.Event()
            response = FakeHTTPResponse([b"a" * 10], block_event=gate)

            with mock.patch("urllib.request.urlopen", return_value=response):
                state = manager.start_download("http://example.test/model.bin", destination)
                self.assertTrue(wait_for(lambda: state.closer is not None))

                started = time.monotonic()
                manager.shutdown()
                self.assertLess(time.monotonic() - started, 5.0)

                self.assertTrue(wait_for(lambda: not state.thread.is_alive()))
            lock_path = destination + ".charon.lock"
            self.assertFalse(
                os.path.exists(lock_path),
                "unblocked worker must remove its lock on the way out",
            )


if __name__ == "__main__":
    unittest.main()
