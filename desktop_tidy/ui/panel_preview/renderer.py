"""Paint shared real-desktop panel layout previews."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen, QPixmap

from desktop_tidy.domain.models import Configuration, PanelGroup
from desktop_tidy.services.screens import ScreenInfo
from desktop_tidy.ui.panel_preview.model import PanelPreviewModel

_OUTER_MARGIN = 12
_PREVIEW_GAP = 10
_DETAIL_MIN_HEIGHT = 96
_DETAIL_MAX_HEIGHT = 138


def safe_screen_infos(screens: list[ScreenInfo]) -> list[ScreenInfo]:
    valid = [
        screen
        for screen in screens
        if screen.geometry.isValid()
        and screen.geometry.width() > 0
        and screen.geometry.height() > 0
    ]
    if valid:
        return valid
    return [ScreenInfo("primary", "primary", QRect(0, 0, 1920, 1080))]


def screen_z_order(screens: list[ScreenInfo], focused_screen_id: str = "") -> list[str]:
    valid = safe_screen_infos(screens)
    ids = [screen.screen_id for screen in valid]
    focused = focused_screen_id if focused_screen_id in ids else ""
    if not focused:
        focused = "primary" if "primary" in ids else ids[0]
    return [screen_id for screen_id in ids if screen_id != focused] + [focused]


def layout_preview_tab_names(config: Configuration) -> list[str]:
    tabs_by_id = {tab.id: tab for tab in config.panel_tabs}
    names: list[str] = []
    for group in config.panel_groups:
        for tab_id in group.tab_ids:
            tab = tabs_by_id.get(tab_id)
            if tab is not None:
                names.append(tab.name)
    return names


def _desktop_union(screens: list[ScreenInfo]) -> QRect:
    geometries = [screen.geometry for screen in safe_screen_infos(screens)]
    left = min(rect.left() for rect in geometries)
    top = min(rect.top() for rect in geometries)
    right = max(rect.right() for rect in geometries)
    bottom = max(rect.bottom() for rect in geometries)
    return QRect(QPoint(left, top), QPoint(right, bottom))


def screen_preview_rects(
    screens: list[ScreenInfo],
    bounds: QRect,
    focused_screen_id: str = "",
    *,
    show_detail: bool = True,
) -> dict[str, QRect]:
    valid = safe_screen_infos(screens)
    desktop = _desktop_union(valid)
    inner = map_preview_rect(bounds, show_detail=show_detail).adjusted(12, 12, -12, -12)
    if inner.width() <= 0 or inner.height() <= 0:
        return {}
    scale = min(
        inner.width() / max(1, desktop.width()),
        inner.height() / max(1, desktop.height()),
    )
    used_width = int(round(desktop.width() * scale))
    used_height = int(round(desktop.height() * scale))
    origin_x = inner.x() + (inner.width() - used_width) // 2
    origin_y = inner.y() + (inner.height() - used_height) // 2
    rects: dict[str, QRect] = {}
    for screen in valid:
        geometry = screen.geometry
        rects[screen.screen_id] = QRect(
            origin_x + int(round((geometry.x() - desktop.x()) * scale)),
            origin_y + int(round((geometry.y() - desktop.y()) * scale)),
            max(36, int(round(geometry.width() * scale))),
            max(28, int(round(geometry.height() * scale))),
        )
    return rects


def map_preview_rect(bounds: QRect, *, show_detail: bool = True) -> QRect:
    inner = bounds.adjusted(_OUTER_MARGIN, _OUTER_MARGIN, -_OUTER_MARGIN, -_OUTER_MARGIN)
    if not show_detail or inner.height() < 180:
        return inner
    detail_height = min(_DETAIL_MAX_HEIGHT, max(_DETAIL_MIN_HEIGHT, int(inner.height() * 0.34)))
    return QRect(inner.x(), inner.y(), inner.width(), max(60, inner.height() - detail_height - _PREVIEW_GAP))


def selected_panel_detail_rect(bounds: QRect) -> QRect:
    inner = bounds.adjusted(_OUTER_MARGIN, _OUTER_MARGIN, -_OUTER_MARGIN, -_OUTER_MARGIN)
    if inner.height() < 180:
        return QRect()
    top = map_preview_rect(bounds).bottom() + 1 + _PREVIEW_GAP
    return QRect(inner.x(), top, inner.width(), max(0, inner.bottom() - top + 1))


def group_preview_rect(group: PanelGroup, screen_rect: QRect) -> QRect:
    inner = screen_rect.adjusted(10, 10, -10, -10)
    geometry = group.geometry
    width = max(42, int(inner.width() * geometry.rw))
    height = max(34, int(inner.height() * geometry.rh))
    width = min(width, inner.width())
    height = min(height, inner.height())
    x = inner.x() + int(inner.width() * geometry.rx)
    y = inner.y() + int(inner.height() * geometry.ry)
    return QRect(
        max(inner.x(), min(x, inner.right() - width + 1)),
        max(inner.y(), min(y, inner.bottom() - height + 1)),
        width,
        height,
    )


def _summary_tab_ids(group: PanelGroup, selected_tab_id: str = "") -> list[str]:
    if not group.tab_ids:
        return []
    first = selected_tab_id if selected_tab_id in group.tab_ids else group.active_tab_id
    if first not in group.tab_ids:
        first = group.tab_ids[0]
    ordered = [first] + [tab_id for tab_id in group.tab_ids if tab_id != first]
    return ordered[:3]


def _summary_tab_ids_from_values(
    tab_ids: list[str],
    selected_tab_id: str = "",
    active_tab_id: str = "",
) -> list[str]:
    if not tab_ids:
        return []
    first = selected_tab_id if selected_tab_id in tab_ids else active_tab_id
    if first not in tab_ids:
        first = tab_ids[0]
    ordered = [first] + [tab_id for tab_id in tab_ids if tab_id != first]
    return ordered[:3]


def tab_preview_rects(
    group_rect: QRect,
    tab_ids: list[str],
    selected_tab_id: str = "",
    active_tab_id: str = "",
) -> dict[str, QRect]:
    if not tab_ids:
        return {}
    visible_ids = _summary_tab_ids_from_values(tab_ids, selected_tab_id, active_tab_id)
    gap = 4
    tab_height = min(20, max(14, group_rect.height() // 5))
    max_tabs_width = max(1, min(group_rect.width() - 16, 172))
    usable_width = max(1, max_tabs_width - gap * (len(visible_ids) - 1))
    tab_width = max(28, min(58, usable_width // max(1, len(visible_ids))))
    rects: dict[str, QRect] = {}
    x = group_rect.x() + 8
    y = group_rect.y() + min(30, max(20, group_rect.height() // 4))
    for tab_id in visible_ids:
        if x + tab_width > group_rect.right() - 8:
            break
        rects[tab_id] = QRect(x, y, tab_width, tab_height)
        x += tab_width + gap
    return rects


def detail_tab_preview_rects(
    detail_rect: QRect,
    tab_ids: list[str],
    selected_tab_id: str = "",
    active_tab_id: str = "",
) -> dict[str, QRect]:
    if detail_rect.isNull() or not tab_ids:
        return {}
    visible_ids = _summary_tab_ids_from_values(tab_ids, selected_tab_id, active_tab_id)
    gap = 8
    tab_height = 24
    max_tabs_width = max(1, detail_rect.width() - 30)
    usable_width = max(1, max_tabs_width - gap * (len(visible_ids) - 1))
    tab_width = max(58, min(104, usable_width // max(1, len(visible_ids))))
    rects: dict[str, QRect] = {}
    x = detail_rect.x() + 14
    y = detail_rect.y() + 50
    for tab_id in visible_ids:
        if x + tab_width > detail_rect.right() - 14:
            break
        rects[tab_id] = QRect(x, y, tab_width, tab_height)
        x += tab_width + gap
    return rects


class PanelPreviewRenderer:
    """Paints desktop screens and translucent panels using one visual language."""

    def __init__(self, model: PanelPreviewModel, size: QSize) -> None:
        self.model = model
        self.size = size

    def screen_rects(self) -> dict[str, QRect]:
        return screen_preview_rects(
            self.model.screens,
            QRect(QPoint(0, 0), self.size),
            self.model.focused_screen_id,
            show_detail=self.model.show_detail,
        )

    def group_rect(self, group_id: str) -> QRect:
        group = next((entry for entry in self.model.groups if entry.id == group_id), None)
        if group is None:
            return QRect()
        rects = self.screen_rects()
        screen_rect = rects.get(group.screen_id or self.model.focused_screen_id)
        if screen_rect is None:
            screen_rect = next(iter(rects.values()), QRect())
        return group_preview_rect(group, screen_rect)

    def tab_rect(self, tab_id: str) -> QRect:
        tab = next((entry for entry in self.model.tabs if entry.id == tab_id), None)
        if tab is None:
            return QRect()
        group = next((entry for entry in self.model.groups if entry.id == tab.group_id), None)
        if group is None:
            return QRect()
        return detail_tab_preview_rects(
            self.selected_panel_detail_rect(),
            group.tab_ids,
            self.model.selected_tab_id,
            group.active_tab_id,
        ).get(tab_id, QRect())

    def map_rect(self) -> QRect:
        return map_preview_rect(QRect(QPoint(0, 0), self.size), show_detail=self.model.show_detail)

    def selected_panel_detail_rect(self) -> QRect:
        if not self.model.show_detail:
            return QRect()
        return selected_panel_detail_rect(QRect(QPoint(0, 0), self.size))

    def selected_group(self) -> PanelGroup | None:
        if self.model.selected_group_id:
            group = next((entry for entry in self.model.groups if entry.id == self.model.selected_group_id), None)
            if group is not None:
                return group
        return self.model.groups[0] if self.model.groups else None

    def render(self) -> QPixmap:
        pixmap = QPixmap(self.size)
        pixmap.fill(QColor("#191919"))
        painter = QPainter(pixmap)
        self.paint(painter)
        painter.end()
        return pixmap

    def paint(self, painter: QPainter) -> None:
        painter.fillRect(QRect(QPoint(0, 0), self.size), QColor("#191919"))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._paint_screens(painter)
        self._paint_groups(painter)
        if self.model.show_detail:
            self._paint_selected_group_detail(painter)

    def _paint_screens(self, painter: QPainter) -> None:
        screen_rects = self.screen_rects()
        screens = {screen.screen_id: screen for screen in safe_screen_infos(self.model.screens)}
        order = screen_z_order(list(screens.values()), self.model.focused_screen_id)
        for screen_id in order:
            screen = screens[screen_id]
            rect = screen_rects.get(screen_id)
            if rect is None:
                continue
            active = screen_id == order[-1]
            painter.setPen(QPen(QColor("#7c7c7c" if active else "#414141"), 1))
            painter.setBrush(QColor("#151515" if active else "#101010"))
            painter.drawRoundedRect(rect, 12, 12)
            painter.setPen(QColor("#d7d7d7" if active else "#8a8a8a"))
            painter.drawText(
                rect.adjusted(10, 8, -10, -8),
                Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
                screen.label,
            )

    def _paint_groups(self, painter: QPainter) -> None:
        group_order = list(self.model.groups)
        group_order.sort(key=lambda entry: entry.id == self.model.selected_group_id)
        screens = {screen.screen_id: screen for screen in safe_screen_infos(self.model.screens)}
        for index, group in enumerate(group_order):
            rect = self.group_rect(group.id)
            if rect.isNull():
                continue
            base = QColor(group.appearance.background_color or "#4B5563")
            base.setAlphaF(max(0.20, min(0.88, group.appearance.background_opacity)))
            painter.setBrush(base)
            selected = group.id == self.model.selected_group_id
            painter.setPen(QPen(QColor("#f0b7d5" if selected else "#9a9a9a"), 2 if selected else 1))
            painter.drawRoundedRect(rect, 10, 10)
            painter.setPen(QColor("#ffffff"))
            screen_label = screens.get(group.screen_id)
            label = str(index + 1) if screen_label is None else str(index + 1)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label)

    def _paint_selected_group_detail(self, painter: QPainter) -> None:
        detail_rect = self.selected_panel_detail_rect()
        group = self.selected_group()
        if detail_rect.isNull() or group is None:
            return
        tabs_by_id = {tab.id: tab for tab in self.model.tabs}
        base = QColor(group.appearance.background_color or "#4B5563")
        base.setAlphaF(max(0.20, min(0.88, group.appearance.background_opacity)))
        painter.setBrush(base)
        painter.setPen(QPen(QColor("#f0b7d5"), 1))
        painter.drawRoundedRect(detail_rect, 10, 10)

        font = painter.font()
        title_font = QFontMetrics(font)
        painter.setPen(QColor("#ffffff"))
        title = title_font.elidedText(group.name or "Panel", Qt.TextElideMode.ElideRight, detail_rect.width() - 28)
        painter.drawText(
            QRect(detail_rect.x() + 14, detail_rect.y() + 10, detail_rect.width() - 28, 24),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            title,
        )
        current = tabs_by_id.get(group.active_tab_id)
        if current is not None:
            painter.setPen(QColor("#d8d8d8"))
            painter.drawText(
                QRect(detail_rect.x() + 14, detail_rect.y() + 30, detail_rect.width() - 28, 18),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                f"当前：{current.name}",
            )
        rects = detail_tab_preview_rects(
            detail_rect,
            group.tab_ids,
            self.model.selected_tab_id,
            group.active_tab_id,
        )
        metrics = QFontMetrics(painter.font())
        for tab_id, tab_rect in rects.items():
            tab = tabs_by_id.get(tab_id)
            if tab is None:
                continue
            checked = tab_id == self.model.selected_tab_id or (
                not self.model.selected_tab_id and tab_id == group.active_tab_id
            )
            painter.setBrush(QColor("#d99abd" if checked else "#3a3a3a"))
            painter.setPen(QPen(QColor("#ffffff" if checked else "#666666"), 1))
            painter.drawRoundedRect(tab_rect, 6, 6)
            painter.setPen(QColor("#111111" if checked else "#ffffff"))
            label = metrics.elidedText(tab.name, Qt.TextElideMode.ElideRight, max(10, tab_rect.width() - 10))
            painter.drawText(tab_rect.adjusted(5, 0, -5, 0), Qt.AlignmentFlag.AlignCenter, label)
        overflow = len(group.tab_ids) - len(rects)
        if overflow > 0:
            painter.setPen(QColor("#ffffff"))
            painter.drawText(
                QRect(detail_rect.right() - 60, detail_rect.y() + 52, 46, 24),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                f"+{overflow}",
            )


def render_layout_preview_pixmap(
    config: Configuration,
    screens: list[ScreenInfo],
    size: QSize,
    *,
    selected_group_id: str = "",
    selected_tab_id: str = "",
    focused_screen_id: str = "",
) -> QPixmap:
    return PanelPreviewRenderer(
        PanelPreviewModel(
            config=config,
            screens=safe_screen_infos(screens),
            selected_group_id=selected_group_id,
            selected_tab_id=selected_tab_id,
            focused_screen_id=focused_screen_id,
            show_detail=True,
        ),
        size,
    ).render()
