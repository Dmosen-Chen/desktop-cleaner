"""Interactive preview widget for panel management."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QMouseEvent, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from desktop_tidy.domain.models import Configuration, PanelGeometry
from desktop_tidy.services.screens import ScreenInfo
from desktop_tidy.ui.panel_preview.model import PanelPreviewModel
from desktop_tidy.ui.panel_preview.renderer import (
    PanelPreviewRenderer,
    detail_tab_preview_rects,
    safe_screen_infos,
    screen_preview_rects,
    screen_z_order,
)


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

    def map_rect(self) -> QRect:
        return self._renderer().map_rect()

    def selected_panel_detail_rect(self) -> QRect:
        return self._renderer().selected_panel_detail_rect()

    def set_selected_screen(self, screen_id: str) -> None:
        valid_ids = {screen.screen_id for screen in self._screens}
        if screen_id in valid_ids:
            self._focused_screen_id = screen_id
            self.update()

    def _preview_model(self) -> PanelPreviewModel:
        return PanelPreviewModel(
            config=self._config,
            screens=self._screens,
            selected_group_id=self._selected_group_id,
            selected_tab_id=self._selected_tab_id,
            focused_screen_id=self._focused_screen_id,
            interaction_mode="drag-panel" if self._drag_group_id else "drag-tab" if self._drag_tab_id else "idle",
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
        visible_ids = list(
            detail_tab_preview_rects(
                self.selected_panel_detail_rect(),
                group.tab_ids,
                self._selected_tab_id,
                group.active_tab_id,
            )
        )
        return [tabs_by_id[tab_id].name for tab_id in visible_ids if tab_id in tabs_by_id]

    def overflow_label_for_group(self, group_id: str) -> str:
        group = next((entry for entry in self._config.panel_groups if entry.id == group_id), None)
        if group is None:
            return ""
        visible_count = len(
            detail_tab_preview_rects(
                self.selected_panel_detail_rect(),
                group.tab_ids,
                self._selected_tab_id,
                group.active_tab_id,
            )
        )
        hidden = len(group.tab_ids) - visible_count
        return f"+{hidden}" if hidden > 0 else ""

    def paintEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        painter = QPainter(self)
        self._renderer().paint(painter)
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        point = event.position().toPoint()
        group_id = self._hit_group(point)
        if group_id and group_id != self._selected_group_id:
            self._select_group_for_drag(group_id, point)
            event.accept()
            return
        tab_id = self._hit_tab(point)
        if tab_id:
            self._drag_tab_id = tab_id
            self._drag_start = point
            self._selected_tab_id = tab_id
            self.tab_selected.emit(tab_id)
            self.update()
            event.accept()
            return
        if group_id:
            self._select_group_for_drag(group_id, point)
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

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
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

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
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

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
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

    def _select_group_for_drag(self, group_id: str, point: QPoint) -> None:
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

    def _hit_tab(self, point: QPoint) -> str:
        for tab in reversed(self._config.panel_tabs):
            group = next((entry for entry in self._config.panel_groups if entry.id == tab.group_id), None)
            if group is None:
                continue
            if self.tab_rect(tab.id).contains(point):
                return tab.id
        return ""

    def _hit_group(self, point: QPoint) -> str:
        for group in reversed(self._config.panel_groups):
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
        rects = detail_tab_preview_rects(
            self.selected_panel_detail_rect(),
            group.tab_ids,
            self._selected_tab_id,
            group.active_tab_id,
        )
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
        screen_rect = self.screen_rect(group.screen_id or self._focused_screen_id)
        if screen_rect.isNull():
            return
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
