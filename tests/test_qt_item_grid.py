from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QContextMenuEvent, QWheelEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QLabel, QToolButton, QWidget

from desktop_tidy.domain.defaults import build_default_configuration
from desktop_tidy.services.desktop_index import IndexedItem
from desktop_tidy.ui.item_grid import ItemGridWidget, display_name_for_path
from desktop_tidy.ui.panel_group import PanelGroupWidget

_RESTORE_AUTO_LABEL = "\u6062\u590d\u81ea\u52a8\u5206\u7c7b"


def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def process_qt_events() -> None:
    qt_app().processEvents()


def make_item_grid(active_tab_id: str = "tab-images") -> ItemGridWidget:
    return ItemGridWidget(active_tab_id=active_tab_id)


def _grid_item_buttons(grid: ItemGridWidget) -> list[QToolButton]:
    layout = grid._grid_host.layout()
    buttons: list[QToolButton] = []
    for index in range(layout.count()):
        cell = layout.itemAt(index).widget()
        button = cell.findChild(QToolButton) if cell is not None else None
        if button is None:
            raise AssertionError(f"missing item control button at grid index {index}")
        buttons.append(button)
    return buttons


def item_button_for_path(grid: ItemGridWidget, path: Path) -> QToolButton:
    resolved = path.resolve()
    paths = grid.entry_paths()
    if resolved not in paths:
        raise AssertionError(f"{resolved} is not shown in the item grid")
    return _grid_item_buttons(grid)[paths.index(resolved)]


def item_cell_for_path(grid: ItemGridWidget, path: Path) -> QWidget:
    cell = grid._cells_by_path.get(path.resolve())
    if cell is None:
        raise AssertionError(f"{path.resolve()} is not shown in the item grid")
    return cell


def item_label_for_path(grid: ItemGridWidget, path: Path) -> QLabel:
    label = item_cell_for_path(grid, path).findChild(QLabel)
    if label is None:
        raise AssertionError(f"{path.resolve()} has no caption label")
    return label


class ShellMenuRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[QWidget, Path, QPoint]] = []

    def __call__(self, owner: QWidget, path: Path, global_pos: QPoint) -> bool:
        self.calls.append((owner, path.resolve(), QPoint(global_pos)))
        return True


class ShellMenuFailureRecorder(ShellMenuRecorder):
    def __call__(self, owner: QWidget, path: Path, global_pos: QPoint) -> bool:
        super().__call__(owner, path, global_pos)
        return False


class NativeShellServiceRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[QWidget, Path, QPoint]] = []

    def show(self, owner: QWidget, path: Path, global_pos: QPoint) -> bool:
        self.calls.append((owner, path.resolve(), QPoint(global_pos)))
        return True


def send_modified_wheel(
    widget: ItemGridWidget,
    delta: int,
    modifier: Qt.KeyboardModifier,
) -> None:
    center = widget.rect().center()
    event = QWheelEvent(
        QPointF(center),
        QPointF(widget.mapToGlobal(center)),
        QPoint(0, 0),
        QPoint(0, delta),
        Qt.MouseButton.NoButton,
        modifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )
    QApplication.sendEvent(widget, event)
    process_qt_events()


def send_ctrl_wheel(widget: ItemGridWidget, delta: int) -> None:
    send_modified_wheel(widget, delta, Qt.KeyboardModifier.ControlModifier)


def send_alt_wheel(widget: ItemGridWidget, delta: int) -> None:
    send_modified_wheel(widget, delta, Qt.KeyboardModifier.AltModifier)


class ItemGridWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _make_panel_group(self) -> PanelGroupWidget:
        config = build_default_configuration(r"D:\Preview\Desktop")
        return PanelGroupWidget(config.panel_groups[0], config.panel_tabs)

    def test_default_group_construction_exposes_background_opacity_without_window_fade(
        self,
    ) -> None:
        widget = self._make_panel_group()
        self.assertEqual(widget.windowOpacity(), 1.0)
        self.assertEqual(widget.background_opacity, 0.60)

    def test_item_caption_is_limited_to_two_elided_lines(self) -> None:
        widget = self._make_panel_group()
        caption = widget.item_grid.caption_text(
            "一个特别特别特别长的桌面文档文件名称.pdf",
            width=80,
        )
        self.assertLessEqual(len(caption.splitlines()), 2)
        self.assertTrue(caption.endswith("..."))

    def test_runtime_entries_render_without_modifying_paths(self) -> None:
        widget = self._make_panel_group()
        with TemporaryDirectory() as tmp:
            first = Path(tmp) / "keep-me.txt"
            second = Path(tmp) / "also-keep.pdf"
            first.write_text("alpha", encoding="utf-8")
            second.write_text("beta", encoding="utf-8")
            entries = [IndexedItem(first), IndexedItem(second)]
            before = {path: path.read_text(encoding="utf-8") for path in (first, second)}

            widget.item_grid.set_entries(entries)

            self.assertEqual(
                widget.item_grid.entry_paths(),
                [first.resolve(), second.resolve()],
            )
            self.assertEqual(widget.item_grid.item_count(), 2)
            for path, content in before.items():
                self.assertEqual(path.read_text(encoding="utf-8"), content)

    def test_narrow_width_switches_to_compact_list_layout(self) -> None:
        widget = make_item_grid(active_tab_id="tab-documents")
        with TemporaryDirectory() as tmp:
            entries = [IndexedItem(Path(tmp) / f"compact-{index}.pdf") for index in range(4)]
            for entry in entries:
                entry.path.write_text("x", encoding="utf-8")
            widget.resize(330, 260)
            widget.show()
            widget.set_entries(entries)
            type(self).app.processEvents()

            first_cell = item_cell_for_path(widget, entries[0].path)
            first_button = item_button_for_path(widget, entries[0].path)
            first_label = item_label_for_path(widget, entries[0].path)

            self.assertEqual(widget.column_count(), 1)
            self.assertLess(first_button.geometry().x(), first_label.geometry().x())
            self.assertLess(
                abs(first_button.geometry().center().y() - first_label.geometry().center().y()),
                10,
            )
            self.assertGreaterEqual(
                first_cell.width(),
                widget._scroll_area.viewport().width() - 32,
            )

    def test_empty_active_tab_shows_empty_state(self) -> None:
        widget = self._make_panel_group()
        widget.item_grid.set_entries([])
        self.assertTrue(widget.item_grid.shows_empty_state())
        self.assertTrue(widget.item_grid.empty_state_text().strip())

    def test_item_grid_accepts_url_drops(self) -> None:
        widget = make_item_grid()

        self.assertTrue(widget.acceptDrops())

    def test_local_paths_from_urls_accepts_any_suffix_and_folders(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            weird = root / "asset.weird"
            folder = root / "nested-folder"
            weird.write_text("payload", encoding="utf-8")
            folder.mkdir()
            widget = make_item_grid()

            paths = widget.local_paths_from_urls(
                [
                    QUrl.fromLocalFile(str(weird)),
                    QUrl.fromLocalFile(str(folder)),
                ]
            )

            self.assertEqual(paths, [weird.resolve(), folder.resolve()])

    def test_accept_dropped_urls_emits_paths_with_active_tab_without_mutating_sources(
        self,
    ) -> None:
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "drop.me"
            source.write_text("keep", encoding="utf-8")
            before = source.read_text(encoding="utf-8")
            widget = make_item_grid(active_tab_id="tab-folders")
            spy = QSignalSpy(widget.paths_dropped)

            widget.accept_dropped_urls([QUrl.fromLocalFile(str(source))])

            self.assertEqual(spy.count(), 1)
            paths, tab_id = spy.at(0)
            self.assertEqual(tab_id, "tab-folders")
            self.assertEqual(paths, [source.resolve()])
            self.assertEqual(source.read_text(encoding="utf-8"), before)

    def test_column_count_grows_with_panel_width(self) -> None:
        widget = self._make_panel_group()
        with TemporaryDirectory() as tmp:
            entries = [
                IndexedItem(Path(tmp) / f"item-{index}.txt")
                for index in range(12)
            ]
            for entry in entries:
                entry.path.write_text("x", encoding="utf-8")
            widget.item_grid.set_entries(entries)
            widget.resize(320, 420)
            widget.show()
            type(self).app.processEvents()
            narrow_columns = widget.item_grid.column_count()

            widget.resize(960, 420)
            type(self).app.processEvents()
            wide_columns = widget.item_grid.column_count()

            self.assertGreater(wide_columns, narrow_columns)
            self.assertLess(narrow_columns, 4)

    def test_item_spacing_adapts_to_reduce_right_edge_gap_when_panel_is_wide(self) -> None:
        widget = make_item_grid(active_tab_id="tab-documents")
        with TemporaryDirectory() as tmp:
            entries = [IndexedItem(Path(tmp) / f"item-{index}.pdf") for index in range(6)]
            for entry in entries:
                entry.path.write_text("x", encoding="utf-8")
            widget.resize(760, 320)
            widget.show()
            widget.set_entries(entries)
            type(self).app.processEvents()

            layout = widget._grid_host.layout()
            first = layout.itemAt(0).widget()
            last = layout.itemAt(min(widget.column_count(), len(entries)) - 1).widget()
            self.assertIsNotNone(first)
            self.assertIsNotNone(last)
            viewport_width = widget._scroll_area.viewport().width()
            right_gap = viewport_width - last.geometry().right()

            self.assertLessEqual(
                right_gap,
                48,
                "wide panels should distribute spare width instead of leaving it on the right",
            )

    def test_ctrl_wheel_changes_item_icon_size_and_emits_change_signal(self) -> None:
        widget = make_item_grid(active_tab_id="tab-documents")
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "zoom-me.pdf"
            source.write_text("x", encoding="utf-8")
            widget.set_entries([IndexedItem(source)])
            widget.resize(360, 260)
            widget.show()
            type(self).app.processEvents()

            before = widget.item_icon_size()
            spy = QSignalSpy(widget.item_icon_size_changed)

            send_ctrl_wheel(widget, 120)

            self.assertGreater(widget.item_icon_size(), before)
            self.assertEqual(spy.count(), 1)

    def test_ctrl_wheel_updates_existing_cells_without_rebuilding_grid(self) -> None:
        widget = make_item_grid(active_tab_id="tab-documents")
        with TemporaryDirectory() as tmp:
            entries = [IndexedItem(Path(tmp) / f"zoom-{index}.pdf") for index in range(4)]
            for entry in entries:
                entry.path.write_text("x", encoding="utf-8")
            widget.set_entries(entries)
            widget.resize(420, 260)
            widget.show()
            type(self).app.processEvents()
            rebuilt = QSignalSpy(widget.cells_rebuilt)
            first_button = item_button_for_path(widget, entries[0].path)
            before_button = first_button
            before_icon = first_button.iconSize().width()

            send_ctrl_wheel(widget, 120)

            self.assertIs(item_button_for_path(widget, entries[0].path), before_button)
            self.assertGreater(first_button.iconSize().width(), before_icon)
            self.assertEqual(rebuilt.count(), 0)

    def test_alt_wheel_does_not_change_item_icon_size(self) -> None:
        widget = make_item_grid(active_tab_id="tab-documents")
        widget.resize(360, 260)
        widget.show()
        type(self).app.processEvents()
        before = widget.item_icon_size()

        send_alt_wheel(widget, 120)

        self.assertEqual(widget.item_icon_size(), before)

    def test_plain_wheel_does_not_change_item_icon_size(self) -> None:
        widget = make_item_grid(active_tab_id="tab-documents")
        widget.resize(360, 260)
        widget.show()
        type(self).app.processEvents()
        before = widget.item_icon_size()
        center = widget.rect().center()
        event = QWheelEvent(
            QPointF(center),
            QPointF(widget.mapToGlobal(center)),
            QPoint(0, 0),
            QPoint(0, 120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.ScrollUpdate,
            False,
        )

        QApplication.sendEvent(widget, event)
        process_qt_events()

        self.assertEqual(widget.item_icon_size(), before)

    def test_right_click_restorable_entry_uses_native_shell_menu_only(self) -> None:
        widget = make_item_grid(active_tab_id="tab-documents")
        recorder = ShellMenuRecorder()
        widget.set_context_menu_launcher(recorder)
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "photo.png"
            source.write_text("img", encoding="utf-8")
            entries = [IndexedItem(source)]

            widget.set_entries(entries, restorable_paths={source.resolve()})
            widget.resize(320, 240)
            widget.show()
            type(self).app.processEvents()

            QTest.mouseClick(item_button_for_path(widget, source), Qt.MouseButton.RightButton)
            type(self).app.processEvents()

            self.assertEqual(widget.selected_path(), source.resolve())
            self.assertEqual([(call[1]) for call in recorder.calls], [source.resolve()])
            self.assertFalse(
                getattr(widget, "_context_menu", None),
                "native success must not create an in-app replacement menu",
            )

    def test_right_click_non_restorable_entry_still_uses_native_shell_menu(self) -> None:
        widget = make_item_grid(active_tab_id="tab-images")
        recorder = ShellMenuRecorder()
        widget.set_context_menu_launcher(recorder)
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            desktop_item = root / "auto-only.txt"
            external_item = root / "outside.weird"
            desktop_item.write_text("keep", encoding="utf-8")
            external_item.write_text("keep", encoding="utf-8")
            entries = [IndexedItem(desktop_item), IndexedItem(external_item)]

            widget.set_entries(entries, restorable_paths=set())
            widget.resize(320, 240)
            widget.show()
            type(self).app.processEvents()

            for path in (desktop_item, external_item):
                QTest.mouseClick(item_button_for_path(widget, path), Qt.MouseButton.RightButton)
                type(self).app.processEvents()

            self.assertEqual(
                [path for _owner, path, _pos in recorder.calls],
                [desktop_item.resolve(), external_item.resolve()],
            )

    def test_right_click_does_not_emit_restore_auto_requested_signal(self) -> None:
        widget = make_item_grid(active_tab_id="tab-documents")
        widget.set_context_menu_launcher(ShellMenuRecorder())
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "photo.png"
            source.write_text("img", encoding="utf-8")
            entries = [IndexedItem(source)]
            widget.set_entries(entries, restorable_paths={source.resolve()})
            widget.resize(320, 240)
            widget.show()
            type(self).app.processEvents()
            spy = QSignalSpy(widget.restore_auto_requested)

            QTest.mouseClick(item_button_for_path(widget, source), Qt.MouseButton.RightButton)
            type(self).app.processEvents()

            self.assertEqual(spy.count(), 0)

    def test_default_right_click_uses_windows_shell_context_menu_service(self) -> None:
        recorder = NativeShellServiceRecorder()
        with patch("desktop_tidy.ui.item_grid.ShellContextMenuService", return_value=recorder):
            widget = make_item_grid(active_tab_id="tab-apps")

        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "Canva.lnk"
            source.write_text("shortcut", encoding="utf-8")
            widget.set_entries([IndexedItem(source)])
            widget.resize(320, 240)
            widget.show()
            type(self).app.processEvents()

            QTest.mouseClick(item_button_for_path(widget, source), Qt.MouseButton.RightButton)
            type(self).app.processEvents()

            self.assertEqual([path for _owner, path, _pos in recorder.calls], [source.resolve()])
            self.assertFalse(
                getattr(widget, "_context_menu", None),
                "default right click should not open the in-app fallback menu",
            )

    def test_item_labels_hide_file_extensions_without_modifying_paths(self) -> None:
        widget = make_item_grid(active_tab_id="tab-apps")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = [
                root / "Canva.lnk",
                root / "Terraria.url",
                root / "script.py",
                root / "archive.tar.gz",
            ]
            for path in paths:
                path.write_text("x", encoding="utf-8")

            widget.set_entries([IndexedItem(path) for path in paths])
            widget.resize(640, 320)
            widget.show()
            type(self).app.processEvents()

            self.assertEqual([display_name_for_path(path) for path in paths], [
                "Canva",
                "Terraria",
                "script",
                "archive",
            ])
            labels = [item_label_for_path(widget, path).text() for path in paths]
            for label, suffix in zip(labels, (".lnk", ".url", ".py", ".tar.gz")):
                self.assertNotIn(suffix, label)
            self.assertEqual(widget.entry_paths(), [path.resolve() for path in paths])

    def test_short_desktop_style_names_get_enough_width_for_one_line(self) -> None:
        widget = make_item_grid(active_tab_id="tab-apps")
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "\u5c0f\u9ed1\u76d2\u52a0\u901f\u5668.lnk"
            source.write_text("shortcut", encoding="utf-8")
            widget.set_entries([IndexedItem(source)])
            widget.resize(640, 320)
            widget.show()
            type(self).app.processEvents()

            label = item_label_for_path(widget, source)
            required_width = label.fontMetrics().horizontalAdvance("\u5c0f\u9ed1\u76d2\u52a0\u901f\u5668")

            self.assertNotIn("\n", label.text())
            self.assertGreaterEqual(
                label.width(),
                required_width,
                "desktop-style labels must not be compressed narrower than short app names",
            )


    def test_many_entries_do_not_inflate_grid_widget_minimum_height(self) -> None:
        """Many entries must not force the grid widget to a huge minimum height."""
        widget = make_item_grid()
        with TemporaryDirectory() as tmp:
            entries = [
                IndexedItem(Path(tmp) / f"item-{index:03d}.txt")
                for index in range(50)
            ]
            for entry in entries:
                entry.path.write_text("x", encoding="utf-8")
            widget.set_entries(entries)
            widget.resize(320, 240)
            widget.show()
            type(self).app.processEvents()

            effective_min = widget.effective_minimum_height()
            self.assertLess(
                effective_min,
                400,
                f"50 items must not force min height to {effective_min}px; "
                "grid must be scrollable",
            )
            self.assertGreater(
                widget.item_count(),
                20,
                "setup should produce more than 20 items",
            )

    def test_double_click_item_emits_item_activated_signal(self) -> None:
        """Double-click on an item cell must emit item_activated with the correct Path."""
        widget = make_item_grid(active_tab_id="tab-documents")
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "report.pdf"
            source.write_text("pdf-content", encoding="utf-8")
            entries = [IndexedItem(source)]
            widget.set_entries(entries)
            widget.resize(320, 240)
            widget.show()
            type(self).app.processEvents()

            spy = QSignalSpy(widget.item_activated)
            button = _grid_item_buttons(widget)[0]
            QTest.mouseDClick(button, Qt.MouseButton.LeftButton)
            type(self).app.processEvents()

            self.assertEqual(spy.count(), 1)
            self.assertEqual(Path(spy.at(0)[0]).resolve(), source.resolve())

    def test_double_click_cell_background_emits_item_activated(self) -> None:
        """Double-click on the cell background (not button/label) must emit item_activated."""
        widget = make_item_grid(active_tab_id="tab-documents")
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "cell-click.pdf"
            source.write_text("data", encoding="utf-8")
            entries = [IndexedItem(source)]
            widget.set_entries(entries)
            widget.resize(320, 240)
            widget.show()
            type(self).app.processEvents()

            layout = widget._grid_host.layout()
            cell = layout.itemAt(0).widget()
            self.assertIsNotNone(cell, "grid must have a cell widget")

            spy = QSignalSpy(widget.item_activated)
            QTest.mouseDClick(cell, Qt.MouseButton.LeftButton)
            type(self).app.processEvents()

            self.assertEqual(spy.count(), 1)
            self.assertEqual(Path(spy.at(0)[0]).resolve(), source.resolve())

    def test_single_click_cell_background_does_not_emit_item_activated(self) -> None:
        """Single-click on the cell background must NOT emit item_activated."""
        widget = make_item_grid(active_tab_id="tab-documents")
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "cell-no-emit.txt"
            source.write_text("text", encoding="utf-8")
            entries = [IndexedItem(source)]
            widget.set_entries(entries)
            widget.resize(320, 240)
            widget.show()
            type(self).app.processEvents()

            layout = widget._grid_host.layout()
            cell = layout.itemAt(0).widget()
            self.assertIsNotNone(cell, "grid must have a cell widget")

            spy = QSignalSpy(widget.item_activated)
            QTest.mouseClick(cell, Qt.MouseButton.LeftButton)
            type(self).app.processEvents()

            self.assertEqual(spy.count(), 0)

    def test_single_click_item_selects_without_activating(self) -> None:
        """Single-click should behave like Windows: select only, double-click opens."""
        widget = make_item_grid(active_tab_id="tab-documents")
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "select-me.txt"
            source.write_text("text", encoding="utf-8")
            widget.set_entries([IndexedItem(source)])
            widget.resize(320, 240)
            widget.show()
            type(self).app.processEvents()

            selected_spy = QSignalSpy(widget.item_selected)
            activated_spy = QSignalSpy(widget.item_activated)
            button = _grid_item_buttons(widget)[0]

            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
            type(self).app.processEvents()

            self.assertEqual(activated_spy.count(), 0)
            self.assertEqual(selected_spy.count(), 1)
            self.assertEqual(Path(selected_spy.at(0)[0]).resolve(), source.resolve())
            self.assertEqual(widget.selected_path(), source.resolve())

    def test_selection_moves_between_items(self) -> None:
        widget = make_item_grid(active_tab_id="tab-documents")
        with TemporaryDirectory() as tmp:
            first = Path(tmp) / "first.txt"
            second = Path(tmp) / "second.txt"
            first.write_text("1", encoding="utf-8")
            second.write_text("2", encoding="utf-8")
            widget.set_entries([IndexedItem(first), IndexedItem(second)])
            widget.resize(360, 240)
            widget.show()
            type(self).app.processEvents()

            buttons = _grid_item_buttons(widget)
            QTest.mouseClick(buttons[0], Qt.MouseButton.LeftButton)
            QTest.mouseClick(buttons[1], Qt.MouseButton.LeftButton)
            type(self).app.processEvents()

            self.assertEqual(widget.selected_path(), second.resolve())

    def test_right_click_selects_item_and_invokes_native_shell_context_menu(self) -> None:
        widget = make_item_grid(active_tab_id="tab-documents")
        recorder = ShellMenuRecorder()
        widget.set_context_menu_launcher(recorder)
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "right-click.txt"
            source.write_text("text", encoding="utf-8")
            widget.set_entries([IndexedItem(source)])
            widget.resize(320, 240)
            widget.show()
            type(self).app.processEvents()

            selected_spy = QSignalSpy(widget.item_selected)
            activated_spy = QSignalSpy(widget.item_activated)
            QTest.mouseClick(item_button_for_path(widget, source), Qt.MouseButton.RightButton)
            type(self).app.processEvents()

            self.assertEqual(activated_spy.count(), 0)
            self.assertEqual(selected_spy.count(), 1)
            self.assertEqual(widget.selected_path(), source.resolve())
            self.assertEqual(len(recorder.calls), 1)
            owner, path, global_pos = recorder.calls[0]
            self.assertIs(owner, widget.window())
            self.assertEqual(path, source.resolve())
            self.assertIsInstance(global_pos, QPoint)

    def test_native_shell_context_menu_opens_on_right_button_release(self) -> None:
        widget = make_item_grid(active_tab_id="tab-documents")
        recorder = ShellMenuRecorder()
        widget.set_context_menu_launcher(recorder)
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "release-menu.txt"
            source.write_text("text", encoding="utf-8")
            widget.set_entries([IndexedItem(source)])
            widget.resize(320, 240)
            widget.show()
            type(self).app.processEvents()
            button = item_button_for_path(widget, source)

            QTest.mousePress(button, Qt.MouseButton.RightButton)
            type(self).app.processEvents()

            self.assertEqual(recorder.calls, [])
            self.assertEqual(widget.selected_path(), source.resolve())

            QTest.mouseRelease(button, Qt.MouseButton.RightButton)
            type(self).app.processEvents()

            self.assertEqual([path for _owner, path, _pos in recorder.calls], [source.resolve()])

    def test_right_click_selects_from_icon_label_and_cell_surface(self) -> None:
        widget = make_item_grid(active_tab_id="tab-documents")
        recorder = ShellMenuRecorder()
        widget.set_context_menu_launcher(recorder)
        with TemporaryDirectory() as tmp:
            first = Path(tmp) / "icon-target.txt"
            second = Path(tmp) / "label-target.txt"
            third = Path(tmp) / "cell-target.txt"
            for path in (first, second, third):
                path.write_text("text", encoding="utf-8")
            widget.set_entries([IndexedItem(first), IndexedItem(second), IndexedItem(third)])
            widget.resize(420, 240)
            widget.show()
            type(self).app.processEvents()

            QTest.mouseClick(item_button_for_path(widget, first), Qt.MouseButton.RightButton)
            type(self).app.processEvents()
            self.assertEqual(widget.selected_path(), first.resolve())
            self.assertIn("rgba(255,255,255,0.18)", item_cell_for_path(widget, first).styleSheet())

            QTest.mouseClick(item_label_for_path(widget, second), Qt.MouseButton.RightButton)
            type(self).app.processEvents()
            self.assertEqual(widget.selected_path(), second.resolve())
            self.assertIn("rgba(255,255,255,0.18)", item_cell_for_path(widget, second).styleSheet())

            QTest.mouseClick(item_cell_for_path(widget, third), Qt.MouseButton.RightButton)
            type(self).app.processEvents()
            self.assertEqual(widget.selected_path(), third.resolve())
            self.assertIn("rgba(255,255,255,0.18)", item_cell_for_path(widget, third).styleSheet())
            self.assertEqual(
                [path for _owner, path, _pos in recorder.calls],
                [first.resolve(), second.resolve(), third.resolve()],
            )

    def test_right_click_falls_back_to_basic_menu_when_native_shell_menu_fails(self) -> None:
        widget = make_item_grid(active_tab_id="tab-documents")
        recorder = ShellMenuFailureRecorder()
        fallback_calls: list[tuple[Path, QPoint]] = []
        widget.set_context_menu_launcher(recorder)
        widget.set_fallback_context_menu(
            lambda path, global_pos: fallback_calls.append((path.resolve(), QPoint(global_pos)))
        )
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "fallback-menu.txt"
            source.write_text("text", encoding="utf-8")
            widget.set_entries([IndexedItem(source)])
            widget.resize(320, 240)
            widget.show()
            type(self).app.processEvents()

            QTest.mouseClick(item_button_for_path(widget, source), Qt.MouseButton.RightButton)
            type(self).app.processEvents()

            self.assertEqual([path for _owner, path, _pos in recorder.calls], [source.resolve()])
            self.assertEqual(fallback_calls, [(source.resolve(), fallback_calls[0][1])])

    def test_context_menu_event_does_not_open_qt_fallback_when_native_menu_fails_by_default(self) -> None:
        widget = make_item_grid(active_tab_id="tab-documents")
        widget.set_context_menu_launcher(ShellMenuFailureRecorder())
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "context-event.txt"
            source.write_text("text", encoding="utf-8")
            widget.set_entries([IndexedItem(source)])
            widget.resize(320, 240)
            widget.show()
            type(self).app.processEvents()
            button = item_button_for_path(widget, source)
            local = button.rect().center()
            event = QContextMenuEvent(
                QContextMenuEvent.Reason.Mouse,
                local,
                button.mapToGlobal(local),
            )

            QApplication.sendEvent(button, event)
            type(self).app.processEvents()

            menu = getattr(widget, "_context_menu", None)
            self.assertIsNone(menu, "native failure should not open an in-app replacement menu")

    def test_compact_list_mode_uses_hysteresis_near_width_threshold(self) -> None:
        widget = make_item_grid(active_tab_id="tab-documents")
        with TemporaryDirectory() as tmp:
            entries = [IndexedItem(Path(tmp) / f"narrow-{index}.pdf") for index in range(4)]
            for entry in entries:
                entry.path.write_text("x", encoding="utf-8")
            widget.resize(330, 260)
            widget.show()
            widget.set_entries(entries)
            type(self).app.processEvents()
            first_label = item_label_for_path(widget, entries[0].path)
            self.assertFalse(first_label.wordWrap())

            widget.resize(378, 260)
            type(self).app.processEvents()

            self.assertEqual(widget.column_count(), 1)
            self.assertFalse(
                item_label_for_path(widget, entries[0].path).wordWrap(),
                "compact list must not flicker back to grid near the threshold",
            )

    def test_right_click_native_shell_menu_does_not_emit_activation(self) -> None:
        widget = make_item_grid(active_tab_id="tab-documents")
        widget.set_context_menu_launcher(ShellMenuRecorder())
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "no-open-menu.txt"
            source.write_text("text", encoding="utf-8")
            widget.set_entries([IndexedItem(source)])
            widget.resize(320, 240)
            widget.show()
            type(self).app.processEvents()

            activated_spy = QSignalSpy(widget.item_activated)
            QTest.mouseClick(item_button_for_path(widget, source), Qt.MouseButton.RightButton)
            type(self).app.processEvents()

            self.assertEqual(activated_spy.count(), 0)

    def test_resize_without_column_change_does_not_rebuild_cells(self) -> None:
        widget = make_item_grid(active_tab_id="tab-documents")
        with TemporaryDirectory() as tmp:
            entries = [IndexedItem(Path(tmp) / f"item-{index}.pdf") for index in range(5)]
            for entry in entries:
                entry.path.write_text("x", encoding="utf-8")
            widget.resize(540, 260)
            widget.show()
            widget.set_entries(entries)
            type(self).app.processEvents()
            initial_columns = widget.column_count()
            rebuilt = QSignalSpy(widget.cells_rebuilt)

            widget.resize(548, 260)
            type(self).app.processEvents()

            self.assertEqual(widget.column_count(), initial_columns)
            self.assertEqual(rebuilt.count(), 0)

    def test_single_click_item_does_not_emit_item_activated(self) -> None:
        """Single-click on an item must NOT emit item_activated."""
        widget = make_item_grid(active_tab_id="tab-documents")
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "note.txt"
            source.write_text("text", encoding="utf-8")
            entries = [IndexedItem(source)]
            widget.set_entries(entries)
            widget.resize(320, 240)
            widget.show()
            type(self).app.processEvents()

            spy = QSignalSpy(widget.item_activated)
            button = _grid_item_buttons(widget)[0]
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
            type(self).app.processEvents()

            self.assertEqual(spy.count(), 0)


if __name__ == "__main__":
    unittest.main()
