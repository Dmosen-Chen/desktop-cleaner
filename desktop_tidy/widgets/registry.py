"""Registry for built-in function panels."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from desktop_tidy.widgets.clock import ClockWidgetPlugin
from desktop_tidy.widgets.models import WidgetDefinition, WidgetPlugin


class UnknownWidgetPlugin:
    def __init__(self, widget_type: str) -> None:
        self.id = widget_type
        self.display_name = "未知功能"

    def definition(self) -> WidgetDefinition:
        return WidgetDefinition(
            id=self.id,
            display_name=self.display_name,
            description="此功能面板当前不可用",
            preview_title="未知",
            preview_body=self.id,
            accent_color="#6b7280",
        )

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

    def available(self) -> list[WidgetDefinition]:
        return [plugin.definition() for plugin in self._plugins.values()]
