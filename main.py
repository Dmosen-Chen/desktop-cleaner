"""Application entry point for Desktop Cleaner."""

from __future__ import annotations

from desktop_tidy.application import DesktopCleanerApplication, ensure_application


def main() -> int:
    ensure_application()
    return DesktopCleanerApplication().run()


if __name__ == "__main__":
    raise SystemExit(main())
