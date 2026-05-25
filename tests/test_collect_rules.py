from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from main import App, normalize_collect_rules


class CollectRulesTests(unittest.TestCase):
    def test_default_rules_target_matching_workspace_names(self) -> None:
        parts = [{"id": "pic", "name": "图片"}, {"id": "tool", "name": "工具"}]

        rules = normalize_collect_rules(None, parts)
        image_rule = next(rule for rule in rules if rule["type"] == "图片")
        shortcut_rule = next(rule for rule in rules if rule["type"] == "快捷方式")
        other_rule = next(rule for rule in rules if rule["type"] == "其它")

        self.assertEqual(image_rule["target_id"], "pic")
        self.assertIn(".png", image_rule["exts"])
        self.assertTrue(image_rule["enabled"])
        self.assertEqual(shortcut_rule["target_id"], "tool")
        self.assertFalse(other_rule["enabled"])

    def test_empty_rule_list_stays_empty(self) -> None:
        self.assertEqual(normalize_collect_rules([], [{"id": "a", "name": "图片"}]), [])

    def test_external_drop_creates_desktop_url_entry(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            desktop = root / "desktop"
            source_dir = root / "source"
            desktop.mkdir()
            source_dir.mkdir()
            source = source_dir / "note.txt"
            source.write_text("hello", encoding="utf-8")
            app = object.__new__(App)
            app.cfg = {"desktop": str(desktop)}

            entry = App._desktop_entry_for_drop(app, source.resolve())

            self.assertEqual(entry.parent, desktop)
            self.assertEqual(entry.suffix, ".url")
            self.assertIn(source.resolve().as_uri(), entry.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
