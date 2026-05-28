from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
