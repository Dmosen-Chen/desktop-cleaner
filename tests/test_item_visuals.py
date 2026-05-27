from __future__ import annotations

import os
import sys
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication

from desktop_tidy.services.item_visuals import ItemVisualProvider, WindowsShellIconProvider


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

    def test_windows_shortcut_icon_failure_still_tries_shell_icon(self) -> None:
        class RecoveringShellProvider(WindowsShellIconProvider):
            def __init__(self) -> None:
                super().__init__(platform_name="win32")
                self.calls: list[str] = []

            def _shortcut_icon(self, path: Path, size: int) -> QIcon | None:
                self.calls.append("shortcut")
                raise RuntimeError("shortcut target icon denied")

            def _shell_icon(self, path: Path, size: int) -> QIcon | None:
                self.calls.append("shell")
                return sample_icon()

        provider = RecoveringShellProvider()

        with patch("desktop_tidy.services.item_visuals.log_exception") as log_exception:
            icon = provider.icon_for(Path("Game.lnk"))

        self.assertFalse(icon.isNull())
        self.assertEqual(provider.calls, ["shortcut", "shell"])
        log_exception.assert_called_once()

    def test_windows_shell_icon_unwraps_pywin32_result_tuple(self) -> None:
        class RecordingShellProvider(WindowsShellIconProvider):
            def __init__(self) -> None:
                super().__init__(platform_name="win32")
                self.handles: list[int] = []

            def _icon_from_hicon(self, hicon: int, size: int) -> QIcon | None:
                self.handles.append(hicon)
                return sample_icon()

        shell_module = types.SimpleNamespace(
            SHGetFileInfo=lambda path, attributes, flags: (
                1,
                (24680, 402, 0, "", ""),
            )
        )
        destroyed: list[int] = []
        gui_module = types.SimpleNamespace(DestroyIcon=lambda handle: destroyed.append(handle))
        module_map = {
            "win32com": types.ModuleType("win32com"),
            "win32com.shell": types.ModuleType("win32com.shell"),
            "win32com.shell.shell": shell_module,
            "win32gui": gui_module,
        }
        provider = RecordingShellProvider()

        with patch.dict(sys.modules, module_map):
            icon = provider._shell_icon(Path("Game.lnk"), 64)

        self.assertIsNotNone(icon)
        self.assertFalse(icon.isNull())
        self.assertEqual(provider.handles, [24680])
        self.assertEqual(destroyed, [24680])

    def test_shortcut_candidate_icon_failures_are_quiet_best_effort(self) -> None:
        class DeniedShortcutProvider(WindowsShellIconProvider):
            def __init__(self) -> None:
                super().__init__(platform_name="win32")
                self.candidates: list[tuple[str, int]] = []

            def _extract_icon(self, path: Path, index: int, size: int) -> QIcon | None:
                self.candidates.append((str(path), index))
                raise PermissionError("denied")

        class FakeShortcut:
            IconLocation = "C:/blocked/icon.ico,2"
            TargetPath = "C:/blocked/app.exe"

        class FakeWScriptShell:
            def CreateShortcut(self, path: str) -> FakeShortcut:
                return FakeShortcut()

        client_module = types.SimpleNamespace(
            Dispatch=lambda name: FakeWScriptShell()
        )
        win32com_module = types.ModuleType("win32com")
        win32com_module.client = client_module
        module_map = {
            "win32com": win32com_module,
            "win32com.client": client_module,
        }
        provider = DeniedShortcutProvider()

        with patch.dict(sys.modules, module_map), patch(
            "desktop_tidy.services.item_visuals.log_exception"
        ) as log_exception:
            icon = provider._shortcut_icon(Path("Game.lnk"), 64)

        self.assertIsNone(icon)
        self.assertEqual(
            provider.candidates,
            [(str(Path("C:/blocked/icon.ico")), 2), (str(Path("C:/blocked/app.exe")), 0)],
        )
        log_exception.assert_not_called()


if __name__ == "__main__":
    unittest.main()
