"""Grid of opaque desktop item cells with a two-line caption helper."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from desktop_tidy.services.desktop_index import IndexedItem
from desktop_tidy.services.item_visuals import ItemVisualProvider

_EMPTY_STATE_TEXT = "此分类暂无内容"
_ICON_SIZE = 48
_CELL_HORIZONTAL = 100
_CELL_WIDTH = 96
_CAPTION_WIDTH = 88
_MIN_COLUMNS = 1
_ELLIPSIS = "..."


class ItemGridWidget(QWidget):
    paths_dropped = Signal(object, str)
    restore_auto_requested = Signal(object)
    item_activated = Signal(Path)
    item_selected = Signal(Path)
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
        self._layout.setHorizontalSpacing(12)
        self._layout.setVerticalSpacing(12)
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
        margins = self._layout.contentsMargins()
        return max(
            0,
            viewport.width() - margins.left() - margins.right(),
        )

    def column_count(self) -> int:
        available = self._usable_grid_width()
        if available <= 0:
            return _MIN_COLUMNS
        return max(_MIN_COLUMNS, (available + 12) // (_CELL_HORIZONTAL + 12))

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
            self.cells_rebuilt.emit()
            return
        self._empty_label.hide()
        self._grid_host.show()
        columns = self.column_count()
        self._last_column_count = columns
        caption_width = _CAPTION_WIDTH
        for index, entry in enumerate(self._entries):
            row = index // columns
            column = index % columns
            self._layout.addWidget(self._make_cell(entry, caption_width), row, column)
        self.cells_rebuilt.emit()

    def _make_cell(self, entry: IndexedItem, caption_width: int) -> QWidget:
        cell = QWidget(self._grid_host)
        cell.setObjectName("itemCell")
        cell.setFixedWidth(_CELL_WIDTH)
        cell.setCursor(Qt.CursorShape.ArrowCursor)
        cell.setAutoFillBackground(True)
        cell_palette = cell.palette()
        cell_palette.setColor(cell.backgroundRole(), Qt.GlobalColor.transparent)
        cell.setPalette(cell_palette)

        button = QToolButton(cell)
        button.setAutoRaise(True)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setIcon(self._visuals.icon_for(entry.path))
        button.setIconSize(QSize(_ICON_SIZE, _ICON_SIZE))
        button.setFixedSize(_ICON_SIZE + 8, _ICON_SIZE + 8)
        button.setStyleSheet("QToolButton { background: transparent; border: none; }")
        button.setCursor(Qt.CursorShape.ArrowCursor)
        label = QLabel(self.caption_text(entry.path.name, caption_width), cell)
        label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        label.setWordWrap(True)
        label.setMaximumWidth(caption_width + 8)
        label.setStyleSheet("color: #f0f0f0; background: transparent;")
        label.setCursor(Qt.CursorShape.ArrowCursor)

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

    def eventFilter(self, watched, event) -> bool:  # type: ignore[no-untyped-def]
        path = watched.property("_item_path")
        if (
            path is not None
            and event.type()
            in (event.Type.MouseButtonPress, event.Type.MouseButtonDblClick)
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
        if self._entries and self.column_count() != self._last_column_count:
            self._rebuild_cells()


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
