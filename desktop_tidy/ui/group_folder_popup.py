"""Expanded popup for a collapsed desktop item group (folder-style)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QPoint,
    QRect,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QGraphicsDropShadowEffect,
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

if TYPE_CHECKING:
    from desktop_tidy.ui.item_grid import ItemGridWidget

_ICON_PADDING = 8
_GRID_COLUMNS = 3
_SCROLL_ITEM_THRESHOLD = 9
_MAX_VISIBLE_ROWS = 3

_CARD_STYLE = (
    "QFrame#groupFolderCard {"
    "  background: qlineargradient("
    "    x1:0, y1:0, x2:0, y2:1,"
    "    stop:0 rgba(58, 50, 68, 0.97),"
    "    stop:1 rgba(38, 32, 48, 0.97)"
    "  );"
    "  border: 1px solid rgba(255, 255, 255, 0.32);"
    "  border-radius: 16px;"
    "}"
)
_MEMBER_HOVER_STYLE = (
    "QWidget#groupPopupItem {"
    "  background: rgba(255, 255, 255, 0.10);"
    "  border: 1px solid rgba(255, 255, 255, 0.18);"
    "  border-radius: 10px;"
    "}"
)
_MEMBER_IDLE_STYLE = (
    "QWidget#groupPopupItem { background: transparent; border: none; }"
)


def _header_style_for_accent(accent_color: str) -> str:
    color = QColor(accent_color)
    if not color.isValid():
        color = QColor(DEFAULT_GROUP_ACCENT_COLOR)
    return (
        "QWidget#groupFolderHeader {"
        f"  background: rgba({color.red()}, {color.green()}, {color.blue()}, 0.42);"
        "  border-top-left-radius: 15px;"
        "  border-top-right-radius: 15px;"
        "  border-bottom: 1px solid rgba(255, 255, 255, 0.14);"
        "}"
    )


class GroupFolderPopup(QWidget):
    """点击文件夹后在上方弹出的成员网格。"""

    item_activated = Signal(Path)
    rename_requested = Signal(str)
    dissolve_requested = Signal(str)

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
        self._group_id = group_id
        self._members = [path.resolve() for path in members]
        self._icon_size = icon_size
        self._accent_color = accent_color.upper()
        self._visuals = visuals or ItemVisualProvider()
        self._final_rect = QRect()
        self._full_card_height = 0
        self._header: QWidget | None = None
        self._drag_host: ItemGridWidget | None = None
        self._drag_source_path: Path | None = None
        self._drag_start_pos: QPoint | None = None
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setObjectName("groupFolderPopupRoot")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 10)
        outer.setSpacing(0)

        self._card = QFrame(self)
        self._card.setObjectName("groupFolderCard")
        self._card.setStyleSheet(_CARD_STYLE)
        shadow = QGraphicsDropShadowEffect(self._card)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 0, 0, 180))
        self._card.setGraphicsEffect(shadow)

        card_layout = QVBoxLayout(self._card)
        self._card_layout = card_layout
        card_layout.setContentsMargins(0, 0, 0, 14)
        card_layout.setSpacing(10)

        self._header = QWidget(self._card)
        self._header.setObjectName("groupFolderHeader")
        self._header.setStyleSheet(_header_style_for_accent(self._accent_color))
        header_layout = QHBoxLayout(self._header)
        header_layout.setContentsMargins(14, 10, 14, 10)
        header_layout.setSpacing(8)

        self._title_label = QLabel(name or "未命名分组", self._header)
        self._title_label.setStyleSheet(
            "color: #ffffff; font-weight: 600; font-size: 14px; background: transparent;"
        )
        self._count_label = QLabel(f"{len(self._members)} 项", self._header)
        self._count_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._count_label.setStyleSheet(
            "color: rgba(255,255,255,0.72); font-size: 12px; background: transparent;"
        )
        header_layout.addWidget(self._title_label, stretch=1)
        header_layout.addWidget(self._count_label)
        card_layout.addWidget(self._header)

        self._content_host = QWidget(self._card)
        self._content_host.setObjectName("groupFolderContent")
        self._rebuild_member_grid()
        card_layout.addWidget(self._content_host)

        self._apply_card_width()
        outer.addWidget(self._card)
        self.adjustSize()
        self._full_card_height = self._card.sizeHint().height()

    def group_id(self) -> str:
        return self._group_id

    def set_drag_host(self, host: ItemGridWidget) -> None:
        self._drag_host = host

    def set_accent_color(self, accent_color: str) -> None:
        self._accent_color = accent_color.upper()
        if self._header is not None:
            self._header.setStyleSheet(_header_style_for_accent(self._accent_color))

    def _replace_content_layout(self) -> QVBoxLayout:
        old_host = self._content_host
        self._content_host = QWidget(self._card)
        self._content_host.setObjectName("groupFolderContent")
        if self._card_layout.indexOf(old_host) >= 0:
            self._card_layout.replaceWidget(old_host, self._content_host)
        old_host.setParent(None)
        old_host.deleteLater()
        layout = QVBoxLayout(self._content_host)
        layout.setContentsMargins(0, 0, 0, 0)
        return layout

    def _grid_columns(self, *, host_width: int | None = None) -> int:
        if len(self._members) <= 1:
            return 1
        max_columns = min(_GRID_COLUMNS, len(self._members))
        if host_width is None:
            return max_columns
        caption_width = max(80, min(96, self._icon_size + 36))
        for columns in range(max_columns, 0, -1):
            card_width = columns * (caption_width + 24) + 52
            if card_width <= max(host_width - 16, caption_width + 76):
                return columns
        return 1

    def _apply_card_width(self, *, host_width: int | None = None) -> None:
        columns = self._grid_columns(host_width=host_width)
        caption_width = max(80, min(96, self._icon_size + 36))
        natural = columns * (caption_width + 24) + 52
        if host_width is not None:
            natural = min(natural, max(160, host_width - 16))
        self._card.setFixedWidth(max(160, natural))

    def _rebuild_member_grid(self, *, host_width: int | None = None) -> None:
        layout = self._replace_content_layout()
        columns = self._grid_columns(host_width=host_width)
        caption_width = max(80, min(96, self._icon_size + 36))
        row_height = self._icon_size + _ICON_PADDING + 52
        rows = max(1, (len(self._members) + columns - 1) // columns)

        grid_host = QWidget(self._content_host)
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(12, 4, 12, 4)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(14)
        for index, member in enumerate(self._members):
            cell = self._make_member_cell(member, caption_width)
            grid.addWidget(cell, index // columns, index % columns)

        layout.setContentsMargins(0, 0, 0, 0)
        if len(self._members) > _SCROLL_ITEM_THRESHOLD:
            scroll = QScrollArea(self._content_host)
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
            scroll.setWidget(grid_host)
            scroll.setFixedHeight(_MAX_VISIBLE_ROWS * row_height)
            layout.addWidget(scroll)
        else:
            content_height = rows * row_height
            grid_host.setFixedHeight(content_height)
            layout.addWidget(grid_host)
        self._content_host.setMinimumHeight(
            _MAX_VISIBLE_ROWS * row_height
            if len(self._members) > _SCROLL_ITEM_THRESHOLD
            else rows * row_height
        )

    def show_above(self, anchor_widget: QWidget) -> None:
        self.show_expanded_from(anchor_widget)

    def update_group(
        self,
        *,
        group_id: str,
        name: str,
        members: list[Path],
        icon_size: int,
        accent_color: str,
        host_width: int | None = None,
    ) -> None:
        self._group_id = group_id
        self._members = [path.resolve() for path in members]
        self._icon_size = icon_size
        self._title_label.setText(name or "未命名分组")
        self._count_label.setText(f"{len(self._members)} 项")
        self.set_accent_color(accent_color)
        self._reset_presented_state()
        self.setUpdatesEnabled(False)
        try:
            self._rebuild_member_grid(host_width=host_width)
            self._apply_card_width(host_width=host_width)
            self.adjustSize()
            self._full_card_height = self._card.sizeHint().height()
        finally:
            self.setUpdatesEnabled(True)

    def _reset_presented_state(self) -> None:
        self._card.setMaximumHeight(16777215)
        self.setMaximumHeight(16777215)
        self.setWindowOpacity(1.0)

    def _fit_height_to_host(self, position_host: QWidget) -> QSize:
        self.adjustSize()
        popup_size = self.size()
        host_height = position_host.rect().height()
        if host_height <= 0:
            return popup_size
        maximum_height = max(80, host_height - 16)
        if popup_size.height() <= maximum_height:
            return popup_size
        self.setMaximumHeight(maximum_height)
        self._card.setMaximumHeight(max(56, maximum_height - 18))
        popup_size.setHeight(maximum_height)
        self.resize(popup_size)
        return popup_size

    def reposition_from(
        self,
        anchor_widget: QWidget,
        position_host: QWidget,
        *,
        host_width: int | None = None,
    ) -> None:
        width = host_width if host_width is not None else position_host.rect().width()
        if width > 0:
            self._apply_card_width(host_width=width)
        self._reset_presented_state()
        self._fit_height_to_host(position_host)
        self._full_card_height = self._card.sizeHint().height()
        end_rect = self._compute_popup_rect(anchor_widget, position_host)
        self._final_rect = end_rect
        self.setGeometry(end_rect)
        self.raise_()

    def show_expanded_from(
        self,
        anchor_widget: QWidget,
        *,
        preview_widget: QWidget | None = None,
        position_host: QWidget | None = None,
        animate: bool = True,
        relayout: bool = True,
    ) -> None:
        del preview_widget, animate
        host = position_host or anchor_widget
        host_width = host.rect().width()
        self._reset_presented_state()
        if relayout and host_width > 0:
            self._rebuild_member_grid(host_width=host_width)
            self._apply_card_width(host_width=host_width)
            self._fit_height_to_host(host)
            self._full_card_height = self._card.sizeHint().height()
        end_rect = self._compute_popup_rect(anchor_widget, host)
        self._final_rect = end_rect
        self.setGeometry(end_rect)
        self.show()
        self.raise_()

    def _compute_popup_rect(self, anchor_widget: QWidget, position_host: QWidget) -> QRect:
        host_rect = position_host.rect()
        host_width = host_rect.width()
        if host_width > 0:
            self._apply_card_width(host_width=host_width)
        popup_size = self._fit_height_to_host(position_host)
        anchor_local = anchor_widget.mapTo(position_host, QPoint(0, 0))
        anchor_w = anchor_widget.width()
        anchor_h = anchor_widget.height()
        popup_w = popup_size.width()
        popup_h = popup_size.height()
        margin = 8
        gap = 10

        def fits(x: int, y: int) -> bool:
            return (
                margin <= x
                and margin <= y
                and x + popup_w <= host_rect.width() - margin
                and y + popup_h <= host_rect.height() - margin
            )

        centered_x = anchor_local.x() + (anchor_w - popup_w) // 2
        candidates = [
            (centered_x, anchor_local.y() - popup_h - gap),
            (centered_x, anchor_local.y() + anchor_h + gap),
            (anchor_local.x() + anchor_w + gap, anchor_local.y()),
            (anchor_local.x() - popup_w - gap, anchor_local.y()),
            (centered_x, margin),
            (margin, anchor_local.y()),
        ]
        for x, y in candidates:
            if fits(x, y):
                return QRect(QPoint(x, y), popup_size)

        x = max(margin, min(centered_x, host_rect.width() - popup_w - margin))
        y = anchor_local.y() - popup_h - gap
        if y < margin:
            y = anchor_local.y() + anchor_h + gap
        y = max(margin, min(y, host_rect.height() - popup_h - margin))
        return QRect(QPoint(x, y), popup_size)

    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.button() == Qt.MouseButton.LeftButton:
            card_local = self._card.mapFrom(self, event.position().toPoint())
            if not self._card.rect().contains(card_local):
                if self._drag_host is not None:
                    self._drag_host._close_group_folder()
                event.accept()
                return
        super().mousePressEvent(event)

    def eventFilter(self, watched, event) -> bool:  # type: ignore[no-untyped-def]
        raw_path = watched.property("_item_path")
        if raw_path is None or self._drag_host is None:
            return super().eventFilter(watched, event)
        if (
            event.type() == event.Type.MouseMove
            and event.buttons() & Qt.MouseButton.LeftButton
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

    def _make_member_cell(self, path: Path, caption_width: int) -> QWidget:
        cell = QWidget(self._card)
        cell.setObjectName("groupPopupItem")
        cell.setStyleSheet(_MEMBER_IDLE_STYLE)
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
        button.setStyleSheet("QToolButton { background: transparent; border: none; }")
        button.setCursor(Qt.CursorShape.PointingHandCursor)

        label = QLabel(path.name, cell)
        label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        label.setWordWrap(True)
        label.setMinimumWidth(caption_width)
        label.setMaximumWidth(caption_width)
        label.setMinimumHeight(36)
        label.setStyleSheet("color: #f5f5f5; background: transparent;")

        layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(label, alignment=Qt.AlignmentFlag.AlignHCenter)

        resolved = path.resolve()
        cell.setProperty("_item_path", resolved)
        button.setProperty("_item_path", resolved)
        label.setProperty("_item_path", resolved)
        cell.installEventFilter(self)
        button.installEventFilter(self)
        label.installEventFilter(self)

        button.clicked.connect(lambda _checked=False, p=path: self.item_activated.emit(p))
        cell.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        cell.customContextMenuRequested.connect(
            lambda _pos, p=path: self._show_item_menu(p, cell)
        )
        cell.enterEvent = lambda _event, c=cell: c.setStyleSheet(_MEMBER_HOVER_STYLE)  # type: ignore[method-assign,assignment]
        cell.leaveEvent = lambda _event, c=cell: c.setStyleSheet(_MEMBER_IDLE_STYLE)  # type: ignore[method-assign,assignment]
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

    def keyPressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)
