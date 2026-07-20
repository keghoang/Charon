"""Persistence boundary for converted ComfyUI prompts stored on Charon nodes."""

from __future__ import annotations

import os
from typing import Callable, Tuple


def prompt_path_matches_hash(path_value: str, hash_value: str) -> bool:
    if not path_value or not hash_value:
        return False
    try:
        basename = os.path.basename(str(path_value)).lower()
    except Exception:
        return False
    prefix = str(hash_value)[:8].lower()
    return bool(prefix) and prefix in basename


class PromptCacheRepository:
    """Read and write a node's converted-prompt path and workflow hash."""

    def __init__(
        self,
        node,
        nuke_module,
        *,
        write_metadata: Callable[[str, str], bool],
        run_on_main_thread: Callable,
        log_debug: Callable[[str], None],
    ) -> None:
        self._node = node
        self._nuke = nuke_module
        self._write_metadata = write_metadata
        self._run_on_main_thread = run_on_main_thread
        self._log_debug = log_debug

    def _read_hash_knob(self) -> str:
        try:
            knob = self._node.knob("charon_prompt_hash")
            if knob is not None:
                return str(knob.value()).strip()
        except Exception:
            pass
        return ""

    def _ensure_hash_knob(self):
        try:
            knob = self._node.knob("charon_prompt_hash")
        except Exception:
            knob = None
        if knob is not None:
            return knob
        try:
            knob = self._nuke.String_Knob("charon_prompt_hash", "Prompt Hash", "")
            knob.setFlag(self._nuke.NO_ANIMATION | self._nuke.INVISIBLE)
            self._node.addKnob(knob)
        except Exception:
            return None
        return knob

    def load(self) -> Tuple[str, str]:
        path_value = ""
        try:
            knob = self._node.knob("charon_prompt_path")
            if knob is not None:
                path_value = str(knob.value()).strip()
        except Exception:
            pass

        hash_value = self._read_hash_knob()
        try:
            metadata_value = self._node.metadata("charon/prompt_hash")
            metadata_hash = str(metadata_value).strip() if metadata_value is not None else ""
            if metadata_hash and not hash_value:
                hash_value = metadata_hash
        except Exception:
            # A host without readable metadata must retain the knob fallback.
            pass
        return path_value, hash_value

    def store(self, path_value: str, hash_value: str) -> None:
        def _store() -> None:
            normalized_path = path_value.replace("\\", "/") if isinstance(path_value, str) else ""
            try:
                knob = self._node.knob("charon_prompt_path")
                if knob is not None:
                    knob.setValue(normalized_path)
            except Exception:
                pass

            normalized_hash = str(hash_value or "")
            hash_knob = self._ensure_hash_knob()
            if hash_knob is not None:
                try:
                    hash_knob.setValue(normalized_hash)
                except Exception:
                    pass
            self._write_metadata("charon/prompt_hash", normalized_hash)
            if hash_value:
                self._log_debug(f"Stored prompt cache hash {hash_value}")
            if normalized_path:
                self._log_debug(f"Stored prompt cache path {normalized_path}")

        self._run_on_main_thread(_store)
