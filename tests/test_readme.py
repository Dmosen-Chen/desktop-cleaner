from __future__ import annotations

import unittest
from pathlib import Path


class ReadmeTests(unittest.TestCase):
    def test_readme_is_utf8_chinese_release_documentation(self) -> None:
        text = Path("README.md").read_text(encoding="utf-8")

        self.assertIn("Desktop Cleaner 是一个 Windows 桌面入口面板工具", text)
        self.assertIn("桌面接管", text)
        self.assertIn("单实例", text)
        self.assertNotIn("当前版本不会接管 Windows 桌面层", text)
        self.assertNotIn("鏄", text)
        self.assertNotIn("鎺ョ", text)


if __name__ == "__main__":
    unittest.main()
