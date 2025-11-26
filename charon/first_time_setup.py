from __future__ import annotations

from . import preferences
from .charon_logger import system_error, system_info
from .dependency_check import PREF_DEPENDENCIES_VERIFIED
from .qt_compat import QtWidgets

FIRST_TIME_SETUP_KEY = "first_time_setup_complete"
FORCE_FIRST_TIME_SETUP_KEY = "force_first_time_setup"


def is_force_first_time_setup_enabled() -> bool:
    return bool(preferences.get_preference(FORCE_FIRST_TIME_SETUP_KEY, False))


def set_force_first_time_setup(enabled: bool) -> None:
    preferences.set_preference(FORCE_FIRST_TIME_SETUP_KEY, bool(enabled))
    if enabled:
        system_info("First-time setup will be forced on next launch.")


def is_first_time_setup_complete() -> bool:
    if is_force_first_time_setup_enabled():
        return False
    return bool(preferences.get_preference(FIRST_TIME_SETUP_KEY, False))


def mark_first_time_setup_complete() -> None:
    preferences.set_preference(FIRST_TIME_SETUP_KEY, True)
    preferences.set_preference(FORCE_FIRST_TIME_SETUP_KEY, False)
    if not preferences.get_preference(PREF_DEPENDENCIES_VERIFIED, False):
        preferences.set_preference(PREF_DEPENDENCIES_VERIFIED, True)


def force_first_time_setup_next_run() -> None:
    set_force_first_time_setup(True)


def run_first_time_setup_if_needed(parent=None) -> bool:
    force_flag = is_force_first_time_setup_enabled()
    if not force_flag and is_first_time_setup_complete():
        return True

    try:
        from .ui.first_time_setup_dialog import FirstTimeSetupDialog
    except Exception as exc:
        system_error(f"Could not load first-time setup dialog: {exc}")
        return False

    dialog = FirstTimeSetupDialog(parent)
    result = dialog.exec()

    if result == QtWidgets.QDialog.Accepted and dialog.setup_completed:
        mark_first_time_setup_complete()
        system_info("First-time setup completed and recorded.")
        return True

    system_info("First-time setup canceled or incomplete.")
    return False
