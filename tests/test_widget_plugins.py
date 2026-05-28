from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from desktop_tidy.ui.widget_plugins import BuiltinWidgetRegistry, UnknownWidgetPlugin


class WidgetPluginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_clock_plugin_is_registered_and_creates_widget(self) -> None:
        registry = BuiltinWidgetRegistry()
        plugin = registry.get("clock")

        widget = plugin.create_widget(plugin.default_settings())

        self.assertEqual(plugin.id, "clock")
        self.assertEqual(plugin.display_name, "时间")
        self.assertTrue(widget.findChildren(QLabel))
        self.assertLessEqual(widget.maximumWidth(), 340)
        self.assertLessEqual(widget.maximumHeight(), 190)

    def test_unknown_widget_type_uses_safe_placeholder(self) -> None:
        registry = BuiltinWidgetRegistry()
        plugin = registry.get("missing-widget")

        self.assertIsInstance(plugin, UnknownWidgetPlugin)
        widget = plugin.create_widget({})
        label = widget.findChild(QLabel)
        self.assertIsNotNone(label)
        self.assertIn("未知功能面板", label.text())
        self.assertIn("missing-widget", label.text())


if __name__ == "__main__":
    unittest.main()
