"""Frameless translucent panel shell with tab header controls and an item grid."""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QCloseEvent, QIcon, QMouseEvent, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from desktop_tidy.domain.models import PanelGeometry, PanelGroup, PanelTab
from desktop_tidy.domain.workspace import WorkspaceModel
from desktop_tidy.services.screens import available_screen_geometries, screen_id_containing_point
from desktop_tidy.services.window_styles import hide_window_from_taskbar
from desktop_tidy.ui.item_grid import ITEM_MIME_TYPE, ItemGridWidget, _drag_dbg, paths_from_item_mime
from desktop_tidy.ui.widget_plugins import BuiltinWidgetRegistry

_CORNER_RADIUS = 12
_PANEL_SCREEN_BOTTOM_INSET = 8
_HEADER_DRAG_MARGIN = 40
_RESIZE_MARGIN = 16
_TOP_RESIZE_MARGIN = 6
_MIN_PANEL_WIDTH = 240
_MIN_PANEL_HEIGHT = 160
_SNAP_MARGIN = 18
_DEFAULT_DETACHED_RW = 0.28
_DEFAULT_DETACHED_RH = 0.42
_FALLBACK_SCREEN = QRect(0, 0, 1920, 1080)
_TITLEBAR_LOCK_ICON_SIZE = 16
_lock_icon_unlocked: QIcon | None = None
_lock_icon_locked: QIcon | None = None


def _paint_lock_titlebar_icon(*, locked: bool) -> QIcon:
    size = _TITLEBAR_LOCK_ICON_SIZE
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(QColor(255, 255, 255))
    pen.setWidthF(1.5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    body_left = 4.5
    body_right = 11.5
    body_top = 8.5
    body_bottom = 14.0
    body_path = QPainterPath()
    body_path.addRoundedRect(
        QRectF(body_left, body_top, body_right - body_left, body_bottom - body_top),
        1.4,
        1.4,
    )
    painter.drawPath(body_path)

    shackle_left = body_left + 1.0
    shackle_right = body_right - 1.0
    shackle_top = 3.0
    shackle_rect = QRectF(
        shackle_left - 0.5,
        shackle_top,
        shackle_right - shackle_left + 1.0,
        body_top - shackle_top + 0.5,
    )
    shackle = QPainterPath()
    shackle.moveTo(shackle_left, body_top)
    if locked:
        shackle.arcTo(shackle_rect, 180.0, -180.0)
        shackle.lineTo(shackle_right, body_top)
    else:
        shackle.arcTo(shackle_rect, 180.0, -135.0)
    painter.drawPath(shackle)
    painter.end()
    return QIcon(pixmap)


def _unlocked_lock_icon() -> QIcon:
    global _lock_icon_unlocked
    if _lock_icon_unlocked is None:
        _lock_icon_unlocked = _paint_lock_titlebar_icon(locked=False)
    return _lock_icon_unlocked


def _locked_lock_icon() -> QIcon:
    global _lock_icon_locked
    if _lock_icon_locked is None:
        _lock_icon_locked = _paint_lock_titlebar_icon(locked=True)
    return _lock_icon_locked


class _TabDetachPreview(QWidget):
    """Lightweight non-interactive chip shown while a tab is dragged outside the panel."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        self._label = QLabel(self)
        self._label.setStyleSheet("color: #ffffff; background: transparent;")
        layout.addWidget(self._label)
        self.setStyleSheet(
            "background: rgba(20, 20, 20, 0.72); border-radius: 8px;"
        )

    def set_title(self, title: str) -> None:
        self._label.setText(title)
        self.adjustSize()

    def move_near_global(self, global_point: QPoint) -> None:
        self.move(global_point + QPoint(14, 14))


class _ResizeRegion(Enum):
    NONE = "none"
    LEFT = "left"
    RIGHT = "right"
    TOP = "top"
    BOTTOM = "bottom"
    TOP_LEFT = "top_left"
    TOP_RIGHT = "top_right"
    BOTTOM_LEFT = "bottom_left"
    BOTTOM_RIGHT = "bottom_right"


class _TabButton(QPushButton):
    """标签头按钮，同时作为图标的放置目标(把图标拖到其它标签即归类过去)。"""

    def __init__(
        self,
        text: str,
        parent: QWidget | None = None,
        *,
        on_item_drag_enter=None,
        on_item_dropped=None,
    ) -> None:
        super().__init__(text, parent)
        self._on_item_drag_enter = on_item_drag_enter
        self._on_item_dropped = on_item_dropped
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        _drag_dbg("tab.dragEnter item?", event.mimeData().hasFormat(ITEM_MIME_TYPE))
        if event.mimeData().hasFormat(ITEM_MIME_TYPE):
            event.acceptProposedAction()
            if self._on_item_drag_enter is not None:
                self._on_item_drag_enter()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.mimeData().hasFormat(ITEM_MIME_TYPE):
            event.acceptProposedAction()
            if self._on_item_drag_enter is not None:
                self._on_item_drag_enter()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        md = event.mimeData()
        _drag_dbg("tab.drop item?", md.hasFormat(ITEM_MIME_TYPE))
        if md.hasFormat(ITEM_MIME_TYPE) and self._on_item_dropped is not None:
            paths = paths_from_item_mime(bytes(md.data(ITEM_MIME_TYPE)))
            if not paths:
                return
            self._on_item_dropped(paths)
            event.acceptProposedAction()
            return
        super().dropEvent(event)


class PanelGroupWidget(QWidget):
    changed = Signal()
    active_tab_changed = Signal(str, str)
    state_changed = Signal(str)
    geometry_changed = Signal()
    appearance_changed = Signal()
    layout_gesture_started = Signal(str)
    settings_requested = Signal(str)
    organize_requested = Signal(str)
    tab_detach_requested = Signal(str, object)
    tab_reordered = Signal(str)
    item_dropped_on_tab = Signal(object, str)
    item_drag_over_tab = Signal(str)
    group_merge_requested = Signal(str, int, int)
    close_requested = Signal()
    widget_settings_changed = Signal(str, object)
    widget_item_open_requested = Signal(str)
    widget_url_open_requested = Signal(str)
    widget_weather_refresh_requested = Signal(str)
    widget_recent_refresh_requested = Signal()
    widget_recent_clear_requested = Signal()

    def __init__(
        self,
        group: PanelGroup,
        tabs: list[PanelTab],
        *,
        workspace: WorkspaceModel | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._group = group
        self._workspace = workspace
        self._tabs_by_id = {tab.id: tab for tab in tabs}
        self._editing_tab_id = ""
        self._locked = group.locked
        self._collapsed = group.collapsed
        self._expanded_content_height = 480
        self._expanded_rh = group.geometry.rh
        self._tab_buttons: dict[str, QPushButton] = {}
        self._drag_tab_id = ""
        self._tab_drag_active = False
        self._tab_reorder_dirty = False
        self._header_drag_active = False
        self._resize_active = False
        self._resize_region = _ResizeRegion.NONE
        self._drag_start_global = QPoint()
        self._start_geometry = PanelGeometry()
        self._start_frame = QRect()
        self._snap_rects: list[QRect] = []
        self._screen_geometries: dict[str, QRect] = available_screen_geometries()
        self._suppress_click_tab_id = ""
        self._detach_preview = _TabDetachPreview(self)
        self._detach_preview.hide()
        self._widget_registry = BuiltinWidgetRegistry()
        self._widget_content: QWidget | None = None
        self._widget_content_type = ""
        self._widget_content_settings_fingerprint = ""

        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnBottomHint
        )
        self.setAcceptDrops(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self._apply_taskbar_visibility_policy()

        header_row = QHBoxLayout()
        header_row.setSpacing(6)

        self._tab_bar = QHBoxLayout()
        self._tab_bar.setSpacing(4)
        header_row.addLayout(self._tab_bar, stretch=1)

        self.collapse_button = QPushButton(self)
        self.lock_button = QPushButton(self)
        self.add_button = QPushButton(self)
        self.organize_button = QPushButton(self)
        self.delete_button = QPushButton(self)
        self.more_button = QPushButton(self)
        for button in (
            self.collapse_button,
            self.lock_button,
            self.add_button,
            self.organize_button,
            self.delete_button,
            self.more_button,
        ):
            button.setFixedHeight(28)
            button.setSizePolicy(
                QSizePolicy.Policy.Fixed,
                QSizePolicy.Policy.Fixed,
            )
            button.setStyleSheet(
                "QPushButton { color: #ffffff; background: rgba(255,255,255,0.12); "
                "border: none; border-radius: 6px; padding: 0 8px; }"
                "QPushButton:hover { background: rgba(255,255,255,0.22); }"
                "QPushButton:pressed { background: rgba(255,255,255,0.34); }"
                "QPushButton:disabled { color: rgba(255,255,255,0.32); "
                "background: rgba(255,255,255,0.07); }"
            )
        header_row.addWidget(self.collapse_button)
        header_row.addWidget(self.lock_button)
        header_row.addWidget(self.add_button)
        header_row.addWidget(self.organize_button)
        header_row.addWidget(self.delete_button)
        header_row.addWidget(self.more_button)

        self.inline_title_editor = QLineEdit(self)
        self.inline_title_editor.hide()
        self.inline_title_editor.setObjectName("inlineTabTitleEditor")
        self.inline_title_editor.setStyleSheet(
            "QLineEdit#inlineTabTitleEditor {"
            "  color: #ffffff;"
            "  background: rgba(18, 18, 22, 0.92);"
            "  border: 1px solid rgba(255, 255, 255, 0.72);"
            "  border-radius: 6px;"
            "  padding: 2px 8px;"
            "}"
        )
        self.inline_title_editor.returnPressed.connect(self.commit_inline_title_edit)
        self.inline_title_editor.editingFinished.connect(self._on_inline_edit_finished)

        self._item_grid = ItemGridWidget(self, active_tab_id=group.active_tab_id)
        self._item_grid.setStyleSheet("background: transparent;")
        self._item_grid.set_item_icon_size(
            group.appearance.item_icon_size,
            notify=False,
        )
        self._item_grid.item_icon_size_changed.connect(self._on_item_icon_size_changed)
        self._item_grid.cells_rebuilt.connect(self._install_content_resize_filters)
        self._content_host = QWidget(self)
        self._content_host.setStyleSheet("background: transparent;")
        self._content_layout = QVBoxLayout(self._content_host)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.addWidget(self._item_grid)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(16, 14, 16, 16)
        self._layout.setSpacing(10)
        self._layout.addLayout(header_row)
        self._layout.addWidget(self._content_host, stretch=1)

        self.add_button.clicked.connect(self._on_add_clicked)
        self.organize_button.clicked.connect(
            lambda: self.organize_requested.emit(self._group.id)
        )
        self.delete_button.clicked.connect(self._on_delete_clicked)
        self.more_button.clicked.connect(
            lambda: self.settings_requested.emit(self._group.id)
        )
        self.collapse_button.clicked.connect(self._on_collapse_clicked)
        self.lock_button.clicked.connect(self._on_lock_clicked)

        self._rebuild_tab_buttons()
        self._render_active_content()
        self._install_content_resize_filters()
        self._apply_geometry_from_model()
        self._apply_collapsed_state()
        self._render_titlebar_control_states()

    def _on_item_icon_size_changed(self, size: int) -> None:
        self._group.appearance.item_icon_size = size
        self.appearance_changed.emit()

    @property
    def group_id(self) -> str:
        return self._group.id

    @property
    def background_opacity(self) -> float:
        return self._group.appearance.background_opacity

    @property
    def item_grid(self) -> ItemGridWidget:
        return self._item_grid

    @property
    def active_tab_id(self) -> str:
        return self._group.active_tab_id

    @property
    def screen_id(self) -> str:
        return self._group.screen_id

    @property
    def is_locked(self) -> bool:
        return self._locked

    @property
    def is_collapsed(self) -> bool:
        return self._collapsed

    def header_height(self) -> int:
        return 14 + 28 + 14

    def active_tab_title(self) -> str:
        tab = self._tabs_by_id.get(self._group.active_tab_id)
        return tab.name if tab is not None else ""

    def active_tab_content_kind(self) -> str:
        tab = self._tabs_by_id.get(self._group.active_tab_id)
        return tab.content_kind if tab is not None else "items"

    def _render_active_content(self) -> None:
        tab = self._tabs_by_id.get(self._group.active_tab_id)
        if tab is not None and tab.content_kind == "widget":
            self._show_widget_content(tab.widget_type, tab.widget_settings)
            self.organize_button.setEnabled(False)
            return
        self._show_item_content()
        self.organize_button.setEnabled(True)

    def _show_item_content(self) -> None:
        if self._widget_content is not None:
            self._widget_content.hide()
        self._item_grid.show()

    def _show_widget_content(
        self,
        widget_type: str,
        settings: dict[str, object],
    ) -> None:
        settings_fingerprint = json.dumps(
            settings,
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        )
        needs_rebuild = (
            self._widget_content is None
            or self._widget_content_type != widget_type
            or self._widget_content_settings_fingerprint != settings_fingerprint
        )
        if needs_rebuild:
            if self._widget_content is not None:
                self._content_layout.removeWidget(self._widget_content)
                self._widget_content.deleteLater()
            plugin = self._widget_registry.get(widget_type)
            self._widget_content = plugin.create_widget(settings)
            self._widget_content_type = widget_type
            self._widget_content_settings_fingerprint = settings_fingerprint
            self._widget_content.setParent(self._content_host)
            settings_changed = getattr(self._widget_content, "settings_changed", None)
            if settings_changed is not None:
                try:
                    settings_changed.connect(self._forward_widget_settings_changed)
                except TypeError:
                    pass
            item_open_requested = getattr(self._widget_content, "item_open_requested", None)
            if item_open_requested is not None:
                try:
                    item_open_requested.connect(self.widget_item_open_requested.emit)
                except TypeError:
                    pass
            url_open_requested = getattr(self._widget_content, "url_open_requested", None)
            if url_open_requested is not None:
                try:
                    url_open_requested.connect(self.widget_url_open_requested.emit)
                except TypeError:
                    pass
            weather_refresh_requested = getattr(
                self._widget_content,
                "weather_refresh_requested",
                None,
            )
            if weather_refresh_requested is not None:
                try:
                    weather_refresh_requested.connect(
                        self.widget_weather_refresh_requested.emit
                    )
                except TypeError:
                    pass
            recent_refresh_requested = getattr(
                self._widget_content,
                "recent_refresh_requested",
                None,
            )
            if recent_refresh_requested is not None:
                try:
                    recent_refresh_requested.connect(
                        self.widget_recent_refresh_requested.emit
                    )
                except TypeError:
                    pass
            recent_clear_requested = getattr(
                self._widget_content,
                "recent_clear_requested",
                None,
            )
            if recent_clear_requested is not None:
                try:
                    recent_clear_requested.connect(
                        self.widget_recent_clear_requested.emit
                    )
                except TypeError:
                    pass
            if widget_type == "home":
                self._widget_content.setSizePolicy(
                    QSizePolicy.Policy.Expanding,
                    QSizePolicy.Policy.Expanding,
                )
                self._widget_content.setMaximumSize(16777215, 16777215)
                self._content_layout.addWidget(self._widget_content, 1)
            else:
                self._content_layout.addWidget(
                    self._widget_content,
                    alignment=Qt.AlignmentFlag.AlignCenter,
                )
        self._item_grid.hide()
        if self._widget_content is not None:
            self._widget_content.show()

    def _forward_widget_settings_changed(self, settings: object) -> None:
        tab_id = self._group.active_tab_id
        if tab_id:
            self.widget_settings_changed.emit(tab_id, settings)

    def detach_preview_visible(self) -> bool:
        return self._detach_preview.isVisible()

    def tab_button_ids(self) -> list[str]:
        return list(self._group.tab_ids)

    def set_snap_rects(self, rects: list[QRect]) -> None:
        self._snap_rects = [QRect(rect) for rect in rects]

    def set_screen_geometries(self, geometries: dict[str, QRect]) -> None:
        self._screen_geometries = {
            screen_id: QRect(geometry)
            for screen_id, geometry in geometries.items()
            if geometry.isValid() and geometry.width() > 0 and geometry.height() > 0
        }
        if not self._screen_geometries:
            self._screen_geometries = available_screen_geometries()

    def activate_tab(self, tab_id: str, *, notify: bool = True) -> None:
        if tab_id not in self._group.tab_ids:
            return
        self._item_grid.close_open_group_folder()
        self._group.active_tab_id = tab_id
        self._item_grid.set_active_tab_id(tab_id)
        if list(self._tab_buttons.keys()) != list(self._group.tab_ids):
            self._rebuild_tab_buttons()
        else:
            self._sync_tab_button_states()
        self._render_active_content()
        if notify:
            self.active_tab_changed.emit(self._group.id, tab_id)

    def _on_item_drag_enter_tab(self, tab_id: str) -> None:
        if tab_id not in self._group.tab_ids:
            return
        if tab_id == self._group.active_tab_id:
            return
        self.activate_tab(tab_id, notify=False)
        self.item_drag_over_tab.emit(tab_id)

    def _on_item_dropped_on_tab_button(self, paths: list[Path], tab_id: str) -> None:
        if tab_id not in self._group.tab_ids:
            return
        self.activate_tab(tab_id, notify=False)
        self.item_dropped_on_tab.emit(paths, tab_id)

    def _tab_id_at_panel_point(self, local_point: QPoint) -> str:
        for tab_id, button in self._tab_buttons.items():
            button_rect = QRect(button.mapTo(self, QPoint(0, 0)), button.size())
            if button_rect.adjusted(-6, -8, 6, 8).contains(local_point):
                return tab_id
        return ""

    def _handle_item_drag_over_panel(self, local_point: QPoint) -> bool:
        tab_id = self._tab_id_at_panel_point(local_point)
        if not tab_id:
            return False
        self._on_item_drag_enter_tab(tab_id)
        return True

    def dragEnterEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.mimeData().hasFormat(ITEM_MIME_TYPE) and self._handle_item_drag_over_panel(
            event.position().toPoint()
        ):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.mimeData().hasFormat(ITEM_MIME_TYPE) and self._handle_item_drag_over_panel(
            event.position().toPoint()
        ):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        md = event.mimeData()
        if md.hasFormat(ITEM_MIME_TYPE):
            tab_id = self._tab_id_at_panel_point(event.position().toPoint())
            if tab_id:
                paths = paths_from_item_mime(bytes(md.data(ITEM_MIME_TYPE)))
                if paths:
                    self._on_item_dropped_on_tab_button(paths, tab_id)
                    event.acceptProposedAction()
                    return
        super().dropEvent(event)

    def reload_from_model(self) -> None:
        if self._workspace is None:
            return
        self._tabs_by_id = {tab.id: tab for tab in self._workspace.config.panel_tabs}
        self._group = self._workspace.group(self._group.id)
        self._locked = self._group.locked
        self._collapsed = self._group.collapsed
        self._item_grid.set_item_icon_size(
            self._group.appearance.item_icon_size,
            notify=False,
        )
        if list(self._group.tab_ids) != list(self._tab_buttons.keys()):
            self._rebuild_tab_buttons()
        else:
            self._sync_tab_button_states()
        self._render_active_content()
        self._apply_geometry_from_model()
        self._apply_collapsed_state()
        self._render_titlebar_control_states()
        self.update()

    def _standard_icon(self, pixmap: QStyle.StandardPixmap) -> QIcon:
        style = self.style()
        if style is not None:
            return style.standardIcon(pixmap)
        return QIcon()

    def _render_titlebar_control_states(self) -> None:
        if self._collapsed:
            self.collapse_button.setIcon(
                self._standard_icon(QStyle.StandardPixmap.SP_ArrowDown)
            )
            self.collapse_button.setText("")
            self.collapse_button.setToolTip("展开面板")
            self.collapse_button.setAccessibleName("展开面板")
        else:
            self.collapse_button.setIcon(
                self._standard_icon(QStyle.StandardPixmap.SP_ArrowUp)
            )
            self.collapse_button.setText("")
            self.collapse_button.setToolTip("收起面板")
            self.collapse_button.setAccessibleName("收起面板")

        if self._locked:
            self.lock_button.setIcon(_locked_lock_icon())
            self.lock_button.setText("")
            self.lock_button.setToolTip("解锁面板位置")
            self.lock_button.setAccessibleName("解锁面板位置")
        else:
            self.lock_button.setIcon(_unlocked_lock_icon())
            self.lock_button.setText("")
            self.lock_button.setToolTip("锁定面板位置")
            self.lock_button.setAccessibleName("锁定面板位置")

        self.add_button.setText("+")
        self.add_button.setIcon(QIcon())
        self.add_button.setToolTip("新建标签")
        self.add_button.setAccessibleName("新建标签")

        self.organize_button.setText("整理")
        self.organize_button.setIcon(QIcon())
        self.organize_button.setToolTip("一键整理")
        self.organize_button.setAccessibleName("一键整理")

        self.delete_button.setText("")
        self.delete_button.setIcon(
            self._standard_icon(QStyle.StandardPixmap.SP_TrashIcon)
        )
        self.delete_button.setToolTip("删除当前标签")
        self.delete_button.setAccessibleName("删除当前标签")
        self.delete_button.setEnabled(self._can_delete_active_tab())

        self.more_button.setText("...")
        self.more_button.setIcon(QIcon())
        self.more_button.setToolTip("更多设置")
        self.more_button.setAccessibleName("更多设置")

    def _sync_tab_button_states(self) -> None:
        for tab_id, button in self._tab_buttons.items():
            button.setChecked(tab_id == self._group.active_tab_id)
            tab = self._tabs_by_id.get(tab_id)
            label = tab.name if tab is not None else tab_id
            if button.text() != label:
                button.setText(label)
            button.setToolTip(label)

    def complete_tab_detach_gesture(self, tab_id: str, global_point: tuple[int, int]) -> None:
        if self._locked or tab_id not in self._group.tab_ids:
            return
        if len(self._group.tab_ids) <= 1:
            return
        geometry = self._default_detach_geometry(global_point)
        self.tab_detach_requested.emit(tab_id, geometry)

    def complete_header_drag_at_global_point(self, global_point: tuple[int, int]) -> None:
        if self._locked:
            return
        self.group_merge_requested.emit(
            self._group.id,
            int(global_point[0]),
            int(global_point[1]),
        )

    def _sync_from_workspace(self) -> None:
        if self._workspace is None:
            return
        self._tabs_by_id = {tab.id: tab for tab in self._workspace.config.panel_tabs}
        self._group = self._workspace.group(self._group.id)

    def start_inline_title_edit(self, tab_id: str) -> None:
        self._sync_from_workspace()
        tab = self._tabs_by_id.get(tab_id)
        if tab is None:
            return
        self._editing_tab_id = tab_id
        self.inline_title_editor.setText(tab.name)
        self._position_inline_title_editor(tab_id)
        self.inline_title_editor.show()
        self.inline_title_editor.raise_()
        self.inline_title_editor.setFocus()
        self.inline_title_editor.selectAll()

    def _position_inline_title_editor(self, tab_id: str) -> None:
        button = self._tab_buttons.get(tab_id)
        if button is None:
            return
        tab_rect = QRect(button.mapTo(self, QPoint(0, 0)), button.size())
        self.inline_title_editor.setGeometry(tab_rect.adjusted(0, 0, 0, 0))

    def commit_inline_title_edit(self) -> None:
        if not self._editing_tab_id:
            return
        name = self.inline_title_editor.text()
        if self._workspace is not None:
            self._workspace.rename_tab(self._editing_tab_id, name)
            tab = self._workspace.tab(self._editing_tab_id)
            self._tabs_by_id[tab.id] = tab
        elif self._editing_tab_id in self._tabs_by_id:
            label = name.strip() or "未命名面板"
            self._tabs_by_id[self._editing_tab_id].name = label
        self.inline_title_editor.hide()
        self._editing_tab_id = ""
        self._rebuild_tab_buttons()
        self.changed.emit()

    def set_locked(self, value: bool) -> None:
        self._locked = value
        self._group.locked = value
        self._render_titlebar_control_states()

    def set_collapsed(self, value: bool) -> None:
        if value == self._collapsed:
            return
        if value:
            self._expanded_content_height = max(self.height(), self._expanded_content_height)
            self._collapsed = True
            self._group.collapsed = True
        else:
            self._collapsed = False
            self._group.collapsed = False
        self._apply_collapsed_state()
        self._render_titlebar_control_states()

    def _on_inline_edit_finished(self) -> None:
        if self.inline_title_editor.isVisible():
            self.commit_inline_title_edit()

    def _on_add_clicked(self) -> None:
        if self._workspace is None:
            return
        tab = self._workspace.add_tab(self._group.id, "新标签")
        self._tabs_by_id[tab.id] = tab
        self._group = self._workspace.group(self._group.id)
        self.activate_tab(tab.id, notify=False)
        self.start_inline_title_edit(tab.id)
        self.changed.emit()

    def _on_delete_clicked(self) -> None:
        if self._workspace is None or not self._group.active_tab_id:
            return
        tab_id = self._group.active_tab_id
        if not self._workspace.can_delete_tab(tab_id):
            self._render_titlebar_control_states()
            return
        group_id = self._group.id
        deleted = self._workspace.delete_tab(tab_id)
        if not deleted:
            self._render_titlebar_control_states()
            return
        if group_id not in {group.id for group in self._workspace.config.panel_groups}:
            self.changed.emit()
            return
        self._tabs_by_id = {tab.id: tab for tab in self._workspace.config.panel_tabs}
        self._group = self._workspace.group(group_id)
        self._rebuild_tab_buttons()
        self._render_titlebar_control_states()
        self.changed.emit()

    def _on_collapse_clicked(self) -> None:
        self.set_collapsed(not self._collapsed)
        self.state_changed.emit(self._group.id)

    def _on_lock_clicked(self) -> None:
        self.set_locked(not self._locked)
        self.state_changed.emit(self._group.id)

    def _dispose_tab_button(self, button: QPushButton) -> None:
        button.removeEventFilter(self)
        button.hide()
        button.setParent(None)
        button.deleteLater()

    def _rebuild_tab_buttons(self) -> None:
        for button in list(self._tab_buttons.values()):
            self._dispose_tab_button(button)
        self._tab_buttons.clear()
        while self._tab_bar.count():
            self._tab_bar.takeAt(0)
        for tab_id in self._group.tab_ids:
            tab = self._tabs_by_id.get(tab_id)
            label = tab.name if tab is not None else tab_id
            button = _TabButton(
                label,
                self,
                on_item_drag_enter=lambda tid=tab_id: self._on_item_drag_enter_tab(tid),
                on_item_dropped=lambda paths, tid=tab_id: self._on_item_dropped_on_tab_button(
                    paths, tid
                ),
            )
            button.setCheckable(True)
            button.setChecked(tab_id == self._group.active_tab_id)
            button.setMinimumWidth(0)
            button.setSizePolicy(
                QSizePolicy.Policy.Ignored,
                QSizePolicy.Policy.Fixed,
            )
            button.setToolTip(label)
            button.setStyleSheet(
                "QPushButton { color: #d8d8d8; background: transparent; border: none; "
                "padding: 4px 8px; }"
                "QPushButton:checked { color: #ffffff; font-weight: 600; "
                "border-bottom: 2px solid #ffffff; }"
            )
            button.clicked.connect(
                lambda _checked=False, tid=tab_id: self._on_tab_button_clicked(tid)
            )
            button.installEventFilter(self)
            self._tab_buttons[tab_id] = button
            self._tab_bar.addWidget(button, stretch=1)

    def _on_tab_button_clicked(self, tab_id: str) -> None:
        if self._suppress_click_tab_id == tab_id:
            self._suppress_click_tab_id = ""
            return
        self.activate_tab(tab_id)

    def _apply_collapsed_state(self) -> None:
        show_content = not self._collapsed
        self._content_host.setVisible(show_content)
        if self._collapsed:
            self.inline_title_editor.hide()
        elif self._editing_tab_id and self.inline_title_editor.isVisible():
            self._position_inline_title_editor(self._editing_tab_id)
        for button in self._tab_buttons.values():
            button.setVisible(True)
        if self._collapsed:
            self.setMinimumHeight(self.header_height())
            self.setMaximumHeight(self.header_height() + 8)
            self.resize(self.width(), self.header_height())
        else:
            self.setMinimumHeight(self.header_height())
            self.setMaximumHeight(16777215)
            screen = self._screen_geometry()
            model_height = max(
                _MIN_PANEL_HEIGHT,
                int(screen.height() * self._group.geometry.rh),
            )
            target_height = max(
                self._expanded_content_height,
                model_height,
                _MIN_PANEL_HEIGHT,
            )
            self.resize(self.width(), target_height)

    def _screen_geometry(self, screen_id: str | None = None) -> QRect:
        if not self._screen_geometries:
            self._screen_geometries = available_screen_geometries()
        target_id = screen_id or self._group.screen_id or "primary"
        if target_id in self._screen_geometries:
            return QRect(self._screen_geometries[target_id])
        if "primary" in self._screen_geometries:
            return QRect(self._screen_geometries["primary"])
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            if available.isValid() and available.width() > 0 and available.height() > 0:
                return available
            return screen.geometry()
        return QRect(_FALLBACK_SCREEN)

    def _screen_id_for_global_point(self, global_point: QPoint) -> str:
        return screen_id_containing_point(
            global_point,
            self._screen_geometries,
            fallback=self._group.screen_id or "primary",
        )

    def _screen_id_for_frame(self, frame: QRect) -> str:
        return self._screen_id_for_global_point(frame.center())

    def _screen_bottom_limit(self, screen: QRect) -> int:
        """面板底边允许到达的最大 y(留出间距,避免圆角/边框被任务栏裁切)。"""
        return screen.bottom() - _PANEL_SCREEN_BOTTOM_INSET

    def _clamp_frame_bottom_to_screen(self, frame: QRect, screen: QRect) -> QRect:
        limit = self._screen_bottom_limit(screen)
        if frame.bottom() > limit:
            frame.moveBottom(limit)
        return frame

    def _apply_geometry_from_model(self) -> None:
        screen = self._screen_geometry(self._group.screen_id)
        geometry = self._group.geometry
        width = max(_MIN_PANEL_WIDTH, int(screen.width() * geometry.rw))
        expanded_height = max(_MIN_PANEL_HEIGHT, int(screen.height() * geometry.rh))
        self._expanded_rh = geometry.rh
        self._expanded_content_height = expanded_height
        height = self.header_height() if self._collapsed else expanded_height
        x = screen.x() + int(screen.width() * geometry.rx)
        y = screen.y() + int(screen.height() * geometry.ry)
        frame = QRect(x, y, width, height)
        frame = self._clamp_frame_bottom_to_screen(frame, screen)
        self.setGeometry(frame)

    def _frame_height_matches_expanded_rh(self, frame_height: int) -> bool:
        screen_id = self._group.screen_id or "primary"
        screen = self._screen_geometry(screen_id)
        if screen.height() <= 0:
            return True
        expected = int(screen.height() * self._expanded_rh)
        return abs(frame_height - expected) <= 8

    def _persist_geometry_from_widget(self, *, update_rh: bool = False) -> None:
        frame = self.frameGeometry()
        screen_id = self._screen_id_for_frame(frame)
        screen = self._screen_geometry(screen_id)
        self._group.screen_id = screen_id
        if screen.width() <= 0 or screen.height() <= 0:
            return
        rx = (frame.x() - screen.x()) / screen.width()
        ry = (frame.y() - screen.y()) / screen.height()
        rw = frame.width() / screen.width()
        if update_rh and not self._collapsed:
            self._expanded_rh = frame.height() / screen.height()
            self._expanded_content_height = frame.height()
        rh = self._expanded_rh
        self._group.geometry = self._clamp_geometry(PanelGeometry(rx, ry, rw, rh))

    @staticmethod
    def _clamp_geometry(geometry: PanelGeometry) -> PanelGeometry:
        rw = max(0.05, min(1.0, geometry.rw))
        rh = max(0.05, min(1.0, geometry.rh))
        rx = max(0.0, min(1.0 - rw, geometry.rx))
        ry = max(0.0, min(1.0 - rh, geometry.ry))
        if rx + rw > 1.0:
            rx = max(0.0, 1.0 - rw)
        if ry + rh > 1.0:
            ry = max(0.0, 1.0 - rh)
        return PanelGeometry(rx, ry, rw, rh)

    def _default_detach_geometry(self, global_point: tuple[int, int]) -> PanelGeometry:
        screen_id = self._group.screen_id or "primary"
        screen = self._screen_geometry(screen_id)
        width = max(_MIN_PANEL_WIDTH, int(screen.width() * _DEFAULT_DETACHED_RW))
        height = max(_MIN_PANEL_HEIGHT, int(screen.height() * _DEFAULT_DETACHED_RH))
        center_x, center_y = global_point
        rx = (center_x - width / 2 - screen.x()) / screen.width()
        ry = (center_y - height / 2 - screen.y()) / screen.height()
        return self._clamp_geometry(
            PanelGeometry(rx, ry, width / screen.width(), height / screen.height())
        )

    def _finish_tab_drag(self, global_point: QPoint, *, local_point: QPoint | None = None) -> None:
        if not self._drag_tab_id:
            return
        if self._locked:
            self._clear_tab_drag()
            return
        local = local_point if local_point is not None else self.mapFromGlobal(global_point)
        if self._tab_drag_active and not self.rect().contains(local):
            self.complete_tab_detach_gesture(
                self._drag_tab_id,
                (global_point.x(), global_point.y()),
            )
        elif self._tab_drag_active:
            self._reorder_dragged_tab_at(local, final=True)
        if self._tab_drag_active:
            self._suppress_click_tab_id = self._drag_tab_id
        self._clear_tab_drag()

    def _begin_tab_drag_if_needed(self, global_point: QPoint) -> None:
        if self._tab_drag_active or not self._drag_tab_id:
            return
        if (global_point - self._drag_start_global).manhattanLength() < QApplication.startDragDistance():
            return
        self._tab_drag_active = True
        if self.mouseGrabber() is not self:
            self.grabMouse()

    def _clear_tab_drag(self) -> None:
        if self.mouseGrabber() is self:
            self.releaseMouse()
        self._hide_tab_detach_preview()
        self._drag_tab_id = ""
        self._tab_drag_active = False
        self._tab_reorder_dirty = False

    def _tab_title_for_id(self, tab_id: str) -> str:
        tab = self._tabs_by_id.get(tab_id)
        return tab.name if tab is not None else tab_id

    def _can_show_tab_detach_preview(self) -> bool:
        return (
            not self._locked
            and self._tab_drag_active
            and bool(self._drag_tab_id)
            and len(self._group.tab_ids) > 1
        )

    def _hide_tab_detach_preview(self) -> None:
        self._detach_preview.hide()

    def _show_tab_detach_preview(self, tab_id: str, global_point: QPoint) -> None:
        self._detach_preview.set_title(self._tab_title_for_id(tab_id))
        self._detach_preview.move_near_global(global_point)
        self._detach_preview.show()

    def _update_tab_detach_preview(self, global_point: QPoint) -> None:
        if not self._can_show_tab_detach_preview():
            self._hide_tab_detach_preview()
            return
        local = self.mapFromGlobal(global_point)
        if self.rect().contains(local):
            self._reorder_dragged_tab_at(local, final=False)
        self._show_tab_detach_preview(self._drag_tab_id, global_point)

    def _target_tab_index_for_local(self, local_point: QPoint) -> int:
        dragged_button = self._tab_buttons.get(self._drag_tab_id)
        if dragged_button is not None:
            dragged_local = dragged_button.mapFrom(self, local_point)
            if dragged_button.rect().adjusted(-4, -4, 4, 4).contains(dragged_local):
                return self._group.tab_ids.index(self._drag_tab_id)
        final_order = [tab_id for tab_id in self._group.tab_ids if tab_id != self._drag_tab_id]
        visible = [
            (index, self._tab_buttons.get(tab_id))
            for index, tab_id in enumerate(final_order)
            if self._tab_buttons.get(tab_id) is not None
        ]
        if not visible:
            return -1
        for index, button in visible:
            assert button is not None
            center_x = button.mapTo(self, button.rect().center()).x()
            if local_point.x() < center_x:
                return index
        return len(final_order)

    def _reorder_dragged_tab_at(self, local_point: QPoint, *, final: bool) -> None:
        if not self._drag_tab_id or len(self._group.tab_ids) <= 1:
            return
        target_index = self._target_tab_index_for_local(local_point)
        if target_index < 0:
            return
        changed = False
        if self._workspace is not None:
            changed = self._workspace.reorder_tab(self._drag_tab_id, target_index)
            self._group = self._workspace.group(self._group.id)
            self._tabs_by_id = {tab.id: tab for tab in self._workspace.config.panel_tabs}
        elif self._drag_tab_id in self._group.tab_ids:
            current_index = self._group.tab_ids.index(self._drag_tab_id)
            if current_index != target_index:
                self._group.tab_ids.pop(current_index)
                self._group.tab_ids.insert(target_index, self._drag_tab_id)
                self._group.active_tab_id = self._drag_tab_id
                changed = True
        if changed:
            self._tab_reorder_dirty = True
            self._item_grid.set_active_tab_id(self._group.active_tab_id)
            self._rebuild_tab_buttons()
            self._render_active_content()
        if final and self._tab_reorder_dirty:
            self.tab_reordered.emit(self._group.id)

    def _resize_region_at(self, local_point: QPoint) -> _ResizeRegion:
        width = self.width()
        height = self.height()
        near_left = local_point.x() <= _RESIZE_MARGIN
        near_right = local_point.x() >= width - _RESIZE_MARGIN
        near_top = local_point.y() <= _TOP_RESIZE_MARGIN
        near_bottom = local_point.y() >= height - _RESIZE_MARGIN
        if near_top and near_left:
            return _ResizeRegion.TOP_LEFT
        if near_top and near_right:
            return _ResizeRegion.TOP_RIGHT
        if near_bottom and near_left:
            return _ResizeRegion.BOTTOM_LEFT
        if near_bottom and near_right:
            return _ResizeRegion.BOTTOM_RIGHT
        if near_left:
            return _ResizeRegion.LEFT
        if near_right:
            return _ResizeRegion.RIGHT
        if near_top:
            return _ResizeRegion.TOP
        if near_bottom:
            return _ResizeRegion.BOTTOM
        return _ResizeRegion.NONE

    def _can_delete_active_tab(self) -> bool:
        if self._workspace is None or not self._group.active_tab_id:
            return True
        return self._workspace.can_delete_tab(self._group.active_tab_id)

    def _cursor_for_resize_region(self, region: _ResizeRegion) -> Qt.CursorShape:
        if region in (_ResizeRegion.LEFT, _ResizeRegion.RIGHT):
            return Qt.CursorShape.SizeHorCursor
        if region in (_ResizeRegion.TOP, _ResizeRegion.BOTTOM):
            return Qt.CursorShape.SizeVerCursor
        if region in (_ResizeRegion.TOP_LEFT, _ResizeRegion.BOTTOM_RIGHT):
            return Qt.CursorShape.SizeFDiagCursor
        if region in (_ResizeRegion.TOP_RIGHT, _ResizeRegion.BOTTOM_LEFT):
            return Qt.CursorShape.SizeBDiagCursor
        return Qt.CursorShape.ArrowCursor

    def _update_resize_cursor(self, local_point: QPoint) -> None:
        if self._locked:
            self.setCursor(Qt.CursorShape.ArrowCursor)
            return
        self.setCursor(self._cursor_for_resize_region(self._resize_region_at(local_point)))

    def _grab_mouse_for_layout_gesture(self) -> None:
        if self.mouseGrabber() is not self:
            self.grabMouse()

    def _release_layout_mouse_grab(self) -> None:
        if self.mouseGrabber() is self:
            self.releaseMouse()

    def _begin_resize_gesture(
        self,
        region: _ResizeRegion,
        global_point: QPoint,
    ) -> None:
        self.layout_gesture_started.emit(self._group.id)
        self._persist_geometry_from_widget()
        self._resize_active = True
        self._resize_region = region
        self._drag_start_global = global_point
        self._start_frame = self.frameGeometry()
        self._start_geometry = PanelGeometry(
            self._group.geometry.rx,
            self._group.geometry.ry,
            self._group.geometry.rw,
            self._group.geometry.rh,
        )
        self._item_grid.suspend_layout_updates()
        self._grab_mouse_for_layout_gesture()

    def _resize_frame_for_global_point(self, global_point: QPoint) -> QRect:
        delta = global_point - self._drag_start_global
        frame = QRect(self._start_frame)
        region = self._resize_region
        if region in (
            _ResizeRegion.RIGHT,
            _ResizeRegion.TOP_RIGHT,
            _ResizeRegion.BOTTOM_RIGHT,
        ):
            frame.setWidth(max(_MIN_PANEL_WIDTH, self._start_frame.width() + delta.x()))
        if region in (
            _ResizeRegion.BOTTOM,
            _ResizeRegion.BOTTOM_LEFT,
            _ResizeRegion.BOTTOM_RIGHT,
        ):
            frame.setHeight(max(_MIN_PANEL_HEIGHT, self._start_frame.height() + delta.y()))
        if region in (
            _ResizeRegion.LEFT,
            _ResizeRegion.TOP_LEFT,
            _ResizeRegion.BOTTOM_LEFT,
        ):
            new_width = max(_MIN_PANEL_WIDTH, self._start_frame.width() - delta.x())
            frame.setLeft(self._start_frame.left() + self._start_frame.width() - new_width)
            frame.setWidth(new_width)
        if region in (
            _ResizeRegion.TOP,
            _ResizeRegion.TOP_LEFT,
            _ResizeRegion.TOP_RIGHT,
        ):
            new_height = max(_MIN_PANEL_HEIGHT, self._start_frame.height() - delta.y())
            frame.setTop(self._start_frame.top() + self._start_frame.height() - new_height)
            frame.setHeight(new_height)
        return frame

    def _snap_resize_frame(self, frame: QRect) -> QRect:
        snapped = QRect(frame)
        region = self._resize_region
        moves_left = region in (
            _ResizeRegion.LEFT,
            _ResizeRegion.TOP_LEFT,
            _ResizeRegion.BOTTOM_LEFT,
        )
        moves_right = region in (
            _ResizeRegion.RIGHT,
            _ResizeRegion.TOP_RIGHT,
            _ResizeRegion.BOTTOM_RIGHT,
        )
        moves_top = region in (
            _ResizeRegion.TOP,
            _ResizeRegion.TOP_LEFT,
            _ResizeRegion.TOP_RIGHT,
        )
        moves_bottom = region in (
            _ResizeRegion.BOTTOM,
            _ResizeRegion.BOTTOM_LEFT,
            _ResizeRegion.BOTTOM_RIGHT,
        )

        def set_left(value: int) -> None:
            if snapped.right() - value + 1 >= _MIN_PANEL_WIDTH:
                snapped.setLeft(value)

        def set_right(value: int) -> None:
            if value - snapped.left() + 1 >= _MIN_PANEL_WIDTH:
                snapped.setRight(value)

        def set_top(value: int) -> None:
            if snapped.bottom() - value + 1 >= _MIN_PANEL_HEIGHT:
                snapped.setTop(value)

        def set_bottom(value: int) -> None:
            if value - snapped.top() + 1 >= _MIN_PANEL_HEIGHT:
                snapped.setBottom(value)

        def set_width_from_stationary_edge(width: int) -> None:
            if width < _MIN_PANEL_WIDTH:
                return
            if moves_right:
                set_right(snapped.left() + width - 1)
            elif moves_left:
                set_left(snapped.right() - width + 1)

        def set_height_from_stationary_edge(height: int) -> None:
            if height < _MIN_PANEL_HEIGHT:
                return
            if moves_bottom:
                set_bottom(snapped.top() + height - 1)
            elif moves_top:
                set_top(snapped.bottom() - height + 1)

        screen_id = self._group.screen_id or "primary"
        screen = self._screen_geometry(screen_id)
        bottom_limit = self._screen_bottom_limit(screen)
        if moves_left:
            if abs(snapped.left() - screen.left()) <= _SNAP_MARGIN or snapped.left() < screen.left():
                set_left(screen.left())
        if moves_right:
            if abs(snapped.right() - screen.right()) <= _SNAP_MARGIN or snapped.right() > screen.right():
                set_right(screen.right())
        if moves_top:
            if abs(snapped.top() - screen.top()) <= _SNAP_MARGIN or snapped.top() < screen.top():
                set_top(screen.top())
        if moves_bottom:
            if (
                abs(snapped.bottom() - bottom_limit) <= _SNAP_MARGIN
                or snapped.bottom() > bottom_limit
            ):
                set_bottom(bottom_limit)

        for target in self._snap_rects:
            if self._screen_id_for_frame(target) != screen_id:
                continue
            if moves_right and abs((snapped.right() + 1) - target.left()) <= _SNAP_MARGIN:
                set_right(target.left() - 1)
            if moves_left and abs(snapped.left() - (target.right() + 1)) <= _SNAP_MARGIN:
                set_left(target.right() + 1)
            if moves_bottom and abs((snapped.bottom() + 1) - target.top()) <= _SNAP_MARGIN:
                set_bottom(target.top() - 1)
            if moves_top and abs(snapped.top() - (target.bottom() + 1)) <= _SNAP_MARGIN:
                set_top(target.bottom() + 1)
            if (moves_left or moves_right) and abs(snapped.width() - target.width()) <= _SNAP_MARGIN:
                set_width_from_stationary_edge(target.width())
            if (moves_top or moves_bottom) and abs(snapped.height() - target.height()) <= _SNAP_MARGIN:
                set_height_from_stationary_edge(target.height())
        return snapped

    def _update_resize_gesture(self, global_point: QPoint) -> None:
        frame = self._snap_resize_frame(self._resize_frame_for_global_point(global_point))
        if self.frameGeometry() != frame:
            self.setGeometry(frame)
        if not self._collapsed:
            self._expanded_content_height = frame.height()

    def _finish_resize_gesture(self) -> None:
        vertical_resize = self._resize_region in (
            _ResizeRegion.TOP,
            _ResizeRegion.TOP_LEFT,
            _ResizeRegion.TOP_RIGHT,
            _ResizeRegion.BOTTOM,
            _ResizeRegion.BOTTOM_LEFT,
            _ResizeRegion.BOTTOM_RIGHT,
        )
        self._resize_active = False
        self._resize_region = _ResizeRegion.NONE
        self._release_layout_mouse_grab()
        self._item_grid.resume_layout_updates()
        self._persist_geometry_from_widget(update_rh=vertical_resize)
        self.geometry_changed.emit()

    def _begin_header_drag(self, global_point: QPoint) -> None:
        self.layout_gesture_started.emit(self._group.id)
        self._header_drag_active = True
        self._drag_start_global = global_point
        self._start_frame = self.frameGeometry()
        self._grab_mouse_for_layout_gesture()

    def _snap_frame_to_screen(
        self,
        frame: QRect,
        global_point: QPoint | None = None,
    ) -> QRect:
        screen_id = (
            self._screen_id_for_global_point(global_point)
            if global_point is not None
            else self._screen_id_for_frame(frame)
        )
        screen = self._screen_geometry(screen_id)
        bottom_limit = self._screen_bottom_limit(screen)
        snapped = QRect(frame)
        if abs(snapped.left() - screen.left()) <= _SNAP_MARGIN:
            snapped.moveLeft(screen.left())
        if abs(snapped.top() - screen.top()) <= _SNAP_MARGIN:
            snapped.moveTop(screen.top())
        if abs(snapped.right() - screen.right()) <= _SNAP_MARGIN:
            snapped.moveRight(screen.right())
        if abs(snapped.bottom() - bottom_limit) <= _SNAP_MARGIN:
            snapped.moveBottom(bottom_limit)
        if snapped.left() < screen.left():
            snapped.moveLeft(screen.left())
        if snapped.top() < screen.top():
            snapped.moveTop(screen.top())
        if snapped.right() > screen.right():
            snapped.moveRight(screen.right())
        if snapped.bottom() > bottom_limit:
            snapped.moveBottom(bottom_limit)
        for target in self._snap_rects:
            if self._screen_id_for_frame(target) != screen_id:
                continue
            if abs((snapped.right() + 1) - target.left()) <= _SNAP_MARGIN:
                snapped.moveRight(target.left() - 1)
            elif abs(snapped.left() - (target.right() + 1)) <= _SNAP_MARGIN:
                snapped.moveLeft(target.right() + 1)
            if abs((snapped.bottom() + 1) - target.top()) <= _SNAP_MARGIN:
                snapped.moveBottom(target.top() - 1)
            elif abs(snapped.top() - (target.bottom() + 1)) <= _SNAP_MARGIN:
                snapped.moveTop(target.bottom() + 1)
        return snapped

    def _update_header_drag(self, global_point: QPoint) -> None:
        delta = global_point - self._drag_start_global
        if delta.manhattanLength() < QApplication.startDragDistance():
            return
        frame = QRect(self._start_frame)
        frame.moveTopLeft(self._start_frame.topLeft() + delta)
        frame = self._snap_frame_to_screen(frame, global_point)
        self.setGeometry(frame)
        if not self._collapsed:
            self._expanded_content_height = frame.height()

    def _finish_header_drag(self, global_point: QPoint) -> None:
        self._header_drag_active = False
        self._release_layout_mouse_grab()
        delta = global_point - self._drag_start_global
        if delta.manhattanLength() < QApplication.startDragDistance():
            return
        frame = QRect(self._start_frame)
        frame.moveTopLeft(self._start_frame.topLeft() + delta)
        frame = self._snap_frame_to_screen(frame, global_point)
        self.setGeometry(frame)
        if not self._collapsed:
            self._expanded_content_height = frame.height()
        self._persist_geometry_from_widget(update_rh=False)
        self._apply_geometry_from_model()
        self.geometry_changed.emit()
        self.complete_header_drag_at_global_point((global_point.x(), global_point.y()))

    _CONTENT_RESIZE_MARGIN = 16

    def _install_content_resize_filters(self) -> None:
        for widget in (
            self._content_host,
            self._item_grid,
            self._item_grid._scroll_area,
            self._item_grid._scroll_area.viewport(),
            self._item_grid._grid_host,
            self._item_grid._empty_label,
            *([self._widget_content] if self._widget_content is not None else []),
            *(
                self._widget_content.findChildren(QWidget)
                if self._widget_content is not None
                else []
            ),
            *self._item_grid.findChildren(QWidget),
        ):
            if widget is not None:
                widget.installEventFilter(self)

    def _content_edge_resize_region(
        self, child: QWidget, child_point: QPoint
    ) -> _ResizeRegion:
        child_w = child.width()
        child_h = child.height()
        child_left = child.mapTo(self, QPoint(0, 0)).x()
        child_top = child.mapTo(self, QPoint(0, 0)).y()
        child_right = child.mapTo(self, QPoint(child_w, 0)).x()
        child_bottom = child.mapTo(self, QPoint(0, child_h)).y()
        panel_w = self.width()
        panel_h = self.height()

        threshold = _RESIZE_MARGIN + 18
        near_panel_right = (panel_w - child_right) <= threshold
        near_panel_bottom = (panel_h - child_bottom) <= threshold
        near_panel_left = child_left <= threshold
        near_panel_top = child_top <= threshold

        near_child_right = child_point.x() >= child_w - self._CONTENT_RESIZE_MARGIN
        near_child_bottom = child_point.y() >= child_h - self._CONTENT_RESIZE_MARGIN
        near_child_left = child_point.x() <= self._CONTENT_RESIZE_MARGIN
        near_child_top = child_point.y() <= self._CONTENT_RESIZE_MARGIN

        if near_child_right and near_panel_right and near_child_bottom and near_panel_bottom:
            return _ResizeRegion.BOTTOM_RIGHT
        if near_child_right and near_panel_right and near_child_top and near_panel_top:
            return _ResizeRegion.TOP_RIGHT
        if near_child_left and near_panel_left and near_child_bottom and near_panel_bottom:
            return _ResizeRegion.BOTTOM_LEFT
        if near_child_left and near_panel_left and near_child_top and near_panel_top:
            return _ResizeRegion.TOP_LEFT
        if near_child_right and near_panel_right:
            return _ResizeRegion.RIGHT
        if near_child_bottom and near_panel_bottom:
            return _ResizeRegion.BOTTOM
        if near_child_left and near_panel_left:
            return _ResizeRegion.LEFT
        if near_child_top and near_panel_top:
            return _ResizeRegion.TOP
        return _ResizeRegion.NONE

    def _header_contains(self, local_point: QPoint) -> bool:
        if local_point.y() > _HEADER_DRAG_MARGIN:
            return False
        child = self.childAt(local_point)
        while child is not None and child is not self:
            if isinstance(child, QPushButton):
                return False
            child = child.parentWidget()
        return True

    def eventFilter(self, watched, event) -> bool:  # type: ignore[no-untyped-def]
        if watched in self._tab_buttons.values():
            if (
                event.type() == event.Type.MouseButtonDblClick
                and event.button() == Qt.MouseButton.LeftButton
            ):
                tab_id = next(
                    (tid for tid, button in self._tab_buttons.items() if button is watched),
                    "",
                )
                if tab_id:
                    self.start_inline_title_edit(tab_id)
                return True
            if self._locked:
                return super().eventFilter(watched, event)
            if self._header_drag_active:
                if event.type() == event.Type.MouseMove:
                    self._update_header_drag(watched.mapToGlobal(event.position().toPoint()))
                    return True
                if (
                    event.type() == event.Type.MouseButtonRelease
                    and event.button() == Qt.MouseButton.LeftButton
                ):
                    self._finish_header_drag(watched.mapToGlobal(event.position().toPoint()))
                    return True
            if event.type() == event.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                tab_id = next(
                    (tid for tid, button in self._tab_buttons.items() if button is watched),
                    "",
                )
                if len(self._group.tab_ids) <= 1:
                    self._begin_header_drag(watched.mapToGlobal(event.position().toPoint()))
                    return True
                self._drag_tab_id = tab_id
                self._tab_drag_active = False
                self._drag_start_global = watched.mapToGlobal(event.position().toPoint())
                return False
            if event.type() == event.Type.MouseMove and self._drag_tab_id:
                current = watched.mapToGlobal(event.position().toPoint())
                self._begin_tab_drag_if_needed(current)
                if self._tab_drag_active:
                    self._update_tab_detach_preview(current)
                return False
            if event.type() == event.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                if self._drag_tab_id:
                    global_point = watched.mapToGlobal(event.position().toPoint())
                    if self._tab_drag_active:
                        local_in_panel = self.mapFromGlobal(global_point)
                        self._finish_tab_drag(global_point, local_point=local_in_panel)
                        return True
                    self._clear_tab_drag()
                    return False
                self._clear_tab_drag()
        if self._is_content_resize_child(watched):
            return self._handle_content_resize_event(watched, event)
        return super().eventFilter(watched, event)

    def _is_content_resize_child(self, watched) -> bool:  # type: ignore[no-untyped-def]
        if not isinstance(watched, QWidget):
            return False
        widget: QWidget | None = watched
        while widget is not None:
            if widget is self._content_host:
                return True
            widget = widget.parentWidget()
        return False

    def _set_resize_cursor_for_widget(
        self,
        watched,
        shape: Qt.CursorShape,
    ) -> None:  # type: ignore[no-untyped-def]
        if self.cursor().shape() != shape:
            self.setCursor(shape)
        if isinstance(watched, QWidget) and watched.cursor().shape() != shape:
            watched.setCursor(shape)

    def _handle_content_resize_event(self, watched, event) -> bool:  # type: ignore[no-untyped-def]
        if event.type() not in (
            event.Type.MouseMove,
            event.Type.MouseButtonPress,
            event.Type.MouseButtonRelease,
        ):
            return False
        if self._locked:
            if event.type() == event.Type.MouseMove:
                self._set_resize_cursor_for_widget(watched, Qt.CursorShape.ArrowCursor)
            return False
        if event.type() == event.Type.MouseMove and not self._resize_active:
            child_point = event.position().toPoint()
            region = self._content_edge_resize_region(watched, child_point)
            self._set_resize_cursor_for_widget(
                watched,
                self._cursor_for_resize_region(region),
            )
            return False
        if event.type() == event.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            child_point = event.position().toPoint()
            region = self._content_edge_resize_region(watched, child_point)
            if region is not _ResizeRegion.NONE:
                self._begin_resize_gesture(region, watched.mapToGlobal(child_point))
                return True
            return False
        if self._resize_active and event.type() == event.Type.MouseMove:
            self._update_resize_gesture(watched.mapToGlobal(event.position().toPoint()))
            return True
        if self._resize_active and event.type() == event.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            self._finish_resize_gesture()
            return True
        return False

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._locked or event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        local = event.position().toPoint()
        region = self._resize_region_at(local)
        if region is not _ResizeRegion.NONE:
            self._begin_resize_gesture(region, event.globalPosition().toPoint())
            event.accept()
            return
        if self._header_contains(local):
            self._begin_header_drag(event.globalPosition().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._locked:
            super().mouseMoveEvent(event)
            return
        if self._resize_active:
            self._update_resize_gesture(event.globalPosition().toPoint())
            event.accept()
            return
        if self._header_drag_active:
            self._update_header_drag(event.globalPosition().toPoint())
            event.accept()
            return
        if self._tab_drag_active and self._drag_tab_id:
            self._update_tab_detach_preview(event.globalPosition().toPoint())
            event.accept()
            return
        if self._drag_tab_id and not self._tab_drag_active:
            self._begin_tab_drag_if_needed(event.globalPosition().toPoint())
            event.accept()
            return
        self._update_resize_cursor(event.position().toPoint())
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if not self._resize_active:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(event)
            return
        global_point = event.globalPosition().toPoint()
        if self._drag_tab_id and not self._locked:
            if self._tab_drag_active:
                self._finish_tab_drag(global_point, local_point=event.position().toPoint())
                event.accept()
                return
            self._clear_tab_drag()
        if self._resize_active and not self._locked:
            self._finish_resize_gesture()
            event.accept()
            return
        if self._header_drag_active and not self._locked:
            self._finish_header_drag(global_point)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        event.ignore()
        self.close_requested.emit()

    def showEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().showEvent(event)
        self._apply_taskbar_visibility_policy()
        self._persist_geometry_from_widget(update_rh=False)

    def _apply_taskbar_visibility_policy(self) -> None:
        hide_window_from_taskbar(int(self.winId()))

    def reassert_desktop_layer(self) -> None:
        """Re-establish normal always-on-bottom layering after a takeover detach.

        During takeover the panel is pushed to the raw Win32 bottom of the
        z-order; restoring Explorer icons then re-raises the desktop above it,
        which swallows all mouse input. Re-applying the window flags makes Qt
        re-run its known-good show placement so the panel sits just above the
        desktop and becomes interactive again.
        """
        was_visible = self.isVisible()
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnBottomHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        if was_visible:
            self.show()
            self._apply_taskbar_visibility_policy()

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        if self._editing_tab_id and self.inline_title_editor.isVisible():
            self._position_inline_title_editor(self._editing_tab_id)
        if not self._resize_active and not self._header_drag_active:
            if not self._collapsed:
                self._expanded_content_height = self.height()
            sync_rh = (
                not self._collapsed
                and not self._frame_height_matches_expanded_rh(self.height())
            )
            self._persist_geometry_from_widget(update_rh=sync_rh)

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(self._group.appearance.background_color)
        color.setAlphaF(self._group.appearance.background_opacity)
        path = QPainterPath()
        rect = self.rect().adjusted(1, 1, -1, -1)
        path.addRoundedRect(rect, _CORNER_RADIUS, _CORNER_RADIUS)
        painter.fillPath(path, color)
        border = QPen(QColor(255, 255, 255, 40))
        border.setWidth(1)
        painter.setPen(border)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        super().paintEvent(event)
