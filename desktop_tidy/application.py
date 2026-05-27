"""Qt application bootstrap for the desktop panel."""

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
from desktop_tidy.persistence.layout_history import LayoutHistoryStore
from desktop_tidy.services.desktop_index import (
    DesktopIndex,
    DesktopWatcher,
    IndexChanges,
    IndexedItem,
)
from desktop_tidy.services.desktop_takeover import (
    DesktopRecoveryGuard,
    DesktopTakeoverService,
)
from desktop_tidy.services.activation import ActivationServer
from desktop_tidy.services.item_launcher import open_item
from desktop_tidy.services.logging_setup import (
    configure_logging,
    install_global_exception_hook,
    log_exception,
)
from desktop_tidy.services.screens import available_screen_geometries, available_screen_options
from desktop_tidy.services.startup import StartupService
from desktop_tidy.ui.panel_group import PanelGroupWidget
from desktop_tidy.ui.settings_window import SettingsWindow
from desktop_tidy.ui.tray import TrayController


APP_DIR_NAME = "DesktopCleaner"
APP_CONFIG_NAME = "config.json"
APP_APPEARANCE_DEFAULTS = AppearanceSettings("#000000", 0.60)


def application_store() -> ConfigurationStore:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / APP_DIR_NAME
    return ConfigurationStore(base / APP_CONFIG_NAME)


def application_history_store() -> LayoutHistoryStore:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / APP_DIR_NAME
    return LayoutHistoryStore(base / "layout-history.json")


def apply_application_appearance_defaults(config: Configuration) -> None:
    config.appearance_defaults = deepcopy(APP_APPEARANCE_DEFAULTS)
    for group in config.panel_groups:
        group.appearance = deepcopy(APP_APPEARANCE_DEFAULTS)


def ensure_application(argv: list[str] | None = None) -> QApplication:
    application = QApplication.instance()
    if application is None:
        application = QApplication(argv if argv is not None else sys.argv)
        install_global_exception_hook()
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


class DesktopCleanerApplication:
    """Qt desktop panel application that reads the desktop without takeover."""

    def __init__(
        self,
        config: Configuration | None = None,
        *,
        store: ConfigurationStore | None = None,
        takeover_service: DesktopTakeoverService | None = None,
        startup_service: StartupService | None = None,
        tray_controller: TrayController | None = None,
        activation_server: ActivationServer | None = None,
        history_store: LayoutHistoryStore | None = None,
    ) -> None:
        should_configure_logging = config is None or store is not None
        if config is None:
            self.store = store or application_store()
            is_new_config = not self.store.path.is_file()
            self.model = WorkspaceModel(self.store.load())
        else:
            self.store = store or application_store()
            self.model = WorkspaceModel(config)
            is_new_config = store is not None and not self.store.path.is_file()
        if is_new_config:
            apply_application_appearance_defaults(self.model.config)
        self.config = self.model.config
        self.takeover_service = takeover_service or DesktopTakeoverService()
        self.startup_service = startup_service or StartupService()
        self.tray = tray_controller or TrayController()
        self.activation_server = activation_server or ActivationServer()
        if should_configure_logging:
            configure_logging(self.store.path.parent)
        self.history_store = history_store or LayoutHistoryStore(
            self.store.path.with_name("layout-history.json")
        )
        self._takeover_active = False
        self._shutdown_started = False
        if DesktopRecoveryGuard(self.takeover_service).recover_if_needed(self.config):
            self.save()
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
        self._connect_tray()
        self.activation_server.activated.connect(self._show_panels_from_tray)

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

    def save_with_history(self, reason: str) -> None:
        try:
            self.history_store.push(self.model.config, reason)
        except Exception as exc:
            log_exception(f"record layout history: {reason}", exc)
        self.save()

    def _on_about_to_quit(self) -> None:
        if self._shutdown_started:
            return
        self._shutdown_started = True
        for panel in self._panels.values():
            panel._persist_geometry_from_widget(update_rh=not panel.is_collapsed)
        self._restore_desktop_takeover_if_needed()
        self.save_with_history("merge-group")

    def _connect_tray(self) -> None:
        self.tray.show_panels_requested.connect(self._show_panels_from_tray)
        self.tray.hide_panels_requested.connect(self._hide_panels_from_tray)
        self.tray.settings_requested.connect(self._show_settings_from_tray)
        self.tray.restore_desktop_requested.connect(self._restore_desktop_from_tray)
        self.tray.quit_requested.connect(self._quit_from_tray)
        self.tray.show()

    def _show_panels_from_tray(self) -> None:
        for panel in self._panels.values():
            panel.show()
        self._sync_panel_snap_targets()
        self.refresh()

    def _hide_panels_from_tray(self) -> None:
        for panel in self._panels.values():
            panel.hide()

    def _show_settings_from_tray(self) -> None:
        self._show_settings(self.panel.group_id)

    def _restore_desktop_from_tray(self) -> None:
        self._restore_desktop_takeover_if_needed()
        self.save()
        self._notify_user("桌面图标恢复", "已尝试恢复 Explorer 桌面图标。")

    def _notify_user(self, title: str, message: str) -> None:
        notifier = getattr(self.tray, "show_message", None)
        if notifier is None:
            return
        try:
            notifier(title, message)
        except Exception as exc:
            log_exception("show tray notification", exc)

    def _quit_from_tray(self) -> None:
        self._on_about_to_quit()
        application = QApplication.instance()
        if application is not None:
            application.quit()

    def handle_paths_dropped(self, paths: list[Path], tab_id: str) -> None:
        self.model.add_paths_to_tab(paths, tab_id)
        self.save_with_history("item-reference-change")
        self.refresh()

    def refresh(self, _changes: IndexChanges | None = None) -> None:
        for panel in self._panels.values():
            active_tab_id = panel.active_tab_id
            panel.item_grid.set_active_tab_id(active_tab_id)
            tab = self.model.tab(active_tab_id)
            if tab.content_kind != "items":
                continue
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
        self.save_with_history("panel-change")
        self.refresh()

    def _on_panel_geometry_changed(self) -> None:
        self.save_with_history("geometry-change")

    def _on_panel_appearance_changed(self) -> None:
        self.save_with_history("appearance-change")

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
        except Exception as exc:
            log_exception(f"open item {path}", exc)

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
            self._settings_window.restore_desktop_requested.connect(
                self._restore_desktop_from_settings
            )
            self._settings_window.add_widget_panel_requested.connect(
                self._on_add_widget_panel_requested
            )
            self._settings_window.add_widget_tab_requested.connect(
                self._on_add_widget_tab_requested
            )
            self._settings_window.history_restore_requested.connect(
                self._on_history_restore_requested
            )
        else:
            self._settings_window.set_configuration(
                self.model.config,
                group_id=group_id,
            )
        self._settings_window.set_history_snapshots(self.history_store.load())
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
        self._apply_startup_preference()
        self._apply_desktop_takeover_preference()
        self.save_with_history("settings-save")
        for panel in self._panels.values():
            panel.reload_from_model()
        self._sync_panel_snap_targets()
        self.refresh()

    def _restore_desktop_from_settings(self) -> None:
        self._restore_desktop_from_tray()

    def _on_add_widget_panel_requested(self, widget_type: str) -> None:
        group = self.model.add_widget_panel(widget_type)
        panel = self._ensure_panel_widget(group.id)
        panel._apply_geometry_from_model()
        panel.show()
        self._sync_panel_geometries()
        self._sync_panel_snap_targets()
        self.save_with_history(f"add-widget-panel:{widget_type}")
        self.refresh()

    def _on_add_widget_tab_requested(self, widget_type: str) -> None:
        group_id = self._settings_window._group_id if self._settings_window is not None else self.panel.group_id
        tab = self.model.add_widget_tab(group_id, widget_type)
        panel = self._ensure_panel_widget(group_id)
        panel.reload_from_model()
        panel.activate_tab(tab.id)
        self._sync_panel_snap_targets()
        self.save_with_history(f"add-widget-tab:{widget_type}")
        self.refresh()

    def _on_history_restore_requested(self, snapshot_id: str) -> None:
        restored = self.history_store.restore(snapshot_id)
        self._replace_configuration(restored)
        self.save()
        self.refresh()

    def _replace_configuration(self, config: Configuration) -> None:
        self.model = WorkspaceModel(config)
        self.config = self.model.config
        try:
            self.watcher.changed.disconnect(self._on_desktop_changed)
        except RuntimeError:
            pass
        self.watcher.deleteLater()
        for panel in self._panels.values():
            panel.hide()
            panel.deleteLater()
        self._panels.clear()
        self.index = DesktopIndex(Path(self.config.desktop.path))
        self.watcher = DesktopWatcher(self.index)
        self.watcher.changed.connect(self._on_desktop_changed)
        for group in self.config.panel_groups:
            self._ensure_panel_widget(group.id)
        self.panel = self._panels[self.config.panel_groups[0].id]
        self._sync_panel_geometries()
        self._sync_panel_snap_targets()
        for panel in self._panels.values():
            panel.show()

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
        self._apply_desktop_takeover_preference()
        return self.panel

    def run(self) -> int:
        ensure_application()
        self.show()
        application = QApplication.instance()
        assert application is not None
        return application.exec()

    def _panel_native_handles(self) -> list[int]:
        return [int(panel.winId()) for panel in self._panels.values()]

    def _startup_executable_path(self) -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve()
        return Path(sys.argv[0]).resolve()

    def _apply_startup_preference(self) -> None:
        enabled = self.startup_service.set_enabled(
            self.model.config.desktop.startup_enabled,
            self._startup_executable_path(),
        )
        if not enabled and self.model.config.desktop.startup_enabled:
            self.model.config.desktop.startup_enabled = False

    def _apply_desktop_takeover_preference(self) -> None:
        if not self.model.config.desktop.takeover_enabled:
            self._restore_desktop_takeover_if_needed()
            return
        if self._takeover_active:
            return
        result = self.takeover_service.attach_panels(self._panel_native_handles())
        if not result.success:
            log_exception("desktop takeover attach failed", RuntimeError(str(result.message)))
            self._disable_desktop_takeover_after_failure(restore=False)
            self._notify_user("桌面接管失败", "无法进入桌面层，已保持普通窗口模式。")
            return
        self.model.config.desktop.restore_required = True
        self.model.config.desktop.explorer_icons_hidden = False
        self.save()
        if not self.takeover_service.hide_explorer_icons():
            log_exception(
                "desktop takeover hide icons failed",
                RuntimeError("hide_explorer_icons returned false"),
            )
            self._disable_desktop_takeover_after_failure(restore=True)
            self._notify_user("桌面接管失败", "隐藏 Explorer 桌面图标失败，已自动恢复。")
            return
        self._takeover_active = True
        self.model.config.desktop.explorer_icons_hidden = True
        self.save()

    def _disable_desktop_takeover_after_failure(self, *, restore: bool) -> None:
        if restore:
            restored = self.takeover_service.restore_explorer_icons()
        else:
            restored = True
        self.takeover_service.detach_panels()
        self._takeover_active = False
        self.model.config.desktop.takeover_enabled = False
        if restored:
            self.model.config.desktop.restore_required = False
            self.model.config.desktop.explorer_icons_hidden = False
        else:
            self.model.config.desktop.restore_required = True
        self.save()

    def _restore_desktop_takeover_if_needed(self) -> None:
        if not (
            self._takeover_active
            or self.model.config.desktop.restore_required
            or self.model.config.desktop.explorer_icons_hidden
        ):
            return
        restored = self.takeover_service.restore_explorer_icons()
        self.takeover_service.detach_panels()
        self._takeover_active = False
        if restored:
            self.model.config.desktop.restore_required = False
            self.model.config.desktop.explorer_icons_hidden = False
        else:
            self.model.config.desktop.restore_required = True
