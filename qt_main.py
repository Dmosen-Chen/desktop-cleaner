"""Development entry point for the Qt desktop panel preview."""

from __future__ import annotations

from desktop_tidy.application import PreviewApplication, ensure_application


def main() -> int:
    ensure_application()
    return PreviewApplication().run()


if __name__ == "__main__":
    raise SystemExit(main())
