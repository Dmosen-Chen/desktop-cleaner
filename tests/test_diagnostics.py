from __future__ import annotations

import json
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from desktop_tidy.domain.defaults import build_default_configuration
from desktop_tidy.services.diagnostics import DiagnosticsService


class FakeTakeoverService:
    def __init__(
        self,
        *,
        visible: bool | None = True,
        restore_result: bool = True,
        attach_success: bool = True,
        hide_result: bool = True,
    ) -> None:
        self.visible = visible
        self.restore_result = restore_result
        self.attach_success = attach_success
        self.hide_result = hide_result
        self.calls: list[tuple[str, object]] = []

    def explorer_icons_visible(self) -> bool | None:
        self.calls.append(("visible", None))
        return self.visible

    def restore_explorer_icons(self) -> bool:
        self.calls.append(("restore", None))
        return self.restore_result

    def detach_panels(self) -> None:
        self.calls.append(("detach", None))

    def attach_panels(self, panel_hwnds: list[int]):
        self.calls.append(("attach", list(panel_hwnds)))
        return SimpleNamespace(success=self.attach_success, message="fake")

    def hide_explorer_icons(self) -> bool:
        self.calls.append(("hide", None))
        return self.hide_result


class DiagnosticsServiceTests(unittest.TestCase):
    def test_collect_snapshot_reports_paths_state_counts_and_recent_errors(self) -> None:
        with TemporaryDirectory() as tmp:
            base = Path(tmp) / "DesktopCleaner"
            base.mkdir()
            config_path = base / "config.json"
            history_path = base / "layout-history.json"
            log_path = base / "logs" / "desktop-cleaner.log"
            log_path.parent.mkdir()
            log_path.write_text(
                "info line\n2026 ERROR desktop_cleaner: boom\nlast line\n",
                encoding="utf-8",
            )
            config = build_default_configuration(Path(tmp) / "desktop")
            config.desktop.takeover_enabled = True
            config.desktop.restore_required = True
            config.desktop.explorer_icons_hidden = True
            service = DiagnosticsService(
                config,
                config_path=config_path,
                history_path=history_path,
                takeover_service=FakeTakeoverService(visible=False),
                executable_path_provider=lambda: Path("D:/tool/DesktopCleaner.exe"),
                panel_window_count_provider=lambda: 2,
            )

            snapshot = service.collect_snapshot()

            self.assertEqual(snapshot.desktop_path, config.desktop.path)
            self.assertEqual(snapshot.config_path, str(config_path))
            self.assertEqual(snapshot.log_path, str(log_path))
            self.assertTrue(snapshot.takeover_enabled)
            self.assertTrue(snapshot.restore_required)
            self.assertTrue(snapshot.explorer_icons_hidden)
            self.assertFalse(snapshot.explorer_icons_visible)
            self.assertEqual(snapshot.group_count, 1)
            self.assertEqual(snapshot.tab_count, 6)
            self.assertEqual(snapshot.panel_window_count, 2)
            self.assertEqual(snapshot.recent_errors, ["2026 ERROR desktop_cleaner: boom"])

    def test_read_recent_logs_limits_lines_and_handles_missing_file(self) -> None:
        with TemporaryDirectory() as tmp:
            base = Path(tmp) / "DesktopCleaner"
            config = build_default_configuration(Path(tmp) / "desktop")
            service = DiagnosticsService(
                config,
                config_path=base / "config.json",
                history_path=base / "layout-history.json",
                takeover_service=FakeTakeoverService(),
            )

            self.assertEqual(service.read_recent_logs(5), [])

            log_path = base / "logs" / "desktop-cleaner.log"
            log_path.parent.mkdir(parents=True)
            log_path.write_text("1\n2\n3\n4\n", encoding="utf-8")

            self.assertEqual(service.read_recent_logs(2), ["3", "4"])

    def test_export_bundle_contains_full_local_diagnostics_files(self) -> None:
        with TemporaryDirectory() as tmp:
            base = Path(tmp) / "DesktopCleaner"
            base.mkdir()
            config_path = base / "config.json"
            history_path = base / "layout-history.json"
            log_path = base / "logs" / "desktop-cleaner.log"
            log_path.parent.mkdir()
            config = build_default_configuration(Path(tmp) / "desktop")
            config_path.write_text(json.dumps(config.to_dict()), encoding="utf-8")
            history_path.write_text("[]", encoding="utf-8")
            log_path.write_text("hello log\n", encoding="utf-8")
            service = DiagnosticsService(
                config,
                config_path=config_path,
                history_path=history_path,
                takeover_service=FakeTakeoverService(),
            )

            bundle = service.export_bundle(Path(tmp))

            self.assertTrue(bundle.is_file())
            with zipfile.ZipFile(bundle) as archive:
                names = set(archive.namelist())
                self.assertIn("diagnostics.json", names)
                self.assertIn("config.json", names)
                self.assertIn("layout-history.json", names)
                self.assertIn("logs/desktop-cleaner.log", names)
                payload = json.loads(archive.read("diagnostics.json").decode("utf-8"))
                self.assertEqual(payload["desktop_path"], config.desktop.path)

    def test_restore_desktop_icons_updates_flags_and_saves(self) -> None:
        with TemporaryDirectory() as tmp:
            config = build_default_configuration(Path(tmp) / "desktop")
            config.desktop.restore_required = True
            config.desktop.explorer_icons_hidden = True
            saves: list[bool] = []
            takeover = FakeTakeoverService()
            service = DiagnosticsService(
                config,
                config_path=Path(tmp) / "config.json",
                history_path=Path(tmp) / "layout-history.json",
                takeover_service=takeover,
                config_saver=lambda: saves.append(True),
            )

            result = service.restore_desktop_icons()

            self.assertTrue(result.success)
            self.assertEqual(takeover.calls, [("restore", None), ("detach", None)])
            self.assertFalse(config.desktop.restore_required)
            self.assertFalse(config.desktop.explorer_icons_hidden)
            self.assertEqual(saves, [True])

    def test_refresh_takeover_restores_detaches_attaches_and_hides_when_enabled(self) -> None:
        with TemporaryDirectory() as tmp:
            config = build_default_configuration(Path(tmp) / "desktop")
            config.desktop.takeover_enabled = True
            config.desktop.restore_required = True
            config.desktop.explorer_icons_hidden = True
            saves: list[bool] = []
            takeover = FakeTakeoverService()
            service = DiagnosticsService(
                config,
                config_path=Path(tmp) / "config.json",
                history_path=Path(tmp) / "layout-history.json",
                takeover_service=takeover,
                panel_handles_provider=lambda: [111, 222],
                config_saver=lambda: saves.append(True),
            )

            result = service.refresh_takeover_if_enabled()

            self.assertTrue(result.success)
            self.assertEqual(
                takeover.calls,
                [
                    ("restore", None),
                    ("detach", None),
                    ("attach", [111, 222]),
                    ("hide", None),
                ],
            )
            self.assertTrue(config.desktop.restore_required)
            self.assertTrue(config.desktop.explorer_icons_hidden)
            self.assertGreaterEqual(len(saves), 1)


if __name__ == "__main__":
    unittest.main()
