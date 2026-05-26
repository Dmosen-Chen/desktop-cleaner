from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from desktop_tidy.persistence.migration import load_or_migrate
from desktop_tidy.services import resolve_desktop_path


KNOWN_DESKTOP = Path("E:\\system\\\u684c\u9762")


class DesktopLocationTests(unittest.TestCase):
    def test_known_folder_desktop_is_used_for_new_and_recovered_configuration(self) -> None:
        with TemporaryDirectory() as tmp, patch(
            "desktop_tidy.services.desktop_location.windows_known_folder_desktop",
            return_value=KNOWN_DESKTOP,
        ):
            root = Path(tmp)
            missing_path = root / "missing.json"
            corrupt_path = root / "corrupt.json"
            corrupt_path.write_text("{broken", encoding="utf-8")

            new_config = load_or_migrate(missing_path)
            recovered_config = load_or_migrate(corrupt_path)

            self.assertEqual(new_config.desktop.path, str(KNOWN_DESKTOP))
            self.assertEqual(recovered_config.desktop.path, str(KNOWN_DESKTOP))

    def test_failed_known_folder_uses_existing_candidate_then_home_desktop(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            one_drive_desktop = home / "OneDrive" / "\u684c\u9762"
            one_drive_desktop.mkdir(parents=True)

            with patch(
                "desktop_tidy.services.desktop_location.windows_known_folder_desktop",
                side_effect=OSError("known folder unavailable"),
            ):
                self.assertEqual(resolve_desktop_path(home=home), one_drive_desktop)
                one_drive_desktop.rmdir()
                self.assertEqual(resolve_desktop_path(home=home), home / "Desktop")


if __name__ == "__main__":
    unittest.main()
