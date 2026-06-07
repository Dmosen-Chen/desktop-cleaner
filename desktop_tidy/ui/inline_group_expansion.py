"""Inline expanded view for a virtual item group inside an item grid."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRect,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from desktop_tidy.persistence.ui_preferences import DEFAULT_GROUP_ACCENT_COLOR
from desktop_tidy.services.item_visuals import ItemVisualProvider

ITEM_MIME_TYPE = "application/x-desktop-tidy-item-path"
_ICON_PADDING = 8
_MAX_VISIBLE_ROWS = 3
_MIN_CARD_WIDTH = 320
_MAX_CARD_WIDTH = 680
_GRID_COLUMNS = 5
_RENDER_BATCH_SIZE = 8


class _DragHost(Protocol):
    def begin_item_drag(
        self,
        source_path: Path,
        *,
        ghost_widget: QWidget | None = None,
    ) -> None:
        ...


def _paths_from_item_mime(data: bytes) -> list[Path]:
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


def _card_style(accent_color: str) -> str:
    color = accent_color if accent_color.startswith("#") else DEFAULT_GROUP_ACCENT_COLOR
    return (
        "QFrame#inlineGroupCard {"
        "  background: qlineargradient("
        "    x1:0, y1:0, x2:0, y2:1,"
        "    stop:0 rgba(54, 40, 56, 0.96),"
        "    stop:1 rgba(40, 28, 44, 0.96)"
        "  );"
        f"  border: 1px solid {color};"
        "  border-radius: 14px;"
        "}"
        "QWidget#inlineGroupHeader {"
        "  background: rgba(255,255,255,0.08);"
        "  border-top-left-radius: 13px;"
        "  border-top-right-radius: 13px;"
        "}"
        "QLabel { color: #f8fafc; background: transparent; }"
        "QToolButton { background: transparent; border: none; }"
    )


class InlineGroupExpansionWidget(QWidget):
    """A non-window group expansion card rendered inside the current grid viewport."""

    item_activated = Signal(Path)
    rename_requested = Signal(str)
    dissolve_requested = Signal(str)
    members_dropped = Signal(str, object)

    def __init__(
        self,
        *,
        group_id: str,
        name: str,
        members: list[Path],
        icon_size: int,
        accent_color: str = DEFAULT_GROUP_ACCENT_COLOR,
        parent: QWidget | None = None,
        visuals: ItemVisualProvider | None = None,
    ) -> None:
        super().__init__(parent)
        self._group_id = ""
        self._name = ""
        self._members: list[Path] = []
        self._icon_size = icon_size
        self._accent_color = accent_color
        self._visuals = visuals or ItemVisualProvider()
        self._drag_host: _DragHost | None = None
        self._drag_source_path: Path | None = None
        self._drag_start_pos: QPoint | None = None
        self._fingerprint: tuple[object, ...] | None = None
        self._grid_layout: QGridLayout | None = None
        self._grid_parent: QWidget | None = None
        self._pending_render_members: list[Path] = []
        self._pending_caption_width = 0
        self._render_index = 0
        self._open_animation: QPropertyAnimation | None = None
        self._slide_animation: QPropertyAnimation | None = None
        self._close_animation: QPropertyAnimation | None = None

        self.setObjectName("inlineGroupExpansion")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAcceptDrops(True)

        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity_effect)

        self._render_timer = QTimer(self)
        self._render_timer.setInterval(0)
        self._render_timer.timeout.connect(self._render_next_batch)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._card = QFrame(self)
        self._card.setObjectName("inlineGroupCard")
        self._card.setAcceptDrops(True)
        self._card.installEventFilter(self)
        outer.addWidget(self._card)

        self._layout = QVBoxLayout(self._card)
        self._layout.setContentsMargins(0, 0, 0, 16)
        self._layout.setSpacing(14)

        self._header = QWidget(self._card)
        self._header.setObjectName("inlineGroupHeader")
        header_layout = QHBoxLayout(self._header)
        header_layout.setContentsMargins(18, 12, 18, 12)
        header_layout.setSpacing(10)

        self._title_label = QLabel(self._header)
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_label.setStyleSheet("font-size: 18px; font-weight: 700;")
        self._count_label = QLabel(self._header)
        self._count_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._count_label.setStyleSheet(
            "color: rgba(248,250,252,0.72); font-size: 12px;"
        )
        header_layout.addStretch(1)
        header_layout.addWidget(self._title_label)
        header_layout.addStretch(1)
        header_layout.addWidget(self._count_label)
        self._layout.addWidget(self._header)

        self._content_host = QWidget(self._card)
        self._content_host.setAcceptDrops(True)
        self._content_host.installEventFilter(self)
        self._content_layout = QVBoxLayout(self._content_host)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._layout.addWidget(self._content_host)

        self.update_group(
            group_id=group_id,
            name=name,
            members=members,
            icon_size=icon_size,
            accent_color=accent_color,
        )
        self.hide()

    def group_id(self) -> str:
        return self._group_id

    def set_drag_host(self, host: _DragHost) -> None:
        self._drag_host = host

    def set_accent_color(self, accent_color: str) -> None:
        self._accent_color = accent_color
        self._card.setStyleSheet(_card_style(self._accent_color))

    def update_group(
        self,
        *,
        group_id: str,
        name: str,
        members: list[Path],
        icon_size: int,
        accent_color: str,
    ) -> None:
        resolved_members = [path.resolve() for path in members]
        fingerprint: tuple[object, ...] = (
            group_id,
            name,
            tuple(str(path) for path in resolved_members),
            icon_size,
            accent_color.upper(),
        )
        self._group_id = group_id
        self._name = name
        self._members = resolved_members
        self._icon_size = icon_size
        self._title_label.setText(self._name or "未命名分组")
        self._count_label.setText(f"{len(self._members)} 项")
        self.set_accent_color(accent_color)
        if fingerprint == self._fingerprint:
            return
        self._fingerprint = fingerprint
        self._rebuild_member_grid()

    def reposition_in(self, host: QWidget) -> None:
        host_rect = host.rect()
        if host_rect.width() <= 0 or host_rect.height() <= 0:
            return
        width = min(_MAX_CARD_WIDTH, max(_MIN_CARD_WIDTH, int(host_rect.width() * 0.58)))
        width = min(width, max(180, host_rect.width() - 32))
        self._card.setFixedWidth(width)
        self.adjustSize()
        height = min(self.sizeHint().height(), max(120, host_rect.height() - 32))
        x = host_rect.x() + (host_rect.width() - width) // 2
        y = host_rect.y() + max(16, (host_rect.height() - height) // 2)
        self.setGeometry(x, y, width, height)
        self.raise_()

    def show_animated(self, host: QWidget) -> None:
        self._stop_motion()
        self.reposition_in(host)
        final_geometry = QRect(self.geometry())
        start_geometry = QRect(final_geometry)
        start_geometry.translate(0, 8)
        self.setGeometry(start_geometry)
        self._opacity_effect.setOpacity(0.0)
        self.show()
        self.raise_()

        self._open_animation = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._open_animation.setDuration(120)
        self._open_animation.setStartValue(0.0)
        self._open_animation.setEndValue(1.0)
        self._open_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._slide_animation = QPropertyAnimation(self, b"geometry", self)
        self._slide_animation.setDuration(120)
        self._slide_animation.setStartValue(start_geometry)
        self._slide_animation.setEndValue(final_geometry)
        self._slide_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._open_animation.start()
        self._slide_animation.start()

    def hide_animated(self) -> None:
        if not self.isVisible():
            return
        self._stop_motion()
        self._close_animation = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._close_animation.setDuration(90)
        self._close_animation.setStartValue(self._opacity_effect.opacity())
        self._close_animation.setEndValue(0.0)
        self._close_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._close_animation.finished.connect(self.hide_immediately)
        self._close_animation.start()

    def hide_immediately(self) -> None:
        self._stop_motion()
        self._render_timer.stop()
        self._pending_render_members = []
        self.hide()
        self._opacity_effect.setOpacity(1.0)

    def dragEnterEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.mimeData().hasFormat(ITEM_MIME_TYPE):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.mimeData().hasFormat(ITEM_MIME_TYPE):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if not event.mimeData().hasFormat(ITEM_MIME_TYPE):
            super().dropEvent(event)
            return
        paths = _paths_from_item_mime(bytes(event.mimeData().data(ITEM_MIME_TYPE)))
        if paths:
            self.members_dropped.emit(self._group_id, paths)
            event.acceptProposedAction()

    def _stop_motion(self) -> None:
        for animation in (
            self._open_animation,
            self._slide_animation,
            self._close_animation,
        ):
            if animation is not None:
                animation.stop()
        self._open_animation = None
        self._slide_animation = None
        self._close_animation = None

    def _clear_content(self) -> None:
        self._render_timer.stop()
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._grid_layout = None
        self._grid_parent = None

    def _rebuild_member_grid(self) -> None:
        self._clear_content()
        columns = max(1, min(_GRID_COLUMNS, len(self._members) or 1))
        caption_width = max(88, min(118, self._icon_size + 54))
        row_height = self._icon_size + _ICON_PADDING + 58
        rows = max(1, (len(self._members) + columns - 1) // columns)

        grid_host = QWidget(self._content_host)
        grid_host.setAcceptDrops(True)
        grid_host.installEventFilter(self)
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(22, 4, 22, 4)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(18)
        self._grid_parent = grid_host
        self._grid_layout = grid

        if rows > _MAX_VISIBLE_ROWS:
            scroll = QScrollArea(self._content_host)
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
            scroll.setWidget(grid_host)
            scroll.setFixedHeight(_MAX_VISIBLE_ROWS * row_height)
            self._content_layout.addWidget(scroll)
        else:
            grid_host.setFixedHeight(rows * row_height)
            self._content_layout.addWidget(grid_host)

        self._pending_render_members = list(self._members)
        self._pending_caption_width = caption_width
        self._render_index = 0
        self._render_next_batch()
        if self._render_index < len(self._pending_render_members):
            self._render_timer.start()

    def _render_next_batch(self) -> None:
        if self._grid_layout is None:
            self._render_timer.stop()
            return
        end = min(
            self._render_index + _RENDER_BATCH_SIZE,
            len(self._pending_render_members),
        )
        for index in range(self._render_index, end):
            member = self._pending_render_members[index]
            self._grid_layout.addWidget(
                self._make_member_cell(member, self._pending_caption_width),
                index // _GRID_COLUMNS,
                index % _GRID_COLUMNS,
            )
        self._render_index = end
        if self._render_index >= len(self._pending_render_members):
            self._render_timer.stop()

    def _make_member_cell(self, path: Path, caption_width: int) -> QWidget:
        parent = self._grid_parent or self._content_host
        cell = QWidget(parent)
        cell.setObjectName("inlineGroupItem")
        cell.setStyleSheet(
            "QWidget#inlineGroupItem { background: transparent; border: none; }"
            "QWidget#inlineGroupItem:hover {"
            "  background: rgba(255,255,255,0.10);"
            "  border: 1px solid rgba(255,255,255,0.18);"
            "  border-radius: 10px;"
            "}"
        )
        layout = QVBoxLayout(cell)
        layout.setContentsMargins(6, 6, 6, 8)
        layout.setSpacing(6)

        button = QToolButton(cell)
        button.setAutoRaise(True)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setIcon(self._visuals.icon_for(path))
        button.setIconSize(QSize(self._icon_size, self._icon_size))
        button.setFixedSize(
            self._icon_size + _ICON_PADDING,
            self._icon_size + _ICON_PADDING,
        )

        label = QLabel(path.name, cell)
        label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        label.setWordWrap(True)
        label.setMaximumWidth(caption_width)
        label.setMinimumWidth(caption_width)
        label.setMinimumHeight(36)
        label.setStyleSheet("color: #f8fafc; background: transparent;")

        layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(label, alignment=Qt.AlignmentFlag.AlignHCenter)

        resolved = path.resolve()
        for widget in (cell, button, label):
            widget.setAcceptDrops(True)
            widget.setProperty("_item_path", resolved)
            widget.installEventFilter(self)
        button.clicked.connect(lambda _checked=False, p=resolved: self.item_activated.emit(p))
        cell.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        cell.customContextMenuRequested.connect(
            lambda _pos, p=resolved, owner=cell: self._show_item_menu(p, owner)
        )
        return cell

    def _show_item_menu(self, path: Path, owner: QWidget) -> None:
        menu = QMenu(self)
        open_action = menu.addAction("打开")
        open_action.triggered.connect(lambda: self.item_activated.emit(path))
        menu.addSeparator()
        rename_action = menu.addAction("重命名分组")
        rename_action.triggered.connect(lambda: self.rename_requested.emit(self._group_id))
        dissolve_action = menu.addAction("解散分组")
        dissolve_action.triggered.connect(lambda: self.dissolve_requested.emit(self._group_id))
        menu.popup(owner.mapToGlobal(owner.rect().center()))

    def eventFilter(self, watched, event) -> bool:  # type: ignore[no-untyped-def]
        if event.type() in (
            event.Type.DragEnter,
            event.Type.DragMove,
            event.Type.Drop,
        ):
            mime = event.mimeData()
            if mime.hasFormat(ITEM_MIME_TYPE):
                if event.type() == event.Type.Drop:
                    paths = _paths_from_item_mime(bytes(mime.data(ITEM_MIME_TYPE)))
                    if paths:
                        self.members_dropped.emit(self._group_id, paths)
                event.acceptProposedAction()
                return True
        raw_path = watched.property("_item_path")
        if raw_path is None:
            return super().eventFilter(watched, event)
        if (
            event.type() == event.Type.MouseMove
            and event.buttons() & Qt.MouseButton.LeftButton
            and self._drag_host is not None
            and self._drag_source_path is not None
            and self._drag_start_pos is not None
        ):
            moved = (
                event.globalPosition().toPoint() - self._drag_start_pos
            ).manhattanLength()
            if moved >= QApplication.startDragDistance():
                source = self._drag_source_path
                ghost = watched if isinstance(watched, QWidget) else None
                self._drag_source_path = None
                self._drag_start_pos = None
                self._drag_host.begin_item_drag(source, ghost_widget=ghost)
                return True
        if event.type() in (
            event.Type.MouseButtonPress,
            event.Type.MouseButtonRelease,
        ) and event.button() == Qt.MouseButton.LeftButton:
            resolved = Path(str(raw_path)).resolve()
            if event.type() == event.Type.MouseButtonPress:
                self._drag_source_path = resolved
                self._drag_start_pos = event.globalPosition().toPoint()
            else:
                self._drag_source_path = None
                self._drag_start_pos = None
        return super().eventFilter(watched, event)
