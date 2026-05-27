from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from desktop_tidy.domain.defaults import build_default_configuration
from desktop_tidy.persistence.migration import load_or_migrate


class MigrationTests(unittest.TestCase):
    def test_declared_unsupported_version_is_rejected_without_migration_or_overwrite(self) -> None:
        from desktop_tidy.persistence import UnsupportedConfigurationVersion

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for schema_version in (1, 4):
                with self.subTest(schema_version=schema_version):
                    path = root / f"config-{schema_version}.json"
                    content = json.dumps(
                        {"schema_version": schema_version, "desktop": {"path": r"D:\Desktop"}}
                    )
                    path.write_text(content, encoding="utf-8")

                    with self.assertRaisesRegex(
                        UnsupportedConfigurationVersion,
                        f"unsupported configuration schema version: {schema_version}",
                    ):
                        load_or_migrate(path)

                    self.assertEqual(path.read_text(encoding="utf-8"), content)
                    self.assertEqual(list(root.glob(f"config-{schema_version}.*-*.json")), [])

    def test_invalid_schema_v3_is_backed_up_and_returns_clean_defaults(self) -> None:
        invalid_cases = {
            "no-groups": lambda payload: payload.__setitem__("panel_groups", []),
            "missing-desktop-path": lambda payload: payload["desktop"].pop("path"),
            "non-string-desktop-path": lambda payload: payload["desktop"].__setitem__(
                "path", 42
            ),
            "blank-desktop-path": lambda payload: payload["desktop"].__setitem__("path", "  "),
            "non-bool-desktop-takeover": lambda payload: payload["desktop"].__setitem__(
                "takeover_enabled", "false"
            ),
            "non-bool-desktop-restore": lambda payload: payload["desktop"].__setitem__(
                "restore_required", "false"
            ),
            "non-bool-desktop-icons-hidden": lambda payload: payload["desktop"].__setitem__(
                "explorer_icons_hidden", "false"
            ),
            "non-bool-desktop-startup": lambda payload: payload["desktop"].__setitem__(
                "startup_enabled", "false"
            ),
            "missing-primary-screen-id": lambda payload: payload["desktop"].pop(
                "primary_screen_id"
            ),
            "non-string-primary-screen-id": lambda payload: payload["desktop"].__setitem__(
                "primary_screen_id", 42
            ),
            "blank-primary-screen-id": lambda payload: payload["desktop"].__setitem__(
                "primary_screen_id", "  "
            ),
            "missing-appearance-defaults": lambda payload: payload.pop("appearance_defaults"),
            "non-object-appearance-defaults": lambda payload: payload.__setitem__(
                "appearance_defaults", []
            ),
            "non-numeric-default-opacity": lambda payload: payload["appearance_defaults"].__setitem__(
                "background_opacity", "0.60"
            ),
            "missing-tab": lambda payload: payload["panel_groups"][0]["tab_ids"].append(
                "tab-missing"
            ),
            "missing-active-tab": lambda payload: payload["panel_groups"][0].__setitem__(
                "active_tab_id", "tab-missing"
            ),
            "missing-enabled-rule-target": lambda payload: payload["rules"][0].__setitem__(
                "target_tab_id", "tab-missing"
            ),
            "missing-manual-override-target": lambda payload: payload[
                "manual_overrides"
            ].append(
                {"canonical_path": r"D:\BrokenDesktop\fixed.txt", "target_tab_id": "tab-missing"}
            ),
            "missing-external-ref-target": lambda payload: payload["external_refs"].append(
                {
                    "id": "external-broken",
                    "source_kind": "external",
                    "canonical_path": r"D:\Outside\fixed.txt",
                    "target_tab_id": "tab-missing",
                }
            ),
            "invalid-external-ref-source-kind": lambda payload: payload["external_refs"].append(
                {
                    "id": "external-broken",
                    "source_kind": "desktop",
                    "canonical_path": r"D:\Outside\fixed.txt",
                    "target_tab_id": "tab-other",
                }
            ),
            "invalid-default-color": lambda payload: payload["appearance_defaults"].__setitem__(
                "background_color", "red"
            ),
            "invalid-default-opacity": lambda payload: payload["appearance_defaults"].__setitem__(
                "background_opacity", 1.1
            ),
            "invalid-group-color": lambda payload: payload["panel_groups"][0][
                "appearance"
            ].__setitem__("background_color", "red"),
            "invalid-group-opacity": lambda payload: payload["panel_groups"][0][
                "appearance"
            ].__setitem__("background_opacity", -0.1),
            "missing-group-geometry": lambda payload: payload["panel_groups"][0].pop(
                "geometry"
            ),
            "missing-group-appearance": lambda payload: payload["panel_groups"][0].pop(
                "appearance"
            ),
            "non-numeric-group-geometry": lambda payload: payload["panel_groups"][0][
                "geometry"
            ].__setitem__("rx", "0.04"),
            "bool-group-geometry": lambda payload: payload["panel_groups"][0][
                "geometry"
            ].__setitem__("rx", False),
            "missing-group-locked": lambda payload: payload["panel_groups"][0].pop("locked"),
            "missing-group-collapsed": lambda payload: payload["panel_groups"][0].pop(
                "collapsed"
            ),
            "non-bool-group-locked": lambda payload: payload["panel_groups"][0].__setitem__(
                "locked", "false"
            ),
            "non-bool-group-collapsed": lambda payload: payload["panel_groups"][0].__setitem__(
                "collapsed", "false"
            ),
            "non-list-panel-tabs": lambda payload: payload.__setitem__("panel_tabs", {}),
            "missing-tab-name": lambda payload: payload["panel_tabs"][0].pop("name"),
            "missing-tab-category-role": lambda payload: payload["panel_tabs"][0].pop(
                "category_role"
            ),
            "non-string-tab-name": lambda payload: payload["panel_tabs"][0].__setitem__(
                "name", 42
            ),
            "missing-rules": lambda payload: payload.pop("rules"),
            "non-list-rules": lambda payload: payload.__setitem__("rules", {}),
            "non-string-rule-id": lambda payload: payload["rules"][0].__setitem__("id", 42),
            "non-list-rule-extensions": lambda payload: payload["rules"][0].__setitem__(
                "extensions", ".txt"
            ),
            "non-int-rule-order": lambda payload: payload["rules"][0].__setitem__(
                "order", "0"
            ),
            "non-bool-rule-enabled": lambda payload: payload["rules"][0].__setitem__(
                "enabled", "false"
            ),
            "non-list-manual-overrides": lambda payload: payload.__setitem__(
                "manual_overrides", {}
            ),
            "non-list-external-refs": lambda payload: payload.__setitem__("external_refs", {}),
            "invalid-geometry": lambda payload: payload["panel_groups"][0]["geometry"].__setitem__(
                "rw", 1.1
            ),
            "relative-desktop-path": lambda payload: payload["desktop"].__setitem__(
                "path", "relative\\desktop"
            ),
            "external-ref-inside-desktop": lambda payload: payload["external_refs"].append(
                {
                    "id": "external-inside",
                    "source_kind": "external",
                    "canonical_path": r"D:\BrokenDesktop\inside.txt",
                    "target_tab_id": "tab-other",
                }
            ),
            "relative-external-ref-path": lambda payload: payload["external_refs"].append(
                {
                    "id": "external-relative",
                    "source_kind": "external",
                    "canonical_path": "notes.txt",
                    "target_tab_id": "tab-other",
                }
            ),
        }
        for name, invalidate in invalid_cases.items():
            with self.subTest(name=name), TemporaryDirectory() as tmp:
                root = Path(tmp)
                path = root / "config.json"
                payload = build_default_configuration(r"D:\BrokenDesktop").to_dict()
                invalidate(payload)
                content = json.dumps(payload, ensure_ascii=False)
                path.write_text(content, encoding="utf-8")

                config = load_or_migrate(path)

                self.assertEqual(config.schema_version, 3)
                self.assertEqual(config.panel_groups[0].id, "group-default")
                backups = list(root.glob("config.corrupt-*.json"))
                self.assertEqual(len(backups), 1)
                self.assertEqual(backups[0].read_text(encoding="utf-8"), content)
                self.assertEqual(path.read_text(encoding="utf-8"), content)

    def test_schema_v2_is_migrated_to_v3_and_allows_disabled_rule_with_cleared_target(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "config.json"
            expected = build_default_configuration(r"D:\Desktop")
            expected.rules[0].enabled = False
            expected.rules[0].target_tab_id = ""
            payload = expected.to_dict()
            payload["schema_version"] = 2
            for tab in payload["panel_tabs"]:
                tab.pop("content_kind", None)
                tab.pop("widget_type", None)
                tab.pop("widget_settings", None)
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

            config = load_or_migrate(path)

            self.assertEqual(config, expected)
            self.assertEqual(list(root.glob("config.corrupt-*.json")), [])
            self.assertEqual(len(list(root.glob("config.pre-schema-v3-*.json"))), 1)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["schema_version"], 3)
            self.assertTrue(all(tab.content_kind == "items" for tab in config.panel_tabs))

    def test_referenced_legacy_desktop_url_resolves_external_target_and_deduplicates(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            desktop = root / "desktop"
            outside = root / "outside"
            desktop.mkdir()
            outside.mkdir()
            internal = desktop / "inside.txt"
            external = outside / "notes.pdf"
            internal.write_text("inside", encoding="utf-8")
            external.write_text("outside", encoding="utf-8")
            shortcut = desktop / "old-external.url"
            shortcut.write_text(
                "[InternetShortcut]\nURL=" + external.resolve().as_uri() + "\n",
                encoding="utf-8",
            )
            legacy = {
                "desktop": str(desktop),
                "ui": {
                    "startup_enabled": True,
                    "partitions": [
                        {
                            "color": "#234567",
                            "alpha": 0.72,
                            "items": [
                                {"path": str(internal)},
                                {"path": str(external)},
                                {"path": str(shortcut)},
                            ],
                        }
                    ],
                },
            }
            path = root / "config.json"
            path.write_text(json.dumps(legacy), encoding="utf-8")

            config = load_or_migrate(path)

            self.assertEqual(config.desktop.path, str(desktop))
            self.assertTrue(config.desktop.startup_enabled)
            self.assertEqual(config.panel_groups[0].appearance.background_color, "#234567")
            self.assertEqual(config.panel_groups[0].appearance.background_opacity, 0.72)
            self.assertEqual([ref.canonical_path for ref in config.external_refs], [str(external.resolve())])
            self.assertEqual(config.external_refs[0].target_tab_id, "tab-other")
            self.assertEqual(len(list(root.glob("config.pre-qt-v1-*.json"))), 1)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["schema_version"], 3)
            self.assertTrue(internal.exists())
            self.assertTrue(external.exists())
            self.assertTrue(shortcut.exists())

    def test_invalid_legacy_appearance_falls_back_to_default(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "ui": {
                            "partitions": [
                                {"color": "red", "alpha": 4},
                                {"color": "#FFFFFF", "alpha": 0.5},
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )

            config = load_or_migrate(path)

            self.assertEqual(config.panel_groups[0].appearance.background_color, "#111111")
            self.assertEqual(config.panel_groups[0].appearance.background_opacity, 0.60)

    def test_unlisted_legacy_desktop_url_is_not_imported(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            desktop = root / "desktop"
            outside = root / "outside"
            desktop.mkdir()
            outside.mkdir()
            external = outside / "drawing.weird"
            external.write_text("data", encoding="utf-8")
            shortcut = desktop / "remembered.url"
            shortcut.write_text(
                "[InternetShortcut]\nURL=" + external.resolve().as_uri() + "\n",
                encoding="utf-8",
            )
            path = root / "config.json"
            path.write_text(json.dumps({"desktop": str(desktop), "ui": {}}), encoding="utf-8")

            config = load_or_migrate(path)

            self.assertEqual(config.external_refs, [])
            self.assertTrue(shortcut.exists())
            self.assertTrue(external.exists())

    def test_legacy_migration_ignores_empty_or_relative_desktop_path(self) -> None:
        from unittest.mock import patch

        with TemporaryDirectory() as tmp, patch(
            "desktop_tidy.services.desktop_location.resolve_desktop_path",
            return_value=Path(r"E:\Resolved\Desktop"),
        ):
            root = Path(tmp)
            for name, legacy in (
                ("empty", {"desktop": "  ", "ui": {}}),
                ("relative", {"desktop": "relative\\desktop", "ui": {}}),
            ):
                with self.subTest(name=name):
                    path = root / f"config-{name}.json"
                    path.write_text(json.dumps(legacy), encoding="utf-8")

                    config = load_or_migrate(path)

                    self.assertEqual(config.desktop.path, str(Path(r"E:\Resolved\Desktop")))

    def test_corrupt_json_is_copied_aside_and_returns_default_configuration(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text("{broken", encoding="utf-8")

            config = load_or_migrate(path)

            self.assertEqual(config.schema_version, 3)
            self.assertEqual(config.panel_groups[0].id, "group-default")
            backups = list(Path(tmp).glob("config.corrupt-*.json"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding="utf-8"), "{broken")
            self.assertEqual(path.read_text(encoding="utf-8"), "{broken")


if __name__ == "__main__":
    unittest.main()
