from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from desktop_tidy.domain.classification import classify_path
from desktop_tidy.domain.defaults import build_default_configuration
from desktop_tidy.domain.workspace import WorkspaceModel


class WorkspaceTests(unittest.TestCase):
    def test_external_drop_stores_any_format_reference_without_writing_desktop(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            desktop = root / "desktop"
            outside = root / "outside"
            desktop.mkdir()
            outside.mkdir()
            source = outside / "anything.custom"
            source.write_text("content", encoding="utf-8")
            folder = outside / "folder-without-extension"
            folder.mkdir()
            model = WorkspaceModel(build_default_configuration(desktop))

            model.add_paths_to_tab([source, folder], "tab-images")

            self.assertTrue(source.is_file())
            self.assertTrue(folder.is_dir())
            self.assertEqual(list(desktop.iterdir()), [])
            self.assertEqual(
                [entry.target_tab_id for entry in model.config.external_refs],
                ["tab-images", "tab-images"],
            )

    def test_desktop_drop_updates_override_and_restore_returns_to_automatic_rule(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp)
            source = desktop / "photo.png"
            source.write_text("img", encoding="utf-8")
            model = WorkspaceModel(build_default_configuration(desktop))

            model.add_paths_to_tab([source], "tab-documents")
            model.add_paths_to_tab([source], "tab-archives")

            self.assertEqual(model.config.external_refs, [])
            self.assertEqual(len(model.config.manual_overrides), 1)
            self.assertEqual(classify_path(source, model.config), "tab-archives")
            model.restore_auto_classification(source)
            self.assertEqual(classify_path(source, model.config), "tab-images")

    def test_add_tab_makes_new_tab_active(self) -> None:
        model = WorkspaceModel(build_default_configuration(r"D:\Desktop"))

        new_tab = model.add_tab("group-default", "临时")

        self.assertEqual(model.group("group-default").active_tab_id, new_tab.id)

    def test_tab_commands_rename_cleanup_and_keep_a_minimum_default_group(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            desktop = root / "desktop"
            outside = root / "outside.txt"
            desktop.mkdir()
            outside.write_text("outside", encoding="utf-8")
            model = WorkspaceModel(build_default_configuration(desktop))
            custom = model.add_tab("group-default", "临时")
            model.rename_tab(custom.id, "收件箱")
            model.add_paths_to_tab([outside], custom.id)

            self.assertEqual(model.tab(custom.id).name, "收件箱")
            model.delete_tab(custom.id)
            self.assertEqual(model.config.external_refs, [])

            initial_ids = [tab.id for tab in model.config.panel_tabs]
            for tab_id in initial_ids:
                model.delete_tab(tab_id)
            self.assertEqual([group.id for group in model.config.panel_groups], ["group-default"])
            self.assertEqual(len(model.config.panel_tabs), 6)


if __name__ == "__main__":
    unittest.main()
