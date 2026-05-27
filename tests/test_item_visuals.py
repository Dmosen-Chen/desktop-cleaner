from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication

from desktop_tidy.services.item_visuals import ItemVisualProvider


def sample_icon() -> QIcon:
    pixmap = QPixmap(16, 16)
    pixmap.fill()
    return QIcon(pixmap)


class FakeShellIconProvider:
    def __init__(self, result: QIcon | None) -> None:
        self.result = result
        self.calls: list[Path] = []

    def icon_for(self, path: Path, size: int) -> QIcon | None:
        self.calls.append(path)
        return self.result


class ItemVisualProviderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_shortcut_icons_use_shell_provider_before_qt_provider(self) -> None:
        shell = FakeShellIconProvider(sample_icon())
        with TemporaryDirectory() as tmp:
            shortcut = Path(tmp) / "Game.lnk"
            shortcut.write_text("shortcut", encoding="utf-8")
            provider = ItemVisualProvider(shell_provider=shell)

            icon = provider.icon_for(shortcut)

            self.assertFalse(icon.isNull())
            self.assertEqual(shell.calls, [shortcut])

    def test_missing_shell_icon_uses_non_blank_fallback(self) -> None:
        shell = FakeShellIconProvider(None)
        with TemporaryDirectory() as tmp:
            shortcut = Path(tmp) / "Broken.url"
            shortcut.write_text("[InternetShortcut]\nURL=https://example.com\n", encoding="utf-8")
            provider = ItemVisualProvider(shell_provider=shell)

            icon = provider.icon_for(shortcut)

            self.assertFalse(icon.isNull())


if __name__ == "__main__":
    unittest.main()
