from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from organizer import (
    MoveRecord,
    append_undo_batch,
    desktop_dir,
    ensure_extension_key,
    move_paths_to_folder,
    organize_batch,
    plan_organize,
    safe_subfolder_name,
    undo_last_batch,
)


class OrganizerTests(unittest.TestCase):
    def test_ensure_extension_key_rejects_empty_input(self) -> None:
        self.assertEqual(ensure_extension_key(""), "")
        self.assertEqual(ensure_extension_key(" PDF "), ".pdf")

    def test_desktop_dir_uses_configured_path_even_before_creation(self) -> None:
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "custom_desktop"

            self.assertEqual(desktop_dir({"desktop": str(target)}), target.resolve())

    def test_safe_subfolder_name_keeps_moves_inside_archive_root(self) -> None:
        self.assertEqual(safe_subfolder_name("../escape"), "__escape")
        self.assertEqual(safe_subfolder_name(r"..\escape"), "__escape")
        self.assertEqual(safe_subfolder_name(""), "其它")

    def test_organize_sanitizes_rule_folder(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            desktop = root / "desktop"
            archive = root / "archive"
            desktop.mkdir()
            (desktop / "report.pdf").write_text("pdf", encoding="utf-8")

            records, logs = organize_batch(
                desktop=desktop,
                archive_root=archive,
                rules={".pdf": "../outside"},
            )

            self.assertEqual(len(records), 1, logs)
            self.assertTrue((archive / "__outside" / "report.pdf").is_file())
            self.assertFalse((root / "outside" / "report.pdf").exists())

    def test_plan_organize_does_not_move_files(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            desktop = root / "desktop"
            archive = root / "archive"
            desktop.mkdir()
            src = desktop / "report.pdf"
            src.write_text("pdf", encoding="utf-8")

            plans, logs = plan_organize(
                desktop=desktop,
                archive_root=archive,
                rules={".pdf": "文档"},
            )

            self.assertEqual(len(plans), 1, logs)
            self.assertTrue(src.is_file())
            self.assertFalse((archive / "文档" / "report.pdf").exists())

    def test_move_paths_skips_non_files_and_moves_remaining_files(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "archive"
            src = root / "image.png"
            directory = root / "folder"
            src.write_text("img", encoding="utf-8")
            directory.mkdir()

            records, logs = move_paths_to_folder([src, directory], archive, "图片")

            self.assertEqual(len(records), 1, logs)
            self.assertTrue((archive / "图片" / "image.png").is_file())
            self.assertIn("跳过（非文件）", "\n".join(logs))

    def test_undo_keeps_failed_moves_for_retry(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            desktop = root / "desktop"
            archive = root / "archive"
            desktop.mkdir()
            archive.mkdir()

            original = desktop / "a.txt"
            moved = archive / "a.txt"
            conflict = desktop / "b.txt"
            moved_conflict = archive / "b.txt"
            moved.write_text("a", encoding="utf-8")
            conflict.write_text("already here", encoding="utf-8")
            moved_conflict.write_text("b", encoding="utf-8")

            undo_path = root / "undo_stack.jsonl"
            append_undo_batch(
                undo_path,
                "batch",
                [
                    MoveRecord(src=str(original), dst=str(moved)),
                    MoveRecord(src=str(conflict), dst=str(moved_conflict)),
                ],
            )

            ok, logs = undo_last_batch(undo_path)

            self.assertFalse(ok)
            self.assertTrue(original.is_file(), logs)
            self.assertTrue(moved_conflict.is_file(), logs)
            saved = [json.loads(line) for line in undo_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0]["moves"], [{"src": str(conflict), "dst": str(moved_conflict)}])


if __name__ == "__main__":
    unittest.main()
