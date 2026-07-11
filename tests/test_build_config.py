from __future__ import annotations

import unittest
from pathlib import Path


class BuildConfigTests(unittest.TestCase):
    def test_build_script_uses_spec_as_pyinstaller_source_of_truth(self) -> None:
        script = Path("scripts/build_exe.bat").read_text(encoding="utf-8")
        spec = Path("DesktopCleaner.spec").read_text(encoding="utf-8")

        pyinstaller_commands = [
            line.strip()
            for line in script.splitlines()
            if line.strip().startswith("python -m PyInstaller")
        ]

        self.assertEqual(
            pyinstaller_commands,
            ["python -m PyInstaller --noconfirm --clean DesktopCleaner.spec"],
        )
        self.assertNotIn("--hidden-import", script)
        self.assertNotIn("--add-data", script)
        self.assertNotIn("--icon", script)
        self.assertIn("'win32com.client'", spec)
        self.assertIn(r"('assets\\icons', 'assets\\icons')", spec)


if __name__ == "__main__":
    unittest.main()
