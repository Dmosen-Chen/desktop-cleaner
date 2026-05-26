from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock

from desktop_tidy.services.desktop_index import DesktopIndex, should_display


class DesktopIndexTests(unittest.TestCase):
    def test_scan_accepts_files_and_folders_in_any_format_and_suppresses_noise(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp)
            (desktop / "note.unusual").write_text("x", encoding="utf-8")
            (desktop / "folder").mkdir()
            (desktop / "desktop.ini").write_text("x", encoding="utf-8")
            (desktop / "~$draft.docx").write_text("x", encoding="utf-8")

            entries = DesktopIndex(desktop).scan()

            self.assertEqual([entry.path.name for entry in entries], ["folder", "note.unusual"])
            self.assertTrue((desktop / "note.unusual").exists())
            self.assertTrue((desktop / "folder").exists())

    def test_hidden_and_system_windows_items_are_suppressed(self) -> None:
        hidden = Mock(name="hidden")
        hidden.name = "hidden.txt"
        hidden.stat.return_value = SimpleNamespace(st_file_attributes=0x2)
        system = Mock(name="system")
        system.name = "system.txt"
        system.stat.return_value = SimpleNamespace(st_file_attributes=0x4)

        self.assertFalse(should_display(hidden))
        self.assertFalse(should_display(system))

    def test_rescan_reports_add_remove_and_rename_as_differences(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp)
            index = DesktopIndex(desktop)
            first = index.rescan()
            source = desktop / "before.txt"
            source.write_text("x", encoding="utf-8")
            added = index.rescan()
            source.rename(desktop / "after.txt")
            changed = index.rescan()

            self.assertEqual(first.added, [])
            self.assertEqual([item.path.name for item in added.added], ["before.txt"])
            self.assertEqual([item.path.name for item in changed.current], ["after.txt"])
            self.assertEqual([item.path.name for item in changed.added], ["after.txt"])
            self.assertEqual([item.path.name for item in changed.removed], ["before.txt"])


class DesktopWatcherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def test_watcher_emits_rescan_changes_after_temp_directory_update(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtTest import QSignalSpy, QTest

        from desktop_tidy.services.desktop_index import DesktopWatcher

        with TemporaryDirectory() as tmp:
            desktop = Path(tmp)
            index = DesktopIndex(desktop)
            watcher = DesktopWatcher(index)
            spy = QSignalSpy(watcher.changed)
            index.rescan()

            new_file = desktop / "watched.txt"
            new_file.write_text("x", encoding="utf-8")

            for _ in range(100):
                type(self).app.processEvents()
                if spy.count() > 0:
                    break
                QTest.qWait(20)

            self.assertGreaterEqual(spy.count(), 1)
            changes = spy.at(spy.count() - 1)[0]
            self.assertEqual([item.path.name for item in changes.added], ["watched.txt"])
            self.assertEqual(new_file.read_text(encoding="utf-8"), "x")


if __name__ == "__main__":
    unittest.main()
