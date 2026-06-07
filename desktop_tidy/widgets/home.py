"""Home dashboard widget for the global main tab."""

from __future__ import annotations

from PySide6.QtCore import QDateTime, Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QVBoxLayout, QWidget

from desktop_tidy.widgets.models import WidgetDefinition, WidgetVisualPreset

HOME_VISUAL = WidgetVisualPreset(
    preset_id="home-dashboard",
    accent_color="#d99abd",
    background="#17141d",
    foreground="#f8fafc",
    secondary_foreground="rgba(248,250,252,0.72)",
    card_background="rgba(31,35,45,0.92)",
    recommended_width=920,
    recommended_height=560,
    min_width=640,
    min_height=420,
    max_width=1600,
    max_height=1000,
)


class HomeDashboardWidget(QWidget):
    MODULES = (
        ("时间", "当前时间和日期"),
        ("最近使用", "常用入口占位"),
        ("日程提醒", "今日提醒占位"),
        ("网络收藏", "网页入口占位"),
        ("日历", "本月概览占位"),
        ("天气", "天气状态占位"),
    )

    def __init__(self, settings: dict[str, object], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = dict(settings)
        self.setObjectName("HomeDashboardWidgetRoot")
        self.setMinimumSize(HOME_VISUAL.min_width, HOME_VISUAL.min_height)
        self.setMaximumSize(HOME_VISUAL.max_width, HOME_VISUAL.max_height)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(18)

        title = QLabel("主标签页", self)
        title.setObjectName("HomeDashboardTitle")
        title.setStyleSheet(
            f"color: {HOME_VISUAL.foreground}; font-size: 24px; font-weight: 700;"
        )
        layout.addWidget(title)

        now = QDateTime.currentDateTime()
        time_label = QLabel(now.toString("HH:mm  ·  yyyy-MM-dd dddd"), self)
        time_label.setStyleSheet(
            f"color: {HOME_VISUAL.secondary_foreground}; font-size: 15px;"
        )
        layout.addWidget(time_label)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)
        layout.addLayout(grid, 1)

        for index, (name, description) in enumerate(self.MODULES):
            card = self._module_card(name, description)
            grid.addWidget(card, index // 3, index % 3)

    def _module_card(self, title: str, description: str) -> QFrame:
        card = QFrame(self)
        card.setObjectName(f"HomeModuleCard-{title}")
        card.setStyleSheet(
            "QFrame {"
            f"background: {HOME_VISUAL.card_background};"
            "border: 1px solid rgba(255,255,255,0.10);"
            "border-radius: 14px;"
            "}"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)

        name_label = QLabel(title, card)
        name_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        name_label.setStyleSheet(
            f"color: {HOME_VISUAL.foreground}; font-size: 17px; font-weight: 650;"
        )
        description_label = QLabel(description, card)
        description_label.setWordWrap(True)
        description_label.setStyleSheet(
            f"color: {HOME_VISUAL.secondary_foreground}; font-size: 13px;"
        )
        layout.addWidget(name_label)
        layout.addWidget(description_label)
        layout.addStretch(1)
        return card


class HomeWidgetPlugin:
    id = "home"
    display_name = "主标签页"

    def definition(self) -> WidgetDefinition:
        return WidgetDefinition(
            id=self.id,
            display_name=self.display_name,
            description="桌面控制台首页，用于承载时间、最近使用、日程、收藏、日历和天气模块。",
            preview_title="主标签页",
            preview_body="时间 · 最近使用 · 日历 · 天气",
            visual=HOME_VISUAL,
        )

    def default_settings(self) -> dict[str, object]:
        return {"modules": [name for name, _description in HomeDashboardWidget.MODULES]}

    def create_widget(self, settings: dict[str, object]) -> QWidget:
        merged = self.default_settings()
        merged.update(settings)
        return HomeDashboardWidget(merged)
