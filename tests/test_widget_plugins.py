from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QWidget

from desktop_tidy.widgets.models import WidgetDefinition, WidgetVisualPreset
from desktop_tidy.widgets.registry import BuiltinWidgetRegistry as ModularWidgetRegistry
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
        self.assertEqual(plugin.display_name, "时间面板")
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

    def test_modular_registry_exposes_widget_definitions(self) -> None:
        registry = ModularWidgetRegistry()

        definitions = registry.available()
        clock = next(definition for definition in definitions if definition.id == "clock")

        self.assertIsInstance(clock, WidgetDefinition)
        self.assertEqual(clock.display_name, "时间面板")
        self.assertEqual(clock.default_width, 320)
        self.assertEqual(clock.default_height, 190)
        self.assertEqual(clock.max_width, 340)
        self.assertEqual(clock.max_height, 190)

    def test_clock_definition_exposes_reusable_visual_metadata(self) -> None:
        registry = ModularWidgetRegistry()

        clock = registry.get("clock").definition()

        self.assertIsInstance(clock.visual, WidgetVisualPreset)
        self.assertEqual(clock.visual.preset_id, "quiet-clock")
        self.assertEqual(clock.visual_preset, "quiet-clock")
        self.assertEqual(clock.accent_color, clock.visual.accent_color)
        self.assertEqual(clock.preview_background, clock.visual.background)
        self.assertEqual(clock.default_width, clock.visual.recommended_width)
        self.assertEqual(clock.default_height, clock.visual.recommended_height)
        self.assertTrue(clock.preview_background)
        self.assertTrue(clock.preview_foreground)
        self.assertTrue(clock.preview_secondary_foreground)
        self.assertIn("#", clock.preview_background)

    def test_clock_widget_keeps_transparent_desktop_style(self) -> None:
        registry = ModularWidgetRegistry()
        plugin = registry.get("clock")
        definition = plugin.definition()

        widget = plugin.create_widget(plugin.default_settings())

        self.assertNotIn(definition.visual.background, widget.styleSheet())
        self.assertEqual(widget.minimumWidth(), definition.visual.min_width)
        self.assertEqual(widget.maximumWidth(), definition.visual.max_width)

    def test_home_dashboard_plugin_is_registered_and_creates_modules(self) -> None:
        registry = ModularWidgetRegistry()

        plugin = registry.get("home")
        definition = plugin.definition()
        widget = plugin.create_widget(plugin.default_settings())

        self.assertEqual(plugin.id, "home")
        self.assertEqual(definition.display_name, "主标签页")
        self.assertEqual(definition.visual.preset_id, "home-dashboard")
        self.assertIsInstance(widget, QWidget)
        self.assertEqual(widget.objectName(), "HomeDashboardWidgetRoot")
        label_text = "\n".join(label.text() for label in widget.findChildren(QLabel))
        for expected in ("时间", "最近使用", "日程提醒", "网络收藏", "日历", "天气"):
            self.assertIn(expected, label_text)


if __name__ == "__main__":
    unittest.main()
