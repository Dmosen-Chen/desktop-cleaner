"""System tray controller for the desktop cleaner application."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu, QStyle, QSystemTrayIcon


class TrayController(QObject):
    show_panels_requested = Signal()
    hide_panels_requested = Signal()
    settings_requested = Signal()
    restore_desktop_requested = Signal()
    quit_requested = Signal()

    def __init__(self, *, auto_show: bool = True, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._menu = QMenu()
        self._actions: dict[str, QAction] = {}
        self._add_action("show", "显示面板", self.show_panels_requested)
        self._add_action("hide", "隐藏面板", self.hide_panels_requested)
        self._add_action("settings", "设置", self.settings_requested)
        self._add_action("restore", "恢复桌面图标", self.restore_desktop_requested)
        self._add_action("quit", "退出", self.quit_requested)

        self._tray = QSystemTrayIcon(self)
        self._tray.setToolTip("Desktop Cleaner")
        self._tray.setContextMenu(self._menu)
        self._tray.activated.connect(self._on_activated)
        icon = QApplication.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        self._tray.setIcon(icon)
        if auto_show and QSystemTrayIcon.isSystemTrayAvailable():
            self.show()

    def show(self) -> None:
        self._tray.show()

    def hide(self) -> None:
        self._tray.hide()

    def show_message(self, title: str, message: str) -> None:
        self._tray.showMessage(title, message)

    def action_texts(self) -> list[str]:
        return [action.text() for action in self._actions.values()]

    def trigger_action(self, action_id: str) -> None:
        self._actions[action_id].trigger()

    def _add_action(self, action_id: str, text: str, signal: Signal) -> None:
        action = QAction(text, self)
        action.triggered.connect(signal.emit)
        self._menu.addAction(action)
        self._actions[action_id] = action

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_panels_requested.emit()
