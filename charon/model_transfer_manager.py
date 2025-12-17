from __future__ import annotations

import os
import threading
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Optional

from .charon_logger import system_debug, system_warning


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
    error: Optional[str] = None
    resolve_method: Optional[str] = None
    workflow_value: Optional[str] = None
    destination_display: Optional[str] = None
    file_name: Optional[str] = None
    listeners: Dict[int, Callable[["TransferState"], None]] = field(default_factory=dict)
    thread: Optional[threading.Thread] = None


class ModelTransferManager:
    """Singleton manager for model copies/downloads that survives dialog lifetime."""

    _instance: Optional["ModelTransferManager"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._transfers: Dict[str, TransferState] = {}
        self._shutdown = False

    @classmethod
    def instance(cls) -> "ModelTransferManager":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------ Public API
    def active_states(self) -> Dict[str, TransferState]:
        return dict(self._transfers)

    def subscribe(self, destination: str, listener_id: int, callback: Callable[[TransferState], None]) -> Optional[TransferState]:
        key = self._key(destination)
        state = self._transfers.get(key)
        if state:
            state.listeners[listener_id] = callback
            callback(state)
        return state

    def unsubscribe(self, destination: str, listener_id: int) -> None:
        key = self._key(destination)
        state = self._transfers.get(key)
        if state:
            state.listeners.pop(listener_id, None)
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
        for state in list(self._transfers.values()):
            thread = state.thread
            if thread and thread.is_alive():
                try:
                    thread.join(timeout=1.0)
                except Exception:
                    pass
        self._transfers.clear()

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
        if self._shutdown:
            state = TransferState(
                kind=kind,
                destination=destination,
                url=url,
                source=source,
                resolve_method=resolve_method,
                workflow_value=workflow_value,
                destination_display=destination_display,
                file_name=file_name,
                in_progress=False,
                error="Transfer manager shutting down",
            )
            return state
        key = self._key(destination)
        state = self._transfers.get(key)
        if state and state.in_progress:
            system_debug(f"[Transfer] Reusing in-progress transfer | dest='{destination}' kind='{state.kind}'")
            return state

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
        self._transfers[key] = state

        worker = self._run_copy if kind == "copy" else self._run_download
        thread = threading.Thread(
            target=worker,
            name=f"ModelTransfer-{Path(destination).name}",
            args=(state,),
            daemon=True,
        )
        state.thread = thread
        thread.start()
        return state

    def _emit(self, state: TransferState) -> None:
        for callback in list(state.listeners.values()):
            try:
                callback(state)
            except Exception as exc:
                system_warning(f"[Transfer] Listener error: {exc}")
        self._prune_if_idle(state)

    def _prune_if_idle(self, state: TransferState) -> None:
        if state.in_progress:
            return
        if state.listeners:
            return
        key = self._key(state.destination)
        self._transfers.pop(key, None)

    def _run_copy(self, state: TransferState) -> None:
        if not state.source:
            state.error = "Copy source missing"
            state.in_progress = False
            self._emit(state)
            return
        destination = state.destination
        temp_path = f"{destination}.tmp"
        try:
            os.makedirs(os.path.dirname(destination) or ".", exist_ok=True)
            total = os.path.getsize(state.source)
            state.total_bytes = total
            copied = 0
            chunk_size = 4 * 1024 * 1024
            with open(state.source, "rb") as src, open(temp_path, "wb") as dest_fp:
                while True:
                    chunk = src.read(chunk_size)
                    if self._shutdown:
                        state.in_progress = False
                        state.error = "Transfer cancelled"
                        self._emit(state)
                        return
                    if not chunk:
                        break
                    dest_fp.write(chunk)
                    copied += len(chunk)
                    state.copied_bytes = copied
                    state.percent = int((copied / total) * 100) if total else 0
                    self._emit(state)
            os.replace(temp_path, destination)
            state.percent = 100
            state.copied_bytes = total
            state.in_progress = False
            self._emit(state)
        except Exception as exc:
            state.in_progress = False
            state.error = str(exc)
            system_warning(f"[Transfer] Copy failed | dest='{destination}' error='{exc}'")
            self._emit(state)
        finally:
            if os.path.exists(temp_path) and state.error:
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    def _run_download(self, state: TransferState) -> None:
        destination = state.destination
        temp_path = f"{destination}.download"
        try:
            with urllib.request.urlopen(state.url or "") as response:
                total_header = response.getheader("Content-Length")
                try:
                    total = int(total_header) if total_header else 0
                except (TypeError, ValueError):
                    total = 0
                state.total_bytes = total
                copied = 0
                chunk_size = 4 * 1024 * 1024
                os.makedirs(os.path.dirname(destination) or ".", exist_ok=True)
                with open(temp_path, "wb") as dest_fp:
                    while True:
                        chunk = response.read(chunk_size)
                        if self._shutdown:
                            state.in_progress = False
                            state.error = "Transfer cancelled"
                            self._emit(state)
                            return
                        if not chunk:
                            break
                        dest_fp.write(chunk)
                        copied += len(chunk)
                        state.copied_bytes = copied
                        state.percent = int((copied / total) * 100) if total else 0
                        self._emit(state)
            os.replace(temp_path, destination)
            state.percent = 100
            state.copied_bytes = state.total_bytes or state.copied_bytes
            state.in_progress = False
            self._emit(state)
        except Exception as exc:
            state.in_progress = False
            state.error = str(exc)
            system_warning(f"[Transfer] Download failed | dest='{destination}' url='{state.url}' error='{exc}'")
            self._emit(state)
        finally:
            if os.path.exists(temp_path) and state.error:
                try:
                    os.remove(temp_path)
                except OSError:
                    pass


manager = ModelTransferManager.instance()
