"""Shared translucent panel previews used by settings pages."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from desktop_tidy.domain.models import Configuration, PanelGeometry
from desktop_tidy.services.screens import ScreenInfo


@dataclass(frozen=True)
class PanelPreviewModel:
    """Small render-only view model for settings preview surfaces."""

    config: Configuration
    screens: list[ScreenInfo]
    selected_group_id: str = ""
    selected_tab_id: str = ""
    focused_screen_id: str = ""


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
    return [ScreenInfo("primary", "主屏", QRect(0, 0, 1920, 1080))]


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


def _fit_rect_for_aspect(bounds: QRect, source: QRect) -> QRect:
    aspect = source.width() / max(1, source.height())
    width = bounds.width()
    height = int(width / aspect)
    if height > bounds.height():
        height = bounds.height()
        width = int(height * aspect)
    return QRect(
        bounds.x() + (bounds.width() - width) // 2,
        bounds.y() + (bounds.height() - height) // 2,
        max(80, width),
        max(54, height),
    )


def screen_preview_rects(
    screens: list[ScreenInfo],
    bounds: QRect,
    focused_screen_id: str = "",
) -> dict[str, QRect]:
    valid = safe_screen_infos(screens)
    by_id = {screen.screen_id: screen for screen in valid}
    focused = screen_z_order(valid, focused_screen_id)[-1]
    main_bounds = bounds.adjusted(18, 18, -18, -18)
    main_bounds.setWidth(max(90, int(main_bounds.width() * 0.78)))
    main_bounds.setHeight(max(64, int(main_bounds.height() * 0.74)))
    main_bounds.moveCenter(bounds.center())
    rects: dict[str, QRect] = {}
    focused_rect = _fit_rect_for_aspect(main_bounds, by_id[focused].geometry)
    rects[focused] = focused_rect
    offsets = [
        QPoint(-focused_rect.width() // 2, -focused_rect.height() // 3),
        QPoint(focused_rect.width() // 2, focused_rect.height() // 3),
        QPoint(-focused_rect.width() // 5, focused_rect.height() // 4),
    ]
    others = [screen_id for screen_id in by_id if screen_id != focused]
    for index, screen_id in enumerate(others):
        screen = by_id[screen_id]
        back_size = QSize(
            max(88, int(focused_rect.width() * 0.56)),
            max(58, int(focused_rect.height() * 0.56)),
        )
        back_bounds = QRect(QPoint(0, 0), back_size)
        back_bounds.moveCenter(focused_rect.center() + offsets[index % len(offsets)])
        rects[screen_id] = _fit_rect_for_aspect(back_bounds, screen.geometry)
    return rects


def group_preview_rect(group, screen_rect: QRect) -> QRect:  # type: ignore[no-untyped-def]
    inner = screen_rect.adjusted(10, 10, -10, -10)
    geometry = group.geometry
    width = max(150, int(inner.width() * geometry.rw))
    height = max(96, int(inner.height() * geometry.rh))
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


def tab_preview_rects(group_rect: QRect, tab_ids: list[str]) -> dict[str, QRect]:
    if not tab_ids:
        return {}
    visible_ids = tab_ids[:3]
    gap = 4
    tab_height = min(24, max(18, group_rect.height() // 5))
    usable_width = max(1, group_rect.width() - 16 - gap * (len(visible_ids) - 1))
    tab_width = max(36, min(86, usable_width // max(1, len(visible_ids))))
    rects: dict[str, QRect] = {}
    x = group_rect.x() + 8
    y = group_rect.y() + 32
    for tab_id in visible_ids:
        if x + tab_width > group_rect.right() - 8:
            break
        rects[tab_id] = QRect(x, y, tab_width, tab_height)
        x += tab_width + gap
    return rects


class PanelPreviewRenderer:
    """Paints the same translucent panel language across settings surfaces."""

    def __init__(self, model: PanelPreviewModel, size: QSize) -> None:
        self.model = model
        self.size = size

    def screen_rects(self) -> dict[str, QRect]:
        return screen_preview_rects(
            self.model.screens,
            QRect(QPoint(0, 0), self.size),
            self.model.focused_screen_id,
        )

    def group_rect(self, group_id: str) -> QRect:
        group = next(
            (entry for entry in self.model.config.panel_groups if entry.id == group_id),
            None,
        )
        if group is None:
            return QRect()
        rects = self.screen_rects()
        screen_rect = rects.get(group.screen_id or self.model.focused_screen_id)
        if screen_rect is None:
            screen_rect = next(iter(rects.values()), QRect())
        return group_preview_rect(group, screen_rect)

    def tab_rect(self, tab_id: str) -> QRect:
        tab = next(
            (entry for entry in self.model.config.panel_tabs if entry.id == tab_id),
            None,
        )
        if tab is None:
            return QRect()
        group = next(
            (entry for entry in self.model.config.panel_groups if entry.id == tab.group_id),
            None,
        )
        if group is None:
            return QRect()
        return tab_preview_rects(self.group_rect(group.id), group.tab_ids).get(
            tab_id,
            QRect(),
        )

    def render(self) -> QPixmap:
        pixmap = QPixmap(self.size)
        pixmap.fill(QColor("#191919"))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self._paint_screens(painter)
        self._paint_groups(painter)
        painter.end()
        return pixmap

    def _paint_screens(self, painter: QPainter) -> None:
        screen_rects = self.screen_rects()
        safe_screens = {screen.screen_id: screen for screen in safe_screen_infos(self.model.screens)}
        order = screen_z_order(list(safe_screens.values()), self.model.focused_screen_id)
        for screen_id in order:
            screen = safe_screens[screen_id]
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
        tabs_by_id = {tab.id: tab for tab in self.model.config.panel_tabs}
        safe_screens = safe_screen_infos(self.model.screens)
        ordered_screen_ids = screen_z_order(safe_screens, self.model.focused_screen_id)
        font_metrics = QFontMetrics(painter.font())
        for index, group in enumerate(self.model.config.panel_groups):
            if group.screen_id not in ordered_screen_ids:
                continue
            if group.screen_id != ordered_screen_ids[-1]:
                continue
            rect = self.group_rect(group.id)
            base = QColor(group.appearance.background_color or "#4B5563")
            base.setAlphaF(max(0.20, min(0.88, group.appearance.background_opacity)))
            painter.setBrush(base)
            painter.setPen(QPen(QColor("#f0b7d5" if group.id == self.model.selected_group_id else "#9a9a9a"), 2))
            painter.drawRoundedRect(rect, 10, 10)

            painter.setPen(QColor("#ffffff"))
            title = group.name or f"面板 {index + 1}"
            title = font_metrics.elidedText(title, Qt.TextElideMode.ElideRight, max(10, rect.width() - 20))
            painter.drawText(
                QRect(rect.x() + 10, rect.y() + 8, max(10, rect.width() - 20), 20),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                title,
            )
            for tab_id, tab_rect in tab_preview_rects(rect, group.tab_ids).items():
                tab = tabs_by_id.get(tab_id)
                if tab is None:
                    continue
                checked = tab_id == self.model.selected_tab_id or (
                    not self.model.selected_tab_id and tab_id == group.active_tab_id
                )
                painter.setBrush(QColor("#d99abd" if checked else "#3a3a3a"))
                painter.setPen(QPen(QColor("#ffffff" if checked else "#666666"), 1))
                painter.drawRoundedRect(tab_rect, 5, 5)
                painter.setPen(QColor("#111111" if checked else "#ffffff"))
                label = font_metrics.elidedText(
                    tab.name,
                    Qt.TextElideMode.ElideRight,
                    max(10, tab_rect.width() - 8),
                )
                painter.drawText(tab_rect.adjusted(4, 0, -4, 0), Qt.AlignmentFlag.AlignCenter, label)
            overflow = len(group.tab_ids) - len(tab_preview_rects(rect, group.tab_ids))
            if overflow > 0:
                painter.setPen(QColor("#ffffff"))
                painter.drawText(
                    rect.adjusted(8, 32, -8, -8),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
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
        ),
        size,
    ).render()


class PanelPreviewWidget(QWidget):
    group_selected = Signal(str)
    tab_selected = Signal(str)
    tab_reordered = Signal(str, str, int, bool)
    screen_selected = Signal(str)
    group_rename_requested = Signal(str)
    tab_rename_requested = Signal(str)
    group_geometry_changed = Signal(str, object, bool)

    def __init__(
        self,
        config: Configuration,
        screens: list[ScreenInfo],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._screens = safe_screen_infos(screens)
        self._selected_group_id = config.panel_groups[0].id if config.panel_groups else ""
        self._selected_tab_id = ""
        self._focused_screen_id = config.desktop.primary_screen_id or "primary"
        self._drag_group_id = ""
        self._drag_tab_id = ""
        self._drag_start = QPoint()
        self._drag_start_geometry = PanelGeometry()
        self._tab_drag_started = False
        self.setMinimumHeight(260)
        self.setMouseTracking(True)

    def set_state(
        self,
        config: Configuration,
        screens: list[ScreenInfo],
        selected_group_id: str,
        selected_tab_id: str = "",
    ) -> None:
        self._config = config
        self._screens = safe_screen_infos(screens)
        self._selected_group_id = selected_group_id
        self._selected_tab_id = selected_tab_id
        group = next((entry for entry in config.panel_groups if entry.id == selected_group_id), None)
        if group is not None and group.screen_id:
            self._focused_screen_id = group.screen_id
        self.update()

    def focused_screen_id(self) -> str:
        return self._focused_screen_id

    def screen_z_order(self) -> list[str]:
        return screen_z_order(self._screens, self._focused_screen_id)

    def screen_rect(self, screen_id: str) -> QRect:
        return screen_preview_rects(self._screens, self.rect(), self._focused_screen_id).get(screen_id, QRect())

    def set_selected_screen(self, screen_id: str) -> None:
        valid_ids = {screen.screen_id for screen in self._screens}
        if screen_id in valid_ids:
            self._focused_screen_id = screen_id
            self.update()

    def _preview_model(self) -> PanelPreviewModel:
        return PanelPreviewModel(
            self._config,
            self._screens,
            self._selected_group_id,
            self._selected_tab_id,
            self._focused_screen_id,
        )

    def _renderer(self) -> PanelPreviewRenderer:
        return PanelPreviewRenderer(self._preview_model(), self.size())

    def group_rect(self, group_id: str) -> QRect:
        return self._renderer().group_rect(group_id)

    def tab_rect(self, tab_id: str) -> QRect:
        return self._renderer().tab_rect(tab_id)

    def visible_tab_labels(self, group_id: str) -> list[str]:
        group = next((entry for entry in self._config.panel_groups if entry.id == group_id), None)
        if group is None:
            return []
        tabs_by_id = {tab.id: tab for tab in self._config.panel_tabs}
        visible_ids = list(tab_preview_rects(self.group_rect(group_id), group.tab_ids))
        return [tabs_by_id[tab_id].name for tab_id in visible_ids if tab_id in tabs_by_id]

    def overflow_label_for_group(self, group_id: str) -> str:
        group = next((entry for entry in self._config.panel_groups if entry.id == group_id), None)
        if group is None:
            return ""
        visible_count = len(tab_preview_rects(self.group_rect(group_id), group.tab_ids))
        hidden = len(group.tab_ids) - visible_count
        return f"+{hidden}" if hidden > 0 else ""

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self._renderer().render())
        painter.end()

    def mousePressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        point = event.position().toPoint()
        tab_id = self._hit_tab(point)
        if tab_id:
            self._drag_tab_id = tab_id
            self._drag_start = point
            self._selected_tab_id = tab_id
            self.tab_selected.emit(tab_id)
            self.update()
            return
        group_id = self._hit_group(point)
        if group_id:
            self._selected_group_id = group_id
            self.group_selected.emit(group_id)
            self._drag_group_id = group_id
            self._drag_start = point
            group = next(entry for entry in self._config.panel_groups if entry.id == group_id)
            self._drag_start_geometry = PanelGeometry(
                group.geometry.rx,
                group.geometry.ry,
                group.geometry.rw,
                group.geometry.rh,
            )
            self.group_geometry_changed.emit(group.id, group.geometry, False)
            self.update()
            event.accept()
            return
        screen_id = self._hit_screen(point)
        if screen_id:
            self._focused_screen_id = screen_id
            self.screen_selected.emit(screen_id)
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        point = event.position().toPoint()
        if self._drag_tab_id:
            self._update_tab_drag(point, final=False)
            event.accept()
            return
        if self._drag_group_id:
            self._update_group_drag(point, final=False)
            event.accept()
            return
        screen_id = self._hit_screen(point)
        if screen_id and screen_id != self._focused_screen_id:
            self._focused_screen_id = screen_id
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mouseReleaseEvent(event)
        point = event.position().toPoint()
        if self._drag_tab_id:
            self._update_tab_drag(point, final=True)
            self._drag_tab_id = ""
            self._tab_drag_started = False
            event.accept()
            return
        if self._drag_group_id:
            self._update_group_drag(point, final=True)
            self._drag_group_id = ""
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        point = event.position().toPoint()
        tab_id = self._hit_tab(point)
        if tab_id:
            self.tab_rename_requested.emit(tab_id)
            event.accept()
            return
        group_id = self._hit_group(point)
        if group_id:
            self.group_rename_requested.emit(group_id)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _hit_tab(self, point: QPoint) -> str:
        for tab in reversed(self._config.panel_tabs):
            group = next((entry for entry in self._config.panel_groups if entry.id == tab.group_id), None)
            if group is None:
                continue
            if group.screen_id != self._focused_screen_id:
                continue
            if self.tab_rect(tab.id).contains(point):
                return tab.id
        return ""

    def _hit_group(self, point: QPoint) -> str:
        for group in reversed(self._config.panel_groups):
            if group.screen_id != self._focused_screen_id:
                continue
            if self.group_rect(group.id).contains(point):
                return group.id
        return ""

    def _hit_screen(self, point: QPoint) -> str:
        rects = screen_preview_rects(self._screens, self.rect(), self._focused_screen_id)
        for screen_id in reversed(self.screen_z_order()):
            if rects.get(screen_id, QRect()).contains(point):
                return screen_id
        return ""

    def _target_tab_index(self, group_id: str, point: QPoint) -> int:
        group = next((entry for entry in self._config.panel_groups if entry.id == group_id), None)
        if group is None:
            return -1
        rects = tab_preview_rects(self.group_rect(group_id), group.tab_ids)
        if not rects:
            return -1
        dragged_rect = rects.get(self._drag_tab_id)
        if dragged_rect is not None and dragged_rect.adjusted(-4, -4, 4, 4).contains(point):
            return group.tab_ids.index(self._drag_tab_id)
        final_order = [tab_id for tab_id in group.tab_ids if tab_id != self._drag_tab_id]
        for tab_id in final_order:
            rect = rects.get(tab_id)
            if rect is None:
                continue
            if point.x() < rect.center().x():
                return final_order.index(tab_id)
        return min(len(group.tab_ids) - 1, len(final_order))

    def _update_tab_drag(self, point: QPoint, *, final: bool) -> None:
        tab = next((entry for entry in self._config.panel_tabs if entry.id == self._drag_tab_id), None)
        if tab is None:
            return
        if (point - self._drag_start).manhattanLength() >= QApplication.startDragDistance():
            self._tab_drag_started = True
        if not self._tab_drag_started and not final:
            return
        target_index = self._target_tab_index(tab.group_id, point)
        if target_index < 0:
            return
        self.tab_reordered.emit(tab.group_id, tab.id, target_index, final)
        self.update()

    def _update_group_drag(self, point: QPoint, *, final: bool) -> None:
        group = next((entry for entry in self._config.panel_groups if entry.id == self._drag_group_id), None)
        if group is None:
            return
        rects = screen_preview_rects(self._screens, self.rect(), self._focused_screen_id)
        screen_rect = rects.get(group.screen_id or self._focused_screen_id) or next(iter(rects.values()))
        delta = point - self._drag_start
        rx = self._drag_start_geometry.rx + (delta.x() / max(1, screen_rect.width()))
        ry = self._drag_start_geometry.ry + (delta.y() / max(1, screen_rect.height()))
        geometry = PanelGeometry(
            max(0.0, min(1.0 - self._drag_start_geometry.rw, rx)),
            max(0.0, min(1.0 - self._drag_start_geometry.rh, ry)),
            self._drag_start_geometry.rw,
            self._drag_start_geometry.rh,
        )
        group.geometry = geometry
        self.group_geometry_changed.emit(group.id, geometry, final)
        self.update()
