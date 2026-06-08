"""Home dashboard widget for the global main tab."""

from __future__ import annotations

import calendar
import re
from datetime import date
from typing import Any
from urllib.parse import urlparse

from PySide6.QtCore import QDateTime, QEasingCurve, QPropertyAnimation, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from desktop_tidy.widgets.dashboard_modules import (
    DashboardModuleDefinition,
    DashboardModuleRenderMode,
    default_dashboard_modules,
)
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

_REMINDER_TIME_RE = re.compile(
    r"^\s*(?:(?:\d{4}[-/])?\d{1,2}[-/]\d{1,2}\s+)?"
    r"(?P<hour>[0-2]?\d):(?P<minute>[0-5]\d)\b"
)


def _parse_iso_date(value: object, fallback: date | None = None) -> date:
    if fallback is None:
        fallback = date.today()
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return fallback


def _normalize_bookmark_url(value: object) -> str | None:
    url = str(value).strip()
    if not url:
        return None
    if re.search(r"\s", url):
        return None
    if "://" not in url:
        url = f"https://{url}"
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return url


def _shift_month(value: date, delta: int) -> date:
    month_index = value.year * 12 + value.month - 1 + delta
    year = month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


class HomeDashboardWidget(QWidget):
    """The single Home tab, composed from local dashboard modules."""

    settings_changed = Signal(dict)
    item_open_requested = Signal(str)
    url_open_requested = Signal(str)
    weather_refresh_requested = Signal(str)
    recent_refresh_requested = Signal()
    recent_clear_requested = Signal()

    def __init__(
        self,
        settings: dict[str, object],
        parent: QWidget | None = None,
        *,
        module_definitions: tuple[DashboardModuleDefinition, ...] | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = dict(settings)
        if module_definitions is None:
            module_definitions = default_dashboard_modules()
        self._definitions = {entry.id: entry for entry in module_definitions}
        self._definition_order = [entry.id for entry in module_definitions]
        self._animations: list[QPropertyAnimation] = []
        self._module_widgets: list[QWidget] = []
        self._module_controls: dict[str, tuple[QCheckBox, QPushButton, QPushButton]] = {}
        self._layout_columns = 0
        self._compact_modules = False
        self._dashboard_mode = ""
        self._reduced_motion = bool(self._settings.get("reduced_motion", False))
        self._visible_modules = self._read_visible_modules()

        self.setObjectName("HomeDashboardWidgetRoot")
        self.setProperty("reduced_motion", self._reduced_motion)
        self.setProperty("layout_columns", 0)
        self.setProperty("dashboard_mode", "")
        self.setProperty("compact_modules", False)
        self.setMinimumSize(HOME_VISUAL.min_width, HOME_VISUAL.min_height)
        self.setMaximumSize(HOME_VISUAL.max_width, HOME_VISUAL.max_height)
        self.setStyleSheet(self._style_sheet())

        self._root_layout = QVBoxLayout(self)
        self._root_layout.setContentsMargins(28, 24, 28, 24)
        self._root_layout.setSpacing(16)

        self._hero_time = QLabel(self)
        self._hero_time.setObjectName("HomeHeroTime")
        self._hero_date = QLabel(self)
        self._hero_date.setObjectName("HomeHeroDate")
        self._weather_summary_label = QLabel(self)
        self._weather_summary_label.setProperty("class", "HomeModuleBody")
        self._weather_summary_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._weather_summary_label.setWordWrap(True)
        self._edit_button = QPushButton("编辑首页", self)
        self._edit_button.setObjectName("HomeEditButton")
        self._edit_button.clicked.connect(self._toggle_editor)

        self._root_layout.addWidget(self._build_hero_panel())

        self._module_grid = QGridLayout()
        self._module_grid.setHorizontalSpacing(14)
        self._module_grid.setVerticalSpacing(14)
        self._root_layout.addLayout(self._module_grid, 1)

        self._editor_panel = self._build_editor_panel()
        self._editor_panel.hide()

        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(60_000)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start()
        self._update_clock()
        self._apply_responsive_layout(force=True)
        self._animate_entry()

    def _style_sheet(self) -> str:
        return """
            QWidget#HomeDashboardWidgetRoot {
                background: transparent;
                color: #f8fafc;
                font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
            }
            QFrame#HomeHeroPanel,
            QFrame#HomeModuleEditor,
            QFrame.HomeModuleCard {
                background: rgba(24, 27, 36, 0.90);
                border: 1px solid rgba(255, 255, 255, 0.11);
                border-radius: 18px;
            }
            QFrame#HomeModuleEditor {
                background: rgba(24, 27, 36, 0.96);
                border: 1px solid rgba(217, 154, 189, 0.54);
            }
            QScrollArea#HomeModuleEditorScroll {
                background: transparent;
                border: none;
            }
            QWidget#HomeModuleEditorContent {
                background: transparent;
            }
            QFrame.HomeModuleCard:hover {
                background: rgba(31, 35, 46, 0.96);
                border: 1px solid rgba(217, 154, 189, 0.52);
            }
            QLabel#HomeDashboardTitle {
                color: #f8fafc;
                font-size: 24px;
                font-weight: 700;
            }
            QLabel#HomeHeroTime {
                color: #fff7fb;
                font-size: 48px;
                font-weight: 750;
            }
            QLabel#HomeHeroDate {
                color: rgba(248, 250, 252, 0.78);
                font-size: 15px;
            }
            QLabel.HomeModuleTitle {
                color: #f8fafc;
                font-size: 17px;
                font-weight: 700;
            }
            QLabel.HomeModuleBody {
                color: rgba(248, 250, 252, 0.74);
                font-size: 13px;
            }
            QLabel.HomeModuleItem {
                color: rgba(248, 250, 252, 0.90);
                font-size: 13px;
                padding: 3px 0;
            }
            QLabel.HomeMuted {
                color: rgba(248, 250, 252, 0.58);
                font-size: 13px;
            }
            QCheckBox {
                color: #f8fafc;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
            }
            QLineEdit {
                color: #f8fafc;
                background: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 8px;
                padding: 5px 8px;
                selection-background-color: rgba(217, 154, 189, 0.55);
            }
            QLineEdit:focus {
                border-color: rgba(217, 154, 189, 0.70);
            }
            QPushButton#HomeEditButton,
            QPushButton.HomeEditorButton,
            QPushButton.HomeInlineButton,
            QPushButton.HomeTextButton {
                color: #f8fafc;
                background: rgba(255, 255, 255, 0.10);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 10px;
                padding: 6px 12px;
            }
            QPushButton#HomeEditButton:hover,
            QPushButton.HomeEditorButton:hover,
            QPushButton.HomeInlineButton:hover,
            QPushButton.HomeTextButton:hover {
                background: rgba(217, 154, 189, 0.22);
                border-color: rgba(217, 154, 189, 0.55);
            }
            QPushButton.HomeEditorButton:disabled,
            QPushButton.HomeInlineButton:disabled,
            QPushButton.HomeTextButton:disabled {
                color: rgba(248, 250, 252, 0.32);
                background: rgba(255, 255, 255, 0.06);
            }
            QPushButton.HomeCalendarDay {
                color: rgba(248, 250, 252, 0.82);
                background: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 7px;
                padding: 3px 4px;
                min-width: 28px;
            }
            QPushButton.HomeCalendarDay:hover {
                background: rgba(217, 154, 189, 0.20);
                border-color: rgba(217, 154, 189, 0.42);
            }
            QPushButton.HomeCalendarDay[selected="true"] {
                color: #17141d;
                background: #d99abd;
                border-color: rgba(255, 255, 255, 0.72);
                font-weight: 700;
            }
            QPushButton.HomeCalendarDay[today="true"] {
                border-color: rgba(255, 255, 255, 0.55);
            }
            QPushButton.HomeCalendarDay[has_reminder="true"] {
                color: #fff7fb;
                border-color: rgba(217, 154, 189, 0.70);
            }
        """

    def _build_hero_panel(self) -> QFrame:
        hero = QFrame(self)
        hero.setObjectName("HomeHeroPanel")
        hero.setMaximumHeight(210)
        layout = QHBoxLayout(hero)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(18)

        left = QVBoxLayout()
        title = QLabel("今天", hero)
        title.setObjectName("HomeDashboardTitle")
        left.addWidget(title)
        left.addWidget(self._hero_time)
        left.addWidget(self._hero_date)
        layout.addLayout(left, 1)

        layout.addWidget(self._weather_summary_label)
        layout.addWidget(self._edit_button)
        return hero

    def _build_editor_panel(self) -> QFrame:
        editor = QFrame(self)
        editor.setObjectName("HomeModuleEditor")
        editor.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        outer = QVBoxLayout(editor)
        outer.setContentsMargins(18, 14, 18, 14)
        outer.setSpacing(10)

        scroll = QScrollArea(editor)
        scroll.setObjectName("HomeModuleEditorScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget(editor)
        content.setObjectName("HomeModuleEditorContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        title = QLabel("首页模块", editor)
        title.setProperty("class", "HomeModuleTitle")
        layout.addWidget(title)
        for module_id in self._definition_order:
            definition = self._definitions[module_id]
            row = QHBoxLayout()
            checkbox = QCheckBox(definition.display_name, content)
            checkbox.setObjectName(f"HomeModuleToggle-{module_id}")
            checkbox.setChecked(module_id in self._visible_modules)
            checkbox.toggled.connect(
                lambda checked, mid=module_id: self.set_module_visible(mid, checked)
            )
            up_button = QPushButton("上移", editor)
            down_button = QPushButton("下移", editor)
            up_button.setObjectName(f"HomeModuleUp-{module_id}")
            down_button.setObjectName(f"HomeModuleDown-{module_id}")
            up_button.setProperty("class", "HomeEditorButton")
            down_button.setProperty("class", "HomeEditorButton")
            up_button.clicked.connect(lambda _=False, mid=module_id: self.move_module(mid, -1))
            down_button.clicked.connect(lambda _=False, mid=module_id: self.move_module(mid, 1))
            row.addWidget(checkbox, 1)
            row.addWidget(up_button)
            row.addWidget(down_button)
            layout.addLayout(row)
            self._module_controls[module_id] = (checkbox, up_button, down_button)
        self._add_editor_reminder_section(content, layout)
        self._add_editor_bookmark_section(content, layout)
        self._add_editor_weather_section(content, layout)
        layout.addStretch(1)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        done_button = self._inline_button("完成", editor)
        done_button.setObjectName("HomeEditorDoneButton")
        done_button.clicked.connect(lambda: editor.hide())
        outer.addWidget(done_button, alignment=Qt.AlignmentFlag.AlignRight)
        self._sync_editor_controls()
        return editor

    def _add_editor_section_title(self, layout: QVBoxLayout, text: str, parent: QWidget) -> None:
        label = QLabel(text, parent)
        label.setProperty("class", "HomeModuleItem")
        layout.addWidget(label)

    def _add_editor_reminder_section(self, parent: QWidget, layout: QVBoxLayout) -> None:
        self._add_editor_section_title(layout, "日程提醒", parent)
        row = QHBoxLayout()
        reminder_input = QLineEdit(parent)
        reminder_input.setObjectName("HomeEditorReminderInput")
        reminder_input.setPlaceholderText("例如：18:00 复盘")
        add_button = self._inline_button("添加", parent)
        add_button.setObjectName("HomeEditorReminderAddButton")
        add_button.clicked.connect(lambda: self._add_reminder(reminder_input.text()))
        reminder_input.returnPressed.connect(lambda: self._add_reminder(reminder_input.text()))
        row.addWidget(reminder_input, 1)
        row.addWidget(add_button)
        layout.addLayout(row)

        selected_iso = self._selected_date_iso()
        for entry in self._reminder_entries():
            if entry["date"] != selected_iso:
                continue
            item_row = QHBoxLayout()
            status_text = ""
            if entry["done"]:
                status_text = "已完成"
            label = QLabel(status_text, parent)
            label.setProperty("class", "HomeMuted")
            text_input = QLineEdit(parent)
            text_input.setObjectName(f"HomeEditorReminderText-{entry['raw_index']}")
            text_input.setText(str(entry["text"]))
            text_input.returnPressed.connect(
                lambda i=int(entry["raw_index"]), field=text_input: self._update_reminder(
                    i, field.text()
                )
            )
            save_button = self._inline_button("保存", parent)
            save_button.setObjectName(f"HomeEditorReminderSave-{entry['raw_index']}")
            save_button.clicked.connect(
                lambda _=False, i=int(entry["raw_index"]), field=text_input: self._update_reminder(
                    i, field.text()
                )
            )
            if entry["done"]:
                restore_button = self._inline_button("恢复", parent)
                restore_button.setObjectName(
                    f"HomeEditorReminderRestore-{entry['raw_index']}"
                )
                restore_button.clicked.connect(
                    lambda _=False, i=int(entry["raw_index"]): self._restore_reminder(i)
                )
            else:
                restore_button = self._inline_button("完成", parent)
                restore_button.setObjectName(
                    f"HomeEditorReminderDone-{entry['raw_index']}"
                )
                restore_button.clicked.connect(
                    lambda _=False, i=int(entry["raw_index"]): self._complete_reminder(i)
                )
            delete_button = self._inline_button("删除", parent)
            delete_button.setObjectName(f"HomeEditorReminderDelete-{entry['raw_index']}")
            delete_button.clicked.connect(
                lambda _=False, i=int(entry["raw_index"]): self._delete_reminder(i)
            )
            item_row.addWidget(label)
            item_row.addWidget(text_input, 1)
            item_row.addWidget(save_button)
            item_row.addWidget(restore_button)
            item_row.addWidget(delete_button)
            layout.addLayout(item_row)

    def _add_editor_bookmark_section(self, parent: QWidget, layout: QVBoxLayout) -> None:
        self._add_editor_section_title(layout, "网络收藏", parent)
        title_input = QLineEdit(parent)
        title_input.setObjectName("HomeEditorBookmarkTitleInput")
        title_input.setPlaceholderText("名称")
        url_input = QLineEdit(parent)
        url_input.setObjectName("HomeEditorBookmarkUrlInput")
        url_input.setPlaceholderText("https://example.com")
        add_button = self._inline_button("添加", parent)
        add_button.setObjectName("HomeEditorBookmarkAddButton")
        add_button.clicked.connect(
            lambda: self._add_bookmark(title_input.text(), url_input.text())
        )
        url_input.returnPressed.connect(
            lambda: self._add_bookmark(title_input.text(), url_input.text())
        )
        layout.addWidget(title_input)
        input_row = QHBoxLayout()
        input_row.addWidget(url_input, 1)
        input_row.addWidget(add_button)
        layout.addLayout(input_row)

        bookmarks = [
            entry
            for entry in self._module_list_setting("bookmarks", "bookmarks")
            if isinstance(entry, dict)
        ]
        for index, bookmark in enumerate(bookmarks):
            title = str(bookmark.get("title") or bookmark.get("url") or "").strip()
            url = str(bookmark.get("url") or "").strip()
            if not title:
                continue
            item_row = QHBoxLayout()
            title_edit = QLineEdit(parent)
            title_edit.setObjectName(f"HomeEditorBookmarkTitle-{index}")
            title_edit.setText(title)
            url_edit = QLineEdit(parent)
            url_edit.setObjectName(f"HomeEditorBookmarkUrl-{index}")
            url_edit.setText(url)
            save_button = self._inline_button("保存", parent)
            save_button.setObjectName(f"HomeEditorBookmarkSave-{index}")
            delete_button = self._inline_button("删除", parent)
            delete_button.setObjectName(f"HomeEditorBookmarkDelete-{index}")
            save_button.clicked.connect(
                lambda _=False, i=index, title_field=title_edit, url_field=url_edit: self._update_bookmark(
                    i, title_field.text(), url_field.text()
                )
            )
            url_edit.returnPressed.connect(
                lambda i=index, title_field=title_edit, url_field=url_edit: self._update_bookmark(
                    i, title_field.text(), url_field.text()
                )
            )
            delete_button.clicked.connect(lambda _=False, i=index: self._delete_bookmark(i))
            item_row.addWidget(title_edit, 2)
            item_row.addWidget(url_edit, 3)
            item_row.addWidget(save_button)
            item_row.addWidget(delete_button)
            layout.addLayout(item_row)

    def _add_editor_weather_section(self, parent: QWidget, layout: QVBoxLayout) -> None:
        self._add_editor_section_title(layout, "天气", parent)
        weather = self._module_dict_setting("weather", "weather")
        city = str(weather.get("city") or "").strip()
        summary = str(weather.get("summary") or "").strip()
        city_input = QLineEdit(parent)
        city_input.setObjectName("HomeEditorWeatherCityInput")
        city_input.setPlaceholderText("城市")
        city_input.setText(city)
        summary_input = QLineEdit(parent)
        summary_input.setObjectName("HomeEditorWeatherSummaryInput")
        summary_input.setPlaceholderText("天气摘要，例如：多云 18°C")
        summary_input.setText(summary)
        save_button = self._inline_button("保存", parent)
        save_button.setObjectName("HomeEditorWeatherSaveButton")
        refresh_button = self._inline_button("刷新", parent)
        refresh_button.setObjectName("HomeEditorWeatherRefreshButton")
        save_button.clicked.connect(
            lambda: self._save_weather(city_input.text(), summary_input.text())
        )
        summary_input.returnPressed.connect(
            lambda: self._save_weather(city_input.text(), summary_input.text())
        )
        refresh_button.clicked.connect(lambda: self._request_weather_refresh(city_input.text()))
        layout.addWidget(city_input)
        row = QHBoxLayout()
        row.addWidget(summary_input, 1)
        row.addWidget(refresh_button)
        row.addWidget(save_button)
        layout.addLayout(row)

    def _replace_editor_panel(self, *, visible: bool) -> None:
        old_panel = self._editor_panel
        self._module_controls = {}
        self._editor_panel = self._build_editor_panel()
        old_panel.setParent(None)
        old_panel.deleteLater()
        if visible:
            self._position_editor_panel()
            self._editor_panel.show()
            self._editor_panel.raise_()

    def _read_visible_modules(self) -> list[str]:
        configured = self._settings.get("modules")
        if isinstance(configured, list):
            return [str(entry) for entry in configured if str(entry) in self._definitions]
        return [
            module_id
            for module_id in self._definition_order
            if self._definitions[module_id].default_visible
        ]

    def set_module_visible(self, module_id: str, visible: bool) -> None:
        if module_id not in self._definitions:
            return
        currently_visible = module_id in self._visible_modules
        if visible == currently_visible:
            self._sync_editor_controls()
            return
        if visible:
            self._visible_modules.append(module_id)
        else:
            self._visible_modules = [
                current for current in self._visible_modules if current != module_id
            ]
        self._sync_editor_controls()
        self._apply_responsive_layout(force=True)
        self._emit_settings_changed()

    def move_module(self, module_id: str, delta: int) -> None:
        if module_id not in self._visible_modules:
            return
        index = self._visible_modules.index(module_id)
        target = max(0, min(len(self._visible_modules) - 1, index + delta))
        if index == target:
            self._sync_editor_controls()
            return
        self._visible_modules.pop(index)
        self._visible_modules.insert(target, module_id)
        self._sync_editor_controls()
        self._apply_responsive_layout(force=True)
        self._emit_settings_changed()

    def _toggle_editor(self) -> None:
        if self._editor_panel.isVisible():
            self._editor_panel.hide()
        else:
            self._show_editor()

    def _show_editor(self) -> None:
        self._position_editor_panel()
        self._editor_panel.show()
        self._editor_panel.raise_()

    def _position_editor_panel(self) -> None:
        if not hasattr(self, "_editor_panel"):
            return
        margin = 24
        available_width = max(320, self.width() - margin * 2)
        width = min(500, max(360, available_width // 3))
        if available_width < 760:
            width = min(available_width, 420)
        height = max(260, self.height() - margin * 2)
        x = max(margin, self.width() - width - margin)
        self._editor_panel.setGeometry(x, margin, width, height)
        if self._editor_panel.isVisible():
            self._editor_panel.raise_()

    def _sync_editor_controls(self) -> None:
        for module_id, controls in self._module_controls.items():
            checkbox, up_button, down_button = controls
            checkbox.blockSignals(True)
            checkbox.setChecked(module_id in self._visible_modules)
            checkbox.blockSignals(False)
            if module_id in self._visible_modules:
                index = self._visible_modules.index(module_id)
                up_button.setEnabled(index > 0)
                down_button.setEnabled(index < len(self._visible_modules) - 1)
            else:
                up_button.setEnabled(False)
                down_button.setEnabled(False)

    def _emit_settings_changed(self) -> None:
        settings = dict(self._settings)
        settings["modules"] = list(self._visible_modules)
        settings.setdefault("module_settings", {})
        settings["reduced_motion"] = self._reduced_motion
        self._settings = settings
        self.settings_changed.emit(dict(settings))

    def _columns_for_width(self, width: int) -> int:
        if width >= 980:
            return 4
        if width >= 700:
            return 2
        return 1

    def _dashboard_mode_for_columns(self, columns: int) -> str:
        if columns >= 4:
            return "wide"
        if columns == 2:
            return "medium"
        return "compact"

    def _apply_responsive_layout(self, *, force: bool = False) -> None:
        columns = self._columns_for_width(max(self.width(), self.minimumWidth()))
        compact = columns == 1
        mode = self._dashboard_mode_for_columns(columns)
        if (
            not force
            and columns == self._layout_columns
            and compact == self._compact_modules
            and mode == self._dashboard_mode
        ):
            return
        self._layout_columns = columns
        self._compact_modules = compact
        self._dashboard_mode = mode
        self.setProperty("layout_columns", columns)
        self.setProperty("dashboard_mode", mode)
        self.setProperty("compact_modules", compact)
        self._rebuild_module_grid(columns, compact)

    def _rebuild_module_grid(self, columns: int, compact: bool) -> None:
        while self._module_grid.count():
            item = self._module_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._module_widgets.clear()

        placements: list[tuple[str, DashboardModuleDefinition, int, int, int]] = []
        row = 0
        column = 0
        for module_id in self._visible_modules:
            definition = self._definitions.get(module_id)
            if definition is None:
                continue
            span = self._column_span(definition, columns)
            if column + span > columns:
                row += 1
                column = 0
            placements.append((module_id, definition, row, column, span))
            column += span
            if column >= columns:
                row += 1
                column = 0

        if columns > 1 and placements:
            final_row = placements[-1][2]
            final_row_end = max(
                column + span
                for _module_id, _definition, row, column, span in placements
                if row == final_row
            )
            extra_span = columns - final_row_end
            if extra_span > 0:
                module_id, definition, row, column, span = placements[-1]
                if definition.empty_policy != "compact":
                    placements[-1] = (module_id, definition, row, column, span + extra_span)

        for module_id, definition, row, column, span in placements:
            widget = self._create_module_widget(
                definition,
                compact=compact,
                render_mode=self._render_mode_for(definition, columns, span),
            )
            alignment = (
                Qt.AlignmentFlag.AlignTop
                if widget.property("compact_empty")
                else Qt.AlignmentFlag(0)
            )
            self._module_grid.addWidget(widget, row, column, 1, span, alignment)
            self._module_widgets.append(widget)
        for index in range(4):
            self._module_grid.setColumnStretch(index, 1 if index < columns else 0)

    def _column_span(self, definition: DashboardModuleDefinition, columns: int) -> int:
        if columns <= 1:
            return 1
        return max(1, min(columns, definition.preferred_span))

    def _render_mode_for(
        self,
        definition: DashboardModuleDefinition,
        columns: int,
        span: int,
    ) -> DashboardModuleRenderMode:
        if columns <= 1:
            return "compact"
        if span >= 2:
            return "wide"
        return definition.render_mode

    def _create_module_widget(
        self,
        definition: DashboardModuleDefinition,
        *,
        compact: bool,
        render_mode: DashboardModuleRenderMode,
    ) -> QWidget:
        if definition.id == "recent":
            return self._build_recent_module(definition, compact=compact, render_mode=render_mode)
        if definition.id == "schedule":
            return self._build_schedule_module(definition, compact=compact, render_mode=render_mode)
        if definition.id == "bookmarks":
            return self._build_bookmarks_module(definition, compact=compact, render_mode=render_mode)
        if definition.id == "calendar":
            return self._build_calendar_module(definition, compact=compact, render_mode=render_mode)
        if definition.id == "weather":
            return self._build_weather_module(definition, compact=compact, render_mode=render_mode)
        return definition.create_widget(
            self._settings,
            compact=compact,
            render_mode=render_mode,
        )

    def _new_module_card(
        self,
        definition: DashboardModuleDefinition,
        *,
        render_mode: DashboardModuleRenderMode,
        compact_empty: bool = False,
        compact_card: bool = False,
    ) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame(self)
        card.setObjectName(f"HomeModuleCard-{definition.id}")
        card.setProperty("class", "HomeModuleCard")
        card.setProperty("render_mode", render_mode)
        card.setProperty("empty_state", compact_empty)
        card.setProperty("compact_empty", compact_empty)
        if compact_empty:
            card.setMaximumHeight(150)
        elif compact_card:
            card.setMaximumHeight(170)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12 if compact_empty else 14, 16, 12)
        layout.setSpacing(7 if compact_empty or compact_card else 9)
        title = QLabel(definition.display_name, card)
        title.setProperty("class", "HomeModuleTitle")
        layout.addWidget(title)
        return card, layout

    def _build_recent_module_legacy_unused(
        self,
        definition: DashboardModuleDefinition,
        *,
        compact: bool,
        render_mode: DashboardModuleRenderMode,
    ) -> QWidget:
        recent = self._list_setting("recent_items")
        card, layout = self._new_module_card(definition, render_mode=render_mode)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.addStretch(1)
        refresh_button = self._inline_button("刷新最近", card)
        refresh_button.setObjectName("HomeRecentRefreshButton")
        refresh_button.clicked.connect(self.recent_refresh_requested.emit)
        actions.addWidget(refresh_button)
        clear_button = self._inline_button("清理本地记录", card)
        clear_button.setObjectName("HomeRecentClearButton")
        clear_button.clicked.connect(self.recent_clear_requested.emit)
        actions.addWidget(clear_button)
        layout.addLayout(actions)
        self._add_body_label(
            layout,
            "来源：Windows 最近使用 + DesktopCleaner 打开记录",
            muted=True,
        )
        if not recent:
            self._add_body_label(layout, "打开文件、文件夹或快捷方式后会显示在这里。", muted=True)
            self._add_body_label(layout, "之后可以从这里再次打开最近入口。", muted=True)
            layout.addStretch(1)
            return card
        max_items = 3 if compact else 5
        for index, payload in enumerate(recent[:max_items]):
            if not isinstance(payload, dict):
                continue
            name = str(payload.get("name") or payload.get("path") or "").strip()
            path = str(payload.get("path") or "").strip()
            if not name or not path:
                continue
            button = self._text_button(name, card)
            button.setObjectName(f"HomeRecentOpen-{index}")
            source_label = self._recent_source_label(payload.get("source"))
            button.setToolTip(f"{source_label}\n{path}" if source_label else path)
            button.clicked.connect(lambda _=False, p=path: self.item_open_requested.emit(p))
            layout.addWidget(button)
        layout.addStretch(1)
        return card

    def _build_recent_module(
        self,
        definition: DashboardModuleDefinition,
        *,
        compact: bool,
        render_mode: DashboardModuleRenderMode,
    ) -> QWidget:
        recent = self._list_setting("recent_items")
        card, layout = self._new_module_card(definition, render_mode=render_mode)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.addStretch(1)
        refresh_button = self._inline_button("刷新最近", card)
        refresh_button.setObjectName("HomeRecentRefreshButton")
        refresh_button.clicked.connect(self.recent_refresh_requested.emit)
        actions.addWidget(refresh_button)
        layout.addLayout(actions)
        self._add_body_label(layout, "来源：Windows 最近使用", muted=True)
        if not recent:
            self._add_body_label(
                layout,
                "Windows 最近使用为空，或当前系统暂时无法读取。",
                muted=True,
            )
            self._add_body_label(layout, "点击刷新会重新扫描系统最近使用列表。", muted=True)
            layout.addStretch(1)
            return card
        max_items = 3 if compact else 5
        for index, payload in enumerate(recent[:max_items]):
            if not isinstance(payload, dict):
                continue
            name = str(payload.get("name") or payload.get("path") or "").strip()
            path = str(payload.get("path") or "").strip()
            if not name or not path:
                continue
            button = self._text_button(name, card)
            button.setObjectName(f"HomeRecentOpen-{index}")
            source_label = self._recent_source_label(payload.get("source"))
            button.setToolTip(f"{source_label}\n{path}" if source_label else path)
            button.clicked.connect(lambda _=False, p=path: self.item_open_requested.emit(p))
            layout.addWidget(button)
        layout.addStretch(1)
        return card

    def _recent_source_label(self, source: object) -> str:
        value = str(source or "").strip().casefold()
        if value == "windows":
            return "Windows Recent"
        if value == "app":
            return "DesktopCleaner"
        return ""

    def _build_schedule_module(
        self,
        definition: DashboardModuleDefinition,
        *,
        compact: bool,
        render_mode: DashboardModuleRenderMode,
    ) -> QWidget:
        selected = self._selected_date()
        reminders = [
            entry
            for entry in self._reminder_entries()
            if entry["date"] == selected.isoformat()
            and not entry["done"]
        ]
        card, layout = self._new_module_card(
            definition,
            render_mode=render_mode,
            compact_empty=not reminders,
            compact_card=compact,
        )
        selected_label = "今天" if selected == date.today() else selected.strftime("%m-%d")
        self._add_body_label(layout, f"日程 · {selected_label}", muted=True)
        if reminders:
            for entry in reminders[:4]:
                row = QHBoxLayout()
                label = QLabel(str(entry["text"]), card)
                label.setProperty("class", "HomeModuleItem")
                done_button = self._inline_button("完成", card)
                done_button.setObjectName(f"HomeReminderDone-{entry['raw_index']}")
                done_button.clicked.connect(
                    lambda _=False, i=int(entry["raw_index"]): self._complete_reminder(i)
                )
                delete_button = self._inline_button("删除", card)
                delete_button.setObjectName(f"HomeReminderDelete-{entry['raw_index']}")
                delete_button.clicked.connect(
                    lambda _=False, i=int(entry["raw_index"]): self._delete_reminder(i)
                )
                row.addWidget(label, 1)
                row.addWidget(done_button)
                row.addWidget(delete_button)
                layout.addLayout(row)
        else:
            self._add_body_label(layout, "这一天没有提醒。", muted=True)
        if not compact:
            layout.addStretch(1)
        return card

    def _build_calendar_module(
        self,
        definition: DashboardModuleDefinition,
        *,
        compact: bool,
        render_mode: DashboardModuleRenderMode,
    ) -> QWidget:
        selected = self._selected_date()
        today = date.today()
        if compact:
            card, layout = self._new_module_card(
                definition,
                render_mode=render_mode,
                compact_card=True,
            )
            self._add_body_label(layout, f"选中 {selected:%m-%d}")
            if selected != today:
                today_button = self._inline_button("回到今天", card)
                today_button.setObjectName("HomeCalendarTodayButton")
                today_button.clicked.connect(lambda: self._select_calendar_date(today.isoformat()))
                layout.addWidget(today_button)
            nav_row = QHBoxLayout()
            self._add_calendar_month_buttons(nav_row, card, selected)
            layout.addLayout(nav_row)
            return card

        card, layout = self._new_module_card(definition, render_mode=render_mode)
        header_row = QHBoxLayout()
        header = QLabel(f"{selected.year} 年 {selected.month} 月", card)
        header.setProperty("class", "HomeModuleItem")
        header_row.addWidget(header, 1)
        if selected != today:
            today_button = self._inline_button("今天", card)
            today_button.setObjectName("HomeCalendarTodayButton")
            today_button.clicked.connect(lambda: self._select_calendar_date(today.isoformat()))
            header_row.addWidget(today_button)
        self._add_calendar_month_buttons(header_row, card, selected)
        layout.addLayout(header_row)

        calendar_grid = QGridLayout()
        calendar_grid.setHorizontalSpacing(5)
        calendar_grid.setVerticalSpacing(5)
        for column, name in enumerate(("一", "二", "三", "四", "五", "六", "日")):
            label = QLabel(name, card)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setProperty("class", "HomeMuted")
            calendar_grid.addWidget(label, 0, column)

        reminder_dates = {
            entry["date"] for entry in self._reminder_entries() if not entry["done"]
        }
        for row, week in enumerate(calendar.monthcalendar(selected.year, selected.month), start=1):
            for column, day in enumerate(week):
                if day == 0:
                    spacer = QLabel("", card)
                    calendar_grid.addWidget(spacer, row, column)
                    continue
                day_date = date(selected.year, selected.month, day)
                button = QPushButton(f"{day:02d}", card)
                button.setObjectName(f"HomeCalendarDay-{day_date.isoformat()}")
                button.setProperty("class", "HomeCalendarDay")
                button.setProperty("selected", day_date == selected)
                button.setProperty("today", day_date == today)
                button.setProperty("has_reminder", day_date.isoformat() in reminder_dates)
                button.clicked.connect(
                    lambda _=False, iso=day_date.isoformat(): self._select_calendar_date(iso)
                )
                calendar_grid.addWidget(button, row, column)
        layout.addLayout(calendar_grid)
        layout.addStretch(1)
        return card

    def _add_calendar_month_buttons(
        self,
        layout: QHBoxLayout,
        parent: QWidget,
        selected: date,
    ) -> None:
        previous_button = self._inline_button("上月", parent)
        previous_button.setObjectName("HomeCalendarPreviousMonthButton")
        previous_button.clicked.connect(
            lambda: self._select_calendar_date(_shift_month(selected, -1).isoformat())
        )
        layout.addWidget(previous_button)

        next_button = self._inline_button("下月", parent)
        next_button.setObjectName("HomeCalendarNextMonthButton")
        next_button.clicked.connect(
            lambda: self._select_calendar_date(_shift_month(selected, 1).isoformat())
        )
        layout.addWidget(next_button)

    def _build_bookmarks_module(
        self,
        definition: DashboardModuleDefinition,
        *,
        compact: bool,
        render_mode: DashboardModuleRenderMode,
    ) -> QWidget:
        bookmarks = [
            entry
            for entry in self._module_list_setting("bookmarks", "bookmarks")
            if isinstance(entry, dict)
        ]
        card, layout = self._new_module_card(
            definition,
            render_mode=render_mode,
            compact_empty=not bookmarks,
            compact_card=compact,
        )
        if bookmarks:
            for index, bookmark in enumerate(bookmarks[:4]):
                title = str(bookmark.get("title") or bookmark.get("url") or "").strip()
                url = str(bookmark.get("url") or "").strip()
                if not title or not url:
                    continue
                row = QHBoxLayout()
                open_button = self._text_button(title, card)
                open_button.setObjectName(f"HomeBookmarkOpen-{index}")
                open_button.clicked.connect(lambda _=False, u=url: self.url_open_requested.emit(u))
                delete_button = self._inline_button("删除", card)
                delete_button.setObjectName(f"HomeBookmarkDelete-{index}")
                delete_button.clicked.connect(lambda _=False, i=index: self._delete_bookmark(i))
                row.addWidget(open_button, 1)
                row.addWidget(delete_button)
                layout.addLayout(row)
        else:
            self._add_body_label(layout, "还没有收藏网页。", muted=True)
        if not compact:
            layout.addStretch(1)
        return card

    def _build_weather_module(
        self,
        definition: DashboardModuleDefinition,
        *,
        compact: bool,
        render_mode: DashboardModuleRenderMode,
    ) -> QWidget:
        weather = self._module_dict_setting("weather", "weather")
        city = str(weather.get("city") or "").strip()
        summary = str(weather.get("summary") or "").strip()
        error = str(weather.get("error") or "").strip()
        card, layout = self._new_module_card(
            definition,
            render_mode=render_mode,
            compact_empty=not city,
            compact_card=compact,
        )
        if city:
            self._add_body_label(layout, city)
            self._add_body_label(layout, summary or "等待天气数据", muted=not summary)
            if error:
                self._add_body_label(layout, error, muted=True)
            refresh_button = self._inline_button("刷新天气", card)
            refresh_button.setObjectName("HomeWeatherRefreshInlineButton")
            refresh_button.clicked.connect(
                lambda _=False, current_city=city: self.weather_refresh_requested.emit(
                    current_city
                )
            )
            layout.addWidget(refresh_button, alignment=Qt.AlignmentFlag.AlignLeft)
        else:
            self._add_body_label(layout, error or "设置城市后显示天气。", muted=True)
            configure_button = self._inline_button("设置城市", card)
            configure_button.setObjectName("HomeWeatherConfigureButton")
            configure_button.clicked.connect(self._show_editor)
            layout.addWidget(configure_button, alignment=Qt.AlignmentFlag.AlignLeft)
        if not compact:
            layout.addStretch(1)
        return card

    def _add_body_label(self, layout: QVBoxLayout, text: str, *, muted: bool = False) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(False)
        label.setProperty("class", "HomeMuted" if muted else "HomeModuleItem")
        layout.addWidget(label)
        return label

    def _inline_button(self, text: str, parent: QWidget) -> QPushButton:
        button = QPushButton(text, parent)
        button.setProperty("class", "HomeInlineButton")
        return button

    def _text_button(self, text: str, parent: QWidget) -> QPushButton:
        button = QPushButton(text, parent)
        button.setProperty("class", "HomeTextButton")
        button.setToolTip(text)
        return button

    def _list_setting(self, key: str) -> list[Any]:
        value = self._settings.get(key)
        return list(value) if isinstance(value, list) else []

    def _dict_setting(self, key: str) -> dict[str, Any]:
        value = self._settings.get(key)
        return dict(value) if isinstance(value, dict) else {}

    def _module_dict(self, module_id: str) -> dict[str, Any]:
        modules = self._dict_setting("module_settings")
        value = modules.get(module_id)
        return dict(value) if isinstance(value, dict) else {}

    def _module_list_setting(
        self,
        module_id: str,
        key: str,
        *,
        legacy_key: str | None = None,
    ) -> list[Any]:
        value = self._module_dict(module_id).get(key)
        if isinstance(value, list):
            return list(value)
        return self._list_setting(legacy_key or key)

    def _module_dict_setting(
        self,
        module_id: str,
        key: str,
        *,
        legacy_key: str | None = None,
    ) -> dict[str, Any]:
        value = self._module_dict(module_id).get(key)
        if isinstance(value, dict):
            return dict(value)
        return self._dict_setting(legacy_key or key)

    def _set_module_setting(
        self,
        module_id: str,
        key: str,
        value: Any,
        *,
        legacy_key: str | None = None,
    ) -> None:
        modules = self._dict_setting("module_settings")
        module_settings = dict(modules.get(module_id)) if isinstance(modules.get(module_id), dict) else {}
        module_settings[key] = value
        modules[module_id] = module_settings
        self._settings["module_settings"] = modules
        self._settings[legacy_key or key] = value

    def _commit_module_settings(self) -> None:
        editor_visible = self._editor_panel.isVisible()
        self._update_clock()
        self._apply_responsive_layout(force=True)
        if editor_visible:
            self._replace_editor_panel(visible=True)
        self._emit_settings_changed()

    def _selected_date(self) -> date:
        calendar_settings = self._module_dict("calendar")
        return _parse_iso_date(
            calendar_settings.get("selected_date", self._settings.get("selected_date"))
        )

    def _selected_date_iso(self) -> str:
        return self._selected_date().isoformat()

    def _reminder_entries(self) -> list[dict[str, object]]:
        entries: list[dict[str, object]] = []
        for raw_index, item in enumerate(
            self._module_list_setting("schedule", "reminders")
        ):
            payload = self._reminder_payload(item)
            if payload is None:
                continue
            entries.append(
                {
                    "raw_index": raw_index,
                    "date": payload["date"],
                    "text": payload["text"],
                    "done": bool(payload.get("done")),
                }
            )
        return entries

    def _reminder_payload(self, item: Any) -> dict[str, object] | None:
        if isinstance(item, dict):
            text = str(item.get("text") or item.get("title") or "").strip()
            reminder_date = _parse_iso_date(item.get("date"))
            done = bool(item.get("done"))
        else:
            text = str(item).strip()
            reminder_date = date.today()
            done = False
        if not text:
            return None
        payload: dict[str, object] = {"date": reminder_date.isoformat(), "text": text}
        if done:
            payload["done"] = True
        return payload

    def _normalized_reminders(self, reminders: list[Any]) -> list[dict[str, object]]:
        cleaned = [
            payload
            for payload in (self._reminder_payload(item) for item in reminders)
            if payload is not None
        ]

        def sort_key(indexed: tuple[int, dict[str, object]]) -> tuple[str, int, int, int]:
            index, reminder = indexed
            reminder_date = str(reminder["date"])
            reminder_text = str(reminder["text"])
            match = _REMINDER_TIME_RE.match(reminder_text)
            if not match:
                return (reminder_date, 1, index, 0)
            hour = int(match.group("hour"))
            minute = int(match.group("minute"))
            if hour > 23:
                return (reminder_date, 1, index, 0)
            return (reminder_date, 0, hour * 60 + minute, index)

        return [reminder for _, reminder in sorted(enumerate(cleaned), key=sort_key)]

    def _select_calendar_date(self, iso_date: str) -> None:
        selected = _parse_iso_date(iso_date)
        selected_iso = selected.isoformat()
        if self._selected_date_iso() == selected_iso:
            return
        self._set_module_setting("calendar", "selected_date", selected_iso)
        self._commit_module_settings()

    def _add_reminder(self, text: str) -> None:
        value = str(text).strip()
        if not value:
            return
        reminders = list(self._module_list_setting("schedule", "reminders"))
        reminders.append({"date": self._selected_date_iso(), "text": value})
        self._set_module_setting(
            "schedule",
            "reminders",
            self._normalized_reminders(reminders)[:20],
        )
        self._commit_module_settings()

    def _delete_reminder(self, index: int) -> None:
        reminders = list(self._module_list_setting("schedule", "reminders"))
        if 0 <= index < len(reminders):
            del reminders[index]
            self._set_module_setting(
                "schedule",
                "reminders",
                self._normalized_reminders(reminders),
            )
            self._commit_module_settings()

    def _update_reminder(self, index: int, text: str) -> None:
        value = str(text).strip()
        if not value:
            return
        reminders = list(self._module_list_setting("schedule", "reminders"))
        if 0 <= index < len(reminders):
            payload = self._reminder_payload(reminders[index])
            if payload is None:
                return
            payload["text"] = value
            reminders[index] = payload
            self._set_module_setting(
                "schedule",
                "reminders",
                self._normalized_reminders(reminders),
            )
            self._commit_module_settings()

    def _complete_reminder(self, index: int) -> None:
        reminders = list(self._module_list_setting("schedule", "reminders"))
        if 0 <= index < len(reminders):
            payload = self._reminder_payload(reminders[index])
            if payload is None:
                return
            payload["done"] = True
            reminders[index] = payload
            self._set_module_setting(
                "schedule",
                "reminders",
                self._normalized_reminders(reminders),
            )
            self._commit_module_settings()

    def _restore_reminder(self, index: int) -> None:
        reminders = list(self._module_list_setting("schedule", "reminders"))
        if 0 <= index < len(reminders):
            payload = self._reminder_payload(reminders[index])
            if payload is None:
                return
            payload.pop("done", None)
            reminders[index] = payload
            self._set_module_setting(
                "schedule",
                "reminders",
                self._normalized_reminders(reminders),
            )
            self._commit_module_settings()

    def _add_bookmark(self, title: str, url: str) -> None:
        url_value = _normalize_bookmark_url(url)
        if url_value is None:
            return
        title_value = str(title).strip() or url_value
        bookmarks = [
            entry
            for entry in self._module_list_setting("bookmarks", "bookmarks")
            if isinstance(entry, dict)
        ]
        updated = False
        for index, bookmark in enumerate(bookmarks):
            existing_url = str(bookmark.get("url") or "").strip()
            if existing_url == url_value:
                bookmarks[index] = {"title": title_value, "url": url_value}
                updated = True
                break
        if not updated:
            bookmarks.append({"title": title_value, "url": url_value})
        self._set_module_setting("bookmarks", "bookmarks", bookmarks[:50])
        self._commit_module_settings()

    def _delete_bookmark(self, index: int) -> None:
        bookmarks = [
            entry
            for entry in self._module_list_setting("bookmarks", "bookmarks")
            if isinstance(entry, dict)
        ]
        if 0 <= index < len(bookmarks):
            del bookmarks[index]
            self._set_module_setting("bookmarks", "bookmarks", bookmarks)
            self._commit_module_settings()

    def _update_bookmark(self, index: int, title: str, url: str) -> None:
        url_value = _normalize_bookmark_url(url)
        if url_value is None:
            return
        title_value = str(title).strip() or url_value
        bookmarks = [
            entry
            for entry in self._module_list_setting("bookmarks", "bookmarks")
            if isinstance(entry, dict)
        ]
        if 0 <= index < len(bookmarks):
            bookmarks[index] = {"title": title_value, "url": url_value}
            self._set_module_setting("bookmarks", "bookmarks", bookmarks[:50])
            self._commit_module_settings()

    def _save_weather(self, city: str, summary: str) -> None:
        city_value = str(city).strip()
        summary_value = str(summary).strip()
        self._set_module_setting(
            "weather",
            "weather",
            (
                {"city": city_value, "summary": summary_value}
                if city_value or summary_value
                else {}
            ),
        )
        self._commit_module_settings()
        if city_value and not summary_value:
            self.weather_refresh_requested.emit(city_value)

    def _request_weather_refresh(self, city: str) -> None:
        city_value = str(city).strip()
        if city_value:
            self.weather_refresh_requested.emit(city_value)

    def _weather_summary(self) -> str:
        weather = self._module_dict_setting("weather", "weather")
        city = str(weather.get("city") or "").strip()
        if not city:
            return "天气待设置"
        summary = str(weather.get("summary") or "等待天气数据").strip()
        return f"{city}\n{summary}"

    def _update_clock(self) -> None:
        today = date.today()
        current = QDateTime.currentDateTime()
        self._hero_time.setText(current.toString("HH:mm"))
        self._hero_date.setText(f"{today:%Y-%m-%d} · {current.toString('dddd')}")
        self._weather_summary_label.setText(self._weather_summary())

    def _animate_entry(self) -> None:
        if self._reduced_motion:
            return
        effect = QGraphicsOpacityEffect(self)
        effect.setOpacity(0.0)
        self.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(120)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.finished.connect(lambda: self.setGraphicsEffect(None))
        self._animations.append(animation)
        animation.start()

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        self._apply_responsive_layout()
        self._position_editor_panel()


class HomeWidgetPlugin:
    id = "home"
    display_name = "主标签页"

    def definition(self) -> WidgetDefinition:
        return WidgetDefinition(
            id=self.id,
            display_name=self.display_name,
            description="桌面控制台首页，用于承载时间、最近使用、日程、收藏、日历和天气模块。",
            preview_title="今天",
            preview_body="最近使用 · 日程 · 日历 · 天气",
            visual=HOME_VISUAL,
        )

    def module_definitions(self) -> tuple[DashboardModuleDefinition, ...]:
        return default_dashboard_modules()

    def default_settings(self) -> dict[str, object]:
        return {
            "modules": [
                entry.id for entry in self.module_definitions() if entry.default_visible
            ],
            "module_settings": {},
            "recent_items": [],
            "reminders": [],
            "bookmarks": [],
            "weather": {},
            "reduced_motion": False,
        }

    def create_widget(self, settings: dict[str, object]) -> QWidget:
        merged = self.default_settings()
        merged.update(settings)
        return HomeDashboardWidget(merged, module_definitions=self.module_definitions())
