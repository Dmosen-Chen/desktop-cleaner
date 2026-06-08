from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from desktop_tidy.services.recent_items import RecentItemRecord, RecentItemsStore


class RecentItemsStoreTests(unittest.TestCase):
    def test_record_deduplicates_and_keeps_newest_first(self) -> None:
        with TemporaryDirectory() as tmp:
            store = RecentItemsStore(Path(tmp) / "recent-items.json", limit=3)
            first = Path(tmp) / "first.txt"
            second = Path(tmp) / "second.pdf"
            first.write_text("one", encoding="utf-8")
            second.write_text("two", encoding="utf-8")

            store.record(first)
            store.record(second)
            store.record(first)

            records = store.load()
            self.assertEqual([entry.name for entry in records], ["first.txt", "second.pdf"])
            self.assertEqual(records[0].kind, "file")
            self.assertTrue(records[0].opened_at)
            payload = json.loads((Path(tmp) / "recent-items.json").read_text(encoding="utf-8"))
            self.assertEqual(payload[0]["name"], "first.txt")

    def test_snapshot_returns_plain_dicts_and_keeps_missing_paths(self) -> None:
        with TemporaryDirectory() as tmp:
            store = RecentItemsStore(Path(tmp) / "recent-items.json", limit=3)
            missing = Path(tmp) / "deleted.lnk"

            store.record(missing)

            self.assertEqual(
                store.snapshot(limit=1),
                [
                    {
                        "name": "deleted.lnk",
                        "path": str(missing.resolve()),
                        "kind": "missing",
                        "source": "app",
                    }
                ],
            )

    def test_load_ignores_invalid_records(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "recent-items.json"
            path.write_text(
                json.dumps(
                    [
                        {"name": "ok.txt", "path": str(Path(tmp) / "ok.txt"), "kind": "file", "opened_at": "now"},
                        {"name": "", "path": "", "kind": "file", "opened_at": "bad"},
                    ]
                ),
                encoding="utf-8",
            )
            store = RecentItemsStore(path)

            self.assertEqual(
                store.load(),
                [RecentItemRecord("ok.txt", str((Path(tmp) / "ok.txt").resolve()), "file", "now")],
            )

    def test_dashboard_snapshot_uses_only_windows_recent_items(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            recent_dir = root / "WindowsRecent"
            recent_dir.mkdir()
            app_record = root / "app-record.pdf"
            shared_target = root / "shared.docx"
            app_record.write_text("app", encoding="utf-8")
            shared_target.write_text("shared", encoding="utf-8")
            shortcut = recent_dir / "shared.docx.lnk"
            shortcut.write_text("lnk", encoding="utf-8")

            store = RecentItemsStore(
                root / "recent-items.json",
                windows_recent_dir=recent_dir,
                shortcut_resolver=lambda path: shared_target if path == shortcut else None,
            )
            store.record(app_record)
            store.record(shared_target)

            self.assertEqual(
                store.dashboard_snapshot(limit=5),
                [
                    {
                        "name": "shared.docx",
                        "path": str(shared_target.resolve()),
                        "kind": "file",
                        "source": "windows",
                    }
                ],
            )

    def test_clear_removes_local_records_without_hiding_windows_recent_items(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            recent_dir = root / "WindowsRecent"
            recent_dir.mkdir()
            local_target = root / "local.pdf"
            windows_target = root / "windows.docx"
            local_target.write_text("local", encoding="utf-8")
            windows_target.write_text("windows", encoding="utf-8")
            shortcut = recent_dir / "windows.docx.lnk"
            shortcut.write_text("lnk", encoding="utf-8")

            store = RecentItemsStore(
                root / "recent-items.json",
                windows_recent_dir=recent_dir,
                shortcut_resolver=lambda path: windows_target if path == shortcut else None,
            )
            store.record(local_target)

            store.clear()

            self.assertEqual(store.snapshot(limit=5), [])
            self.assertEqual(
                store.dashboard_snapshot(limit=5),
                [
                    {
                        "name": "windows.docx",
                        "path": str(windows_target.resolve()),
                        "kind": "file",
                        "source": "windows",
                    }
                ],
            )

    def test_windows_recent_scan_uses_newest_shortcuts_first_and_keeps_missing_targets(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            recent_dir = root / "WindowsRecent"
            recent_dir.mkdir()
            older_target = root / "older.txt"
            newer_target = root / "newer.txt"
            older_target.write_text("older", encoding="utf-8")
            newer_target.write_text("newer", encoding="utf-8")
            older_shortcut = recent_dir / "older.txt.lnk"
            newer_shortcut = recent_dir / "newer.txt.lnk"
            missing_shortcut = recent_dir / "deleted.txt.lnk"
            older_shortcut.write_text("older", encoding="utf-8")
            newer_shortcut.write_text("newer", encoding="utf-8")
            missing_shortcut.write_text("missing", encoding="utf-8")
            os.utime(older_shortcut, (1000, 1000))
            os.utime(newer_shortcut, (2000, 2000))
            os.utime(missing_shortcut, (3000, 3000))

            resolver_targets = {
                older_shortcut: older_target,
                newer_shortcut: newer_target,
                missing_shortcut: root / "deleted.txt",
            }
            store = RecentItemsStore(
                root / "recent-items.json",
                windows_recent_dir=recent_dir,
                shortcut_resolver=lambda path: resolver_targets[path],
            )

            self.assertEqual(
                [entry["name"] for entry in store.windows_recent_snapshot(limit=2)],
                ["deleted.txt", "newer.txt"],
            )
            self.assertEqual(store.windows_recent_snapshot(limit=1)[0]["kind"], "missing")
            self.assertEqual(store.windows_recent_snapshot(limit=1)[0]["source"], "windows")

    def test_windows_recent_keeps_shortcut_when_target_resolution_fails(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            recent_dir = root / "WindowsRecent"
            recent_dir.mkdir()
            shortcut = recent_dir / "Canva.lnk"
            shortcut.write_text("lnk", encoding="utf-8")
            store = RecentItemsStore(
                root / "recent-items.json",
                windows_recent_dir=recent_dir,
                shortcut_resolver=lambda _path: None,
            )

            self.assertEqual(
                store.windows_recent_snapshot(limit=5),
                [
                    {
                        "name": "Canva",
                        "path": str(shortcut.resolve()),
                        "kind": "file",
                        "source": "windows",
                    }
                ],
            )


if __name__ == "__main__":
    unittest.main()
