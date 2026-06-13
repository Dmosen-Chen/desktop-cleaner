"""Definitions and fallback widgets for modules shown inside the Home dashboard."""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Literal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QVBoxLayout, QWidget

DashboardModuleSize = Literal["hero", "wide", "normal", "compact"]
DashboardModuleRenderMode = Literal["hero", "wide", "normal", "compact"]
DashboardModuleEmptyPolicy = Literal["normal", "compact", "hidden"]
DashboardModuleFactory = Callable[
    [dict[str, object], "DashboardModuleDefinition", bool, DashboardModuleRenderMode],
    QWidget,
]


@dataclass(frozen=True)
class DashboardModuleDefinition:
    """Metadata and fallback factory for a module rendered inside the Home tab."""

    id: str
    display_name: str
    size: DashboardModuleSize
    empty_state: str
    priority: int = 50
    preferred_span: int = 1
    render_mode: DashboardModuleRenderMode = "normal"
    empty_policy: DashboardModuleEmptyPolicy = "normal"
    default_visible: bool = True
    refresh_interval_seconds: int = 0
    layout_default_w: int = 2
    layout_default_h: int = 1
    layout_min_w: int = 1
    layout_max_w: int = 8
    layout_min_h: int = 1
    layout_max_h: int = 3
    standalone_enabled: bool = True
    settings_section: str = ""
    factory: DashboardModuleFactory | None = field(default=None, repr=False, compare=False)

    def create_widget(
        self,
        settings: dict[str, object],
        *,
        compact: bool = False,
        render_mode: DashboardModuleRenderMode | None = None,
    ) -> QWidget:
        mode = "compact" if compact else (render_mode or self.render_mode)
        try:
            if self.factory is not None:
                return self.factory(settings, self, compact, mode)
        except Exception as exc:
            return _module_card(
                self,
                [f"模块加载失败：{exc}"],
                compact=compact,
                render_mode=mode,
                muted=True,
            )
        return _module_card(
            self,
            [self.empty_state],
            compact=compact,
            render_mode=mode,
            muted=True,
        )


def default_dashboard_modules() -> tuple[DashboardModuleDefinition, ...]:
    return (
        DashboardModuleDefinition(
            id="recent",
            display_name="最近使用",
            size="wide",
            empty_state="打开文件、文件夹或快捷方式后会显示在这里。",
            priority=100,
            preferred_span=2,
            render_mode="wide",
            empty_policy="normal",
            layout_default_w=4,
            layout_default_h=1,
            layout_max_w=8,
            layout_max_h=3,
            factory=_recent_module,
        ),
        DashboardModuleDefinition(
            id="schedule",
            display_name="今日日程",
            size="normal",
            empty_state="今天没有提醒。",
            priority=80,
            preferred_span=1,
            render_mode="normal",
            empty_policy="compact",
            layout_default_w=2,
            layout_default_h=1,
            layout_max_w=4,
            layout_max_h=3,
            settings_section="schedule",
            factory=_schedule_module,
        ),
        DashboardModuleDefinition(
            id="bookmarks",
            display_name="网络收藏",
            size="normal",
            empty_state="还没有收藏网页。",
            priority=70,
            preferred_span=1,
            render_mode="normal",
            empty_policy="compact",
            layout_default_w=2,
            layout_default_h=1,
            layout_max_w=4,
            layout_max_h=3,
            settings_section="bookmarks",
            factory=_bookmarks_module,
        ),
        DashboardModuleDefinition(
            id="calendar",
            display_name="月历",
            size="normal",
            empty_state="显示当前月份。",
            priority=60,
            preferred_span=1,
            render_mode="normal",
            empty_policy="normal",
            layout_default_w=3,
            layout_default_h=2,
            layout_max_w=4,
            layout_max_h=3,
            factory=_calendar_module,
        ),
        DashboardModuleDefinition(
            id="weather",
            display_name="天气",
            size="normal",
            empty_state="设置城市后显示天气。",
            priority=50,
            preferred_span=1,
            render_mode="normal",
            empty_policy="compact",
            layout_default_w=2,
            layout_default_h=1,
            layout_max_w=4,
            layout_max_h=3,
            settings_section="weather",
            factory=_weather_module,
        ),
        DashboardModuleDefinition(
            id="module_manager",
            display_name="模块管理",
            size="compact",
            empty_state="管理首页模块显示和顺序。",
            priority=30,
            preferred_span=1,
            render_mode="compact",
            empty_policy="compact",
            default_visible=False,
            layout_default_w=2,
            layout_default_h=1,
            layout_max_w=3,
            layout_max_h=2,
            standalone_enabled=False,
            settings_section="modules",
            factory=_module_manager_module,
        ),
    )


def _module_card(
    definition: DashboardModuleDefinition,
    lines: list[str],
    *,
    compact: bool,
    render_mode: DashboardModuleRenderMode,
    muted: bool = False,
) -> QFrame:
    card = QFrame()
    card.setObjectName(f"HomeModuleCard-{definition.id}")
    card.setProperty("class", "HomeModuleCard")
    card.setProperty("render_mode", render_mode)
    compact_empty = muted and definition.empty_policy == "compact"
    compact_card = compact or render_mode == "compact"
    card.setProperty("empty_state", muted)
    card.setProperty("compact_empty", compact_empty)
    if compact_empty:
        card.setMaximumHeight(124)
    elif compact_card:
        card.setMaximumHeight(150)
    layout = QVBoxLayout(card)
    layout.setContentsMargins(16, 12 if compact_empty else 14, 16, 12 if compact_empty else 14)
    layout.setSpacing(5 if compact_empty or compact_card else 9)

    title = QLabel(definition.display_name, card)
    title.setProperty("class", "HomeModuleTitle")
    layout.addWidget(title)

    max_lines = 2 if compact or definition.empty_policy == "compact" else 6
    for line in lines[:max_lines]:
        label = QLabel(line, card)
        label.setWordWrap(False)
        label.setProperty("class", "HomeMuted" if muted else "HomeModuleItem")
        layout.addWidget(label)
    if not compact_empty and not compact_card:
        layout.addStretch(1)
    return card


def _list_setting(settings: dict[str, object], key: str) -> list[Any]:
    value = settings.get(key)
    return value if isinstance(value, list) else []


def _dict_setting(settings: dict[str, object], key: str) -> dict[str, Any]:
    value = settings.get(key)
    return value if isinstance(value, dict) else {}


def _module_dict(settings: dict[str, object], module_id: str) -> dict[str, Any]:
    modules = _dict_setting(settings, "module_settings")
    value = modules.get(module_id)
    return value if isinstance(value, dict) else {}


def _module_list_setting(
    settings: dict[str, object],
    module_id: str,
    key: str,
) -> list[Any]:
    value = _module_dict(settings, module_id).get(key)
    if isinstance(value, list):
        return value
    return _list_setting(settings, key)


def _module_dict_setting(
    settings: dict[str, object],
    module_id: str,
    key: str,
) -> dict[str, Any]:
    value = _module_dict(settings, module_id).get(key)
    if isinstance(value, dict):
        return value
    return _dict_setting(settings, key)


def _parse_iso_date(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _recent_module(
    settings: dict[str, object],
    definition: DashboardModuleDefinition,
    compact: bool,
    render_mode: DashboardModuleRenderMode,
) -> QWidget:
    recent = _list_setting(settings, "recent_items")
    lines: list[str] = []
    for item in recent:
        if isinstance(item, dict):
            name = str(item.get("name") or item.get("path") or "").strip()
        else:
            name = str(item).strip()
        if name:
            lines.append(name)
    return _module_card(
        definition,
        lines or [definition.empty_state],
        compact=compact,
        render_mode=render_mode,
        muted=not lines,
    )


def _schedule_module(
    settings: dict[str, object],
    definition: DashboardModuleDefinition,
    compact: bool,
    render_mode: DashboardModuleRenderMode,
) -> QWidget:
    today = date.today()
    reminders: list[str] = []
    for item in _module_list_setting(settings, "schedule", "reminders"):
        if isinstance(item, dict):
            reminder_date = _parse_iso_date(item.get("date")) or today
            if reminder_date != today:
                continue
            text = str(item.get("text") or item.get("title") or "").strip()
        else:
            text = str(item).strip()
        if text:
            reminders.append(text)
    return _module_card(
        definition,
        reminders or [definition.empty_state],
        compact=compact,
        render_mode=render_mode,
        muted=not reminders,
    )


def _bookmarks_module(
    settings: dict[str, object],
    definition: DashboardModuleDefinition,
    compact: bool,
    render_mode: DashboardModuleRenderMode,
) -> QWidget:
    bookmarks = _module_list_setting(settings, "bookmarks", "bookmarks")
    lines: list[str] = []
    for bookmark in bookmarks:
        if isinstance(bookmark, dict):
            label = str(bookmark.get("title") or bookmark.get("url") or "").strip()
        else:
            label = str(bookmark).strip()
        if label:
            lines.append(label)
    return _module_card(
        definition,
        lines or [definition.empty_state],
        compact=compact,
        render_mode=render_mode,
        muted=not lines,
    )


def _calendar_module(
    _settings: dict[str, object],
    definition: DashboardModuleDefinition,
    compact: bool,
    render_mode: DashboardModuleRenderMode,
) -> QWidget:
    today = date.today()
    if compact:
        return _module_card(
            definition,
            [f"今天 {today.month:02d}-{today.day:02d}"],
            compact=compact,
            render_mode=render_mode,
        )

    card = QFrame()
    card.setObjectName(f"HomeModuleCard-{definition.id}")
    card.setProperty("class", "HomeModuleCard")
    card.setProperty("render_mode", render_mode)
    layout = QVBoxLayout(card)
    layout.setContentsMargins(16, 14, 16, 14)
    layout.setSpacing(8)

    title = QLabel(definition.display_name, card)
    title.setProperty("class", "HomeModuleTitle")
    layout.addWidget(title)

    header = QLabel(f"{today.year} 年 {today.month} 月", card)
    header.setProperty("class", "HomeModuleItem")
    layout.addWidget(header)

    calendar_grid = QGridLayout()
    calendar_grid.setHorizontalSpacing(7)
    calendar_grid.setVerticalSpacing(5)
    for column, name in enumerate(("一", "二", "三", "四", "五", "六", "日")):
        label = QLabel(name, card)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setProperty("class", "HomeMuted")
        calendar_grid.addWidget(label, 0, column)
    for row, week in enumerate(calendar.monthcalendar(today.year, today.month), start=1):
        for column, day in enumerate(week):
            label = QLabel("" if day == 0 else f"{day:02d}", card)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setProperty(
                "class",
                "HomeModuleItem" if day == today.day else "HomeModuleBody",
            )
            calendar_grid.addWidget(label, row, column)
    layout.addLayout(calendar_grid)
    layout.addStretch(1)
    return card


def _weather_module(
    settings: dict[str, object],
    definition: DashboardModuleDefinition,
    compact: bool,
    render_mode: DashboardModuleRenderMode,
) -> QWidget:
    weather = _module_dict_setting(settings, "weather", "weather")
    city = str(weather.get("city") or "").strip()
    if not city:
        return _module_card(
            definition,
            [definition.empty_state],
            compact=compact,
            render_mode=render_mode,
            muted=True,
        )
    summary = str(weather.get("summary") or "等待天气数据").strip()
    return _module_card(definition, [city, summary], compact=compact, render_mode=render_mode)


def _module_manager_module(
    _settings: dict[str, object],
    definition: DashboardModuleDefinition,
    compact: bool,
    render_mode: DashboardModuleRenderMode,
) -> QWidget:
    return _module_card(
        definition,
        ["在设置中管理首页模块、顺序和尺寸。"],
        compact=compact,
        render_mode=render_mode,
    )
