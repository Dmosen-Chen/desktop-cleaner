from __future__ import annotations

import json
import os
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QPoint, Qt, Signal
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from desktop_tidy.application import (
    DesktopCleanerApplication,
    application_store,
    visible_entries_for_active_tab,
)
from desktop_tidy.domain.classification import classify_path
from desktop_tidy.domain.defaults import build_default_configuration
from desktop_tidy.domain.classification import canonical_key
from desktop_tidy.domain.models import ItemRef, ManualOverride, PanelGeometry
from desktop_tidy.persistence.config_store import ConfigurationStore
from desktop_tidy.persistence.layout_history import LayoutHistoryStore
from desktop_tidy.services.desktop_index import DesktopIndex
from desktop_tidy.ui.settings_window import SettingsWindow
from tests.test_qt_item_grid import send_ctrl_wheel
from tests.test_qt_panel_group import (
    _ResizeRegion,
    find_tab_button,
    simulate_header_drag_release_at_global_point,
    simulate_tab_drag_release_at_local_point,
)


class FakeTakeoverService:
    def __init__(
        self,
        *,
        attach_success: bool = True,
        hide_result: bool = True,
        restore_result: bool = True,
    ) -> None:
        self.attach_success = attach_success
        self.hide_result = hide_result
        self.restore_result = restore_result
        self.calls: list[tuple[str, object]] = []

    def attach_panels(self, panel_hwnds: list[int]):
        self.calls.append(("attach", list(panel_hwnds)))
        return SimpleNamespace(success=self.attach_success, message="fake")

    def hide_explorer_icons(self) -> bool:
        self.calls.append(("hide", None))
        return self.hide_result

    def restore_explorer_icons(self) -> bool:
        self.calls.append(("restore", None))
        return self.restore_result

    def explorer_icons_visible(self) -> bool | None:
        self.calls.append(("visible", None))
        return not self.hide_result

    def detach_panels(self) -> None:
        self.calls.append(("detach", None))


class FakeStartupService:
    def __init__(self, result: bool = True) -> None:
        self.result = result
        self.calls: list[tuple[bool, Path]] = []

    def set_enabled(self, enabled: bool, exe_path: Path):
        self.calls.append((enabled, exe_path))
        return SimpleNamespace(success=self.result, message="fake startup failure")


class FakeTrayController(QObject):
    show_panels_requested = Signal()
    hide_panels_requested = Signal()
    settings_requested = Signal()
    restore_desktop_requested = Signal()
    quit_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.shown = False
        self.hidden = False

    def show(self) -> None:
        self.shown = True

    def hide(self) -> None:
        self.hidden = True

    def show_message(self, title: str, message: str) -> None:
        self.last_message = (title, message)


class FakeActivationServer(QObject):
    activated = Signal()


def assert_application_wires_panel_signals(app: DesktopCleanerApplication) -> None:
    panel = app.panel
    for signal_name in ("tab_detach_requested", "group_merge_requested"):
        if getattr(panel, signal_name, None) is None:
            raise AssertionError(f"PanelGroupWidget must expose {signal_name}")


class DesktopCleanerApplicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_application_store_uses_application_config(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            store = application_store()

            self.assertEqual(
                store.path,
                Path(tmp) / "DesktopCleaner" / "config.json",
            )
            self.assertEqual(store.path.name, "config.json")
            self.assertEqual(store.path, ConfigurationStore.default().path)

    def test_desktop_cleaner_application_uses_application_store_by_default(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            app = DesktopCleanerApplication(build_default_configuration(r"D:\Example\Desktop"))

            self.assertEqual(
                app.store.path,
                Path(tmp) / "DesktopCleaner" / "config.json",
            )

    def test_constructor_restores_leftover_hidden_desktop_icons_before_showing_panels(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            config = build_default_configuration(desktop)
            config.desktop.restore_required = True
            config.desktop.explorer_icons_hidden = True
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            takeover = FakeTakeoverService(restore_result=True)

            DesktopCleanerApplication(config, store=store, takeover_service=takeover)

            self.assertEqual(takeover.calls, [("restore", None)])
            self.assertFalse(config.desktop.restore_required)
            self.assertFalse(config.desktop.explorer_icons_hidden)
            payload = json.loads(store.path.read_text(encoding="utf-8"))
            self.assertFalse(payload["desktop"]["restore_required"])
            self.assertFalse(payload["desktop"]["explorer_icons_hidden"])

    def test_takeover_disabled_does_not_attach_or_hide_when_showing_panels(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            takeover = FakeTakeoverService()
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(
                build_default_configuration(desktop),
                store=store,
                takeover_service=takeover,
            )

            app.show()
            type(self).app.processEvents()

            self.assertEqual(takeover.calls, [])

    def test_takeover_enabled_attaches_marks_restore_then_hides_icons(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            config = build_default_configuration(desktop)
            config.desktop.takeover_enabled = True
            takeover = FakeTakeoverService()
            app = DesktopCleanerApplication(config, store=store, takeover_service=takeover)

            app.show()
            type(self).app.processEvents()

            self.assertEqual([name for name, _value in takeover.calls], ["attach", "hide"])
            self.assertTrue(config.desktop.takeover_enabled)
            self.assertTrue(config.desktop.restore_required)
            self.assertTrue(config.desktop.explorer_icons_hidden)
            payload = json.loads(store.path.read_text(encoding="utf-8"))
            self.assertTrue(payload["desktop"]["restore_required"])
            self.assertTrue(payload["desktop"]["explorer_icons_hidden"])

    def test_attach_failure_disables_takeover_and_never_hides_explorer_icons(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            config = build_default_configuration(desktop)
            config.desktop.takeover_enabled = True
            takeover = FakeTakeoverService(attach_success=False)
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(config, store=store, takeover_service=takeover)

            app.show()
            type(self).app.processEvents()

            self.assertEqual([name for name, _value in takeover.calls], ["attach", "detach"])
            self.assertFalse(config.desktop.takeover_enabled)
            self.assertFalse(config.desktop.restore_required)
            self.assertFalse(config.desktop.explorer_icons_hidden)

    def test_hide_failure_restores_detaches_and_disables_takeover(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            config = build_default_configuration(desktop)
            config.desktop.takeover_enabled = True
            takeover = FakeTakeoverService(hide_result=False)
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(config, store=store, takeover_service=takeover)

            app.show()
            type(self).app.processEvents()

            self.assertEqual(
                [name for name, _value in takeover.calls],
                ["attach", "hide", "restore", "detach"],
            )
            self.assertFalse(config.desktop.takeover_enabled)
            self.assertFalse(config.desktop.restore_required)
            self.assertFalse(config.desktop.explorer_icons_hidden)

    def test_disabling_takeover_from_settings_restores_icons_and_detaches_panels(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            config = build_default_configuration(desktop)
            config.desktop.takeover_enabled = True
            takeover = FakeTakeoverService()
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(config, store=store, takeover_service=takeover)
            app.show()
            type(self).app.processEvents()

            config.desktop.takeover_enabled = False
            app._on_settings_saved()

            self.assertEqual(
                [name for name, _value in takeover.calls],
                ["attach", "hide", "restore", "detach"],
            )
            self.assertFalse(config.desktop.restore_required)
            self.assertFalse(config.desktop.explorer_icons_hidden)

    def test_about_to_quit_restores_icons_when_takeover_is_active(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            config = build_default_configuration(desktop)
            config.desktop.takeover_enabled = True
            takeover = FakeTakeoverService()
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(config, store=store, takeover_service=takeover)
            app.show()
            type(self).app.processEvents()

            app._on_about_to_quit()

            self.assertEqual(
                [name for name, _value in takeover.calls],
                ["attach", "hide", "restore", "detach"],
            )
            self.assertFalse(config.desktop.restore_required)
            self.assertFalse(config.desktop.explorer_icons_hidden)

    def test_tray_hide_and_show_toggle_panel_visibility_without_quitting(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            tray = FakeTrayController()
            app = DesktopCleanerApplication(
                build_default_configuration(desktop),
                store=store,
                tray_controller=tray,
            )
            app.show()
            type(self).app.processEvents()

            self.assertTrue(app.panel.isVisible())

            tray.hide_panels_requested.emit()
            type(self).app.processEvents()

            self.assertFalse(app.panel.isVisible())

            tray.show_panels_requested.emit()
            type(self).app.processEvents()

            self.assertTrue(app.panel.isVisible())

    def test_second_launch_activation_shows_hidden_panels(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            tray = FakeTrayController()
            activation_server = FakeActivationServer()
            app = DesktopCleanerApplication(
                build_default_configuration(desktop),
                store=store,
                tray_controller=tray,
                activation_server=activation_server,
            )
            app.show()
            type(self).app.processEvents()
            tray.hide_panels_requested.emit()
            type(self).app.processEvents()
            self.assertFalse(app.panel.isVisible())

            activation_server.activated.emit()
            type(self).app.processEvents()

            self.assertTrue(app.panel.isVisible())

    def test_tray_restore_desktop_uses_existing_takeover_shutdown_path(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            config = build_default_configuration(desktop)
            takeover = FakeTakeoverService()
            tray = FakeTrayController()
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(
                config,
                store=store,
                takeover_service=takeover,
                tray_controller=tray,
            )
            app._takeover_active = True
            config.desktop.restore_required = True
            config.desktop.explorer_icons_hidden = True

            tray.restore_desktop_requested.emit()

            self.assertEqual(
                [name for name, _value in takeover.calls],
                ["restore", "detach"],
            )
            self.assertFalse(config.desktop.restore_required)
            self.assertFalse(config.desktop.explorer_icons_hidden)
            payload = json.loads(store.path.read_text(encoding="utf-8"))
            self.assertFalse(payload["desktop"]["restore_required"])

    def test_tray_restore_refreshes_takeover_when_preference_stays_enabled(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            config = build_default_configuration(desktop)
            config.desktop.takeover_enabled = True
            config.desktop.restore_required = True
            config.desktop.explorer_icons_hidden = True
            takeover = FakeTakeoverService()
            tray = FakeTrayController()
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(
                config,
                store=store,
                takeover_service=takeover,
                tray_controller=tray,
            )
            app._takeover_active = True
            takeover.calls.clear()

            tray.restore_desktop_requested.emit()

            self.assertEqual(
                [name for name, _value in takeover.calls],
                ["restore", "detach", "attach", "hide"],
            )
            self.assertTrue(config.desktop.takeover_enabled)
            self.assertTrue(config.desktop.restore_required)
            self.assertTrue(config.desktop.explorer_icons_hidden)
            payload = json.loads(store.path.read_text(encoding="utf-8"))
            self.assertTrue(payload["desktop"]["explorer_icons_hidden"])

    def test_tray_quit_saves_and_restores_before_requesting_application_quit(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            config = build_default_configuration(desktop)
            takeover = FakeTakeoverService()
            tray = FakeTrayController()
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(
                config,
                store=store,
                takeover_service=takeover,
                tray_controller=tray,
            )
            app._takeover_active = True
            config.desktop.restore_required = True
            config.desktop.explorer_icons_hidden = True

            tray.quit_requested.emit()

            self.assertEqual(
                [name for name, _value in takeover.calls],
                ["restore", "detach"],
            )
            self.assertFalse(config.desktop.restore_required)
            self.assertFalse(config.desktop.explorer_icons_hidden)
            self.assertTrue(store.path.is_file())

    def test_settings_saved_applies_startup_preference_without_real_registry_access(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            config = build_default_configuration(desktop)
            startup = FakeStartupService()
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(config, store=store, startup_service=startup)

            config.desktop.startup_enabled = True
            app._on_settings_saved()

            self.assertEqual(len(startup.calls), 1)
            enabled, exe_path = startup.calls[0]
            self.assertTrue(enabled)
            self.assertTrue(exe_path.is_absolute())

    def test_startup_registration_failure_keeps_user_checkbox_enabled(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            config = build_default_configuration(desktop)
            config.desktop.startup_enabled = True
            startup = FakeStartupService(result=False)
            tray = FakeTrayController()
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(
                config,
                store=store,
                startup_service=startup,
                tray_controller=tray,
            )

            app._apply_startup_preference()

            self.assertTrue(app.model.config.desktop.startup_enabled)
            self.assertTrue(startup.calls[-1][0])
            self.assertIn("开机启动", tray.last_message[0])

    def test_settings_diagnostics_actions_use_recovery_export_and_log_services(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            config = build_default_configuration(desktop)
            config.desktop.takeover_enabled = True
            takeover = FakeTakeoverService()
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(
                config,
                store=store,
                takeover_service=takeover,
            )
            app._show_settings(app.panel.group_id)
            self.assertIsNotNone(app._settings_window)
            settings = app._settings_window
            assert settings is not None

            with patch("desktop_tidy.application.open_item") as open_item:
                settings._diagnostics_refresh_button.click()
                settings._diagnostics_restore_icons_button.click()
                settings._diagnostics_refresh_takeover_button.click()
                settings._diagnostics_open_logs_button.click()
                settings._diagnostics_export_button.click()

            self.assertEqual(
                [name for name, _value in takeover.calls if name != "visible"],
                ["restore", "restore", "detach", "attach", "hide"],
            )
            open_item.assert_called_once_with(store.path.parent / "logs")
            bundles = list(store.path.parent.glob("desktop-cleaner-diagnostics-*.zip"))
            self.assertEqual(len(bundles), 1)
            self.assertIn("已导出诊断包", settings.all_text())

    def test_settings_can_add_item_panel_and_item_tab(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(build_default_configuration(desktop), store=store)
            app.show()
            type(self).app.processEvents()
            app._show_settings(app.panel.group_id)
            settings = app._settings_window
            assert settings is not None

            settings._management_add_button.click()
            type(self).app.processEvents()
            settings._panel_tab_list.itemClicked.emit(settings._panel_tab_list.item(0))
            settings._management_add_button.click()
            type(self).app.processEvents()

            self.assertGreaterEqual(len(app.model.config.panel_groups), 2)
            self.assertTrue(
                any(tab.name == "新标签" and tab.content_kind == "items" for tab in app.model.config.panel_tabs)
            )
            self.assertEqual(len(app.panel_widgets()), len(app.model.config.panel_groups))
            self.assertTrue(store.path.is_file())

    def test_settings_refreshes_after_creating_item_panel_and_adds_tab_to_selected_group(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(build_default_configuration(desktop), store=store)
            app.show()
            type(self).app.processEvents()
            app._show_settings(app.panel.group_id)
            settings = app._settings_window
            assert settings is not None

            settings._management_add_button.click()
            type(self).app.processEvents()
            new_group = app.model.config.panel_groups[-1]

            self.assertEqual(settings.selected_group_id(), new_group.id)
            self.assertIn("面板 2", settings._panel_management_page_text())
            settings._panel_tab_list.itemClicked.emit(settings._panel_tab_list.item(0))
            settings._management_add_button.click()
            type(self).app.processEvents()

            self.assertEqual(len(app.model.group(new_group.id).tab_ids), 2)
            self.assertEqual(app.model.tab(app.model.group(new_group.id).active_tab_id).name, "新标签")

    def test_settings_delete_panel_and_tab_only_remove_metadata(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            real_file = desktop / "keep.pdf"
            real_file.write_text("keep", encoding="utf-8")
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(build_default_configuration(desktop), store=store)
            extra_group = app.model.add_item_panel("临时")
            app._ensure_panel_widget(extra_group.id)
            app._show_settings(extra_group.id)
            settings = app._settings_window
            assert settings is not None
            settings._delete_confirmation = lambda _kind, _label: (True, False)

            settings._management_delete_button.click()
            type(self).app.processEvents()

            self.assertTrue(real_file.is_file())
            self.assertFalse(any(group.id == extra_group.id for group in app.model.config.panel_groups))
            self.assertNotIn(extra_group.id, app.panel_widgets())

    def test_item_reference_changes_do_not_create_layout_history(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            appdata_root = root / "appdata"
            desktop = root / "desktop"
            outside = root / "outside"
            desktop.mkdir()
            outside.mkdir()
            source = outside / "sample.weird"
            source.write_text("keep-me", encoding="utf-8")
            history_store = LayoutHistoryStore(appdata_root / "DesktopCleaner" / "layout-history.json")
            store = ConfigurationStore(appdata_root / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(
                build_default_configuration(desktop),
                store=store,
                history_store=history_store,
            )

            app.handle_paths_dropped([source], "tab-images")

            self.assertEqual(history_store.load(), [])

    def test_external_drop_is_saved_only_as_external_refs(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            appdata_root = root / "appdata"
            desktop = root / "desktop"
            outside = root / "outside"
            desktop.mkdir()
            outside.mkdir()
            source = outside / "sample.weird"
            source.write_text("keep-me", encoding="utf-8")
            store = ConfigurationStore(appdata_root / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(build_default_configuration(desktop), store=store)

            app.handle_paths_dropped([source], "tab-images")
            app.save()

            self.assertEqual(app.model.config.manual_overrides, [])
            self.assertEqual(len(app.model.config.external_refs), 1)
            self.assertEqual(app.model.config.external_refs[0].target_tab_id, "tab-images")
            self.assertEqual(list(desktop.iterdir()), [])
            self.assertEqual(source.read_text(encoding="utf-8"), "keep-me")

    def test_handle_paths_dropped_persists_application_config_without_explicit_save(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            appdata_root = root / "appdata"
            desktop = root / "desktop"
            outside = root / "outside"
            desktop.mkdir()
            outside.mkdir()
            source = outside / "sample.weird"
            source.write_text("keep-me", encoding="utf-8")
            store = ConfigurationStore(appdata_root / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(build_default_configuration(desktop), store=store)

            app.handle_paths_dropped([source], "tab-images")

            self.assertEqual(app.model.config.manual_overrides, [])
            self.assertEqual(len(app.model.config.external_refs), 1)
            self.assertEqual(app.model.config.external_refs[0].target_tab_id, "tab-images")
            self.assertEqual(list(desktop.iterdir()), [])
            self.assertEqual(source.read_text(encoding="utf-8"), "keep-me")

            saved_path = store.path
            self.assertTrue(
                saved_path.is_file(),
                "handle_paths_dropped must persist config.json without app.save()",
            )
            payload = json.loads(saved_path.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["external_refs"]), 1)
            self.assertEqual(payload["external_refs"][0]["target_tab_id"], "tab-images")
            self.assertEqual(
                Path(payload["external_refs"][0]["canonical_path"]).resolve(),
                source.resolve(),
            )

    def test_missing_external_reference_remains_visible_for_runtime_relink(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            desktop = root / "desktop"
            desktop.mkdir()
            missing_path = (root / "outside" / "gone.txt").resolve()
            config = build_default_configuration(desktop)
            config.external_refs.append(
                ItemRef(
                    id="external-missing",
                    source_kind="external",
                    canonical_path=str(missing_path),
                    target_tab_id="tab-documents",
                )
            )
            self.assertFalse(missing_path.exists())

            entries = visible_entries_for_active_tab(
                config,
                DesktopIndex(desktop),
                active_tab_id="tab-documents",
            )
            entry_paths = [entry.path.resolve() for entry in entries]
            self.assertIn(
                missing_path,
                entry_paths,
                "missing external refs must stay visible for relink/remove UI",
            )

    def test_settings_desktop_path_change_rebuilds_index_in_same_preview_session(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            appdata_root = root / "appdata"
            desktop_a = root / "desktop-a"
            desktop_b = root / "desktop-b"
            desktop_a.mkdir()
            desktop_b.mkdir()
            (desktop_a / "photo-a.png").write_text("a", encoding="utf-8")
            (desktop_b / "photo-b.png").write_text("b", encoding="utf-8")
            store = ConfigurationStore(appdata_root / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(build_default_configuration(desktop_a), store=store)

            settings = SettingsWindow(app.model.config)
            settings.config_saved.connect(app._on_settings_saved)
            settings._desktop_path_edit.setText(str(desktop_b))
            settings._save()

            self.assertEqual(app.model.config.desktop.path, str(desktop_b))
            self.assertEqual(
                app.index.desktop.resolve(),
                desktop_b.resolve(),
                "DesktopCleanerApplication must rebuild DesktopIndex for the new desktop path",
            )
            self.assertEqual(
                app.watcher._index.desktop.resolve(),
                desktop_b.resolve(),
                "DesktopCleanerApplication must reconnect DesktopWatcher to the new desktop path",
            )

            app.panel.activate_tab("tab-images")
            app.refresh()
            visible_paths = {path.name for path in app.panel.item_grid.entry_paths()}
            self.assertIn("photo-b.png", visible_paths)
            self.assertNotIn("photo-a.png", visible_paths)
            self.assertEqual(list(desktop_a.iterdir()), [desktop_a / "photo-a.png"])
            self.assertEqual(list(desktop_b.iterdir()), [desktop_b / "photo-b.png"])

            self.assertTrue(store.path.is_file())
            self.assertEqual(store.path.name, "config.json")
            self.assertFalse(str(store.path.resolve()).startswith(str(desktop_a.resolve())))
            self.assertFalse(str(store.path.resolve()).startswith(str(desktop_b.resolve())))
            payload = json.loads(store.path.read_text(encoding="utf-8"))
            self.assertEqual(Path(payload["desktop"]["path"]).resolve(), desktop_b.resolve())

    def test_save_writes_application_config_outside_configured_desktop_directory(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            appdata_root = root / "appdata"
            desktop = root / "desktop"
            outside = root / "outside"
            desktop.mkdir()
            outside.mkdir()
            source = outside / "folder-ref"
            source.mkdir()
            store = ConfigurationStore(appdata_root / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(build_default_configuration(desktop), store=store)

            app.handle_paths_dropped([source], "tab-folders")
            app.save()

            saved_path = store.path
            self.assertTrue(saved_path.is_file())
            self.assertFalse(str(saved_path).startswith(str(desktop.resolve())))
            payload = json.loads(saved_path.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["external_refs"]), 1)
            self.assertEqual(payload["external_refs"][0]["target_tab_id"], "tab-folders")
            self.assertEqual(list(desktop.iterdir()), [])

    def test_save_does_not_create_config_json_in_preview_directory(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            appdata_root = root / "appdata"
            desktop = root / "desktop"
            desktop.mkdir()
            store = ConfigurationStore(appdata_root / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(build_default_configuration(desktop), store=store)

            app.save()

            self.assertTrue(store.path.exists())
            self.assertEqual(store.path.name, "config.json")

    def test_detach_creates_second_panel_widget_and_refresh_keeps_both_in_sync(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(build_default_configuration(desktop), store=store)
            app.show()
            type(self).app.processEvents()

            app.panel.activate_tab("tab-images")
            app.detach_tab_to_new_group("tab-images", PanelGeometry(0.55, 0.18, 0.28, 0.42))
            type(self).app.processEvents()

            panels = app.panel_widgets()
            self.assertEqual(len(panels), 2)
            group_ids = {panel.group_id for panel in panels}
            self.assertEqual(len(group_ids), 2)
            self.assertIn("group-default", group_ids)

            moved_group_id = app.model.tab("tab-images").group_id
            self.assertIn(moved_group_id, group_ids)
            app.refresh()
            type(self).app.processEvents()
            self.assertEqual({panel.group_id for panel in app.panel_widgets()}, group_ids)
            self.assertEqual(
                next(panel for panel in app.panel_widgets() if panel.group_id == moved_group_id).active_tab_id,
                "tab-images",
            )

    def test_merge_on_pointer_inside_target_panel_persists_to_application_config(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(build_default_configuration(desktop), store=store)
            app.show()
            type(self).app.processEvents()

            app.panel.activate_tab("tab-images")
            app.detach_tab_to_new_group("tab-images", PanelGeometry(0.55, 0.18, 0.28, 0.42))
            type(self).app.processEvents()

            moved_group_id = app.model.tab("tab-images").group_id
            source = next(panel for panel in app.panel_widgets() if panel.group_id == moved_group_id)
            target = next(panel for panel in app.panel_widgets() if panel.group_id == "group-default")
            inside = target.mapToGlobal(QPoint(target.width() // 2, target.height() // 2))

            merged = app.complete_group_merge_at_global_point(source.group_id, (inside.x(), inside.y()))
            type(self).app.processEvents()

            self.assertTrue(merged)
            self.assertEqual(len(app.model.config.panel_groups), 1)
            self.assertIn("tab-images", app.model.group("group-default").tab_ids)
            self.assertEqual(len(app.panel_widgets()), 1)
            self.assertTrue(store.path.is_file())
            payload = json.loads(store.path.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["panel_groups"]), 1)
            self.assertIn("tab-images", payload["panel_groups"][0]["tab_ids"])
            self.assertEqual(store.path.name, "config.json")

    def test_merge_rejects_release_outside_target_panel_bounds(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            app = DesktopCleanerApplication(build_default_configuration(desktop))
            app.show()
            type(self).app.processEvents()

            app.panel.activate_tab("tab-images")
            app.detach_tab_to_new_group("tab-images", PanelGeometry(0.55, 0.18, 0.28, 0.42))
            type(self).app.processEvents()

            moved_group_id = app.model.tab("tab-images").group_id
            source = next(panel for panel in app.panel_widgets() if panel.group_id == moved_group_id)
            target = next(panel for panel in app.panel_widgets() if panel.group_id == "group-default")
            outside = target.mapToGlobal(QPoint(-20, target.height() // 2))

            merged = app.complete_group_merge_at_global_point(source.group_id, (outside.x(), outside.y()))
            type(self).app.processEvents()

            self.assertFalse(merged)
            self.assertEqual(len(app.model.config.panel_groups), 2)
            self.assertEqual(len(app.panel_widgets()), 2)
            self.assertEqual(app.model.tab("tab-images").group_id, source.group_id)

    def test_mouse_tab_drag_outside_wires_detach_and_persists_application_config(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(build_default_configuration(desktop), store=store)
            app.show()
            type(self).app.processEvents()

            assert_application_wires_panel_signals(app)

            panel = app.panel
            panel.activate_tab("tab-images")
            outside = QPoint(panel.width() + 40, panel.height() // 2)
            simulate_tab_drag_release_at_local_point(panel, "图片", outside)
            type(self).app.processEvents()

            panels = app.panel_widgets()
            self.assertEqual(len(panels), 2)
            moved_group_id = app.model.tab("tab-images").group_id
            self.assertNotEqual(moved_group_id, "group-default")
            self.assertEqual(
                {panel.group_id for panel in panels},
                {"group-default", moved_group_id},
            )
            self.assertTrue(store.path.is_file())
            payload = json.loads(store.path.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["panel_groups"]), 2)
            self.assertEqual(store.path.name, "config.json")

    def test_mouse_header_drag_release_wires_merge_and_persists_application_config(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(build_default_configuration(desktop), store=store)
            app.show()
            type(self).app.processEvents()

            assert_application_wires_panel_signals(app)

            app.panel.activate_tab("tab-images")
            app.detach_tab_to_new_group("tab-images", PanelGeometry(0.55, 0.18, 0.28, 0.42))
            type(self).app.processEvents()

            moved_group_id = app.model.tab("tab-images").group_id
            source = next(panel for panel in app.panel_widgets() if panel.group_id == moved_group_id)
            target = next(panel for panel in app.panel_widgets() if panel.group_id == "group-default")
            inside_global = target.mapToGlobal(QPoint(target.width() // 2, target.height() // 2))

            simulate_header_drag_release_at_global_point(source, inside_global)
            type(self).app.processEvents()

            self.assertEqual(len(app.model.config.panel_groups), 1)
            self.assertIn("tab-images", app.model.group("group-default").tab_ids)
            self.assertEqual(len(app.panel_widgets()), 1)
            self.assertTrue(store.path.is_file())
            payload = json.loads(store.path.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["panel_groups"]), 1)
            self.assertIn("tab-images", payload["panel_groups"][0]["tab_ids"])

    def test_locked_panel_mouse_gestures_do_not_detach_or_merge_through_application(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(build_default_configuration(desktop), store=store)
            app.show()
            type(self).app.processEvents()

            assert_application_wires_panel_signals(app)

            panel = app.panel
            panel.set_locked(True)
            outside = QPoint(panel.width() + 40, panel.height() // 2)
            simulate_tab_drag_release_at_local_point(panel, "图片", outside)

            release_global = panel.mapToGlobal(QPoint(150, 36))
            simulate_header_drag_release_at_global_point(panel, release_global)
            type(self).app.processEvents()

            self.assertEqual(len(app.panel_widgets()), 1)
            self.assertEqual(len(app.model.config.panel_groups), 1)
            self.assertEqual(app.model.tab("tab-images").group_id, "group-default")
            if store.path.is_file():
                payload = json.loads(store.path.read_text(encoding="utf-8"))
                self.assertEqual(len(payload["panel_groups"]), 1)

    def test_merge_when_default_is_source_reassigns_primary_panel_reference(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            app = DesktopCleanerApplication(build_default_configuration(desktop))
            app.show()
            type(self).app.processEvents()

            assert_application_wires_panel_signals(app)

            default_panel = app.panel
            self.assertEqual(default_panel.group_id, "group-default")
            app.panel.activate_tab("tab-images")
            app.detach_tab_to_new_group("tab-images", PanelGeometry(0.55, 0.18, 0.28, 0.42))
            type(self).app.processEvents()

            detached_group_id = app.model.tab("tab-images").group_id
            detached_panel = next(
                panel for panel in app.panel_widgets() if panel.group_id == detached_group_id
            )
            inside_global = detached_panel.mapToGlobal(
                QPoint(detached_panel.width() // 2, detached_panel.height() // 2)
            )

            simulate_header_drag_release_at_global_point(default_panel, inside_global)
            type(self).app.processEvents()

            live_panels = app.panel_widgets()
            self.assertEqual(len(live_panels), 1)
            surviving_panel = live_panels[0]
            self.assertEqual(surviving_panel.group_id, detached_group_id)
            self.assertIs(
                app.panel,
                surviving_panel,
                "DesktopCleanerApplication.panel must follow the surviving widget after default merge",
            )
            self.assertNotIn("group-default", {panel.group_id for panel in live_panels})

            surviving_panel.activate_tab("tab-folders")
            app.refresh()
            type(self).app.processEvents()
            self.assertEqual(surviving_panel.active_tab_id, "tab-folders")
            self.assertEqual(
                {panel.group_id for panel in app.panel_widgets()},
                {detached_group_id},
            )

    def test_settings_appearance_applies_to_all_panel_groups(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            app = DesktopCleanerApplication(build_default_configuration(desktop))
            app.show()
            type(self).app.processEvents()

            primary_color = "#101010"
            secondary_color = "#202020"
            saved_color = "#AABBCC"
            app.model.group("group-default").appearance.background_color = primary_color
            app.panel.activate_tab("tab-images")
            app.detach_tab_to_new_group("tab-images", PanelGeometry(0.55, 0.18, 0.28, 0.42))
            type(self).app.processEvents()

            secondary_group_id = app.model.tab("tab-images").group_id
            app.model.group(secondary_group_id).appearance.background_color = secondary_color
            secondary_panel = next(
                panel for panel in app.panel_widgets() if panel.group_id == secondary_group_id
            )

            QTest.mouseClick(secondary_panel.more_button, Qt.MouseButton.LeftButton)
            type(self).app.processEvents()

            settings = app._settings_window
            self.assertIsNotNone(settings)
            settings._select_color(saved_color)
            settings._opacity_slider.setValue(33)
            settings._save()
            type(self).app.processEvents()

            self.assertEqual(
                app.model.group("group-default").appearance.background_color,
                saved_color,
                "appearance settings are now global across panel groups",
            )
            self.assertAlmostEqual(
                app.model.group("group-default").appearance.background_opacity,
                0.33,
            )
            self.assertEqual(
                app.model.group(secondary_group_id).appearance.background_color,
                saved_color,
            )
            self.assertAlmostEqual(
                app.model.group(secondary_group_id).appearance.background_opacity,
                0.33,
            )

    def test_settings_appearance_live_change_updates_panel_and_saves_debounced(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(build_default_configuration(desktop), store=store)
            app.show()
            type(self).app.processEvents()
            app.detach_tab_to_new_group(
                "tab-documents",
                PanelGeometry(0.45, 0.20, 0.30, 0.35),
            )
            type(self).app.processEvents()
            app._show_settings(app.panel.group_id)
            settings = app._settings_window
            self.assertIsNotNone(settings)

            settings._select_color("#4B5563")
            settings._opacity_slider.setValue(70)
            type(self).app.processEvents()

            group = app.model.group("group-default")
            self.assertEqual(group.appearance.background_color, "#4B5563")
            self.assertAlmostEqual(group.appearance.background_opacity, 0.70)
            for panel_group in app.model.config.panel_groups:
                self.assertEqual(panel_group.appearance.background_color, "#4B5563")
                self.assertAlmostEqual(panel_group.appearance.background_opacity, 0.70)
            self.assertAlmostEqual(app.panel.background_opacity, 0.70)

            QTest.qWait(350)
            payload = json.loads(store.path.read_text(encoding="utf-8"))
            for panel_group in payload["panel_groups"]:
                appearance = panel_group["appearance"]
                self.assertEqual(appearance["background_color"], "#4B5563")
                self.assertAlmostEqual(appearance["background_opacity"], 0.70)

    def test_constructor_with_explicit_config_does_not_access_real_application_store(
        self,
    ) -> None:
        invalid_root = r"S:\does-not-exist-917a3f2c"
        with patch.dict(os.environ, {"LOCALAPPDATA": invalid_root}):
            try:
                app = DesktopCleanerApplication(build_default_configuration(r"D:\Example\Desktop"))
            except (OSError, PermissionError) as exc:
                raise AssertionError(
                    "DesktopCleanerApplication(config=...) must not stat or access the preview "
                    "store path on the real filesystem"
                ) from exc

        self.assertEqual(
            app.model.config.appearance_defaults.background_color,
            "#111111",
            "explicit config without store must preserve factory defaults",
        )
        self.assertEqual(
            app.model.group("group-default").appearance.background_color,
            "#111111",
        )

    def test_new_application_config_uses_black_sixty_percent_appearance(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(build_default_configuration(desktop), store=store)

            self.assertEqual(
                app.model.group("group-default").appearance.background_color,
                "#000000",
            )
            self.assertAlmostEqual(
                app.model.group("group-default").appearance.background_opacity,
                0.60,
            )
            self.assertEqual(app.model.config.appearance_defaults.background_color, "#000000")

    def test_detached_group_inherits_preview_black_appearance_defaults(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(build_default_configuration(desktop), store=store)
            app.show()
            type(self).app.processEvents()

            app.panel.activate_tab("tab-images")
            app.detach_tab_to_new_group("tab-images", PanelGeometry(0.55, 0.18, 0.28, 0.42))
            type(self).app.processEvents()

            detached_id = app.model.tab("tab-images").group_id
            appearance = app.model.group(detached_id).appearance
            self.assertEqual(appearance.background_color, "#000000")
            self.assertAlmostEqual(appearance.background_opacity, 0.60)

    def test_delete_sole_tab_on_detached_group_disposes_widget_and_keeps_primary(
        self,
    ) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(build_default_configuration(desktop), store=store)
            app.show()
            type(self).app.processEvents()

            app.panel.activate_tab("tab-images")
            app.detach_tab_to_new_group("tab-images", PanelGeometry(0.55, 0.18, 0.28, 0.42))
            type(self).app.processEvents()

            detached_id = app.model.tab("tab-images").group_id
            detached_panel = next(
                panel for panel in app.panel_widgets() if panel.group_id == detached_id
            )
            self.assertEqual(len(detached_panel.tab_button_ids()), 1)

            QTest.mouseClick(detached_panel.delete_button, Qt.MouseButton.LeftButton)
            type(self).app.processEvents()

            self.assertEqual(len(app.model.config.panel_groups), 1)
            self.assertEqual(app.model.config.panel_groups[0].id, "group-default")
            self.assertEqual(len(app.panel_widgets()), 1)
            self.assertEqual(app.panel.group_id, "group-default")
            self.assertNotIn(detached_id, app._panels)
            self.assertTrue(store.path.is_file())

    def test_delete_final_tab_on_sole_group_keeps_existing_panel_instead_of_rebuilding(
        self,
    ) -> None:
        """Deleting repeatedly must stop at one tab instead of creating a fresh group."""
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(build_default_configuration(desktop), store=store)
            app.show()
            type(self).app.processEvents()

            app.panel.activate_tab("tab-images")
            app.detach_tab_to_new_group("tab-images", PanelGeometry(0.55, 0.18, 0.28, 0.42))
            type(self).app.processEvents()

            surviving_id = app.model.tab("tab-images").group_id
            surviving_panel = next(
                panel for panel in app.panel_widgets() if panel.group_id == surviving_id
            )
            default_panel = next(
                panel for panel in app.panel_widgets() if panel.group_id == "group-default"
            )
            inside_global = surviving_panel.mapToGlobal(
                QPoint(surviving_panel.width() // 2, surviving_panel.height() // 2)
            )
            simulate_header_drag_release_at_global_point(default_panel, inside_global)
            type(self).app.processEvents()

            self.assertEqual(len(app.model.config.panel_groups), 1)
            self.assertEqual(app.model.config.panel_groups[0].id, surviving_id)
            self.assertIs(app.panel, surviving_panel)
            self.assertNotIn("group-default", app._panels)

            while len(surviving_panel.tab_button_ids()) > 1:
                QTest.mouseClick(
                    surviving_panel.delete_button,
                    Qt.MouseButton.LeftButton,
                )
                type(self).app.processEvents()
                surviving_panel = app.panel

            QTest.mouseClick(surviving_panel.delete_button, Qt.MouseButton.LeftButton)
            type(self).app.processEvents()

            self.assertEqual(len(app.model.config.panel_groups), 1)
            self.assertEqual(app.model.config.panel_groups[0].id, surviving_id)
            live_panels = app.panel_widgets()
            self.assertEqual(len(live_panels), 1)
            surviving_widget = live_panels[0]
            self.assertEqual(surviving_widget.group_id, surviving_id)
            self.assertIs(app.panel, surviving_widget)
            self.assertIn(surviving_id, app._panels)
            self.assertTrue(surviving_widget.isVisible())
            self.assertEqual(len(surviving_widget.tab_button_ids()), 1)
            self.assertTrue(store.path.is_file())
            payload = json.loads(store.path.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["panel_groups"]), 1)
            self.assertEqual(payload["panel_groups"][0]["id"], surviving_id)

    def test_delete_sole_tab_when_primary_is_not_default_group(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            app = DesktopCleanerApplication(build_default_configuration(desktop))
            app.show()
            type(self).app.processEvents()

            app.panel.activate_tab("tab-images")
            app.detach_tab_to_new_group("tab-images", PanelGeometry(0.55, 0.18, 0.28, 0.42))
            type(self).app.processEvents()

            surviving_id = app.model.tab("tab-images").group_id
            surviving_panel = next(
                panel for panel in app.panel_widgets() if panel.group_id == surviving_id
            )
            default_panel = next(
                panel for panel in app.panel_widgets() if panel.group_id == "group-default"
            )
            inside_global = surviving_panel.mapToGlobal(
                QPoint(surviving_panel.width() // 2, surviving_panel.height() // 2)
            )
            simulate_header_drag_release_at_global_point(default_panel, inside_global)
            type(self).app.processEvents()

            self.assertEqual(app.panel.group_id, surviving_id)
            app.panel.activate_tab("tab-folders")
            app.detach_tab_to_new_group("tab-folders", PanelGeometry(0.62, 0.22, 0.28, 0.42))
            type(self).app.processEvents()

            ephemeral_id = app.model.tab("tab-folders").group_id
            ephemeral_panel = next(
                panel for panel in app.panel_widgets() if panel.group_id == ephemeral_id
            )
            QTest.mouseClick(ephemeral_panel.delete_button, Qt.MouseButton.LeftButton)
            type(self).app.processEvents()

            self.assertEqual(len(app.model.config.panel_groups), 1)
            self.assertEqual(app.model.config.panel_groups[0].id, surviving_id)
            self.assertEqual(len(app.panel_widgets()), 1)
            self.assertIs(app.panel, surviving_panel)
            self.assertNotIn(ephemeral_id, app._panels)

    def test_external_ref_with_override_is_not_restorable_for_auto_handler(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            appdata_root = root / "appdata"
            desktop = root / "desktop"
            outside = root / "outside"
            desktop.mkdir()
            outside.mkdir()
            source = outside / "linked.weird"
            source.write_text("keep", encoding="utf-8")
            store = ConfigurationStore(appdata_root / "DesktopCleaner" / "config.json")
            config = build_default_configuration(desktop)
            tab_id = "tab-documents"
            key = canonical_key(source)
            config.external_refs.append(
                ItemRef(
                    id="external-test",
                    source_kind="external",
                    canonical_path=str(source.resolve()),
                    target_tab_id=tab_id,
                )
            )
            config.manual_overrides.append(ManualOverride(key, tab_id))
            app = DesktopCleanerApplication(config, store=store)
            app.show()
            app.panel.activate_tab(tab_id)
            app.refresh()
            type(self).app.processEvents()

            self.assertIn(source.resolve(), app.panel.item_grid.entry_paths())
            self.assertEqual(
                app._restorable_paths_for_tab(
                    [entry for entry in app.panel.item_grid._entries],
                    tab_id,
                ),
                set(),
            )

    def test_manual_override_restore_handler_returns_item_to_automatic_tab(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            appdata_root = root / "appdata"
            desktop = root / "desktop"
            desktop.mkdir()
            photo = desktop / "photo.png"
            photo.write_text("img-bytes", encoding="utf-8")
            before = photo.read_text(encoding="utf-8")
            store = ConfigurationStore(appdata_root / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(build_default_configuration(desktop), store=store)
            app.show()
            type(self).app.processEvents()

            app.panel.activate_tab("tab-documents")
            app.handle_paths_dropped([photo], "tab-documents")
            type(self).app.processEvents()

            self.assertEqual(len(app.model.config.manual_overrides), 1)
            self.assertEqual(classify_path(photo, app.model.config), "tab-documents")
            app.panel.activate_tab("tab-documents")
            app.refresh()
            type(self).app.processEvents()
            self.assertIn(photo.resolve(), app.panel.item_grid.entry_paths())

            app._on_restore_auto_requested(photo)
            type(self).app.processEvents()

            self.assertEqual(app.model.config.manual_overrides, [])
            self.assertEqual(classify_path(photo, app.model.config), "tab-images")

            app.panel.activate_tab("tab-images")
            app.refresh()
            type(self).app.processEvents()
            self.assertIn(photo.resolve(), app.panel.item_grid.entry_paths())

            app.panel.activate_tab("tab-documents")
            app.refresh()
            type(self).app.processEvents()
            self.assertNotIn(photo.resolve(), app.panel.item_grid.entry_paths())

            self.assertTrue(store.path.is_file())
            payload = json.loads(store.path.read_text(encoding="utf-8"))
            self.assertEqual(payload.get("manual_overrides", []), [])
            self.assertEqual(store.path.name, "config.json")
            self.assertEqual(photo.read_text(encoding="utf-8"), before)

    def test_one_click_organize_reapplies_rules_without_touching_files(self) -> None:
        from desktop_tidy.application import ensure_application

        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            root = Path(tmp)
            desktop = root / "desktop"
            desktop.mkdir()
            photo = desktop / "photo.png"
            photo.write_text("img-bytes", encoding="utf-8")
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(build_default_configuration(desktop), store=store)
            ensure_application()

            app.show()
            type(self).app.processEvents()

            app.panel.activate_tab("tab-documents")
            app.handle_paths_dropped([photo], "tab-documents")
            type(self).app.processEvents()

            self.assertEqual(classify_path(photo, app.model.config), "tab-documents")
            self.assertEqual(len(app.model.config.manual_overrides), 1)

            QTest.mouseClick(app.panel.organize_button, Qt.MouseButton.LeftButton)
            type(self).app.processEvents()

            self.assertEqual(app.model.config.manual_overrides, [])
            self.assertEqual(classify_path(photo, app.model.config), "tab-images")
            self.assertTrue(photo.is_file())
            self.assertEqual(photo.read_text(encoding="utf-8"), "img-bytes")
            self.assertTrue(store.path.is_file())
            payload = json.loads(store.path.read_text(encoding="utf-8"))
            self.assertEqual(payload.get("manual_overrides", []), [])
            self.assertEqual(store.path.name, "config.json")

    def test_new_desktop_items_show_in_other_until_one_click_organize(self) -> None:
        from desktop_tidy.application import ensure_application

        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            root = Path(tmp)
            desktop = root / "desktop"
            desktop.mkdir()
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(build_default_configuration(desktop), store=store)
            ensure_application()

            app.show()
            type(self).app.processEvents()

            photo = desktop / "fresh.png"
            photo.write_text("img-bytes", encoding="utf-8")
            changes = app.index.rescan()
            app._on_desktop_changed(changes)
            type(self).app.processEvents()

            app.panel.activate_tab("tab-other")
            app.refresh()
            type(self).app.processEvents()
            self.assertIn(photo.resolve(), app.panel.item_grid.entry_paths())
            self.assertEqual(classify_path(photo, app.model.config), "tab-other")

            QTest.mouseClick(app.panel.organize_button, Qt.MouseButton.LeftButton)
            type(self).app.processEvents()

            self.assertEqual(classify_path(photo, app.model.config), "tab-images")
            app.panel.activate_tab("tab-images")
            app.refresh()
            type(self).app.processEvents()
            self.assertIn(photo.resolve(), app.panel.item_grid.entry_paths())
            app.panel.activate_tab("tab-other")
            app.refresh()
            type(self).app.processEvents()
            self.assertNotIn(photo.resolve(), app.panel.item_grid.entry_paths())
            self.assertEqual(photo.read_text(encoding="utf-8"), "img-bytes")

    def test_about_to_quit_saves_latest_panel_geometry(self) -> None:
        from desktop_tidy.application import ensure_application

        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(build_default_configuration(desktop), store=store)
            ensure_application()
            app.show()
            type(self).app.processEvents()

            app.panel.resize(520, 360)
            app.panel.move(120, 90)
            type(self).app.processEvents()
            app._on_about_to_quit()

            self.assertTrue(store.path.is_file())
            payload = json.loads(store.path.read_text(encoding="utf-8"))
            geometry = payload["panel_groups"][0]["geometry"]
            self.assertGreater(geometry["rw"], 0.0)
            self.assertGreater(geometry["rh"], 0.0)
            self.assertGreaterEqual(geometry["rx"], 0.0)
            self.assertGreaterEqual(geometry["ry"], 0.0)
            self.assertEqual(store.path.name, "config.json")

    def test_ctrl_wheel_icon_size_change_persists_to_application_config(self) -> None:
        from desktop_tidy.application import ensure_application

        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(build_default_configuration(desktop), store=store)
            ensure_application()
            app.show()
            type(self).app.processEvents()
            before = app.model.group("group-default").appearance.item_icon_size

            send_ctrl_wheel(app.panel.item_grid, 120)

            self.assertGreater(
                app.model.group("group-default").appearance.item_icon_size,
                before,
            )
            payload = json.loads(store.path.read_text(encoding="utf-8"))
            self.assertEqual(
                payload["panel_groups"][0]["appearance"]["item_icon_size"],
                app.model.group("group-default").appearance.item_icon_size,
            )

    def test_ctrl_wheel_on_one_panel_does_not_reload_show_or_refresh_other_panels(self) -> None:
        from desktop_tidy.application import ensure_application

        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            for name in ("one.pdf", "two.png"):
                (desktop / name).write_text("x", encoding="utf-8")
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(build_default_configuration(desktop), store=store)
            ensure_application()
            app.show()
            app.detach_tab_to_new_group(
                "tab-documents",
                PanelGeometry(rx=0.45, ry=0.20, rw=0.30, rh=0.35),
            )
            type(self).app.processEvents()
            primary = app.panel
            secondary = next(
                panel for panel in app.panel_widgets() if panel.group_id != primary.group_id
            )
            calls = {"reload": 0, "show": 0, "set_entries": 0}
            original_reload = secondary.reload_from_model
            original_show = secondary.show
            original_set_entries = secondary.item_grid.set_entries

            def record_reload():
                calls["reload"] += 1
                original_reload()

            def record_show():
                calls["show"] += 1
                original_show()

            def record_set_entries(*args, **kwargs):
                calls["set_entries"] += 1
                original_set_entries(*args, **kwargs)

            secondary.reload_from_model = record_reload  # type: ignore[method-assign]
            secondary.show = record_show  # type: ignore[method-assign]
            secondary.item_grid.set_entries = record_set_entries  # type: ignore[method-assign]

            send_ctrl_wheel(primary.item_grid, 120)
            type(self).app.processEvents()

            self.assertEqual(calls, {"reload": 0, "show": 0, "set_entries": 0})

    def test_resizing_one_panel_does_not_refresh_other_panel_grids(self) -> None:
        from desktop_tidy.application import ensure_application

        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            for name in ("one.pdf", "two.png", "three.zip"):
                (desktop / name).write_text("x", encoding="utf-8")
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(build_default_configuration(desktop), store=store)
            ensure_application()
            app.show()
            app.detach_tab_to_new_group(
                "tab-documents",
                PanelGeometry(rx=0.45, ry=0.20, rw=0.30, rh=0.35),
            )
            type(self).app.processEvents()
            primary = app.panel
            secondary = next(
                panel for panel in app.panel_widgets() if panel.group_id != primary.group_id
            )
            rebuilt = QSignalSpy(secondary.item_grid.cells_rebuilt)

            start = primary.mapToGlobal(QPoint(primary.width() - 2, primary.height() // 2))
            primary._begin_resize_gesture(_ResizeRegion.RIGHT, start)
            primary._update_resize_gesture(start + QPoint(90, 0))
            primary._finish_resize_gesture()
            type(self).app.processEvents()

            self.assertEqual(rebuilt.count(), 0)
            self.assertTrue(store.path.is_file())

    def test_resizing_one_panel_does_not_reload_show_or_set_entries_on_other_panels(self) -> None:
        from desktop_tidy.application import ensure_application

        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            for name in ("one.pdf", "two.png", "three.zip"):
                (desktop / name).write_text("x", encoding="utf-8")
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(build_default_configuration(desktop), store=store)
            ensure_application()
            app.show()
            app.detach_tab_to_new_group(
                "tab-documents",
                PanelGeometry(rx=0.45, ry=0.20, rw=0.30, rh=0.35),
            )
            type(self).app.processEvents()
            primary = app.panel
            secondary = next(
                panel for panel in app.panel_widgets() if panel.group_id != primary.group_id
            )
            calls = {"reload": 0, "show": 0, "set_entries": 0}
            original_reload = secondary.reload_from_model
            original_show = secondary.show
            original_set_entries = secondary.item_grid.set_entries

            def record_reload():
                calls["reload"] += 1
                original_reload()

            def record_show():
                calls["show"] += 1
                original_show()

            def record_set_entries(*args, **kwargs):
                calls["set_entries"] += 1
                original_set_entries(*args, **kwargs)

            secondary.reload_from_model = record_reload  # type: ignore[method-assign]
            secondary.show = record_show  # type: ignore[method-assign]
            secondary.item_grid.set_entries = record_set_entries  # type: ignore[method-assign]

            start = primary.mapToGlobal(QPoint(primary.width() - 2, primary.height() // 2))
            primary._begin_resize_gesture(_ResizeRegion.RIGHT, start)
            primary._update_resize_gesture(start + QPoint(90, 0))
            primary._finish_resize_gesture()
            type(self).app.processEvents()

            self.assertEqual(calls, {"reload": 0, "show": 0, "set_entries": 0})

    def test_resizing_one_panel_does_not_update_other_panel_snap_targets(self) -> None:
        from desktop_tidy.application import ensure_application

        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(build_default_configuration(desktop), store=store)
            ensure_application()
            app.show()
            app.detach_tab_to_new_group(
                "tab-documents",
                PanelGeometry(rx=0.45, ry=0.20, rw=0.30, rh=0.35),
            )
            type(self).app.processEvents()
            primary = app.panel
            secondary = next(
                panel for panel in app.panel_widgets() if panel.group_id != primary.group_id
            )
            calls = {"secondary": 0}
            original_set_snap_rects = secondary.set_snap_rects

            def record_secondary_snap_rects(rects):
                calls["secondary"] += 1
                original_set_snap_rects(rects)

            secondary.set_snap_rects = record_secondary_snap_rects  # type: ignore[method-assign]

            start = primary.mapToGlobal(QPoint(primary.width() - 2, primary.height() // 2))
            primary._begin_resize_gesture(_ResizeRegion.RIGHT, start)
            primary._update_resize_gesture(start + QPoint(90, 0))
            primary._finish_resize_gesture()
            type(self).app.processEvents()

            self.assertEqual(calls["secondary"], 0)

    def test_starting_panel_resize_refreshes_only_that_panel_snap_targets(self) -> None:
        from desktop_tidy.application import ensure_application

        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(build_default_configuration(desktop), store=store)
            ensure_application()
            app.show()
            app.detach_tab_to_new_group(
                "tab-documents",
                PanelGeometry(rx=0.45, ry=0.20, rw=0.30, rh=0.35),
            )
            type(self).app.processEvents()
            primary = app.panel
            secondary = next(
                panel for panel in app.panel_widgets() if panel.group_id != primary.group_id
            )
            calls = {"primary": 0, "secondary": 0}
            original_primary = primary.set_snap_rects
            original_secondary = secondary.set_snap_rects

            def record_primary(rects):
                calls["primary"] += 1
                original_primary(rects)

            def record_secondary(rects):
                calls["secondary"] += 1
                original_secondary(rects)

            primary.set_snap_rects = record_primary  # type: ignore[method-assign]
            secondary.set_snap_rects = record_secondary  # type: ignore[method-assign]

            start = primary.mapToGlobal(QPoint(primary.width() - 2, primary.height() // 2))
            primary._begin_resize_gesture(_ResizeRegion.RIGHT, start)

            self.assertEqual(calls["primary"], 1)
            self.assertEqual(calls["secondary"], 0)

    def test_desktop_cleaner_application_disables_quit_on_last_window_closed(self) -> None:
        """DesktopCleanerApplication must set quitOnLastWindowClosed(False) to survive settings close."""
        app = QApplication.instance()
        self.assertIsNotNone(app)

        from desktop_tidy.application import ensure_application

        ensure_application()
        app = QApplication.instance()
        self.assertIsNotNone(app)

        self.assertFalse(
            app.quitOnLastWindowClosed(),
            "preview must disable quit-on-last-window-closed via ensure_application",
        )

    def test_settings_can_add_clock_widget_panel_from_preview_card(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(
                build_default_configuration(desktop),
                store=store,
                history_store=LayoutHistoryStore(Path(tmp) / "layout-history.json"),
            )
            app._show_settings(app.panel.group_id)
            settings = app._settings_window
            self.assertIsNotNone(settings)

            settings.add_widget_panel_requested.emit("clock")
            type(self).app.processEvents()

            widget_tabs = [
                tab for tab in app.model.config.panel_tabs if tab.content_kind == "widget"
            ]
            self.assertEqual([tab.widget_type for tab in widget_tabs], ["clock"])
            widget_tab_ids = {tab.id for tab in widget_tabs}
            self.assertTrue(
                any(
                    len(group.tab_ids) == 1 and group.active_tab_id in widget_tab_ids
                    for group in app.model.config.panel_groups
                )
            )
            payload = json.loads(store.path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], 4)

    def test_layout_history_restore_replaces_panel_layout_without_touching_sources(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            source = desktop / "note.txt"
            source.write_text("original", encoding="utf-8")
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            history = LayoutHistoryStore(Path(tmp) / "layout-history.json")
            config = build_default_configuration(desktop)
            config.panel_groups[0].geometry.rw = 0.44
            snapshot = history.push(config, "before-resize")
            self.assertIsNotNone(snapshot)
            app = DesktopCleanerApplication(
                build_default_configuration(desktop),
                store=store,
                history_store=history,
            )

            app._on_history_restore_requested(snapshot.id)

            self.assertAlmostEqual(app.model.config.panel_groups[0].geometry.rw, 0.44)
            self.assertEqual(source.read_text(encoding="utf-8"), "original")
            self.assertEqual(
                json.loads(store.path.read_text(encoding="utf-8"))["schema_version"],
                4,
            )

    def test_settings_window_close_does_not_quit_or_hide_panel(self) -> None:
        """Closing settings must not exit the app or hide the panel."""
        from desktop_tidy.application import ensure_application

        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            app = DesktopCleanerApplication(build_default_configuration(desktop))
            ensure_application()

            app.show()
            type(self).app.processEvents()

            self.assertTrue(app.panel.isVisible())
            app._show_settings(app.panel.group_id)
            settings = app._settings_window
            self.assertIsNotNone(settings)
            self.assertTrue(settings.isVisible())

            settings.close()
            type(self).app.processEvents()

            self.assertFalse(settings.isVisible())
            self.assertTrue(
                app.panel.isVisible(),
                "panel must remain visible after settings is closed",
            )

    def test_settings_reopen_reuses_same_window_instance(self) -> None:
        """Reopening settings via ... must reuse or refresh the existing window."""
        from desktop_tidy.application import ensure_application

        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            app = DesktopCleanerApplication(build_default_configuration(desktop))
            ensure_application()

            app.show()
            type(self).app.processEvents()

            app._show_settings(app.panel.group_id)
            first = app._settings_window
            self.assertIsNotNone(first)
            first.close()
            type(self).app.processEvents()

            app._show_settings(app.panel.group_id)
            second = app._settings_window
            self.assertIsNotNone(second)
            self.assertIs(
                second,
                first,
                "settings reopen must reuse the same SettingsWindow instance",
            )

    def test_double_click_item_calls_open_item_with_correct_path(self) -> None:
        from desktop_tidy.application import ensure_application
        from tests.test_qt_item_grid import _grid_item_buttons

        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            root = Path(tmp)
            desktop = root / "desktop"
            desktop.mkdir()
            source = root / "outside" / "photo.png"
            source.parent.mkdir()
            source.write_text("img", encoding="utf-8")
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(build_default_configuration(desktop), store=store)
            ensure_application()

            app.show()
            type(self).app.processEvents()

            app.panel.activate_tab("tab-images")
            app.handle_paths_dropped([source], "tab-images")
            app.refresh()
            type(self).app.processEvents()

            buttons = _grid_item_buttons(app.panel.item_grid)
            self.assertTrue(buttons, "grid must have at least one item button")

            with patch("desktop_tidy.application.open_item") as mock_open:
                QTest.mouseDClick(buttons[0], Qt.MouseButton.LeftButton)
                type(self).app.processEvents()

            mock_open.assert_called_once()
            called_path = mock_open.call_args[0][0]
            self.assertEqual(called_path.resolve(), source.resolve())

    def test_single_click_item_does_not_call_open_item(self) -> None:
        from desktop_tidy.application import ensure_application
        from tests.test_qt_item_grid import _grid_item_buttons

        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            root = Path(tmp)
            desktop = root / "desktop"
            desktop.mkdir()
            source = root / "outside" / "doc.txt"
            source.parent.mkdir()
            source.write_text("text", encoding="utf-8")
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(build_default_configuration(desktop), store=store)
            ensure_application()

            app.show()
            type(self).app.processEvents()

            app.panel.activate_tab("tab-documents")
            app.handle_paths_dropped([source], "tab-documents")
            app.refresh()
            type(self).app.processEvents()

            buttons = _grid_item_buttons(app.panel.item_grid)
            self.assertTrue(buttons, "grid must have at least one item button")

            with patch("desktop_tidy.application.open_item") as mock_open:
                QTest.mouseClick(buttons[0], Qt.MouseButton.LeftButton)
                type(self).app.processEvents()

            mock_open.assert_not_called()

    def test_double_click_external_ref_calls_open_item(self) -> None:
        from desktop_tidy.application import ensure_application
        from tests.test_qt_item_grid import _grid_item_buttons

        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            root = Path(tmp)
            desktop = root / "desktop"
            outside = root / "outside"
            desktop.mkdir()
            outside.mkdir()
            source = outside / "linked.weird"
            source.write_text("keep", encoding="utf-8")
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(build_default_configuration(desktop), store=store)
            ensure_application()

            app.handle_paths_dropped([source], "tab-documents")
            app.show()
            app.panel.activate_tab("tab-documents")
            app.refresh()
            type(self).app.processEvents()

            buttons = _grid_item_buttons(app.panel.item_grid)
            self.assertTrue(buttons, "grid must have at least one item button")

            with patch("desktop_tidy.application.open_item") as mock_open:
                QTest.mouseDClick(buttons[0], Qt.MouseButton.LeftButton)
                type(self).app.processEvents()

            mock_open.assert_called_once()
            called_path = mock_open.call_args[0][0]
            self.assertEqual(called_path.resolve(), source.resolve())

    def test_open_item_exception_does_not_crash_or_alter_application_config(self) -> None:
        from desktop_tidy.application import ensure_application
        from tests.test_qt_item_grid import _grid_item_buttons

        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            root = Path(tmp)
            desktop = root / "desktop"
            desktop.mkdir()
            source = root / "outside" / "photo.png"
            source.parent.mkdir()
            source.write_text("img", encoding="utf-8")
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(build_default_configuration(desktop), store=store)
            ensure_application()

            app.show()
            type(self).app.processEvents()

            app.panel.activate_tab("tab-images")
            app.handle_paths_dropped([source], "tab-images")
            app.refresh()
            type(self).app.processEvents()

            buttons = _grid_item_buttons(app.panel.item_grid)
            self.assertTrue(buttons, "grid must have at least one item button")

            config_mtime_before = store.path.stat().st_mtime if store.path.is_file() else None
            source_content_before = source.read_text(encoding="utf-8")
            self.assertEqual(store.path.name, "config.json")

            with patch(
                "desktop_tidy.application.open_item",
                side_effect=OSError("simulated launch failure"),
            ) as mock_open:
                QTest.mouseDClick(buttons[0], Qt.MouseButton.LeftButton)
                type(self).app.processEvents()

            mock_open.assert_called_once()
            self.assertEqual(source.read_text(encoding="utf-8"), source_content_before)
            self.assertEqual(list(desktop.iterdir()), [])
            self.assertTrue(store.path.exists())
            if config_mtime_before is not None:
                self.assertEqual(
                    store.path.stat().st_mtime,
                    config_mtime_before,
                    "config.json must not be rewritten after a bare open failure",
                )


if __name__ == "__main__":
    unittest.main()
