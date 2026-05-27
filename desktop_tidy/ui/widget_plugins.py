"""Built-in safe widget panels for non-file content."""

from __future__ import annotations

from typing import Protocol

from PySide6.QtCore import QDateTime, QTimer, Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class WidgetPlugin(Protocol):
    id: str
    display_name: str

    def default_settings(self) -> dict[str, object]:
        ...

    def create_widget(self, settings: dict[str, object]) -> QWidget:
        ...


class ClockWidget(QWidget):
    def __init__(self, settings: dict[str, object], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = dict(settings)
        self._time_label = QLabel(self)
        self._date_label = QLabel(self)
        self._time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._date_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._time_label.setStyleSheet("color: white; font-size: 42px; font-weight: 600;")
        self._date_label.setStyleSheet("color: rgba(255,255,255,0.82); font-size: 15px;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.addStretch(1)
        layout.addWidget(self._time_label)
        layout.addWidget(self._date_label)
        layout.addStretch(1)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(1000)
        self._refresh()

    def _refresh(self) -> None:
        now = QDateTime.currentDateTime()
        use_24h = bool(self._settings.get("hour_24", True))
        self._time_label.setText(now.toString("HH:mm" if use_24h else "h:mm AP"))
        self._date_label.setText(now.toString("yyyy-MM-dd dddd"))


class ClockWidgetPlugin:
    id = "clock"
    display_name = "时间"

    def default_settings(self) -> dict[str, object]:
        return {"hour_24": True}

    def create_widget(self, settings: dict[str, object]) -> QWidget:
        merged = self.default_settings()
        merged.update(settings)
        return ClockWidget(merged)


class UnknownWidgetPlugin:
    def __init__(self, widget_type: str) -> None:
        self.id = widget_type
        self.display_name = "未知功能"

    def default_settings(self) -> dict[str, object]:
        return {}

    def create_widget(self, settings: dict[str, object]) -> QWidget:
        widget = QWidget()
        label = QLabel(f"未知功能面板：{self.id}", widget)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("color: rgba(255,255,255,0.86);")
        layout = QVBoxLayout(widget)
        layout.addWidget(label)
        return widget


class BuiltinWidgetRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, WidgetPlugin] = {
            ClockWidgetPlugin.id: ClockWidgetPlugin(),
        }

    def get(self, widget_type: str) -> WidgetPlugin:
        return self._plugins.get(widget_type) or UnknownWidgetPlugin(widget_type)

    def available(self) -> list[WidgetPlugin]:
        return list(self._plugins.values())
