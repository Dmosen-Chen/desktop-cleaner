"""Qt application bootstrap for the desktop panel preview."""

from __future__ import annotations

import os
import sys
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

from desktop_tidy.domain.classification import canonical_key, classify_path
from desktop_tidy.domain.models import AppearanceSettings, Configuration, PanelGeometry
from desktop_tidy.domain.workspace import WorkspaceModel
from desktop_tidy.persistence.config_store import ConfigurationStore
from desktop_tidy.services.desktop_index import (
    DesktopIndex,
    DesktopWatcher,
    IndexChanges,
    IndexedItem,
)
from desktop_tidy.services.item_launcher import open_item
from desktop_tidy.services.screens import available_screen_geometries, available_screen_options
from desktop_tidy.ui.panel_group import PanelGroupWidget
from desktop_tidy.ui.settings_window import SettingsWindow


PREVIEW_APPEARANCE_DEFAULTS = AppearanceSettings("#000000", 0.60)


def preview_store() -> ConfigurationStore:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "DesktopTidy"
    return ConfigurationStore(base / "preview-config.json")


def apply_preview_appearance_defaults(config: Configuration) -> None:
    config.appearance_defaults = deepcopy(PREVIEW_APPEARANCE_DEFAULTS)
    for group in config.panel_groups:
        group.appearance = deepcopy(PREVIEW_APPEARANCE_DEFAULTS)


def ensure_application(argv: list[str] | None = None) -> QApplication:
    application = QApplication.instance()
    if application is None:
        application = QApplication(argv if argv is not None else sys.argv)
    QApplication.setQuitOnLastWindowClosed(False)
    return application


def visible_entries_for_active_tab(
    config: Configuration,
    index: DesktopIndex,
    *,
    active_tab_id: str | None = None,
) -> list[IndexedItem]:
    tab_id = active_tab_id or config.panel_groups[0].active_tab_id
    desktop_entries = [
        entry
        for entry in index.scan()
        if classify_path(entry.path, config) == tab_id
    ]
    external_entries = [
        IndexedItem(Path(reference.canonical_path).resolve())
        for reference in config.external_refs
        if reference.target_tab_id == tab_id
    ]
    return desktop_entries + external_entries


class PreviewApplication:
    """Development-only preview that reads the desktop without takeover."""

    def __init__(
        self,
        config: Configuration | None = None,
        *,
        store: ConfigurationStore | None = None,
    ) -> None:
        if config is None:
            self.store = store or preview_store()
            is_new_preview = not self.store.path.is_file()
            self.model = WorkspaceModel(self.store.load())
        else:
            self.store = store or preview_store()
            self.model = WorkspaceModel(config)
            is_new_preview = store is not None and not self.store.path.is_file()
        if is_new_preview:
            apply_preview_appearance_defaults(self.model.config)
        self.config = self.model.config
        self.index = DesktopIndex(Path(self.config.desktop.path))
        self._panels: dict[str, PanelGroupWidget] = {}
        for group in self.config.panel_groups:
            self._ensure_panel_widget(group.id)
        self.panel = self._panels[self.config.panel_groups[0].id]
        self._settings_window: SettingsWindow | None = None
        self.watcher = DesktopWatcher(self.index)
        self.watcher.changed.connect(self._on_desktop_changed)
        self._sync_panel_snap_targets()
        application = QApplication.instance()
        if application is not None:
            application.aboutToQuit.connect(self._on_about_to_quit)

    def panel_widgets(self) -> list[PanelGroupWidget]:
        return list(self._panels.values())

    def detach_tab_to_new_group(self, tab_id: str, geometry: PanelGeometry) -> None:
        new_group = self.model.detach_tab(tab_id, geometry)
        panel = self._ensure_panel_widget(new_group.id)
        panel._apply_geometry_from_model()
        panel.show()
        self._sync_panel_geometries()
        self._sync_panel_snap_targets()
        self.save()
        self.refresh()

    def complete_group_merge_at_global_point(
        self,
        source_group_id: str,
        global_point: tuple[int, int],
    ) -> bool:
        bounds = self._panel_merge_bounds(exclude_group_id=source_group_id)
        merged = self.model.merge_group_at_point(
            source_group_id,
            point=global_point,
            bounds=bounds,
        )
        if not merged:
            return False
        removed = self._panels.pop(source_group_id, None)
        if removed is not None:
            removed.hide()
            removed.deleteLater()
        if removed is not None and (
            self.panel is removed or self.panel.group_id == source_group_id
        ):
            self.panel = next(iter(self._panels.values()))
        for panel in self._panels.values():
            panel.reload_from_model()
        self._sync_panel_geometries()
        self._sync_panel_snap_targets()
        self.save()
        self.refresh()
        return True

    def save(self) -> None:
        self.store.save(self.model.config)

    def _on_about_to_quit(self) -> None:
        for panel in self._panels.values():
            panel._persist_geometry_from_widget(update_rh=not panel.is_collapsed)
        self.save()

    def handle_paths_dropped(self, paths: list[Path], tab_id: str) -> None:
        self.model.add_paths_to_tab(paths, tab_id)
        self.save()
        self.refresh()

    def refresh(self, _changes: IndexChanges | None = None) -> None:
        for panel in self._panels.values():
            active_tab_id = panel.active_tab_id
            panel.item_grid.set_active_tab_id(active_tab_id)
            entries = visible_entries_for_active_tab(
                self.model.config,
                self.index,
                active_tab_id=active_tab_id,
            )
            panel.item_grid.set_entries(
                entries,
                restorable_paths=self._restorable_paths_for_tab(entries, active_tab_id),
            )

    def _ensure_panel_widget(self, group_id: str) -> PanelGroupWidget:
        existing = self._panels.get(group_id)
        if existing is not None:
            return existing
        group = self.model.group(group_id)
        panel = PanelGroupWidget(
            group,
            self.model.config.panel_tabs,
            workspace=self.model,
        )
        panel.set_screen_geometries(available_screen_geometries())
        self._connect_panel(panel)
        self._panels[group_id] = panel
        return panel

    def _connect_panel(self, panel: PanelGroupWidget) -> None:
        panel.changed.connect(self._on_panel_changed)
        panel.appearance_changed.connect(self._on_panel_appearance_changed)
        panel.geometry_changed.connect(self._on_panel_geometry_changed)
        panel.layout_gesture_started.connect(self._on_panel_layout_gesture_started)
        panel.settings_requested.connect(self._show_settings)
        panel.organize_requested.connect(self._on_organize_requested)
        panel.item_grid.paths_dropped.connect(self._on_paths_dropped)
        panel.item_grid.restore_auto_requested.connect(self._on_restore_auto_requested)
        panel.item_grid.item_activated.connect(self._on_item_activated)
        panel.tab_detach_requested.connect(self._on_tab_detach_requested)
        panel.group_merge_requested.connect(self._on_group_merge_requested)

    def _apply_panel_geometry(self, panel: PanelGroupWidget) -> None:
        panel._apply_geometry_from_model()

    def _sync_panel_geometries(self) -> None:
        for panel in self._panels.values():
            panel.reload_from_model()

    def _sync_panel_snap_targets(self) -> None:
        screen_geometries = available_screen_geometries()
        groups_by_id = {group.id: group for group in self.model.config.panel_groups}
        for group_id, panel in self._panels.items():
            panel.set_screen_geometries(screen_geometries)
            source_screen_id = groups_by_id[group_id].screen_id
            panel.set_snap_rects(
                [
                    other.frameGeometry()
                    for other_id, other in self._panels.items()
                    if other_id != group_id
                    and groups_by_id[other_id].screen_id == source_screen_id
                ]
            )

    def _panel_merge_bounds(
        self,
        *,
        exclude_group_id: str,
    ) -> dict[str, tuple[int, int, int, int]]:
        bounds: dict[str, tuple[int, int, int, int]] = {}
        for group_id, panel in self._panels.items():
            if group_id == exclude_group_id:
                continue
            top_left = panel.mapToGlobal(QPoint(0, 0))
            bounds[group_id] = (
                top_left.x(),
                top_left.y(),
                panel.width(),
                panel.height(),
            )
        return bounds

    def _on_panel_changed(self) -> None:
        self._sync_panel_widgets_with_model()
        self.save()
        self.refresh()

    def _on_panel_geometry_changed(self) -> None:
        self.save()

    def _on_panel_appearance_changed(self) -> None:
        self.save()

    def _on_panel_layout_gesture_started(self, group_id: str) -> None:
        panel = self._panels.get(group_id)
        if panel is None:
            return
        screen_geometries = available_screen_geometries()
        groups_by_id = {group.id: group for group in self.model.config.panel_groups}
        panel.set_screen_geometries(screen_geometries)
        source_screen_id = groups_by_id[group_id].screen_id
        panel.set_snap_rects(
            [
                other.frameGeometry()
                for other_id, other in self._panels.items()
                if other_id != group_id
                and groups_by_id[other_id].screen_id == source_screen_id
            ]
        )

    def _sync_panel_widgets_with_model(self) -> None:
        live_group_ids = {group.id for group in self.model.config.panel_groups}
        for group_id in list(self._panels.keys()):
            if group_id in live_group_ids:
                continue
            removed = self._panels.pop(group_id)
            removed.hide()
            removed.deleteLater()
        for group_id in live_group_ids:
            self._ensure_panel_widget(group_id)
        primary_id = self.model.config.panel_groups[0].id
        if (
            self.panel.group_id not in live_group_ids
            or self.panel.group_id not in self._panels
        ):
            self.panel = self._panels[primary_id]
        for panel in self._panels.values():
            panel.reload_from_model()
            panel.show()
        self._sync_panel_geometries()
        self._sync_panel_snap_targets()

    def _on_paths_dropped(self, paths: object, tab_id: str) -> None:
        self.handle_paths_dropped(list(paths), tab_id)

    def _restorable_paths_for_tab(
        self,
        entries: list[IndexedItem],
        active_tab_id: str,
    ) -> set[Path]:
        visible_by_key = {
            canonical_key(entry.path): entry.path.resolve() for entry in entries
        }
        external_keys = {
            canonical_key(Path(reference.canonical_path))
            for reference in self.model.config.external_refs
            if reference.target_tab_id == active_tab_id
        }
        restorable: set[Path] = set()
        for override in self.model.config.manual_overrides:
            if override.target_tab_id != active_tab_id:
                continue
            if override.canonical_path in external_keys:
                continue
            resolved = visible_by_key.get(override.canonical_path)
            if resolved is not None:
                restorable.add(resolved)
        return restorable

    def _on_restore_auto_requested(self, path: object) -> None:
        self.model.restore_auto_classification(Path(path))
        self.save()
        self.refresh()

    def _on_organize_requested(self, _group_id: str) -> None:
        self.model.organize_by_rules()
        self.save()
        self.refresh()

    def _on_item_activated(self, path: Path) -> None:
        try:
            open_item(path)
        except Exception:
            pass

    def _on_tab_detach_requested(self, tab_id: str, geometry: object) -> None:
        if not isinstance(geometry, PanelGeometry):
            return
        self.detach_tab_to_new_group(tab_id, geometry)

    def _on_group_merge_requested(self, group_id: str, global_x: int, global_y: int) -> None:
        self.complete_group_merge_at_global_point(group_id, (global_x, global_y))

    def _show_settings(self, group_id: str) -> None:
        if self._settings_window is None:
            self._settings_window = SettingsWindow(
                self.model.config,
                group_id=group_id,
                screen_options=available_screen_options(),
            )
            self._settings_window.config_saved.connect(self._on_settings_saved)
        else:
            self._settings_window.set_configuration(
                self.model.config,
                group_id=group_id,
            )
        self._settings_window.show()
        self._settings_window.raise_()
        self._settings_window.activateWindow()

    def _on_settings_saved(self) -> None:
        new_desktop = Path(self.model.config.desktop.path)
        if new_desktop.resolve() != self.index.desktop.resolve():
            try:
                self.watcher.changed.disconnect(self._on_desktop_changed)
            except RuntimeError:
                pass
            self.watcher.deleteLater()
            self.index = DesktopIndex(new_desktop)
            self.watcher = DesktopWatcher(self.index)
            self.watcher.changed.connect(self._on_desktop_changed)
        self.save()
        for panel in self._panels.values():
            panel.reload_from_model()
        self._sync_panel_snap_targets()
        self.refresh()

    def _on_desktop_changed(self, _changes: IndexChanges) -> None:
        if _changes.added:
            self.model.mark_desktop_items_pending_organize(
                [entry.path for entry in _changes.added]
            )
            self.save()
        self.refresh()

    def show(self) -> PanelGroupWidget:
        self.index.rescan()
        screen_geometries = available_screen_geometries()
        for panel in self._panels.values():
            panel.set_screen_geometries(screen_geometries)
            panel._apply_geometry_from_model()
            panel.show()
        self._sync_panel_snap_targets()
        self.refresh()
        return self.panel

    def run(self) -> int:
        ensure_application()
        self.show()
        application = QApplication.instance()
        assert application is not None
        return application.exec()
