"""Grid of opaque desktop item cells with a two-line caption helper."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import time
from typing import Callable

from PySide6.QtCore import QMimeData, QPoint, QSize, Qt, Signal, QTimer
from PySide6.QtGui import QDrag, QFontMetrics, QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from desktop_tidy.domain.classification import canonical_key
from desktop_tidy.persistence.ui_preferences import DEFAULT_GROUP_ACCENT_COLOR
from desktop_tidy.services.desktop_index import IndexedItem
from desktop_tidy.services.item_visuals import ItemVisualProvider
from desktop_tidy.services.logging_setup import log_exception
from desktop_tidy.services.shell_context_menu import ShellContextMenuService
from desktop_tidy.ui.inline_group_expansion import InlineGroupExpansionWidget
from desktop_tidy.ui.item_grouping import DisplaySlot, GroupBlock, debug_drag

_FOLDER_PREVIEW_STYLE = (
    "QWidget#folderPreview {"
    "  background: rgba(255,255,255,0.12);"
    "  border: 1px solid rgba(255,255,255,0.28);"
    "  border-radius: 12px;"
    "}"
)
_FOLDER_PREVIEW_OPENING_STYLE = (
    "QWidget#folderPreview {"
    "  background: rgba(255,255,255,0.22);"
    "  border: 2px solid rgba(255,255,255,0.55);"
    "  border-radius: 12px;"
    "}"
)
_EMPTY_STATE_TEXT = "此分类暂无内容"
_DEFAULT_ICON_SIZE = 48
_MIN_ICON_SIZE = 32
_MAX_ICON_SIZE = 96
_ICON_STEP = 8
_ICON_PADDING = 8
_MIN_CELL_WIDTH = 96
_MIN_CAPTION_WIDTH = 88
_MIN_GRID_GAP = 8
_VERTICAL_SPACING = 12
_MIN_COLUMNS = 1
_LIST_MODE_ENTER_WIDTH = 360
_LIST_MODE_EXIT_WIDTH = 400
_LIST_ICON_SIZE = 22
_FOLDER_PREVIEW_COUNT = 4
_ELLIPSIS = "..."
ContextMenuLauncher = Callable[[QWidget, Path, object], bool]
FallbackContextMenu = Callable[[Path, object], None]

ITEM_MIME_TYPE = "application/x-desktop-tidy-item-path"
ITEM_MIME_ORIGIN_TAB = "application/x-desktop-tidy-item-origin-tab"
ITEM_MIME_GROUP_ID = "application/x-desktop-tidy-item-group-id"


def item_drag_origin_tab(mime) -> str:  # type: ignore[no-untyped-def]
    if mime.hasFormat(ITEM_MIME_ORIGIN_TAB):
        try:
            return bytes(mime.data(ITEM_MIME_ORIGIN_TAB)).decode("utf-8")
        except UnicodeDecodeError:
            return ""
    return ""


def item_drag_group_id(mime) -> str:  # type: ignore[no-untyped-def]
    if mime.hasFormat(ITEM_MIME_GROUP_ID):
        try:
            return bytes(mime.data(ITEM_MIME_GROUP_ID)).decode("utf-8")
        except UnicodeDecodeError:
            return ""
    return ""


def paths_from_item_mime(data: bytes) -> list[Path]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return []
    paths: list[Path] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            paths.append(Path(stripped).resolve())
    return paths

_DRAG_DEBUG = bool(os.environ.get("DT_DRAG_DEBUG"))


def _drag_dbg(*parts: object) -> None:
    debug_drag(_DRAG_DEBUG, *parts)


class ItemGridWidget(QWidget):
    paths_dropped = Signal(object, str)
    restore_auto_requested = Signal(object)
    item_activated = Signal(Path)
    item_selected = Signal(Path)
    item_icon_size_changed = Signal(int)
    items_reordered = Signal(str, object)
    cells_rebuilt = Signal()
    group_create_requested = Signal(str, object)
    group_join_requested = Signal(str, object)
    group_remove_requested = Signal(object)
    group_rename_requested = Signal(str, str)
    group_dissolve_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None, *, active_tab_id: str = "") -> None:
        super().__init__(parent)
        self._active_tab_id = active_tab_id
        self._visuals = ItemVisualProvider()
        self._entries: list[IndexedItem] = []
        self._groups: list[GroupBlock] = []
        self._render_fingerprint: tuple[object, ...] | None = None
        self._display_slots: list[DisplaySlot] = []
        self._group_blocks_by_id: dict[str, GroupBlock] = {}
        self._cells_by_group_id: dict[str, QWidget] = {}
        self._folder_labels_by_group_id: dict[str, QLabel] = {}
        self._folder_rename_editors_by_group_id: dict[str, QLineEdit] = {}
        self._open_group_popup: QWidget | None = None
        self._group_backdrop: QWidget | None = None
        self._inline_group_expansion: InlineGroupExpansionWidget | None = None
        self._open_group_id = ""
        self._folder_hover_id = ""
        self._folder_drop_target_id = ""
        self._folder_press_group_id = ""
        self._folder_drag_started = False
        self._suppress_folder_click = False
        self._pending_group_open_id = ""
        self._pending_group_open_timer = QTimer(self)
        self._pending_group_open_timer.setSingleShot(True)
        self._pending_group_open_timer.timeout.connect(self._open_pending_group_folder)
        self._folder_keep_open_until = 0.0
        self._drag_from_folder_group_id = ""
        self._dragging_paths: set[Path] = set()
        self._drag_opacity_effects: dict[QWidget, QGraphicsOpacityEffect] = {}
        self._drop_ghost_index: int | None = None
        self._restorable_paths: frozenset[Path] = frozenset()
        self._selected_paths: set[Path] = set()
        self._selection_anchor: Path | None = None
        self._focus_path: Path | None = None
        self._cells_by_path: dict[Path, QWidget] = {}
        self._last_column_count = 0
        self._last_layout_mode = "grid"
        self._item_icon_size = _DEFAULT_ICON_SIZE
        self._layout_updates_suspended = False
        self._pending_rebuild_after_suspension = False
        self._native_context_menu = ShellContextMenuService()
        self._context_menu: QMenu | None = None
        self._reorder_enabled = True
        self._drag_start_pos: QPoint | None = None
        self._drag_source_path: Path | None = None
        self._dragging = False
        self._item_drag_origin_tab_id = ""
        self._group_accent_color = DEFAULT_GROUP_ACCENT_COLOR
        if os.environ.get("DESKTOP_TIDY_DISABLE_NATIVE_CONTEXT_MENU") == "1":
            self._context_menu_launcher: ContextMenuLauncher = lambda _owner, _path, _global_pos: False
        else:
            self._context_menu_launcher = self._native_context_menu.show
        if os.environ.get("DESKTOP_TIDY_QT_CONTEXT_MENU_FALLBACK") == "1":
            self._fallback_context_menu: FallbackContextMenu = self._show_basic_context_menu
        else:
            self._fallback_context_menu = lambda _path, _global_pos: None
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(self.backgroundRole(), Qt.GlobalColor.transparent)
        self.setPalette(palette)

        self._grid_host = QWidget()
        self._grid_host.setMinimumWidth(0)
        self._grid_host.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self._grid_host.setAutoFillBackground(True)
        grid_palette = self._grid_host.palette()
        grid_palette.setColor(self._grid_host.backgroundRole(), Qt.GlobalColor.transparent)
        self._grid_host.setPalette(grid_palette)

        self._layout = QGridLayout(self._grid_host)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setHorizontalSpacing(_MIN_GRID_GAP)
        self._layout.setVerticalSpacing(_VERTICAL_SPACING)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        self._scroll_area = QScrollArea(self)
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll_area.setWidget(self._grid_host)
        self._scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll_area.setAutoFillBackground(True)
        scroll_palette = self._scroll_area.palette()
        scroll_palette.setColor(self._scroll_area.backgroundRole(), Qt.GlobalColor.transparent)
        self._scroll_area.setPalette(scroll_palette)
        self._scroll_area.viewport().setAutoFillBackground(True)
        vp_palette = self._scroll_area.viewport().palette()
        vp_palette.setColor(self._scroll_area.viewport().backgroundRole(), Qt.GlobalColor.transparent)
        self._scroll_area.viewport().setPalette(vp_palette)
        self._scroll_area.installEventFilter(self)
        self._scroll_area.viewport().installEventFilter(self)
        self._grid_host.installEventFilter(self)
        self._scroll_area.verticalScrollBar().valueChanged.connect(
            self._schedule_reposition_open_group_popup
        )
        self._group_reposition_timer = QTimer(self)
        self._group_reposition_timer.setSingleShot(True)
        self._group_reposition_timer.setInterval(32)
        self._group_reposition_timer.timeout.connect(
            self._reposition_open_group_popup
        )

        self._drop_ghost = QWidget(self._grid_host)
        self._drop_ghost.setObjectName("dropGhost")
        self._drop_ghost.setStyleSheet(
            "QWidget#dropGhost {"
            "  background: rgba(180, 180, 180, 0.22);"
            "  border: 2px dashed rgba(255, 255, 255, 0.50);"
            "  border-radius: 10px;"
            "}"
        )
        self._drop_ghost.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._drop_ghost.hide()

        self._empty_label = QLabel(_EMPTY_STATE_TEXT, self)
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setWordWrap(True)
        self._empty_label.setStyleSheet("color: #e8e8e8; background: transparent;")
        self._empty_label.hide()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._scroll_area)
        outer.addWidget(self._empty_label)

    @property
    def active_tab_id(self) -> str:
        return self._active_tab_id

    def set_active_tab_id(self, tab_id: str) -> None:
        if tab_id != self._active_tab_id:
            self._close_group_folder(immediate=True)
        self._active_tab_id = tab_id

    def set_group_accent_color(self, accent_color: str) -> None:
        self._group_accent_color = accent_color.upper()
        if self._inline_group_expansion is not None:
            self._inline_group_expansion.set_accent_color(self._group_accent_color)

    def set_reorder_enabled(self, enabled: bool) -> None:
        self._reorder_enabled = bool(enabled)

    def reorder_enabled(self) -> bool:
        return self._reorder_enabled

    def reordered_entry_paths(self, source_path: Path, target_index: int) -> list[Path]:
        """计算把 ``source_path``(或分组锚点) 移动到 ``target_index`` 后的完整顺序。"""
        return self.reordered_anchor_paths_for_drag([source_path], target_index)

    def reordered_anchor_paths_for_drag(
        self, moving_paths: list[Path], target_index: int
    ) -> list[Path]:
        paths = self._slot_anchor_paths()
        moving_anchors: list[Path] = []
        seen: set[Path] = set()
        for path in moving_paths:
            anchor = self._anchor_for_path(path)
            if anchor in paths and anchor not in seen:
                seen.add(anchor)
                moving_anchors.append(anchor)
        if not moving_anchors:
            return paths
        remaining = [path for path in paths if path not in seen]
        adjusted = int(target_index)
        for index, path in enumerate(paths):
            if index >= target_index:
                break
            if path in seen:
                adjusted -= 1
        clamped = max(0, min(adjusted, len(remaining)))
        return remaining[:clamped] + moving_anchors + remaining[clamped:]

    def _anchor_for_path(self, path: Path) -> Path:
        resolved = path.resolve()
        group_id = self._group_of_path(resolved)
        if group_id is not None:
            block = self._group_block(group_id)
            if block is not None and block.members:
                return block.members[0]
        return resolved

    def _slot_anchor_paths(self) -> list[Path]:
        result: list[Path] = []
        for slot in self._display_slots:
            if slot.kind == "item" and slot.entry is not None:
                result.append(slot.entry.path.resolve())
            elif slot.kind == "group" and slot.group is not None and slot.group.members:
                result.append(slot.group.members[0])
        return result

    def _build_display_slots(self) -> list[DisplaySlot]:
        by_path = {entry.path.resolve(): entry for entry in self._entries}
        path_to_group: dict[Path, GroupBlock] = {}
        for block in self._groups:
            self._group_blocks_by_id[block.group_id] = block
            for member in block.members:
                path_to_group[member] = block
        slots: list[DisplaySlot] = []
        seen_groups: set[str] = set()
        for entry in self._entries:
            resolved = entry.path.resolve()
            block = path_to_group.get(resolved)
            if block is not None:
                if block.group_id in seen_groups:
                    continue
                seen_groups.add(block.group_id)
                slots.append(DisplaySlot(kind="group", group=block))
            else:
                slots.append(DisplaySlot(kind="item", entry=entry))
        return slots

    def _apply_internal_reorder(
        self, source_paths: Path | list[Path], target_index: int
    ) -> None:
        if not self._reorder_enabled:
            return
        moving = (
            [source_paths]
            if isinstance(source_paths, Path)
            else list(source_paths)
        )
        new_paths = self.reordered_anchor_paths_for_drag(moving, target_index)
        if new_paths == self._slot_anchor_paths():
            return
        self._reorder_entries_for_anchor_paths(new_paths)
        self._rebuild_cells()
        self.items_reordered.emit(self._active_tab_id, new_paths)

    def _reorder_entries_for_anchor_paths(self, anchor_paths: list[Path]) -> None:
        if not self._display_slots:
            return
        slot_by_anchor: dict[Path, DisplaySlot] = {}
        for slot in self._display_slots:
            if slot.kind == "item" and slot.entry is not None:
                slot_by_anchor[slot.entry.path.resolve()] = slot
            elif slot.kind == "group" and slot.group is not None and slot.group.members:
                slot_by_anchor[slot.group.members[0]] = slot
        by_path = {entry.path.resolve(): entry for entry in self._entries}
        reordered: list[IndexedItem] = []
        for anchor in anchor_paths:
            slot = slot_by_anchor.get(anchor.resolve())
            if slot is None:
                continue
            if slot.kind == "item" and slot.entry is not None:
                reordered.append(slot.entry)
            elif slot.kind == "group" and slot.group is not None:
                for member in slot.group.members:
                    entry = by_path.get(member)
                    if entry is not None:
                        reordered.append(entry)
        if reordered:
            self._entries = reordered

    def _drop_target_index(self, host_point: QPoint) -> int:
        """根据落点(grid_host 坐标)在网格内的位置,计算插入索引。"""
        if not self._display_slots:
            return 0
        list_mode = self._layout_mode() == "list"
        for index, slot in enumerate(self._display_slots):
            cell = self._cell_for_slot(slot)
            if cell is None:
                continue
            geometry = cell.geometry()
            if list_mode:
                if host_point.y() < geometry.center().y():
                    return index
            else:
                if host_point.y() < geometry.top():
                    return index
                same_row = geometry.top() <= host_point.y() <= geometry.bottom()
                if same_row and host_point.x() < geometry.center().x():
                    return index
        return len(self._display_slots)

    def _cell_for_slot(self, slot: DisplaySlot) -> QWidget | None:
        if slot.kind == "item" and slot.entry is not None:
            return self._cells_by_path.get(slot.entry.path.resolve())
        if slot.kind == "group" and slot.group is not None:
            return self._cells_by_group_id.get(slot.group.group_id)
        return None

    def begin_item_drag(
        self, source_path: Path, *, ghost_widget: QWidget | None = None
    ) -> None:
        """供分组浮层等外部控件发起与标签内一致的拖动。"""
        self._start_item_drag(source_path.resolve(), ghost_widget=ghost_widget)

    def _start_item_drag(
        self, source_path: Path, *, ghost_widget: QWidget | None = None
    ) -> None:
        """用 Qt 原生 QDrag 发起标签内拖动(可靠地走系统拖放管线)。"""
        folder_drag_id = self._drag_from_folder_group_id
        drag_paths = self._drag_paths_for_source(
            source_path,
            folder_drag_id=folder_drag_id,
        )
        self._close_group_folder(immediate=True)
        self._reset_drag_state()
        self._drag_from_folder_group_id = folder_drag_id
        self._item_drag_origin_tab_id = self._active_tab_id
        self._dragging_paths = {path.resolve() for path in drag_paths}
        self._apply_dragging_cell_styles(True)
        drag = self._build_item_drag(
            source_path,
            drag_paths=drag_paths,
            ghost_widget=ghost_widget,
        )
        _drag_dbg(
            "start_item_drag",
            ",".join(path.name for path in drag_paths),
            "from",
            self._item_drag_origin_tab_id,
        )
        result = drag.exec(Qt.DropAction.MoveAction)
        _drag_dbg("drag.exec returned", int(result.value) if result is not None else None)
        self._apply_dragging_cell_styles(False)
        self._update_drop_ghost(None)
        self._drag_from_folder_group_id = ""
        self._item_drag_origin_tab_id = ""

    def _drag_paths_for_source(
        self,
        source_path: Path,
        *,
        folder_drag_id: str = "",
    ) -> list[Path]:
        if folder_drag_id:
            block = self._group_block(folder_drag_id)
            return [block.members[0]] if block and block.members else [source_path.resolve()]
        return self._drag_paths_for(source_path)

    def _build_item_drag(
        self,
        source_path: Path,
        *,
        drag_paths: list[Path] | None = None,
        ghost_widget: QWidget | None = None,
    ) -> QDrag:
        folder_drag_id = self._drag_from_folder_group_id
        resolved_source = source_path.resolve()
        paths = drag_paths or self._drag_paths_for_source(
            resolved_source,
            folder_drag_id=folder_drag_id,
        )
        paths = [path.resolve() for path in paths]
        drag = QDrag(self)
        mime = QMimeData()
        payload = "\n".join(str(path) for path in paths).encode("utf-8")
        mime.setData(ITEM_MIME_TYPE, payload)
        mime.setData(
            ITEM_MIME_ORIGIN_TAB,
            (self._item_drag_origin_tab_id or self._active_tab_id).encode("utf-8"),
        )
        if folder_drag_id:
            mime.setData(ITEM_MIME_GROUP_ID, folder_drag_id.encode("utf-8"))
        drag.setMimeData(mime)
        cell = ghost_widget or self._cells_by_path.get(resolved_source)
        if cell is None and folder_drag_id:
            cell = self._cells_by_group_id.get(folder_drag_id)
        if cell is None:
            for group_id, folder_cell in self._cells_by_group_id.items():
                block = self._group_block(group_id)
                if block is not None and block.members and block.members[0] == resolved_source:
                    cell = folder_cell
                    break
        ghost = self._make_drag_ghost_pixmap(paths, cell)
        drag.setPixmap(ghost)
        drag.setHotSpot(QPoint(ghost.width() // 2, ghost.height() // 2))
        return drag

    def _make_drag_ghost_pixmap(
        self, paths: list[Path], cell: QWidget | None
    ) -> QPixmap:
        if cell is not None and not isValid(cell):
            cell = None
        width = cell.width() if cell is not None and cell.width() > 0 else self._cell_width()
        height = cell.height() if cell is not None and cell.height() > 0 else self._cell_icon_size() + 48
        if len(paths) > 1:
            width = max(width, self._cell_width() + 16)
            height = max(height, self._cell_icon_size() + 56)
        pixmap = QPixmap(max(72, width), max(80, height))
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(QColor(140, 140, 140, 110))
        painter.setPen(QPen(QColor(255, 255, 255, 90), 2, Qt.PenStyle.DashLine))
        painter.drawRoundedRect(3, 3, pixmap.width() - 6, pixmap.height() - 6, 10, 10)

        icon_size = max(24, self._cell_icon_size() - 8)
        stack_count = min(3, len(paths))
        stack_offset = 10 if stack_count > 1 else 0
        base_x = (pixmap.width() - icon_size - stack_offset) // 2
        base_y = max(10, (pixmap.height() - icon_size - 16 - stack_offset) // 2)
        for index in range(stack_count):
            icon_pix = self._visuals.icon_for(paths[index]).pixmap(icon_size, icon_size)
            offset = index * stack_offset
            painter.setOpacity(0.72 if index == 0 else 0.55)
            painter.drawPixmap(base_x + offset, base_y + offset, icon_pix)

        if len(paths) > 1:
            badge = f"{len(paths)}"
            metrics = QFontMetrics(self.font())
            badge_w = max(20, metrics.horizontalAdvance(badge) + 12)
            badge_rect_x = pixmap.width() - badge_w - 8
            badge_rect_y = 8
            painter.setOpacity(1.0)
            painter.setBrush(QColor(90, 140, 220, 220))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(badge_rect_x, badge_rect_y, badge_w, 20, 10, 10)
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(
                badge_rect_x,
                badge_rect_y,
                badge_w,
                20,
                int(Qt.AlignmentFlag.AlignCenter),
                badge,
            )
        painter.end()
        return pixmap

    def _apply_dragging_cell_styles(self, dragging: bool) -> None:
        if not dragging:
            for cell, effect in list(self._drag_opacity_effects.items()):
                if isValid(cell):
                    cell.setGraphicsEffect(None)
            self._drag_opacity_effects.clear()
            self._dragging_paths.clear()
            return
        for path in list(self._dragging_paths):
            cell = self._cells_by_path.get(path)
            if cell is None:
                continue
            if not isValid(cell):
                self._cells_by_path.pop(path, None)
                continue
            effect = QGraphicsOpacityEffect(cell)
            effect.setOpacity(0.38)
            cell.setGraphicsEffect(effect)
            self._drag_opacity_effects[cell] = effect
        for group_id, cell in list(self._cells_by_group_id.items()):
            if not isValid(cell):
                self._cells_by_group_id.pop(group_id, None)
                continue
            block = self._group_block(group_id)
            if block is None or not block.members:
                continue
            if block.members[0] not in self._dragging_paths:
                continue
            effect = QGraphicsOpacityEffect(cell)
            effect.setOpacity(0.38)
            cell.setGraphicsEffect(effect)
            self._drag_opacity_effects[cell] = effect

    def _update_drop_ghost(self, index: int | None) -> None:
        if index is None or not self._display_slots or self._layout_mode() == "list":
            self._drop_ghost_index = None
            self._drop_ghost.hide()
            return
        if index == self._drop_ghost_index and self._drop_ghost.isVisible():
            return
        self._drop_ghost_index = index
        if index >= len(self._display_slots):
            slot = self._display_slots[-1]
            cell = self._cell_for_slot(slot)
            if cell is None:
                self._drop_ghost.hide()
                return
            geometry = cell.geometry()
            gap = max(4, self._layout.horizontalSpacing())
            self._drop_ghost.setGeometry(
                geometry.x() + geometry.width() + gap // 2,
                geometry.y(),
                max(48, cell.width()),
                geometry.height(),
            )
        else:
            slot = self._display_slots[index]
            cell = self._cell_for_slot(slot)
            if cell is None:
                self._drop_ghost.hide()
                return
            self._drop_ghost.setGeometry(cell.geometry())
        self._drop_ghost.show()
        self._drop_ghost.raise_()

    def _cancel_pending_group_open(self) -> None:
        self._pending_group_open_id = ""
        self._pending_group_open_timer.stop()

    def _schedule_group_folder_open(self, group_id: str) -> None:
        if not group_id:
            return
        self._cancel_pending_group_open()
        self._switch_group_folder(group_id, toggle_if_open=False)

    def _open_pending_group_folder(self) -> None:
        group_id = self._pending_group_open_id
        self._pending_group_open_id = ""
        if not group_id:
            return
        if group_id not in self._cells_by_group_id:
            return
        self._switch_group_folder(group_id, toggle_if_open=False)

    def _activate_folder_on_press(self, group_id: str) -> None:
        self._switch_group_folder(group_id, toggle_if_open=False)

    def _handle_item_drop(
        self,
        source: Path,
        host_point: QPoint,
        *,
        origin_tab: str | None = None,
        drag_paths: list[Path] | None = None,
        drag_group_id: str | None = None,
    ) -> None:
        if source is None or not self._reorder_enabled:
            return
        source = source.resolve()
        paths = drag_paths or [source]
        paths = [path.resolve() for path in paths]
        if source not in paths:
            paths = [source, *[path for path in paths if path != source]]
        resolved_origin = (
            origin_tab
            or self._item_drag_origin_tab_id
            or self._active_tab_id
        )
        if resolved_origin != self._active_tab_id:
            _drag_dbg(
                "cross-tab drop",
                ",".join(path.name for path in paths),
                resolved_origin,
                "->",
                self._active_tab_id,
            )
            self.paths_dropped.emit(paths, self._active_tab_id)
            return
        entry_keys = {canonical_key(entry.path) for entry in self._entries}
        if not all(canonical_key(path) in entry_keys for path in paths):
            _drag_dbg(
                "cross-panel drop",
                ",".join(path.name for path in paths),
                "->",
                self._active_tab_id,
            )
            self.paths_dropped.emit(paths, self._active_tab_id)
            return
        # 同标签多选拖动: 排序/建组/加入组均携带完整选区。
        folder_drag_id = drag_group_id or self._drag_from_folder_group_id
        if folder_drag_id:
            block = self._group_block(folder_drag_id)
            anchor = block.members[0] if block and block.members else source
            folder_group = self._folder_cell_hit(host_point)
            if folder_group is not None and folder_group != folder_drag_id:
                self.group_join_requested.emit(folder_group, [anchor])
                self._drag_from_folder_group_id = ""
                return
            self._apply_internal_reorder([anchor], self._drop_target_index(host_point))
            self._drag_from_folder_group_id = ""
            return
        folder_group = self._folder_cell_hit(host_point)
        if folder_group is not None:
            self.group_join_requested.emit(folder_group, paths)
            return
        target = self._cell_central_hit(host_point)
        if target is not None and target.resolve() not in {path.resolve() for path in paths}:
            target_group = self._group_of_path(target)
            if target_group is not None:
                self.group_join_requested.emit(target_group, paths)
            else:
                target_path = target.resolve()
                members = list(
                    dict.fromkeys(
                        [
                            target_path,
                            *[path for path in paths if path.resolve() != target_path],
                        ]
                    )
                )
                self.group_create_requested.emit(self._active_tab_id, members)
            return
        source_group = self._group_of_path(source)
        region_group = self._region_group_at(host_point)
        if region_group is not None:
            if region_group != source_group:
                self.group_join_requested.emit(region_group, paths)
            return
        if source_group is not None:
            self.group_remove_requested.emit(paths)
            return
        self._apply_internal_reorder(paths, self._drop_target_index(host_point))

    def _folder_cell_hit(self, host_point: QPoint) -> str | None:
        for group_id, cell in self._cells_by_group_id.items():
            if cell.geometry().contains(host_point):
                return group_id
        return None

    def _folder_id_at_viewport_point(self, viewport_point: QPoint) -> str | None:
        host_point = self._grid_host.mapFrom(self._scroll_area.viewport(), viewport_point)
        return self._folder_cell_hit(host_point)

    def _cleanup_orphan_group_popups(self) -> None:
        viewport = self._scroll_area.viewport()
        kept = self._open_group_popup
        for child in viewport.findChildren(QWidget):
            if child.objectName() == "groupFolderPopupRoot" and child is not kept:
                child.hide()
                child.setParent(None)
                child.deleteLater()

    def _reposition_open_group_popup(self) -> None:
        if self._inline_group_expansion is None or not self._open_group_id:
            return
        self._inline_group_expansion.reposition_in(self._scroll_area.viewport())

    def _schedule_reposition_open_group_popup(self, _value: int = 0) -> None:
        if self._inline_group_expansion is None:
            return
        self._group_reposition_timer.start()

    def _hide_group_backdrop(self) -> None:
        self._grid_host.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        if self._group_backdrop is not None:
            self._group_backdrop.hide()
            self._group_backdrop.setParent(None)
            self._group_backdrop.deleteLater()
            self._group_backdrop = None

    def _purge_stale_group_popups(self, host: QWidget | None = None) -> None:
        if not isValid(self._scroll_area):
            self._open_group_popup = None
            self._open_group_id = ""
            self._hide_group_backdrop()
            return
        viewport = host or self._scroll_area.viewport()
        popup = self._open_group_popup
        self._open_group_popup = None
        if popup is not None:
            popup.hide()
            popup.setParent(None)
            popup.deleteLater()
        for child in viewport.findChildren(QWidget):
            if child.objectName() == "groupFolderPopupRoot" and child is not popup:
                child.hide()
                child.setParent(None)
                child.deleteLater()
        self._hide_group_backdrop()

    def close_open_group_folder(self) -> None:
        self._close_group_folder(immediate=True)

    def _close_group_folder(self, *, immediate: bool = True) -> None:
        self._cancel_pending_group_open()
        closed_group_id = self._open_group_id
        self._open_group_id = ""
        expansion = self._inline_group_expansion
        if expansion is not None:
            if immediate:
                expansion.hide_immediately()
            else:
                expansion.hide_animated()
        self._purge_stale_group_popups()
        if closed_group_id:
            self._update_folder_cell_style(closed_group_id)
        self._folder_keep_open_until = 0.0
        if closed_group_id:
            block = self._group_block(closed_group_id)
            if block is not None and block.members:
                anchor = block.members[0]
                if anchor in self._selected_paths:
                    self._selected_paths.discard(anchor)
                    if self._focus_path == anchor:
                        self._focus_path = next(iter(self._selected_paths), None)
                    if self._selection_anchor == anchor:
                        self._selection_anchor = self._focus_path
                    self._apply_all_selection_styles()

    def _switch_group_folder(
        self,
        group_id: str,
        *,
        toggle_if_open: bool = True,
    ) -> None:
        self._cancel_pending_group_open()
        self._folder_keep_open_until = 0.0
        self._cleanup_orphan_group_popups()
        folder_cell = self._cells_by_group_id.get(group_id)
        if folder_cell is None:
            self._close_group_folder()
            return
        if (
            self._open_group_id == group_id
            and self._inline_group_expansion is not None
            and self._inline_group_expansion.isVisible()
        ):
            if toggle_if_open:
                self._close_group_folder(immediate=False)
            else:
                self._inline_group_expansion.reposition_in(
                    self._scroll_area.viewport()
                )
                self._inline_group_expansion.raise_()
            return
        block = self._group_block(group_id)
        if block is None or not block.members:
            log_exception(
                f"open group folder {group_id}",
                RuntimeError("group has no visible members"),
            )
            self._close_group_folder()
            return
        previous = self._open_group_id
        self._open_group_id = group_id
        if previous and previous != group_id:
            self._update_folder_cell_style(previous)
        self._update_folder_cell_style(group_id)
        if self._inline_group_expansion is None:
            try:
                expansion = InlineGroupExpansionWidget(
                    group_id=group_id,
                    name=block.name,
                    members=block.members,
                    icon_size=self._cell_icon_size(),
                    accent_color=self._group_accent_color,
                    parent=self._scroll_area.viewport(),
                    visuals=self._visuals,
                )
            except Exception as exc:
                log_exception(f"open inline group {group_id}", exc)
                self._open_group_id = previous or ""
                if previous:
                    self._update_folder_cell_style(previous)
                return
            expansion.set_drag_host(self)
            expansion.item_activated.connect(self.item_activated.emit)
            expansion.rename_requested.connect(self._prompt_rename_group)
            expansion.dissolve_requested.connect(self.group_dissolve_requested.emit)
            expansion.members_dropped.connect(self.group_join_requested.emit)
            self._inline_group_expansion = expansion
        else:
            self._inline_group_expansion.update_group(
                group_id=group_id,
                name=block.name,
                members=block.members,
                icon_size=self._cell_icon_size(),
                accent_color=self._group_accent_color,
            )
        self._inline_group_expansion.show_animated(self._scroll_area.viewport())
        self._open_group_popup = None
        self._group_backdrop = None

    def _open_group_folder(self, group_id: str, anchor_widget: QWidget) -> None:
        del anchor_widget
        self._switch_group_folder(group_id, toggle_if_open=False)

    def _toggle_group_folder(self, group_id: str, anchor_widget: QWidget) -> None:
        self._switch_group_folder(group_id)

    def _group_block(self, group_id: str) -> GroupBlock | None:
        return self._group_blocks_by_id.get(group_id)

    def _group_of_path(self, path: Path) -> str | None:
        resolved = path.resolve()
        for block in self._groups:
            if resolved in block.members:
                return block.group_id
        return None

    def _cell_central_hit(self, host_point: QPoint) -> Path | None:
        for path, cell in self._cells_by_path.items():
            geometry = cell.geometry()
            inset_x = geometry.width() // 4
            inset_y = geometry.height() // 4
            central = geometry.adjusted(inset_x, inset_y, -inset_x, -inset_y)
            if central.contains(host_point):
                return path
        return None

    def _nearest_cell_path(self, host_point: QPoint) -> Path | None:
        best: Path | None = None
        best_distance: int | None = None
        for path, cell in self._cells_by_path.items():
            center = cell.geometry().center()
            distance = (center.x() - host_point.x()) ** 2 + (
                center.y() - host_point.y()
            ) ** 2
            if best_distance is None or distance < best_distance:
                best_distance = distance
                best = path
        return best

    def _region_group_at(self, host_point: QPoint) -> str | None:
        if not self._groups:
            return None
        nearest = self._nearest_cell_path(host_point)
        if nearest is None:
            return None
        return self._group_of_path(nearest)

    def _reset_drag_state(self) -> None:
        self._dragging = False
        self._drag_source_path = None
        self._drag_start_pos = None
        self._folder_press_group_id = ""
        self._folder_drag_started = False
        self._drag_from_folder_group_id = ""
        self._item_drag_origin_tab_id = ""

    def set_context_menu_launcher(self, launcher: ContextMenuLauncher) -> None:
        self._context_menu_launcher = launcher

    def set_fallback_context_menu(self, launcher: FallbackContextMenu) -> None:
        self._fallback_context_menu = launcher

    def item_icon_size(self) -> int:
        return self._item_icon_size

    def set_item_icon_size(self, size: int, *, notify: bool = True) -> None:
        clamped = max(_MIN_ICON_SIZE, min(_MAX_ICON_SIZE, int(size)))
        if clamped == self._item_icon_size:
            return
        old_mode = self._layout_mode()
        self._item_icon_size = clamped
        if self._entries and self._layout_mode() == old_mode:
            self._update_existing_cell_metrics()
            self._relayout_existing_cells(self.column_count())
        else:
            self._rebuild_cells()
        if notify:
            self.item_icon_size_changed.emit(clamped)

    def suspend_layout_updates(self) -> None:
        self._layout_updates_suspended = True
        self._pending_rebuild_after_suspension = False

    def resume_layout_updates(self) -> None:
        if not self._layout_updates_suspended:
            return
        self._layout_updates_suspended = False
        if self._pending_rebuild_after_suspension:
            self._pending_rebuild_after_suspension = False
            self._rebuild_cells()
        else:
            self._apply_adaptive_spacing(self._last_column_count)

    def local_paths_from_urls(self, urls) -> list[Path]:
        paths: list[Path] = []
        for url in urls:
            if url.isLocalFile():
                paths.append(Path(url.toLocalFile()).resolve())
        return paths

    def accept_dropped_urls(self, urls) -> None:
        paths = self.local_paths_from_urls(urls)
        if paths:
            self.paths_dropped.emit(paths, self._active_tab_id)

    def dragEnterEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        md = event.mimeData()
        _drag_dbg("dragEnter item?", md.hasFormat(ITEM_MIME_TYPE), "urls?", md.hasUrls())
        if md.hasFormat(ITEM_MIME_TYPE) or md.hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        md = event.mimeData()
        if md.hasFormat(ITEM_MIME_TYPE) or md.hasUrls():
            host_point = self._grid_host.mapFrom(self, event.position().toPoint())
            folder_group = self._folder_cell_hit(host_point) or ""
            if folder_group != self._folder_drop_target_id:
                previous = self._folder_drop_target_id
                self._folder_drop_target_id = folder_group
                if previous:
                    self._update_folder_cell_style(previous)
                if folder_group:
                    self._update_folder_cell_style(folder_group)
            if md.hasFormat(ITEM_MIME_TYPE) and not folder_group:
                self._update_drop_ghost(self._drop_target_index(host_point))
            else:
                self._update_drop_ghost(None)
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self._folder_drop_target_id:
            previous = self._folder_drop_target_id
            self._folder_drop_target_id = ""
            self._update_folder_cell_style(previous)
        self._update_drop_ghost(None)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self._folder_drop_target_id:
            previous = self._folder_drop_target_id
            self._folder_drop_target_id = ""
            self._update_folder_cell_style(previous)
        self._update_drop_ghost(None)
        md = event.mimeData()
        _drag_dbg("dropEvent item?", md.hasFormat(ITEM_MIME_TYPE), "urls?", md.hasUrls())
        if md.hasFormat(ITEM_MIME_TYPE):
            drag_paths = paths_from_item_mime(bytes(md.data(ITEM_MIME_TYPE)))
            if not drag_paths:
                return
            source = drag_paths[0]
            host_point = self._grid_host.mapFrom(self, event.position().toPoint())
            origin_tab = item_drag_origin_tab(md)
            self._handle_item_drop(
                source,
                host_point,
                origin_tab=origin_tab or None,
                drag_paths=drag_paths,
                drag_group_id=item_drag_group_id(md) or None,
            )
            event.acceptProposedAction()
            return
        paths = self.local_paths_from_urls(md.urls())
        if paths:
            self.paths_dropped.emit(paths, self._active_tab_id)
            event.acceptProposedAction()

    def caption_text(self, text: str, width: int) -> str:
        metrics = QFontMetrics(self.font())
        if width <= 0 or not text:
            return _ELLIPSIS if text else ""
        if metrics.horizontalAdvance(text) <= width:
            return text
        split_at = 0
        for index in range(1, len(text) + 1):
            if metrics.horizontalAdvance(text[:index]) > width:
                break
            split_at = index
        if split_at <= 0:
            return _elide_line(metrics, text, width)
        first = text[:split_at]
        second = _elide_line(metrics, text[split_at:], width)
        if not second.endswith(_ELLIPSIS):
            second = _elide_line(
                metrics,
                text[split_at:],
                max(1, width - metrics.horizontalAdvance(_ELLIPSIS)),
            )
        return f"{first}\n{second}"

    def set_entries(
        self,
        entries: list[IndexedItem],
        *,
        restorable_paths: set[Path] | frozenset[Path] | None = None,
        groups: list[GroupBlock] | None = None,
    ) -> None:
        next_entries = list(entries)
        next_groups = [
            GroupBlock(
                group_id=block.group_id,
                name=block.name,
                members=[Path(path).resolve() for path in block.members],
            )
            for block in (groups or [])
        ]
        if restorable_paths is None:
            next_restorable_paths = frozenset()
        else:
            next_restorable_paths = frozenset(Path(path).resolve() for path in restorable_paths)
        fingerprint = self._entry_render_fingerprint(
            next_entries,
            next_groups,
            next_restorable_paths,
        )
        if fingerprint == self._render_fingerprint:
            return
        self._render_fingerprint = fingerprint
        self._entries = next_entries
        self._groups = next_groups
        self._restorable_paths = next_restorable_paths
        self._rebuild_cells()

    def _entry_render_fingerprint(
        self,
        entries: list[IndexedItem],
        groups: list[GroupBlock],
        restorable_paths: frozenset[Path],
    ) -> tuple[object, ...]:
        return (
            tuple(str(Path(entry.path).resolve()) for entry in entries),
            tuple(
                (
                    block.group_id,
                    block.name,
                    tuple(str(Path(path).resolve()) for path in block.members),
                )
                for block in groups
            ),
            tuple(sorted(str(path) for path in restorable_paths)),
        )

    def entry_paths(self) -> list[Path]:
        return [entry.path.resolve() for entry in self._entries]

    def selected_path(self) -> Path | None:
        return self._focus_path

    def selected_paths(self) -> frozenset[Path]:
        return frozenset(self._selected_paths)

    def item_count(self) -> int:
        return len(self._entries)

    def effective_minimum_height(self) -> int:
        return self._scroll_area.minimumSizeHint().height()

    def shows_empty_state(self) -> bool:
        return not self._entries

    def empty_state_text(self) -> str:
        return self._empty_label.text()

    def _usable_grid_width(self) -> int:
        viewport = self._scroll_area.viewport()
        if viewport is None:
            return 0
        return max(0, viewport.width())

    def _caption_width(self) -> int:
        return max(_MIN_CAPTION_WIDTH, self._item_icon_size + 40)

    def _cell_width(self) -> int:
        if self._layout_mode() == "list":
            return max(_MIN_CELL_WIDTH, self._usable_grid_width() - 16)
        return max(
            _MIN_CELL_WIDTH,
            self._caption_width() + 8,
            self._item_icon_size + (_ICON_PADDING * 2),
        )

    def column_count(self) -> int:
        available = self._usable_grid_width()
        if available <= 0:
            return _MIN_COLUMNS
        if self._layout_mode() == "list":
            return _MIN_COLUMNS
        cell_width = self._cell_width()
        return max(
            _MIN_COLUMNS,
            (available - _MIN_GRID_GAP) // (cell_width + _MIN_GRID_GAP),
        )

    def _layout_mode(self) -> str:
        available = self._usable_grid_width()
        widget_width = self.width()
        if self.isVisible() and available > 0:
            visible_width = available
        elif widget_width > 0:
            visible_width = widget_width
        elif available > 0:
            visible_width = available
        else:
            return self._last_layout_mode
        if self._last_layout_mode == "list":
            return "list" if visible_width <= _LIST_MODE_EXIT_WIDTH else "grid"
        return "list" if visible_width <= _LIST_MODE_ENTER_WIDTH else "grid"

    def _cell_icon_size(self) -> int:
        if self._layout_mode() == "list":
            return min(_LIST_ICON_SIZE, self._item_icon_size)
        return self._item_icon_size

    def _apply_adaptive_spacing(self, columns: int) -> None:
        if self._layout_mode() == "list":
            self._layout.setContentsMargins(8, 6, 8, 6)
            self._layout.setHorizontalSpacing(0)
            self._grid_host.updateGeometry()
            return
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setHorizontalSpacing(_MIN_GRID_GAP)
        self._grid_host.updateGeometry()

    def _rebuild_cells(self) -> None:
        self._cancel_pending_group_open()
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item is None:
                break
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._cells_by_path.clear()
        self._cells_by_group_id.clear()
        self._folder_labels_by_group_id.clear()
        self._folder_rename_editors_by_group_id.clear()
        self._group_blocks_by_id.clear()
        self._close_group_folder()
        self._update_drop_ghost(None)
        visible_paths = {entry.path.resolve() for entry in self._entries}
        self._selected_paths = {path for path in self._selected_paths if path in visible_paths}
        if self._focus_path not in visible_paths:
            self._focus_path = next(iter(self._selected_paths), None)
        if self._selection_anchor not in visible_paths:
            self._selection_anchor = self._focus_path
        if not self._entries:
            self._grid_host.hide()
            self._empty_label.show()
            self._last_column_count = 0
            self._last_layout_mode = self._layout_mode()
            self.cells_rebuilt.emit()
            return
        self._empty_label.hide()
        self._grid_host.show()
        columns = self.column_count()
        self._last_column_count = columns
        self._last_layout_mode = self._layout_mode()
        self._apply_adaptive_spacing(columns)
        caption_width = self._caption_width()
        self._display_slots = self._build_display_slots()
        for index, slot in enumerate(self._display_slots):
            row = index // columns
            column = index % columns
            if slot.kind == "item" and slot.entry is not None:
                self._layout.addWidget(
                    self._make_cell(slot.entry, caption_width),
                    row,
                    column,
                )
            elif slot.kind == "group" and slot.group is not None:
                self._layout.addWidget(
                    self._make_folder_cell(slot.group, caption_width),
                    row,
                    column,
                )
        self.cells_rebuilt.emit()

    def _make_folder_cell(self, block: GroupBlock, caption_width: int) -> QWidget:
        cell = QWidget(self._grid_host)
        cell.setObjectName("folderCell")
        cell.setFixedWidth(self._cell_width())
        cell.setCursor(Qt.CursorShape.PointingHandCursor)
        anchor = block.members[0]

        preview_box = QWidget(cell)
        preview_box.setObjectName("folderPreview")
        preview_box.setCursor(Qt.CursorShape.PointingHandCursor)
        icon_size = max(16, self._cell_icon_size() // 2)
        preview_side = icon_size * 2 + 12
        preview_box.setFixedSize(preview_side, preview_side)
        preview_box.setStyleSheet(_FOLDER_PREVIEW_STYLE)
        cell.setMinimumHeight(preview_side + 40)
        mini_grid = QGridLayout(preview_box)
        mini_grid.setContentsMargins(4, 4, 4, 4)
        mini_grid.setHorizontalSpacing(2)
        mini_grid.setVerticalSpacing(2)
        preview_members = block.members[:_FOLDER_PREVIEW_COUNT]
        for index, member in enumerate(preview_members):
            mini_button = QToolButton(preview_box)
            mini_button.setAutoRaise(True)
            mini_button.setIcon(self._visuals.icon_for(member))
            mini_button.setIconSize(QSize(icon_size, icon_size))
            mini_button.setFixedSize(icon_size, icon_size)
            mini_button.setStyleSheet("QToolButton { background: transparent; border: none; }")
            mini_button.setEnabled(False)
            mini_grid.addWidget(mini_button, index // 2, index % 2)

        label_text = self.caption_text(block.name or "未命名分组", caption_width)
        label = QLabel(label_text, cell)
        label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        label.setWordWrap(True)
        label.setMaximumWidth(caption_width + 8)
        label.setStyleSheet("color: #f0f0f0; background: transparent;")
        label.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(cell)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(preview_box, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(label, alignment=Qt.AlignmentFlag.AlignHCenter)

        resolved_anchor = anchor.resolve()
        self._cells_by_group_id[block.group_id] = cell
        self._folder_labels_by_group_id[block.group_id] = label
        cell.installEventFilter(self)
        preview_box.installEventFilter(self)
        label.installEventFilter(self)
        cell.setProperty("_group_id", block.group_id)
        cell.setProperty("_item_path", resolved_anchor)
        preview_box.setProperty("_group_id", block.group_id)
        preview_box.setProperty("_item_path", resolved_anchor)
        label.setProperty("_group_id", block.group_id)
        label.setProperty("_item_path", resolved_anchor)
        cell.setProperty("_folder_preview", preview_box)
        self._update_folder_cell_style(block.group_id)
        return cell

    def _update_folder_cell_style(self, group_id: str) -> None:
        cell = self._cells_by_group_id.get(group_id)
        if cell is None:
            return
        block = self._group_block(group_id)
        selected = bool(
            block and block.members and block.members[0] in self._selected_paths
        )
        if group_id == self._folder_drop_target_id:
            cell.setStyleSheet(
                "QWidget#folderCell { background: rgba(120, 200, 255, 0.28); "
                "border: 2px solid rgba(120, 200, 255, 0.85); border-radius: 10px; }"
            )
        elif group_id == self._open_group_id:
            cell.setStyleSheet(
                "QWidget#folderCell { background: rgba(255,255,255,0.22); "
                "border: 2px solid rgba(255,255,255,0.55); border-radius: 10px; }"
            )
        elif group_id == self._folder_hover_id:
            cell.setStyleSheet(
                "QWidget#folderCell { background: rgba(255,255,255,0.14); "
                "border: 1px solid rgba(255,255,255,0.38); border-radius: 8px; }"
            )
        elif selected:
            cell.setStyleSheet(
                "QWidget#folderCell { background: rgba(255,255,255,0.18); "
                "border: 1px solid rgba(255,255,255,0.42); border-radius: 8px; }"
            )
        else:
            cell.setStyleSheet(
                "QWidget#folderCell { background: transparent; border: none; }"
            )

    def _apply_folder_selection_style(self, cell: QWidget, selected: bool) -> None:
        group_id = str(cell.property("_group_id") or "")
        if group_id:
            self._update_folder_cell_style(group_id)
            return
        if selected:
            cell.setStyleSheet(
                "QWidget#folderCell { background: rgba(255,255,255,0.18); "
                "border: 1px solid rgba(255,255,255,0.42); border-radius: 8px; }"
            )
        else:
            cell.setStyleSheet("QWidget#folderCell { background: transparent; border: none; }")

    def _prompt_rename_group(self, group_id: str, current_name: str = "") -> None:
        block = self._group_block(group_id)
        name = current_name or (block.name if block is not None else "")
        cell = self._cells_by_group_id.get(group_id)
        label = self._folder_labels_by_group_id.get(group_id)
        if cell is None or label is None:
            if name.strip():
                self.group_rename_requested.emit(group_id, name.strip())
            return
        editor = self._folder_rename_editors_by_group_id.get(group_id)
        if editor is not None and isValid(editor):
            editor.setFocus()
            editor.selectAll()
            return

        editor = QLineEdit(cell)
        editor.setObjectName("folderRenameEditor")
        editor.setText(name)
        editor.setAlignment(Qt.AlignmentFlag.AlignCenter)
        editor.setMaximumWidth(max(80, label.maximumWidth()))
        editor.setStyleSheet(
            "QLineEdit#folderRenameEditor {"
            "  color: #ffffff;"
            "  background: rgba(16, 16, 20, 0.88);"
            "  border: 1px solid rgba(255,255,255,0.72);"
            "  border-radius: 4px;"
            "  padding: 2px 4px;"
            "}"
        )
        layout = cell.layout()
        if layout is None:
            editor.deleteLater()
            return
        index = layout.indexOf(label)
        if index < 0:
            index = layout.count()
        label.hide()
        layout.insertWidget(index, editor, alignment=Qt.AlignmentFlag.AlignHCenter)
        self._folder_rename_editors_by_group_id[group_id] = editor
        done = {"value": False}

        def commit() -> None:
            if done["value"]:
                return
            done["value"] = True
            text = editor.text().strip()
            self._folder_rename_editors_by_group_id.pop(group_id, None)
            editor.hide()
            editor.setParent(None)
            editor.deleteLater()
            if isValid(label):
                label.show()
            if text and text != name.strip():
                self.group_rename_requested.emit(group_id, text)

        editor.returnPressed.connect(commit)
        editor.editingFinished.connect(commit)
        editor.show()
        editor.setFocus()
        editor.selectAll()

    def _make_cell(self, entry: IndexedItem, caption_width: int) -> QWidget:
        cell = QWidget(self._grid_host)
        cell.setObjectName("itemCell")
        cell.setFixedWidth(self._cell_width())
        cell.setCursor(Qt.CursorShape.ArrowCursor)
        cell.setAutoFillBackground(True)
        cell_palette = cell.palette()
        cell_palette.setColor(cell.backgroundRole(), Qt.GlobalColor.transparent)
        cell.setPalette(cell_palette)

        button = QToolButton(cell)
        button.setAutoRaise(True)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setIcon(self._visuals.icon_for(entry.path))
        icon_size = self._cell_icon_size()
        button.setIconSize(QSize(icon_size, icon_size))
        button.setFixedSize(
            icon_size + _ICON_PADDING,
            icon_size + _ICON_PADDING,
        )
        button.setStyleSheet("QToolButton { background: transparent; border: none; }")
        button.setCursor(Qt.CursorShape.ArrowCursor)
        display_name = display_name_for_path(entry.path)
        list_mode = self._layout_mode() == "list"
        if list_mode:
            label_text = _elide_line(QFontMetrics(self.font()), display_name, caption_width)
        else:
            label_text = self.caption_text(display_name, caption_width)
        label = QLabel(label_text, cell)
        label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        label.setWordWrap(not list_mode)
        label.setMaximumWidth(caption_width + 8)
        if list_mode:
            label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        else:
            label.setFixedWidth(caption_width + 8)
        label.setStyleSheet("color: #f0f0f0; background: transparent;")
        label.setCursor(Qt.CursorShape.ArrowCursor)

        if list_mode:
            list_layout = QHBoxLayout(cell)
            list_layout.setContentsMargins(0, 0, 0, 0)
            list_layout.setSpacing(8)
            list_layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignVCenter)
            list_layout.addWidget(label, stretch=1, alignment=Qt.AlignmentFlag.AlignVCenter)
        else:
            layout = QVBoxLayout(cell)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(4)
            layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignHCenter)
            layout.addWidget(label, alignment=Qt.AlignmentFlag.AlignHCenter)

        resolved_path = entry.path.resolve()
        self._cells_by_path[resolved_path] = cell
        cell.installEventFilter(self)
        cell.setProperty("_item_path", resolved_path)
        button.installEventFilter(self)
        button.setProperty("_item_path", resolved_path)
        label.installEventFilter(self)
        label.setProperty("_item_path", resolved_path)
        self._apply_cell_selection_style(cell, resolved_path in self._selected_paths)

        return cell

    def _display_ordered_paths(self) -> list[Path]:
        if self._display_slots:
            ordered: list[Path] = []
            for slot in self._display_slots:
                if slot.kind == "item" and slot.entry is not None:
                    ordered.append(slot.entry.path.resolve())
                elif slot.kind == "group" and slot.group is not None:
                    ordered.extend(slot.group.members)
            return ordered
        return [entry.path.resolve() for entry in self._entries]

    def _apply_all_selection_styles(self) -> None:
        for path, cell in self._cells_by_path.items():
            self._apply_cell_selection_style(cell, path in self._selected_paths)
        for group_id, cell in self._cells_by_group_id.items():
            block = self._group_block(group_id)
            if block is None or not block.members:
                continue
            self._apply_folder_selection_style(
                cell,
                block.members[0] in self._selected_paths,
            )

    def _clear_selection(self) -> None:
        if not self._selected_paths:
            self._focus_path = None
            self._selection_anchor = None
            return
        self._selected_paths.clear()
        self._focus_path = None
        self._selection_anchor = None
        self._apply_all_selection_styles()

    def _select_single_path(self, path: Path) -> None:
        resolved = path.resolve()
        self._selected_paths = {resolved}
        self._focus_path = resolved
        self._selection_anchor = resolved
        self._apply_all_selection_styles()
        self.item_selected.emit(resolved)

    def _toggle_path_selection(self, path: Path) -> None:
        resolved = path.resolve()
        if resolved in self._selected_paths:
            self._selected_paths.remove(resolved)
            if self._focus_path == resolved:
                self._focus_path = next(iter(self._selected_paths), None)
            if self._selection_anchor == resolved:
                self._selection_anchor = self._focus_path
        else:
            self._selected_paths.add(resolved)
            self._focus_path = resolved
            if self._selection_anchor is None:
                self._selection_anchor = resolved
        self._apply_all_selection_styles()
        if self._focus_path is not None:
            self.item_selected.emit(self._focus_path)

    def _select_range_to(self, path: Path) -> None:
        resolved = path.resolve()
        ordered = self._display_ordered_paths()
        if resolved not in ordered:
            return
        anchor = self._selection_anchor or self._focus_path or resolved
        if anchor not in ordered:
            anchor = resolved
        start = ordered.index(anchor)
        end = ordered.index(resolved)
        if start > end:
            start, end = end, start
        self._selected_paths = set(ordered[start : end + 1])
        self._focus_path = resolved
        self._apply_all_selection_styles()
        self.item_selected.emit(resolved)

    def _drag_paths_for(self, source_path: Path) -> list[Path]:
        resolved = source_path.resolve()
        for block in self._groups:
            if block.members and block.members[0] == resolved:
                if resolved in self._selected_paths and len(self._selected_paths) > 1:
                    ordered = self._display_ordered_paths()
                    selected = self._selected_paths
                    return [path for path in ordered if path in selected]
                return [resolved]
        if resolved in self._selected_paths and len(self._selected_paths) > 1:
            ordered = self._display_ordered_paths()
            selected = self._selected_paths
            return [path for path in ordered if path in selected]
        return [resolved]

    def _select_path(self, path: Path) -> None:
        self._select_single_path(path)

    def _apply_cell_selection_style(self, cell: QWidget, selected: bool) -> None:
        if selected:
            cell.setStyleSheet(
                "QWidget#itemCell { background: rgba(255,255,255,0.18); "
                "border: 1px solid rgba(255,255,255,0.42); border-radius: 6px; }"
            )
        else:
            cell.setStyleSheet("QWidget#itemCell { background: transparent; border: none; }")

    def _show_context_menu(self, path: Path, global_pos) -> None:  # type: ignore[no-untyped-def]
        owner = self.window() or self
        resolved = path.resolve()
        if self._context_menu is not None:
            self._context_menu.close()
            self._context_menu = None
        shown = False
        try:
            shown = bool(self._context_menu_launcher(owner, resolved, global_pos))
        except Exception:
            shown = False
        if not shown:
            self._fallback_context_menu(resolved, global_pos)

    def _show_basic_context_menu(self, path: Path, global_pos) -> None:  # type: ignore[no-untyped-def]
        menu = QMenu(self)
        open_action = menu.addAction("打开")
        reveal_action = menu.addAction("打开所在位置")
        copy_action = menu.addAction("复制路径")

        open_action.triggered.connect(lambda _checked=False, p=path: self.item_activated.emit(p))

        def reveal() -> None:
            try:
                subprocess.Popen(["explorer.exe", "/select,", str(path)])
            except Exception:
                pass

        def copy_path() -> None:
            clipboard = QApplication.clipboard()
            if clipboard is not None:
                clipboard.setText(str(path))

        reveal_action.triggered.connect(reveal)
        copy_action.triggered.connect(copy_path)
        menu.aboutToHide.connect(lambda m=menu: self._clear_context_menu(m))
        self._context_menu = menu
        menu.popup(global_pos)

    def _clear_context_menu(self, menu: QMenu) -> None:
        if self._context_menu is menu:
            self._context_menu = None

    def _dismiss_context_menu(self) -> None:
        menu = self._context_menu
        self._context_menu = None
        if menu is not None and isValid(menu):
            menu.close()

    def _show_folder_context_menu(self, group_id: str, global_pos) -> None:  # type: ignore[no-untyped-def]
        block = self._group_block(group_id)
        if block is None:
            return
        if self._context_menu is not None:
            return
        menu = QMenu(self)
        open_action = menu.addAction("打开")
        rename_action = menu.addAction("重命名")
        dissolve_action = menu.addAction("解散分组")
        open_action.triggered.connect(
            lambda: self._open_group_folder(
                group_id,
                self._cells_by_group_id[group_id],
            )
        )
        rename_action.triggered.connect(
            lambda: self._prompt_rename_group(group_id, block.name)
        )
        dissolve_action.triggered.connect(
            lambda: self.group_dissolve_requested.emit(group_id)
        )
        menu.aboutToHide.connect(lambda m=menu: self._clear_context_menu(m))
        self._context_menu = menu
        menu.popup(global_pos)

    def eventFilter(self, watched, event) -> bool:  # type: ignore[no-untyped-def]
        if event.type() == event.Type.Wheel and self._handle_zoom_wheel_event(event):
            return True
        if (
            watched is self._scroll_area.viewport()
            and event.type() == event.Type.MouseButtonPress
            and event.button() == Qt.MouseButton.LeftButton
        ):
            expansion = self._inline_group_expansion
            if expansion is None or not expansion.isVisible():
                self._cancel_pending_group_open()
            elif not expansion.geometry().contains(event.position().toPoint()):
                self._close_group_folder(immediate=True)
                return False
        path = watched.property("_item_path")
        group_id = str(watched.property("_group_id") or "")
        if group_id and event.type() in (event.Type.Enter, event.Type.Leave):
            if event.type() == event.Type.Enter:
                if self._folder_hover_id != group_id:
                    previous = self._folder_hover_id
                    self._folder_hover_id = group_id
                    if previous:
                        self._update_folder_cell_style(previous)
                    self._update_folder_cell_style(group_id)
            elif self._folder_hover_id == group_id:
                self._folder_hover_id = ""
                self._update_folder_cell_style(group_id)
            return False
        if (
            _DRAG_DEBUG
            and path is not None
            and event.type() == event.Type.MouseMove
        ):
            _drag_dbg(
                "move",
                type(watched).__name__,
                "buttons",
                int(event.buttons().value),
                "reorder",
                self._reorder_enabled,
                "src",
                self._drag_source_path is not None,
            )
        if (
            path is not None
            and self._reorder_enabled
            and event.type() == event.Type.MouseMove
            and event.buttons() & Qt.MouseButton.LeftButton
            and self._drag_source_path is not None
            and self._drag_start_pos is not None
        ):
            moved = (
                event.globalPosition().toPoint() - self._drag_start_pos
            ).manhattanLength()
            _drag_dbg("move-threshold", moved, "need", QApplication.startDragDistance())
            if moved >= QApplication.startDragDistance():
                if self._folder_press_group_id:
                    self._folder_drag_started = True
                    self._drag_from_folder_group_id = self._folder_press_group_id
                source = self._drag_source_path
                self._start_item_drag(source)
                return True
        if path is not None and event.type() == event.Type.ContextMenu:
            resolved_path = Path(str(path))
            if group_id:
                if resolved_path.resolve() not in self._selected_paths:
                    self._select_single_path(resolved_path)
                self._show_folder_context_menu(group_id, event.globalPos())
                return True
            if resolved_path.resolve() not in self._selected_paths:
                self._select_single_path(resolved_path)
            else:
                self._focus_path = resolved_path.resolve()
            self._show_context_menu(resolved_path, event.globalPos())
            return True
        if (
            path is not None
            and event.type()
            in (
                event.Type.MouseButtonPress,
                event.Type.MouseButtonRelease,
                event.Type.MouseButtonDblClick,
            )
            and event.button()
            in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton)
        ):
            resolved_path = Path(str(path))
            if (
                event.type() == event.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.RightButton
            ):
                if group_id:
                    self._select_single_path(resolved_path)
                    return True
                if resolved_path.resolve() not in self._selected_paths:
                    self._select_single_path(resolved_path)
                else:
                    self._focus_path = resolved_path.resolve()
                return True
            if (
                event.type() == event.Type.MouseButtonRelease
                and event.button() == Qt.MouseButton.RightButton
            ):
                if group_id:
                    self._select_single_path(resolved_path)
                    self._show_folder_context_menu(
                        group_id,
                        event.globalPosition().toPoint(),
                    )
                    return True
                if resolved_path.resolve() not in self._selected_paths:
                    self._select_single_path(resolved_path)
                else:
                    self._focus_path = resolved_path.resolve()
                self._show_context_menu(resolved_path, event.globalPosition().toPoint())
                return True
            if event.type() == event.Type.MouseButtonPress:
                modifiers = event.modifiers()
                if event.button() == Qt.MouseButton.LeftButton:
                    self._dismiss_context_menu()
                    resolved = resolved_path.resolve()
                    if not group_id:
                        self._cancel_pending_group_open()
                    if (
                        self._inline_group_expansion is not None
                        and not group_id
                    ):
                        self._close_group_folder(immediate=True)
                    if group_id and not self._suppress_folder_click:
                        self._drag_source_path = resolved
                        self._folder_press_group_id = group_id
                        self._folder_drag_started = False
                        self._drag_start_pos = event.globalPosition().toPoint()
                        self._dragging = False
                        return True
                    if modifiers & Qt.KeyboardModifier.ShiftModifier:
                        self._select_range_to(resolved_path)
                    elif modifiers & Qt.KeyboardModifier.ControlModifier:
                        self._toggle_path_selection(resolved_path)
                    elif (
                        resolved in self._selected_paths
                        and len(self._selected_paths) > 1
                    ):
                        self._focus_path = resolved
                        self._apply_all_selection_styles()
                        self.item_selected.emit(resolved)
                    else:
                        self._select_single_path(resolved_path)
                    self._drag_source_path = resolved
                    self._folder_press_group_id = group_id
                    self._drag_start_pos = event.globalPosition().toPoint()
                    self._dragging = False
                    _drag_dbg(
                        "press",
                        type(watched).__name__,
                        resolved_path.name,
                        "reorder",
                        self._reorder_enabled,
                        "selected",
                        len(self._selected_paths),
                    )
                return False
            if (
                event.type() == event.Type.MouseButtonRelease
                and event.button() == Qt.MouseButton.LeftButton
            ):
                if group_id:
                    if not self._folder_drag_started and not self._suppress_folder_click:
                        self._select_single_path(resolved_path)
                        self._schedule_group_folder_open(group_id)
                    self._suppress_folder_click = False
                    self._folder_press_group_id = ""
                    self._folder_drag_started = False
                    self._reset_drag_state()
                    return True
                self._suppress_folder_click = False
                self._folder_press_group_id = ""
                self._reset_drag_state()
                return False
            if event.type() == event.Type.MouseButtonDblClick:
                if group_id:
                    self._cancel_pending_group_open()
                    if self._open_group_id != group_id:
                        self._switch_group_folder(group_id)
                    return True
                self._select_single_path(resolved_path)
                self.item_activated.emit(Path(str(path)))
                return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.key() == Qt.Key.Key_Escape:
            if (
                self._inline_group_expansion is not None
                and self._inline_group_expansion.isVisible()
            ):
                self._close_group_folder(immediate=True)
                event.accept()
                return
        if event.key() == Qt.Key.Key_F2:
            group_id = self._group_id_for_keyboard_rename()
            if group_id:
                block = self._group_block(group_id)
                self._prompt_rename_group(
                    group_id,
                    block.name if block is not None else "",
                )
                event.accept()
                return
        super().keyPressEvent(event)

    def _group_id_for_keyboard_rename(self) -> str:
        if self._open_group_id:
            return self._open_group_id
        for group_id, block in self._group_blocks_by_id.items():
            if block.members and block.members[0] in self._selected_paths:
                return group_id
        return ""

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        self._reposition_open_group_popup()
        if not self._entries:
            return
        columns = self.column_count()
        mode = self._layout_mode()
        if mode != self._last_layout_mode:
            self._rebuild_cells()
            return
        if self._layout_updates_suspended:
            if columns != self._last_column_count:
                self._relayout_existing_cells(columns)
            else:
                self._apply_adaptive_spacing(columns)
            return
        if columns != self._last_column_count:
            self._rebuild_cells()
        else:
            self._apply_adaptive_spacing(columns)

    def wheelEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self._handle_zoom_wheel_event(event):
            return
        super().wheelEvent(event)

    def _handle_zoom_wheel_event(self, event) -> bool:  # type: ignore[no-untyped-def]
        if not event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            return False
        delta = event.angleDelta().y()
        if not delta:
            return False
        step = _ICON_STEP if delta > 0 else -_ICON_STEP
        self.set_item_icon_size(self._item_icon_size + step)
        event.accept()
        return True

    def _update_existing_cell_metrics(self) -> None:
        caption_width = self._caption_width()
        icon_size = self._cell_icon_size()
        list_mode = self._layout_mode() == "list"
        metrics = QFontMetrics(self.font())
        for entry in self._entries:
            cell = self._cells_by_path.get(entry.path.resolve())
            if cell is None:
                self._pending_rebuild_after_suspension = True
                return
            cell.setFixedWidth(self._cell_width())
            button = cell.findChild(QToolButton)
            if button is not None:
                button.setIconSize(QSize(icon_size, icon_size))
                button.setFixedSize(icon_size + _ICON_PADDING, icon_size + _ICON_PADDING)
            label = cell.findChild(QLabel)
            if label is not None:
                label.setMaximumWidth(caption_width + 8)
                label.setWordWrap(not list_mode)
                if list_mode:
                    label.setMinimumWidth(0)
                    label.setMaximumWidth(caption_width + 8)
                    label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
                else:
                    label.setFixedWidth(caption_width + 8)
                display_name = display_name_for_path(entry.path)
                if list_mode:
                    label.setText(_elide_line(metrics, display_name, caption_width))
                else:
                    label.setText(self.caption_text(display_name, caption_width))

    def _relayout_existing_cells(self, columns: int) -> None:
        if self._groups:
            self._rebuild_cells()
            return
        columns = max(_MIN_COLUMNS, columns or _MIN_COLUMNS)
        cells: list[QWidget] = []
        for entry in self._entries:
            cell = self._cells_by_path.get(entry.path.resolve())
            if cell is None:
                self._pending_rebuild_after_suspension = True
                return
            cells.append(cell)
        while self._layout.count():
            self._layout.takeAt(0)
        self._last_column_count = columns
        self._last_layout_mode = self._layout_mode()
        self._apply_adaptive_spacing(columns)
        self._update_existing_cell_metrics()
        for index, cell in enumerate(cells):
            row = index // columns
            column = index % columns
            self._layout.addWidget(cell, row, column)


def _elide_line(metrics: QFontMetrics, text: str, width: int) -> str:
    if not text:
        return ""
    if metrics.horizontalAdvance(text) <= width:
        return text
    suffix_width = metrics.horizontalAdvance(_ELLIPSIS)
    available = width - suffix_width
    if available <= 0:
        return _ELLIPSIS
    low = 0
    high = len(text)
    while low < high:
        mid = (low + high + 1) // 2
        if metrics.horizontalAdvance(text[:mid]) <= available:
            low = mid
        else:
            high = mid - 1
    return text[:low] + _ELLIPSIS


def display_name_for_path(path: Path) -> str:
    name = path.name
    if not name:
        return name
    suffixes = path.suffixes
    if not suffixes:
        return name
    if name.startswith(".") and len(suffixes) == 1 and name == suffixes[0]:
        return name
    display_name = name
    for suffix in reversed(suffixes):
        if display_name.lower().endswith(suffix.lower()):
            display_name = display_name[: -len(suffix)]
    return display_name or name
