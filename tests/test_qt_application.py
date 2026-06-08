from __future__ import annotations

import json
import os
import time
import unittest
from copy import deepcopy
from datetime import datetime, timedelta
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
    arrange_entries_for_tab,
    resolve_startup_executable_path,
    visible_entries_for_active_tab,
)
from desktop_tidy.domain.classification import classify_path
from desktop_tidy.domain.defaults import build_default_configuration
from desktop_tidy.domain.classification import canonical_key
from desktop_tidy.domain.models import ItemGroup, ItemRef, ManualOverride, PanelGeometry
from desktop_tidy.persistence.config_store import ConfigurationStore
from desktop_tidy.persistence.layout_history import LayoutHistoryStore
from desktop_tidy.services.desktop_index import DesktopIndex
from desktop_tidy.services.updates import DownloadResult, UpdateInfo
from desktop_tidy.ui.settings_window import SettingsWindow
from tests.test_qt_item_grid import close_desktop_logger_handlers, send_ctrl_wheel
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


class FakeUpdateService:
    def __init__(self, updates_dir: Path) -> None:
        self.updates_dir = updates_dir
        self.info = UpdateInfo(
            current_version="1.0.12",
            latest_version="1.0.13",
            release_url="https://release",
            asset_url="https://asset/DesktopCleaner.exe",
            available=True,
        )
        self.download_result = DownloadResult(
            version="1.0.13",
            path=updates_dir / "DesktopCleaner-v1.0.13.exe",
        )
        self.calls: list[str] = []

    def check_latest(self) -> UpdateInfo:
        self.calls.append("check")
        return self.info

    def download(self, update: UpdateInfo) -> DownloadResult:
        self.calls.append(f"download:{update.latest_version}")
        self.download_result.path.parent.mkdir(parents=True, exist_ok=True)
        self.download_result.path.write_bytes(b"exe")
        return self.download_result

    def prepare_replace(self, downloaded_exe: Path, current_exe: Path) -> Path:
        self.calls.append(f"replace:{downloaded_exe.name}:{current_exe.name}")
        script = self.updates_dir / "replace-and-restart.cmd"
        script.write_text("echo replace", encoding="utf-8")
        return script


class FakeWeatherService:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[str] = []

    def fetch_current(self, city: str):
        self.calls.append(city)
        if self.fail:
            raise RuntimeError("weather unavailable")
        return SimpleNamespace(
            city=city.title(),
            summary="Cloudy · 18°C",
            provider="fake",
            temperature_c=18.0,
            condition="Cloudy",
        )


class SlowWeatherService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def fetch_current(self, city: str):
        self.calls.append(city)
        time.sleep(0.25)
        return SimpleNamespace(
            city=city.title(),
            summary="Cloudy · 18°C",
            provider="slow-fake",
            temperature_c=18.0,
            condition="Cloudy",
        )


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
        self.messages: list[tuple[str, str]] = []

    def show(self) -> None:
        self.shown = True

    def hide(self) -> None:
        self.hidden = True

    def show_message(self, title: str, message: str) -> None:
        self.last_message = (title, message)
        self.messages.append((title, message))


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

    def _wait_until(self, condition, *, timeout_ms: int = 1000) -> bool:
        deadline = time.perf_counter() + timeout_ms / 1000
        while time.perf_counter() < deadline:
            if condition():
                return True
            type(self).app.processEvents()
            QTest.qWait(10)
        type(self).app.processEvents()
        return bool(condition())

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

    def test_startup_creates_and_activates_single_home_tab(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")

            app = DesktopCleanerApplication(build_default_configuration(desktop), store=store)
            app.show()
            type(self).app.processEvents()

            home_tabs = [
                tab
                for tab in app.model.config.panel_tabs
                if tab.content_kind == "widget" and tab.widget_type == "home"
            ]
            self.assertEqual(len(home_tabs), 1)
            home = home_tabs[0]
            self.assertEqual(app.model.group(home.group_id).active_tab_id, home.id)
            self.assertEqual(app.panel.active_tab_id, home.id)
            self.assertFalse(app.panel.item_grid.isVisible())

    def test_opening_item_records_local_recent_without_showing_on_home_dashboard(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            target = desktop / "paper.pdf"
            target.write_text("pdf", encoding="utf-8")
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(build_default_configuration(desktop), store=store)

            with patch("desktop_tidy.application.open_item") as opened:
                app._on_item_activated(target)

            opened.assert_called_once_with(target)
            recent = app.recent_items_store.snapshot(limit=5)
            self.assertEqual(recent[0]["name"], "paper.pdf")
            home = app.model.home_tab()
            assert home is not None
            self.assertEqual(home.widget_settings["recent_items"], [])

    def test_home_dashboard_reads_windows_recent_items_on_startup(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            desktop = root / "desktop"
            desktop.mkdir()
            recent_dir = root / "Recent"
            recent_dir.mkdir()
            target = root / "windows-report.docx"
            target.write_text("doc", encoding="utf-8")
            shortcut = recent_dir / "windows-report.docx.url"
            shortcut.write_text(
                "[InternetShortcut]\nURL=" + target.resolve().as_uri() + "\n",
                encoding="utf-8",
            )
            store = ConfigurationStore(root / "DesktopCleaner" / "config.json")

            with patch("desktop_tidy.application.default_windows_recent_dir", return_value=recent_dir):
                app = DesktopCleanerApplication(build_default_configuration(desktop), store=store)

            home = app.model.home_tab()
            assert home is not None
            self.assertEqual(
                home.widget_settings["recent_items"][0],
                {
                    "name": "windows-report.docx",
                    "path": str(target.resolve()),
                    "kind": "file",
                    "source": "windows",
                },
            )

    def test_home_dashboard_refreshes_windows_recent_when_home_tab_is_activated(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            desktop = root / "desktop"
            desktop.mkdir()
            recent_dir = root / "Recent"
            recent_dir.mkdir()
            store = ConfigurationStore(root / "DesktopCleaner" / "config.json")

            with patch("desktop_tidy.application.default_windows_recent_dir", return_value=recent_dir):
                app = DesktopCleanerApplication(build_default_configuration(desktop), store=store)

            home = app.model.home_tab()
            assert home is not None
            other_tab = next(tab for tab in app.model.config.panel_tabs if tab.id != home.id)
            app.panel.activate_tab(other_tab.id)
            type(self).app.processEvents()

            target = root / "after-start.pdf"
            target.write_text("pdf", encoding="utf-8")
            shortcut = recent_dir / "after-start.pdf.url"
            shortcut.write_text(
                "[InternetShortcut]\nURL=" + target.resolve().as_uri() + "\n",
                encoding="utf-8",
            )

            app.panel.activate_tab(home.id)
            type(self).app.processEvents()

            self.assertEqual(home.widget_settings["recent_items"][0]["name"], "after-start.pdf")
            self.assertEqual(home.widget_settings["recent_items"][0]["path"], str(target.resolve()))

    def test_home_recent_refresh_request_reads_windows_recent(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            desktop = root / "desktop"
            desktop.mkdir()
            recent_dir = root / "Recent"
            recent_dir.mkdir()
            store = ConfigurationStore(root / "DesktopCleaner" / "config.json")

            with patch("desktop_tidy.application.default_windows_recent_dir", return_value=recent_dir):
                app = DesktopCleanerApplication(build_default_configuration(desktop), store=store)

            home = app.model.home_tab()
            assert home is not None
            self.assertEqual(home.widget_settings["recent_items"], [])

            target = root / "manual-refresh.docx"
            target.write_text("doc", encoding="utf-8")
            shortcut = recent_dir / "manual-refresh.docx.url"
            shortcut.write_text(
                "[InternetShortcut]\nURL=" + target.resolve().as_uri() + "\n",
                encoding="utf-8",
            )

            with patch("desktop_tidy.application.default_windows_recent_dir", return_value=recent_dir):
                app._on_widget_recent_refresh_requested()

            self.assertEqual(home.widget_settings["recent_items"][0]["name"], "manual-refresh.docx")
            self.assertEqual(home.widget_settings["recent_items"][0]["path"], str(target.resolve()))

    def test_home_recent_clear_request_removes_local_records_but_keeps_windows_recent(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            desktop = root / "desktop"
            desktop.mkdir()
            recent_dir = root / "Recent"
            recent_dir.mkdir()
            store = ConfigurationStore(root / "DesktopCleaner" / "config.json")

            with patch("desktop_tidy.application.default_windows_recent_dir", return_value=recent_dir):
                app = DesktopCleanerApplication(build_default_configuration(desktop), store=store)

            local_target = root / "local.pdf"
            local_target.write_text("pdf", encoding="utf-8")
            app.recent_items_store.record(local_target)
            app._sync_home_dashboard_settings()
            home = app.model.home_tab()
            assert home is not None
            self.assertEqual(home.widget_settings["recent_items"], [])

            windows_target = root / "windows.docx"
            windows_target.write_text("doc", encoding="utf-8")
            shortcut = recent_dir / "windows.docx.url"
            shortcut.write_text(
                "[InternetShortcut]\nURL=" + windows_target.resolve().as_uri() + "\n",
                encoding="utf-8",
            )

            app._on_widget_recent_clear_requested()

            self.assertEqual(app.recent_items_store.snapshot(limit=5), [])
            self.assertEqual(home.widget_settings["recent_items"][0]["name"], "windows.docx")
            self.assertEqual(home.widget_settings["recent_items"][0]["source"], "windows")

    def test_home_url_request_opens_browser_without_recent_file_record(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(build_default_configuration(desktop), store=store)

            with patch("desktop_tidy.application.open_url") as opened:
                app._on_widget_url_open_requested("https://example.com")

            opened.assert_called_once_with("https://example.com")
            self.assertEqual(app.recent_items_store.snapshot(), [])

    def test_home_widget_settings_change_persists_module_configuration(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            target = desktop / "paper.pdf"
            target.write_text("pdf", encoding="utf-8")
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(build_default_configuration(desktop), store=store)
            home = app.model.home_tab()
            assert home is not None
            app.recent_items_store.record(target)
            app._sync_home_dashboard_settings()

            app._on_widget_settings_changed(
                home.id,
                {
                    "modules": ["recent", "calendar"],
                    "module_settings": {"calendar": {"compact": True}},
                    "reduced_motion": True,
                },
            )
            app._flush_deferred_save()

            self.assertEqual(home.widget_settings["modules"], ["recent", "calendar"])
            self.assertEqual(home.widget_settings["module_settings"]["calendar"], {"compact": True})
            self.assertTrue(home.widget_settings["reduced_motion"])
            self.assertEqual(home.widget_settings["recent_items"], [])
            payload = json.loads(store.path.read_text(encoding="utf-8"))
            saved_home = next(tab for tab in payload["panel_tabs"] if tab["id"] == home.id)
            self.assertEqual(saved_home["widget_settings"]["modules"], ["recent", "calendar"])

    def test_due_home_reminder_notifies_once_and_ignores_future_items(self) -> None:
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
            home = app.model.home_tab()
            assert home is not None
            today = datetime(2026, 6, 7, 9, 5)
            tomorrow = today.date() + timedelta(days=1)
            home.widget_settings["reminders"] = [
                {"date": today.date().isoformat(), "text": "09:00 standup"},
                {"date": today.date().isoformat(), "text": "23:59 later"},
                {"date": tomorrow.isoformat(), "text": "08:00 tomorrow"},
                {"date": today.date().isoformat(), "text": "untimed note"},
            ]

            app._check_due_home_reminders(today)
            app._check_due_home_reminders(today)

            self.assertEqual(tray.messages, [("日程提醒", "09:00 standup")])
            self.assertEqual(
                home.widget_settings["notified_reminders"],
                [f"{today.date().isoformat()}|09:00 standup"],
            )

    def test_due_home_reminder_ignores_done_items(self) -> None:
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
            home = app.model.home_tab()
            assert home is not None
            now = datetime(2026, 6, 7, 9, 5)
            home.widget_settings["module_settings"] = {
                "schedule": {
                    "reminders": [
                        {
                            "date": now.date().isoformat(),
                            "text": "09:00 already handled",
                            "done": True,
                        },
                    ],
                },
            }

            app._check_due_home_reminders(now)

            self.assertEqual(tray.messages, [])
            self.assertNotIn("notified_reminders", home.widget_settings)

    def test_due_home_reminder_reads_schedule_module_settings(self) -> None:
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
            home = app.model.home_tab()
            assert home is not None
            now = datetime(2026, 6, 7, 9, 5)
            home.widget_settings["module_settings"] = {
                "schedule": {
                    "reminders": [
                        {"date": now.date().isoformat(), "text": "09:00 module standup"},
                    ],
                },
            }

            app._check_due_home_reminders(now)

            self.assertEqual(tray.messages, [("日程提醒", "09:00 module standup")])
            self.assertEqual(
                home.widget_settings["notified_reminders"],
                [f"{now.date().isoformat()}|09:00 module standup"],
            )

    def test_due_home_reminder_accepts_date_prefix_before_time(self) -> None:
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
            home = app.model.home_tab()
            assert home is not None
            now = datetime(2026, 6, 7, 9, 5)
            home.widget_settings["reminders"] = [
                {"date": now.date().isoformat(), "text": "06-07 09:00 standup"},
            ]

            app._check_due_home_reminders(now)

            self.assertEqual(tray.messages, [("日程提醒", "06-07 09:00 standup")])

    def test_update_check_and_download_are_exposed_through_settings(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            update_service = FakeUpdateService(Path(tmp) / "updates")
            app = DesktopCleanerApplication(
                build_default_configuration(desktop),
                store=store,
                update_service=update_service,
            )

            app._show_settings(app.panel.group_id)
            assert app._settings_window is not None
            window = app._settings_window
            window._update_check_button.click()
            window._update_download_button.click()

            self.assertEqual(update_service.calls, ["check", "download:1.0.13"])
            self.assertIn("1.0.13", window._other_page_text())
            self.assertIn("下载完成", window._update_status_label.text())
            self.assertFalse(window._update_replace_button.isEnabled())

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

            self.assertEqual(takeover.calls, [("restore", None), ("detach", None)])
            self.assertFalse(config.desktop.restore_required)
            self.assertFalse(config.desktop.explorer_icons_hidden)
            payload = json.loads(store.path.read_text(encoding="utf-8"))
            self.assertFalse(payload["desktop"]["restore_required"])
            self.assertFalse(payload["desktop"]["explorer_icons_hidden"])

    def test_abandoned_takeover_recovery_keeps_user_takeover_preference(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            config = build_default_configuration(desktop)
            config.desktop.takeover_enabled = True
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            marker = store.path.parent / "takeover-session.marker"
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text("active\n", encoding="utf-8")
            takeover = FakeTakeoverService()

            app = DesktopCleanerApplication(config, store=store, takeover_service=takeover)
            self.assertFalse(marker.exists())
            app.show()
            type(self).app.processEvents()

            self.assertTrue(config.desktop.takeover_enabled)
            self.assertEqual(
                [name for name, _value in takeover.calls],
                ["restore", "detach", "attach", "hide"],
            )
            self.assertTrue(marker.exists())
            payload = json.loads(store.path.read_text(encoding="utf-8"))
            self.assertTrue(payload["desktop"]["takeover_enabled"])

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
            self.assertTrue(config.desktop.takeover_enabled)
            self.assertFalse(config.desktop.restore_required)
            self.assertFalse(config.desktop.explorer_icons_hidden)
            self.assertFalse(app._takeover_marker.is_active())

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

    def test_settings_restore_desktop_icons_disables_takeover_and_keeps_icons(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            config = build_default_configuration(desktop)
            config.desktop.takeover_enabled = True
            config.desktop.restore_required = True
            config.desktop.explorer_icons_hidden = True
            takeover = FakeTakeoverService()
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(
                config,
                store=store,
                takeover_service=takeover,
            )
            app._takeover_active = True
            app._show_settings(app.panel.group_id)
            assert app._settings_window is not None
            takeover.calls.clear()

            app._settings_window.restore_desktop_requested.emit()

            self.assertEqual(
                [name for name, _value in takeover.calls if name != "visible"],
                ["restore", "detach"],
            )
            self.assertFalse(config.desktop.takeover_enabled)
            self.assertFalse(config.desktop.explorer_icons_hidden)
            self.assertFalse(config.desktop.restore_required)
            payload = json.loads(store.path.read_text(encoding="utf-8"))
            self.assertFalse(payload["desktop"]["takeover_enabled"])

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

    def test_development_startup_path_uses_packaged_exe_not_main_py(self) -> None:
        with TemporaryDirectory() as tmp:
            project_root = Path(tmp)
            packaged = project_root / "dist" / "DesktopCleaner.exe"
            packaged.parent.mkdir()
            packaged.write_bytes(b"exe")

            resolved = resolve_startup_executable_path(
                frozen=False,
                executable=Path(r"D:\Python\python.exe"),
                project_root=project_root,
            )

            self.assertEqual(resolved, packaged.resolve())

    def test_show_reapplies_enabled_startup_preference(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            config = build_default_configuration(desktop)
            config.desktop.startup_enabled = True
            startup = FakeStartupService()
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(config, store=store, startup_service=startup)

            packaged = Path(tmp) / "dist" / "DesktopCleaner.exe"
            with patch(
                "desktop_tidy.application.resolve_startup_executable_path",
                return_value=packaged,
            ):
                app.show()

            self.assertTrue(startup.calls)
            enabled, exe_path = startup.calls[-1]
            self.assertTrue(enabled)
            self.assertEqual(exe_path.name, "DesktopCleaner.exe")

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
                ["restore", "detach", "restore", "detach", "attach", "hide"],
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

    def test_continuous_layout_changes_share_one_history_entry_within_five_minutes(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            desktop = root / "desktop"
            desktop.mkdir()
            store = ConfigurationStore(root / "DesktopCleaner" / "config.json")
            now = datetime(2026, 5, 28, 12, 0, 0)

            def clock() -> datetime:
                return now

            history_store = LayoutHistoryStore(
                root / "DesktopCleaner" / "layout-history.json",
                clock=clock,
            )
            app = DesktopCleanerApplication(
                build_default_configuration(desktop),
                store=store,
                history_store=history_store,
            )

            app.model.config.panel_groups[0].appearance.background_opacity = 0.72
            app.save_with_history("appearance-change")
            first_snapshot = history_store.load()[0]

            now = now + timedelta(minutes=2)
            app.model.config.panel_groups[0].geometry.rx = 0.18
            app.save_with_history("geometry-change")

            now = now + timedelta(minutes=2)
            group = app.model.config.panel_groups[0]
            group.tab_ids = [group.tab_ids[1], group.tab_ids[0], *group.tab_ids[2:]]
            app.save_with_history("tab-reorder")

            snapshots = history_store.load()
            self.assertEqual(len(snapshots), 1)
            self.assertEqual(snapshots[0].id, first_snapshot.id)
            self.assertEqual(snapshots[0].reason, "layout-adjustment")

            now = now + timedelta(minutes=6)
            app.model.config.panel_groups[0].geometry.rx = 0.26
            app.save_with_history("geometry-change")

            self.assertEqual(len(history_store.load()), 2)

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

    def test_visible_entries_deduplicates_scan_and_external_ref(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            desktop = root / "desktop"
            desktop.mkdir()
            photo = desktop / "photo.png"
            photo.write_text("img", encoding="utf-8")
            config = build_default_configuration(desktop)
            config.external_refs.append(
                ItemRef(
                    id="external-dup",
                    source_kind="external",
                    canonical_path=str(photo.resolve()),
                    target_tab_id="tab-images",
                )
            )

            entries = visible_entries_for_active_tab(
                config,
                DesktopIndex(desktop),
                active_tab_id="tab-images",
            )

            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].path.resolve(), photo.resolve())

    def test_visible_entries_hide_duplicate_shortcuts_with_same_target(self) -> None:
        from desktop_tidy.domain.shortcut_identity import item_identity_key

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            user_desktop = root / "user"
            public_desktop = root / "public"
            user_desktop.mkdir()
            public_desktop.mkdir()
            user_link = user_desktop / "终末地.lnk"
            public_link = public_desktop / "终末地.lnk"
            user_link.write_text("a", encoding="utf-8")
            public_link.write_text("b", encoding="utf-8")
            config = build_default_configuration(user_desktop)
            identity = "lnk:c:\\games\\endfield.exe"

            def fake_identity(path: Path) -> str:
                if path.name.casefold() == "终末地.lnk":
                    return identity
                return item_identity_key(path)

            with patch(
                "desktop_tidy.application.item_identity_key",
                side_effect=fake_identity,
            ):
                index = DesktopIndex(user_desktop, extra_desktops=[public_desktop])
                entries = visible_entries_for_active_tab(
                    config,
                    index,
                    active_tab_id="tab-apps",
                )
                endfield_entries = [
                    entry for entry in entries if entry.path.name == "终末地.lnk"
                ]
                self.assertEqual(len(endfield_entries), 1)
                self.assertEqual(endfield_entries[0].path.resolve(), user_link.resolve())

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

    def test_locked_panel_still_allows_item_grid_reorder(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            app = DesktopCleanerApplication(build_default_configuration(desktop))
            app.show()
            type(self).app.processEvents()

            app.panel.activate_tab("tab-folders")
            app.refresh()
            type(self).app.processEvents()

            app.panel.set_locked(True)
            app.refresh()
            type(self).app.processEvents()

            self.assertTrue(app.panel.is_locked)
            self.assertTrue(app.panel.item_grid.reorder_enabled())

    def test_item_dropped_on_tab_switches_active_tab_and_moves_item(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            source = desktop / "game.url"
            source.write_text("url", encoding="utf-8")
            app = DesktopCleanerApplication(build_default_configuration(desktop))
            app.show()
            type(self).app.processEvents()

            app.panel.activate_tab("tab-folders")
            app.refresh()
            type(self).app.processEvents()

            app.panel._on_item_dropped_on_tab_button([source], "tab-apps")
            type(self).app.processEvents()

            self.assertEqual(app.panel.active_tab_id, "tab-apps")
            self.assertEqual(
                app.model.config.manual_overrides[0].target_tab_id,
                "tab-apps",
            )
            self.assertIn(source.resolve(), app.panel.item_grid.entry_paths())

    def test_item_drag_over_tab_switches_preview_to_target_tab(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            folder = desktop / "project"
            folder.mkdir()
            app_link = desktop / "game.url"
            app_link.write_text("url", encoding="utf-8")
            app = DesktopCleanerApplication(build_default_configuration(desktop))
            app.show()
            type(self).app.processEvents()

            app.panel.activate_tab("tab-folders")
            app.refresh()
            type(self).app.processEvents()

            app.panel._on_item_drag_enter_tab("tab-apps")
            type(self).app.processEvents()

            self.assertEqual(app.panel.active_tab_id, "tab-apps")
            preview_paths = app.panel.item_grid.entry_paths()
            self.assertIn(app_link.resolve(), preview_paths)
            self.assertNotIn(folder.resolve(), preview_paths)

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
                "appearance is global: all panel groups share the same color",
            )
            self.assertEqual(
                app.model.group(secondary_group_id).appearance.background_color,
                saved_color,
            )
            self.assertAlmostEqual(
                app.model.group("group-default").appearance.background_opacity,
                0.33,
            )
            self.assertAlmostEqual(
                app.model.group(secondary_group_id).appearance.background_opacity,
                0.33,
            )
            self.assertEqual(
                app.model.config.appearance_defaults.background_color,
                saved_color,
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
            secondary_group_id = app.model.tab("tab-documents").group_id
            self.assertNotEqual(secondary_group_id, "group-default")
            secondary_group = app.model.group(secondary_group_id)
            # 颜色/透明度是全局外观,所有面板组都应同步生效。
            self.assertEqual(secondary_group.appearance.background_color, "#4B5563")
            self.assertAlmostEqual(
                secondary_group.appearance.background_opacity,
                0.70,
            )
            self.assertAlmostEqual(app.panel.background_opacity, 0.70)
            for panel in app.panel_widgets():
                self.assertAlmostEqual(panel.background_opacity, 0.70)

            QTest.qWait(350)
            payload = json.loads(store.path.read_text(encoding="utf-8"))
            appearances = {
                panel_group["id"]: panel_group["appearance"]
                for panel_group in payload["panel_groups"]
            }
            self.assertEqual(appearances["group-default"]["background_color"], "#4B5563")
            self.assertAlmostEqual(
                appearances["group-default"]["background_opacity"],
                0.70,
            )
            self.assertEqual(
                appearances[secondary_group_id]["background_color"],
                "#4B5563",
            )
            self.assertAlmostEqual(
                appearances[secondary_group_id]["background_opacity"],
                0.70,
            )
            self.assertEqual(
                payload["appearance_defaults"]["background_color"],
                "#4B5563",
            )

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

    def test_one_click_organize_preserves_manual_moves_and_releases_pending(self) -> None:
        from desktop_tidy.application import ensure_application

        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            root = Path(tmp)
            desktop = root / "desktop"
            desktop.mkdir()
            photo = desktop / "photo.png"
            photo.write_text("img-bytes", encoding="utf-8")
            pending = desktop / "fresh.png"
            pending.write_text("new-bytes", encoding="utf-8")
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(build_default_configuration(desktop), store=store)
            ensure_application()

            app.show()
            type(self).app.processEvents()

            app.panel.activate_tab("tab-documents")
            app.handle_paths_dropped([photo], "tab-documents")
            app.model.mark_desktop_items_pending_organize([pending])
            type(self).app.processEvents()

            self.assertEqual(classify_path(photo, app.model.config), "tab-documents")
            self.assertEqual(classify_path(pending, app.model.config), "tab-other")
            self.assertEqual(len(app.model.config.manual_overrides), 2)

            QTest.mouseClick(app.panel.organize_button, Qt.MouseButton.LeftButton)
            type(self).app.processEvents()

            self.assertEqual(len(app.model.config.manual_overrides), 1)
            self.assertEqual(app.model.config.manual_overrides[0].target_tab_id, "tab-documents")
            self.assertEqual(classify_path(photo, app.model.config), "tab-documents")
            self.assertEqual(classify_path(pending, app.model.config), "tab-images")
            self.assertTrue(photo.is_file())
            self.assertEqual(photo.read_text(encoding="utf-8"), "img-bytes")
            self.assertTrue(store.path.is_file())
            payload = json.loads(store.path.read_text(encoding="utf-8"))
            self.assertEqual(len(payload.get("manual_overrides", [])), 1)
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

    def test_lock_toggle_is_lightweight_and_delayed_saved(self) -> None:
        from desktop_tidy.application import ensure_application

        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            (desktop / "one.pdf").write_text("x", encoding="utf-8")
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(build_default_configuration(desktop), store=store)
            ensure_application()
            app.show()
            type(self).app.processEvents()

            calls = {"history": 0, "refresh": 0, "set_entries": 0}
            original_save_with_history = app.save_with_history
            original_refresh = app.refresh
            original_set_entries = app.panel.item_grid.set_entries

            def record_history(*args, **kwargs):
                calls["history"] += 1
                original_save_with_history(*args, **kwargs)

            def record_refresh(*args, **kwargs):
                calls["refresh"] += 1
                original_refresh(*args, **kwargs)

            def record_set_entries(*args, **kwargs):
                calls["set_entries"] += 1
                original_set_entries(*args, **kwargs)

            app.save_with_history = record_history  # type: ignore[method-assign]
            app.refresh = record_refresh  # type: ignore[method-assign]
            app.panel.item_grid.set_entries = record_set_entries  # type: ignore[method-assign]

            QTest.mouseClick(app.panel.lock_button, Qt.MouseButton.LeftButton)
            type(self).app.processEvents()

            self.assertEqual(calls, {"history": 0, "refresh": 0, "set_entries": 0})
            self.assertTrue(app.model.group("group-default").locked)

            QTest.qWait(650)
            type(self).app.processEvents()

            payload = json.loads(store.path.read_text(encoding="utf-8"))
            self.assertTrue(payload["panel_groups"][0]["locked"])

    def test_tab_switch_refreshes_only_current_panel_without_history(self) -> None:
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
            calls = {"history": 0, "refresh": 0, "primary_entries": 0, "secondary_entries": 0}
            original_history = app.save_with_history
            original_refresh = app.refresh
            original_primary_set_entries = primary.item_grid.set_entries
            original_secondary_set_entries = secondary.item_grid.set_entries

            def record_history(*args, **kwargs):
                calls["history"] += 1
                original_history(*args, **kwargs)

            def record_refresh(*args, **kwargs):
                calls["refresh"] += 1
                original_refresh(*args, **kwargs)

            def record_primary(*args, **kwargs):
                calls["primary_entries"] += 1
                original_primary_set_entries(*args, **kwargs)

            def record_secondary(*args, **kwargs):
                calls["secondary_entries"] += 1
                original_secondary_set_entries(*args, **kwargs)

            app.save_with_history = record_history  # type: ignore[method-assign]
            app.refresh = record_refresh  # type: ignore[method-assign]
            primary.item_grid.set_entries = record_primary  # type: ignore[method-assign]
            secondary.item_grid.set_entries = record_secondary  # type: ignore[method-assign]

            primary.activate_tab("tab-images")
            type(self).app.processEvents()

            self.assertEqual(
                calls,
                {"history": 0, "refresh": 0, "primary_entries": 1, "secondary_entries": 0},
            )

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
                tab
                for tab in app.model.config.panel_tabs
                if tab.content_kind == "widget" and tab.widget_type == "clock"
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
            self.assertEqual(payload["schema_version"], 5)

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
                5,
            )

    def test_history_restore_refreshes_open_settings_window_config(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            history = LayoutHistoryStore(Path(tmp) / "layout-history.json")
            config = build_default_configuration(desktop)
            config.panel_groups[0].geometry.rw = 0.44
            snapshot = history.push(config, "before-resize")
            app = DesktopCleanerApplication(
                build_default_configuration(desktop),
                store=store,
                history_store=history,
            )
            app.show()
            type(self).app.processEvents()
            app._show_settings(app.panel.group_id)
            settings = app._settings_window
            self.assertIsNotNone(settings)

            app._on_history_restore_requested(snapshot.id)
            type(self).app.processEvents()

            self.assertIs(
                settings._config,
                app.model.config,
                "settings window must follow the restored configuration object",
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

    def test_item_group_change_refreshes_only_panel_showing_that_tab(self) -> None:
        from desktop_tidy.application import ensure_application

        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            try:
                desktop = Path(tmp) / "desktop"
                desktop.mkdir()
                first = desktop / "a.png"
                second = desktop / "b.png"
                first.write_text("a", encoding="utf-8")
                second.write_text("b", encoding="utf-8")
                store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
                app = DesktopCleanerApplication(build_default_configuration(desktop), store=store)
                ensure_application()
                app.show()
                app.panel.activate_tab("tab-images")
                app.detach_tab_to_new_group(
                    "tab-images",
                    PanelGeometry(rx=0.55, ry=0.18, rw=0.28, rh=0.42),
                )
                type(self).app.processEvents()

                image_group_id = app.model.tab("tab-images").group_id
                image_panel = next(
                    panel for panel in app.panel_widgets() if panel.group_id == image_group_id
                )
                other_panel = next(
                    panel for panel in app.panel_widgets() if panel.group_id != image_group_id
                )
                calls = {"image": 0, "other": 0}
                image_set_entries = image_panel.item_grid.set_entries
                other_set_entries = other_panel.item_grid.set_entries

                def record_image(*args, **kwargs):
                    calls["image"] += 1
                    image_set_entries(*args, **kwargs)

                def record_other(*args, **kwargs):
                    calls["other"] += 1
                    other_set_entries(*args, **kwargs)

                image_panel.item_grid.set_entries = record_image  # type: ignore[method-assign]
                other_panel.item_grid.set_entries = record_other  # type: ignore[method-assign]

                app._on_group_create_requested("tab-images", [first, second])
                type(self).app.processEvents()

                self.assertEqual(calls["other"], 0)
                self.assertGreaterEqual(calls["image"], 1)
                self.assertTrue(first.is_file())
                self.assertTrue(second.is_file())
            finally:
                close_desktop_logger_handlers()

    def test_item_group_operation_failure_is_logged(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            try:
                desktop = Path(tmp) / "desktop"
                desktop.mkdir()
                source = desktop / "a.png"
                source.write_text("a", encoding="utf-8")
                store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
                app = DesktopCleanerApplication(build_default_configuration(desktop), store=store)

                app._on_group_create_requested("missing-tab", [source])

                log_path = Path(tmp) / "DesktopCleaner" / "logs" / "desktop-cleaner.log"
                close_desktop_logger_handlers()
                self.assertIn(
                    "图标分组创建失败",
                    log_path.read_text(encoding="utf-8"),
                )
            finally:
                close_desktop_logger_handlers()

    def test_clicking_outside_group_popup_closes_open_group_folder(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            first = desktop / "a.png"
            second = desktop / "b.png"
            first.write_text("a", encoding="utf-8")
            second.write_text("b", encoding="utf-8")
            config = build_default_configuration(desktop)
            config.item_groups.append(
                ItemGroup(
                    id="item-group-test",
                    tab_id="tab-images",
                    name="图片组",
                    member_paths=[canonical_key(first), canonical_key(second)],
                    order=0,
                )
            )
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(config, store=store)
            app.show()
            app.panel.activate_tab("tab-images")
            type(self).app.processEvents()

            app.panel.item_grid._switch_group_folder("item-group-test")
            self.assertEqual(app.panel.item_grid._open_group_id, "item-group-test")

            app._on_global_mouse_press(app.panel)

            self.assertEqual(app.panel.item_grid._open_group_id, "")

    def test_clicking_inside_inline_group_expansion_keeps_open_group_folder(self) -> None:
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            first = desktop / "a.png"
            second = desktop / "b.png"
            first.write_text("a", encoding="utf-8")
            second.write_text("b", encoding="utf-8")
            config = build_default_configuration(desktop)
            config.item_groups.append(
                ItemGroup(
                    id="item-group-test",
                    tab_id="tab-images",
                    name="图片组",
                    member_paths=[canonical_key(first), canonical_key(second)],
                    order=0,
                )
            )
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            app = DesktopCleanerApplication(config, store=store)
            app.show()
            app.panel.activate_tab("tab-images")
            type(self).app.processEvents()

            app.panel.item_grid._switch_group_folder("item-group-test")
            expansion = app.panel.item_grid._inline_group_expansion
            self.assertIsNotNone(expansion)
            assert expansion is not None
            self.assertEqual(app.panel.item_grid._open_group_id, "item-group-test")

            app._on_global_mouse_press(expansion)

            self.assertEqual(app.panel.item_grid._open_group_id, "item-group-test")


    def test_home_weather_refresh_updates_home_settings(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            weather = FakeWeatherService()
            app = DesktopCleanerApplication(
                build_default_configuration(desktop),
                store=store,
                weather_service=weather,
            )
            home = app.model.home_tab()
            assert home is not None
            home.widget_settings["module_settings"] = {
                "weather": {"weather": {"city": "Old", "summary": "Old"}}
            }

            app._on_widget_weather_refresh_requested("london")
            self.assertTrue(
                self._wait_until(
                    lambda: home.widget_settings.get("weather", {}).get("provider") == "fake"
                )
            )
            app._flush_deferred_save()

            self.assertEqual(weather.calls, ["london"])
            self.assertEqual(home.widget_settings["weather"]["city"], "London")
            nested_weather = home.widget_settings["module_settings"]["weather"]["weather"]
            self.assertEqual(nested_weather["city"], "London")
            self.assertEqual(nested_weather["provider"], "fake")
            self.assertEqual(home.widget_settings["weather"]["summary"], "Cloudy · 18°C")
            payload = json.loads(store.path.read_text(encoding="utf-8"))
            saved_home = next(tab for tab in payload["panel_tabs"] if tab["id"] == home.id)
            self.assertEqual(saved_home["widget_settings"]["weather"]["provider"], "fake")
            saved_nested = saved_home["widget_settings"]["module_settings"]["weather"]["weather"]
            self.assertEqual(saved_nested["provider"], "fake")

    def test_home_weather_auto_refreshes_on_show_when_city_has_no_summary(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            weather = FakeWeatherService()
            app = DesktopCleanerApplication(
                build_default_configuration(desktop),
                store=store,
                weather_service=weather,
            )
            home = app.model.home_tab()
            assert home is not None
            home.widget_settings["weather"] = {"city": "london"}
            home.widget_settings["module_settings"] = {
                "weather": {"weather": {"city": "london"}}
            }

            app.show()

            self.assertTrue(
                self._wait_until(
                    lambda: home.widget_settings.get("weather", {}).get("provider") == "fake"
                )
            )
            self.assertEqual(weather.calls, ["london"])
            self.assertEqual(home.widget_settings["weather"]["city"], "London")

    def test_home_weather_auto_refresh_skips_when_summary_exists(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            weather = FakeWeatherService()
            app = DesktopCleanerApplication(
                build_default_configuration(desktop),
                store=store,
                weather_service=weather,
            )
            home = app.model.home_tab()
            assert home is not None
            cached = {"city": "London", "summary": "Cloudy 路 18掳C", "provider": "cached"}
            home.widget_settings["weather"] = cached
            home.widget_settings["module_settings"] = {
                "weather": {"weather": dict(cached)}
            }

            app.show()
            QTest.qWait(100)
            type(self).app.processEvents()

            self.assertEqual(weather.calls, [])
            self.assertEqual(home.widget_settings["weather"]["provider"], "cached")

    def test_home_weather_refresh_failure_keeps_existing_weather_settings(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            weather = FakeWeatherService(fail=True)
            app = DesktopCleanerApplication(
                build_default_configuration(desktop),
                store=store,
                weather_service=weather,
            )
            home = app.model.home_tab()
            assert home is not None
            home.widget_settings["weather"] = {"city": "Paris", "summary": "Sunny · 20°C"}

            app._on_widget_weather_refresh_requested("paris")
            self.assertTrue(self._wait_until(lambda: weather.calls == ["paris"]))

            self.assertEqual(weather.calls, ["paris"])
            self.assertEqual(home.widget_settings["weather"]["city"], "Paris")
            self.assertEqual(home.widget_settings["weather"]["summary"], "Sunny · 20°C")


    def test_home_weather_refresh_failure_sets_visible_error_state(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            weather = FakeWeatherService(fail=True)
            app = DesktopCleanerApplication(
                build_default_configuration(desktop),
                store=store,
                weather_service=weather,
            )
            home = app.model.home_tab()
            assert home is not None
            home.widget_settings["weather"] = {"city": "Paris", "summary": "Sunny · 20°C"}
            home.widget_settings["module_settings"] = {
                "weather": {"weather": {"city": "Paris", "summary": "Sunny · 20°C"}}
            }

            app._on_widget_weather_refresh_requested("paris")
            self.assertTrue(self._wait_until(lambda: weather.calls == ["paris"]))

            self.assertEqual(home.widget_settings["weather"]["city"], "Paris")
            self.assertEqual(home.widget_settings["weather"]["summary"], "Sunny · 20°C")
            self.assertIn("error", home.widget_settings["weather"])
            nested_weather = home.widget_settings["module_settings"]["weather"]["weather"]
            self.assertEqual(nested_weather["city"], "Paris")
            self.assertEqual(nested_weather["summary"], "Sunny · 20°C")
            self.assertIn("error", nested_weather)

    def test_home_weather_refresh_does_not_block_ui_thread(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            store = ConfigurationStore(Path(tmp) / "DesktopCleaner" / "config.json")
            weather = SlowWeatherService()
            app = DesktopCleanerApplication(
                build_default_configuration(desktop),
                store=store,
                weather_service=weather,
            )
            home = app.model.home_tab()
            assert home is not None

            started = time.perf_counter()
            app._on_widget_weather_refresh_requested("london")
            elapsed = time.perf_counter() - started

            self.assertLess(elapsed, 0.12)
            self.assertTrue(
                self._wait_until(
                    lambda: home.widget_settings.get("weather", {}).get("provider") == "slow-fake",
                    timeout_ms=1000,
                )
            )


class ArrangeEntriesForTabTests(unittest.TestCase):
    def _entries(self, root: Path, names: list[str]):
        from desktop_tidy.services.desktop_index import IndexedItem

        return [IndexedItem((root / name)) for name in names]

    def test_no_manual_order_keeps_default_order(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = build_default_configuration(root)
            entries = self._entries(root, ["a.png", "b.png", "c.png"])

            arranged = arrange_entries_for_tab(config, entries, "tab-images")

            self.assertEqual([entry.path for entry in arranged], [entry.path for entry in entries])

    def test_manual_order_is_honored_and_new_item_appended_by_default(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = build_default_configuration(root)
            a, b, c = self._entries(root, ["a.png", "b.png", "c.png"])
            config.manual_orders["tab-images"] = [
                canonical_key(c.path),
                canonical_key(a.path),
            ]

            arranged = arrange_entries_for_tab(config, [a, b, c], "tab-images")

            self.assertEqual([entry.path for entry in arranged], [c.path, a.path, b.path])

    def test_prepend_front_places_new_items_first(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = build_default_configuration(root)
            config.new_item_placement = "prepend_front"
            a, b, c = self._entries(root, ["a.png", "b.png", "c.png"])
            config.manual_orders["tab-images"] = [canonical_key(a.path), canonical_key(c.path)]

            arranged = arrange_entries_for_tab(config, [a, b, c], "tab-images")

            self.assertEqual([entry.path for entry in arranged], [b.path, a.path, c.path])

    def test_resort_all_ignores_manual_order_when_new_items_present(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = build_default_configuration(root)
            config.new_item_placement = "resort_all"
            a, b, c = self._entries(root, ["a.png", "b.png", "c.png"])
            config.manual_orders["tab-images"] = [canonical_key(c.path), canonical_key(a.path)]

            arranged = arrange_entries_for_tab(config, [a, b, c], "tab-images")

            self.assertEqual([entry.path for entry in arranged], [a.path, b.path, c.path])

    def test_dangling_manual_order_keys_are_filtered(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = build_default_configuration(root)
            a, b = self._entries(root, ["a.png", "b.png"])
            config.manual_orders["tab-images"] = [
                canonical_key(b.path),
                canonical_key(root / "ghost.png"),
                canonical_key(a.path),
            ]

            arranged = arrange_entries_for_tab(config, [a, b], "tab-images")

            self.assertEqual([entry.path for entry in arranged], [b.path, a.path])


if __name__ == "__main__":
    unittest.main()
