"""Home dashboard widget for the global main tab."""

from __future__ import annotations

import calendar
import re
from datetime import date
from typing import Any
from urllib.parse import urlparse

from PySide6.QtCore import QDateTime, QEasingCurve, QEvent, QPoint, QPropertyAnimation, QRect, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QBoxLayout,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from desktop_tidy.widgets.dashboard_modules import (
    DashboardModuleDefinition,
    DashboardModuleRenderMode,
    default_dashboard_modules,
)
from desktop_tidy.widgets.home_layout import (
    HomeLayoutSpec,
    HomeModuleLayout,
    build_default_module_layout,
    normalize_home_module_layout,
    resize_module as resize_home_module,
    set_module_position as set_home_module_position,
)
from desktop_tidy.widgets.models import WidgetDefinition, WidgetVisualPreset

HOME_GRID_UNITS = 8
HOME_UNIT_WIDTH = 144
HOME_GRID_GAP = 12
HOME_ROOT_HORIZONTAL_MARGIN = 24
HOME_CONTENT_RECOMMENDED_WIDTH = HOME_GRID_UNITS * HOME_UNIT_WIDTH + (
    HOME_GRID_UNITS - 1
) * HOME_GRID_GAP
HOME_WIDGET_RECOMMENDED_WIDTH = (
    HOME_CONTENT_RECOMMENDED_WIDTH + HOME_ROOT_HORIZONTAL_MARGIN * 2
)
HOME_WIDGET_MAX_WIDTH = HOME_WIDGET_RECOMMENDED_WIDTH
HOME_MODULE_RESIZE_MARGIN = 12
HOME_MODULE_HEIGHT_UNIT = 96
HOME_MODULE_MIN_HEIGHT = 132
HOME_GRID_MAX_ROWS = 6
HOME_MODULE_UNIT_SPANS = {
    "recent": 4,
    "calendar": 3,
    "schedule": 2,
    "bookmarks": 2,
    "weather": 2,
    "module_manager": 2,
}
HOME_MODULE_UNIT_HEIGHTS = {
    "calendar": 2,
}

HOME_VISUAL = WidgetVisualPreset(
    preset_id="home-dashboard",
    accent_color="#d99abd",
    background="#17141d",
    foreground="#f8fafc",
    secondary_foreground="rgba(248,250,252, 184)",
    card_background="rgba(31,35,45, 235)",
    recommended_width=HOME_WIDGET_RECOMMENDED_WIDTH,
    recommended_height=560,
    min_width=640,
    min_height=420,
    max_width=HOME_WIDGET_MAX_WIDTH,
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


class _HomeModuleGridItem:
    def __init__(self, widget: QWidget) -> None:
        self._widget = widget

    def widget(self) -> QWidget:
        return self._widget


class _HomeModuleGridSnapshot:
    def __init__(self, owner: "HomeDashboardWidget") -> None:
        self._owner = owner

    def count(self) -> int:
        return len(self._owner._module_widgets)

    def itemAt(self, index: int) -> _HomeModuleGridItem:
        return _HomeModuleGridItem(self._owner._module_widgets[index])

    def getItemPosition(self, index: int) -> tuple[int, int, int, int]:
        widget = self._owner._module_widgets[index]
        module_id = str(widget.property("module_id") or "")
        return self._owner._module_grid_position_tuple(module_id)


class HomeDashboardWidget(QWidget):
    """The single Home tab, composed from local dashboard modules."""

    settings_changed = Signal(dict)
    item_open_requested = Signal(str)
    url_open_requested = Signal(str)
    weather_refresh_requested = Signal(str)
    recent_refresh_requested = Signal()
    recent_clear_requested = Signal()
    home_settings_requested = Signal(str)

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
        self._module_cards_by_id: dict[str, QWidget] = {}
        self._module_drag_handles: dict[str, QPushButton] = {}
        self._module_render_modes: dict[str, DashboardModuleRenderMode] = {}
        self._module_drag_source_id = ""
        self._module_drag_started = False
        self._module_drag_start_global = QPoint()
        self._module_drag_start_column = 0
        self._module_drag_start_row = 0
        self._module_drag_preview_column = 0
        self._module_drag_preview_row = 0
        self._module_drag_original_positions: dict[str, dict[str, int]] = {}
        self._module_drop_target_id = ""
        self._module_resize_source_id = ""
        self._module_resize_started = False
        self._module_resize_start_global = QPoint()
        self._module_resize_start_width = 1
        self._module_resize_start_height = 1
        self._module_resize_preview_width = 1
        self._module_resize_preview_height = 1
        self._module_resize_axis = ""
        self._module_resize_original_spans: dict[str, dict[str, int]] = {}
        self._layout_columns = 0
        self._layout_units = 0
        self._compact_modules = False
        self._dashboard_mode = ""
        self._reduced_motion = bool(self._settings.get("reduced_motion", False))
        self._layout_locked = bool(self._settings.get("layout_locked", True))
        self._visible_modules = self._read_visible_modules()
        self._layout_specs = self._home_layout_specs()
        self._module_layout = normalize_home_module_layout(
            self._visible_modules,
            self._layout_specs,
            self._settings,
        )
        self._module_spans = self._read_module_spans()
        self._module_positions = self._read_module_positions()

        self.setObjectName("HomeDashboardWidgetRoot")
        self.setProperty("reduced_motion", self._reduced_motion)
        self.setProperty("layout_columns", 0)
        self.setProperty("layout_units", 0)
        self.setProperty("dashboard_mode", "")
        self.setProperty("compact_modules", False)
        self.setProperty("layout_locked", self._layout_locked)
        self.setMinimumSize(HOME_VISUAL.min_width, HOME_VISUAL.min_height)
        self.setMaximumSize(HOME_VISUAL.max_width, HOME_VISUAL.max_height)
        self.setStyleSheet(self._style_sheet())

        self._root_layout = QVBoxLayout(self)
        self._root_layout.setContentsMargins(
            HOME_ROOT_HORIZONTAL_MARGIN, 20, HOME_ROOT_HORIZONTAL_MARGIN, 22
        )
        self._root_layout.setSpacing(14)
        self._root_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)

        self._dashboard_shell = QWidget(self)
        self._dashboard_shell.setObjectName("HomeDashboardShell")
        self._dashboard_shell.setMaximumWidth(HOME_CONTENT_RECOMMENDED_WIDTH)
        self._dashboard_shell.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self._dashboard_layout = QVBoxLayout(self._dashboard_shell)
        self._dashboard_layout.setContentsMargins(0, 0, 0, 0)
        self._dashboard_layout.setSpacing(14)

        self._hero_time = QLabel(self)
        self._hero_time.setObjectName("HomeHeroTime")
        self._hero_date = QLabel(self)
        self._hero_date.setObjectName("HomeHeroDate")
        self._weather_status = QFrame(self)
        self._weather_status.setObjectName("HomeHeroWeatherStatus")
        weather_status_layout = QVBoxLayout(self._weather_status)
        weather_status_layout.setContentsMargins(12, 8, 12, 8)
        weather_status_layout.setSpacing(2)
        self._weather_city_label = QLabel(self._weather_status)
        self._weather_city_label.setObjectName("HomeHeroWeatherCity")
        self._weather_city_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._weather_summary_label = QLabel(self._weather_status)
        self._weather_summary_label.setObjectName("HomeHeroWeatherSummary")
        self._weather_summary_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._weather_summary_label.setWordWrap(True)
        weather_status_layout.addWidget(self._weather_city_label)
        weather_status_layout.addWidget(self._weather_summary_label)
        self._edit_button = QPushButton("锁定", self)
        self._edit_button.setObjectName("HomeLayoutLockButton")
        self._edit_button.clicked.connect(self._toggle_layout_lock)
        self._lock_button = self._edit_button
        self._sync_lock_button()

        self._dashboard_layout.addWidget(self._build_hero_panel())

        self._content_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(HOME_GRID_GAP)
        self._content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._module_area = QWidget(self)
        self._module_area.setObjectName("HomeModuleArea")
        self._module_area.setMaximumWidth(HOME_CONTENT_RECOMMENDED_WIDTH)
        self._module_area.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._module_grid = _HomeModuleGridSnapshot(self)
        self._content_layout.addWidget(self._module_area, 1)

        self._dashboard_layout.addLayout(self._content_layout, 1)
        self._root_layout.addWidget(
            self._dashboard_shell,
            1,
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
        )

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
            QFrame.HomeModuleCard {
                background: rgba(24, 27, 36, 235);
                border: 1px solid rgba(255, 255, 255, 28);
                border-radius: 14px;
            }
            QFrame.HomeModuleCard:hover {
                background: rgba(31, 35, 46, 240);
                border: 1px solid rgba(217, 154, 189, 112);
            }
            QFrame.HomeModuleCard[dragging="true"] {
                background: rgba(34, 38, 48, 245);
                border: 1px solid rgba(217, 154, 189, 184);
            }
            QFrame.HomeModuleCard[drop_target="true"] {
                border: 1px solid rgba(217, 154, 189, 224);
            }
            QFrame.HomeModuleCard[resizing="true"] {
                border: 1px solid rgba(217, 154, 189, 224);
                background: rgba(34, 38, 48, 245);
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
                color: rgba(248, 250, 252, 199);
                font-size: 15px;
            }
            QFrame#HomeHeroWeatherStatus {
                background: rgba(255, 255, 255, 11);
                border-radius: 10px;
            }
            QLabel#HomeHeroWeatherCity {
                color: rgba(248, 250, 252, 235);
                font-size: 14px;
                font-weight: 650;
            }
            QLabel#HomeHeroWeatherSummary {
                color: rgba(248, 250, 252, 173);
                font-size: 13px;
            }
            QLabel.HomeModuleTitle {
                color: #f8fafc;
                font-size: 17px;
                font-weight: 700;
            }
            QLabel.HomeModuleBody {
                color: rgba(248, 250, 252, 199);
                font-size: 13px;
            }
            QLabel.HomeModuleItem {
                color: rgba(248, 250, 252, 235);
                font-size: 13px;
                padding: 3px 0;
            }
            QLabel.HomeMuted {
                color: rgba(248, 250, 252, 163);
                font-size: 13px;
            }
            QPushButton#HomeLayoutLockButton,
            QPushButton.HomeInlineButton,
            QPushButton.HomeTextButton {
                color: #f8fafc;
                background: rgba(255, 255, 255, 26);
                border: 1px solid rgba(255, 255, 255, 31);
                border-radius: 10px;
                padding: 6px 12px;
            }
            QPushButton#HomeLayoutLockButton:hover,
            QPushButton.HomeInlineButton:hover,
            QPushButton.HomeTextButton:hover {
                background: rgba(217, 154, 189, 56);
                border-color: rgba(217, 154, 189, 140);
            }
            QPushButton.HomeInlineButton:disabled,
            QPushButton.HomeTextButton:disabled {
                color: rgba(248, 250, 252, 82);
                background: rgba(255, 255, 255, 15);
            }
            QPushButton.HomeModuleDragHandle {
                color: rgba(248, 250, 252, 184);
                background: rgba(255, 255, 255, 15);
                border: 1px solid rgba(255, 255, 255, 26);
                border-radius: 8px;
                padding: 2px 7px;
            }
            QPushButton.HomeModuleDragHandle:hover {
                color: #f8fafc;
                background: rgba(217, 154, 189, 46);
                border-color: rgba(217, 154, 189, 112);
            }
            QPushButton.HomeModuleDragHandle:pressed {
                background: rgba(217, 154, 189, 71);
                border-color: rgba(217, 154, 189, 184);
            }
            QPushButton.HomeCalendarDay {
                color: rgba(248, 250, 252, 209);
                background: rgba(255, 255, 255, 10);
                border: 1px solid rgba(255, 255, 255, 20);
                border-radius: 7px;
                padding: 3px 4px;
                min-width: 28px;
            }
            QPushButton.HomeCalendarDay:hover {
                background: rgba(217, 154, 189, 51);
                border-color: rgba(217, 154, 189, 107);
            }
            QPushButton.HomeCalendarDay[selected="true"] {
                color: #17141d;
                background: #d99abd;
                border-color: rgba(255, 255, 255, 184);
                font-weight: 700;
            }
            QPushButton.HomeCalendarDay[today="true"] {
                border-color: rgba(255, 255, 255, 140);
            }
            QPushButton.HomeCalendarDay[has_reminder="true"] {
                color: #fff7fb;
                border-color: rgba(217, 154, 189, 178);
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

        layout.addWidget(self._weather_status)
        layout.addWidget(self._edit_button)
        return hero

    def _read_visible_modules(self) -> list[str]:
        configured = self._settings.get("modules")
        if isinstance(configured, list):
            return [str(entry) for entry in configured if str(entry) in self._definitions]
        return [
            module_id
            for module_id in self._definition_order
            if self._definitions[module_id].default_visible
        ]

    def _home_layout_specs(self) -> dict[str, HomeLayoutSpec]:
        return {
            module_id: HomeLayoutSpec(
                default_w=definition.layout_default_w,
                default_h=definition.layout_default_h,
                min_w=definition.layout_min_w,
                max_w=definition.layout_max_w,
                min_h=definition.layout_min_h,
                max_h=definition.layout_max_h,
            )
            for module_id, definition in self._definitions.items()
        }

    def _read_module_spans(self) -> dict[str, dict[str, int]]:
        return {
            module_id: {"w": layout["w"], "h": layout["h"]}
            for module_id, layout in self._module_layout.items()
        }

    def _read_module_positions(self) -> dict[str, dict[str, int]]:
        return {
            module_id: {"x": layout["x"], "y": layout["y"]}
            for module_id, layout in self._module_layout.items()
        }

    def _sync_legacy_layout_views(self) -> None:
        self._module_spans = self._read_module_spans()
        self._module_positions = self._read_module_positions()

    def _normalize_current_module_layout(self) -> None:
        settings = dict(self._settings)
        settings["module_layout"] = {
            module_id: dict(layout)
            for module_id, layout in self._module_layout.items()
            if module_id in self._definitions
        }
        self._module_layout = normalize_home_module_layout(
            self._visible_modules,
            self._layout_specs,
            settings,
        )
        self._sync_legacy_layout_views()

    def set_module_visible(self, module_id: str, visible: bool) -> None:
        if module_id not in self._definitions:
            return
        currently_visible = module_id in self._visible_modules
        if visible == currently_visible:
            return
        if visible:
            self._visible_modules.append(module_id)
        else:
            self._visible_modules = [
                current for current in self._visible_modules if current != module_id
            ]
        self._normalize_current_module_layout()
        self._apply_responsive_layout(force=True, animate=True)
        self._emit_settings_changed()

    def move_module(self, module_id: str, delta: int) -> None:
        if module_id not in self._visible_modules:
            return
        index = self._visible_modules.index(module_id)
        target = max(0, min(len(self._visible_modules) - 1, index + delta))
        if index == target:
            return
        self._visible_modules.pop(index)
        self._visible_modules.insert(target, module_id)
        self._apply_responsive_layout(force=True, animate=True)
        self._emit_settings_changed()

    def _toggle_layout_lock(self) -> None:
        self._set_layout_locked(not self._layout_locked, emit=True)

    def _toggle_editor(self) -> None:
        self._toggle_layout_lock()

    def _show_editor(self) -> None:
        self.home_settings_requested.emit("modules")

    def _hide_editor(self) -> None:
        self._set_layout_locked(True, emit=True)

    def _set_layout_locked(self, locked: bool, *, emit: bool = False) -> None:
        locked = bool(locked)
        if self._layout_locked == locked:
            self._sync_lock_button()
            return
        self._layout_locked = locked
        self.setProperty("layout_locked", self._layout_locked)
        if locked:
            self._finish_module_drag(commit=False)
            self._finish_module_resize(commit=False)
        self._sync_lock_button()
        self._set_module_drag_handles_visible(not locked)
        self._apply_responsive_layout(force=True, animate=True)
        if emit:
            self._emit_settings_changed()

    def _sync_lock_button(self) -> None:
        if not hasattr(self, "_lock_button"):
            return
        if self._layout_locked:
            self._lock_button.setText("锁定")
            self._lock_button.setToolTip("点击解锁布局，拖动或调整首页模块")
            self._lock_button.setProperty("layout_locked", True)
        else:
            self._lock_button.setText("调整中")
            self._lock_button.setToolTip("点击锁定首页布局")
            self._lock_button.setProperty("layout_locked", False)
        style = self._lock_button.style()
        style.unpolish(self._lock_button)
        style.polish(self._lock_button)

    def _position_editor_panel(self) -> None:
        self._sync_content_layout()

    def _content_width(self) -> int:
        margins = self._root_layout.contentsMargins()
        width = self.width() or HOME_VISUAL.recommended_width
        return max(0, width - margins.left() - margins.right())

    def _sync_content_layout(self) -> None:
        if not hasattr(self, "_content_layout"):
            return
        if self._content_layout.direction() != QBoxLayout.Direction.LeftToRight:
            self._content_layout.setDirection(QBoxLayout.Direction.LeftToRight)
        target_width = max(1, min(self._content_width(), HOME_CONTENT_RECOMMENDED_WIDTH))
        self._dashboard_shell.setFixedWidth(target_width)
        self._module_area.setFixedWidth(target_width)

    def _available_module_width(self) -> int:
        return max(0, min(self._content_width(), HOME_CONTENT_RECOMMENDED_WIDTH))

    def _set_module_drag_handles_visible(self, visible: bool) -> None:
        for handle in self._module_drag_handles.values():
            handle.setVisible(visible)
        cursor = Qt.CursorShape.OpenHandCursor if visible else Qt.CursorShape.ArrowCursor
        for card in self._module_cards_by_id.values():
            card.setCursor(cursor)

    def _is_module_resize_edge(self, widget: object, local_pos: QPoint) -> bool:
        return any(self._module_resize_edges(widget, local_pos))

    def _module_resize_edges(self, widget: object, local_pos: QPoint) -> tuple[bool, bool]:
        if self._layout_locked:
            return (False, False)
        if not bool(getattr(widget, "property", lambda _name: False)("module_drag_surface")):
            return (False, False)
        width = getattr(widget, "width", lambda: 0)()
        height = getattr(widget, "height", lambda: 0)()
        right = self._layout_units > 1 and local_pos.x() >= max(
            0,
            width - HOME_MODULE_RESIZE_MARGIN,
        )
        bottom = local_pos.y() >= max(0, height - HOME_MODULE_RESIZE_MARGIN)
        return (right, bottom)

    def _module_id_from_drag_widget(self, widget: object) -> str:
        module_id = getattr(widget, "property", lambda _name: "")("module_id")
        return str(module_id or "")

    def _set_dynamic_property(self, widget: QWidget | None, name: str, value: object) -> None:
        if widget is None:
            return
        if widget.property(name) == value:
            return
        widget.setProperty(name, value)
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)
        widget.update()

    def _set_module_dragging(self, module_id: str, dragging: bool) -> None:
        self._set_dynamic_property(self._module_cards_by_id.get(module_id), "dragging", dragging)

    def _set_module_resizing(self, module_id: str, resizing: bool) -> None:
        self._set_dynamic_property(self._module_cards_by_id.get(module_id), "resizing", resizing)

    def _set_module_drop_target(self, module_id: str) -> None:
        if module_id == self._module_drop_target_id:
            return
        if self._module_drop_target_id:
            self._set_dynamic_property(
                self._module_cards_by_id.get(self._module_drop_target_id),
                "drop_target",
                False,
            )
        self._module_drop_target_id = module_id
        if module_id:
            self._set_dynamic_property(
                self._module_cards_by_id.get(module_id),
                "drop_target",
                True,
            )

    def _global_pos_from_mouse_event(self, event: object) -> QPoint:
        global_position = getattr(event, "globalPosition", None)
        if global_position is not None:
            return global_position().toPoint()
        global_pos = getattr(event, "globalPos", None)
        if global_pos is not None:
            return global_pos()
        return QPoint()

    def _drop_index_for_global_pos(self, global_pos: QPoint) -> int | None:
        for index, module_id in enumerate(self._visible_modules):
            card = self._module_cards_by_id.get(module_id)
            if card is None or not card.isVisible():
                continue
            local_pos = card.mapFromGlobal(global_pos)
            if not card.rect().contains(local_pos):
                continue
            if self._layout_columns <= 1:
                after_target = local_pos.y() > card.height() // 2
            else:
                after_target = local_pos.x() > card.width() // 2
            return index + (1 if after_target else 0)
        return None

    def _module_grid_position(self, module_id: str) -> tuple[int, int]:
        item = self._module_layout.get(module_id)
        if item is None:
            return (0, 0)
        return (item["y"], item["x"])

    def _module_grid_position_tuple(self, module_id: str) -> tuple[int, int, int, int]:
        item = self._module_layout.get(module_id)
        if item is None:
            return (0, 0, 1, 1)
        columns = max(1, self._layout_units or HOME_GRID_UNITS)
        span = min(columns, item["w"])
        column = max(0, min(max(0, columns - span), item["x"]))
        return (item["y"], column, item["h"], span)

    def _occupied_cells_from_grid(
        self,
        *,
        exclude_module_id: str = "",
    ) -> set[tuple[int, int]]:
        occupied: set[tuple[int, int]] = set()
        for module_id, item in self._module_layout.items():
            if module_id == exclude_module_id:
                continue
            occupied.update(
                (cell_row, cell_column)
                for cell_row in range(item["y"], item["y"] + item["h"])
                for cell_column in range(item["x"], item["x"] + item["w"])
            )
        return occupied

    def _module_id_for_drop_index(self, drop_index: int | None) -> str:
        if drop_index is None or not self._visible_modules:
            return ""
        clamped = max(0, min(drop_index, len(self._visible_modules) - 1))
        return self._visible_modules[clamped]

    def _move_module_to_index(self, module_id: str, target_index: int) -> bool:
        if module_id not in self._visible_modules:
            return False
        current_index = self._visible_modules.index(module_id)
        insert_index = max(0, min(len(self._visible_modules), int(target_index)))
        if insert_index > current_index:
            insert_index -= 1
        self._visible_modules.pop(current_index)
        insert_index = max(0, min(len(self._visible_modules), insert_index))
        if current_index == insert_index:
            self._visible_modules.insert(current_index, module_id)
            return False
        self._visible_modules.insert(insert_index, module_id)
        self._apply_responsive_layout(force=True, animate=True)
        self._emit_settings_changed()
        return True

    def _set_module_position(self, module_id: str, column: int, row: int) -> bool:
        if module_id not in self._definitions:
            return False
        changed, next_layout = set_home_module_position(
            self._module_layout,
            module_id,
            column,
            row,
            self._visible_modules,
            self._layout_specs,
        )
        if not changed:
            return False
        self._module_layout = next_layout
        self._sync_legacy_layout_views()
        self._apply_responsive_layout(force=True, animate=True)
        self._emit_settings_changed()
        return True

    def _module_unit_step(self) -> float:
        units = max(1, self._layout_units)
        width = max(1, self._module_area.width())
        total_gap = HOME_GRID_GAP * max(0, units - 1)
        unit_width = max(1.0, (width - total_gap) / units)
        return unit_width + HOME_GRID_GAP

    def _module_height_step(self) -> float:
        return float(HOME_MODULE_MIN_HEIGHT + HOME_GRID_GAP)

    def _resize_units_for_global_pos(self, global_pos: QPoint) -> tuple[int, int]:
        delta = global_pos - self._module_resize_start_global
        width_delta = 0
        height_delta = 0
        if self._module_resize_axis in {"w", "both"}:
            width_delta = int(round(delta.x() / self._module_unit_step()))
        if self._module_resize_axis in {"h", "both"}:
            height_delta = int(round(delta.y() / self._module_height_step()))
        max_width = max(1, self._layout_units)
        width = max(
            1,
            min(max_width, self._module_resize_start_width + width_delta),
        )
        height = max(
            1,
            min(3, self._module_resize_start_height + height_delta),
        )
        return (width, height)

    def _copy_module_spans(self) -> dict[str, dict[str, int]]:
        return {
            module_id: dict(layout)
            for module_id, layout in self._module_layout.items()
        }

    def _copy_module_positions(self) -> dict[str, dict[str, int]]:
        return {
            module_id: dict(layout)
            for module_id, layout in self._module_layout.items()
        }

    def _default_module_width(self, module_id: str) -> int:
        definition = self._definitions[module_id]
        return definition.layout_default_w

    def _default_module_height(self, module_id: str) -> int:
        return self._definitions[module_id].layout_default_h

    def _normalized_module_span(
        self,
        module_id: str,
        *,
        width: int | None = None,
        height: int | None = None,
        base: dict[str, int] | None = None,
    ) -> dict[str, int]:
        current = dict(base if base is not None else self._module_layout.get(module_id) or {})
        next_width = int(
            width if width is not None else current.get("w", self._default_module_width(module_id))
        )
        next_height = int(
            height if height is not None else current.get("h", self._default_module_height(module_id))
        )
        spec = self._layout_specs.get(module_id, HomeLayoutSpec(default_w=2))
        return {
            "w": max(spec.min_w, min(spec.max_w, HOME_GRID_UNITS, next_width)),
            "h": max(spec.min_h, min(spec.max_h, 3, next_height)),
        }

    def _normalized_module_position(
        self,
        module_id: str,
        *,
        column: int | None = None,
        row: int | None = None,
        columns: int | None = None,
        base: dict[str, int] | None = None,
    ) -> dict[str, int]:
        current = dict(
            base if base is not None else self._module_layout.get(module_id) or {}
        )
        layout_columns = max(1, int(columns or self._layout_units or HOME_GRID_UNITS))
        definition = self._definitions[module_id]
        width_units = self._column_span(definition, layout_columns)
        height_units = self._module_height_units(definition)
        next_column = int(column if column is not None else current.get("x", 0))
        next_row = int(row if row is not None else current.get("y", 0))
        return {
            "x": max(0, min(max(0, layout_columns - width_units), next_column)),
            "y": max(0, min(max(0, HOME_GRID_MAX_ROWS - height_units), next_row)),
        }

    def _occupied_cells_for(
        self,
        module_id: str,
        *,
        column: int,
        row: int,
        columns: int,
    ) -> set[tuple[int, int]]:
        definition = self._definitions[module_id]
        width_units = self._column_span(definition, columns)
        height_units = self._module_height_units(definition)
        return {
            (cell_row, cell_column)
            for cell_row in range(row, row + height_units)
            for cell_column in range(column, column + width_units)
        }

    def _position_is_free(
        self,
        module_id: str,
        *,
        column: int,
        row: int,
        columns: int,
        occupied: set[tuple[int, int]],
    ) -> bool:
        return not (
            self._occupied_cells_for(
                module_id,
                column=column,
                row=row,
                columns=columns,
            )
            & occupied
        )

    def _nearest_free_module_position(
        self,
        module_id: str,
        *,
        target_column: int,
        target_row: int,
        columns: int,
        occupied: set[tuple[int, int]],
    ) -> dict[str, int]:
        normalized = self._normalized_module_position(
            module_id,
            column=target_column,
            row=target_row,
            columns=columns,
        )
        definition = self._definitions[module_id]
        width_units = self._column_span(definition, columns)
        height_units = self._module_height_units(definition)
        max_column = max(0, columns - width_units)
        max_row = max(0, HOME_GRID_MAX_ROWS - height_units)
        best_position = normalized
        best_distance: int | None = None
        for row in range(max_row + 1):
            for column in range(max_column + 1):
                if not self._position_is_free(
                    module_id,
                    column=column,
                    row=row,
                    columns=columns,
                    occupied=occupied,
                ):
                    continue
                distance = abs(column - normalized["x"]) + abs(row - normalized["y"])
                if best_distance is None or distance < best_distance:
                    best_distance = distance
                    best_position = {"x": column, "y": row}
        return best_position

    def _set_module_span(
        self,
        module_id: str,
        *,
        width: int | None = None,
        height: int | None = None,
    ) -> bool:
        if module_id not in self._definitions:
            return False
        current = self._module_layout.get(module_id)
        changed, next_layout = resize_home_module(
            self._module_layout,
            module_id,
            int(width if width is not None else (current or {}).get("w", self._default_module_width(module_id))),
            int(height if height is not None else (current or {}).get("h", self._default_module_height(module_id))),
            self._visible_modules,
            self._layout_specs,
        )
        if not changed:
            return False
        self._module_layout = next_layout
        self._sync_legacy_layout_views()
        self._apply_responsive_layout(force=True, animate=True)
        self._emit_settings_changed()
        return True

    def _apply_module_resize_preview(self, width: int, height: int) -> None:
        source_id = self._module_resize_source_id
        if not source_id or source_id not in self._definitions:
            return
        changed, next_layout = resize_home_module(
            self._module_layout,
            source_id,
            width,
            height,
            self._visible_modules,
            self._layout_specs,
        )
        if not changed:
            return
        self._module_layout = next_layout
        self._sync_legacy_layout_views()
        self._apply_responsive_layout(force=True, animate=True)
        self._set_module_resizing(source_id, True)

    def _finish_module_resize(
        self,
        *,
        commit: bool,
        global_pos: QPoint | None = None,
    ) -> None:
        source_id = self._module_resize_source_id
        next_width, next_height = (
            self._resize_units_for_global_pos(global_pos)
            if commit and global_pos is not None
            else (self._module_resize_start_width, self._module_resize_start_height)
        )
        original_spans = {
            module_id: dict(layout)
            for module_id, layout in self._module_resize_original_spans.items()
        }
        preview_changed = self._module_layout != original_spans
        self.releaseMouse()
        self._set_module_resizing(source_id, False)
        self._module_resize_source_id = ""
        self._module_resize_started = False
        self._module_resize_axis = ""
        self._module_resize_original_spans = {}
        if preview_changed:
            self._module_layout = original_spans
            self._sync_legacy_layout_views()
        if source_id and commit:
            changed = self._set_module_span(source_id, width=next_width, height=next_height)
            if not changed and preview_changed:
                self._apply_responsive_layout(force=True, animate=True)
        elif preview_changed:
            self._apply_responsive_layout(force=True, animate=True)

    def _update_module_resize_for_global_pos(self, global_pos: QPoint) -> None:
        if not self._module_resize_source_id or self._layout_locked:
            return
        if (global_pos - self._module_resize_start_global).manhattanLength() >= 6:
            self._module_resize_started = True
        if not self._module_resize_started:
            return
        next_width, next_height = self._resize_units_for_global_pos(global_pos)
        if (
            next_width == self._module_resize_preview_width
            and next_height == self._module_resize_preview_height
        ):
            return
        self._module_resize_preview_width = next_width
        self._module_resize_preview_height = next_height
        self._apply_module_resize_preview(next_width, next_height)

    def _finish_module_drag(self, *, commit: bool, global_pos: QPoint | None = None) -> None:
        source_id = self._module_drag_source_id
        next_position = (
            self._drag_position_for_global_pos(global_pos)
            if commit and global_pos is not None
            else {
                "x": self._module_drag_start_column,
                "y": self._module_drag_start_row,
            }
        )
        original_positions = {
            module_id: dict(position)
            for module_id, position in self._module_drag_original_positions.items()
        }
        preview_changed = self._module_layout != original_positions
        self.releaseMouse()
        self._set_module_dragging(source_id, False)
        self._set_module_drop_target("")
        self._module_drag_source_id = ""
        self._module_drag_started = False
        self._module_drag_original_positions = {}
        if preview_changed:
            self._module_layout = original_positions
            self._sync_legacy_layout_views()
        if source_id and commit:
            changed = self._set_module_position(
                source_id,
                next_position["x"],
                next_position["y"],
            )
            if not changed and preview_changed:
                self._apply_responsive_layout(force=True, animate=True)
        elif preview_changed:
            self._apply_responsive_layout(force=True, animate=True)

    def _drag_position_for_global_pos(self, global_pos: QPoint) -> dict[str, int]:
        source_id = self._module_drag_source_id
        if not source_id:
            return {
                "x": self._module_drag_start_column,
                "y": self._module_drag_start_row,
            }
        delta = global_pos - self._module_drag_start_global
        column_delta = int(round(delta.x() / self._module_unit_step()))
        row_delta = int(round(delta.y() / self._module_height_step()))
        target_column = self._module_drag_start_column + column_delta
        target_row = self._module_drag_start_row + row_delta
        item = self._module_layout.get(source_id, {})
        width = int(item.get("w", self._default_module_width(source_id)))
        height = int(item.get("h", self._default_module_height(source_id)))
        return {
            "x": max(0, min(max(0, HOME_GRID_UNITS - width), target_column)),
            "y": max(0, min(max(0, HOME_GRID_MAX_ROWS - height), target_row)),
        }

    def _apply_module_drag_preview(self, position: dict[str, int]) -> None:
        source_id = self._module_drag_source_id
        if not source_id:
            return
        current = self._normalized_module_position(source_id)
        if current == position:
            return
        self._set_module_dragging(source_id, False)
        changed, next_layout = set_home_module_position(
            self._module_layout,
            source_id,
            position["x"],
            position["y"],
            self._visible_modules,
            self._layout_specs,
        )
        if not changed:
            self._set_module_dragging(source_id, True)
            return
        self._module_layout = next_layout
        self._sync_legacy_layout_views()
        self._module_drag_preview_column = position["x"]
        self._module_drag_preview_row = position["y"]
        self._apply_responsive_layout(force=True, animate=True)
        self._set_module_dragging(source_id, True)

    def _update_module_drag_for_global_pos(self, global_pos: QPoint) -> None:
        if not self._module_drag_source_id or self._layout_locked:
            return
        if (global_pos - self._module_drag_start_global).manhattanLength() >= 6:
            self._module_drag_started = True
        if self._module_drag_started:
            self._apply_module_drag_preview(
                self._drag_position_for_global_pos(global_pos)
            )

    def eventFilter(self, watched: object, event: object) -> bool:  # type: ignore[override]
        event_type = event.type()
        is_drag_handle = bool(getattr(watched, "property", lambda _name: False)("module_drag_handle"))
        is_drag_surface = bool(
            getattr(watched, "property", lambda _name: False)("module_drag_surface")
        )
        module_id = self._module_id_from_drag_widget(watched)
        local_pos = (
            event.position().toPoint()
            if hasattr(event, "position")
            else QPoint()
        )
        if (
            event_type == QEvent.Type.MouseMove
            and is_drag_surface
            and not self._module_drag_source_id
            and not self._module_resize_source_id
        ):
            widget = watched if isinstance(watched, QWidget) else None
            if widget is not None:
                right_edge, bottom_edge = self._module_resize_edges(widget, local_pos)
                cursor = (
                    Qt.CursorShape.SizeFDiagCursor
                    if right_edge and bottom_edge
                    else Qt.CursorShape.SizeHorCursor
                    if right_edge
                    else Qt.CursorShape.SizeVerCursor
                    if bottom_edge
                    else (
                        Qt.CursorShape.OpenHandCursor
                        if not self._layout_locked
                        else Qt.CursorShape.ArrowCursor
                    )
                )
                widget.setCursor(cursor)
            return False

        resize_right, resize_bottom = self._module_resize_edges(watched, local_pos)
        if (
            event_type == QEvent.Type.MouseButtonPress
            and is_drag_surface
            and (resize_right or resize_bottom)
            and not self._layout_locked
            and event.button() == Qt.MouseButton.LeftButton
            and module_id in self._visible_modules
        ):
            self._module_resize_source_id = module_id
            self._module_resize_started = False
            self._module_resize_start_global = self._global_pos_from_mouse_event(event)
            self._module_resize_start_width = self._column_span(
                self._definitions[module_id],
                max(1, self._layout_units),
            )
            self._module_resize_start_height = self._module_height_units(
                self._definitions[module_id]
            )
            self._module_resize_preview_width = self._module_resize_start_width
            self._module_resize_preview_height = self._module_resize_start_height
            self._module_resize_axis = (
                "both" if resize_right and resize_bottom else "w" if resize_right else "h"
            )
            self._module_resize_original_spans = self._copy_module_spans()
            self._set_module_resizing(module_id, True)
            self.grabMouse()
            event.accept()
            return True

        if (
            event_type == QEvent.Type.MouseButtonPress
            and (is_drag_handle or is_drag_surface)
            and not self._layout_locked
            and event.button() == Qt.MouseButton.LeftButton
            and module_id in self._visible_modules
        ):
            self._module_drag_source_id = module_id
            self._module_drag_started = False
            self._module_drag_start_global = self._global_pos_from_mouse_event(event)
            (
                self._module_drag_start_row,
                self._module_drag_start_column,
            ) = self._module_grid_position(module_id)
            self._module_drag_preview_row = self._module_drag_start_row
            self._module_drag_preview_column = self._module_drag_start_column
            self._module_drag_original_positions = self._copy_module_positions()
            self._set_module_dragging(module_id, True)
            self.grabMouse()
            event.accept()
            return True

        if (
            event_type == QEvent.Type.MouseMove
            and self._module_resize_source_id
            and not self._layout_locked
        ):
            global_pos = self._global_pos_from_mouse_event(event)
            self._update_module_resize_for_global_pos(global_pos)
            event.accept()
            return True

        if (
            event_type == QEvent.Type.MouseMove
            and self._module_drag_source_id
            and not self._layout_locked
        ):
            global_pos = self._global_pos_from_mouse_event(event)
            self._update_module_drag_for_global_pos(global_pos)
            event.accept()
            return True

        if (
            event_type == QEvent.Type.MouseButtonRelease
            and self._module_resize_source_id
            and event.button() == Qt.MouseButton.LeftButton
        ):
            global_pos = self._global_pos_from_mouse_event(event)
            self._finish_module_resize(
                commit=self._module_resize_started,
                global_pos=global_pos,
            )
            event.accept()
            return True

        if (
            event_type == QEvent.Type.MouseButtonRelease
            and self._module_drag_source_id
            and event.button() == Qt.MouseButton.LeftButton
        ):
            global_pos = self._global_pos_from_mouse_event(event)
            self._finish_module_drag(commit=self._module_drag_started, global_pos=global_pos)
            event.accept()
            return True

        return super().eventFilter(watched, event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self._module_resize_source_id:
            self._update_module_resize_for_global_pos(self._global_pos_from_mouse_event(event))
            event.accept()
            return
        if self._module_drag_source_id:
            self._update_module_drag_for_global_pos(self._global_pos_from_mouse_event(event))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if (
            self._module_resize_source_id
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self._finish_module_resize(
                commit=self._module_resize_started,
                global_pos=self._global_pos_from_mouse_event(event),
            )
            event.accept()
            return
        if (
            self._module_drag_source_id
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self._finish_module_drag(
                commit=self._module_drag_started,
                global_pos=self._global_pos_from_mouse_event(event),
            )
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _emit_settings_changed(self) -> None:
        settings = dict(self._settings)
        settings["modules"] = list(self._visible_modules)
        valid_layout = {
            module_id: dict(layout)
            for module_id, layout in self._module_layout.items()
            if module_id in self._definitions
        }
        if valid_layout:
            settings["module_layout"] = valid_layout
        else:
            settings.pop("module_layout", None)
        settings.pop("module_spans", None)
        settings.pop("module_positions", None)
        settings.setdefault("module_settings", {})
        settings["reduced_motion"] = self._reduced_motion
        settings["layout_locked"] = self._layout_locked
        self._settings = settings
        self.settings_changed.emit(dict(settings))

    def _columns_for_width(self, width: int) -> int:
        if width >= 1000:
            return 8
        if width >= 700:
            return 4
        return 1

    def _dashboard_mode_for_columns(self, columns: int) -> str:
        if columns >= 8:
            return "wide"
        if columns >= 4:
            return "medium"
        return "compact"

    def _apply_responsive_layout(
        self,
        *,
        force: bool = False,
        animate: bool = False,
    ) -> None:
        self._sync_content_layout()
        columns = self._columns_for_width(self._available_module_width())
        compact = columns == 1
        mode = self._dashboard_mode_for_columns(columns)
        if (
            not force
            and columns == self._layout_columns
            and columns == self._layout_units
            and compact == self._compact_modules
            and mode == self._dashboard_mode
        ):
            return
        self._layout_columns = columns
        self._layout_units = columns
        self._compact_modules = compact
        self._dashboard_mode = mode
        self.setProperty("layout_columns", columns)
        self.setProperty("layout_units", columns)
        self.setProperty("dashboard_mode", mode)
        self.setProperty("compact_modules", compact)
        should_animate = animate and bool(self._module_widgets)
        self._rebuild_module_grid(columns, compact, animate=should_animate)

    def _module_placements(
        self,
        columns: int,
    ) -> list[tuple[str, DashboardModuleDefinition, int, int, int, int]]:
        placements: list[tuple[str, DashboardModuleDefinition, int, int, int, int]] = []
        if columns <= 1:
            row = 0
            for module_id in self._visible_modules:
                definition = self._definitions.get(module_id)
                if definition is None:
                    continue
                placements.append((module_id, definition, row, 0, 1, 1))
                row += 1
            return placements

        for module_id in self._visible_modules:
            definition = self._definitions.get(module_id)
            if definition is None:
                continue
            item = self._module_layout.get(module_id)
            if item is None:
                self._normalize_current_module_layout()
                item = self._module_layout.get(module_id)
            if item is None:
                continue
            span = max(1, min(columns, int(item["w"])))
            height_units = self._module_height_units(definition)
            column = max(0, min(max(0, columns - span), int(item["x"])))
            row = max(0, min(max(0, HOME_GRID_MAX_ROWS - height_units), int(item["y"])))
            placements.append(
                (
                    module_id,
                    definition,
                    row,
                    column,
                    height_units,
                    span,
                )
            )
        return placements

    def _rebuild_module_grid(
        self,
        columns: int,
        compact: bool,
        *,
        animate: bool = False,
    ) -> None:
        placements = self._module_placements(columns)
        active_ids = {module_id for module_id, *_rest in placements}
        for module_id, widget in list(self._module_cards_by_id.items()):
            if module_id in active_ids:
                continue
            self._stop_widget_animations(widget)
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
            self._module_cards_by_id.pop(module_id, None)
            self._module_drag_handles.pop(module_id, None)
            self._module_render_modes.pop(module_id, None)
        self._module_widgets.clear()
        self._module_drop_target_id = ""

        max_row_end = 0
        for module_id, definition, row, column, row_span, span in placements:
            render_mode = self._render_mode_for(definition, columns, span)
            widget = self._module_cards_by_id.get(module_id)
            if widget is None or self._module_render_modes.get(module_id) != render_mode:
                if widget is not None:
                    self._stop_widget_animations(widget)
                    widget.hide()
                    widget.setParent(None)
                    widget.deleteLater()
                widget = self._create_module_widget(
                    definition,
                    compact=compact,
                    render_mode=render_mode,
                )
                widget.setParent(self._module_area)
                self._module_cards_by_id[module_id] = widget
                self._module_render_modes[module_id] = render_mode
            widget.show()
            self._apply_module_height(widget, definition)
            target_geometry = self._module_rect_for_grid(
                row=row,
                column=column,
                row_span=row_span,
                column_span=span,
                columns=columns,
            )
            self._set_module_geometry(widget, target_geometry, animate=animate)
            self._module_widgets.append(widget)
            max_row_end = max(max_row_end, row + row_span)
            if module_id == self._module_drag_source_id:
                self._set_module_dragging(module_id, True)
            if module_id == self._module_resize_source_id:
                self._set_module_resizing(module_id, True)
        total_height = (
            max_row_end * HOME_MODULE_MIN_HEIGHT
            + max(0, max_row_end - 1) * HOME_GRID_GAP
        )
        self._module_area.setMinimumHeight(total_height)
        if self._module_area.width() <= 0 or self._module_area.height() <= 0:
            self._module_area.resize(
                self._available_module_width() or HOME_CONTENT_RECOMMENDED_WIDTH,
                total_height,
            )

    def _module_rect_for_grid(
        self,
        *,
        row: int,
        column: int,
        row_span: int,
        column_span: int,
        columns: int,
    ) -> QRect:
        available_width = max(1, self._module_area.width() or self._available_module_width())
        total_gap = HOME_GRID_GAP * max(0, columns - 1)
        unit_width = max(1, int((available_width - total_gap) / max(1, columns)))
        x = column * (unit_width + HOME_GRID_GAP)
        y = row * (HOME_MODULE_MIN_HEIGHT + HOME_GRID_GAP)
        width = column_span * unit_width + max(0, column_span - 1) * HOME_GRID_GAP
        height = row_span * HOME_MODULE_MIN_HEIGHT + max(0, row_span - 1) * HOME_GRID_GAP
        return QRect(x, y, width, height)

    def _set_module_geometry(
        self,
        widget: QWidget,
        target_geometry: QRect,
        *,
        animate: bool,
    ) -> None:
        if self._reduced_motion or not animate or widget.geometry().isNull():
            self._stop_widget_animations(widget)
            widget.setGeometry(target_geometry)
            return
        if widget.geometry() == target_geometry:
            return
        self._stop_widget_animations(widget)
        animation = QPropertyAnimation(widget, b"geometry", widget)
        animation.setDuration(120)
        animation.setStartValue(widget.geometry())
        animation.setEndValue(target_geometry)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        def cleanup(active_animation: QPropertyAnimation = animation) -> None:
            self._release_animation(active_animation)

        animation.finished.connect(cleanup)
        self._animations.append(animation)
        animation.start()

    def _release_animation(
        self,
        animation: QPropertyAnimation,
        *,
        stop: bool = False,
    ) -> None:
        if animation in self._animations:
            self._animations.remove(animation)
        if stop:
            animation.stop()
        animation.deleteLater()

    def _stop_widget_animations(self, widget: QWidget) -> None:
        for animation in list(self._animations):
            if animation.parent() is widget:
                self._release_animation(animation, stop=True)

    def _column_span(self, definition: DashboardModuleDefinition, columns: int) -> int:
        if columns <= 1:
            return 1
        configured = self._module_layout.get(definition.id) or {}
        preferred_units = int(
            configured.get(
                "w",
                definition.layout_default_w,
            )
        )
        return max(1, min(columns, preferred_units))

    def _module_height_units(self, definition: DashboardModuleDefinition) -> int:
        configured = self._module_layout.get(definition.id) or {}
        default_height = definition.layout_default_h
        return max(1, min(3, int(configured.get("h", default_height))))

    def _apply_module_height(
        self,
        widget: QWidget,
        definition: DashboardModuleDefinition,
    ) -> None:
        height_units = self._module_height_units(definition)
        widget.setProperty("height_units", height_units)
        target_height = (
            height_units * HOME_MODULE_MIN_HEIGHT
            + max(0, height_units - 1) * HOME_GRID_GAP
        )
        widget.setMinimumHeight(target_height)
        widget.setMaximumHeight(target_height)

    def _animate_module_layout_change(self) -> None:
        if self._reduced_motion:
            return
        for widget in self._module_widgets:
            effect = QGraphicsOpacityEffect(widget)
            effect.setOpacity(0.72)
            widget.setGraphicsEffect(effect)
            animation = QPropertyAnimation(effect, b"opacity", widget)
            animation.setDuration(120)
            animation.setStartValue(0.72)
            animation.setEndValue(1.0)
            animation.setEasingCurve(QEasingCurve.Type.OutCubic)

            def cleanup(
                watched: QWidget = widget,
                active_animation: QPropertyAnimation = animation,
            ) -> None:
                watched.setGraphicsEffect(None)
                self._release_animation(active_animation)

            animation.finished.connect(cleanup)
            self._animations.append(animation)
            animation.start()

    def _render_mode_for(
        self,
        definition: DashboardModuleDefinition,
        columns: int,
        span: int,
    ) -> DashboardModuleRenderMode:
        if columns <= 1:
            return "compact"
        if definition.id == "calendar" and self._module_height_units(definition) <= 1:
            return "compact"
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
            return self._build_calendar_module(
                definition,
                compact=compact or render_mode == "compact",
                render_mode=render_mode,
            )
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
        title_text: str | None = None,
    ) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame(self)
        card.setObjectName(f"HomeModuleCard-{definition.id}")
        card.setProperty("class", "HomeModuleCard")
        card.setProperty("render_mode", render_mode)
        card.setProperty("empty_state", compact_empty)
        card.setProperty("compact_empty", compact_empty)
        if compact_empty:
            card.setMaximumHeight(132)
        elif compact_card:
            card.setMaximumHeight(164)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 11 if compact_empty else 13, 16, 11)
        layout.setSpacing(6 if compact_empty or compact_card else 8)
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(8)
        title = QLabel(title_text or definition.display_name, card)
        title.setProperty("class", "HomeModuleTitle")
        header_row.addWidget(title, 1)
        drag_handle = QPushButton("⋮⋮", card)
        drag_handle.setObjectName(f"HomeModuleDragHandle-{definition.id}")
        drag_handle.setProperty("class", "HomeModuleDragHandle")
        drag_handle.setProperty("module_id", definition.id)
        drag_handle.setProperty("module_drag_handle", True)
        drag_handle.setCursor(Qt.CursorShape.OpenHandCursor)
        drag_handle.setFixedHeight(24)
        drag_handle.setToolTip("拖动位置")
        drag_handle.setVisible(not self._layout_locked)
        drag_handle.installEventFilter(self)
        header_row.addWidget(drag_handle)
        layout.addLayout(header_row)
        card.setProperty("module_id", definition.id)
        card.setProperty("module_drag_surface", True)
        card.setProperty("dragging", False)
        card.setProperty("drop_target", False)
        card.setProperty("resizing", False)
        card.setCursor(
            Qt.CursorShape.OpenHandCursor
            if not self._layout_locked
            else Qt.CursorShape.ArrowCursor
        )
        card.installEventFilter(self)
        self._module_drag_handles[definition.id] = drag_handle
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
                "暂无最近项目。打开文件或刷新后会显示在这里。",
                muted=True,
            )
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
        today = date.today()
        reminders = [
            entry
            for entry in self._reminder_entries()
            if entry["date"] == selected.isoformat()
            and not entry["done"]
        ]
        title_text = "今日日程" if selected == today else f"{selected:%m-%d} 日程"
        card, layout = self._new_module_card(
            definition,
            render_mode=render_mode,
            compact_empty=not reminders,
            compact_card=compact,
            title_text=title_text,
        )
        selected_label = "今天" if selected == today else "选中日期"
        self._add_body_label(layout, selected_label, muted=True)
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
            add_button = self._inline_button("添加收藏", card)
            add_button.setObjectName("HomeBookmarkAddButton")
            add_button.clicked.connect(
                lambda _checked=False: self.home_settings_requested.emit("bookmarks")
            )
            layout.addWidget(add_button, alignment=Qt.AlignmentFlag.AlignLeft)
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
            configure_button.clicked.connect(
                lambda _checked=False: self.home_settings_requested.emit("weather")
            )
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
        self._update_clock()
        self._module_render_modes.clear()
        self._apply_responsive_layout(force=True, animate=True)
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

    def _weather_summary(self) -> tuple[str, str]:
        weather = self._module_dict_setting("weather", "weather")
        city = str(weather.get("city") or "").strip()
        if not city:
            return ("天气待设置", "在设置中添加城市")
        summary = str(weather.get("summary") or "等待天气数据").strip()
        return (city, summary)

    def _update_clock(self) -> None:
        today = date.today()
        current = QDateTime.currentDateTime()
        self._hero_time.setText(current.toString("HH:mm"))
        self._hero_date.setText(f"{today:%Y-%m-%d} · {current.toString('dddd')}")
        city, summary = self._weather_summary()
        self._weather_city_label.setText(city)
        self._weather_summary_label.setText(summary)

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
        def cleanup(active_animation: QPropertyAnimation = animation) -> None:
            self.setGraphicsEffect(None)
            self._release_animation(active_animation)

        animation.finished.connect(cleanup)
        self._animations.append(animation)
        animation.start()

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        self._apply_responsive_layout(force=True)
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
        modules = [
            entry.id for entry in self.module_definitions() if entry.default_visible
        ]
        specs = {
            entry.id: HomeLayoutSpec(
                default_w=entry.layout_default_w,
                default_h=entry.layout_default_h,
                min_w=entry.layout_min_w,
                max_w=entry.layout_max_w,
                min_h=entry.layout_min_h,
                max_h=entry.layout_max_h,
            )
            for entry in self.module_definitions()
        }
        return {
            "modules": modules,
            "module_layout": build_default_module_layout(modules, specs),
            "module_settings": {},
            "recent_items": [],
            "reminders": [],
            "bookmarks": [],
            "weather": {},
            "reduced_motion": False,
            "layout_locked": True,
        }

    def create_widget(self, settings: dict[str, object]) -> QWidget:
        merged = self.default_settings()
        merged.update(settings)
        return HomeDashboardWidget(merged, module_definitions=self.module_definitions())


class HomeModuleWidgetPlugin:
    """Standalone function-panel wrapper for a single Home dashboard module."""

    def __init__(self, module_definition: DashboardModuleDefinition) -> None:
        self._module_definition = module_definition
        self.id = f"home-{module_definition.id}"
        self.display_name = module_definition.display_name

    def definition(self) -> WidgetDefinition:
        visual = WidgetVisualPreset(
            preset_id=f"home-module-{self._module_definition.id}",
            accent_color=HOME_VISUAL.accent_color,
            background=HOME_VISUAL.background,
            foreground=HOME_VISUAL.foreground,
            secondary_foreground=HOME_VISUAL.secondary_foreground,
            card_background=HOME_VISUAL.card_background,
            recommended_width=320,
            recommended_height=220,
            min_width=240,
            min_height=140,
            max_width=420,
            max_height=320,
        )
        return WidgetDefinition(
            id=self.id,
            display_name=self.display_name,
            description=f"独立显示首页模块：{self.display_name}",
            preview_title=self.display_name,
            preview_body=self._module_definition.empty_state,
            visual=visual,
        )

    def default_settings(self) -> dict[str, object]:
        settings = HomeWidgetPlugin().default_settings()
        settings["modules"] = [self._module_definition.id]
        return settings

    def create_widget(self, settings: dict[str, object]) -> QWidget:
        merged = self.default_settings()
        merged.update(settings)
        widget = self._module_definition.create_widget(
            merged,
            compact=False,
            render_mode=self._module_definition.render_mode,
        )
        widget.setStyleSheet(
            """
            QFrame.HomeModuleCard {
                background: rgba(24, 27, 36, 235);
                border: 1px solid rgba(255, 255, 255, 28);
                border-radius: 14px;
            }
            QLabel.HomeModuleTitle {
                color: #f8fafc;
                font-size: 17px;
                font-weight: 700;
            }
            QLabel.HomeModuleItem {
                color: rgba(248, 250, 252, 235);
                font-size: 13px;
            }
            QLabel.HomeMuted {
                color: rgba(248, 250, 252, 163);
                font-size: 13px;
            }
            """
        )
        widget.setMinimumSize(240, 140)
        widget.setMaximumSize(420, 320)
        return widget
