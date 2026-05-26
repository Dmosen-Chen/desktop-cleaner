"""Read-only desktop item icons for the Qt preview grid."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QFileInfo, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QFileIconProvider

IMAGE_EXTENSIONS = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".bmp",
        ".tif",
        ".tiff",
        ".svg",
    }
)


class ItemVisualProvider:
    """Loads native or thumbnail icons without mutating source files."""

    def __init__(self) -> None:
        self.icons = QFileIconProvider()

    def icon_for(self, path: Path) -> QIcon:
        if path.suffix.casefold() in IMAGE_EXTENSIONS:
            pixmap = QPixmap(str(path)).scaled(
                64,
                64,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            if not pixmap.isNull():
                return QIcon(pixmap)
        return self.icons.icon(QFileInfo(str(path)))
