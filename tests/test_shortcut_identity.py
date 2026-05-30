from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from desktop_tidy.domain.shortcut_identity import item_identity_key


class ShortcutIdentityTests(unittest.TestCase):
    def test_item_identity_key_falls_back_to_path_for_regular_files(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "note.txt"
            path.write_text("x", encoding="utf-8")
            self.assertTrue(item_identity_key(path).startswith("path:"))

    def test_item_identity_key_uses_lnk_target_when_available(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "game.lnk"
            path.write_text("placeholder", encoding="utf-8")
            with patch(
                "desktop_tidy.domain.shortcut_identity._lnk_target",
                return_value=r"C:\Games\endfield.exe",
            ):
                self.assertEqual(
                    item_identity_key(path),
                    r"lnk:c:\games\endfield.exe",
                )


if __name__ == "__main__":
    unittest.main()
