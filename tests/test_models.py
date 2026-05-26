from __future__ import annotations

import json
import unittest
from pathlib import Path

from desktop_tidy.domain.defaults import build_default_configuration
from desktop_tidy.domain.models import (
    AppearanceSettings,
    ClassificationRule,
    Configuration,
    DesktopIntegrationState,
    ItemRef,
    ManualOverride,
    PanelGeometry,
    PanelGroup,
    PanelTab,
)


class ModelTests(unittest.TestCase):
    def test_default_configuration_has_required_group_tabs_appearance_and_rules(self) -> None:
        config = build_default_configuration(r"E:\system\桌面")

        self.assertEqual(config.schema_version, 2)
        self.assertEqual(config.desktop.path, r"E:\system\桌面")
        self.assertEqual(config.desktop.primary_screen_id, "primary")
        self.assertEqual(len(config.panel_groups), 1)
        group = config.panel_groups[0]
        self.assertEqual(group.id, "group-default")
        self.assertFalse(group.locked)
        self.assertEqual(group.appearance, AppearanceSettings("#111111", 0.60))
        self.assertEqual(
            [tab.id for tab in config.panel_tabs],
            [
                "tab-folders",
                "tab-documents",
                "tab-images",
                "tab-archives",
                "tab-apps",
                "tab-other",
            ],
        )
        self.assertEqual(
            [tab.name for tab in config.panel_tabs],
            ["文件夹", "文档", "图片", "压缩包", "应用", "其它"],
        )
        self.assertEqual(group.tab_ids, [tab.id for tab in config.panel_tabs])
        self.assertEqual(group.active_tab_id, "tab-folders")
        self.assertEqual({rule.target_tab_id for rule in config.rules}, set(group.tab_ids))

    def test_each_persisted_entity_supports_dictionary_round_trip(self) -> None:
        entities = [
            AppearanceSettings("#234567", 0.4),
            PanelGeometry(0.1, 0.2, 0.3, 0.4),
            PanelGroup(
                id="group-a",
                screen_id="primary",
                geometry=PanelGeometry(0.1, 0.2, 0.3, 0.4),
                tab_ids=["tab-a"],
                active_tab_id="tab-a",
                appearance=AppearanceSettings("#234567", 0.4),
                locked=True,
                collapsed=True,
            ),
            PanelTab("tab-a", "group-a", "归档", 1, "custom"),
            ItemRef("external-a", "external", r"D:\Notes\readme.md", "tab-a"),
            ClassificationRule("rule-a", "Markdown", "extension", "tab-a", [".md"], False, 4),
            ManualOverride(r"d:\desktop\readme.md", "tab-a"),
            DesktopIntegrationState(r"D:\Desktop", True, True, True, True, "primary"),
        ]

        for entity in entities:
            with self.subTest(entity=type(entity).__name__):
                self.assertEqual(type(entity).from_dict(entity.to_dict()), entity)

    def test_configuration_round_trip_persists_only_external_refs_not_desktop_inventory(self) -> None:
        config = build_default_configuration(r"E:\system\桌面")
        config.external_refs.append(
            ItemRef("external-1", "external", r"D:\draft\readme.md", "tab-other")
        )
        config.manual_overrides.append(ManualOverride(r"e:\system\桌面\fixed.png", "tab-documents"))

        payload = config.to_dict()
        restored = Configuration.from_dict(payload)

        self.assertNotIn("desktop_items", payload)
        self.assertEqual(restored, config)
        self.assertEqual(restored.external_refs[0].source_kind, "external")

    def test_default_resource_contains_complete_v2_first_run_layout(self) -> None:
        resource_path = (
            Path(__file__).parents[1] / "desktop_tidy" / "resources" / "default_config.json"
        )
        config = Configuration.from_dict(json.loads(resource_path.read_text(encoding="utf-8")))

        self.assertEqual(config.schema_version, 2)
        # Resolve the user's real desktop at first startup; never ship a developer path.
        self.assertEqual(config.desktop.path, "")
        self.assertEqual([group.id for group in config.panel_groups], ["group-default"])
        self.assertEqual(len(config.panel_tabs), 6)
        self.assertTrue(config.rules)


if __name__ == "__main__":
    unittest.main()
