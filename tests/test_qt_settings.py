from __future__ import annotations

import os
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QComboBox

from desktop_tidy.domain.defaults import build_default_configuration
from desktop_tidy.ui.settings_window import SettingsWindow

_SUPPORTED_SECTIONS = ["基础设置", "桌面分区", "桌面整理", "面板外观"]
_FORBIDDEN_TERMS = ("壁纸", "归档", "移动", "搜索", "AI", "同步")


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

        index = window._screen_combo.findData("screen-1")
        self.assertGreaterEqual(index, 0)
        window._screen_combo.setCurrentIndex(index)
        window._save()

        self.assertEqual(config.panel_groups[0].screen_id, "screen-1")
        self.assertEqual(config.desktop.primary_screen_id, "screen-1")

    def test_visible_sections_match_supported_settings_surface(self) -> None:
        window = self._make_window()

        self.assertEqual(window.visible_section_names(), _SUPPORTED_SECTIONS)

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
        self.assertGreaterEqual(window.panel_opacity_minimum(), 0.18)
        self.assertLessEqual(window.panel_opacity_maximum(), 0.95)

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
            window._color_edit.setText("not-a-color")

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
