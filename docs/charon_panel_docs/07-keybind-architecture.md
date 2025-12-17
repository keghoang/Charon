# Keybind Architecture

## Overview
- Charon now ships with **local keybinds only**; the former global hotkey layer has been removed.
- `KeybindManager` coordinates local shortcut registration and host-scoped app settings.
- Local shortcuts use `Qt.WindowShortcut` so they only fire when Charon has focus; the quick search shortcut is promoted to `Qt.ApplicationShortcut` while tiny mode is active so it stays reachable.

## Components
- **KeybindManager** (`keybind_manager.py`): loads local keybind definitions from the database, registers them through the handler, applies host app settings, and updates quick search context when tiny mode toggles.
- **LocalKeybindHandler** (`local_handler.py`): seeds defaults from `config.DEFAULT_LOCAL_KEYBINDS`, reads/writes overrides via `user_settings_db`, and owns the `QShortcut` instances scoped to the main window.
- **Settings UI** (`settings_ui.py`): combines ComfyUI path selection, host settings, and a single “Charon Keybinds” tab for editing local shortcuts. The former global keybind tab has been retired.

## Data Storage
- Local keybind overrides live in the `local_keybind_settings` table managed by `charon.settings.user_settings_db`; missing entries are auto-filled from `config.DEFAULT_LOCAL_KEYBINDS`.
- Application settings (e.g., always-on-top, debug logging) are stored per host using the definitions in `config.APP_SETTING_DEFINITIONS`.

## Tiny Mode Context
- When tiny mode is enabled, `KeybindManager` flips the quick search shortcut to `Qt.ApplicationShortcut` so it remains usable even when the Charon window is not focused. When returning to normal mode, the shortcut is returned to `Qt.WindowShortcut`.
