"""Qt application bootstrap for the desktop panel."""

from __future__ import annotations

import os
import subprocess
import sys
import atexit
import weakref
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import isValid

from desktop_tidy.domain.classification import canonical_key, classify_path
from desktop_tidy.domain.shortcut_identity import desktop_entry_rank, item_identity_key
from desktop_tidy.domain.models import AppearanceSettings, Configuration, PanelGeometry
from desktop_tidy.domain.workspace import WorkspaceModel
from desktop_tidy.persistence.config_store import ConfigurationStore
from desktop_tidy.persistence.layout_history import LayoutHistoryStore
from desktop_tidy.persistence.ui_preferences import UiPreferencesStore
from desktop_tidy.services.desktop_index import (
    DesktopIndex,
    DesktopWatcher,
    IndexChanges,
    IndexedItem,
)
from desktop_tidy.services.desktop_location import windows_public_desktop
from desktop_tidy.services.desktop_takeover import (
    DesktopRecoveryGuard,
    DesktopTakeoverService,
    TakeoverSessionMarker,
    install_abnormal_exit_handler,
    recover_abandoned_takeover,
)
from desktop_tidy.services.diagnostics import DiagnosticsService, RecoveryResult
from desktop_tidy.services.activation import ActivationServer
from desktop_tidy.services.item_launcher import open_item
from desktop_tidy.services.logging_setup import (
    configure_logging,
    get_logger,
    install_global_exception_hook,
    log_exception,
)
from desktop_tidy.services.screens import available_screen_geometries, available_screens
from desktop_tidy.services.startup import StartupService
from desktop_tidy.services.updates import DownloadResult, UpdateInfo, UpdateService
from desktop_tidy.ui.app_icons import apply_application_icon
from desktop_tidy.ui.item_grid import GroupBlock, ItemGridWidget
from desktop_tidy.ui.panel_group import PanelGroupWidget
from desktop_tidy.ui.settings_window import SettingsWindow
from desktop_tidy.ui.tray import TrayController
from desktop_tidy.version import APP_VERSION


APP_DIR_NAME = "DesktopCleaner"
APP_CONFIG_NAME = "config.json"
APP_APPEARANCE_DEFAULTS = AppearanceSettings("#000000", 0.60)


def resolve_startup_executable_path(
    *,
    frozen: bool | None = None,
    executable: Path | None = None,
    project_root: Path | None = None,
) -> Path | None:
    """Return the executable that should be registered for Windows startup.

    In packaged mode the running executable is correct. In development mode,
    registering ``main.py`` causes Windows to open the source file at login, so
    only the built release executable is acceptable.
    """

    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    current_executable = executable or Path(sys.executable)
    if is_frozen:
        return current_executable.resolve()
    root = project_root or Path(__file__).resolve().parents[1]
    candidate = root / "dist" / "DesktopCleaner.exe"
    if candidate.is_file():
        return candidate.resolve()
    return None


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
    apply_application_icon(application)
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
    primary_desktop = Path(config.desktop.path)
    candidates: list[IndexedItem] = []
    seen_paths: set[str] = set()
    for entry in desktop_entries + external_entries:
        key = canonical_key(entry.path)
        if key in seen_paths:
            continue
        seen_paths.add(key)
        candidates.append(entry)

    chosen_by_identity: dict[str, IndexedItem] = {}
    for entry in candidates:
        identity = item_identity_key(entry.path)
        existing = chosen_by_identity.get(identity)
        if existing is None:
            chosen_by_identity[identity] = entry
            continue
        if desktop_entry_rank(entry.path, primary_desktop=primary_desktop) < desktop_entry_rank(
            existing.path, primary_desktop=primary_desktop
        ):
            chosen_by_identity[identity] = entry

    merged: list[IndexedItem] = []
    emitted_identities: set[str] = set()
    for entry in candidates:
        identity = item_identity_key(entry.path)
        if identity in emitted_identities:
            continue
        if chosen_by_identity[identity] is not entry:
            continue
        merged.append(entry)
        emitted_identities.add(identity)
    return merged


def arrange_entries_for_tab(
    config: Configuration,
    entries: list[IndexedItem],
    tab_id: str,
) -> list[IndexedItem]:
    """应用标签内的手动顺序与新项落位策略,纯显示层重排,不触碰真实文件。"""
    key_to_entry = {canonical_key(entry.path): entry for entry in entries}
    groups_for_tab = [
        group for group in config.item_groups if group.tab_id == tab_id and group.member_paths
    ]
    anchor_to_group = {group.member_paths[0]: group for group in groups_for_tab}
    grouped_member_keys = {
        member_key
        for group in groups_for_tab
        for member_key in group.member_paths
    }

    def normalize_order_keys(keys: list[str]) -> list[str]:
        normalized: list[str] = []
        seen_anchors: set[str] = set()
        for key in keys:
            if key in anchor_to_group:
                if key in seen_anchors:
                    continue
                seen_anchors.add(key)
                normalized.append(key)
            elif key in grouped_member_keys:
                continue
            else:
                normalized.append(key)
        return normalized

    def expand_order_key(key: str) -> list[str]:
        if key in anchor_to_group:
            return [
                member_key
                for member_key in anchor_to_group[key].member_paths
                if member_key in key_to_entry
            ]
        if key in key_to_entry:
            return [key]
        return []

    order = normalize_order_keys(config.manual_orders.get(tab_id, []))
    if not order:
        return entries

    ordered_entries: list[IndexedItem] = []
    ordered_set: set[str] = set()
    for key in order:
        for member_key in expand_order_key(key):
            if member_key in ordered_set:
                continue
            ordered_entries.append(key_to_entry[member_key])
            ordered_set.add(member_key)

    new_entries = [
        entry
        for entry in entries
        if canonical_key(entry.path) not in ordered_set
    ]
    if not new_entries:
        return ordered_entries
    placement = config.new_item_placement
    if placement == "resort_all":
        return entries
    if placement == "prepend_front":
        return new_entries + ordered_entries
    return ordered_entries + new_entries


def group_blocks_for_tab(
    config: Configuration,
    entries: list[IndexedItem],
    tab_id: str,
) -> list[GroupBlock]:
    """构建某标签的分组渲染区块,成员过滤为当前可见项,按组 order 排序。"""
    key_to_entry = {canonical_key(entry.path): entry for entry in entries}
    groups = sorted(
        (group for group in config.item_groups if group.tab_id == tab_id),
        key=lambda group: group.order,
    )
    blocks: list[GroupBlock] = []
    for group in groups:
        members = [
            key_to_entry[key].path.resolve()
            for key in group.member_paths
            if key in key_to_entry
        ]
        if members:
            blocks.append(GroupBlock(group_id=group.id, name=group.name, members=members))
    return blocks


def _restore_takeover_on_process_exit(takeover_service: DesktopTakeoverService) -> None:
    """进程异常退出时尽量恢复 Explorer 桌面图标。"""
    try:
        takeover_service.restore_explorer_icons()
        takeover_service.detach_panels()
    except Exception:
        pass


_active_desktop_apps: weakref.WeakSet[DesktopCleanerApplication] = weakref.WeakSet()
_focus_hook_installed = False
_mouse_filter: _GlobalMouseFilter | None = None


class _GlobalMouseFilter(QObject):
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.MouseButtonPress and isinstance(watched, QWidget):
            for app in list(_active_desktop_apps):
                if not _app_can_manage_group_folders(app):
                    _active_desktop_apps.discard(app)
                    continue
                app._on_global_mouse_press(watched)
        return False


def _dispatch_application_focus_changed(
    old: QWidget | None, new: QWidget | None
) -> None:
    for app in list(_active_desktop_apps):
        if not _app_can_manage_group_folders(app):
            _active_desktop_apps.discard(app)
            continue
        app._on_application_focus_changed(old, new)


def _app_can_manage_group_folders(app: DesktopCleanerApplication) -> bool:
    if app._shutdown_started or not app._panels:
        return False
    try:
        panel = next(iter(app._panels.values()))
    except StopIteration:
        return False
    return isValid(panel)


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
        update_service: UpdateService | None = None,
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
        existing_home = self.model.home_tab()
        existing_home_group = self.model.group(existing_home.group_id) if existing_home else None
        existing_home_active = existing_home_group.active_tab_id if existing_home_group else ""
        existing_home_first = (
            bool(existing_home_group and existing_home_group.tab_ids)
            and existing_home_group.tab_ids[0] == existing_home.id
        )
        self._home_tab = self.model.ensure_home_tab()
        self._home_startup_dirty = (
            existing_home is None
            or existing_home_active != self._home_tab.id
            or not existing_home_first
        )
        self.config = self.model.config
        self.takeover_service = takeover_service or DesktopTakeoverService()
        self._takeover_marker = TakeoverSessionMarker(
            self.store.path.parent / "takeover-session.marker"
        )
        atexit.register(_restore_takeover_on_process_exit, self.takeover_service)
        install_abnormal_exit_handler(
            lambda: self._emergency_restore_desktop_takeover()
        )
        self.startup_service = startup_service or StartupService()
        self.tray = tray_controller or TrayController()
        self.activation_server = activation_server or ActivationServer()
        if should_configure_logging:
            configure_logging(self.store.path.parent)
        self.history_store = history_store or LayoutHistoryStore(
            self.store.path.with_name("layout-history.json")
        )
        self.ui_preferences_store = UiPreferencesStore(
            self.store.path.with_name("ui-preferences.json")
        )
        self.ui_preferences = self.ui_preferences_store.load()
        self._takeover_active = False
        self._shutdown_started = False
        self._closing_group_from_focus = False
        self._deferred_save_pending = False
        self._deferred_save_timer = QTimer()
        self._deferred_save_timer.setSingleShot(True)
        self._deferred_save_timer.setInterval(450)
        self._deferred_save_timer.timeout.connect(self._flush_deferred_save)
        if recover_abandoned_takeover(self.takeover_service, self._takeover_marker):
            self.model.config.desktop.restore_required = False
            self.model.config.desktop.explorer_icons_hidden = False
            self.save()
        elif DesktopRecoveryGuard(self.takeover_service).recover_if_needed(self.config):
            self.save()
        self.index = self._make_desktop_index(self.config.desktop.path)
        self._panels: dict[str, PanelGroupWidget] = {}
        for group in self.config.panel_groups:
            self._ensure_panel_widget(group.id)
        self.panel = self._panels.get(self._home_tab.group_id) or self._panels[self.config.panel_groups[0].id]
        self._last_layout_history_fingerprint = self.history_store.fingerprint(
            self.model.config
        )
        self.diagnostics_service = self._create_diagnostics_service()
        self.update_service = update_service or UpdateService(
            updates_dir=self.store.path.parent / "updates"
        )
        self._latest_update_info: UpdateInfo | None = None
        self._downloaded_update: DownloadResult | None = None
        self._update_status_message = "点击检查更新。"
        self._settings_window: SettingsWindow | None = None
        self.watcher = DesktopWatcher(self.index)
        self.watcher.changed.connect(self._on_desktop_changed)
        self._sync_panel_snap_targets()
        _active_desktop_apps.add(self)
        application = QApplication.instance()
        global _focus_hook_installed, _mouse_filter
        if application is not None:
            application.aboutToQuit.connect(self._on_about_to_quit)
            if not _focus_hook_installed:
                application.focusChanged.connect(_dispatch_application_focus_changed)
                _focus_hook_installed = True
            if _mouse_filter is None:
                _mouse_filter = _GlobalMouseFilter(application)
                application.installEventFilter(_mouse_filter)
        self._connect_tray()
        self.activation_server.activated.connect(self._show_panels_from_tray)

    def panel_widgets(self) -> list[PanelGroupWidget]:
        return list(self._panels.values())

    def _make_desktop_index(self, desktop_path: str | Path) -> DesktopIndex:
        primary = Path(desktop_path)
        extras: list[Path] = []
        try:
            public = windows_public_desktop()
        except Exception:
            public = None
        if public is not None and public.resolve() != primary.resolve():
            extras.append(public)
        return DesktopIndex(primary, extra_desktops=extras)

    def detach_tab_to_new_group(self, tab_id: str, geometry: PanelGeometry) -> None:
        new_group = self.model.detach_tab(tab_id, geometry)
        panel = self._ensure_panel_widget(new_group.id)
        panel._apply_geometry_from_model()
        panel.show()
        self._sync_panel_geometries()
        self._sync_panel_snap_targets()
        self.save_with_history("detach-tab")
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
        self.save_with_history("merge-group")
        self.refresh()
        return True

    def save(self) -> None:
        if hasattr(self, "_deferred_save_timer") and self._deferred_save_timer.isActive():
            self._deferred_save_timer.stop()
        self._deferred_save_pending = False
        self.store.save(self.model.config)

    def _schedule_deferred_save(self, delay_ms: int = 450) -> None:
        if self._shutdown_started:
            return
        self._deferred_save_pending = True
        self._deferred_save_timer.start(max(0, delay_ms))

    def _flush_deferred_save(self) -> None:
        if hasattr(self, "_deferred_save_timer") and self._deferred_save_timer.isActive():
            self._deferred_save_timer.stop()
        if not self._deferred_save_pending:
            return
        self._deferred_save_pending = False
        self.store.save(self.model.config)

    def save_with_history(self, reason: str, *, merge_key: str = "") -> None:
        try:
            fingerprint = self.history_store.fingerprint(self.model.config)
            if fingerprint != self._last_layout_history_fingerprint:
                self.history_store.push(
                    self.model.config,
                    reason,
                    merge_key=merge_key or self._history_merge_key(reason),
                )
                self._last_layout_history_fingerprint = fingerprint
        except Exception as exc:
            log_exception(f"record layout history: {reason}", exc)
        self.save()

    def _history_merge_key(self, reason: str) -> str:
        if reason in {
            "appearance-change",
            "geometry-change",
            "settings-preview-move",
            "tab-reorder",
            "panel-change",
            "settings-save",
        }:
            return "layout-adjustment"
        return ""

    def _emergency_restore_desktop_takeover(self) -> None:
        try:
            self.takeover_service.restore_explorer_icons()
            self.takeover_service.detach_panels()
            self._takeover_marker.clear()
        except Exception:
            pass

    def _on_application_focus_changed(
        self, _old: QWidget | None, new: QWidget | None
    ) -> None:
        if self._shutdown_started or self._closing_group_from_focus:
            return
        if new is not None and self._widget_belongs_to_app(new):
            return
        QTimer.singleShot(0, self._close_all_group_folders_safe)

    def _on_global_mouse_press(self, widget: QWidget) -> None:
        if self._shutdown_started or self._closing_group_from_focus:
            return
        if self._widget_is_inside_group_popup(widget):
            return
        clicked_grid = self._item_grid_for_widget(widget)
        if clicked_grid is not None and self._group_id_for_widget(widget):
            self._close_group_folders_except(clicked_grid)
            return
        self._close_all_group_folders_safe()

    def _close_all_group_folders_safe(self) -> None:
        if self._shutdown_started or self._closing_group_from_focus:
            return
        has_open = any(
            panel.item_grid._open_group_id
            for panel in self._panels.values()
        )
        if not has_open:
            return
        self._closing_group_from_focus = True
        try:
            self._close_all_group_folders()
        finally:
            self._closing_group_from_focus = False

    def _close_group_folders_except(self, excluded_grid: ItemGridWidget) -> None:
        if self._shutdown_started or self._closing_group_from_focus:
            return
        self._closing_group_from_focus = True
        try:
            for panel in self._panels.values():
                if panel.item_grid is excluded_grid:
                    continue
                try:
                    panel.item_grid.close_open_group_folder()
                except RuntimeError:
                    pass
        finally:
            self._closing_group_from_focus = False

    def _widget_belongs_to_app(self, widget: QWidget) -> bool:
        current: QWidget | None = widget
        while current is not None:
            for panel in self._panels.values():
                if current is panel or current.window() is panel.window():
                    return True
            if self._settings_window is not None:
                try:
                    settings_valid = isValid(self._settings_window)
                    if settings_valid and (
                        current is self._settings_window
                        or current.window() is self._settings_window.window()
                    ):
                        return True
                    if not settings_valid:
                        self._settings_window = None
                except RuntimeError:
                    self._settings_window = None
            current = current.parentWidget()
        return False

    def _widget_is_inside_group_popup(self, widget: QWidget) -> bool:
        current: QWidget | None = widget
        while current is not None:
            try:
                if current.objectName() == "groupFolderPopupRoot":
                    return True
                current = current.parentWidget()
            except RuntimeError:
                return False
        return False

    def _item_grid_for_widget(self, widget: QWidget) -> ItemGridWidget | None:
        current: QWidget | None = widget
        while current is not None:
            if isinstance(current, ItemGridWidget):
                return current
            try:
                current = current.parentWidget()
            except RuntimeError:
                return None
        return None

    def _group_id_for_widget(self, widget: QWidget) -> str:
        current: QWidget | None = widget
        while current is not None:
            try:
                group_id = str(current.property("_group_id") or "")
                if group_id:
                    return group_id
                current = current.parentWidget()
            except RuntimeError:
                return ""
        return ""

    def _close_all_group_folders(self) -> None:
        for panel in self._panels.values():
            try:
                panel.item_grid.close_open_group_folder()
            except RuntimeError:
                pass

    def _on_about_to_quit(self) -> None:
        if self._shutdown_started:
            return
        self._shutdown_started = True
        _active_desktop_apps.discard(self)
        for panel in self._panels.values():
            panel._persist_geometry_from_widget(update_rh=not panel.is_collapsed)
        self._flush_deferred_save()
        restored = self._restore_desktop_takeover_if_needed()
        self._takeover_marker.clear()
        if not restored:
            get_logger().warning("退出时恢复 Explorer 桌面图标失败,下次启动会继续尝试")
        self.save_with_history("app-exit")

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
        takeover_should_stay_enabled = self.model.config.desktop.takeover_enabled
        restored = self._restore_desktop_takeover_if_needed()
        if takeover_should_stay_enabled and restored:
            self._apply_desktop_takeover_preference()
            self._notify_user("桌面接管刷新", "已尝试恢复并重新接管桌面。")
            return
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
        self.model.move_paths_to_tab(
            paths,
            tab_id,
            desktop_roots=self.index.directories(),
        )
        self.save()
        self.refresh()

    def refresh(self, _changes: IndexChanges | None = None) -> None:
        issues = self.model.repair_metadata(desktop_roots=self.index.directories())
        if issues:
            get_logger().info("元数据修复: %s", "; ".join(issues))
            self.save()
        for panel in self._panels.values():
            self._refresh_panel_item_grid(panel)

    def _refresh_panel_item_grid(self, panel: PanelGroupWidget) -> None:
        active_tab_id = panel.active_tab_id
        panel.item_grid.set_active_tab_id(active_tab_id)
        tab = self.model.tab(active_tab_id)
        panel.item_grid.set_reorder_enabled(tab.content_kind == "items")
        if tab.content_kind != "items":
            return
        entries = visible_entries_for_active_tab(
            self.model.config,
            self.index,
            active_tab_id=active_tab_id,
        )
        entries = arrange_entries_for_tab(self.model.config, entries, active_tab_id)
        group_blocks = group_blocks_for_tab(
            self.model.config, entries, active_tab_id
        )
        panel.item_grid.set_entries(
            entries,
            restorable_paths=self._restorable_paths_for_tab(entries, active_tab_id),
            groups=group_blocks,
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
        panel.active_tab_changed.connect(self._on_panel_active_tab_changed)
        panel.state_changed.connect(self._on_panel_state_changed)
        panel.appearance_changed.connect(self._on_panel_appearance_changed)
        panel.geometry_changed.connect(self._on_panel_geometry_changed)
        panel.layout_gesture_started.connect(self._on_panel_layout_gesture_started)
        panel.settings_requested.connect(self._show_settings)
        panel.organize_requested.connect(self._on_organize_requested)
        panel.item_grid.paths_dropped.connect(self._on_paths_dropped)
        panel.item_grid.restore_auto_requested.connect(self._on_restore_auto_requested)
        panel.item_grid.item_activated.connect(self._on_item_activated)
        panel.item_grid.items_reordered.connect(self._on_items_reordered)
        panel.item_grid.group_create_requested.connect(self._on_group_create_requested)
        panel.item_grid.group_join_requested.connect(self._on_group_join_requested)
        panel.item_grid.group_remove_requested.connect(self._on_group_remove_requested)
        panel.item_grid.group_rename_requested.connect(self._on_group_rename_requested)
        panel.item_grid.group_dissolve_requested.connect(self._on_group_dissolve_requested)
        panel.item_grid.set_group_accent_color(self.ui_preferences.group_accent_color)
        panel.tab_detach_requested.connect(self._on_tab_detach_requested)
        panel.tab_reordered.connect(self._on_panel_tab_reordered)
        panel.item_dropped_on_tab.connect(self._on_item_dropped_on_tab)
        panel.item_drag_over_tab.connect(self._on_item_drag_over_tab)
        panel.group_merge_requested.connect(self._on_group_merge_requested)
        panel.close_requested.connect(self._quit_from_tray)

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

    def _on_panel_active_tab_changed(self, group_id: str, _tab_id: str) -> None:
        panel = self._panels.get(group_id)
        if panel is None:
            return
        self._refresh_panel_item_grid(panel)
        self._schedule_deferred_save()

    def _on_panel_state_changed(self, _group_id: str) -> None:
        self._schedule_deferred_save()

    def _on_panel_geometry_changed(self) -> None:
        self.save_with_history("geometry-change")

    def _on_panel_appearance_changed(self) -> None:
        self.save_with_history("appearance-change")

    def _on_panel_tab_reordered(self, _group_id: str) -> None:
        self.save_with_history("tab-reorder")
        self.refresh()

    def _on_items_reordered(self, tab_id: str, paths: object) -> None:
        ordered = [Path(entry) for entry in paths]  # type: ignore[union-attr]
        try:
            self.model.reorder_tab_items(tab_id, ordered)
        except (KeyError, ValueError):
            return
        # 仅持久化显示顺序;不进布局历史,避免历史被排序操作刷屏。
        self.save()
        self.refresh()

    def _refresh_panels_for_tab(self, tab_id: str) -> None:
        for panel in self._panels.values():
            if panel.active_tab_id == tab_id:
                self._refresh_panel_item_grid(panel)

    def _item_group_tab_id(self, group_id: str) -> str:
        for group in self.model.config.item_groups:
            if group.id == group_id:
                return group.tab_id
        raise KeyError(group_id)

    def _tabs_containing_group_members(self, paths: list[Path]) -> set[str]:
        keys = {canonical_key(path) for path in paths}
        if not keys:
            return set()
        return {
            group.tab_id
            for group in self.model.config.item_groups
            if any(member in keys for member in group.member_paths)
        }

    def _on_group_create_requested(self, tab_id: str, paths: object) -> None:
        members = [Path(entry) for entry in paths]  # type: ignore[union-attr]
        suggested_name = members[0].stem if members else "新建分组"
        try:
            self.model.create_item_group(tab_id, members, name=suggested_name)
        except (KeyError, ValueError) as exc:
            get_logger().warning(
                "图标分组创建失败: tab=%s count=%d error=%s",
                tab_id,
                len(members),
                exc,
            )
            return
        get_logger().info("图标分组创建: tab=%s count=%d", tab_id, len(members))
        self.save()
        self._refresh_panels_for_tab(tab_id)

    def _on_group_join_requested(self, group_id: str, paths: object) -> None:
        members = [Path(entry) for entry in paths]  # type: ignore[union-attr]
        try:
            tab_id = self._item_group_tab_id(group_id)
            self.model.add_items_to_group(group_id, members)
        except (KeyError, ValueError) as exc:
            get_logger().warning(
                "图标分组加入失败: group=%s count=%d error=%s",
                group_id,
                len(members),
                exc,
            )
            return
        get_logger().info(
            "图标分组加入: group=%s tab=%s count=%d",
            group_id,
            tab_id,
            len(members),
        )
        self.save()
        self._refresh_panels_for_tab(tab_id)

    def _on_group_remove_requested(self, paths: object) -> None:
        members = [Path(entry) for entry in paths]  # type: ignore[union-attr]
        affected_tabs = self._tabs_containing_group_members(members)
        self.model.remove_items_from_group(members)
        get_logger().info(
            "图标分组移出: tabs=%s count=%d",
            ",".join(sorted(affected_tabs)) or "-",
            len(members),
        )
        self.save()
        for tab_id in affected_tabs:
            self._refresh_panels_for_tab(tab_id)

    def _on_group_rename_requested(self, group_id: str, name: str) -> None:
        try:
            tab_id = self._item_group_tab_id(group_id)
            self.model.rename_item_group(group_id, name)
        except KeyError as exc:
            get_logger().warning(
                "图标分组重命名失败: group=%s error=%s",
                group_id,
                exc,
            )
            return
        get_logger().info("图标分组重命名: group=%s tab=%s", group_id, tab_id)
        self.save()
        self._refresh_panels_for_tab(tab_id)

    def _on_group_dissolve_requested(self, group_id: str) -> None:
        try:
            tab_id = self._item_group_tab_id(group_id)
        except KeyError as exc:
            get_logger().warning(
                "图标分组解散失败: group=%s error=%s",
                group_id,
                exc,
            )
            return
        self.model.dissolve_item_group(group_id)
        get_logger().info("图标分组解散: group=%s tab=%s", group_id, tab_id)
        self.save()
        self._refresh_panels_for_tab(tab_id)

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

    def _on_item_dropped_on_tab(self, paths: object, tab_id: str) -> None:
        tab = next(
            (tab for tab in self.model.config.panel_tabs if tab.id == tab_id),
            None,
        )
        if tab is None or tab.content_kind != "items":
            return
        if isinstance(paths, Path):
            dropped = [paths]
        else:
            dropped = [Path(str(path)) for path in paths]
        self.handle_paths_dropped(dropped, tab_id)

    def _on_item_drag_over_tab(self, tab_id: str) -> None:
        tab = next(
            (tab for tab in self.model.config.panel_tabs if tab.id == tab_id),
            None,
        )
        if tab is None or tab.content_kind != "items":
            return
        for panel in self._panels.values():
            if tab_id not in panel.tab_button_ids():
                continue
            if panel.active_tab_id == tab_id:
                self._refresh_panel_item_grid(panel)
                return
            panel.activate_tab(tab_id, notify=False)
            self._refresh_panel_item_grid(panel)
            return

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
        issues = self.model.organize_by_rules(desktop_roots=self.index.directories())
        if issues:
            get_logger().info("整理时修复: %s", "; ".join(issues))
            preview = "; ".join(issues[:3])
            if len(issues) > 3:
                preview = f"{preview} 等 {len(issues)} 项"
            self._notify_user("整理完成", f"已修复：{preview}")
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
                screen_infos=available_screens(),
                ui_preferences=self.ui_preferences,
            )
            self._settings_window.config_saved.connect(self._on_settings_saved)
            self._settings_window.restore_desktop_requested.connect(
                self._restore_desktop_from_settings
            )
            self._settings_window.add_item_panel_requested.connect(
                self._on_add_item_panel_requested
            )
            self._settings_window.add_item_tab_requested.connect(
                self._on_add_item_tab_requested
            )
            self._settings_window.delete_item_panel_requested.connect(
                self._on_delete_item_panel_requested
            )
            self._settings_window.delete_item_tab_requested.connect(
                self._on_delete_item_tab_requested
            )
            self._settings_window.ui_preferences_changed.connect(
                self._save_ui_preferences
            )
            self._settings_window.management_metadata_changed.connect(
                self._on_settings_metadata_changed
            )
            self._settings_window.management_group_geometry_changed.connect(
                self._on_settings_group_geometry_changed
            )
            self._settings_window.management_tab_reordered.connect(
                self._on_settings_tab_reordered
            )
            self._settings_window.appearance_live_changed.connect(
                self._on_settings_appearance_live_changed
            )
            self._settings_window.appearance_live_save_requested.connect(
                self._on_settings_appearance_live_save_requested
            )
            self._settings_window.identify_screens_requested.connect(
                self._on_identify_screens_requested
            )
            self._settings_window.add_widget_panel_requested.connect(
                self._on_add_widget_panel_requested
            )
            self._settings_window.history_restore_requested.connect(
                self._on_history_restore_requested
            )
            self._settings_window.diagnostics_refresh_requested.connect(
                self._refresh_settings_diagnostics
            )
            self._settings_window.diagnostics_restore_icons_requested.connect(
                self._on_diagnostics_restore_icons_requested
            )
            self._settings_window.diagnostics_refresh_takeover_requested.connect(
                self._on_diagnostics_refresh_takeover_requested
            )
            self._settings_window.takeover_live_changed.connect(
                self._on_settings_takeover_live_changed
            )
            self._settings_window.diagnostics_open_logs_requested.connect(
                self._on_diagnostics_open_logs_requested
            )
            self._settings_window.diagnostics_export_requested.connect(
                self._on_diagnostics_export_requested
            )
            self._settings_window.update_check_requested.connect(
                self._on_update_check_requested
            )
            self._settings_window.update_download_requested.connect(
                self._on_update_download_requested
            )
            self._settings_window.update_open_folder_requested.connect(
                self._on_update_open_folder_requested
            )
            self._settings_window.update_replace_requested.connect(
                self._on_update_replace_requested
            )
        else:
            self._settings_window.set_configuration(
                self.model.config,
                group_id=group_id,
            )
        self._settings_window.set_history_snapshots(self.history_store.load())
        self._refresh_settings_diagnostics()
        self._refresh_settings_update_state()
        if self._settings_window.windowState() & Qt.WindowState.WindowMinimized:
            self._settings_window.showNormal()
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
            self.index = self._make_desktop_index(new_desktop)
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
        # 设置里的「恢复桌面图标」语义是:把图标找回来并让它留住,
        # 因此关闭桌面接管,避免恢复后立刻又被重新接管隐藏。
        # (托盘按钮保留「刷新接管」语义,见 _restore_desktop_from_tray。)
        restored = self._restore_desktop_takeover_if_needed()
        self.model.config.desktop.takeover_enabled = False
        self._takeover_active = False
        if restored:
            self.model.config.desktop.restore_required = False
            self.model.config.desktop.explorer_icons_hidden = False
        else:
            self.model.config.desktop.restore_required = True
        self.save()
        if self._settings_window is not None:
            self._settings_window.set_configuration(self.model.config)
        if restored:
            self._notify_user("桌面图标恢复", "已恢复 Explorer 桌面图标，并关闭桌面接管。")
        else:
            self._notify_user("桌面图标恢复", "恢复 Explorer 桌面图标失败，下次启动会继续尝试。")

    def _on_add_item_panel_requested(self) -> None:
        group = self.model.add_item_panel()
        if self._settings_window is not None:
            group.screen_id = self._settings_window.selected_screen_id()
            group.geometry = PanelGeometry(0.33, 0.33, group.geometry.rw, group.geometry.rh)
        panel = self._ensure_panel_widget(group.id)
        panel._apply_geometry_from_model()
        panel.show()
        self.panel = panel
        self._sync_panel_geometries()
        self._sync_panel_snap_targets()
        self.save_with_history("add-item-panel")
        if self._settings_window is not None:
            self._settings_window.set_configuration(self.model.config, group_id=group.id)
        self.refresh()

    def _on_settings_metadata_changed(self) -> None:
        for panel in self._panels.values():
            panel.reload_from_model()
        self.save_with_history("settings-rename")
        self.refresh()

    def _on_settings_group_geometry_changed(
        self,
        group_id: str,
        geometry: object,
        final: bool,
    ) -> None:
        group = self.model.group(group_id)
        if isinstance(geometry, PanelGeometry):
            group.geometry = geometry
        panel = self._panels.get(group_id)
        if panel is not None:
            panel._apply_geometry_from_model()
        self._sync_panel_snap_targets()
        if final:
            self.save_with_history("settings-preview-move")

    def _on_settings_tab_reordered(
        self,
        group_id: str,
        _tab_id: str,
        _target_index: int,
        final: bool,
    ) -> None:
        panel = self._panels.get(group_id)
        if panel is not None:
            panel.reload_from_model()
        if final:
            self.save_with_history("tab-reorder")
            self.refresh()

    def _on_settings_appearance_live_changed(
        self,
        group_id: str,
        color: str,
        opacity: float,
    ) -> None:
        # 颜色/透明度是全局外观：同时写入默认值和所有面板组,
        # 并刷新所有面板 widget,避免出现"只有当前面板生效"的视觉不一致。
        self.model.config.appearance_defaults.background_color = color
        self.model.config.appearance_defaults.background_opacity = opacity
        for group in self.model.config.panel_groups:
            group.appearance.background_color = color
            group.appearance.background_opacity = opacity
        for panel in self._panels.values():
            panel.reload_from_model()
            panel.update()

    def _on_settings_appearance_live_save_requested(self, group_id: str) -> None:
        self.save_with_history("appearance-change")

    def _on_add_item_tab_requested(self) -> None:
        group_id = self._settings_window.selected_group_id() if self._settings_window is not None else self.panel.group_id
        tab = self.model.add_tab(group_id, "新标签")
        panel = self._ensure_panel_widget(group_id)
        panel.reload_from_model()
        panel.activate_tab(tab.id)
        panel.start_inline_title_edit(tab.id)
        self._sync_panel_snap_targets()
        self.save_with_history("add-item-tab")
        if self._settings_window is not None:
            self._settings_window.set_configuration(self.model.config, group_id=group_id)
        self.refresh()

    def _on_identify_screens_requested(self) -> None:
        self._notify_user("显示器识别", "已在面板管理中高亮当前选择的显示器。")

    def _on_delete_item_panel_requested(self, group_id: str) -> None:
        if len(self.model.config.panel_groups) <= 1:
            return
        if group_id not in self._panels:
            return
        panel = self._panels.pop(group_id)
        panel.hide()
        panel.deleteLater()
        self.model.delete_group(group_id)
        replacement_group_id = self.model.config.panel_groups[0].id
        self.panel = self._ensure_panel_widget(replacement_group_id)
        self._sync_panel_geometries()
        self._sync_panel_snap_targets()
        self.save_with_history("delete-item-panel")
        if self._settings_window is not None:
            self._settings_window.set_configuration(
                self.model.config,
                group_id=replacement_group_id,
            )
        self.refresh()

    def _on_delete_item_tab_requested(self, tab_id: str) -> None:
        if len(self.model.config.panel_tabs) <= 1:
            return
        try:
            group_id = self.model.tab(tab_id).group_id
        except KeyError:
            return
        self.model.delete_tab(tab_id)
        if group_id not in [group.id for group in self.model.config.panel_groups]:
            removed = self._panels.pop(group_id, None)
            if removed is not None:
                removed.hide()
                removed.deleteLater()
            group_id = self.model.config.panel_groups[0].id
        panel = self._ensure_panel_widget(group_id)
        panel.reload_from_model()
        self._sync_panel_snap_targets()
        self.save_with_history("delete-item-tab")
        if self._settings_window is not None:
            self._settings_window.set_configuration(self.model.config, group_id=group_id)
        self.refresh()

    def _save_ui_preferences(self) -> None:
        self.ui_preferences_store.save(self.ui_preferences)
        self._apply_group_accent_preferences()

    def _apply_group_accent_preferences(self) -> None:
        accent = self.ui_preferences.group_accent_color
        for panel in self._panels.values():
            panel.item_grid.set_group_accent_color(accent)

    def _on_add_widget_panel_requested(self, widget_type: str) -> None:
        group = self.model.add_widget_panel(widget_type)
        if self._settings_window is not None:
            group.screen_id = self._settings_window.selected_screen_id()
            group.geometry = PanelGeometry(0.38, 0.38, group.geometry.rw, group.geometry.rh)
        panel = self._ensure_panel_widget(group.id)
        panel._apply_geometry_from_model()
        panel.show()
        self._sync_panel_geometries()
        self._sync_panel_snap_targets()
        self.save_with_history(f"add-widget-panel:{widget_type}")
        if self._settings_window is not None:
            self._settings_window.set_configuration(self.model.config, group_id=group.id)
        self.refresh()

    def _on_history_restore_requested(self, snapshot_id: str) -> None:
        try:
            restored = self.history_store.restore(snapshot_id)
        except KeyError:
            get_logger().warning("忽略未知布局快照: %s", snapshot_id)
            if self._settings_window is not None:
                self._settings_window.set_history_snapshots(self.history_store.load())
            return
        self._replace_configuration(restored)
        self.save()
        self.refresh()
        if self._settings_window is not None:
            # 历史恢复重建了 self.model,设置窗口必须改指向新配置对象,
            # 否则后续在设置里的编辑/保存会写到已废弃的旧配置。
            self._settings_window.set_configuration(
                self.model.config, group_id=self.panel.group_id
            )
            self._settings_window.set_history_snapshots(self.history_store.load())

    def _replace_configuration(self, config: Configuration) -> None:
        self.model = WorkspaceModel(config)
        self.config = self.model.config
        self._last_layout_history_fingerprint = self.history_store.fingerprint(
            self.model.config
        )
        self.diagnostics_service = self._create_diagnostics_service()
        try:
            self.watcher.changed.disconnect(self._on_desktop_changed)
        except RuntimeError:
            pass
        self.watcher.deleteLater()
        for panel in self._panels.values():
            panel.hide()
            panel.deleteLater()
        self._panels.clear()
        self.index = self._make_desktop_index(self.config.desktop.path)
        self.watcher = DesktopWatcher(self.index)
        self.watcher.changed.connect(self._on_desktop_changed)
        for group in self.config.panel_groups:
            self._ensure_panel_widget(group.id)
        self.panel = self._panels[self.config.panel_groups[0].id]
        self._sync_panel_geometries()
        self._sync_panel_snap_targets()
        for panel in self._panels.values():
            panel.show()

    def _create_diagnostics_service(self) -> DiagnosticsService:
        return DiagnosticsService(
            self.model.config,
            config_path=self.store.path,
            history_path=self.history_store.path,
            takeover_service=self.takeover_service,
            executable_path_provider=self._startup_executable_path,
            panel_handles_provider=self._panel_native_handles,
            panel_window_count_provider=lambda: len(self._panels),
            config_saver=self.save,
        )

    def _refresh_settings_diagnostics(self) -> None:
        if self._settings_window is None:
            return
        try:
            snapshot = self.diagnostics_service.collect_snapshot()
            logs = self.diagnostics_service.read_recent_logs(120)
            self._settings_window.set_diagnostics(snapshot, logs)
        except Exception as exc:
            log_exception("refresh settings diagnostics", exc)
            self._settings_window.show_diagnostics_message(f"诊断读取失败：{exc}")

    def _on_diagnostics_restore_icons_requested(self) -> None:
        result = self.diagnostics_service.restore_desktop_icons()
        if result.success:
            self._takeover_active = False
        self._show_diagnostics_result(result)

    def _on_diagnostics_refresh_takeover_requested(self) -> None:
        result = self.diagnostics_service.refresh_takeover_if_enabled()
        self._takeover_active = result.success
        self._show_diagnostics_result(result)

    def _on_settings_takeover_live_changed(self, enabled: bool) -> None:
        # 设置里勾选/取消「启用桌面接管」时立刻生效,无需点击保存。
        self.model.config.desktop.takeover_enabled = bool(enabled)
        self._apply_desktop_takeover_preference()
        self.save()
        if self._settings_window is not None:
            self._settings_window.set_configuration(self.model.config)
        if self.model.config.desktop.takeover_enabled and self._takeover_active:
            self._notify_user("桌面接管", "已进入桌面层，Explorer 桌面图标已隐藏。")
        elif not self.model.config.desktop.takeover_enabled:
            self._notify_user("桌面接管", "已退出桌面接管，Explorer 桌面图标已恢复。")

    def _on_diagnostics_open_logs_requested(self) -> None:
        try:
            self.diagnostics_service.log_dir.mkdir(parents=True, exist_ok=True)
            open_item(self.diagnostics_service.log_dir)
            self._show_diagnostics_result(
                RecoveryResult(True, "已打开日志文件夹", str(self.diagnostics_service.log_dir))
            )
        except Exception as exc:
            log_exception("open diagnostics log folder", exc)
            self._show_diagnostics_result(
                RecoveryResult(False, "打开日志文件夹失败", str(exc))
            )

    def _on_diagnostics_export_requested(self) -> None:
        try:
            bundle = self.diagnostics_service.export_bundle(self.store.path.parent)
            self._show_diagnostics_result(
                RecoveryResult(True, "已导出诊断包", str(bundle))
            )
        except Exception as exc:
            log_exception("export diagnostics from settings", exc)
            self._show_diagnostics_result(
                RecoveryResult(False, "导出诊断包失败", str(exc))
            )

    def _show_diagnostics_result(self, result: RecoveryResult) -> None:
        detail = f"\n{result.details}" if result.details else ""
        if self._settings_window is not None:
            self._refresh_settings_diagnostics()
            self._settings_window.show_diagnostics_message(f"{result.message}{detail}")
        self._notify_user(result.message, result.details or result.message)

    def _refresh_settings_update_state(self) -> None:
        if self._settings_window is None:
            return
        info = self._latest_update_info
        downloaded_path = (
            self._downloaded_update.path
            if self._downloaded_update is not None
            else None
        )
        download_ready = downloaded_path is not None and downloaded_path.is_file()
        self._settings_window.set_update_state(
            current_version=APP_VERSION,
            latest_version=info.latest_version if info is not None else "",
            message=self._update_status_message,
            update_available=bool(info and info.available),
            download_ready=download_ready,
            can_replace=download_ready and self._is_frozen_executable(),
        )

    def _on_update_check_requested(self) -> None:
        if self._settings_window is not None:
            self._settings_window.set_update_state(
                current_version=APP_VERSION,
                message="正在检查更新...",
                checking=True,
            )
        try:
            self._latest_update_info = self.update_service.check_latest()
            self._downloaded_update = None
            if self._latest_update_info.available:
                self._update_status_message = (
                    f"发现新版本 {self._latest_update_info.latest_version}。"
                )
            else:
                self._update_status_message = "已经是最新版本。"
        except Exception as exc:
            self._latest_update_info = None
            self._downloaded_update = None
            log_exception("check application update", exc)
            self._update_status_message = f"检查更新失败：{exc}"
            self._notify_user("检查更新失败", str(exc))
        self._refresh_settings_update_state()

    def _on_update_download_requested(self) -> None:
        if self._latest_update_info is None:
            self._on_update_check_requested()
            if self._latest_update_info is None:
                return
        if self._settings_window is not None:
            self._settings_window.set_update_state(
                current_version=APP_VERSION,
                latest_version=self._latest_update_info.latest_version,
                message="正在下载更新...",
                update_available=True,
                downloading=True,
            )
        try:
            self._downloaded_update = None
            self._downloaded_update = self.update_service.download(
                self._latest_update_info
            )
            if self._is_frozen_executable():
                self._update_status_message = (
                    f"下载完成：{self._downloaded_update.path}"
                )
            else:
                self._update_status_message = (
                    "下载完成。开发模式下请手动替换或打开更新文件夹。"
                )
        except Exception as exc:
            self._downloaded_update = None
            log_exception("download application update", exc)
            self._update_status_message = f"下载更新失败：{exc}"
            self._notify_user("下载更新失败", str(exc))
        self._refresh_settings_update_state()

    def _on_update_open_folder_requested(self) -> None:
        try:
            self.update_service.updates_dir.mkdir(parents=True, exist_ok=True)
            open_item(self.update_service.updates_dir)
            self._update_status_message = f"已打开：{self.update_service.updates_dir}"
        except Exception as exc:
            log_exception("open update folder", exc)
            self._update_status_message = f"打开更新文件夹失败：{exc}"
            self._notify_user("打开更新文件夹失败", str(exc))
        self._refresh_settings_update_state()

    def _on_update_replace_requested(self) -> None:
        if not self._is_frozen_executable():
            self._update_status_message = "当前是开发模式，不能自动替换。"
            self._refresh_settings_update_state()
            return
        if self._downloaded_update is None or not self._downloaded_update.path.is_file():
            self._update_status_message = "请先下载更新。"
            self._refresh_settings_update_state()
            return
        try:
            script = self.update_service.prepare_replace(
                self._downloaded_update.path,
                Path(sys.executable).resolve(),
            )
            subprocess.Popen(
                ["cmd.exe", "/c", str(script)],
                cwd=str(self.update_service.updates_dir),
                close_fds=True,
            )
            self._update_status_message = "正在替换并重启..."
            self._quit_from_tray()
        except Exception as exc:
            log_exception("prepare application update replacement", exc)
            self._update_status_message = f"准备替换失败：{exc}"
            self._notify_user("准备替换失败", str(exc))
            self._refresh_settings_update_state()

    def _is_frozen_executable(self) -> bool:
        return bool(getattr(sys, "frozen", False))

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
        if self._home_startup_dirty:
            self._schedule_deferred_save()
        self._apply_startup_preference()
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

    def _startup_executable_path(self) -> Path | None:
        return resolve_startup_executable_path()

    def _apply_startup_preference(self) -> None:
        startup_path = self._startup_executable_path()
        if self.model.config.desktop.startup_enabled and startup_path is None:
            detail = "开发模式下未找到 dist\\DesktopCleaner.exe，未写入开机启动项。"
            log_exception("startup registration failed", RuntimeError(detail))
            self._notify_user("开机启动设置失败", detail)
            return
        result = self.startup_service.set_enabled(
            self.model.config.desktop.startup_enabled,
            startup_path or Path(sys.executable).resolve(),
        )
        success = bool(getattr(result, "success", result))
        if not success and self.model.config.desktop.startup_enabled:
            detail = str(getattr(result, "message", "") or "系统拒绝写入开机启动项")
            log_exception("startup registration failed", RuntimeError(detail))
            self._notify_user("开机启动设置失败", detail)

    def _apply_desktop_takeover_preference(self) -> None:
        self._flush_deferred_save()
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
        self._takeover_marker.mark_active()
        self.save()

    def _disable_desktop_takeover_after_failure(self, *, restore: bool) -> None:
        if restore:
            restored = self.takeover_service.restore_explorer_icons()
        else:
            restored = True
        self.takeover_service.detach_panels()
        self._reassert_panel_desktop_layer()
        self._takeover_active = False
        self.model.config.desktop.takeover_enabled = False
        if restored:
            self.model.config.desktop.restore_required = False
            self.model.config.desktop.explorer_icons_hidden = False
        else:
            self.model.config.desktop.restore_required = True
        self.save()

    def _reassert_panel_desktop_layer(self) -> None:
        for panel in self._panels.values():
            panel.reassert_desktop_layer()

    def _restore_desktop_takeover_if_needed(self) -> bool:
        self._flush_deferred_save()
        if not (
            self._takeover_active
            or self.model.config.desktop.restore_required
            or self.model.config.desktop.explorer_icons_hidden
            or self._takeover_marker.is_active()
        ):
            return True
        restored = self.takeover_service.restore_explorer_icons()
        self.takeover_service.detach_panels()
        self._reassert_panel_desktop_layer()
        self._takeover_active = False
        self._takeover_marker.clear()
        if restored:
            self.model.config.desktop.restore_required = False
            self.model.config.desktop.explorer_icons_hidden = False
        else:
            self.model.config.desktop.restore_required = True
        return restored
