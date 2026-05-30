from __future__ import annotations

from datetime import datetime, timedelta
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from desktop_tidy.domain.defaults import build_default_configuration
from desktop_tidy.domain.models import ItemRef, ManualOverride
from desktop_tidy.persistence.layout_history import LayoutHistoryStore


class LayoutHistoryStoreTests(unittest.TestCase):
    def test_push_snapshot_deduplicates_and_keeps_recent_limit(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "layout-history.json"
            store = LayoutHistoryStore(path, limit=3)
            config = build_default_configuration(r"D:\Desktop")

            store.push(config, reason="initial")
            store.push(config, reason="duplicate")
            self.assertEqual(len(store.load()), 1)

            for index in range(4):
                config.panel_groups[0].geometry.rx = 0.01 * index
                store.push(config, reason=f"move-{index}")

            snapshots = store.load()
            self.assertEqual(len(snapshots), 3)
            self.assertEqual([entry.reason for entry in snapshots], ["move-1", "move-2", "move-3"])
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["snapshots"]), 3)

    def test_restore_snapshot_returns_configuration_without_desktop_inventory(self) -> None:
        with TemporaryDirectory() as tmp:
            store = LayoutHistoryStore(Path(tmp) / "layout-history.json")
            config = build_default_configuration(r"D:\Desktop")
            config.panel_groups[0].geometry.rw = 0.42
            store.push(config, reason="resize")

            restored = store.restore(store.load()[0].id)

            self.assertEqual(restored.panel_groups[0].geometry.rw, 0.42)
            self.assertNotIn("desktop_items", restored.to_dict())

    def test_item_reference_and_rule_only_changes_do_not_create_layout_snapshots(self) -> None:
        with TemporaryDirectory() as tmp:
            store = LayoutHistoryStore(Path(tmp) / "layout-history.json")
            config = build_default_configuration(r"D:\Desktop")

            store.push(config, reason="initial")
            config.external_refs.append(
                ItemRef("external-1", "external", r"D:\outside\file.txt", "tab-documents")
            )
            config.manual_overrides.append(ManualOverride(r"D:\Desktop\fresh.png", "tab-other"))
            config.rules[0].extensions.append(".folderalias")
            store.push(config, reason="item-reference-change")

            snapshots = store.load()
            self.assertEqual(len(snapshots), 1)
            self.assertEqual(snapshots[0].reason, "initial")

    def test_snapshot_preview_fields_are_optional_and_persisted_when_present(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "layout-history.json"
            path.write_text(
                json.dumps(
                    {
                        "snapshots": [
                            {
                                "id": "old",
                                "created_at": "2026-05-28T10:00:00",
                                "reason": "legacy",
                                "configuration": build_default_configuration(r"D:\Desktop").to_dict(),
                            },
                            {
                                "id": "new",
                                "created_at": "2026-05-28T10:01:00",
                                "reason": "move",
                                "preview_kind": "screenshot",
                                "preview_path": r"D:\previews\new.png",
                                "configuration": build_default_configuration(r"D:\Desktop").to_dict(),
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            store = LayoutHistoryStore(path)

            old, new = store.load()

            self.assertEqual(old.preview_kind, "layout")
            self.assertEqual(old.preview_path, "")
            self.assertEqual(new.preview_kind, "screenshot")
            self.assertEqual(new.preview_path, r"D:\previews\new.png")

    def test_default_history_limit_keeps_ten_snapshots(self) -> None:
        with TemporaryDirectory() as tmp:
            store = LayoutHistoryStore(Path(tmp) / "layout-history.json")
            config = build_default_configuration(r"D:\Desktop")

            for index in range(12):
                config.panel_groups[0].geometry.rx = 0.01 * index
                store.push(config, reason=f"move-{index}")

            snapshots = store.load()
            self.assertEqual(len(snapshots), 10)
            self.assertEqual(snapshots[0].reason, "move-2")

    def test_push_coalesces_same_merge_key_within_five_minutes(self) -> None:
        with TemporaryDirectory() as tmp:
            now = datetime(2026, 5, 28, 12, 0, 0)

            def clock() -> datetime:
                return now

            store = LayoutHistoryStore(Path(tmp) / "layout-history.json", clock=clock)
            config = build_default_configuration(r"D:\Desktop")

            store.push(config, reason="appearance-change", merge_key="appearance")
            first_id = store.load()[0].id
            now = now + timedelta(minutes=3)
            config.panel_groups[0].appearance.background_opacity = 0.72
            store.push(config, reason="appearance-change", merge_key="appearance")

            snapshots = store.load()
            self.assertEqual(len(snapshots), 1)
            self.assertEqual(snapshots[0].id, first_id)
            self.assertAlmostEqual(
                snapshots[0].configuration.panel_groups[0].appearance.background_opacity,
                0.72,
            )

            now = now + timedelta(minutes=6)
            config.panel_groups[0].appearance.background_opacity = 0.43
            store.push(config, reason="appearance-change", merge_key="appearance")

            self.assertEqual(len(store.load()), 2)

    def test_load_migrates_legacy_v4_snapshot_instead_of_dropping_it(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "layout-history.json"
            config = build_default_configuration(r"D:\Desktop")
            legacy_payload = config.to_dict()
            legacy_payload["schema_version"] = 4
            legacy_payload.pop("manual_orders", None)
            legacy_payload.pop("item_groups", None)
            legacy_payload.pop("new_item_placement", None)
            path.write_text(
                json.dumps(
                    {
                        "snapshots": [
                            {
                                "id": "layout-legacy",
                                "created_at": "2026-01-01T00:00:00",
                                "reason": "legacy",
                                "configuration": legacy_payload,
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            store = LayoutHistoryStore(path)
            snapshots = store.load()

            self.assertEqual(len(snapshots), 1)
            self.assertEqual(snapshots[0].id, "layout-legacy")
            self.assertEqual(snapshots[0].configuration.schema_version, 5)
            self.assertEqual(snapshots[0].configuration.new_item_placement, "append_end")
            restored = store.restore("layout-legacy")
            self.assertEqual(restored.schema_version, 5)


if __name__ == "__main__":
    unittest.main()
