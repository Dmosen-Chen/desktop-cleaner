from __future__ import annotations

import os
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QComboBox

from desktop_tidy.domain.defaults import build_default_configuration
from desktop_tidy.ui.settings_window import SettingsWindow

_SUPPORTED_SECTIONS = ["基础设置", "面板管理", "桌面整理", "面板外观"]
_FORBIDDEN_TERMS = ("壁纸", "归档", "移动", "搜索", "AI", "同步")


_SUPPORTED_SECTIONS = _SUPPORTED_SECTIONS + ["面板历史", "功能面板", "诊断与恢复"]


class SettingsWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _make_window(self) -> SettingsWindow:
        return SettingsWindow(build_default_configuration(r"D:\Preview\Desktop"))

    def test_screen_selector_saves_target_group_screen_id(self) -> None:
        config = build_default_configuration(r"D:\Preview\Desktop")
        window = SettingsWindow(
            config,
            screen_options=[
                ("primary", "\u4e3b\u5c4f"),
                ("screen-1", "\u526f\u5c4f 1"),
            ],
        )

        self.assertEqual(window.selected_screen_id(), "primary")

        window._screen_card_buttons["screen-1"].click()
        window._save()

        self.assertEqual(config.panel_groups[0].screen_id, "screen-1")
        self.assertEqual(config.desktop.primary_screen_id, "screen-1")

    def test_visible_sections_match_supported_settings_surface(self) -> None:
        window = self._make_window()

        self.assertEqual(window.visible_section_names(), _SUPPORTED_SECTIONS)

    def test_recovery_history_and_widget_actions_are_exposed_as_signals(self) -> None:
        window = self._make_window()
        restore_spy = QSignalSpy(window.restore_desktop_requested)
        add_panel_spy = QSignalSpy(window.add_widget_panel_requested)
        add_tab_spy = QSignalSpy(window.add_widget_tab_requested)

        window._restore_desktop_button.click()
        window._add_clock_panel_button.click()
        window._add_clock_tab_button.click()

        self.assertEqual(restore_spy.count(), 1)
        self.assertEqual(add_panel_spy.at(0)[0], "clock")
        self.assertEqual(add_tab_spy.at(0)[0], "clock")

    def test_panel_management_exposes_screen_cards_and_create_actions(self) -> None:
        config = build_default_configuration(r"D:\Preview\Desktop")
        window = SettingsWindow(
            config,
            screen_options=[
                ("primary", "主屏"),
                ("screen-1", "副屏 1"),
            ],
        )
        add_panel_spy = QSignalSpy(window.add_item_panel_requested)
        add_tab_spy = QSignalSpy(window.add_item_tab_requested)
        identify_spy = QSignalSpy(window.identify_screens_requested)

        self.assertEqual(set(window._screen_card_buttons), {"primary", "screen-1"})
        self.assertTrue(window._screen_card_buttons["primary"].isChecked())
        window._screen_card_buttons["screen-1"].click()
        window._new_item_panel_button.click()
        window._new_item_tab_button.click()
        window._identify_screens_button.click()

        self.assertEqual(window.selected_screen_id(), "screen-1")
        self.assertEqual(add_panel_spy.count(), 1)
        self.assertEqual(add_tab_spy.count(), 1)
        self.assertEqual(identify_spy.count(), 1)

    def test_rules_page_uses_extension_tags_presets_and_organize_to_label(self) -> None:
        config = build_default_configuration(r"D:\Preview\Desktop")
        window = SettingsWindow(config)
        headers = [
            window._rules_table.horizontalHeaderItem(column).text()
            for column in range(window._rules_table.columnCount())
        ]

        self.assertEqual(headers, ["启用", "名称", "包含后缀", "整理到"])
        self.assertIn("新建面板", window.all_text())
        self.assertIn("新建标签", window.all_text())
        editor = window._rule_extension_editors["rule-images"]
        editor.apply_preset("代码")
        editor.add_extension(".webp")
        editor.remove_extension(".png")
        window._save()

        image_rule = next(rule for rule in config.rules if rule.id == "rule-images")
        self.assertIn(".py", image_rule.extensions)
        self.assertIn(".webp", image_rule.extensions)
        self.assertNotIn(".png", image_rule.extensions)

    def test_appearance_page_uses_swatch_buttons_and_percent_opacity_slider(self) -> None:
        config = build_default_configuration(r"D:\Preview\Desktop")
        window = SettingsWindow(config)

        self.assertNotIn("背景颜色", [child.placeholderText() for child in window.findChildren(type(window._desktop_path_edit))])
        self.assertIn("#4B5563", window._color_swatch_buttons)
        window._color_swatch_buttons["#4B5563"].click()
        window._opacity_slider.setValue(70)
        window._save()

        appearance = config.panel_groups[0].appearance
        self.assertEqual(appearance.background_color, "#4B5563")
        self.assertAlmostEqual(appearance.background_opacity, 0.70)
        self.assertEqual(window._opacity_slider.tickInterval(), 10)

    def test_diagnostics_page_exposes_status_logs_and_recovery_actions(self) -> None:
        window = self._make_window()
        refresh_spy = QSignalSpy(window.diagnostics_refresh_requested)
        restore_icons_spy = QSignalSpy(window.diagnostics_restore_icons_requested)
        refresh_takeover_spy = QSignalSpy(window.diagnostics_refresh_takeover_requested)
        open_logs_spy = QSignalSpy(window.diagnostics_open_logs_requested)
        export_spy = QSignalSpy(window.diagnostics_export_requested)
        snapshot = SimpleNamespace(
            desktop_path=r"D:\Preview\Desktop",
            config_path=r"C:\Users\me\AppData\Local\DesktopCleaner\config.json",
            log_path=r"C:\Users\me\AppData\Local\DesktopCleaner\logs\desktop-cleaner.log",
            executable_path=r"D:\code\tool\dist\DesktopCleaner.exe",
            takeover_enabled=True,
            restore_required=False,
            explorer_icons_hidden=True,
            explorer_icons_visible=False,
            group_count=2,
            tab_count=8,
            panel_window_count=2,
            primary_screen_id="primary",
            recent_errors=["2026 ERROR desktop_cleaner: boom"],
        )

        window.set_diagnostics(snapshot, ["line 1", "line 2"])
        window._diagnostics_refresh_button.click()
        window._diagnostics_restore_icons_button.click()
        window._diagnostics_refresh_takeover_button.click()
        window._diagnostics_open_logs_button.click()
        window._diagnostics_export_button.click()

        text = window.all_text()
        self.assertIn("诊断与恢复", window.visible_section_names())
        self.assertIn("桌面接管需要恢复", text)
        self.assertFalse(window._diagnostics_advanced_group.isChecked())
        self.assertTrue(window._diagnostics_advanced_content.isHidden())
        window._diagnostics_advanced_group.setChecked(True)
        self.assertFalse(window._diagnostics_advanced_content.isHidden())
        self.assertIn("D:\\Preview\\Desktop", window.all_text())
        self.assertIn("Explorer 图标可见：否", window.all_text())
        self.assertIn("line 2", text)
        self.assertEqual(refresh_spy.count(), 1)
        self.assertEqual(restore_icons_spy.count(), 1)
        self.assertEqual(refresh_takeover_spy.count(), 1)
        self.assertEqual(open_logs_spy.count(), 1)
        self.assertEqual(export_spy.count(), 1)

    def test_history_page_lists_snapshots_and_emits_restore_request(self) -> None:
        window = self._make_window()
        restore_spy = QSignalSpy(window.history_restore_requested)
        capture_spy = QSignalSpy(window.history_capture_preview_requested)
        snapshot = SimpleNamespace(
            id="layout-1",
            created_at="2026-05-27T12:00:00",
            reason="move",
            group_count=2,
            tab_count=7,
            preview_kind="layout",
            preview_path="",
            configuration=build_default_configuration(r"D:\Preview\Desktop"),
        )

        window.set_history_snapshots([snapshot])
        window._history_list.setCurrentRow(0)
        self.assertFalse(window._history_list.item(0).icon().isNull())
        window._restore_history_button.click()
        window._capture_history_preview_button.click()

        self.assertEqual(restore_spy.count(), 1)
        self.assertEqual(restore_spy.at(0)[0], "layout-1")
        self.assertEqual(capture_spy.count(), 1)
        self.assertEqual(capture_spy.at(0)[0], "layout-1")

    def test_widget_page_shows_preview_card_for_clock_panel(self) -> None:
        window = self._make_window()

        text = window.all_text()

        self.assertIn("时间面板预览", text)
        self.assertIn("添加为独立面板", text)
        self.assertIn("添加到当前面板组", text)

    def test_unsupported_features_are_not_exposed_in_ui_text(self) -> None:
        window = self._make_window()
        text = window.all_text()

        for term in _FORBIDDEN_TERMS:
            with self.subTest(term=term):
                self.assertNotIn(term, text)

        self.assertNotIn("暂未开放", text)

    def test_desktop_takeover_checkbox_is_now_available(self) -> None:
        window = self._make_window()

        self.assertEqual(window._takeover_checkbox.text(), "启用桌面接管")
        self.assertTrue(window._takeover_checkbox.isEnabled())

    def test_enabling_desktop_takeover_requires_confirmation(self) -> None:
        config = build_default_configuration(r"D:\Preview\Desktop")
        window = SettingsWindow(config, takeover_confirmation=lambda: False)
        window._takeover_checkbox.setChecked(True)

        saved_spy = QSignalSpy(window.config_saved)
        window._save()

        self.assertEqual(saved_spy.count(), 1)
        self.assertFalse(config.desktop.takeover_enabled)
        self.assertFalse(window._takeover_checkbox.isChecked())

    def test_confirmed_desktop_takeover_enable_is_saved(self) -> None:
        config = build_default_configuration(r"D:\Preview\Desktop")
        window = SettingsWindow(config, takeover_confirmation=lambda: True)
        window._takeover_checkbox.setChecked(True)

        window._save()

        self.assertTrue(config.desktop.takeover_enabled)

    def test_already_enabled_takeover_does_not_confirm_again(self) -> None:
        config = build_default_configuration(r"D:\Preview\Desktop")
        config.desktop.takeover_enabled = True

        def fail_if_called() -> bool:
            raise AssertionError("already-enabled takeover should not ask again")

        window = SettingsWindow(config, takeover_confirmation=fail_if_called)

        window._save()

        self.assertTrue(config.desktop.takeover_enabled)

    def test_panel_appearance_controls_reflect_configuration(self) -> None:
        config = build_default_configuration(r"D:\Preview\Desktop")
        config.panel_groups[0].appearance.background_color = "#336699"
        config.panel_groups[0].appearance.background_opacity = 0.42
        window = SettingsWindow(config)

        self.assertEqual(window.panel_background_color(), "#336699")
        self.assertAlmostEqual(window.panel_background_opacity(), 0.42)
        self.assertAlmostEqual(window.panel_opacity_minimum(), 0.10)
        self.assertAlmostEqual(window.panel_opacity_maximum(), 1.00)

    def test_default_panel_opacity_initializes_at_sixty_percent(self) -> None:
        window = self._make_window()

        self.assertAlmostEqual(window.panel_background_opacity(), 0.60)

    def test_save_rejects_invalid_editor_values_without_mutating_configuration(
        self,
    ) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            config = build_default_configuration(str(desktop.resolve()))
            original_payload = deepcopy(config.to_dict())
            window = SettingsWindow(config)

            window._desktop_path_edit.setText(r"relative\desktop")

            saved_spy = QSignalSpy(window.config_saved)
            validation_spy = QSignalSpy(window.validation_failed)

            window._save()

            self.assertEqual(saved_spy.count(), 0)
            self.assertEqual(validation_spy.count(), 1)
            self.assertTrue(str(validation_spy.at(0)[0]).strip())
            self.assertEqual(config.to_dict(), original_payload)

    def test_successful_save_hides_settings_window(self) -> None:
        window = self._make_window()
        window.show()
        type(self).app.processEvents()
        self.assertTrue(window.isVisible())

        saved_spy = QSignalSpy(window.config_saved)
        window._save()
        type(self).app.processEvents()

        self.assertEqual(saved_spy.count(), 1)
        self.assertFalse(
            window.isVisible(),
            "settings should hide after a successful save",
        )

    def test_save_repairs_default_rule_targets_and_hides_window(self) -> None:
        config = build_default_configuration(r"D:\Preview\Desktop")
        for rule in config.rules:
            rule.enabled = True
            rule.target_tab_id = ""
        window = SettingsWindow(config)
        window.show()
        type(self).app.processEvents()

        target_values: list[str] = []
        for row in range(window._rules_table.rowCount()):
            combo = window._rules_table.cellWidget(row, 3)
            self.assertIsInstance(combo, QComboBox)
            target_values.append(str(combo.currentData() or ""))

        self.assertIn("tab-folders", target_values)
        self.assertIn("tab-documents", target_values)
        self.assertIn("tab-images", target_values)

        saved_spy = QSignalSpy(window.config_saved)
        validation_spy = QSignalSpy(window.validation_failed)
        window._save()
        type(self).app.processEvents()

        self.assertEqual(validation_spy.count(), 0)
        self.assertEqual(saved_spy.count(), 1)
        self.assertFalse(window.isVisible())
        rules_by_id = {rule.id: rule for rule in config.rules}
        self.assertEqual(rules_by_id["rule-folders"].target_tab_id, "tab-folders")
        self.assertEqual(rules_by_id["rule-documents"].target_tab_id, "tab-documents")
        self.assertEqual(rules_by_id["rule-images"].target_tab_id, "tab-images")
        self.assertEqual(rules_by_id["rule-other"].target_tab_id, "tab-other")


    def test_close_event_hides_window_and_allows_reopen(self) -> None:
        """Close must hide the settings window; the same instance must be reusable."""
        window = self._make_window()
        window.show()
        type(self).app.processEvents()
        self.assertTrue(window.isVisible())

        window.close()
        type(self).app.processEvents()

        self.assertFalse(window.isVisible())

        window.show()
        type(self).app.processEvents()
        self.assertTrue(
            window.isVisible(),
            "settings window must be re-showable after close (hide, not destroy)",
        )


if __name__ == "__main__":
    unittest.main()
