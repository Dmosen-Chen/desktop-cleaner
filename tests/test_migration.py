from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from desktop_tidy.persistence.migration import load_or_migrate


class MigrationTests(unittest.TestCase):
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
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["schema_version"], 2)
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

    def test_corrupt_json_is_copied_aside_and_returns_default_configuration(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text("{broken", encoding="utf-8")

            config = load_or_migrate(path)

            self.assertEqual(config.schema_version, 2)
            self.assertEqual(config.panel_groups[0].id, "group-default")
            backups = list(Path(tmp).glob("config.corrupt-*.json"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding="utf-8"), "{broken")
            self.assertEqual(path.read_text(encoding="utf-8"), "{broken")


if __name__ == "__main__":
    unittest.main()
