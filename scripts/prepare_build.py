"""Build-time guard for DesktopCleaner executable replacement.

The guard restores Explorer desktop icons before terminating running
DesktopCleaner instances, so a forced build-time shutdown cannot leave the
desktop icon list hidden.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from desktop_tidy.application import application_store
from desktop_tidy.persistence.config_store import ConfigurationStore
from desktop_tidy.services.desktop_takeover import DesktopTakeoverService
from desktop_tidy.services.logging_setup import configure_logging, get_logger, log_exception


class BuildGuardError(RuntimeError):
    """Raised when the build guard cannot leave the desktop in a safe state."""


def _log_exception_if_configured(context: str, exc: BaseException) -> None:
    if get_logger().handlers:
        log_exception(context, exc)


def stop_running_desktop_cleaner(runner=subprocess.run) -> None:
    """Terminate running DesktopCleaner.exe instances after state recovery."""
    if sys.platform != "win32":
        return
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        "Get-Process -Name DesktopCleaner -ErrorAction SilentlyContinue | "
        "Stop-Process -Force",
    ]
    result = runner(command, capture_output=True, text=True)
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        if not message:
            return
        raise BuildGuardError(f"failed to stop running DesktopCleaner.exe: {message}")


def run_guard(
    *,
    store: ConfigurationStore | None = None,
    takeover: DesktopTakeoverService | None = None,
    stop_processes: Callable[[], None] | None = None,
) -> None:
    config_store = store or application_store()
    takeover_service = takeover or DesktopTakeoverService()
    stopper = stop_processes or stop_running_desktop_cleaner
    store_path = getattr(config_store, "path", None)
    if store_path is not None:
        try:
            configure_logging(store_path.parent)
        except OSError:
            pass

    config = None
    restore_required = True
    try:
        config = config_store.load()
        restore_required = (
            config.desktop.restore_required or config.desktop.explorer_icons_hidden
        )
    except Exception as exc:
        _log_exception_if_configured("prepare build load config", exc)
        print("[guard] Could not read DesktopCleaner config; restoring icons defensively.")

    try:
        restored = takeover_service.restore_explorer_icons()
    except Exception as exc:
        _log_exception_if_configured("prepare build restore desktop icons", exc)
        restored = False
    print(f"[guard] Restore Explorer desktop icons: {'ok' if restored else 'not-needed-or-failed'}")
    if restore_required and not restored:
        raise BuildGuardError(
            "Explorer desktop icons may still be hidden; build stopped before killing "
            "DesktopCleaner.exe."
        )

    if restored and config is not None and restore_required:
        config.desktop.restore_required = False
        config.desktop.explorer_icons_hidden = False
        config_store.save(config)
        print("[guard] Cleared DesktopCleaner recovery flags.")

    stopper()
    print("[guard] Running DesktopCleaner.exe instances stopped.")


def main() -> int:
    try:
        run_guard()
    except BuildGuardError as exc:
        print(f"[guard] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
