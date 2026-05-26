"""Grid of opaque desktop item cells with a two-line caption helper."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
from typing import Callable

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from desktop_tidy.services.desktop_index import IndexedItem
from desktop_tidy.services.item_visuals import ItemVisualProvider
from desktop_tidy.services.shell_context_menu import ShellContextMenuService

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
_ELLIPSIS = "..."
ContextMenuLauncher = Callable[[QWidget, Path, object], bool]
FallbackContextMenu = Callable[[Path, object], None]


class ItemGridWidget(QWidget):
    paths_dropped = Signal(object, str)
    restore_auto_requested = Signal(object)
    item_activated = Signal(Path)
    item_selected = Signal(Path)
    item_icon_size_changed = Signal(int)
    cells_rebuilt = Signal()

    def __init__(self, parent: QWidget | None = None, *, active_tab_id: str = "") -> None:
        super().__init__(parent)
        self._active_tab_id = active_tab_id
        self._visuals = ItemVisualProvider()
        self._entries: list[IndexedItem] = []
        self._restorable_paths: frozenset[Path] = frozenset()
        self._selected_path: Path | None = None
        self._cells_by_path: dict[Path, QWidget] = {}
        self._last_column_count = 0
        self._last_layout_mode = "grid"
        self._item_icon_size = _DEFAULT_ICON_SIZE
        self._layout_updates_suspended = False
        self._pending_rebuild_after_suspension = False
        self._native_context_menu = ShellContextMenuService()
        self._context_menu: QMenu | None = None
        if os.environ.get("DESKTOP_TIDY_DISABLE_NATIVE_CONTEXT_MENU") == "1":
            self._context_menu_launcher: ContextMenuLauncher = lambda _owner, _path, _global_pos: False
        else:
            self._context_menu_launcher = self._native_context_menu.show
        if os.environ.get("DESKTOP_TIDY_QT_CONTEXT_MENU_FALLBACK") == "1":
            self._fallback_context_menu: FallbackContextMenu = self._show_basic_context_menu
        else:
            self._fallback_context_menu = lambda _path, _global_pos: None
        self.setAcceptDrops(True)
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
        self._active_tab_id = tab_id

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
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        paths = self.local_paths_from_urls(event.mimeData().urls())
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
    ) -> None:
        self._entries = list(entries)
        if restorable_paths is None:
            self._restorable_paths = frozenset()
        else:
            self._restorable_paths = frozenset(Path(path).resolve() for path in restorable_paths)
        self._rebuild_cells()

    def entry_paths(self) -> list[Path]:
        return [entry.path.resolve() for entry in self._entries]

    def selected_path(self) -> Path | None:
        return self._selected_path

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
        visible_columns = max(
            _MIN_COLUMNS,
            min(columns or _MIN_COLUMNS, len(self._entries) or _MIN_COLUMNS),
        )
        available = self._usable_grid_width()
        cell_width = self._cell_width()
        spare = max(0, available - (visible_columns * cell_width))
        gap = max(_MIN_GRID_GAP, spare // (visible_columns + 1))
        self._layout.setContentsMargins(gap, 8, gap, 8)
        self._layout.setHorizontalSpacing(gap)
        self._grid_host.updateGeometry()

    def _rebuild_cells(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._cells_by_path.clear()
        visible_paths = {entry.path.resolve() for entry in self._entries}
        if self._selected_path not in visible_paths:
            self._selected_path = None
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
        for index, entry in enumerate(self._entries):
            row = index // columns
            column = index % columns
            self._layout.addWidget(self._make_cell(entry, caption_width), row, column)
        self.cells_rebuilt.emit()

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
        self._apply_cell_selection_style(cell, resolved_path == self._selected_path)

        return cell

    def _select_path(self, path: Path) -> None:
        resolved = path.resolve()
        if self._selected_path == resolved:
            return
        previous = self._selected_path
        self._selected_path = resolved
        if previous is not None:
            previous_cell = self._cells_by_path.get(previous)
            if previous_cell is not None:
                self._apply_cell_selection_style(previous_cell, False)
        current_cell = self._cells_by_path.get(resolved)
        if current_cell is not None:
            self._apply_cell_selection_style(current_cell, True)
        self.item_selected.emit(resolved)

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

    def eventFilter(self, watched, event) -> bool:  # type: ignore[no-untyped-def]
        if event.type() == event.Type.Wheel and self._handle_zoom_wheel_event(event):
            return True
        path = watched.property("_item_path")
        if path is not None and event.type() == event.Type.ContextMenu:
            resolved_path = Path(str(path))
            self._select_path(resolved_path)
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
                self._select_path(resolved_path)
                return True
            if (
                event.type() == event.Type.MouseButtonRelease
                and event.button() == Qt.MouseButton.RightButton
            ):
                self._select_path(resolved_path)
                self._show_context_menu(resolved_path, event.globalPosition().toPoint())
                return True
            if event.type() == event.Type.MouseButtonPress:
                self._select_path(resolved_path)
                return False
            if event.type() == event.Type.MouseButtonDblClick:
                self._select_path(resolved_path)
                self.item_activated.emit(Path(str(path)))
                return True
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
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
