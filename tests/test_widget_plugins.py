from __future__ import annotations

import os
import unittest
from datetime import date, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QLineEdit, QPushButton, QWidget

from desktop_tidy.ui.widget_plugins import BuiltinWidgetRegistry, UnknownWidgetPlugin
from desktop_tidy.widgets.dashboard_modules import DashboardModuleDefinition
from desktop_tidy.widgets.home import HomeDashboardWidget
from desktop_tidy.widgets.models import WidgetDefinition, WidgetVisualPreset
from desktop_tidy.widgets.registry import BuiltinWidgetRegistry as ModularWidgetRegistry


class WidgetPluginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _show_home_editor(self, widget: HomeDashboardWidget) -> None:
        widget.resize(1100, 700)
        widget.show()
        type(self).app.processEvents()
        editor = widget.findChild(QWidget, "HomeModuleEditor")
        self.assertIsNotNone(editor)
        editor.setVisible(True)
        type(self).app.processEvents()

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

    def test_registry_separates_global_home_from_standalone_widgets(self) -> None:
        registry = ModularWidgetRegistry()

        standalone_ids = [definition.id for definition in registry.available_standalone_widgets()]
        home = registry.home_plugin()

        self.assertEqual(standalone_ids, ["clock"])
        self.assertEqual(home.id, "home")
        self.assertEqual(home.definition().display_name, "主标签页")

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
        settings = plugin.default_settings()
        settings["recent_items"] = [
            {"name": "paper.pdf", "path": r"D:\Desktop\paper.pdf", "kind": "file"}
        ]
        widget = plugin.create_widget(settings)

        self.assertEqual(plugin.id, "home")
        self.assertEqual(definition.display_name, "主标签页")
        self.assertEqual(definition.visual.preset_id, "home-dashboard")
        self.assertIsInstance(widget, QWidget)
        self.assertEqual(widget.objectName(), "HomeDashboardWidgetRoot")
        label_text = "\n".join(label.text() for label in widget.findChildren(QLabel))
        button_text = "\n".join(button.text() for button in widget.findChildren(QPushButton))
        for expected in ("最近使用", "今日日程", "网络收藏", "月历", "天气"):
            self.assertIn(expected, label_text)
        self.assertIn("paper.pdf", button_text)
        self.assertNotIn("占位", label_text)
        self.assertNotIn("主标签页", label_text)
        self.assertIsNone(widget.findChild(QWidget, "HomeModuleCard-time"))
        self.assertIsNotNone(widget.findChild(QWidget, "HomeHeroPanel"))

    def test_home_modules_use_dashboard_definitions_not_widget_definitions(self) -> None:
        registry = ModularWidgetRegistry()
        plugin = registry.get("home")

        definitions = plugin.module_definitions()

        self.assertTrue(definitions)
        self.assertTrue(all(isinstance(entry, DashboardModuleDefinition) for entry in definitions))
        self.assertTrue(all(not isinstance(entry, WidgetDefinition) for entry in definitions))
        self.assertEqual(
            [entry.id for entry in definitions],
            ["recent", "schedule", "bookmarks", "calendar", "weather", "module_manager"],
        )
        self.assertEqual(definitions[0].size, "wide")
        self.assertEqual(definitions[0].preferred_span, 2)
        self.assertEqual(definitions[0].render_mode, "wide")
        self.assertEqual(definitions[1].empty_policy, "compact")
        self.assertGreater(definitions[0].priority, definitions[-1].priority)

    def test_home_module_definitions_create_real_module_widgets(self) -> None:
        registry = ModularWidgetRegistry()
        plugin = registry.get("home")
        settings = plugin.default_settings()
        settings["recent_items"] = [
            {"name": "paper.pdf", "path": r"D:\Desktop\paper.pdf", "kind": "file"}
        ]

        widgets = [definition.create_widget(settings) for definition in plugin.module_definitions()]

        self.assertTrue(widgets)
        self.assertTrue(all(isinstance(widget, QWidget) for widget in widgets))
        labels = "\n".join(
            label.text()
            for widget in widgets
            for label in widget.findChildren(QLabel)
        )
        self.assertIn("paper.pdf", labels)
        self.assertIn("今天没有提醒", labels)

    def test_home_module_fallback_factories_read_module_settings(self) -> None:
        registry = ModularWidgetRegistry()
        plugin = registry.get("home")
        settings = {
            "bookmarks": [{"title": "Legacy", "url": "https://legacy.test"}],
            "weather": {"city": "Legacy", "summary": "Old"},
            "module_settings": {
                "bookmarks": {
                    "bookmarks": [
                        {"title": "Module Link", "url": "https://module.test"}
                    ]
                },
                "weather": {
                    "weather": {"city": "Module City", "summary": "Module Weather"}
                },
            },
        }
        definitions = {entry.id: entry for entry in plugin.module_definitions()}

        widgets = [
            definitions["bookmarks"].create_widget(settings),
            definitions["weather"].create_widget(settings),
        ]

        labels = "\n".join(
            label.text()
            for widget in widgets
            for label in widget.findChildren(QLabel)
        )
        self.assertIn("Module Link", labels)
        self.assertIn("Module City", labels)
        self.assertIn("Module Weather", labels)
        self.assertNotIn("Legacy", labels)

    def test_home_schedule_fallback_module_only_shows_today_reminders(self) -> None:
        registry = ModularWidgetRegistry()
        plugin = registry.get("home")
        today = date.today()
        tomorrow = today + timedelta(days=1)
        settings = {
            "module_settings": {
                "schedule": {
                    "reminders": [
                        {"date": today.isoformat(), "text": "09:00 today"},
                        {"date": tomorrow.isoformat(), "text": "10:00 tomorrow"},
                    ]
                }
            }
        }
        schedule = next(
            definition for definition in plugin.module_definitions() if definition.id == "schedule"
        )

        widget = schedule.create_widget(settings)

        labels = "\n".join(label.text() for label in widget.findChildren(QLabel))
        self.assertIn("09:00 today", labels)
        self.assertNotIn("10:00 tomorrow", labels)

    def test_home_dashboard_treats_invalid_reminder_dates_as_today(self) -> None:
        widget = HomeDashboardWidget(
            {
                "module_settings": {
                    "schedule": {
                        "reminders": [
                            {"date": "not-a-date", "text": "09:00 recover config"}
                        ]
                    }
                },
                "reduced_motion": True,
            }
        )

        labels = "\n".join(label.text() for label in widget.findChildren(QLabel))
        self.assertIn("09:00 recover config", labels)

    def test_home_dashboard_can_render_registered_custom_module_without_core_branch(self) -> None:
        def factory(settings, definition, compact, render_mode):
            widget = QLabel(str(settings.get("custom_value", definition.empty_state)))
            widget.setObjectName("HomeModuleCard-custom")
            widget.setProperty("render_mode", render_mode)
            widget.setProperty("compact", compact)
            return widget

        custom = DashboardModuleDefinition(
            id="custom",
            display_name="自定义模块",
            size="normal",
            empty_state="没有内容",
            factory=factory,
        )

        widget = HomeDashboardWidget(
            {"modules": ["custom"], "custom_value": "模块内容", "reduced_motion": True},
            module_definitions=(custom,),
        )
        widget.resize(900, 500)
        widget.show()
        type(self).app.processEvents()

        module = widget.findChild(QLabel, "HomeModuleCard-custom")
        self.assertIsNotNone(module)
        self.assertEqual(module.text(), "模块内容")
        self.assertEqual(widget.property("dashboard_mode"), "medium")

    def test_home_plugin_default_settings_use_overridden_module_definitions(self) -> None:
        custom = DashboardModuleDefinition(
            id="custom",
            display_name="自定义模块",
            size="normal",
            empty_state="没有内容",
            default_visible=True,
        )

        class CustomHomePlugin(ModularWidgetRegistry().home_plugin().__class__):
            def module_definitions(self):
                return (custom,)

        plugin = CustomHomePlugin()

        self.assertEqual(plugin.default_settings()["modules"], ["custom"])

    def test_home_dashboard_reflows_at_width_breakpoints(self) -> None:
        registry = ModularWidgetRegistry()
        plugin = registry.get("home")
        widget = plugin.create_widget(plugin.default_settings())
        widget.show()
        type(self).app.processEvents()

        widget.resize(1100, 700)
        type(self).app.processEvents()
        self.assertEqual(widget.property("layout_columns"), 4)
        self.assertEqual(widget.property("dashboard_mode"), "wide")

        widget.resize(820, 700)
        type(self).app.processEvents()
        self.assertEqual(widget.property("layout_columns"), 2)
        self.assertEqual(widget.property("dashboard_mode"), "medium")

        widget.resize(640, 700)
        type(self).app.processEvents()
        self.assertEqual(widget.property("layout_columns"), 1)
        self.assertEqual(widget.property("dashboard_mode"), "compact")
        self.assertTrue(widget.property("compact_modules"))

    def test_home_dashboard_wide_layout_fills_final_row_and_compacts_empty_cards(self) -> None:
        registry = ModularWidgetRegistry()
        plugin = registry.get("home")
        widget = plugin.create_widget(plugin.default_settings())
        widget.resize(1500, 900)
        widget.show()
        type(self).app.processEvents()

        hero = widget.findChild(QWidget, "HomeHeroPanel")
        self.assertIsNotNone(hero)
        self.assertLessEqual(hero.maximumHeight(), 220)

        schedule = widget.findChild(QWidget, "HomeModuleCard-schedule")
        self.assertIsNotNone(schedule)
        self.assertTrue(schedule.property("compact_empty"))
        self.assertLessEqual(schedule.maximumHeight(), 150)

        grid = widget._module_grid
        positions = {
            grid.itemAt(index).widget().objectName(): grid.getItemPosition(index)
            for index in range(grid.count())
        }
        weather = widget.findChild(QWidget, "HomeModuleCard-weather")
        self.assertIsNotNone(weather)
        self.assertTrue(weather.property("compact_empty"))
        _row, _column, _row_span, weather_span = positions["HomeModuleCard-weather"]
        self.assertEqual(weather_span, 1)

    def test_home_dashboard_editor_updates_visible_module_order(self) -> None:
        registry = ModularWidgetRegistry()
        plugin = registry.get("home")
        widget = plugin.create_widget(plugin.default_settings())
        spy = QSignalSpy(widget.settings_changed)

        widget.set_module_visible("weather", False)

        self.assertEqual(spy.count(), 1)
        settings = spy.at(0)[0]
        self.assertNotIn("weather", settings["modules"])

        spy = QSignalSpy(widget.settings_changed)
        widget.set_module_visible("weather", True)
        widget.move_module("weather", -1)

        self.assertGreaterEqual(spy.count(), 2)
        latest = spy.at(spy.count() - 1)[0]
        modules = latest["modules"]
        self.assertLess(modules.index("weather"), len(modules) - 1)

    def test_home_dashboard_editor_ui_toggles_modules_and_can_close(self) -> None:
        widget = HomeDashboardWidget({"reduced_motion": True})
        settings_spy = QSignalSpy(widget.settings_changed)
        self._show_home_editor(widget)

        weather_toggle = widget.findChild(QCheckBox, "HomeModuleToggle-weather")
        done_button = widget.findChild(QPushButton, "HomeEditorDoneButton")
        editor = widget.findChild(QWidget, "HomeModuleEditor")
        self.assertIsNotNone(weather_toggle)
        self.assertIsNotNone(done_button)
        self.assertIsNotNone(editor)

        weather_toggle.click()
        type(self).app.processEvents()

        latest = settings_spy.at(settings_spy.count() - 1)[0]
        self.assertNotIn("weather", latest["modules"])
        self.assertIsNone(widget.findChild(QWidget, "HomeModuleCard-weather"))

        done_button.click()
        type(self).app.processEvents()

        self.assertFalse(editor.isVisible())

    def test_home_dashboard_editor_is_floating_and_bounded(self) -> None:
        widget = HomeDashboardWidget({"reduced_motion": True})
        widget.resize(1280, 760)
        widget.show()
        type(self).app.processEvents()

        edit_button = widget.findChild(QPushButton, "HomeEditButton")
        editor = widget.findChild(QWidget, "HomeModuleEditor")
        self.assertIsNotNone(edit_button)
        self.assertIsNotNone(editor)

        edit_button.click()
        type(self).app.processEvents()

        self.assertTrue(editor.isVisible())
        self.assertEqual(widget._root_layout.indexOf(editor), -1)
        self.assertLessEqual(editor.width(), 520)
        self.assertLess(editor.width(), widget.width() * 0.5)
        self.assertGreaterEqual(editor.x(), widget.width() - editor.width() - 40)
        self.assertLessEqual(editor.height(), widget.height() - 32)

    def test_home_main_cards_do_not_expose_editor_inputs(self) -> None:
        widget = HomeDashboardWidget({"reduced_motion": True})

        self.assertIsNone(widget.findChild(QLineEdit, "HomeReminderInput"))
        self.assertIsNone(widget.findChild(QLineEdit, "HomeBookmarkTitleInput"))
        self.assertIsNone(widget.findChild(QLineEdit, "HomeBookmarkUrlInput"))
        self.assertIsNone(widget.findChild(QLineEdit, "HomeWeatherCityInput"))
        self.assertIsNone(widget.findChild(QLineEdit, "HomeWeatherSummaryInput"))
        self.assertIsNone(widget.findChild(QPushButton, "HomeReminderAddButton"))
        self.assertIsNone(widget.findChild(QPushButton, "HomeBookmarkAddButton"))
        self.assertIsNone(widget.findChild(QPushButton, "HomeWeatherSaveButton"))

    def test_home_dashboard_reduced_motion_disables_entry_animation(self) -> None:
        registry = ModularWidgetRegistry()
        plugin = registry.get("home")

        widget = plugin.create_widget({"reduced_motion": True})

        self.assertTrue(widget.property("reduced_motion"))
        self.assertIsNone(widget.graphicsEffect())

    def test_home_dashboard_uses_readable_chinese_text(self) -> None:
        registry = ModularWidgetRegistry()
        plugin = registry.get("home")

        definition = plugin.definition()
        widget = plugin.create_widget(plugin.default_settings())
        label_text = "\n".join(label.text() for label in widget.findChildren(QLabel))

        self.assertEqual(definition.display_name, "主标签页")
        self.assertIn("今天", label_text)
        self.assertIn("最近使用", label_text)
        self.assertIn("今日日程", label_text)
        self.assertIn("网络收藏", label_text)
        self.assertIn("天气", label_text)
        self.assertNotIn("涓", label_text)
        self.assertNotIn("锟", label_text)

    def test_home_recent_item_button_exposes_path_tooltip_for_duplicate_names(self) -> None:
        widget = HomeDashboardWidget(
            {
                "recent_items": [
                    {"name": "report.pdf", "path": r"D:\Work\report.pdf", "kind": "file"},
                    {"name": "report.pdf", "path": r"E:\Archive\report.pdf", "kind": "file"},
                ],
                "reduced_motion": True,
            }
        )

        first = widget.findChild(QPushButton, "HomeRecentOpen-0")
        second = widget.findChild(QPushButton, "HomeRecentOpen-1")
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(first.text(), "report.pdf")
        self.assertIn(r"D:\Work\report.pdf", first.toolTip())
        self.assertIn(r"E:\Archive\report.pdf", second.toolTip())

    def test_home_recent_item_button_exposes_recent_source_in_tooltip(self) -> None:
        widget = HomeDashboardWidget(
            {
                "recent_items": [
                    {
                        "name": "windows.docx",
                        "path": r"D:\Desktop\windows.docx",
                        "kind": "file",
                        "source": "windows",
                    },
                    {
                        "name": "app.pdf",
                        "path": r"D:\Desktop\app.pdf",
                        "kind": "file",
                        "source": "app",
                    },
                ],
                "reduced_motion": True,
            }
        )

        windows_button = widget.findChild(QPushButton, "HomeRecentOpen-0")
        app_button = widget.findChild(QPushButton, "HomeRecentOpen-1")
        self.assertIsNotNone(windows_button)
        self.assertIsNotNone(app_button)
        self.assertIn("Windows Recent", windows_button.toolTip())
        self.assertIn("DesktopCleaner", app_button.toolTip())

    def test_home_recent_module_displays_windows_recent_source_hint(self) -> None:
        widget = HomeDashboardWidget(
            {
                "recent_items": [
                    {
                        "name": "windows.docx",
                        "path": r"D:\Desktop\windows.docx",
                        "kind": "file",
                        "source": "windows",
                    }
                ],
                "reduced_motion": True,
            }
        )

        label_text = "\n".join(label.text() for label in widget.findChildren(QLabel))
        self.assertIn("Windows 最近使用", label_text)

    def test_home_recent_item_button_emits_open_request(self) -> None:
        widget = HomeDashboardWidget(
            {
                "recent_items": [
                    {"name": "paper.pdf", "path": r"D:\Desktop\paper.pdf", "kind": "file"}
                ],
                "reduced_motion": True,
            }
        )
        spy = QSignalSpy(widget.item_open_requested)

        button = widget.findChild(QPushButton, "HomeRecentOpen-0")
        self.assertIsNotNone(button)
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)

        self.assertEqual(spy.count(), 1)
        self.assertEqual(spy.at(0)[0], r"D:\Desktop\paper.pdf")

    def test_home_recent_refresh_button_emits_request(self) -> None:
        widget = HomeDashboardWidget({"reduced_motion": True})
        spy = QSignalSpy(widget.recent_refresh_requested)

        button = widget.findChild(QPushButton, "HomeRecentRefreshButton")
        self.assertIsNotNone(button)
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)

        self.assertEqual(spy.count(), 1)

    def test_home_recent_clear_button_is_not_exposed_for_windows_recent(self) -> None:
        widget = HomeDashboardWidget({"reduced_motion": True})

        button = widget.findChild(QPushButton, "HomeRecentClearButton")
        self.assertIsNone(button)

    def test_home_bookmarks_can_add_open_and_delete(self) -> None:
        widget = HomeDashboardWidget({"reduced_motion": True})
        settings_spy = QSignalSpy(widget.settings_changed)
        open_spy = QSignalSpy(widget.url_open_requested)
        self._show_home_editor(widget)

        title_input = widget.findChild(QLineEdit, "HomeEditorBookmarkTitleInput")
        url_input = widget.findChild(QLineEdit, "HomeEditorBookmarkUrlInput")
        add_button = widget.findChild(QPushButton, "HomeEditorBookmarkAddButton")
        self.assertIsNotNone(title_input)
        self.assertIsNotNone(url_input)
        self.assertIsNotNone(add_button)

        title_input.setText("OpenAI")
        url_input.setText("https://openai.com")
        QTest.mouseClick(add_button, Qt.MouseButton.LeftButton)
        type(self).app.processEvents()

        self.assertGreaterEqual(settings_spy.count(), 1)
        latest = settings_spy.at(settings_spy.count() - 1)[0]
        self.assertEqual(latest["bookmarks"], [{"title": "OpenAI", "url": "https://openai.com"}])

        open_button = widget.findChild(QPushButton, "HomeBookmarkOpen-0")
        delete_button = widget.findChild(QPushButton, "HomeEditorBookmarkDelete-0")
        self.assertIsNotNone(open_button)
        self.assertIsNotNone(delete_button)

        QTest.mouseClick(open_button, Qt.MouseButton.LeftButton)
        self.assertEqual(open_spy.count(), 1)
        self.assertEqual(open_spy.at(0)[0], "https://openai.com")

        QTest.mouseClick(delete_button, Qt.MouseButton.LeftButton)
        type(self).app.processEvents()
        latest = settings_spy.at(settings_spy.count() - 1)[0]
        self.assertEqual(latest["bookmarks"], [])

    def test_home_bookmarks_update_existing_url_instead_of_duplicating(self) -> None:
        widget = HomeDashboardWidget({"reduced_motion": True})
        settings_spy = QSignalSpy(widget.settings_changed)
        self._show_home_editor(widget)

        title_input = widget.findChild(QLineEdit, "HomeEditorBookmarkTitleInput")
        url_input = widget.findChild(QLineEdit, "HomeEditorBookmarkUrlInput")
        add_button = widget.findChild(QPushButton, "HomeEditorBookmarkAddButton")
        self.assertIsNotNone(title_input)
        self.assertIsNotNone(url_input)
        self.assertIsNotNone(add_button)

        title_input.setText("OpenAI")
        url_input.setText("openai.com")
        QTest.mouseClick(add_button, Qt.MouseButton.LeftButton)
        type(self).app.processEvents()

        title_input = widget.findChild(QLineEdit, "HomeEditorBookmarkTitleInput")
        url_input = widget.findChild(QLineEdit, "HomeEditorBookmarkUrlInput")
        add_button = widget.findChild(QPushButton, "HomeEditorBookmarkAddButton")
        self.assertIsNotNone(title_input)
        self.assertIsNotNone(url_input)
        self.assertIsNotNone(add_button)
        title_input.setText("OpenAI Docs")
        url_input.setText("https://openai.com")
        QTest.mouseClick(add_button, Qt.MouseButton.LeftButton)
        type(self).app.processEvents()

        latest = settings_spy.at(settings_spy.count() - 1)[0]
        self.assertEqual(
            latest["bookmarks"],
            [{"title": "OpenAI Docs", "url": "https://openai.com"}],
        )

    def test_home_bookmarks_can_be_edited_from_editor(self) -> None:
        widget = HomeDashboardWidget(
            {
                "reduced_motion": True,
                "module_settings": {
                    "bookmarks": {
                        "bookmarks": [
                            {"title": "Docs", "url": "https://docs.test"},
                        ],
                    },
                },
            }
        )
        settings_spy = QSignalSpy(widget.settings_changed)
        self._show_home_editor(widget)

        title_input = widget.findChild(QLineEdit, "HomeEditorBookmarkTitle-0")
        url_input = widget.findChild(QLineEdit, "HomeEditorBookmarkUrl-0")
        save_button = widget.findChild(QPushButton, "HomeEditorBookmarkSave-0")
        self.assertIsNotNone(title_input)
        self.assertIsNotNone(url_input)
        self.assertIsNotNone(save_button)

        title_input.setText("Docs New")
        url_input.setText("docs-new.test")
        QTest.mouseClick(save_button, Qt.MouseButton.LeftButton)
        type(self).app.processEvents()

        latest = settings_spy.at(settings_spy.count() - 1)[0]
        expected = [{"title": "Docs New", "url": "https://docs-new.test"}]
        self.assertEqual(latest["bookmarks"], expected)
        self.assertEqual(latest["module_settings"]["bookmarks"]["bookmarks"], expected)

    def test_home_bookmarks_reject_invalid_urls_without_saving(self) -> None:
        widget = HomeDashboardWidget({"reduced_motion": True})
        settings_spy = QSignalSpy(widget.settings_changed)
        self._show_home_editor(widget)

        title_input = widget.findChild(QLineEdit, "HomeEditorBookmarkTitleInput")
        url_input = widget.findChild(QLineEdit, "HomeEditorBookmarkUrlInput")
        add_button = widget.findChild(QPushButton, "HomeEditorBookmarkAddButton")
        self.assertIsNotNone(title_input)
        self.assertIsNotNone(url_input)
        self.assertIsNotNone(add_button)

        title_input.setText("Broken")
        url_input.setText("not a url")
        QTest.mouseClick(add_button, Qt.MouseButton.LeftButton)
        type(self).app.processEvents()

        self.assertEqual(settings_spy.count(), 0)
        self.assertIsNone(widget.findChild(QPushButton, "HomeBookmarkOpen-0"))

    def test_home_bookmarks_read_module_settings_before_legacy_root_settings(self) -> None:
        widget = HomeDashboardWidget(
            {
                "bookmarks": [{"title": "Legacy", "url": "https://legacy.test"}],
                "module_settings": {
                    "bookmarks": {
                        "bookmarks": [{"title": "Module", "url": "https://module.test"}]
                    }
                },
                "reduced_motion": True,
            }
        )
        open_spy = QSignalSpy(widget.url_open_requested)

        button = widget.findChild(QPushButton, "HomeBookmarkOpen-0")
        self.assertIsNotNone(button)
        self.assertEqual(button.text(), "Module")
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)

        self.assertEqual(open_spy.count(), 1)
        self.assertEqual(open_spy.at(0)[0], "https://module.test")

    def test_home_bookmarks_editor_reads_module_settings_before_legacy_root_settings(self) -> None:
        widget = HomeDashboardWidget(
            {
                "bookmarks": [{"title": "Legacy", "url": "https://legacy.test"}],
                "module_settings": {
                    "bookmarks": {
                        "bookmarks": [{"title": "Module", "url": "https://module.test"}]
                    }
                },
                "reduced_motion": True,
            }
        )

        self._show_home_editor(widget)

        bookmark_title = widget.findChild(QLineEdit, "HomeEditorBookmarkTitle-0")
        self.assertIsNotNone(bookmark_title)
        self.assertEqual(bookmark_title.text(), "Module")
        self.assertNotEqual(bookmark_title.text(), "Legacy")

    def test_home_bookmarks_write_module_settings_and_legacy_root_settings(self) -> None:
        widget = HomeDashboardWidget({"reduced_motion": True})
        settings_spy = QSignalSpy(widget.settings_changed)
        self._show_home_editor(widget)

        title_input = widget.findChild(QLineEdit, "HomeEditorBookmarkTitleInput")
        url_input = widget.findChild(QLineEdit, "HomeEditorBookmarkUrlInput")
        add_button = widget.findChild(QPushButton, "HomeEditorBookmarkAddButton")
        self.assertIsNotNone(title_input)
        self.assertIsNotNone(url_input)
        self.assertIsNotNone(add_button)

        title_input.setText("Docs")
        url_input.setText("https://docs.test")
        add_button.click()
        type(self).app.processEvents()

        latest = settings_spy.at(settings_spy.count() - 1)[0]
        expected = [{"title": "Docs", "url": "https://docs.test"}]
        self.assertEqual(latest["bookmarks"], expected)
        self.assertEqual(latest["module_settings"]["bookmarks"]["bookmarks"], expected)

    def test_home_reminders_write_module_settings_and_legacy_root_settings(self) -> None:
        widget = HomeDashboardWidget(
            {"selected_date": "2026-06-07", "reduced_motion": True}
        )
        settings_spy = QSignalSpy(widget.settings_changed)
        self._show_home_editor(widget)

        reminder_input = widget.findChild(QLineEdit, "HomeEditorReminderInput")
        add_button = widget.findChild(QPushButton, "HomeEditorReminderAddButton")
        self.assertIsNotNone(reminder_input)
        self.assertIsNotNone(add_button)

        reminder_input.setText("09:00 Standup")
        add_button.click()
        type(self).app.processEvents()

        latest = settings_spy.at(settings_spy.count() - 1)[0]
        expected = [{"date": "2026-06-07", "text": "09:00 Standup"}]
        self.assertEqual(latest["reminders"], expected)
        self.assertEqual(latest["module_settings"]["schedule"]["reminders"], expected)

    def test_home_reminders_can_add_and_delete(self) -> None:
        widget = HomeDashboardWidget({"reduced_motion": True})
        settings_spy = QSignalSpy(widget.settings_changed)
        self._show_home_editor(widget)

        reminder_input = widget.findChild(QLineEdit, "HomeEditorReminderInput")
        add_button = widget.findChild(QPushButton, "HomeEditorReminderAddButton")
        self.assertIsNotNone(reminder_input)
        self.assertIsNotNone(add_button)

        reminder_input.setText("18:00 复盘")
        QTest.mouseClick(add_button, Qt.MouseButton.LeftButton)
        type(self).app.processEvents()

        latest = settings_spy.at(settings_spy.count() - 1)[0]
        self.assertEqual(
            latest["reminders"],
            [{"date": date.today().isoformat(), "text": "18:00 复盘"}],
        )

        delete_button = widget.findChild(QPushButton, "HomeEditorReminderDelete-0")
        self.assertIsNotNone(delete_button)
        QTest.mouseClick(delete_button, Qt.MouseButton.LeftButton)
        type(self).app.processEvents()

        latest = settings_spy.at(settings_spy.count() - 1)[0]
        self.assertEqual(latest["reminders"], [])

    def test_home_reminders_can_be_marked_done_and_hidden_from_schedule(self) -> None:
        today = date.today().isoformat()
        widget = HomeDashboardWidget(
            {
                "reduced_motion": True,
                "module_settings": {
                    "schedule": {
                        "reminders": [
                            {"date": today, "text": "09:00 standup"},
                        ],
                    },
                },
            }
        )
        settings_spy = QSignalSpy(widget.settings_changed)

        done_button = widget.findChild(QPushButton, "HomeReminderDone-0")
        self.assertIsNotNone(done_button)
        QTest.mouseClick(done_button, Qt.MouseButton.LeftButton)
        type(self).app.processEvents()

        latest = settings_spy.at(settings_spy.count() - 1)[0]
        expected = [{"date": today, "text": "09:00 standup", "done": True}]
        self.assertEqual(latest["reminders"], expected)
        self.assertEqual(latest["module_settings"]["schedule"]["reminders"], expected)
        schedule_card = widget.findChild(QWidget, "HomeModuleCard-schedule")
        self.assertIsNotNone(schedule_card)
        labels = "\n".join(label.text() for label in schedule_card.findChildren(QLabel))
        self.assertNotIn("09:00 standup", labels)

    def test_home_done_reminders_can_be_restored_from_editor(self) -> None:
        today = date.today().isoformat()
        widget = HomeDashboardWidget(
            {
                "reduced_motion": True,
                "module_settings": {
                    "schedule": {
                        "reminders": [
                            {"date": today, "text": "09:00 standup", "done": True},
                        ],
                    },
                },
            }
        )
        settings_spy = QSignalSpy(widget.settings_changed)
        self._show_home_editor(widget)

        restore_button = widget.findChild(QPushButton, "HomeEditorReminderRestore-0")
        self.assertIsNotNone(restore_button)
        editor_text = "\n".join(label.text() for label in widget.findChildren(QLabel))
        self.assertIn("已完成", editor_text)
        QTest.mouseClick(restore_button, Qt.MouseButton.LeftButton)
        type(self).app.processEvents()

        latest = settings_spy.at(settings_spy.count() - 1)[0]
        expected = [{"date": today, "text": "09:00 standup"}]
        self.assertEqual(latest["reminders"], expected)
        self.assertEqual(latest["module_settings"]["schedule"]["reminders"], expected)

    def test_home_reminders_can_be_edited_from_editor(self) -> None:
        today = date.today().isoformat()
        widget = HomeDashboardWidget(
            {
                "reduced_motion": True,
                "module_settings": {
                    "schedule": {
                        "reminders": [
                            {"date": today, "text": "09:00 standup", "done": True},
                        ],
                    },
                },
            }
        )
        settings_spy = QSignalSpy(widget.settings_changed)
        self._show_home_editor(widget)

        reminder_input = widget.findChild(QLineEdit, "HomeEditorReminderText-0")
        save_button = widget.findChild(QPushButton, "HomeEditorReminderSave-0")
        self.assertIsNotNone(reminder_input)
        self.assertIsNotNone(save_button)

        reminder_input.setText("10:30 review")
        QTest.mouseClick(save_button, Qt.MouseButton.LeftButton)
        type(self).app.processEvents()

        latest = settings_spy.at(settings_spy.count() - 1)[0]
        expected = [{"date": today, "text": "10:30 review", "done": True}]
        self.assertEqual(latest["reminders"], expected)
        self.assertEqual(latest["module_settings"]["schedule"]["reminders"], expected)

    def test_home_reminders_sort_timed_items_before_untimed_items(self) -> None:
        widget = HomeDashboardWidget({"reduced_motion": True})
        settings_spy = QSignalSpy(widget.settings_changed)
        self._show_home_editor(widget)

        reminder_input = widget.findChild(QLineEdit, "HomeEditorReminderInput")
        add_button = widget.findChild(QPushButton, "HomeEditorReminderAddButton")
        self.assertIsNotNone(reminder_input)
        self.assertIsNotNone(add_button)

        for reminder in ["20:30 review", "untimed note", "08:00 standup"]:
            reminder_input.setText(reminder)
            QTest.mouseClick(add_button, Qt.MouseButton.LeftButton)
            type(self).app.processEvents()

        latest = settings_spy.at(settings_spy.count() - 1)[0]
        self.assertEqual(
            latest["reminders"],
            [
                {"date": date.today().isoformat(), "text": "08:00 standup"},
                {"date": date.today().isoformat(), "text": "20:30 review"},
                {"date": date.today().isoformat(), "text": "untimed note"},
            ],
        )

    def test_home_calendar_selection_filters_and_adds_dated_reminders(self) -> None:
        today = date.today()
        target_date = (
            today.replace(day=today.day + 1)
            if today.day < 28
            else today.replace(day=today.day - 1)
        )
        widget = HomeDashboardWidget(
            {
                "reduced_motion": True,
                "reminders": [
                    {"date": today.isoformat(), "text": "08:00 today"},
                    {"date": target_date.isoformat(), "text": "09:00 tomorrow"},
                ],
            }
        )
        widget.resize(1100, 700)
        widget.show()
        type(self).app.processEvents()
        settings_spy = QSignalSpy(widget.settings_changed)

        target_button = widget.findChild(QPushButton, f"HomeCalendarDay-{target_date.isoformat()}")
        self.assertIsNotNone(target_button)
        QTest.mouseClick(target_button, Qt.MouseButton.LeftButton)
        type(self).app.processEvents()

        labels = "\n".join(
            label.text() for label in widget.findChildren(QLabel) if label.isVisible()
        )
        self.assertIn("09:00 tomorrow", labels)
        self.assertNotIn("08:00 today", labels)

        self._show_home_editor(widget)
        reminder_input = widget.findChild(QLineEdit, "HomeEditorReminderInput")
        add_button = widget.findChild(QPushButton, "HomeEditorReminderAddButton")
        self.assertIsNotNone(reminder_input)
        self.assertIsNotNone(add_button)
        reminder_input.setText("10:00 call")
        QTest.mouseClick(add_button, Qt.MouseButton.LeftButton)
        type(self).app.processEvents()

        latest = settings_spy.at(settings_spy.count() - 1)[0]
        self.assertEqual(latest["selected_date"], target_date.isoformat())
        self.assertIn(
            {"date": target_date.isoformat(), "text": "10:00 call"},
            latest["reminders"],
        )

    def test_home_calendar_selected_date_uses_module_settings_and_writes_legacy(self) -> None:
        widget = HomeDashboardWidget(
            {
                "reduced_motion": True,
                "selected_date": "2026-01-01",
                "module_settings": {
                    "calendar": {"selected_date": "2026-06-07"},
                },
            }
        )
        settings_spy = QSignalSpy(widget.settings_changed)

        self.assertEqual(widget._selected_date().isoformat(), "2026-06-07")

        widget._select_calendar_date("2026-06-08")

        latest = settings_spy.at(settings_spy.count() - 1)[0]
        self.assertEqual(latest["selected_date"], "2026-06-08")
        self.assertEqual(
            latest["module_settings"]["calendar"]["selected_date"],
            "2026-06-08",
        )

    def test_home_calendar_month_navigation_clamps_selected_day(self) -> None:
        widget = HomeDashboardWidget(
            {
                "reduced_motion": True,
                "selected_date": "2026-03-31",
            }
        )
        widget.resize(820, 700)
        type(self).app.processEvents()
        settings_spy = QSignalSpy(widget.settings_changed)

        next_button = widget.findChild(QPushButton, "HomeCalendarNextMonthButton")
        self.assertIsNotNone(next_button)
        QTest.mouseClick(next_button, Qt.MouseButton.LeftButton)
        type(self).app.processEvents()

        latest = settings_spy.at(settings_spy.count() - 1)[0]
        self.assertEqual(latest["selected_date"], "2026-04-30")
        self.assertIsNotNone(widget.findChild(QPushButton, "HomeCalendarDay-2026-04-30"))

    def test_home_calendar_today_button_returns_to_current_date(self) -> None:
        selected = "2026-03-31"
        if selected == date.today().isoformat():
            selected = "2026-04-30"
        widget = HomeDashboardWidget(
            {
                "reduced_motion": True,
                "selected_date": selected,
            }
        )
        settings_spy = QSignalSpy(widget.settings_changed)

        today_button = widget.findChild(QPushButton, "HomeCalendarTodayButton")
        self.assertIsNotNone(today_button)
        QTest.mouseClick(today_button, Qt.MouseButton.LeftButton)
        type(self).app.processEvents()

        latest = settings_spy.at(settings_spy.count() - 1)[0]
        self.assertEqual(latest["selected_date"], date.today().isoformat())

    def test_home_reminder_placeholder_uses_time_only_because_date_is_selected(self) -> None:
        widget = HomeDashboardWidget({"reduced_motion": True})
        self._show_home_editor(widget)

        reminder_input = widget.findChild(QLineEdit, "HomeEditorReminderInput")
        self.assertIsNotNone(reminder_input)

        self.assertTrue(reminder_input.placeholderText().startswith("例如：18:00"))

    def test_home_weather_settings_update_summary(self) -> None:
        widget = HomeDashboardWidget({"reduced_motion": True})
        settings_spy = QSignalSpy(widget.settings_changed)
        self._show_home_editor(widget)

        city_input = widget.findChild(QLineEdit, "HomeEditorWeatherCityInput")
        summary_input = widget.findChild(QLineEdit, "HomeEditorWeatherSummaryInput")
        save_button = widget.findChild(QPushButton, "HomeEditorWeatherSaveButton")
        self.assertIsNotNone(city_input)
        self.assertIsNotNone(summary_input)
        self.assertIsNotNone(save_button)

        city_input.setText("London")
        summary_input.setText("多云 18°C")
        QTest.mouseClick(save_button, Qt.MouseButton.LeftButton)
        type(self).app.processEvents()

        latest = settings_spy.at(settings_spy.count() - 1)[0]
        self.assertEqual(latest["weather"], {"city": "London", "summary": "多云 18°C"})
        labels = "\n".join(label.text() for label in widget.findChildren(QLabel))
        self.assertIn("London", labels)
        self.assertIn("多云 18°C", labels)

    def test_home_weather_reads_and_writes_module_settings(self) -> None:
        widget = HomeDashboardWidget(
            {
                "weather": {"city": "Legacy", "summary": "Old"},
                "module_settings": {
                    "weather": {"weather": {"city": "Module", "summary": "Sunny"}}
                },
                "reduced_motion": True,
            }
        )
        label_text = "\n".join(label.text() for label in widget.findChildren(QLabel))
        self.assertIn("Module", label_text)
        self.assertIn("Sunny", label_text)
        self.assertNotIn("Legacy", label_text)

        settings_spy = QSignalSpy(widget.settings_changed)
        self._show_home_editor(widget)
        city_input = widget.findChild(QLineEdit, "HomeEditorWeatherCityInput")
        summary_input = widget.findChild(QLineEdit, "HomeEditorWeatherSummaryInput")
        save_button = widget.findChild(QPushButton, "HomeEditorWeatherSaveButton")
        self.assertIsNotNone(city_input)
        self.assertIsNotNone(summary_input)
        self.assertIsNotNone(save_button)

        city_input.setText("London")
        summary_input.setText("Cloudy")
        save_button.click()
        type(self).app.processEvents()

        latest = settings_spy.at(settings_spy.count() - 1)[0]
        expected = {"city": "London", "summary": "Cloudy"}
        self.assertEqual(latest["weather"], expected)
        self.assertEqual(latest["module_settings"]["weather"]["weather"], expected)


    def test_home_weather_error_is_visible_in_weather_module(self) -> None:
        widget = HomeDashboardWidget(
            {
                "weather": {
                    "city": "Paris",
                    "summary": "Sunny · 20°C",
                    "error": "天气刷新失败，请稍后再试",
                },
                "reduced_motion": True,
            }
        )

        labels = "\n".join(label.text() for label in widget.findChildren(QLabel))
        self.assertIn("Paris", labels)
        self.assertIn("Sunny · 20°C", labels)
        self.assertIn("天气刷新失败，请稍后再试", labels)

    def test_home_weather_refresh_button_emits_city(self) -> None:
        widget = HomeDashboardWidget({"weather": {"city": "London"}, "reduced_motion": True})
        refresh_spy = QSignalSpy(widget.weather_refresh_requested)
        self._show_home_editor(widget)

        city_input = widget.findChild(QLineEdit, "HomeEditorWeatherCityInput")
        refresh_button = widget.findChild(QPushButton, "HomeEditorWeatherRefreshButton")
        self.assertIsNotNone(city_input)
        self.assertIsNotNone(refresh_button)

        city_input.setText("  London  ")
        QTest.mouseClick(refresh_button, Qt.MouseButton.LeftButton)

        self.assertEqual(refresh_spy.count(), 1)
        self.assertEqual(refresh_spy.at(0)[0], "London")

    def test_home_weather_save_city_without_summary_requests_refresh(self) -> None:
        widget = HomeDashboardWidget({"reduced_motion": True})
        settings_spy = QSignalSpy(widget.settings_changed)
        refresh_spy = QSignalSpy(widget.weather_refresh_requested)
        self._show_home_editor(widget)

        city_input = widget.findChild(QLineEdit, "HomeEditorWeatherCityInput")
        summary_input = widget.findChild(QLineEdit, "HomeEditorWeatherSummaryInput")
        save_button = widget.findChild(QPushButton, "HomeEditorWeatherSaveButton")
        self.assertIsNotNone(city_input)
        self.assertIsNotNone(summary_input)
        self.assertIsNotNone(save_button)

        city_input.setText("London")
        summary_input.clear()
        QTest.mouseClick(save_button, Qt.MouseButton.LeftButton)
        type(self).app.processEvents()

        latest = settings_spy.at(settings_spy.count() - 1)[0]
        self.assertEqual(latest["weather"], {"city": "London", "summary": ""})
        self.assertEqual(refresh_spy.count(), 1)
        self.assertEqual(refresh_spy.at(0)[0], "London")

    def test_home_weather_card_can_refresh_configured_city(self) -> None:
        widget = HomeDashboardWidget(
            {
                "weather": {"city": "London", "summary": "多云 18°C"},
                "reduced_motion": True,
            }
        )
        refresh_spy = QSignalSpy(widget.weather_refresh_requested)

        refresh_button = widget.findChild(QPushButton, "HomeWeatherRefreshInlineButton")
        self.assertIsNotNone(refresh_button)
        QTest.mouseClick(refresh_button, Qt.MouseButton.LeftButton)

        self.assertEqual(refresh_spy.count(), 1)
        self.assertEqual(refresh_spy.at(0)[0], "London")

    def test_home_weather_empty_card_opens_editor_for_city_setup(self) -> None:
        widget = HomeDashboardWidget({"reduced_motion": True})
        widget.resize(1100, 700)
        widget.show()
        type(self).app.processEvents()

        configure_button = widget.findChild(QPushButton, "HomeWeatherConfigureButton")
        self.assertIsNotNone(configure_button)
        self.assertFalse(widget.findChild(QWidget, "HomeModuleEditor").isVisible())
        QTest.mouseClick(configure_button, Qt.MouseButton.LeftButton)

        editor = widget.findChild(QWidget, "HomeModuleEditor")
        self.assertIsNotNone(editor)
        self.assertTrue(editor.isVisible())
        self.assertIsNotNone(widget.findChild(QLineEdit, "HomeEditorWeatherCityInput"))


if __name__ == "__main__":
    unittest.main()
