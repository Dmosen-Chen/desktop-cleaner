from __future__ import annotations

import os
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QLineEdit, QPushButton, QWidget

from desktop_tidy.domain.defaults import build_default_configuration
from desktop_tidy.domain.models import Configuration, PanelGeometry
from desktop_tidy.domain.workspace import WorkspaceModel
from desktop_tidy.services.desktop_index import IndexedItem
from desktop_tidy.ui.panel_group import PanelGroupWidget, _ResizeRegion


def make_group_widget(
    desktop_path: str | Path = r"D:\Preview\Desktop",
    *,
    workspace: WorkspaceModel | None = None,
) -> tuple[PanelGroupWidget, WorkspaceModel]:
    config = build_default_configuration(desktop_path)
    model = workspace or WorkspaceModel(config)
    group = model.group("group-default")
    widget = PanelGroupWidget(group, model.config.panel_tabs, workspace=model)
    return widget, model


def toolbar_buttons(widget: PanelGroupWidget) -> set[QPushButton]:
    buttons = {
        widget.collapse_button,
        widget.lock_button,
        widget.add_button,
        widget.delete_button,
        widget.more_button,
    }
    organize_button = getattr(widget, "organize_button", None)
    if organize_button is not None:
        buttons.add(organize_button)
    return buttons


def button_tooltip(button: QPushButton) -> str:
    return button.toolTip().strip()


def button_has_icon(button: QPushButton) -> bool:
    return not button.icon().isNull()


def tooltip_mentions(tooltip: str, *fragments: str) -> bool:
    if not tooltip:
        return False
    lowered = tooltip.casefold()
    return any(fragment.casefold() in lowered for fragment in fragments)


def lock_uses_icon_without_glyph(button: QPushButton) -> bool:
    return button_has_icon(button) and button.text().strip() == ""


def lock_icon_cache_key(button: QPushButton) -> int:
    return button.icon().cacheKey()


def tab_buttons(widget: PanelGroupWidget) -> list[QPushButton]:
    excluded = toolbar_buttons(widget)
    return [button for button in widget.findChildren(QPushButton) if button not in excluded]


def find_tab_button(widget: PanelGroupWidget, label: str) -> QPushButton:
    return next(button for button in tab_buttons(widget) if label in button.text())


def visible_label_texts(widget: QWidget) -> list[str]:
    return [label.text() for label in widget.findChildren(QLabel) if label.isVisible()]


def simulate_tab_drag_release_at_local_point(
    widget: PanelGroupWidget,
    tab_label: str,
    release_local: QPoint,
) -> None:
    """Drive tab-button press/move/release through the widget event path."""
    tab_button = find_tab_button(widget, tab_label)
    start = tab_button.rect().center()
    QTest.mousePress(tab_button, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(tab_button, pos=start + QPoint(12, 0))
    QTest.mouseMove(widget, pos=release_local)
    QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=release_local)


def simulate_tab_drag_release_at_global_point(
    widget: PanelGroupWidget,
    tab_label: str,
    release_global: QPoint,
) -> None:
    release_local = widget.mapFromGlobal(release_global)
    simulate_tab_drag_release_at_local_point(widget, tab_label, release_local)


def simulate_header_drag_release_at_global_point(
    widget: PanelGroupWidget,
    release_global: QPoint,
    *,
    press_local: QPoint | None = None,
) -> None:
    """Drive header drag release; re-map release local after live move updates widget geometry."""
    start = press_local or QPoint(80, 12)
    QTest.mousePress(widget, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(widget, pos=widget.mapFromGlobal(release_global))
    app = QApplication.instance()
    if app is not None:
        app.processEvents()
    release_local = widget.mapFromGlobal(release_global)
    QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=release_local)


def simulate_tab_drag_to_local_point_without_release(
    widget: PanelGroupWidget,
    tab_label: str,
    move_local: QPoint,
) -> None:
    """Press tab, exceed drag threshold, move to local point without releasing."""
    tab_button = find_tab_button(widget, tab_label)
    start = tab_button.rect().center()
    QTest.mousePress(tab_button, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(tab_button, pos=start + QPoint(12, 0))
    QTest.mouseMove(widget, pos=move_local)


def simulate_header_drag_to_local_point_without_release(
    widget: PanelGroupWidget,
    move_local: QPoint,
    *,
    press_local: QPoint | None = None,
) -> None:
    """Press header, move beyond threshold, stop before release."""
    start = press_local or QPoint(80, 12)
    QTest.mousePress(widget, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(widget, pos=move_local)


class PanelGroupWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_activate_tab_switches_active_content(self) -> None:
        widget, _model = make_group_widget()

        widget.activate_tab("tab-images")

        self.assertEqual(widget.active_tab_id, "tab-images")
        self.assertIn("图片", widget.active_tab_title())

    def test_widget_tab_shows_clock_content_and_hides_item_grid(self) -> None:
        config = build_default_configuration(r"D:\Preview\Desktop")
        model = WorkspaceModel(config)
        tab = model.add_widget_tab("group-default", "clock", name="时间")
        widget = PanelGroupWidget(
            model.group("group-default"),
            model.config.panel_tabs,
            workspace=model,
        )

        widget.activate_tab(tab.id)
        widget.show()
        type(self).app.processEvents()

        self.assertFalse(widget.item_grid.isVisible())
        self.assertTrue(any(":" in text for text in visible_label_texts(widget)))
        self.assertFalse(widget.organize_button.isEnabled())
        clock_widget = widget.findChild(QWidget, "ClockWidgetRoot")
        self.assertIsNotNone(clock_widget)
        self.assertNotIn("qlineargradient", clock_widget.styleSheet())
        self.assertNotIn("border-radius: 16px", clock_widget.styleSheet())

    def test_tab_button_click_switches_active_tab_without_drag(self) -> None:
        """Plain tab click must switch content; drag-detection must not swallow clicks."""
        widget, _model = make_group_widget()
        widget.resize(640, 480)
        widget.show()
        type(self).app.processEvents()

        self.assertEqual(widget.active_tab_id, "tab-folders")

        images_tab = find_tab_button(widget, "图片")
        QTest.mouseClick(images_tab, Qt.MouseButton.LeftButton)
        type(self).app.processEvents()

        self.assertEqual(widget.active_tab_id, "tab-images")
        self.assertIn("图片", widget.active_tab_title())

    def test_tab_buttons_cover_group_tabs(self) -> None:
        widget, model = make_group_widget()
        group = model.group("group-default")

        self.assertEqual(widget.tab_button_ids(), group.tab_ids)

    def test_dragging_tab_inside_panel_reorders_tabs(self) -> None:
        widget, model = make_group_widget()
        widget.resize(760, 420)
        widget.show()
        type(self).app.processEvents()

        images_button = find_tab_button(widget, "图片")
        release_local = images_button.mapTo(widget, images_button.rect().center()) - QPoint(1, 0)
        reordered = QSignalSpy(widget.tab_reordered)
        widget._drag_tab_id = "tab-folders"
        widget._tab_drag_active = True
        widget._reorder_dragged_tab_at(release_local, final=True)
        type(self).app.processEvents()

        self.assertEqual(
            model.group("group-default").tab_ids[:3],
            ["tab-documents", "tab-folders", "tab-images"],
        )
        self.assertEqual(reordered.count(), 1)

    def test_toolbar_exposes_add_delete_more_lock_and_collapse_controls(self) -> None:
        widget, _model = make_group_widget()

        self.assertIsNotNone(widget.add_button)
        self.assertIsNotNone(widget.delete_button)
        self.assertIsNotNone(widget.more_button)
        self.assertIsNotNone(widget.lock_button)
        self.assertIsNotNone(widget.collapse_button)

    def test_toolbar_exposes_one_click_organize_control(self) -> None:
        widget, _model = make_group_widget()

        self.assertTrue(
            hasattr(widget, "organize_button"),
            "titlebar must expose a one-click organize button",
        )
        self.assertTrue(
            hasattr(widget, "organize_requested"),
            "one-click organize must be wired through a dedicated signal",
        )

    def test_default_titlebar_toolbar_uses_icon_like_visual_contract(self) -> None:
        """M2 titlebar: icon-like controls with accessible tooltips, not legacy text glyphs."""
        widget, _model = make_group_widget()
        widget.show()
        type(self).app.processEvents()

        lock = widget.lock_button
        delete = widget.delete_button
        collapse = widget.collapse_button
        add = widget.add_button
        more = widget.more_button

        self.assertTrue(
            lock_uses_icon_without_glyph(lock),
            msg=(
                "unlocked lock control must use a non-null QIcon with no glyph text "
                f"(emoji/unicode fallback is not acceptable); "
                f"got text={lock.text()!r} icon_null={lock.icon().isNull()}"
            ),
        )
        self.assertTrue(
            tooltip_mentions(button_tooltip(lock), "锁定", "lock"),
            msg=f"lock control needs a lock-action tooltip; got {button_tooltip(lock)!r}",
        )

        self.assertTrue(
            button_has_icon(delete),
            msg="delete control must use a trash-can icon instead of text-only 删",
        )
        self.assertNotIn(
            "删",
            delete.text(),
            msg="delete control must not display legacy text 删",
        )

        self.assertTrue(
            button_has_icon(collapse),
            msg=(
                "collapse control must use an arrow icon for expand/collapse state; "
                f"got text={collapse.text()!r}"
            ),
        )
        self.assertTrue(
            tooltip_mentions(button_tooltip(collapse), "收起", "collapse", "fold"),
            msg=f"expanded collapse control needs a collapse tooltip; got {button_tooltip(collapse)!r}",
        )

        self.assertEqual(add.text(), "+")

        self.assertEqual(
            more.text(),
            "...",
            msg="more control must show literal ASCII ellipsis ...",
        )
        self.assertTrue(
            tooltip_mentions(
                button_tooltip(more),
                "更多",
                "其它",
                "设置",
                "more",
                "menu",
            ),
            msg=f"more control needs a descriptive tooltip; got {button_tooltip(more)!r}",
        )

    def test_titlebar_lock_and_collapse_controls_update_visual_state_on_click(self) -> None:
        """M2 titlebar: toggles update lock/collapse indicators and tooltips in place."""
        widget, _model = make_group_widget()
        widget.show()
        type(self).app.processEvents()

        lock = widget.lock_button
        collapse = widget.collapse_button

        self.assertTrue(
            lock_uses_icon_without_glyph(lock),
            msg=(
                "unlocked lock control must use a non-null QIcon with no glyph text "
                f"(emoji/unicode fallback is not acceptable); "
                f"got text={lock.text()!r} icon_null={lock.icon().isNull()}"
            ),
        )
        self.assertTrue(
            tooltip_mentions(button_tooltip(lock), "锁定", "lock"),
            msg=f"unlocked lock tooltip must name lock action; got {button_tooltip(lock)!r}",
        )
        unlocked_lock_cache_key = lock_icon_cache_key(lock)

        QTest.mouseClick(lock, Qt.MouseButton.LeftButton)
        type(self).app.processEvents()

        self.assertIs(widget.lock_button, lock, "lock toggle must reuse the same button widget")
        self.assertTrue(
            lock_uses_icon_without_glyph(lock),
            msg=(
                "locked lock control must use a non-null QIcon with no glyph text "
                f"(emoji/unicode fallback is not acceptable); "
                f"got text={lock.text()!r} icon_null={lock.icon().isNull()}"
            ),
        )
        self.assertNotEqual(
            lock_icon_cache_key(lock),
            unlocked_lock_cache_key,
            msg=(
                "lock toggle must swap to a different QIcon cacheKey "
                f"(unlocked={unlocked_lock_cache_key!r}, locked={lock_icon_cache_key(lock)!r})"
            ),
        )
        self.assertTrue(
            tooltip_mentions(button_tooltip(lock), "解锁", "unlock"),
            msg=f"locked lock tooltip must name unlock action; got {button_tooltip(lock)!r}",
        )

        self.assertTrue(button_has_icon(collapse))
        collapse_tooltip_before = button_tooltip(collapse)
        self.assertTrue(
            tooltip_mentions(collapse_tooltip_before, "收起", "collapse", "fold"),
            msg=f"expanded collapse tooltip must name collapse; got {collapse_tooltip_before!r}",
        )

        QTest.mouseClick(collapse, Qt.MouseButton.LeftButton)
        type(self).app.processEvents()

        self.assertIs(
            widget.collapse_button,
            collapse,
            "collapse toggle must reuse the same button widget",
        )
        self.assertTrue(
            button_has_icon(collapse),
            msg="collapsed state must keep a non-null arrow icon on the same control",
        )
        self.assertTrue(
            tooltip_mentions(button_tooltip(collapse), "展开", "expand"),
            msg=(
                "collapsed collapse tooltip must name expand action; "
                f"got {button_tooltip(collapse)!r}"
            ),
        )

    def test_inline_title_editor_is_available_without_dialog(self) -> None:
        widget, model = make_group_widget()
        tab_id = model.group("group-default").active_tab_id
        widget.show()
        type(self).app.processEvents()

        widget.start_inline_title_edit(tab_id)

        self.assertIsInstance(widget.inline_title_editor, QLineEdit)
        self.assertTrue(widget.inline_title_editor.isVisible())
        self.assertEqual(widget.findChildren(QDialog), [])

    def test_inline_title_edit_commits_metadata_only_rename(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            widget, model = make_group_widget(desktop)
            tab = model.add_tab("group-default", "待命名")

            widget.start_inline_title_edit(tab.id)
            widget.inline_title_editor.setText("收件箱")
            widget.commit_inline_title_edit()

            self.assertEqual(model.tab(tab.id).name, "收件箱")
            self.assertEqual(list(desktop.iterdir()), [])

    def test_add_button_creates_tab_in_workspace_without_filesystem_writes(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            widget, model = make_group_widget(desktop)
            before = len(model.config.panel_tabs)

            QTest.mouseClick(widget.add_button, Qt.MouseButton.LeftButton)

            self.assertEqual(len(model.config.panel_tabs), before + 1)
            new_tab = model.tab(model.group("group-default").active_tab_id)
            self.assertEqual(new_tab.group_id, "group-default")
            self.assertEqual(list(desktop.iterdir()), [])

    def test_add_button_requests_inline_rename(self) -> None:
        widget, _model = make_group_widget()
        widget.show()
        type(self).app.processEvents()

        QTest.mouseClick(widget.add_button, Qt.MouseButton.LeftButton)

        self.assertTrue(widget.inline_title_editor.isVisible())

    def test_delete_button_removes_active_tab_metadata_without_filesystem_writes(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            desktop = root / "desktop"
            outside = root / "outside.custom"
            desktop.mkdir()
            outside.write_text("keep", encoding="utf-8")
            widget, model = make_group_widget(desktop)
            tab = model.add_tab("group-default", "临时")
            model.add_paths_to_tab([outside], tab.id)
            widget.activate_tab(tab.id)

            QTest.mouseClick(widget.delete_button, Qt.MouseButton.LeftButton)

            self.assertFalse(any(entry.id == tab.id for entry in model.config.panel_tabs))
            self.assertEqual(model.config.external_refs, [])
            self.assertTrue(outside.is_file())
            self.assertEqual(outside.read_text(encoding="utf-8"), "keep")
            self.assertEqual(list(desktop.iterdir()), [])

    def test_lock_and_collapse_controls_update_group_metadata(self) -> None:
        widget, model = make_group_widget()
        group = model.group("group-default")
        widget.show()
        type(self).app.processEvents()

        QTest.mouseClick(widget.lock_button, Qt.MouseButton.LeftButton)
        QTest.mouseClick(widget.collapse_button, Qt.MouseButton.LeftButton)
        type(self).app.processEvents()

        self.assertTrue(widget.is_locked)
        self.assertTrue(widget.is_collapsed)
        self.assertTrue(group.locked)
        self.assertTrue(group.collapsed)

    def test_collapsed_panel_keeps_titlebar_tabs_and_hides_content_without_bottom_strip(self) -> None:
        widget, _model = make_group_widget()
        widget.resize(640, 480)
        widget.show()
        type(self).app.processEvents()
        expanded_height = widget.height()

        QTest.mouseClick(widget.collapse_button, Qt.MouseButton.LeftButton)
        type(self).app.processEvents()

        self.assertTrue(widget.is_collapsed)
        self.assertFalse(widget.item_grid.isVisible())
        buttons = tab_buttons(widget)
        self.assertTrue(buttons, "tab buttons must exist to verify collapse visibility")
        self.assertTrue(all(button.isVisible() for button in buttons))
        collapsed_height = widget.height()
        self.assertLess(collapsed_height, expanded_height - 80)
        self.assertLessEqual(collapsed_height, widget.header_height() + 8)

    def test_expanding_collapsed_panel_restores_tab_row_and_content(self) -> None:
        widget, _model = make_group_widget()
        widget.resize(640, 480)
        widget.show()
        type(self).app.processEvents()

        QTest.mouseClick(widget.collapse_button, Qt.MouseButton.LeftButton)
        type(self).app.processEvents()
        self.assertFalse(widget.item_grid.isVisible())
        QTest.mouseClick(widget.collapse_button, Qt.MouseButton.LeftButton)
        type(self).app.processEvents()

        self.assertFalse(widget.is_collapsed)
        self.assertTrue(widget.item_grid.isVisible())
        self.assertTrue(all(button.isVisible() for button in tab_buttons(widget)))

    def test_locked_panel_ignores_header_drag_and_resize_gestures(self) -> None:
        widget, model = make_group_widget()
        widget.resize(320, 260)
        widget.show()
        type(self).app.processEvents()
        widget.set_locked(True)
        geometry_before = deepcopy(model.group("group-default").geometry)
        pos_before = widget.pos()
        size_before = widget.size()

        header_start = QPoint(80, 12)
        header_end = QPoint(140, 40)
        QTest.mousePress(widget, Qt.MouseButton.LeftButton, pos=header_start)
        QTest.mouseMove(widget, pos=header_end)
        QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=header_end)
        corner = QPoint(widget.width() - 3, widget.height() - 3)
        corner_end = corner + QPoint(30, 24)
        QTest.mousePress(widget, Qt.MouseButton.LeftButton, pos=corner)
        QTest.mouseMove(widget, pos=corner_end)
        QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=corner_end)
        type(self).app.processEvents()

        self.assertEqual(widget.pos(), pos_before)
        self.assertEqual(widget.size(), size_before)
        self.assertEqual(model.group("group-default").geometry, geometry_before)

    def test_double_click_tab_opens_inline_rename_editor(self) -> None:
        widget, model = make_group_widget()
        widget.show()
        type(self).app.processEvents()

        tab_button = find_tab_button(widget, "图片")
        QTest.mouseDClick(tab_button, Qt.MouseButton.LeftButton)
        type(self).app.processEvents()

        self.assertTrue(widget.inline_title_editor.isVisible())
        self.assertEqual(widget.inline_title_editor.text(), model.tab("tab-images").name)

    def test_double_click_existing_tab_rename_commits_metadata_only(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            widget, model = make_group_widget(desktop)

            tab_button = find_tab_button(widget, "文档")
            QTest.mouseDClick(tab_button, Qt.MouseButton.LeftButton)
            type(self).app.processEvents()
            widget.inline_title_editor.setText("工作文档")
            widget.commit_inline_title_edit()

            self.assertEqual(model.tab("tab-documents").name, "工作文档")
            self.assertEqual(list(desktop.iterdir()), [])

    def test_header_click_without_move_does_not_emit_group_merge_requested(self) -> None:
        widget, _model = make_group_widget()
        widget.resize(320, 260)
        widget.show()
        type(self).app.processEvents()

        spy = QSignalSpy(widget.group_merge_requested)
        click_point = QPoint(80, 12)
        QTest.mousePress(widget, Qt.MouseButton.LeftButton, pos=click_point)
        QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=click_point)
        type(self).app.processEvents()

        self.assertEqual(spy.count(), 0)

    def test_header_click_without_move_does_not_change_position(self) -> None:
        widget, _model = make_group_widget()
        widget.resize(320, 260)
        widget.show()
        type(self).app.processEvents()

        pos_before = widget.pos()
        click_point = QPoint(80, 12)
        QTest.mousePress(widget, Qt.MouseButton.LeftButton, pos=click_point)
        QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=click_point)
        type(self).app.processEvents()

        self.assertEqual(widget.pos(), pos_before)

    def test_header_drag_moves_widget_before_release_without_merge_signal(self) -> None:
        widget, model = make_group_widget()
        widget.resize(320, 260)
        widget.show()
        type(self).app.processEvents()

        pos_before = widget.pos()
        geometry_before = deepcopy(model.group("group-default").geometry)
        merge_spy = QSignalSpy(widget.group_merge_requested)

        start = QPoint(80, 12)
        end = QPoint(150, 36)
        QTest.mousePress(widget, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(widget, pos=end)
        type(self).app.processEvents()

        self.assertNotEqual(widget.pos(), pos_before)
        self.assertEqual(merge_spy.count(), 0)
        self.assertEqual(model.group("group-default").geometry, geometry_before)

        QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=end)
        type(self).app.processEvents()

        self.assertEqual(merge_spy.count(), 1)
        self.assertNotEqual(model.group("group-default").geometry, geometry_before)

    def test_header_drag_grabs_mouse_until_release(self) -> None:
        widget, _model = make_group_widget()
        widget.resize(320, 260)
        widget.show()
        type(self).app.processEvents()

        start = QPoint(80, 12)
        end = QPoint(150, 36)
        QTest.mousePress(widget, Qt.MouseButton.LeftButton, pos=start)

        self.assertIs(
            QWidget.mouseGrabber(),
            widget,
            "panel drag must grab mouse so child widgets cannot steal move events",
        )

        QTest.mouseMove(widget, pos=end)
        QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=end)
        type(self).app.processEvents()

        self.assertIsNot(QWidget.mouseGrabber(), widget)

    def test_header_drag_beyond_threshold_emits_group_merge_requested(self) -> None:
        widget, _model = make_group_widget()
        widget.resize(320, 260)
        widget.show()
        type(self).app.processEvents()

        spy = QSignalSpy(widget.group_merge_requested)
        release_global = widget.mapToGlobal(QPoint(150, 36))
        simulate_header_drag_release_at_global_point(widget, release_global)
        type(self).app.processEvents()

        self.assertEqual(spy.count(), 1)

    def test_header_drag_offscreen_clamps_visible_geometry_immediately(self) -> None:
        widget, model = make_group_widget()
        widget.resize(320, 260)
        widget.show()
        type(self).app.processEvents()

        start = QPoint(80, 12)
        end = QPoint(5000, 12)
        QTest.mousePress(widget, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(widget, pos=end)
        QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=end)
        type(self).app.processEvents()

        geometry = model.group("group-default").geometry
        screen = widget.screen().geometry() if widget.screen() else None
        self.assertLessEqual(geometry.rx + geometry.rw, 1.0)
        expected_x = screen.x() + int(screen.width() * geometry.rx) if screen else 0
        self.assertEqual(widget.frameGeometry().x(), expected_x)

    def test_header_drag_near_screen_edge_snaps_to_edge(self) -> None:
        widget, model = make_group_widget()
        widget.resize(320, 260)
        widget.show()
        type(self).app.processEvents()
        screen = widget.screen().availableGeometry() if widget.screen() else widget.geometry()
        widget.setGeometry(screen.x() + 40, screen.y() + 80, 320, 260)
        widget._persist_geometry_from_widget(update_rh=True)
        type(self).app.processEvents()

        start = QPoint(80, 12)
        end = start + QPoint((screen.x() + 8) - widget.frameGeometry().x(), 0)
        QTest.mousePress(widget, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(widget, pos=end)
        QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=end)
        type(self).app.processEvents()

        self.assertEqual(widget.frameGeometry().x(), screen.x())
        self.assertEqual(model.group("group-default").geometry.rx, 0.0)

    def test_header_drag_near_another_panel_snaps_to_its_edge(self) -> None:
        widget, _model = make_group_widget()
        widget.setGeometry(100, 120, 320, 260)
        widget.set_snap_rects([QRect(430, 120, 320, 260)])
        widget.show()
        type(self).app.processEvents()

        start = QPoint(80, 12)
        end = start + QPoint(12, 0)
        QTest.mousePress(widget, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(widget, pos=end)
        QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=end)
        type(self).app.processEvents()

        self.assertEqual(widget.frameGeometry().right() + 1, 430)

    def test_screen_id_positions_panel_on_selected_screen(self) -> None:
        widget, model = make_group_widget()
        group = model.group("group-default")
        group.screen_id = "screen-1"
        group.geometry = PanelGeometry(rx=0.10, ry=0.20, rw=0.30, rh=0.40)
        widget.set_screen_geometries(
            {
                "primary": QRect(0, 0, 1000, 800),
                "screen-1": QRect(1000, 0, 800, 600),
            }
        )

        widget._apply_geometry_from_model()

        self.assertEqual(widget.frameGeometry().x(), 1080)
        self.assertEqual(widget.frameGeometry().y(), 120)
        self.assertEqual(widget.frameGeometry().width(), 240)
        self.assertEqual(widget.frameGeometry().height(), 240)

    def test_header_drag_to_secondary_screen_updates_screen_id(self) -> None:
        widget, model = make_group_widget()
        group = model.group("group-default")
        group.geometry = PanelGeometry(rx=0.05, ry=0.05, rw=0.30, rh=0.30)
        widget.set_screen_geometries(
            {
                "primary": QRect(0, 0, 800, 600),
                "screen-1": QRect(800, 0, 800, 600),
            }
        )
        widget.setGeometry(40, 40, 240, 180)
        widget.show()
        type(self).app.processEvents()

        widget._begin_header_drag(QPoint(100, 60))
        widget._finish_header_drag(QPoint(900, 80))
        type(self).app.processEvents()

        self.assertEqual(group.screen_id, "screen-1")
        self.assertGreaterEqual(group.geometry.rx, 0.0)
        self.assertLessEqual(group.geometry.rx + group.geometry.rw, 1.0)

    def test_snap_targets_on_other_screens_are_ignored(self) -> None:
        widget, _model = make_group_widget()
        widget.set_screen_geometries(
            {
                "primary": QRect(0, 0, 800, 600),
                "screen-1": QRect(800, 0, 800, 600),
            }
        )
        widget.set_snap_rects([QRect(805, 100, 240, 200)])

        snapped = widget._snap_frame_to_screen(
            QRect(510, 100, 280, 200),
            QPoint(790, 120),
        )

        self.assertLessEqual(snapped.right(), 799)

    def test_titlebar_buttons_have_hover_and_pressed_feedback_styles(self) -> None:
        widget, _model = make_group_widget()

        for button in toolbar_buttons(widget):
            with self.subTest(button=button.accessibleName() or button.text()):
                style = button.styleSheet()
                self.assertIn(":hover", style)
                self.assertIn(":pressed", style)

    def test_resize_hover_updates_cursor_shape(self) -> None:
        widget, _model = make_group_widget()
        widget.resize(420, 300)
        widget.show()
        type(self).app.processEvents()

        def send_hover(pos: QPoint) -> None:
            event = QMouseEvent(
                QEvent.Type.MouseMove,
                QPointF(pos),
                QPointF(widget.mapToGlobal(pos)),
                Qt.MouseButton.NoButton,
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
            )
            QApplication.sendEvent(widget, event)
            type(self).app.processEvents()

        send_hover(QPoint(widget.width() // 2, widget.header_height() // 2))

        send_hover(QPoint(widget.width() - 3, widget.height() // 2))
        self.assertEqual(widget.cursor().shape(), Qt.CursorShape.SizeHorCursor)

        send_hover(QPoint(widget.width() - 3, widget.height() - 3))
        self.assertEqual(widget.cursor().shape(), Qt.CursorShape.SizeFDiagCursor)

        send_hover(QPoint(widget.width() // 2, widget.header_height() // 2))
        self.assertEqual(widget.cursor().shape(), Qt.CursorShape.ArrowCursor)

    def test_collapsed_panel_keeps_titlebar_tab_buttons_visible(self) -> None:
        widget, _model = make_group_widget()
        widget.resize(640, 480)
        widget.show()
        type(self).app.processEvents()
        visible_before = [button.text() for button in tab_buttons(widget) if button.isVisible()]

        QTest.mouseClick(widget.collapse_button, Qt.MouseButton.LeftButton)
        type(self).app.processEvents()

        visible_after = [button.text() for button in tab_buttons(widget) if button.isVisible()]
        self.assertEqual(visible_after, visible_before)
        self.assertLessEqual(widget.height(), widget.header_height() + 8)

    def test_resize_offscreen_clamps_visible_geometry_immediately(self) -> None:
        widget, model = make_group_widget()
        widget.resize(320, 260)
        widget.show()
        type(self).app.processEvents()

        right_edge = QPoint(widget.width() - 3, widget.height() // 2)
        drag_end = right_edge + QPoint(8000, 0)
        QTest.mousePress(widget, Qt.MouseButton.LeftButton, pos=right_edge)
        QTest.mouseMove(widget, pos=drag_end)
        QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=drag_end)
        type(self).app.processEvents()

        geometry = model.group("group-default").geometry
        screen = widget.screen().geometry() if widget.screen() else None
        self.assertLessEqual(geometry.rx + geometry.rw, 1.0)
        if screen is not None:
            expected_width = max(240, int(screen.width() * geometry.rw))
            self.assertEqual(widget.width(), expected_width)

    def test_left_edge_resize_changes_width(self) -> None:
        widget, model = make_group_widget()
        widget.resize(320, 260)
        widget.show()
        type(self).app.processEvents()
        geometry_before = deepcopy(model.group("group-default").geometry)
        pos_before = widget.pos()

        left_edge = QPoint(3, widget.height() // 2)
        drag_end = left_edge + QPoint(30, 0)
        QTest.mousePress(widget, Qt.MouseButton.LeftButton, pos=left_edge)
        QTest.mouseMove(widget, pos=drag_end)
        QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=drag_end)
        type(self).app.processEvents()

        self.assertLess(widget.width(), 320)
        self.assertGreater(widget.pos().x(), pos_before.x())
        self.assertLess(model.group("group-default").geometry.rw, geometry_before.rw)

    def test_top_edge_resize_changes_height(self) -> None:
        widget, model = make_group_widget()
        widget.resize(320, 260)
        widget.show()
        type(self).app.processEvents()
        geometry_before = deepcopy(model.group("group-default").geometry)
        pos_before = widget.pos()

        top_edge = QPoint(widget.width() // 2, 3)
        drag_end = top_edge + QPoint(0, 24)
        QTest.mousePress(widget, Qt.MouseButton.LeftButton, pos=top_edge)
        QTest.mouseMove(widget, pos=drag_end)
        QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=drag_end)
        type(self).app.processEvents()

        self.assertLess(widget.height(), 260)
        self.assertGreater(widget.pos().y(), pos_before.y())
        self.assertLess(model.group("group-default").geometry.rh, geometry_before.rh)

    def test_header_drag_updates_geometry_and_persists_normalized_values(self) -> None:
        widget, model = make_group_widget()
        widget.resize(320, 260)
        widget.show()
        type(self).app.processEvents()
        start = QPoint(80, 12)
        end = QPoint(150, 36)
        geometry_before = deepcopy(model.group("group-default").geometry)

        QTest.mousePress(widget, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(widget, pos=end)
        QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=end)
        type(self).app.processEvents()

        geometry_after = model.group("group-default").geometry
        self.assertNotEqual(geometry_after, geometry_before)
        self.assertGreaterEqual(geometry_after.rx, 0.0)
        self.assertGreaterEqual(geometry_after.ry, 0.0)
        self.assertLessEqual(geometry_after.rx + geometry_after.rw, 1.0)
        self.assertLessEqual(geometry_after.ry + geometry_after.rh, 1.0)

    def test_resize_handles_change_dimensions_and_persist_geometry(self) -> None:
        widget, model = make_group_widget()
        widget.resize(320, 260)
        widget.show()
        type(self).app.processEvents()
        geometry_before = deepcopy(model.group("group-default").geometry)

        right_edge = QPoint(widget.width() - 3, widget.height() // 2)
        right_end = right_edge + QPoint(40, 0)
        QTest.mousePress(widget, Qt.MouseButton.LeftButton, pos=right_edge)
        QTest.mouseMove(widget, pos=right_end)
        QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=right_end)
        type(self).app.processEvents()
        self.assertGreater(widget.width(), 320)
        self.assertGreater(model.group("group-default").geometry.rw, geometry_before.rw)

        bottom_edge = QPoint(widget.width() // 2, widget.height() - 3)
        bottom_end = bottom_edge + QPoint(0, 30)
        QTest.mousePress(widget, Qt.MouseButton.LeftButton, pos=bottom_edge)
        QTest.mouseMove(widget, pos=bottom_end)
        QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=bottom_end)
        type(self).app.processEvents()
        self.assertGreater(widget.height(), 260)
        self.assertGreater(model.group("group-default").geometry.rh, geometry_before.rh)

        corner = QPoint(widget.width() - 3, widget.height() - 3)
        width_before = widget.width()
        height_before = widget.height()
        corner_end = corner + QPoint(20, 18)
        QTest.mousePress(widget, Qt.MouseButton.LeftButton, pos=corner)
        QTest.mouseMove(widget, pos=corner_end)
        QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=corner_end)
        type(self).app.processEvents()
        self.assertGreater(widget.width(), width_before)
        self.assertGreater(widget.height(), height_before)

    def test_resize_right_edge_near_screen_edge_snaps_width(self) -> None:
        widget, _model = make_group_widget()
        screen = widget.screen().availableGeometry() if widget.screen() else QRect(0, 0, 1200, 800)
        widget.setGeometry(screen.x() + 80, screen.y() + 120, 320, 260)
        widget.show()
        type(self).app.processEvents()

        start = QPoint(widget.width() - 3, widget.height() // 2)
        target_right = screen.right() - 8
        end = start + QPoint(target_right - widget.frameGeometry().right(), 0)
        QTest.mousePress(widget, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(widget, pos=end)
        QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=end)
        type(self).app.processEvents()

        self.assertEqual(widget.frameGeometry().right(), screen.right())

    def test_resize_right_edge_near_another_panel_snaps_width(self) -> None:
        widget, _model = make_group_widget()
        widget.setGeometry(100, 120, 320, 260)
        widget.set_snap_rects([QRect(450, 120, 320, 260)])
        widget.show()
        type(self).app.processEvents()

        start = QPoint(widget.width() - 3, widget.height() // 2)
        end = start + QPoint(22, 0)
        QTest.mousePress(widget, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(widget, pos=end)
        QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=end)
        type(self).app.processEvents()

        self.assertEqual(widget.frameGeometry().right() + 1, 450)

    def test_panel_window_stays_below_normal_application_windows(self) -> None:
        widget, _model = make_group_widget()

        flags = widget.windowFlags()

        self.assertFalse(bool(flags & Qt.WindowType.WindowStaysOnTopHint))
        self.assertNotEqual(widget.windowType(), Qt.WindowType.Tool)
        self.assertTrue(bool(flags & Qt.WindowType.WindowStaysOnBottomHint))

    def test_panel_window_is_hidden_from_taskbar_when_native_handle_exists(self) -> None:
        with patch("desktop_tidy.ui.panel_group.hide_window_from_taskbar") as hide:
            widget, _model = make_group_widget()
            widget.show()
            type(self).app.processEvents()

            self.assertGreaterEqual(hide.call_count, 1)
            self.assertTrue(all(call.args[0] for call in hide.call_args_list))

    def test_resize_grabs_mouse_until_release(self) -> None:
        widget, _model = make_group_widget()
        widget.resize(320, 260)
        widget.show()
        type(self).app.processEvents()

        right_edge = QPoint(widget.width() - 3, widget.height() // 2)
        QTest.mousePress(widget, Qt.MouseButton.LeftButton, pos=right_edge)

        self.assertIs(
            QWidget.mouseGrabber(),
            widget,
            "panel resize must grab mouse so resizing continues after leaving child widgets",
        )

        QTest.mouseMove(widget, pos=right_edge + QPoint(40, 0))
        QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=right_edge + QPoint(40, 0))
        type(self).app.processEvents()

        self.assertIsNot(QWidget.mouseGrabber(), widget)

    def test_resize_hot_zone_is_wide_enough_for_manual_dragging(self) -> None:
        widget, model = make_group_widget()
        widget.resize(360, 280)
        widget.show()
        type(self).app.processEvents()
        geometry_before = deepcopy(model.group("group-default").geometry)

        right_edge = QPoint(widget.width() - 14, widget.height() // 2)
        right_end = right_edge + QPoint(44, 0)
        QTest.mousePress(widget, Qt.MouseButton.LeftButton, pos=right_edge)
        QTest.mouseMove(widget, pos=right_end)
        QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=right_end)
        type(self).app.processEvents()

        self.assertGreater(widget.width(), 360)
        self.assertGreater(model.group("group-default").geometry.rw, geometry_before.rw)

    def test_corner_resize_hot_zone_is_wide_enough_for_manual_dragging(self) -> None:
        widget, _model = make_group_widget()
        widget.resize(360, 280)
        widget.show()
        type(self).app.processEvents()
        width_before = widget.width()
        height_before = widget.height()

        corner = QPoint(widget.width() - 14, widget.height() - 14)
        corner_end = corner + QPoint(36, 28)
        QTest.mousePress(widget, Qt.MouseButton.LeftButton, pos=corner)
        QTest.mouseMove(widget, pos=corner_end)
        QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=corner_end)
        type(self).app.processEvents()

        self.assertGreater(widget.width(), width_before)
        self.assertGreater(widget.height(), height_before)

    def test_tab_drag_outside_panel_emits_tab_detach_requested(self) -> None:
        widget, _model = make_group_widget()
        widget.resize(640, 480)
        widget.show()
        type(self).app.processEvents()

        self.assertTrue(
            hasattr(widget, "tab_detach_requested"),
            "PanelGroupWidget must expose tab_detach_requested for application wiring",
        )

        payloads: list[tuple[str, PanelGeometry]] = []
        widget.tab_detach_requested.connect(
            lambda tab_id, geometry: payloads.append((tab_id, geometry))
        )

        outside = QPoint(widget.width() + 40, widget.height() // 2)
        simulate_tab_drag_release_at_local_point(widget, "图片", outside)
        type(self).app.processEvents()

        self.assertEqual(len(payloads), 1)
        tab_id, geometry = payloads[0]
        self.assertEqual(tab_id, "tab-images")
        self.assertIsInstance(geometry, PanelGeometry)

    def test_tab_detach_preview_visible_before_release_when_dragging_outside(self) -> None:
        widget, model = make_group_widget()
        widget.resize(640, 480)
        widget.show()
        type(self).app.processEvents()

        self.assertTrue(
            hasattr(widget, "detach_preview_visible"),
            "PanelGroupWidget must expose detach_preview_visible for detach preview tests",
        )

        detach_spy = QSignalSpy(widget.tab_detach_requested)
        tabs_before = list(widget.tab_button_ids())
        group_tabs_before = list(model.group("group-default").tab_ids)

        outside = QPoint(widget.width() + 40, widget.height() // 2)
        simulate_tab_drag_to_local_point_without_release(widget, "图片", outside)
        type(self).app.processEvents()

        self.assertTrue(widget.detach_preview_visible())
        self.assertEqual(detach_spy.count(), 0)
        self.assertEqual(widget.tab_button_ids(), tabs_before)
        self.assertEqual(model.group("group-default").tab_ids, group_tabs_before)

        QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=outside)
        type(self).app.processEvents()

        self.assertFalse(widget.detach_preview_visible())
        self.assertEqual(detach_spy.count(), 1)

    def test_tab_detach_preview_hidden_while_dragging_inside_panel(self) -> None:
        widget, _model = make_group_widget()
        widget.resize(640, 480)
        widget.show()
        type(self).app.processEvents()

        inside = QPoint(widget.width() // 2, widget.height() // 2)
        simulate_tab_drag_to_local_point_without_release(widget, "图片", inside)
        type(self).app.processEvents()

        self.assertFalse(widget.detach_preview_visible())

        QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=inside)
        type(self).app.processEvents()

        self.assertFalse(widget.detach_preview_visible())

    def test_tab_detach_preview_hidden_when_drag_returns_inside_before_release(self) -> None:
        widget, _model = make_group_widget()
        widget.resize(640, 480)
        widget.show()
        type(self).app.processEvents()

        outside = QPoint(widget.width() + 40, widget.height() // 2)
        inside = QPoint(widget.width() // 2, widget.height() // 2)
        simulate_tab_drag_to_local_point_without_release(widget, "图片", outside)
        type(self).app.processEvents()
        self.assertTrue(widget.detach_preview_visible())

        QTest.mouseMove(widget, pos=inside)
        type(self).app.processEvents()

        self.assertFalse(widget.detach_preview_visible())

    def test_locked_panel_never_shows_tab_detach_preview(self) -> None:
        widget, _model = make_group_widget()
        widget.resize(640, 480)
        widget.show()
        type(self).app.processEvents()
        widget.set_locked(True)

        outside = QPoint(widget.width() + 40, widget.height() // 2)
        simulate_tab_drag_to_local_point_without_release(widget, "图片", outside)
        type(self).app.processEvents()

        self.assertFalse(widget.detach_preview_visible())

    def test_single_tab_group_never_shows_tab_detach_preview(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            widget, model = make_group_widget(desktop)
            group = model.group("group-default")
            while len(group.tab_ids) > 1:
                tab_id = group.tab_ids[-1]
                if tab_id == group.active_tab_id:
                    widget.activate_tab(group.tab_ids[0])
                model.delete_tab(tab_id)
                group = model.group("group-default")
            widget.reload_from_model()
            widget.resize(640, 480)
            widget.show()
            type(self).app.processEvents()

            self.assertEqual(len(widget.tab_button_ids()), 1)

            outside = QPoint(widget.width() + 40, widget.height() // 2)
            simulate_tab_drag_to_local_point_without_release(
                widget,
                widget.active_tab_title(),
                outside,
            )
            type(self).app.processEvents()

            self.assertFalse(widget.detach_preview_visible())

    def test_single_tab_title_drag_moves_panel_without_collapsing_or_detaching(self) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            widget, model = make_group_widget(desktop)
            group = model.group("group-default")
            while len(group.tab_ids) > 1:
                tab_id = group.tab_ids[-1]
                if tab_id == group.active_tab_id:
                    widget.activate_tab(group.tab_ids[0])
                model.delete_tab(tab_id)
                group = model.group("group-default")
            widget.reload_from_model()
            widget.resize(420, 300)
            widget.show()
            type(self).app.processEvents()

            title_button = find_tab_button(widget, widget.active_tab_title())
            pos_before = widget.pos()
            detach_spy = QSignalSpy(widget.tab_detach_requested)
            collapse_before = widget.is_collapsed

            start = title_button.rect().center()
            QTest.mousePress(title_button, Qt.MouseButton.LeftButton, pos=start)
            QTest.mouseMove(title_button, pos=start + QPoint(80, 24))
            QTest.mouseRelease(title_button, Qt.MouseButton.LeftButton, pos=start + QPoint(80, 24))
            type(self).app.processEvents()

            self.assertNotEqual(widget.pos(), pos_before)
            self.assertEqual(detach_spy.count(), 0)
            self.assertEqual(widget.is_collapsed, collapse_before)
            self.assertFalse(widget.is_collapsed)

    def test_tab_drag_mouse_handler_invokes_complete_tab_detach_gesture(self) -> None:
        widget, _model = make_group_widget()
        widget.resize(640, 480)
        widget.show()
        type(self).app.processEvents()

        self.assertTrue(
            hasattr(widget, "complete_tab_detach_gesture"),
            "PanelGroupWidget must expose complete_tab_detach_gesture invoked from mouse handlers",
        )

        calls: list[tuple[str, tuple[int, int]]] = []
        original = widget.complete_tab_detach_gesture

        def spy(tab_id: str, global_point: tuple[int, int]) -> None:
            calls.append((tab_id, global_point))
            return original(tab_id, global_point)

        widget.complete_tab_detach_gesture = spy  # type: ignore[method-assign]

        release_global = widget.mapToGlobal(QPoint(widget.width() + 40, widget.height() // 2))
        simulate_tab_drag_release_at_global_point(widget, "图片", release_global)
        type(self).app.processEvents()

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "tab-images")
        self.assertEqual(calls[0][1], (release_global.x(), release_global.y()))

    def test_header_drag_release_emits_group_merge_requested_with_global_point(self) -> None:
        widget, _model = make_group_widget()
        widget.resize(320, 260)
        widget.show()
        type(self).app.processEvents()

        self.assertTrue(
            hasattr(widget, "group_merge_requested"),
            "PanelGroupWidget must expose group_merge_requested for merge wiring",
        )
        self.assertTrue(hasattr(widget, "group_id"), "PanelGroupWidget must expose group_id")

        payloads: list[tuple[str, int, int]] = []
        widget.group_merge_requested.connect(
            lambda group_id, global_x, global_y: payloads.append((group_id, global_x, global_y))
        )

        release_global = widget.mapToGlobal(QPoint(150, 36))
        simulate_header_drag_release_at_global_point(widget, release_global)
        type(self).app.processEvents()

        self.assertEqual(len(payloads), 1)
        group_id, global_x, global_y = payloads[0]
        self.assertEqual(group_id, widget.group_id)
        self.assertEqual((global_x, global_y), (release_global.x(), release_global.y()))

    def test_header_drag_mouse_handler_invokes_complete_header_drag_at_global_point(self) -> None:
        widget, _model = make_group_widget()
        widget.resize(320, 260)
        widget.show()
        type(self).app.processEvents()

        self.assertTrue(
            hasattr(widget, "complete_header_drag_at_global_point"),
            "PanelGroupWidget must expose complete_header_drag_at_global_point invoked from mouse handlers",
        )

        calls: list[tuple[int, int]] = []
        original = widget.complete_header_drag_at_global_point

        def spy(global_point: tuple[int, int]) -> None:
            calls.append(global_point)
            return original(global_point)

        widget.complete_header_drag_at_global_point = spy  # type: ignore[method-assign]

        release_global = widget.mapToGlobal(QPoint(160, 40))
        simulate_header_drag_release_at_global_point(
            widget,
            release_global,
            press_local=QPoint(80, 12),
        )
        type(self).app.processEvents()

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0], (release_global.x(), release_global.y()))

    def test_locked_panel_double_click_rename_commits_without_layout_gestures(
        self,
    ) -> None:
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            widget, model = make_group_widget(desktop)
            widget.resize(640, 480)
            widget.show()
            type(self).app.processEvents()
            widget.set_locked(True)
            geometry_before = deepcopy(model.group("group-default").geometry)
            pos_before = widget.pos()
            size_before = widget.size()

            detach_spy = QSignalSpy(widget.tab_detach_requested)
            merge_spy = QSignalSpy(widget.group_merge_requested)

            tab_button = find_tab_button(widget, "文档")
            QTest.mouseDClick(tab_button, Qt.MouseButton.LeftButton)
            type(self).app.processEvents()
            self.assertTrue(widget.inline_title_editor.isVisible())

            widget.inline_title_editor.setText("锁定重命名")
            widget.commit_inline_title_edit()
            type(self).app.processEvents()

            self.assertEqual(model.tab("tab-documents").name, "锁定重命名")
            self.assertEqual(detach_spy.count(), 0)
            self.assertEqual(merge_spy.count(), 0)
            self.assertEqual(widget.pos(), pos_before)
            self.assertEqual(widget.size(), size_before)
            self.assertEqual(model.group("group-default").geometry, geometry_before)

            outside = QPoint(widget.width() + 40, widget.height() // 2)
            simulate_tab_drag_release_at_local_point(widget, "图片", outside)
            release_global = widget.mapToGlobal(QPoint(150, 36))
            simulate_header_drag_release_at_global_point(widget, release_global)
            type(self).app.processEvents()

            self.assertEqual(detach_spy.count(), 0)
            self.assertEqual(merge_spy.count(), 0)
            self.assertEqual(len(model.config.panel_groups), 1)

    def test_locked_panel_does_not_emit_detach_or_merge_request_signals(self) -> None:
        widget, model = make_group_widget()
        widget.resize(640, 480)
        widget.show()
        type(self).app.processEvents()
        widget.set_locked(True)
        groups_before = len(model.config.panel_groups)

        self.assertTrue(hasattr(widget, "tab_detach_requested"))
        self.assertTrue(hasattr(widget, "group_merge_requested"))

        detach_payloads: list[tuple] = []
        merge_payloads: list[tuple] = []
        widget.tab_detach_requested.connect(lambda *args: detach_payloads.append(args))
        widget.group_merge_requested.connect(lambda *args: merge_payloads.append(args))

        outside = QPoint(widget.width() + 40, widget.height() // 2)
        simulate_tab_drag_release_at_local_point(widget, "图片", outside)

        release_global = widget.mapToGlobal(QPoint(150, 36))
        simulate_header_drag_release_at_global_point(widget, release_global)
        type(self).app.processEvents()

        self.assertEqual(detach_payloads, [])
        self.assertEqual(merge_payloads, [])
        self.assertEqual(len(model.config.panel_groups), groups_before)
        self.assertEqual(model.tab("tab-images").group_id, "group-default")

    def test_collapsed_state_preserves_expanded_geometry_and_restores_on_expand(
        self,
    ) -> None:
        """Collapse is visibility-only: saved rh stays expanded; reload+expand restores it."""
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            widget, model = make_group_widget(desktop)
            group = model.group("group-default")
            expanded_rh = 0.52
            group.geometry = PanelGeometry(0.08, 0.10, 0.40, expanded_rh)
            widget.reload_from_model()
            widget.resize(520, 420)
            widget.show()
            type(self).app.processEvents()
            expanded_height = widget.height()

            QTest.mouseClick(widget.collapse_button, Qt.MouseButton.LeftButton)
            type(self).app.processEvents()

            self.assertTrue(widget.is_collapsed)
            self.assertFalse(widget.item_grid.isVisible())
            buttons = tab_buttons(widget)
            self.assertTrue(buttons)
            self.assertTrue(all(button.isVisible() for button in buttons))
            self.assertLessEqual(widget.height(), widget.header_height() + 8)
            self.assertAlmostEqual(
                group.geometry.rh,
                expanded_rh,
                places=3,
                msg="collapsed save must keep expanded rh, not the header-only height",
            )

            payload = deepcopy(model.config.to_dict())
            restored_config = Configuration.from_dict(payload)
            restored_model = WorkspaceModel(restored_config)
            restored_group = restored_model.group("group-default")
            self.assertTrue(restored_group.collapsed)

            replacement = PanelGroupWidget(
                restored_group,
                restored_model.config.panel_tabs,
                workspace=restored_model,
            )
            replacement.show()
            type(self).app.processEvents()

            self.assertTrue(replacement.is_collapsed)
            self.assertFalse(replacement.item_grid.isVisible())
            self.assertAlmostEqual(restored_group.geometry.rh, expanded_rh, places=3)

            QTest.mouseClick(replacement.collapse_button, Qt.MouseButton.LeftButton)
            type(self).app.processEvents()

            self.assertFalse(replacement.is_collapsed)
            self.assertTrue(replacement.item_grid.isVisible())
            self.assertTrue(all(button.isVisible() for button in tab_buttons(replacement)))
            self.assertAlmostEqual(restored_group.geometry.rh, expanded_rh, places=3)
            self.assertGreaterEqual(replacement.height(), expanded_height - 40)


    def test_many_entries_do_not_inflate_panel_minimum_height(self) -> None:
        """Panel must be resizable to a reasonable height even with many grid items."""
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            widget, model = make_group_widget(desktop)
            widget.resize(400, 500)
            widget.show()
            type(self).app.processEvents()

            entries = [
                IndexedItem(Path(tmp) / f"item-{index:03d}.txt")
                for index in range(40)
            ]
            for entry in entries:
                entry.path.write_text("x", encoding="utf-8")
            widget.item_grid.set_entries(entries)
            type(self).app.processEvents()
            self.assertEqual(widget.item_grid.item_count(), 40)

            bottom_right = QPoint(widget.width() - 3, widget.height() - 3)
            drag_end = bottom_right + QPoint(-20, -180)
            QTest.mousePress(widget, Qt.MouseButton.LeftButton, pos=bottom_right)
            QTest.mouseMove(widget, pos=drag_end)
            QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=drag_end)
            type(self).app.processEvents()

            self.assertLess(
                widget.height(),
                350,
                "panel must shrink below total item grid content height",
            )

    def test_locked_panel_still_blocks_resize_even_with_many_entries(self) -> None:
        """Locked panel must block resize regardless of grid content count."""
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            widget, model = make_group_widget(desktop)
            widget.resize(400, 400)
            widget.show()
            type(self).app.processEvents()

            entries = [
                IndexedItem(Path(tmp) / f"entry-{index:03d}.txt")
                for index in range(20)
            ]
            for entry in entries:
                entry.path.write_text("x", encoding="utf-8")
            widget.item_grid.set_entries(entries)
            widget.set_locked(True)
            type(self).app.processEvents()
            size_before = widget.size()

            bottom_right = QPoint(widget.width() - 3, widget.height() - 3)
            drag_end = bottom_right + QPoint(30, 30)
            QTest.mousePress(widget, Qt.MouseButton.LeftButton, pos=bottom_right)
            QTest.mouseMove(widget, pos=drag_end)
            QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=drag_end)
            type(self).app.processEvents()

            self.assertEqual(widget.size(), size_before)

    # ── content-area edge resize ──────────────────────────────────────

    def _content_child_at_panel_point(
        self, widget: PanelGroupWidget, panel_point: QPoint
    ) -> tuple[QWidget, QPoint]:
        """Return the deepest child at *panel_point* and its local equivalent."""
        child = widget.childAt(panel_point)
        if child is None:
            child = widget
        local = child.mapFrom(widget, panel_point)
        return child, local

    def test_resize_from_item_grid_right_edge_changes_width(self) -> None:
        """Dragging from the right edge of the item grid must resize the panel."""
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            widget, model = make_group_widget(desktop)
            widget.resize(400, 300)
            widget.show()
            type(self).app.processEvents()

            entries = [
                IndexedItem(Path(tmp) / f"entry-{index:03d}.txt")
                for index in range(3)
            ]
            for entry in entries:
                entry.path.write_text("x", encoding="utf-8")
            widget.item_grid.set_entries(entries)
            type(self).app.processEvents()

            geometry_before = deepcopy(model.group("group-default").geometry)
            width_before = widget.width()

            # Click near the content right edge (inset by panel margins)
            right_edge_panel = QPoint(widget.width() - 18, widget.height() // 2)
            child, child_local = self._content_child_at_panel_point(
                widget, right_edge_panel
            )
            drag_end = child_local + QPoint(40, 0)

            QTest.mousePress(child, Qt.MouseButton.LeftButton, pos=child_local)
            QTest.mouseMove(child, pos=drag_end)
            QTest.mouseRelease(child, Qt.MouseButton.LeftButton, pos=drag_end)
            type(self).app.processEvents()

            self.assertGreater(widget.width(), width_before)
            self.assertGreater(
                model.group("group-default").geometry.rw,
                geometry_before.rw,
            )

    def test_resize_snaps_width_to_other_panel_width(self) -> None:
        widget, _model = make_group_widget()
        widget.set_screen_geometries({"primary": QRect(0, 0, 1200, 900)})
        widget.set_snap_rects([QRect(80, 40, 700, 260)])
        widget.setGeometry(120, 420, 520, 260)
        widget.show()
        type(self).app.processEvents()

        start = widget.mapToGlobal(QPoint(widget.width() - 2, widget.height() // 2))
        widget._begin_resize_gesture(_ResizeRegion.RIGHT, start)
        widget._update_resize_gesture(start + QPoint(700 - widget.width() - 6, 0))
        widget._finish_resize_gesture()
        type(self).app.processEvents()

        self.assertEqual(widget.width(), 700)

    def test_resize_snaps_height_to_other_panel_height(self) -> None:
        widget, _model = make_group_widget()
        widget.set_screen_geometries({"primary": QRect(0, 0, 1200, 900)})
        widget.set_snap_rects([QRect(80, 40, 420, 380)])
        widget.setGeometry(540, 220, 420, 260)
        widget.show()
        type(self).app.processEvents()

        start = widget.mapToGlobal(QPoint(widget.width() // 2, widget.height() - 2))
        widget._begin_resize_gesture(_ResizeRegion.BOTTOM, start)
        widget._update_resize_gesture(start + QPoint(0, 380 - widget.height() - 6))
        widget._finish_resize_gesture()
        type(self).app.processEvents()

        self.assertEqual(widget.height(), 380)

    def test_live_resize_reflows_grid_without_rebuilding_cells(self) -> None:
        with TemporaryDirectory() as tmp:
            widget, _model = make_group_widget(Path(tmp) / "desktop")
            widget.setGeometry(120, 120, 440, 260)
            widget.show()
            type(self).app.processEvents()
            entries = [
                IndexedItem(Path(tmp) / f"entry-{index:03d}.txt")
                for index in range(16)
            ]
            for entry in entries:
                entry.path.write_text("x", encoding="utf-8")
            widget.item_grid.set_entries(entries)
            type(self).app.processEvents()
            rebuilt = QSignalSpy(widget.item_grid.cells_rebuilt)
            layout = widget.item_grid._grid_host.layout()
            before_position = layout.getItemPosition(3)

            start = widget.mapToGlobal(QPoint(widget.width() - 2, widget.height() // 2))
            widget._begin_resize_gesture(_ResizeRegion.RIGHT, start)
            widget._update_resize_gesture(start + QPoint(420, 0))
            type(self).app.processEvents()

            during_position = layout.getItemPosition(3)
            self.assertNotEqual(
                during_position[:2],
                before_position[:2],
                "grid item positions should update while the panel is still being resized",
            )
            self.assertEqual(rebuilt.count(), 0)

            widget._finish_resize_gesture()
            type(self).app.processEvents()

            self.assertEqual(rebuilt.count(), 0)

    def test_resize_from_content_bottom_edge_changes_height(self) -> None:
        """Dragging from the bottom edge of the scroll area must resize the panel."""
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            widget, model = make_group_widget(desktop)
            widget.resize(400, 300)
            widget.show()
            type(self).app.processEvents()

            entries = [
                IndexedItem(Path(tmp) / f"item-{index:03d}.txt")
                for index in range(4)
            ]
            for entry in entries:
                entry.path.write_text("x", encoding="utf-8")
            widget.item_grid.set_entries(entries)
            type(self).app.processEvents()

            geometry_before = deepcopy(model.group("group-default").geometry)
            height_before = widget.height()

            bottom_edge_panel = QPoint(widget.width() // 2, widget.height() - 18)
            child, child_local = self._content_child_at_panel_point(
                widget, bottom_edge_panel
            )
            drag_end = child_local + QPoint(0, 30)

            QTest.mousePress(child, Qt.MouseButton.LeftButton, pos=child_local)
            QTest.mouseMove(child, pos=drag_end)
            QTest.mouseRelease(child, Qt.MouseButton.LeftButton, pos=drag_end)
            type(self).app.processEvents()

            self.assertGreater(widget.height(), height_before)
            self.assertGreater(
                model.group("group-default").geometry.rh,
                geometry_before.rh,
            )

    def test_resize_from_content_corner_changes_both_dimensions(self) -> None:
        """Dragging from the bottom-right corner of a content child must resize both axes."""
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            widget, model = make_group_widget(desktop)
            widget.resize(400, 300)
            widget.show()
            type(self).app.processEvents()

            entries = [
                IndexedItem(Path(tmp) / f"item-{index:03d}.txt")
                for index in range(3)
            ]
            for entry in entries:
                entry.path.write_text("x", encoding="utf-8")
            widget.item_grid.set_entries(entries)
            type(self).app.processEvents()

            width_before = widget.width()
            height_before = widget.height()

            corner_panel = QPoint(widget.width() - 18, widget.height() - 18)
            child, child_local = self._content_child_at_panel_point(
                widget, corner_panel
            )
            drag_end = child_local + QPoint(30, 25)

            QTest.mousePress(child, Qt.MouseButton.LeftButton, pos=child_local)
            QTest.mouseMove(child, pos=drag_end)
            QTest.mouseRelease(child, Qt.MouseButton.LeftButton, pos=drag_end)
            type(self).app.processEvents()

            self.assertGreater(widget.width(), width_before)
            self.assertGreater(widget.height(), height_before)

    def test_locked_panel_ignores_resize_from_content_edge(self) -> None:
        """Locked panel must not resize when dragging from a content child edge."""
        with TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "desktop"
            desktop.mkdir()
            widget, model = make_group_widget(desktop)
            widget.resize(400, 300)
            widget.show()
            type(self).app.processEvents()

            entries = [
                IndexedItem(Path(tmp) / f"item-{index:03d}.txt")
                for index in range(3)
            ]
            for entry in entries:
                entry.path.write_text("x", encoding="utf-8")
            widget.item_grid.set_entries(entries)
            widget.set_locked(True)
            type(self).app.processEvents()

            size_before = widget.size()
            geometry_before = deepcopy(model.group("group-default").geometry)

            # right edge via child
            right_edge = QPoint(widget.width() - 18, widget.height() // 2)
            child, child_local = self._content_child_at_panel_point(widget, right_edge)
            QTest.mousePress(child, Qt.MouseButton.LeftButton, pos=child_local)
            QTest.mouseMove(child, pos=child_local + QPoint(40, 0))
            QTest.mouseRelease(child, Qt.MouseButton.LeftButton, pos=child_local + QPoint(40, 0))
            type(self).app.processEvents()

            # bottom edge via child
            bottom_edge = QPoint(widget.width() // 2, widget.height() - 18)
            child2, child_local2 = self._content_child_at_panel_point(widget, bottom_edge)
            QTest.mousePress(child2, Qt.MouseButton.LeftButton, pos=child_local2)
            QTest.mouseMove(child2, pos=child_local2 + QPoint(0, 30))
            QTest.mouseRelease(child2, Qt.MouseButton.LeftButton, pos=child_local2 + QPoint(0, 30))
            type(self).app.processEvents()

            self.assertEqual(widget.size(), size_before)
            self.assertEqual(model.group("group-default").geometry, geometry_before)


if __name__ == "__main__":
    unittest.main()
