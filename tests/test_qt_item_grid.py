from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QUrl
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QToolButton

from desktop_tidy.domain.defaults import build_default_configuration
from desktop_tidy.services.desktop_index import IndexedItem
from desktop_tidy.ui.item_grid import ItemGridWidget
from desktop_tidy.ui.panel_group import PanelGroupWidget

_RESTORE_AUTO_LABEL = "恢复自动分类"


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


def context_menu_action_labels(grid: ItemGridWidget, path: Path) -> list[str]:
    button = item_button_for_path(grid, path)
    QTest.mouseClick(button, Qt.MouseButton.RightButton)
    process_qt_events()
    return [action.text() for action in button.actions() if action.text()]


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

    def test_item_spacing_stays_compact_when_panel_is_wide(self) -> None:
        widget = make_item_grid(active_tab_id="tab-documents")
        with TemporaryDirectory() as tmp:
            entries = [IndexedItem(Path(tmp) / f"item-{index}.pdf") for index in range(8)]
            for entry in entries:
                entry.path.write_text("x", encoding="utf-8")
            widget.resize(1400, 320)
            widget.show()
            widget.set_entries(entries)
            type(self).app.processEvents()

            layout = widget._grid_host.layout()
            first = layout.itemAt(0).widget()
            second = layout.itemAt(1).widget()
            self.assertIsNotNone(first)
            self.assertIsNotNone(second)
            gap = second.geometry().x() - first.geometry().x()

            self.assertLessEqual(gap, 130)

    def test_restorable_entry_keeps_restore_auto_action_hidden_from_right_click_ui(self) -> None:
        widget = make_item_grid(active_tab_id="tab-documents")
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "photo.png"
            source.write_text("img", encoding="utf-8")
            entries = [IndexedItem(source)]

            widget.set_entries(entries, restorable_paths={source.resolve()})
            widget.resize(320, 240)
            widget.show()
            type(self).app.processEvents()

            labels = context_menu_action_labels(widget, source)
            self.assertNotIn(_RESTORE_AUTO_LABEL, labels)

    def test_non_restorable_entries_hide_restore_auto_context_menu_action(self) -> None:
        widget = make_item_grid(active_tab_id="tab-images")
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
                labels = context_menu_action_labels(widget, path)
                self.assertNotIn(
                    _RESTORE_AUTO_LABEL,
                    labels,
                    f"{path.name} must not expose restore-auto when not restorable",
                )

    def test_right_click_does_not_emit_restore_auto_requested_signal(self) -> None:
        widget = make_item_grid(active_tab_id="tab-documents")
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

    def test_right_click_selects_item_without_opening_or_showing_custom_menu(self) -> None:
        widget = make_item_grid(active_tab_id="tab-documents")
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "right-click.txt"
            source.write_text("text", encoding="utf-8")
            widget.set_entries([IndexedItem(source)])
            widget.resize(320, 240)
            widget.show()
            type(self).app.processEvents()

            selected_spy = QSignalSpy(widget.item_selected)
            activated_spy = QSignalSpy(widget.item_activated)
            labels = context_menu_action_labels(widget, source)
            popup = QApplication.activePopupWidget()

            self.assertEqual(activated_spy.count(), 0)
            self.assertEqual(selected_spy.count(), 1)
            self.assertEqual(widget.selected_path(), source.resolve())
            self.assertEqual(labels, [])
            self.assertIsNone(popup)

    def test_right_click_does_not_expose_open_action(self) -> None:
        widget = make_item_grid(active_tab_id="tab-documents")
        with TemporaryDirectory() as tmp:
            source = Path(tmp) / "no-open-menu.txt"
            source.write_text("text", encoding="utf-8")
            widget.set_entries([IndexedItem(source)])
            widget.resize(320, 240)
            widget.show()
            type(self).app.processEvents()

            button = item_button_for_path(widget, source)
            QTest.mouseClick(button, Qt.MouseButton.RightButton)
            type(self).app.processEvents()

            activated_spy = QSignalSpy(widget.item_activated)
            type(self).app.processEvents()

            self.assertEqual(activated_spy.count(), 0)
            self.assertEqual(button.actions(), [])

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
