"""Launch files, folders, and shortcuts using the OS default handler."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlparse


def open_item(path: str | Path) -> None:
    """Open a file, folder, or .lnk shortcut with the OS default application.

    Uses os.startfile on Windows; falls back to QDesktopServices elsewhere.
    Does not move, copy, delete, or mutate source files.
    """
    resolved = Path(path).resolve()
    if sys.platform == "win32":
        os.startfile(str(resolved))
    else:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(resolved)))


def open_url(url: str) -> None:
    """Open a web URL with the OS default browser."""

    value = str(url).strip()
    if not value:
        raise ValueError("url is empty")
    parsed = urlparse(value)
    if not parsed.scheme:
        value = f"https://{value}"
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices

    if not QDesktopServices.openUrl(QUrl(value)):
        raise RuntimeError(f"failed to open url: {value}")
