from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from desktop_tidy.persistence.ui_preferences import UiPreferences, UiPreferencesStore


class UiPreferencesStoreTests(unittest.TestCase):
    def test_missing_file_defaults_to_delete_confirmations_enabled(self) -> None:
        with TemporaryDirectory() as tmp:
            store = UiPreferencesStore(Path(tmp) / "ui-preferences.json")

            preferences = store.load()

            self.assertTrue(preferences.confirm_delete_panel)
            self.assertTrue(preferences.confirm_delete_tab)

    def test_group_accent_color_round_trip(self) -> None:
        with TemporaryDirectory() as tmp:
            store = UiPreferencesStore(Path(tmp) / "ui-preferences.json")
            store.save(UiPreferences(group_accent_color="#5078C8"))
            self.assertEqual(store.load().group_accent_color, "#5078C8")

    def test_round_trip_and_reset_delete_confirmations(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "ui-preferences.json"
            store = UiPreferencesStore(path)

            store.save(
                UiPreferences(
                    confirm_delete_panel=False,
                    confirm_delete_tab=False,
                    confirm_takeover=False,
                )
            )
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {
                    "confirm_delete_panel": False,
                    "confirm_delete_tab": False,
                    "confirm_takeover": False,
                    "group_accent_color": "#8264D2",
                },
            )

            restored = store.reset_delete_confirmations()

            self.assertTrue(restored.confirm_delete_panel)
            self.assertTrue(restored.confirm_delete_tab)
            self.assertTrue(restored.confirm_takeover)
            self.assertTrue(store.load().confirm_delete_panel)
            self.assertTrue(store.load().confirm_delete_tab)
            self.assertTrue(store.load().confirm_takeover)


if __name__ == "__main__":
    unittest.main()
