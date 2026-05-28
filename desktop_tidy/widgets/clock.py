"""Clock function panel."""

from __future__ import annotations

from PySide6.QtCore import QDateTime, QTimer, Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from desktop_tidy.widgets.models import WidgetDefinition


class ClockWidget(QWidget):
    def __init__(self, settings: dict[str, object], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = dict(settings)
        self.setMinimumSize(260, 130)
        self.setMaximumSize(340, 190)
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
    display_name = "时间面板"

    def definition(self) -> WidgetDefinition:
        return WidgetDefinition(
            id=self.id,
            display_name=self.display_name,
            description="显示本地时间和日期",
            preview_title="12:34",
            preview_body="2026-05-28",
            accent_color="#d99abd",
        )

    def default_settings(self) -> dict[str, object]:
        return {"hour_24": True}

    def create_widget(self, settings: dict[str, object]) -> QWidget:
        merged = self.default_settings()
        merged.update(settings)
        return ClockWidget(merged)
