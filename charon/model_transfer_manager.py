from __future__ import annotations

import os
import socket
import threading
import time
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Optional

from .charon_logger import system_debug, system_warning


# Transfers copy in small chunks so progress, cancellation, and the stall
# watchdog all get a chance to run frequently even on slow links.
CHUNK_SIZE = 256 * 1024
# A transfer with no byte progress for this long is declared stalled. SMB and
# socket reads have no reliable interrupt on Windows, so the watchdog fails the
# transfer state (unblocking the UI and queue) and closes the handle to nudge
# the blocked worker.
STALL_TIMEOUT = 120.0
WATCHDOG_INTERVAL = 5.0
# A lock file older than this belongs to a crashed/killed session and may be
# reclaimed. Active transfers refresh their lock's mtime on every chunk.
STALE_LOCK_SECONDS = 30 * 60.0
# Progress listeners are throttled; terminal states always emit.
EMIT_INTERVAL = 0.25


@dataclass
class TransferState:
    kind: str
    destination: str
    url: Optional[str] = None
    source: Optional[str] = None
    total_bytes: int = 0
    copied_bytes: int = 0
    percent: int = 0
    in_progress: bool = True
    cancelled: bool = False
    error: Optional[str] = None
    resolve_method: Optional[str] = None
    workflow_value: Optional[str] = None
    destination_display: Optional[str] = None
    file_name: Optional[str] = None
    listeners: Dict[int, Callable[["TransferState"], None]] = field(default_factory=dict)
    thread: Optional[threading.Thread] = None
    # True once at least one listener has seen this state; terminal states are
    # kept until they have been delivered so a fast failure is never lost.
    delivered: bool = False
    last_activity: float = field(default=0.0, repr=False)
    closer: Optional[Callable[[], None]] = field(default=None, repr=False)
    _last_emit: float = field(default=0.0, repr=False)


class ModelTransferManager:
    """Singleton manager for model copies/downloads that survives dialog lifetime."""

    _instance: Optional["ModelTransferManager"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._transfers: Dict[str, TransferState] = {}
        self._transfers_lock = threading.Lock()
        self._shutdown = False
        self._watchdog: Optional[threading.Thread] = None
        self.stall_timeout = STALL_TIMEOUT
        self.watchdog_interval = WATCHDOG_INTERVAL
        self.stale_lock_seconds = STALE_LOCK_SECONDS

    @classmethod
    def instance(cls) -> "ModelTransferManager":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------ Public API
    def active_states(self) -> Dict[str, TransferState]:
        with self._transfers_lock:
            return dict(self._transfers)

    def subscribe(self, destination: str, listener_id: int, callback: Callable[[TransferState], None]) -> Optional[TransferState]:
        key = self._key(destination)
        with self._transfers_lock:
            state = self._transfers.get(key)
            if state:
                state.listeners[listener_id] = callback
                state.delivered = True
        if state:
            try:
                callback(state)
            except Exception as exc:
                system_warning(f"[Transfer] Listener error: {exc}")
        return state

    def unsubscribe(self, destination: str, listener_id: int) -> None:
        key = self._key(destination)
        with self._transfers_lock:
            state = self._transfers.get(key)
            if state:
                state.listeners.pop(listener_id, None)
        if state:
            self._prune_if_idle(state)

    def start_copy(
        self,
        source: str,
        destination: str,
        *,
        resolve_method: Optional[str] = None,
        workflow_value: Optional[str] = None,
        destination_display: Optional[str] = None,
        file_name: Optional[str] = None,
    ) -> TransferState:
        return self._start_transfer(
            kind="copy",
            source=source,
            url=None,
            destination=destination,
            resolve_method=resolve_method,
            workflow_value=workflow_value,
            destination_display=destination_display,
            file_name=file_name,
        )

    def start_download(
        self,
        url: str,
        destination: str,
        *,
        resolve_method: Optional[str] = None,
        workflow_value: Optional[str] = None,
        destination_display: Optional[str] = None,
        file_name: Optional[str] = None,
    ) -> TransferState:
        return self._start_transfer(
            kind="download",
            source=None,
            url=url,
            destination=destination,
            resolve_method=resolve_method,
            workflow_value=workflow_value,
            destination_display=destination_display,
            file_name=file_name,
        )

    def shutdown(self) -> None:
        """Signal all transfers to stop and wait briefly for threads to exit."""
        self._shutdown = True
        self.cancel_all()
        for state in self.active_states().values():
            thread = state.thread
            if thread and thread.is_alive():
                try:
                    thread.join(timeout=1.0)
                except Exception:
                    pass
        with self._transfers_lock:
            self._transfers.clear()

    def cancel_all(self) -> None:
        """Cancel all active transfers without shutting down the manager."""
        for state in self.active_states().values():
            if state.in_progress:
                state.cancelled = True
                self._invoke_closer(state)

    # ------------------------------------------------------------------ Internals
    def _key(self, destination: str) -> str:
        try:
            return Path(destination).resolve().as_posix().lower()
        except Exception:
            return destination.replace("\\", "/").lower()

    def _start_transfer(
        self,
        *,
        kind: str,
        source: Optional[str],
        url: Optional[str],
        destination: str,
        resolve_method: Optional[str],
        workflow_value: Optional[str],
        destination_display: Optional[str],
        file_name: Optional[str],
    ) -> TransferState:
        # A new transfer request revives the manager after a window close in
        # the same host session; the singleton must not stay dead forever.
        self._shutdown = False
        key = self._key(destination)
        state = TransferState(
            kind=kind,
            destination=destination,
            url=url,
            source=source,
            resolve_method=resolve_method,
            workflow_value=workflow_value,
            destination_display=destination_display,
            file_name=file_name,
        )
        with self._transfers_lock:
            existing = self._transfers.get(key)
            if existing and existing.in_progress:
                system_debug(f"[Transfer] Reusing in-progress transfer | dest='{destination}' kind='{existing.kind}'")
                return existing
            self._transfers[key] = state

        worker = self._run_copy if kind == "copy" else self._run_download
        thread = threading.Thread(
            target=worker,
            name=f"ModelTransfer-{Path(destination).name}",
            args=(state,),
            daemon=True,
        )
        state.thread = thread
        state.last_activity = time.monotonic()
        self._ensure_watchdog()
        thread.start()
        return state

    def _ensure_watchdog(self) -> None:
        if self._watchdog and self._watchdog.is_alive():
            return
        self._watchdog = threading.Thread(
            target=self._watchdog_loop,
            name="ModelTransferWatchdog",
            daemon=True,
        )
        self._watchdog.start()

    def _watchdog_loop(self) -> None:
        while True:
            time.sleep(self.watchdog_interval)
            now = time.monotonic()
            for state in self.active_states().values():
                if not state.in_progress or state.cancelled:
                    continue
                if not state.last_activity:
                    continue
                if now - state.last_activity <= self.stall_timeout:
                    continue
                state.error = (
                    f"Transfer stalled: no data received for {int(self.stall_timeout)}s"
                )
                state.cancelled = True
                state.in_progress = False
                system_warning(
                    f"[Transfer] Stalled | kind='{state.kind}' dest='{state.destination}'"
                )
                self._emit(state)
                # The blocked worker cannot observe the flag; closing the
                # handle makes the pending read raise so it can clean up.
                self._invoke_closer(state)

    def _invoke_closer(self, state: TransferState) -> None:
        closer = state.closer
        if not closer:
            return
        # close() on a buffered reader can block behind the read lock held by
        # the stuck worker; run it in a throwaway thread so callers never wedge.
        threading.Thread(target=self._safe_close, args=(closer,), daemon=True).start()

    @staticmethod
    def _safe_close(closer: Callable[[], None]) -> None:
        try:
            closer()
        except Exception:
            pass

    def _emit(self, state: TransferState) -> None:
        for callback in list(state.listeners.values()):
            try:
                callback(state)
            except Exception as exc:
                system_warning(f"[Transfer] Listener error: {exc}")
        self._prune_if_idle(state)

    def _emit_progress(self, state: TransferState) -> None:
        """Throttled emit for per-chunk progress updates."""
        now = time.monotonic()
        if now - state._last_emit < EMIT_INTERVAL:
            return
        state._last_emit = now
        self._emit(state)

    def _prune_if_idle(self, state: TransferState) -> None:
        if state.in_progress:
            return
        if state.listeners:
            return
        # Keep undelivered terminal states so a UI that subscribes after a
        # fast failure still receives the outcome.
        if not state.delivered:
            return
        key = self._key(state.destination)
        with self._transfers_lock:
            if self._transfers.get(key) is state:
                self._transfers.pop(key, None)

    def _finish_success(self, state: TransferState, total: Optional[int] = None) -> None:
        if total is not None:
            state.total_bytes = total
            state.copied_bytes = total
        state.percent = 100
        state.in_progress = False
        self._emit(state)

    def _finish_error(self, state: TransferState, message: str) -> None:
        if state.in_progress:
            state.in_progress = False
            state.error = state.error or message
            self._emit(state)

    def _run_copy(self, state: TransferState) -> None:
        if not state.source:
            self._finish_error(state, "Copy source missing")
            return
        destination = state.destination
        temp_path = f"{destination}.{uuid.uuid4().hex}.tmp"
        lock_path = f"{destination}.charon.lock"
        lock_acquired = False
        try:
            os.makedirs(os.path.dirname(destination) or ".", exist_ok=True)
            total = os.path.getsize(state.source)
            if self._destination_already_delivered(destination, expected_size=total):
                self._finish_success(state, total)
                return
            self._acquire_destination_lock(destination, lock_path)
            lock_acquired = True
            state.total_bytes = total
            copied = 0
            with open(state.source, "rb") as src, open(temp_path, "wb") as dest_fp:
                state.closer = src.close
                while True:
                    chunk = src.read(CHUNK_SIZE)
                    if self._shutdown or state.cancelled:
                        self._finish_error(state, "Transfer cancelled")
                        return
                    if not chunk:
                        break
                    dest_fp.write(chunk)
                    copied += len(chunk)
                    state.copied_bytes = copied
                    state.percent = min(100, int((copied / total) * 100)) if total else 0
                    state.last_activity = time.monotonic()
                    self._touch_lock(lock_path)
                    self._emit_progress(state)
            state.closer = None
            self._publish_temp_file(state, temp_path, destination, copied)
        except Exception as exc:
            message = "Transfer cancelled" if state.cancelled else str(exc)
            if not state.cancelled:
                system_warning(f"[Transfer] Copy failed | dest='{destination}' error='{exc}'")
            self._finish_error(state, message)
        finally:
            state.closer = None
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            if lock_acquired:
                self._release_destination_lock(lock_path)

    def _run_download(self, state: TransferState) -> None:
        destination = state.destination
        temp_path = f"{destination}.{uuid.uuid4().hex}.download"
        lock_path = f"{destination}.charon.lock"
        lock_acquired = False
        try:
            os.makedirs(os.path.dirname(destination) or ".", exist_ok=True)
            if self._destination_already_delivered(destination):
                self._finish_success(state, self._safe_size(destination))
                return
            self._acquire_destination_lock(destination, lock_path)
            lock_acquired = True
            with urllib.request.urlopen(state.url or "", timeout=30) as response:
                state.closer = response.close
                total_header = response.getheader("Content-Length")
                try:
                    total = int(total_header) if total_header else 0
                except (TypeError, ValueError):
                    total = 0
                state.total_bytes = total
                copied = 0
                with open(temp_path, "wb") as dest_fp:
                    while True:
                        chunk = response.read(CHUNK_SIZE)
                        if self._shutdown or state.cancelled:
                            self._finish_error(state, "Transfer cancelled")
                            return
                        if not chunk:
                            break
                        dest_fp.write(chunk)
                        copied += len(chunk)
                        state.copied_bytes = copied
                        state.percent = min(100, int((copied / total) * 100)) if total else 0
                        state.last_activity = time.monotonic()
                        self._touch_lock(lock_path)
                        self._emit_progress(state)
            state.closer = None
            self._publish_temp_file(state, temp_path, destination, copied)
        except Exception as exc:
            message = "Transfer cancelled" if state.cancelled else str(exc)
            if not state.cancelled:
                system_warning(
                    f"[Transfer] Download failed | dest='{destination}' url='{state.url}' error='{exc}'"
                )
            self._finish_error(state, message)
        finally:
            state.closer = None
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            if lock_acquired:
                self._release_destination_lock(lock_path)

    @staticmethod
    def _safe_size(path: str) -> Optional[int]:
        try:
            return os.path.getsize(path)
        except OSError:
            return None

    def _destination_already_delivered(
        self,
        destination: str,
        *,
        expected_size: Optional[int] = None,
    ) -> bool:
        """A destination that already exists was delivered by another session.

        When the expected size is known and differs, this is treated as a
        conflict (raises) rather than silently accepting a different file.
        """
        if not os.path.exists(destination):
            return False
        if expected_size is not None:
            actual = self._safe_size(destination)
            if actual is not None and actual != expected_size:
                raise FileExistsError(
                    f"Destination already exists with a different size: {destination}"
                )
        system_debug(f"[Transfer] Destination already delivered | dest='{destination}'")
        return True

    def _acquire_destination_lock(self, destination: str, lock_path: str) -> None:
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        try:
            fd = os.open(lock_path, flags)
        except FileExistsError as exc:
            if not self._reclaim_stale_lock(lock_path):
                raise RuntimeError(
                    f"Another workstation is already transferring this model: {destination}"
                ) from exc
            fd = os.open(lock_path, flags)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(
                f"pid={os.getpid()} host={socket.gethostname()} started={int(time.time())}\n"
            )

    def _reclaim_stale_lock(self, lock_path: str) -> bool:
        """Remove a lock whose owner stopped refreshing it (crashed session)."""
        try:
            age = time.time() - os.path.getmtime(lock_path)
        except OSError:
            # Lock vanished between the failed open and now.
            return True
        if age <= self.stale_lock_seconds:
            return False
        try:
            os.remove(lock_path)
        except OSError:
            return False
        system_warning(f"[Transfer] Reclaimed stale lock | lock='{lock_path}' age={int(age)}s")
        return True

    @staticmethod
    def _touch_lock(lock_path: str) -> None:
        try:
            os.utime(lock_path, None)
        except OSError:
            pass

    def _publish_temp_file(
        self,
        state: TransferState,
        temp_path: str,
        destination: str,
        copied: int,
    ) -> None:
        if self._destination_already_delivered(destination, expected_size=copied or None):
            self._finish_success(state, self._safe_size(destination))
            return
        os.replace(temp_path, destination)
        self._finish_success(state, copied or state.total_bytes)

    def _release_destination_lock(self, lock_path: str) -> None:
        try:
            if os.path.exists(lock_path):
                os.remove(lock_path)
        except OSError:
            pass


manager = ModelTransferManager.instance()
