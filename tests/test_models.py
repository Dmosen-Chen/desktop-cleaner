from __future__ import annotations

import unittest

from desktop_tidy.domain.defaults import build_default_configuration
from desktop_tidy.domain.models import (
    AppearanceSettings,
    ClassificationRule,
    Configuration,
    DesktopIntegrationState,
    InvalidConfiguration,
    ItemRef,
    ManualOverride,
    PanelGeometry,
    PanelGroup,
    PanelTab,
    validate_configuration,
)


class ModelTests(unittest.TestCase):
    def test_default_configuration_has_required_group_tabs_appearance_and_rules(self) -> None:
        config = build_default_configuration(r"C:\Users\Example\Desktop")

        self.assertEqual(config.schema_version, 2)
        self.assertEqual(config.desktop.path, r"C:\Users\Example\Desktop")
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
            AppearanceSettings("#234567", 0.4, 56),
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
        config = build_default_configuration(r"C:\Users\Example\Desktop")
        config.external_refs.append(
            ItemRef("external-1", "external", r"D:\draft\readme.md", "tab-other")
        )
        config.manual_overrides.append(ManualOverride(r"c:\users\example\desktop\fixed.png", "tab-documents"))

        payload = config.to_dict()
        restored = Configuration.from_dict(payload)

        self.assertNotIn("desktop_items", payload)
        self.assertEqual(restored, config)
        self.assertEqual(restored.external_refs[0].source_kind, "external")

    def test_validate_configuration_requires_absolute_desktop_path(self) -> None:
        config = build_default_configuration(r"D:\Desktop")
        config.desktop.path = r"relative\desktop"

        with self.assertRaisesRegex(InvalidConfiguration, "desktop.path must be an absolute path"):
            validate_configuration(config)

    def test_validate_configuration_allows_nonexistent_absolute_desktop_path(self) -> None:
        config = build_default_configuration(r"D:\MissingDesktop")

        validate_configuration(config)

    def test_validate_configuration_rejects_external_ref_inside_desktop(self) -> None:
        config = build_default_configuration(r"D:\Desktop")
        config.external_refs.append(
            ItemRef("external-inside", "external", r"D:\Desktop\notes.txt", "tab-other")
        )

        with self.assertRaisesRegex(
            InvalidConfiguration,
            "external reference external-inside must point outside the desktop",
        ):
            validate_configuration(config)

    def test_validate_configuration_allows_missing_external_ref_outside_desktop(self) -> None:
        config = build_default_configuration(r"D:\Desktop")
        config.external_refs.append(
            ItemRef("external-missing", "external", r"D:\Outside\missing.txt", "tab-other")
        )

        validate_configuration(config)

    def test_validate_configuration_rejects_relative_external_ref_canonical_path(self) -> None:
        config = build_default_configuration(r"D:\Desktop")
        config.external_refs.append(
            ItemRef("external-relative", "external", "notes.txt", "tab-other")
        )

        with self.assertRaisesRegex(
            InvalidConfiguration,
            "external reference external-relative must use an absolute path",
        ):
            validate_configuration(config)

    def test_appearance_settings_persist_item_icon_size(self) -> None:
        appearance = AppearanceSettings("#234567", 0.4, 64)

        payload = appearance.to_dict()

        self.assertEqual(payload["item_icon_size"], 64)
        self.assertEqual(AppearanceSettings.from_dict(payload), appearance)

    def test_validate_configuration_rejects_invalid_item_icon_size(self) -> None:
        config = build_default_configuration(r"D:\Desktop")
        config.panel_groups[0].appearance.item_icon_size = 4

        with self.assertRaisesRegex(InvalidConfiguration, "icon size"):
            validate_configuration(config)


if __name__ == "__main__":
    unittest.main()
