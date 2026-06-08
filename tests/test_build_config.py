from __future__ import annotations

import unittest
from pathlib import Path


class BuildConfigTests(unittest.TestCase):
    def test_pyinstaller_includes_win32com_client_for_windows_recent_links(self) -> None:
        script = Path("scripts/build_exe.bat").read_text(encoding="utf-8")
        spec = Path("DesktopCleaner.spec").read_text(encoding="utf-8")

        self.assertIn("--hidden-import=win32com.client", script)
        self.assertIn("'win32com.client'", spec)


if __name__ == "__main__":
    unittest.main()
