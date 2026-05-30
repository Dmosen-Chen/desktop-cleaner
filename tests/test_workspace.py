from __future__ import annotations

import ast
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

from desktop_tidy.domain.classification import canonical_key, classify_path
from desktop_tidy.domain.defaults import build_default_configuration
from desktop_tidy.domain.models import ClassificationRule, ItemRef, ManualOverride, PanelGeometry, validate_configuration
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

    def test_organize_by_rules_only_clears_pending_overrides(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            desktop = root / "desktop"
            outside = root / "outside"
            desktop.mkdir()
            outside.mkdir()
            photo = desktop / "photo.png"
            photo.write_text("img", encoding="utf-8")
            pending = desktop / "fresh.png"
            pending.write_text("new", encoding="utf-8")
            external = outside / "linked.any"
            external.write_text("external", encoding="utf-8")
            model = WorkspaceModel(build_default_configuration(desktop))

            model.add_paths_to_tab([photo], "tab-documents")
            model.add_paths_to_tab([external], "tab-documents")
            model.mark_desktop_items_pending_organize([pending])

            self.assertEqual(classify_path(photo, model.config), "tab-documents")
            self.assertEqual(classify_path(pending, model.config), "tab-other")
            self.assertEqual(len(model.config.manual_overrides), 2)
            self.assertEqual(len(model.config.external_refs), 1)

            model.organize_by_rules()

            self.assertEqual(len(model.config.manual_overrides), 1)
            self.assertEqual(model.config.manual_overrides[0].target_tab_id, "tab-documents")
            self.assertEqual(classify_path(photo, model.config), "tab-documents")
            self.assertEqual(classify_path(pending, model.config), "tab-images")
            self.assertEqual(len(model.config.external_refs), 1)
            self.assertEqual(model.config.external_refs[0].target_tab_id, "tab-documents")
            self.assertTrue(photo.is_file())
            self.assertEqual(photo.read_text(encoding="utf-8"), "img")
            self.assertTrue(external.is_file())
            self.assertEqual(external.read_text(encoding="utf-8"), "external")

    def test_new_desktop_items_land_in_other_until_organize_runs(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp)
            photo = desktop / "fresh.png"
            photo.write_text("img", encoding="utf-8")
            model = WorkspaceModel(build_default_configuration(desktop))

            model.mark_desktop_items_pending_organize([photo])

            self.assertEqual(classify_path(photo, model.config), "tab-other")
            self.assertEqual(len(model.config.manual_overrides), 1)

            model.organize_by_rules()

            self.assertEqual(model.config.manual_overrides, [])
            self.assertEqual(classify_path(photo, model.config), "tab-images")
            self.assertEqual(photo.read_text(encoding="utf-8"), "img")

    def test_add_tab_makes_new_tab_active(self) -> None:
        model = WorkspaceModel(build_default_configuration(r"D:\Desktop"))

        new_tab = model.add_tab("group-default", "临时")

        self.assertEqual(new_tab.group_id, "group-default")
        self.assertEqual(model.group("group-default").active_tab_id, new_tab.id)

    def test_add_widget_tab_creates_active_function_tab_without_item_targets(self) -> None:
        model = WorkspaceModel(build_default_configuration(r"D:\Desktop"))

        tab = model.add_widget_tab("group-default", "clock", name="时间")

        self.assertEqual(tab.content_kind, "widget")
        self.assertEqual(tab.widget_type, "clock")
        self.assertEqual(tab.widget_settings, {})
        self.assertEqual(model.group("group-default").active_tab_id, tab.id)
        validate_configuration(model.config)

    def test_add_widget_panel_creates_independent_single_clock_group(self) -> None:
        model = WorkspaceModel(build_default_configuration(r"D:\Desktop"))

        group = model.add_widget_panel("clock", name="时间")

        self.assertEqual(group.tab_ids, [group.active_tab_id])
        tab = model.tab(group.active_tab_id)
        self.assertEqual(tab.content_kind, "widget")
        self.assertEqual(tab.widget_type, "clock")
        self.assertEqual(tab.group_id, group.id)
        validate_configuration(model.config)

    def test_files_cannot_be_dropped_on_widget_tab(self) -> None:
        model = WorkspaceModel(build_default_configuration(r"D:\Desktop"))
        tab = model.add_widget_tab("group-default", "clock", name="时间")

        with self.assertRaisesRegex(ValueError, "does not accept item entries"):
            model.add_paths_to_tab([Path(r"D:\outside.txt")], tab.id)

    def test_rename_tab_uses_default_label_when_inline_name_is_blank(self) -> None:
        model = WorkspaceModel(build_default_configuration(r"D:\Desktop"))
        tab = model.add_tab("group-default", "临时")

        model.rename_tab(tab.id, "   ")

        self.assertEqual(model.tab(tab.id).name, "未命名面板")

    def test_delete_tab_disables_and_clears_its_rule_instead_of_deleting_it(self) -> None:
        model = WorkspaceModel(build_default_configuration(r"D:\Desktop"))
        custom = model.add_tab("group-default", "Custom", tab_id="tab-custom")
        rule = ClassificationRule(
            "rule-custom", "Custom", "extension", custom.id, [".custom"], enabled=True, order=50
        )
        model.config.rules.append(rule)

        model.delete_tab(custom.id)

        saved_rule = next(entry for entry in model.config.rules if entry.id == "rule-custom")
        self.assertFalse(saved_rule.enabled)
        self.assertEqual(saved_rule.target_tab_id, "")
        validate_configuration(model.config)

    def test_delete_active_tab_selects_previous_neighbor(self) -> None:
        model = WorkspaceModel(build_default_configuration(r"D:\Desktop"))
        group = model.group("group-default")
        self.assertEqual(group.tab_ids[:4], ["tab-folders", "tab-documents", "tab-images", "tab-archives"])

        group.active_tab_id = "tab-images"
        model.delete_tab("tab-images")

        self.assertEqual(group.active_tab_id, "tab-documents")

        model.delete_tab("tab-folders")

        self.assertEqual(group.active_tab_id, "tab-documents")

    def test_deleting_until_one_tab_remains_does_not_rebuild_a_new_group(self) -> None:
        model = WorkspaceModel(build_default_configuration(r"D:\Desktop"))
        custom = model.add_tab("group-default", "Custom", tab_id="tab-custom")
        model.config.rules.append(
            ClassificationRule(
                "rule-custom", "Custom", "extension", custom.id, [".custom"], order=50
            )
        )
        existing_rule_ids = {entry.id for entry in model.config.rules}

        for tab_id in list(model.group("group-default").tab_ids):
            model.delete_tab(tab_id)

        rules_by_id = {entry.id: entry for entry in model.config.rules}
        self.assertEqual(set(rules_by_id), existing_rule_ids)
        self.assertEqual([group.id for group in model.config.panel_groups], ["group-default"])
        self.assertEqual([tab.id for tab in model.config.panel_tabs], ["tab-custom"])
        self.assertEqual(model.group("group-default").tab_ids, ["tab-custom"])
        self.assertTrue(rules_by_id["rule-custom"].enabled)
        self.assertEqual(rules_by_id["rule-custom"].target_tab_id, "tab-custom")
        validate_configuration(model.config)

    def test_deleting_until_one_tab_remains_does_not_restore_missing_default_rules(self) -> None:
        model = WorkspaceModel(build_default_configuration(r"D:\Desktop"))
        model.config.rules = [
            entry for entry in model.config.rules if entry.id != "rule-images"
        ]

        for tab_id in list(model.group("group-default").tab_ids):
            model.delete_tab(tab_id)

        rules_by_id = {entry.id: entry for entry in model.config.rules}
        self.assertNotIn("rule-images", rules_by_id)
        self.assertFalse(rules_by_id["rule-folders"].enabled)
        self.assertEqual(rules_by_id["rule-folders"].target_tab_id, "")
        self.assertEqual(len(model.config.panel_tabs), 1)
        validate_configuration(model.config)

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
            self.assertEqual(len(model.config.panel_tabs), 1)

    def test_domain_package_stays_free_of_qt_imports(self) -> None:
        domain_root = Path(__file__).resolve().parents[1] / "desktop_tidy" / "domain"
        forbidden = {"PySide6", "PyQt6", "QtCore", "QtGui", "QtWidgets", "QPoint", "QRect"}
        for path in sorted(domain_root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imported: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".")[0])
            with self.subTest(path=path.name):
                self.assertFalse(imported & forbidden, msg=f"{path.name} imports Qt: {imported & forbidden}")

    def test_detach_tab_from_multi_tab_group_creates_group_with_default_appearance(self) -> None:
        model = WorkspaceModel(build_default_configuration(r"D:\Desktop"))
        model.config.appearance_defaults.background_opacity = 0.75
        original = model.group("group-default")
        original_tab_count = len(original.tab_ids)

        detached_group = model.detach_tab("tab-images", PanelGeometry(0.5, 0.2, 0.3, 0.4))

        self.assertNotEqual(detached_group.id, "group-default")
        self.assertEqual(detached_group.tab_ids, ["tab-images"])
        self.assertEqual(detached_group.active_tab_id, "tab-images")
        self.assertEqual(detached_group.appearance.background_opacity, 0.75)
        self.assertEqual(model.tab("tab-images").group_id, detached_group.id)
        self.assertEqual(len(model.group("group-default").tab_ids), original_tab_count - 1)
        self.assertNotIn("tab-images", model.group("group-default").tab_ids)
        validate_configuration(model.config)

    def test_detach_tab_preserves_metadata_targeting_tab_id(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            desktop = root / "desktop"
            outside = root / "outside.txt"
            desktop.mkdir()
            outside.write_text("outside", encoding="utf-8")
            desktop_file = desktop / "photo.png"
            desktop_file.write_text("img", encoding="utf-8")
            model = WorkspaceModel(build_default_configuration(desktop))
            model.add_paths_to_tab([outside], "tab-images")
            model.add_paths_to_tab([desktop_file], "tab-images")

            model.detach_tab("tab-images", PanelGeometry(0.55, 0.25, 0.25, 0.35))

            self.assertEqual(model.config.external_refs[0].target_tab_id, "tab-images")
            self.assertEqual(model.config.manual_overrides[0].target_tab_id, "tab-images")
            self.assertEqual(list(desktop.iterdir()), [desktop_file])
            self.assertTrue(outside.is_file())

    def test_merge_group_at_point_inside_bounds_appends_tabs_and_keeps_target_appearance(self) -> None:
        model = WorkspaceModel(build_default_configuration(r"D:\Desktop"))
        target = model.group("group-default")
        target.appearance.background_color = "#224466"
        target_appearance = deepcopy(target.appearance)
        second = model.detach_tab("tab-images", PanelGeometry(0.6, 0.2, 0.3, 0.4))

        merged = model.merge_group_at_point(
            second.id,
            point=(180, 160),
            bounds={"group-default": (100, 100, 400, 300)},
        )

        self.assertTrue(merged)
        merged_group = model.group("group-default")
        self.assertEqual(merged_group.tab_ids[-1], "tab-images")
        self.assertEqual(model.tab("tab-images").group_id, "group-default")
        self.assertEqual(merged_group.appearance.background_color, target_appearance.background_color)
        self.assertFalse(any(group.id == second.id for group in model.config.panel_groups))
        validate_configuration(model.config)

    def test_merge_group_preserves_source_tab_order(self) -> None:
        model = WorkspaceModel(build_default_configuration(r"D:\Desktop"))
        first = model.detach_tab("tab-images", PanelGeometry(0.55, 0.18, 0.28, 0.42))
        second = model.detach_tab("tab-archives", PanelGeometry(0.58, 0.20, 0.26, 0.40))

        merged = model.merge_group_at_point(
            second.id,
            point=(200, 180),
            bounds={first.id: (120, 120, 360, 280)},
        )

        self.assertTrue(merged)
        self.assertEqual(model.group(first.id).tab_ids, ["tab-images", "tab-archives"])
        validate_configuration(model.config)

    def test_merge_group_at_point_outside_bounds_leaves_groups_unchanged(self) -> None:
        model = WorkspaceModel(build_default_configuration(r"D:\Desktop"))
        second = model.detach_tab("tab-images", PanelGeometry(0.6, 0.2, 0.3, 0.4))
        before_groups = [group.id for group in model.config.panel_groups]

        merged = model.merge_group_at_point(
            second.id,
            point=(999, 999),
            bounds={"group-default": (100, 100, 400, 300)},
        )

        self.assertFalse(merged)
        self.assertEqual([group.id for group in model.config.panel_groups], before_groups)
        self.assertEqual(model.tab("tab-images").group_id, second.id)

    def test_locked_source_or_target_rejects_detach_and_merge(self) -> None:
        model = WorkspaceModel(build_default_configuration(r"D:\Desktop"))
        second = model.detach_tab("tab-images", PanelGeometry(0.6, 0.2, 0.3, 0.4))

        model.group("group-default").locked = True
        with self.assertRaises(ValueError):
            model.detach_tab("tab-documents", PanelGeometry(0.4, 0.2, 0.3, 0.4))

        model.group("group-default").locked = False
        model.add_tab(second.id, "Side")
        model.group(second.id).locked = True
        with self.assertRaises(ValueError):
            model.detach_tab("tab-images", PanelGeometry(0.62, 0.22, 0.28, 0.38))

        model.group(second.id).locked = False
        model.group(second.id).locked = True
        self.assertFalse(
            model.merge_group_at_point(
                second.id,
                point=(180, 160),
                bounds={"group-default": (100, 100, 400, 300)},
            )
        )
        self.assertEqual(model.tab("tab-images").group_id, second.id)

        model.group(second.id).locked = False
        model.group("group-default").locked = True
        self.assertFalse(
            model.merge_group_at_point(
                second.id,
                point=(180, 160),
                bounds={"group-default": (100, 100, 400, 300)},
            )
        )
        self.assertEqual(len(model.config.panel_groups), 2)

    def test_reorder_tab_items_records_canonical_order_without_touching_files(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp)
            first = desktop / "a.png"
            second = desktop / "b.png"
            first.write_text("a", encoding="utf-8")
            second.write_text("b", encoding="utf-8")
            model = WorkspaceModel(build_default_configuration(desktop))

            model.reorder_tab_items("tab-images", [second, first])

            order = model.config.manual_orders["tab-images"]
            self.assertEqual(len(order), 2)
            self.assertEqual(order[0], canonical_key(second))
            self.assertEqual(order[1], canonical_key(first))
            self.assertEqual(first.read_text(encoding="utf-8"), "a")
            self.assertEqual(second.read_text(encoding="utf-8"), "b")
            self.assertTrue(first.is_file() and second.is_file())
            validate_configuration(model.config)

    def test_reorder_tab_items_empty_clears_manual_order(self) -> None:
        model = WorkspaceModel(build_default_configuration(r"D:\Desktop"))
        model.config.manual_orders["tab-images"] = ["x"]

        model.reorder_tab_items("tab-images", [])

        self.assertNotIn("tab-images", model.config.manual_orders)

    def test_set_new_item_placement_validates_value(self) -> None:
        model = WorkspaceModel(build_default_configuration(r"D:\Desktop"))

        model.set_new_item_placement("prepend_front")
        self.assertEqual(model.config.new_item_placement, "prepend_front")

        with self.assertRaises(ValueError):
            model.set_new_item_placement("nonsense")

    def test_delete_tab_clears_manual_orders_and_groups_metadata_only(self) -> None:
        from desktop_tidy.domain.models import ItemGroup

        model = WorkspaceModel(build_default_configuration(r"D:\Desktop"))
        model.config.manual_orders["tab-images"] = ["one", "two"]
        model.config.item_groups.append(
            ItemGroup(id="g1", tab_id="tab-images", name="工作", order=0, member_paths=["one"])
        )

        self.assertTrue(model.delete_tab("tab-images"))

        self.assertNotIn("tab-images", model.config.manual_orders)
        self.assertEqual(
            [group for group in model.config.item_groups if group.tab_id == "tab-images"],
            [],
        )
        validate_configuration(model.config)


class ItemGroupTests(unittest.TestCase):
    def _model_with_files(self, tmp: str):
        desktop = Path(tmp)
        paths = []
        for name in ("a.png", "b.png", "c.png"):
            path = desktop / name
            path.write_text(name, encoding="utf-8")
            paths.append(path)
        return WorkspaceModel(build_default_configuration(desktop)), paths

    def test_create_group_records_members_without_touching_files(self) -> None:
        with TemporaryDirectory() as tmp:
            model, paths = self._model_with_files(tmp)
            group = model.create_item_group("tab-images", [paths[0], paths[1]], "游戏")

            self.assertTrue(group.id.startswith("item-group-"))
            self.assertEqual(group.tab_id, "tab-images")
            self.assertEqual(group.name, "游戏")
            self.assertEqual(
                group.member_paths,
                [canonical_key(paths[0]), canonical_key(paths[1])],
            )
            self.assertEqual(len(model.config.item_groups), 1)
            for path in paths:
                self.assertTrue(path.is_file())
                self.assertEqual(path.read_text(encoding="utf-8"), path.name)
            validate_configuration(model.config)

    def test_create_group_uses_default_name_when_blank(self) -> None:
        with TemporaryDirectory() as tmp:
            model, paths = self._model_with_files(tmp)
            group = model.create_item_group("tab-images", [paths[0]], "   ")
            self.assertEqual(group.name, "新建分组")

    def test_create_group_orders_increment_per_tab(self) -> None:
        with TemporaryDirectory() as tmp:
            model, paths = self._model_with_files(tmp)
            first = model.create_item_group("tab-images", [paths[0]])
            second = model.create_item_group("tab-images", [paths[1]])
            self.assertEqual(first.order, 0)
            self.assertEqual(second.order, 1)

    def test_add_items_moves_member_out_of_previous_group(self) -> None:
        with TemporaryDirectory() as tmp:
            model, paths = self._model_with_files(tmp)
            first = model.create_item_group("tab-images", [paths[0], paths[1]])
            second = model.create_item_group("tab-images", [paths[2]])

            model.add_items_to_group(second.id, [paths[1]])

            self.assertEqual(
                [group for group in model.config.item_groups if group.id == first.id],
                [],
            )
            self.assertEqual(
                second.member_paths,
                [canonical_key(paths[2]), canonical_key(paths[1])],
            )
            validate_configuration(model.config)

    def test_remove_item_prunes_emptied_group(self) -> None:
        with TemporaryDirectory() as tmp:
            model, paths = self._model_with_files(tmp)
            group = model.create_item_group("tab-images", [paths[0]])
            model.remove_items_from_group([paths[0]])
            self.assertEqual(model.config.item_groups, [])
            self.assertTrue(paths[0].is_file())

    def test_remove_item_leaving_one_member_dissolves_group(self) -> None:
        with TemporaryDirectory() as tmp:
            model, paths = self._model_with_files(tmp)
            group = model.create_item_group("tab-images", [paths[0], paths[1]])
            model.remove_items_from_group([paths[1]])
            self.assertEqual(model.config.item_groups, [])
            self.assertTrue(all(path.is_file() for path in paths[:2]))

    def test_move_paths_to_tab_clears_manual_order_on_source_tab(self) -> None:
        with TemporaryDirectory() as tmp:
            model, paths = self._model_with_files(tmp)
            key = canonical_key(paths[0])
            model.config.manual_orders["tab-images"] = [key, canonical_key(paths[1])]
            model.config.manual_orders["tab-documents"] = [key]

            model.move_paths_to_tab([paths[0]], "tab-apps")

            self.assertEqual(
                model.config.manual_overrides[0].target_tab_id,
                "tab-apps",
            )
            self.assertNotIn(key, model.config.manual_orders.get("tab-images", []))
            self.assertNotIn(key, model.config.manual_orders.get("tab-documents", []))

    def test_rename_and_dissolve_group_metadata_only(self) -> None:
        with TemporaryDirectory() as tmp:
            model, paths = self._model_with_files(tmp)
            group = model.create_item_group("tab-images", [paths[0], paths[1]])
            model.rename_item_group(group.id, "工作")
            self.assertEqual(model._item_group(group.id).name, "工作")

            model.dissolve_item_group(group.id)
            self.assertEqual(model.config.item_groups, [])
            for path in paths:
                self.assertTrue(path.is_file())
            validate_configuration(model.config)

    def test_create_group_rejects_widget_tab(self) -> None:
        from desktop_tidy.domain.models import PanelTab

        with TemporaryDirectory() as tmp:
            model, paths = self._model_with_files(tmp)
            widget_tab = PanelTab(
                "tab-widget",
                model.config.panel_groups[0].id,
                "时钟",
                99,
                content_kind="widget",
                widget_type="clock",
            )
            model.config.panel_tabs.append(widget_tab)
            with self.assertRaises(ValueError):
                model.create_item_group("tab-widget", [paths[0]])

    def test_repair_metadata_deduplicates_overrides_and_external_refs(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            source = desktop / "photo.png"
            source.write_text("img", encoding="utf-8")
            model = WorkspaceModel(build_default_configuration(desktop))
            key = canonical_key(source)
            model.config.manual_overrides.extend(
                [
                    ManualOverride(key, "tab-documents"),
                    ManualOverride(key, "tab-images"),
                ]
            )
            model.config.external_refs.append(
                ItemRef("e1", "external", str(source.resolve()), "tab-documents")
            )

            issues = model.repair_metadata(desktop_roots=[desktop])

            self.assertTrue(any("重复的手动归类" in issue for issue in issues))
            self.assertTrue(any("清理与手动归类重复的外部引用" in issue for issue in issues))
            self.assertEqual(len(model.config.manual_overrides), 1)
            self.assertEqual(model.config.external_refs, [])

    def test_repair_metadata_keeps_external_ref_for_outside_paths_with_override(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            desktop = root / "desktop"
            outside = root / "outside"
            desktop.mkdir()
            outside.mkdir()
            source = outside / "linked.any"
            source.write_text("external", encoding="utf-8")
            model = WorkspaceModel(build_default_configuration(desktop))
            key = canonical_key(source)
            model.config.manual_overrides.append(ManualOverride(key, "tab-documents"))
            model.config.external_refs.append(
                ItemRef("e1", "external", str(source.resolve()), "tab-documents")
            )

            issues = model.repair_metadata(desktop_roots=[desktop])

            self.assertEqual(issues, [])
            self.assertEqual(len(model.config.manual_overrides), 1)
            self.assertEqual(len(model.config.external_refs), 1)

    def test_add_paths_to_tab_uses_override_for_extra_desktop_roots(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            user_desktop = root / "user"
            public_desktop = root / "public"
            user_desktop.mkdir()
            public_desktop.mkdir()
            shortcut = public_desktop / "game.lnk"
            shortcut.write_text("lnk", encoding="utf-8")
            model = WorkspaceModel(build_default_configuration(user_desktop))

            model.add_paths_to_tab(
                [shortcut],
                "tab-apps",
                desktop_roots=[public_desktop],
            )

            self.assertEqual(model.config.external_refs, [])
            self.assertEqual(len(model.config.manual_overrides), 1)
            self.assertEqual(classify_path(shortcut, model.config), "tab-apps")


if __name__ == "__main__":
    unittest.main()
