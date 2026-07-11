from __future__ import annotations

import ast
import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon

from desktop_tidy.application import ensure_application
from desktop_tidy.ui.app_icons import (
    application_icon,
    application_icon_path,
    apply_application_icon,
    tray_icon,
    tray_icon_path,
)
from desktop_tidy.ui.tray import TrayController


class AppIconTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_icon_assets_exist_at_expected_paths(self) -> None:
        self.assertEqual(application_icon_path().as_posix().split("/")[-3:], ["assets", "icons", "app.ico"])
        self.assertEqual(tray_icon_path().as_posix().split("/")[-3:], ["assets", "icons", "tray.ico"])
        self.assertTrue(application_icon_path().is_file())
        self.assertTrue(tray_icon_path().is_file())

    def test_qt_icons_load_from_assets(self) -> None:
        app_icon = application_icon()
        small_icon = tray_icon()

        self.assertFalse(app_icon.isNull())
        self.assertFalse(small_icon.isNull())
        self.assertEqual(
            [size.width() for size in app_icon.availableSizes()],
            [16, 24, 32, 48, 64, 128, 256],
        )
        self.assertEqual(
            [size.width() for size in small_icon.availableSizes()],
            [16, 20, 24, 32, 48],
        )

    def test_application_window_icon_is_applied(self) -> None:
        app = ensure_application([])
        app.setWindowIcon(QIcon())

        apply_application_icon(app)

        self.assertFalse(app.windowIcon().isNull())

    def test_tray_uses_custom_tray_icon_asset(self) -> None:
        tray = TrayController(auto_show=False)

        self.assertEqual(tray.icon_path(), tray_icon_path())
        self.assertFalse(tray.icon().isNull())

    def test_pyinstaller_build_includes_icon_assets(self) -> None:
        spec_tree = ast.parse(
            Path("DesktopCleaner.spec").read_text(encoding="utf-8"),
            filename="DesktopCleaner.spec",
        )
        options_by_call: dict[str, dict[str, object]] = {}
        for statement in spec_tree.body:
            if not isinstance(statement, ast.Assign):
                continue
            call = statement.value
            if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name):
                continue
            options_by_call[call.func.id] = {
                keyword.arg: ast.literal_eval(keyword.value)
                for keyword in call.keywords
                if keyword.arg is not None
            }

        self.assertIn(
            (r"assets\icons", r"assets\icons"),
            options_by_call["Analysis"]["datas"],
        )
        self.assertIn(
            r"assets\icons\app.ico",
            options_by_call["EXE"]["icon"],
        )


if __name__ == "__main__":
    unittest.main()
