from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from desktop_tidy.domain.defaults import build_default_configuration
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


if __name__ == "__main__":
    unittest.main()
