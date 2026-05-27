from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication

from desktop_tidy.ui.tray import TrayController


class TrayControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_menu_contains_fixed_application_actions(self) -> None:
        tray = TrayController(auto_show=False)

        self.assertEqual(
            tray.action_texts(),
            ["显示面板", "隐藏面板", "设置", "恢复桌面图标", "退出"],
        )

    def test_actions_emit_application_requests(self) -> None:
        tray = TrayController(auto_show=False)
        show_spy = QSignalSpy(tray.show_panels_requested)
        hide_spy = QSignalSpy(tray.hide_panels_requested)
        settings_spy = QSignalSpy(tray.settings_requested)
        restore_spy = QSignalSpy(tray.restore_desktop_requested)
        quit_spy = QSignalSpy(tray.quit_requested)

        for action_id in ("show", "hide", "settings", "restore", "quit"):
            tray.trigger_action(action_id)

        self.assertEqual(show_spy.count(), 1)
        self.assertEqual(hide_spy.count(), 1)
        self.assertEqual(settings_spy.count(), 1)
        self.assertEqual(restore_spy.count(), 1)
        self.assertEqual(quit_spy.count(), 1)


if __name__ == "__main__":
    unittest.main()
