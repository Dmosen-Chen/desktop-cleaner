from __future__ import annotations

import os
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QSize, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QComboBox

from desktop_tidy.domain.defaults import build_default_configuration
from desktop_tidy.domain.models import PanelGeometry
from desktop_tidy.domain.workspace import WorkspaceModel
from desktop_tidy.persistence.ui_preferences import UiPreferences
from desktop_tidy.services.screens import ScreenInfo
from desktop_tidy.version import APP_VERSION
from desktop_tidy.ui.panel_preview import PanelPreviewWidget
from desktop_tidy.ui.settings_window import SettingsWindow
from desktop_tidy.widgets.registry import BuiltinWidgetRegistry as ModularWidgetRegistry

_SUPPORTED_SECTIONS = ["面板", "分类规则"]
_FORBIDDEN_TERMS = ("壁纸", "归档", "移动", "搜索", "AI", "同步")


_SUPPORTED_SECTIONS = _SUPPORTED_SECTIONS + ["面板历史", "功能面板", "诊断与恢复", "其他"]


class SettingsWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def tearDown(self) -> None:
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, SettingsWindow):
                widget.hide()
                widget.deleteLater()
        type(self).app.processEvents()

    def _make_window(self) -> SettingsWindow:
        return SettingsWindow(build_default_configuration(r"D:\Preview\Desktop"))

    def test_basic_settings_are_folded_into_other_and_preview_selects_screen(self) -> None:
        config = build_default_configuration(r"D:\Preview\Desktop")
        window = SettingsWindow(
            config,
            screen_infos=[
                ScreenInfo("screen-1", "副屏 1", QRect(-1280, 120, 1280, 720)),
                ScreenInfo("primary", "主屏", QRect(0, 0, 1920, 1080)),
            ],
        )

        self.assertEqual(window.selected_screen_id(), "primary")
        self.assertNotIn("基础设置", window.visible_section_names())
        other_text = window._other_page_text()
        self.assertIn("桌面路径", other_text)
        self.assertIn("显示器", other_text)
        self.assertIn("桌面接管", other_text)
        self.assertIn("开机启动", other_text)
        self.assertIn("恢复桌面图标", other_text)
        window.show()
        window.raise_()
        window.activateWindow()
        type(self).app.processEvents()

        preview = window._panel_layout_preview
        self.assertEqual(preview.focused_screen_id(), "primary")
        self.assertEqual(preview.screen_z_order()[-1], "primary")

        secondary_rect = preview.screen_rect("screen-1")
        QApplication.sendEvent(
            preview,
            QMouseEvent(
                QEvent.Type.MouseMove,
                QPointF(secondary_rect.center()),
                QPointF(secondary_rect.center()),
                QPointF(preview.mapToGlobal(secondary_rect.center())),
                Qt.MouseButton.NoButton,
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
            ),
        )
        type(self).app.processEvents()
        self.assertEqual(preview.focused_screen_id(), "screen-1")
        self.assertEqual(preview.screen_z_order()[-1], "screen-1")

        secondary_rect = preview.screen_rect("screen-1")
        QTest.mouseClick(preview, Qt.MouseButton.LeftButton, pos=secondary_rect.center())
        window._save()

        self.assertEqual(config.panel_groups[0].screen_id, "screen-1")
        self.assertEqual(config.desktop.primary_screen_id, "screen-1")

    def test_visible_sections_match_supported_settings_surface(self) -> None:
        window = self._make_window()

        self.assertEqual(window.visible_section_names(), _SUPPORTED_SECTIONS)

    def test_settings_window_uses_translucent_console_shell(self) -> None:
        window = self._make_window()

        self.assertEqual(window.objectName(), "DesktopCleanerSettings")
        self.assertTrue(window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))
        self.assertTrue(bool(window.windowFlags() & Qt.WindowType.FramelessWindowHint))
        self.assertEqual(window.windowOpacity(), 1.0)
        self.assertIn("rgba", window.styleSheet())
        self.assertIn("background: rgba(9, 11, 15, 214)", window.styleSheet())
        self.assertIn("background: rgba(28, 31, 37, 236)", window.styleSheet())
        self.assertIn("QGroupBox", window.styleSheet())
        self.assertIn("selection-color: #F8FAFC", window.styleSheet())
        self.assertIn("QListWidget::item:selected", window.styleSheet())
        self.assertIn("color: #F8FAFC", window.styleSheet())
        self.assertIn("QWidget#SettingsTitleBar", window.styleSheet())
        self.assertIn("SettingsTitleIcon", window.styleSheet())
        self.assertEqual(window._title_label.text(), "设置")

    def test_custom_titlebar_close_hides_settings_without_quitting(self) -> None:
        window = self._make_window()
        window.show()
        type(self).app.processEvents()

        self.assertTrue(window.isVisible())
        window._title_close_button.click()
        type(self).app.processEvents()

        self.assertFalse(window.isVisible())
        self.assertFalse(QApplication.quitOnLastWindowClosed())

    def test_recovery_history_and_widget_actions_are_exposed_as_signals(self) -> None:
        window = self._make_window()
        restore_spy = QSignalSpy(window.restore_desktop_requested)
        add_panel_spy = QSignalSpy(window.add_widget_panel_requested)

        self.assertIn("恢复桌面图标", window._other_page_text())
        window._other_restore_desktop_button.click()
        window._add_clock_panel_button.click()

        self.assertEqual(restore_spy.count(), 1)
        self.assertEqual(add_panel_spy.at(0)[0], "clock")

    def test_other_page_exposes_manual_update_controls(self) -> None:
        window = self._make_window()
        check_spy = QSignalSpy(window.update_check_requested)
        download_spy = QSignalSpy(window.update_download_requested)
        open_folder_spy = QSignalSpy(window.update_open_folder_requested)
        replace_spy = QSignalSpy(window.update_replace_requested)

        text = window._other_page_text()
        self.assertEqual(window._update_group.title(), "软件更新")
        self.assertIn(f"当前版本：{APP_VERSION}", text)
        self.assertIn("检查更新", text)
        self.assertIn("下载更新", text)
        self.assertIn("打开更新文件夹", text)
        self.assertIn("替换并重启", text)
        self.assertFalse(window._update_download_button.isEnabled())
        self.assertFalse(window._update_replace_button.isEnabled())

        window._update_check_button.click()
        window._update_download_button.setEnabled(True)
        window._update_download_button.click()
        window._update_open_folder_button.click()
        window._update_replace_button.setEnabled(True)
        window._update_replace_button.click()

        self.assertEqual(check_spy.count(), 1)
        self.assertEqual(download_spy.count(), 1)
        self.assertEqual(open_folder_spy.count(), 1)
        self.assertEqual(replace_spy.count(), 1)

    def test_update_status_controls_download_and_dev_mode_replace(self) -> None:
        window = self._make_window()

        window.set_update_state(
            latest_version="1.0.13",
            message="发现新版本 1.0.13",
            update_available=True,
            download_ready=False,
            can_replace=False,
        )

        self.assertIn("最新版本：1.0.13", window._other_page_text())
        self.assertTrue(window._update_download_button.isEnabled())
        self.assertFalse(window._update_replace_button.isEnabled())
        self.assertIn("发现新版本", window._update_status_label.text())

        window.set_update_state(
            latest_version="1.0.13",
            message="下载完成。开发模式下请手动替换。",
            update_available=True,
            download_ready=True,
            can_replace=False,
        )

        self.assertTrue(window._update_download_button.isEnabled())
        self.assertFalse(window._update_replace_button.isEnabled())
        self.assertIn("开发模式", window._update_status_label.text())

    def test_panel_management_uses_compact_panel_rows_and_contextual_actions(self) -> None:
        config = build_default_configuration(r"D:\Preview\Desktop")
        model = WorkspaceModel(config)
        second_group = model.add_item_panel("资料")
        window = SettingsWindow(
            config,
            delete_confirmation=lambda _kind, _label: (True, False),
        )
        add_panel_spy = QSignalSpy(window.add_item_panel_requested)
        add_tab_spy = QSignalSpy(window.add_item_tab_requested)
        delete_panel_spy = QSignalSpy(window.delete_item_panel_requested)
        delete_tab_spy = QSignalSpy(window.delete_item_tab_requested)

        self.assertNotIn("group-", window._panel_management_page_text())
        self.assertEqual(window._management_add_button.text(), "+")
        self.assertEqual(window._panel_group_list.item(0).text(), "面板 1")
        self.assertIsNone(window._panel_group_list.itemWidget(window._panel_group_list.item(0)))
        self.assertEqual(
            window._panel_group_list.item(0).data(window.PANEL_COUNT_ROLE),
            6,
        )
        self.assertIn("位置：主屏", window._panel_summary_label.text())
        self.assertNotIn("大小", window._panel_summary_label.text())
        self.assertNotIn("0.", window._panel_summary_label.text())

        window._panel_group_list.setCurrentRow(1)
        self.assertEqual(window.selected_group_id(), second_group.id)
        window._management_add_button.click()
        window._management_delete_button.click()
        window._panel_tab_list.itemClicked.emit(window._panel_tab_list.item(0))
        window._management_add_button.click()
        window._management_delete_button.click()

        self.assertEqual(add_panel_spy.count(), 1)
        self.assertEqual(add_tab_spy.count(), 1)
        self.assertEqual(delete_panel_spy.count(), 1)
        self.assertEqual(delete_panel_spy.at(0)[0], second_group.id)
        self.assertEqual(delete_tab_spy.count(), 1)
        self.assertEqual(delete_tab_spy.at(0)[0], second_group.active_tab_id)

    def test_panel_management_double_click_renames_panel_and_tab_inline(self) -> None:
        config = build_default_configuration(r"D:\Preview\Desktop")
        window = SettingsWindow(config)
        changed_spy = QSignalSpy(window.management_metadata_changed)
        window._section_list.setCurrentRow(window.visible_section_names().index("面板"))
        window.show()
        type(self).app.processEvents()
        before = set(QApplication.topLevelWidgets())

        window._panel_group_list.itemDoubleClicked.emit(window._panel_group_list.item(0))
        editor = window._panel_inline_editor
        self.assertTrue(editor.isVisible())
        editor.setText("主工作区")
        editor.editingFinished.emit()

        window._panel_tab_list.itemDoubleClicked.emit(window._panel_tab_list.item(0))
        tab_editor = window._panel_inline_editor
        self.assertTrue(tab_editor.isVisible())
        tab_editor.setText("资料")
        tab_editor.editingFinished.emit()

        after = set(QApplication.topLevelWidgets())
        self.assertEqual(after - before, set())
        self.assertEqual(config.panel_groups[0].name, "主工作区")
        self.assertEqual(config.panel_tabs[0].name, "资料")
        self.assertEqual(changed_spy.count(), 2)

    def test_panel_layout_preview_clicks_and_drags_groups(self) -> None:
        config = build_default_configuration(r"D:\Preview\Desktop")
        model = WorkspaceModel(config)
        second_group = model.add_item_panel("资料")
        second_tab = model.add_tab(second_group.id, "发票")
        window = SettingsWindow(config)
        moved_spy = QSignalSpy(window.management_group_geometry_changed)
        window._section_list.setCurrentRow(window.visible_section_names().index("面板"))
        window.show()
        type(self).app.processEvents()

        preview = window._panel_layout_preview
        self.assertTrue(preview.selected_panel_detail_rect().isNull())
        group_rect = preview.group_rect(second_group.id)
        self.assertGreater(group_rect.width(), 0)

        QTest.mouseClick(preview, Qt.MouseButton.LeftButton, pos=group_rect.center())
        self.assertEqual(window.selected_group_id(), second_group.id)
        self.assertIn("发票", window._panel_management_page_text())
        window._panel_tab_list.setCurrentRow(window._panel_tab_list.count() - 1)
        self.assertEqual(window.selected_group_id(), second_group.id)
        self.assertEqual(
            window._panel_tab_list.currentItem().data(Qt.ItemDataRole.UserRole),
            second_tab.id,
        )
        drag_start = group_rect.center()
        drag_end = drag_start + QPoint(24, 18)
        QTest.mousePress(preview, Qt.MouseButton.LeftButton, pos=drag_start)
        QTest.mouseMove(preview, pos=drag_end)
        QTest.mouseRelease(preview, Qt.MouseButton.LeftButton, pos=drag_end)

        self.assertGreaterEqual(moved_spy.count(), 2)
        self.assertEqual(moved_spy.at(0)[0], second_group.id)
        self.assertFalse(moved_spy.at(0)[2])
        self.assertTrue(moved_spy.at(moved_spy.count() - 1)[2])
        self.assertNotEqual(second_group.geometry.rx, 0.04)

    def test_panel_preview_uses_real_desktop_coordinates_for_all_screens(self) -> None:
        config = build_default_configuration(r"D:\Preview\Desktop")
        model = WorkspaceModel(config)
        secondary = model.add_item_panel("副屏面板")
        config.panel_groups[0].screen_id = "primary"
        config.panel_groups[0].geometry = PanelGeometry(0.10, 0.10, 0.34, 0.32)
        secondary.screen_id = "secondary"
        secondary.geometry = PanelGeometry(0.50, 0.25, 0.36, 0.42)
        screens = [
            ScreenInfo("secondary", "副屏", QRect(-1280, 120, 1280, 720)),
            ScreenInfo("primary", "主屏", QRect(0, 0, 1920, 1080)),
        ]
        preview = PanelPreviewWidget(config, screens)
        preview.resize(900, 320)
        preview.show()
        type(self).app.processEvents()

        secondary_screen = preview.screen_rect("secondary")
        primary_screen = preview.screen_rect("primary")
        secondary_panel = preview.group_rect(secondary.id)
        primary_panel = preview.group_rect(config.panel_groups[0].id)

        self.assertLess(secondary_screen.right(), primary_screen.left())
        self.assertTrue(secondary_screen.contains(secondary_panel.center()))
        self.assertTrue(primary_screen.contains(primary_panel.center()))
        self.assertNotEqual(secondary_panel.center(), primary_panel.center())

    def test_panel_preview_uses_map_for_positions_and_detail_card_for_labels(self) -> None:
        config = build_default_configuration(r"D:\Preview\Desktop")
        config.panel_groups[0].geometry = PanelGeometry(0.06, 0.12, 0.38, 0.36)
        preview = PanelPreviewWidget(config, [ScreenInfo("primary", "主屏", QRect(0, 0, 1920, 1080))])
        preview.resize(900, 360)
        preview.show()
        type(self).app.processEvents()

        map_rect = preview.map_rect()
        detail_rect = preview.selected_panel_detail_rect()
        group_rect = preview.group_rect(config.panel_groups[0].id)
        tab_rect = preview.tab_rect(config.panel_groups[0].active_tab_id)

        self.assertTrue(map_rect.contains(group_rect.center()))
        self.assertLess(group_rect.bottom(), detail_rect.top())
        self.assertTrue(detail_rect.contains(tab_rect.center()))
        self.assertGreater(detail_rect.width(), group_rect.width())

    def test_panel_layout_preview_reorders_tabs_live_and_final(self) -> None:
        config = build_default_configuration(r"D:\Preview\Desktop")
        window = SettingsWindow(config)
        reorder_spy = QSignalSpy(window.management_tab_reordered)
        window._section_list.setCurrentRow(window.visible_section_names().index("面板"))
        window.show()
        type(self).app.processEvents()

        window._reorder_tab_from_preview("group-default", "tab-folders", 1, final=True)

        self.assertGreaterEqual(reorder_spy.count(), 1)
        self.assertTrue(reorder_spy.at(reorder_spy.count() - 1)[3])
        self.assertEqual(
            config.panel_groups[0].tab_ids[:3],
            ["tab-documents", "tab-folders", "tab-images"],
        )

    def test_rules_page_uses_master_detail_extension_editor(self) -> None:
        config = build_default_configuration(r"D:\Preview\Desktop")
        window = SettingsWindow(config)

        self.assertIsNone(getattr(window, "_rules_table", None))
        self.assertIn("分类规则", window.visible_section_names())
        self.assertIn("按文件类型显示到哪个标签", window._rules_page_text())
        self.assertIn("整理到", window._rules_page_text())
        self.assertIn("规则类型", window._rules_page_text())
        self.assertIn("当前预设", window._rules_page_text())
        self.assertIn("后缀列表", window._rules_page_text())
        self.assertIn("新增类型", window._rules_page_text())
        self.assertIn("删除类型", window._rules_page_text())
        self.assertIn("图片", window._rule_preset_buttons)
        self.assertLessEqual(window._rule_detail_layout.spacing(), 8)
        self.assertLessEqual(window._rule_detail_card.maximumHeight(), 520)
        self.assertGreaterEqual(window._rule_preset_flow.row_count_for_width(260), 2)
        window._rule_list.setCurrentRow(2)
        editor = window._rule_extension_editor
        window._rule_preset_buttons["代码"].click()
        editor.add_extension(".webp")
        editor.remove_extension(".png")
        window._save()

        image_rule = next(rule for rule in config.rules if rule.id == "rule-images")
        self.assertIn(".py", image_rule.extensions)
        self.assertIn(".webp", image_rule.extensions)
        self.assertNotIn(".png", image_rule.extensions)

    def test_selecting_folder_rule_does_not_open_extra_windows(self) -> None:
        config = build_default_configuration(r"D:\Preview\Desktop")
        window = SettingsWindow(config)
        window._section_list.setCurrentRow(window.visible_section_names().index("分类规则"))
        window.show()
        type(self).app.processEvents()
        before = set(QApplication.topLevelWidgets())
        size_before = window.size()

        window._rule_list.setCurrentRow(0)
        type(self).app.processEvents()

        after = set(QApplication.topLevelWidgets())
        self.assertEqual(after - before, set())
        self.assertEqual(window.size(), size_before)
        self.assertFalse(window._rule_extension_panel.isVisible())
        self.assertIn("按文件夹类型整理", window._rules_page_text())
        window._rule_list.setCurrentRow(2)
        type(self).app.processEvents()
        self.assertTrue(window._rule_extension_panel.isVisible())
        window._rule_list.setCurrentRow(1)
        window._rule_preset_buttons["文档"].click()
        type(self).app.processEvents()
        self.assertTrue(window._rule_extension_editor.is_flow_layout_enabled())
        self.assertGreaterEqual(window._rule_extension_editor.chip_row_count_for_width(360), 2)
        self.assertEqual(
            window._rule_extension_editor.scroll_height_range(),
            (112, 112),
        )
        stable_top_levels = set(QApplication.topLevelWidgets())
        for row in range(window._rule_list.count()):
            window._rule_list.setCurrentRow(row)
            for button in window._rule_preset_buttons.values():
                button.click()
            type(self).app.processEvents()
        self.assertEqual(set(QApplication.topLevelWidgets()) - stable_top_levels, set())

    def test_appearance_page_uses_swatch_slider_and_percent_spinbox(self) -> None:
        config = build_default_configuration(r"D:\Preview\Desktop")
        window = SettingsWindow(config)

        self.assertNotIn("面板外观", window.visible_section_names())
        self.assertNotIn("背景颜色", [child.placeholderText() for child in window.findChildren(type(window._desktop_path_edit))])
        self.assertIn("#4B5563", window._color_swatch_buttons)
        window._color_swatch_buttons["#4B5563"].click()
        window._opacity_slider.setValue(70)
        self.assertEqual(window._opacity_spinbox.value(), 70)
        window._opacity_spinbox.setValue(40)
        self.assertEqual(window._opacity_slider.value(), 40)
        window._save()

        appearance = config.panel_groups[0].appearance
        self.assertEqual(appearance.background_color, "#4B5563")
        self.assertAlmostEqual(appearance.background_opacity, 0.40)
        self.assertEqual(window._opacity_slider.tickInterval(), 10)

    def test_custom_classification_type_creates_rule_and_label_but_delete_keeps_label(self) -> None:
        config = build_default_configuration(r"D:\Preview\Desktop")
        window = SettingsWindow(config)

        window._custom_type_name_edit.setText("代码")
        window._create_custom_type_button.click()

        created_tab = next(tab for tab in config.panel_tabs if tab.name == "代码")
        created_rule = next(rule for rule in config.rules if rule.name == "代码")
        fallback_order = next(rule.order for rule in config.rules if rule.matcher_kind == "fallback")
        self.assertEqual(created_tab.group_id, config.panel_groups[0].id)
        self.assertEqual(created_tab.content_kind, "items")
        self.assertEqual(created_rule.matcher_kind, "extension")
        self.assertTrue(created_rule.enabled)
        self.assertEqual(created_rule.target_tab_id, created_tab.id)
        self.assertLess(created_rule.order, fallback_order)

        for row in range(window._rule_list.count()):
            item = window._rule_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == created_rule.id:
                window._rule_list.setCurrentRow(row)
                break
        window._delete_custom_rule_button.click()

        self.assertFalse(any(rule.id == created_rule.id for rule in config.rules))
        self.assertTrue(any(tab.id == created_tab.id for tab in config.panel_tabs))
        self.assertEqual(config.panel_groups[0].tab_ids[-1], created_tab.id)

    def test_deleted_custom_type_target_is_hidden_from_classification_targets(self) -> None:
        config = build_default_configuration(r"D:\Preview\Desktop")
        window = SettingsWindow(config)

        window._custom_type_name_edit.setText("代码")
        window._create_custom_type_button.click()
        created_tab = next(tab for tab in config.panel_tabs if tab.name == "代码")
        created_rule = next(rule for rule in config.rules if rule.name == "代码")

        window._select_rule_by_id(created_rule.id)
        window._delete_custom_rule_button.click()
        window._select_rule_by_id("rule-documents")

        combo_values = {
            str(window._rule_target_combo.itemData(index) or "")
            for index in range(window._rule_target_combo.count())
        }
        self.assertTrue(any(tab.id == created_tab.id for tab in config.panel_tabs))
        self.assertNotIn(created_tab.id, combo_values)

    def test_appearance_changes_emit_live_preview_and_debounced_save(self) -> None:
        config = build_default_configuration(r"D:\Preview\Desktop")
        window = SettingsWindow(config)
        live_spy = QSignalSpy(window.appearance_live_changed)
        save_spy = QSignalSpy(window.appearance_live_save_requested)

        window._color_swatch_buttons["#4B5563"].click()
        window._opacity_slider.setValue(70)
        QTest.qWait(350)

        self.assertGreaterEqual(live_spy.count(), 2)
        self.assertEqual(live_spy.at(live_spy.count() - 1)[0], config.panel_groups[0].id)
        self.assertEqual(live_spy.at(live_spy.count() - 1)[1], "#4B5563")
        self.assertAlmostEqual(float(live_spy.at(live_spy.count() - 1)[2]), 0.70)
        self.assertGreaterEqual(save_spy.count(), 1)
        self.assertEqual(save_spy.at(save_spy.count() - 1)[0], config.panel_groups[0].id)

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
        self.assertGreaterEqual(window._history_card_preview_size.width(), 420)
        self.assertGreaterEqual(window._history_card_preview_size.height(), 240)
        self.assertIn(window._history_grid_columns, (1, 2))
        self.assertEqual(len(window._history_cards), 1)
        self.assertIn("文件夹", window._history_cards[0].preview_tab_names)
        self.assertIn("文档", window._history_cards[0].preview_tab_names)
        self.assertFalse(hasattr(window._history_cards[0], "capture_button"))
        self.assertIn("移动或缩放", window.all_text())
        self.assertNotIn("panel-change", window.all_text())
        window._history_cards[0].restore_button.click()

        self.assertEqual(restore_spy.count(), 1)
        self.assertEqual(restore_spy.at(0)[0], "layout-1")

    def test_history_grid_uses_one_to_three_responsive_columns(self) -> None:
        window = self._make_window()
        snapshots = [
            SimpleNamespace(
                id=f"layout-{index}",
                created_at="2026-05-27T12:00:00",
                reason="appearance-change",
                group_count=1,
                tab_count=6,
                preview_kind="layout",
                preview_path="",
                configuration=build_default_configuration(r"D:\Preview\Desktop"),
            )
            for index in range(4)
        ]

        window.resize(720, 600)
        window.set_history_snapshots(snapshots)
        self.assertEqual(window._history_grid_columns, 1)

        window.resize(1180, 600)
        window.set_history_snapshots(snapshots)
        self.assertEqual(window._history_grid_columns, 2)

        window.resize(1680, 600)
        window.set_history_snapshots(snapshots)
        self.assertEqual(window._history_grid_columns, 3)

    def test_history_grid_reflows_when_window_width_changes(self) -> None:
        window = self._make_window()
        snapshots = [
            SimpleNamespace(
                id=f"layout-{index}",
                created_at="2026-05-27T12:00:00",
                reason="move",
                group_count=1,
                tab_count=6,
                preview_kind="layout",
                preview_path="",
                configuration=build_default_configuration(r"D:\Preview\Desktop"),
            )
            for index in range(4)
        ]
        window.resize(720, 600)
        window.show()
        type(self).app.processEvents()
        window.set_history_snapshots(snapshots)
        self.assertEqual(window._history_grid_columns, 1)

        window.resize(1180, 600)
        type(self).app.processEvents()

        self.assertEqual(window._history_grid_columns, 2)

    def test_widget_page_shows_preview_card_for_clock_panel(self) -> None:
        window = self._make_window()
        clock_definition = ModularWidgetRegistry().get("clock").definition()

        text = window.all_text()

        self.assertIn("时间面板", text)
        self.assertNotIn("时间面板预览", text)
        self.assertIn("#", window._clock_widget_card.styleSheet())
        self.assertIn(clock_definition.preview_background, window._clock_widget_preview.styleSheet())
        self.assertIn(clock_definition.preview_foreground, window._clock_widget_preview.styleSheet())
        self.assertEqual(window._add_clock_panel_button.text(), "+")
        self.assertNotIn("添加到当前面板组", text)
        self.assertEqual(window._clock_widget_card.width(), 320)
        self.assertEqual(window._clock_widget_card.height(), 190)

    def test_other_page_resets_delete_confirmation_preferences(self) -> None:
        preferences = UiPreferences(confirm_delete_panel=False, confirm_delete_tab=False)
        window = SettingsWindow(
            build_default_configuration(r"D:\Preview\Desktop"),
            ui_preferences=preferences,
        )
        changed_spy = QSignalSpy(window.ui_preferences_changed)
        window._section_list.setCurrentRow(window.visible_section_names().index("其他"))
        window.show()
        type(self).app.processEvents()

        window._reset_delete_confirmations_button.click()

        self.assertTrue(preferences.confirm_delete_panel)
        self.assertTrue(preferences.confirm_delete_tab)
        self.assertEqual(changed_spy.count(), 1)
        self.assertGreater(
            window._reset_delete_confirmations_button.geometry().x(),
            window.width() // 2,
        )

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
        for row in range(window._rule_list.count()):
            window._rule_list.setCurrentRow(row)
            combo = window._rule_target_combo
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
