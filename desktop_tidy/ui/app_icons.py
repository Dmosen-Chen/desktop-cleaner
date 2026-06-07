"""Application icon resources for Desktop Cleaner."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication


def resource_root() -> Path:
    """Return the root for bundled runtime resources."""

    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        return Path(bundle_root)
    return Path(__file__).resolve().parents[2]


def application_icon_path() -> Path:
    return resource_root() / "assets" / "icons" / "app.ico"


def tray_icon_path() -> Path:
    return resource_root() / "assets" / "icons" / "tray.ico"


def application_icon() -> QIcon:
    return QIcon(str(application_icon_path()))


def tray_icon() -> QIcon:
    return QIcon(str(tray_icon_path()))


def apply_application_icon(application: QApplication | None = None) -> None:
    app = application or QApplication.instance()
    if app is None:
        return
    icon = application_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)
