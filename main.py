"""Application entry point for Desktop Cleaner."""

from __future__ import annotations

from desktop_tidy.application import DesktopCleanerApplication, ensure_application
from desktop_tidy.services.activation import notify_existing_instance
from desktop_tidy.services.single_instance import SingleInstanceLock


def main() -> int:
    lock = SingleInstanceLock()
    if not lock.acquire():
        notify_existing_instance()
        return 0

    try:
        ensure_application()
        return DesktopCleanerApplication().run()
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
