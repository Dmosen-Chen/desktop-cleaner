from __future__ import annotations

import inspect
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QContextMenuEvent, QDropEvent, QMouseEvent, QWheelEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsOpacityEffect,
    QLabel,
    QLineEdit,
    QToolButton,
    QWidget,
)
from shiboken6 import delete, isValid

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


def close_desktop_logger_handlers() -> None:
    from desktop_tidy.services.logging_setup import get_logger

    logger = get_logger()
    for handler in list(logger.handlers):
        handler.flush()
        handler.close()
        logger.removeHandler(handler)


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

    def test_drag_style_application_ignores_stale_deleted_cells(self) -> None:
        widget = make_item_grid()
        stale_path = Path(r"D:\Preview\Desktop\stale.pdf").resolve()
        stale_cell = QWidget()
        widget._cells_by_path[stale_path] = stale_cell
        widget._dragging_paths = {stale_path}
        delete(stale_cell)
        self.assertFalse(isValid(stale_cell))

        widget._apply_dragging_cell_styles(True)

        self.assertNotIn(stale_path, widget._cells_by_path)

    def test_drag_style_cleanup_ignores_stale_deleted_effect_cells(self) -> None:
        widget = make_item_grid()
        stale_cell = QWidget()
        widget._drag_opacity_effects[stale_cell] = QGraphicsOpacityEffect(stale_cell)
        delete(stale_cell)
        self.assertFalse(isValid(stale_cell))

        widget._apply_dragging_cell_styles(False)

        self.assertEqual(widget._drag_opacity_effects, {})

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

    def test_item_spacing_stays_fixed_when_panel_is_wide(self) -> None:
        widget = make_item_grid(active_tab_id="tab-documents")
        with TemporaryDirectory() as tmp:
            entries = [IndexedItem(Path(tmp) / f"item-{index}.pdf") for index in range(6)]
            for entry in entries:
                entry.path.write_text("x", encoding="utf-8")
            widget.resize(520, 320)
            widget.show()
            widget.set_entries(entries)
            type(self).app.processEvents()
            layout = widget._grid_host.layout()
            narrow_spacing = layout.horizontalSpacing()

            widget.resize(960, 320)
            type(self).app.processEvents()
            wide_spacing = layout.horizontalSpacing()
            first = layout.itemAt(0).widget()
            last = layout.itemAt(min(widget.column_count(), len(entries)) - 1).widget()
            self.assertIsNotNone(first)
            self.assertIsNotNone(last)
            viewport_width = widget._scroll_area.viewport().width()
            right_gap = viewport_width - last.geometry().right()

            self.assertEqual(wide_spacing, narrow_spacing)
            self.assertGreater(
                right_gap,
                48,
                "wide panels should keep fixed desktop-like icon spacing and leave spare room on the right",
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

    def test_ctrl_click_toggles_multi_selection(self) -> None:
        widget = make_item_grid(active_tab_id="tab-documents")
        with TemporaryDirectory() as tmp:
            first = Path(tmp) / "first.txt"
            second = Path(tmp) / "second.txt"
            third = Path(tmp) / "third.txt"
            for path in (first, second, third):
                path.write_text("x", encoding="utf-8")
            widget.set_entries([IndexedItem(first), IndexedItem(second), IndexedItem(third)])
            widget.resize(420, 240)
            widget.show()
            type(self).app.processEvents()

            buttons = _grid_item_buttons(widget)
            QTest.mouseClick(buttons[0], Qt.MouseButton.LeftButton)
            QTest.mouseClick(
                buttons[1],
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.ControlModifier,
            )
            QTest.mouseClick(
                buttons[2],
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.ControlModifier,
            )
            type(self).app.processEvents()

            self.assertEqual(
                widget.selected_paths(),
                frozenset({first.resolve(), second.resolve(), third.resolve()}),
            )

            QTest.mouseClick(
                buttons[1],
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.ControlModifier,
            )
            type(self).app.processEvents()
            self.assertEqual(
                widget.selected_paths(),
                frozenset({first.resolve(), third.resolve()}),
            )

    def test_shift_click_selects_visual_range(self) -> None:
        widget = make_item_grid(active_tab_id="tab-documents")
        with TemporaryDirectory() as tmp:
            paths = [Path(tmp) / f"item-{index}.txt" for index in range(6)]
            for path in paths:
                path.write_text("x", encoding="utf-8")
            widget.set_entries([IndexedItem(path) for path in paths])
            widget.resize(420, 260)
            widget.show()
            type(self).app.processEvents()

            buttons = _grid_item_buttons(widget)
            QTest.mouseClick(buttons[0], Qt.MouseButton.LeftButton)
            QTest.mouseClick(
                buttons[3],
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.ShiftModifier,
            )
            type(self).app.processEvents()

            self.assertEqual(
                widget.selected_paths(),
                frozenset(path.resolve() for path in paths[:4]),
            )

    def test_dragging_from_multi_selection_keeps_all_paths(self) -> None:
        widget = make_item_grid(active_tab_id="tab-documents")
        with TemporaryDirectory() as tmp:
            first = Path(tmp) / "first.txt"
            second = Path(tmp) / "second.txt"
            third = Path(tmp) / "third.txt"
            for path in (first, second, third):
                path.write_text("x", encoding="utf-8")
            widget.set_entries([IndexedItem(first), IndexedItem(second), IndexedItem(third)])
            widget.resize(420, 240)
            widget.show()
            type(self).app.processEvents()

            buttons = _grid_item_buttons(widget)
            QTest.mouseClick(buttons[0], Qt.MouseButton.LeftButton)
            QTest.mouseClick(
                buttons[2],
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.ControlModifier,
            )
            type(self).app.processEvents()

            QTest.mousePress(buttons[0], Qt.MouseButton.LeftButton)
            type(self).app.processEvents()
            dragged = widget._drag_paths_for(first.resolve())
            self.assertEqual(
                dragged,
                [first.resolve(), third.resolve()],
            )

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

    def test_set_entries_with_same_render_payload_does_not_rebuild_cells(self) -> None:
        widget = make_item_grid(active_tab_id="tab-documents")
        with TemporaryDirectory() as tmp:
            entries = [IndexedItem(Path(tmp) / f"item-{index}.pdf") for index in range(4)]
            for entry in entries:
                entry.path.write_text("x", encoding="utf-8")
            widget.resize(540, 260)
            widget.show()
            widget.set_entries(entries)
            type(self).app.processEvents()
            rebuilt = QSignalSpy(widget.cells_rebuilt)

            widget.set_entries(entries)
            type(self).app.processEvents()

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

    def test_reordered_entry_paths_moves_source_to_target_index(self) -> None:
        widget = make_item_grid(active_tab_id="tab-images")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = [IndexedItem(root / name) for name in ["a.png", "b.png", "c.png"]]
            for entry in entries:
                entry.path.write_text("x", encoding="utf-8")
            widget.set_entries(entries)

            moved = widget.reordered_entry_paths(entries[2].path, 0)

            self.assertEqual(
                moved,
                [entries[2].path.resolve(), entries[0].path.resolve(), entries[1].path.resolve()],
            )

    def test_reordered_anchor_paths_for_drag_moves_block_together(self) -> None:
        widget = make_item_grid(active_tab_id="tab-images")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = [
                IndexedItem(root / name)
                for name in ["a.png", "b.png", "c.png", "d.png"]
            ]
            for entry in entries:
                entry.path.write_text("x", encoding="utf-8")
            widget.set_entries(entries)

            moved = widget.reordered_anchor_paths_for_drag(
                [entries[1].path, entries[3].path],
                0,
            )

            self.assertEqual(
                moved,
                [
                    entries[1].path.resolve(),
                    entries[3].path.resolve(),
                    entries[0].path.resolve(),
                    entries[2].path.resolve(),
                ],
            )

    def test_internal_reorder_emits_signal_and_keeps_files_untouched(self) -> None:
        widget = make_item_grid(active_tab_id="tab-images")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = [IndexedItem(root / name) for name in ["a.png", "b.png", "c.png"]]
            for entry in entries:
                entry.path.write_text(entry.path.name, encoding="utf-8")
            widget.resize(640, 400)
            widget.show()
            widget.set_entries(entries)
            type(self).app.processEvents()

            spy = QSignalSpy(widget.items_reordered)
            widget._apply_internal_reorder(entries[2].path, 0)
            type(self).app.processEvents()

            self.assertEqual(spy.count(), 1)
            tab_id, ordered = spy.at(0)[0], spy.at(0)[1]
            self.assertEqual(tab_id, "tab-images")
            self.assertEqual(
                [Path(p) for p in ordered],
                [entries[2].path.resolve(), entries[0].path.resolve(), entries[1].path.resolve()],
            )
            self.assertEqual(
                widget.entry_paths(),
                [entries[2].path.resolve(), entries[0].path.resolve(), entries[1].path.resolve()],
            )
            for entry in entries:
                self.assertTrue(entry.path.is_file())
                self.assertEqual(entry.path.read_text(encoding="utf-8"), entry.path.name)

    def test_drop_event_with_item_mime_reorders_item(self) -> None:
        from PySide6.QtCore import QMimeData, QPointF
        from PySide6.QtGui import QDropEvent

        from desktop_tidy.ui.item_grid import ITEM_MIME_TYPE

        widget = make_item_grid(active_tab_id="tab-images")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = [IndexedItem(root / name) for name in ["a.png", "b.png", "c.png"]]
            for entry in entries:
                entry.path.write_text("x", encoding="utf-8")
            widget.resize(640, 400)
            widget.show()
            widget.set_entries(entries)
            type(self).app.processEvents()

            target_cell = item_cell_for_path(widget, entries[0].path)
            pos = QPointF(target_cell.mapTo(widget, target_cell.rect().topLeft()))
            mime = QMimeData()
            mime.setData(
                ITEM_MIME_TYPE, str(entries[2].path.resolve()).encode("utf-8")
            )
            event = QDropEvent(
                pos,
                Qt.DropAction.MoveAction,
                mime,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )

            spy = QSignalSpy(widget.items_reordered)
            widget.dropEvent(event)
            type(self).app.processEvents()

            self.assertEqual(spy.count(), 1)
            self.assertEqual(widget.entry_paths()[0], entries[2].path.resolve())

    def test_drop_after_tab_preview_emits_paths_dropped_for_cross_tab_move(self) -> None:
        widget = make_item_grid(active_tab_id="tab-documents")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = IndexedItem(root / "game.url")
            source.path.write_text("url", encoding="utf-8")
            widget.resize(640, 400)
            widget.show()
            widget.set_entries([source])
            type(self).app.processEvents()

            widget._item_drag_origin_tab_id = "tab-folders"
            widget.set_active_tab_id("tab-apps")
            spy = QSignalSpy(widget.paths_dropped)
            widget._handle_item_drop(source.path, QPoint(12, 12), origin_tab="tab-folders")
            type(self).app.processEvents()

            self.assertEqual(spy.count(), 1)
            paths, tab_id = spy.at(0)[0], spy.at(0)[1]
            self.assertEqual(tab_id, "tab-apps")
            self.assertEqual([Path(p) for p in paths], [source.path.resolve()])

    def test_drop_on_other_panel_grid_uses_mime_origin_tab(self) -> None:
        from PySide6.QtCore import QMimeData, QPointF
        from PySide6.QtGui import QDropEvent

        from desktop_tidy.ui.item_grid import ITEM_MIME_ORIGIN_TAB, ITEM_MIME_TYPE

        target = make_item_grid(active_tab_id="tab-images")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "other-panel.url"
            source.write_text("url", encoding="utf-8")
            target.resize(640, 400)
            target.show()
            target.set_active_tab_id("tab-archives")
            target.set_entries([])
            type(self).app.processEvents()

            mime = QMimeData()
            mime.setData(ITEM_MIME_TYPE, str(source.resolve()).encode("utf-8"))
            mime.setData(ITEM_MIME_ORIGIN_TAB, b"tab-apps")
            event = QDropEvent(
                QPointF(24, 24),
                Qt.DropAction.MoveAction,
                mime,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
            spy = QSignalSpy(target.paths_dropped)
            target.dropEvent(event)
            type(self).app.processEvents()

            self.assertEqual(spy.count(), 1)
            paths, tab_id = spy.at(0)[0], spy.at(0)[1]
            self.assertEqual(tab_id, "tab-archives")
            self.assertEqual([Path(p) for p in paths], [source.resolve()])

    def test_reorder_disabled_blocks_internal_reorder(self) -> None:
        widget = make_item_grid(active_tab_id="tab-images")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = [IndexedItem(root / name) for name in ["a.png", "b.png"]]
            for entry in entries:
                entry.path.write_text("x", encoding="utf-8")
            widget.set_entries(entries)
            widget.set_reorder_enabled(False)

            spy = QSignalSpy(widget.items_reordered)
            widget._apply_internal_reorder(entries[1].path, 0)

            self.assertEqual(spy.count(), 0)
            self.assertEqual(widget.entry_paths(), [entries[0].path.resolve(), entries[1].path.resolve()])


class ItemGroupRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = qt_app()

    def _entries(self, root: Path, names: list[str]) -> list[IndexedItem]:
        entries = []
        for name in names:
            path = root / name
            path.write_text(name, encoding="utf-8")
            entries.append(IndexedItem(path))
        return entries

    def test_item_grid_main_class_does_not_depend_on_legacy_group_popup(self) -> None:
        from desktop_tidy.ui import item_grid as item_grid_module

        source = inspect.getsource(item_grid_module)

        self.assertNotIn("GroupFolderPopup", source)
        self.assertNotIn("_GroupPopupBackdrop", source)
        self.assertNotIn("groupPopupBackdrop", source)

    def test_item_grid_group_rename_does_not_depend_on_input_dialog(self) -> None:
        from desktop_tidy.ui import item_grid as item_grid_module

        source = inspect.getsource(item_grid_module)

        self.assertNotIn("QInputDialog", source)

    def test_group_block_renders_folder_cell_instead_of_inline_members(self) -> None:
        from desktop_tidy.ui.item_grid import GroupBlock

        widget = make_item_grid(active_tab_id="tab-images")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = self._entries(root, ["a.png", "b.png", "c.png"])
            widget.resize(640, 400)
            widget.show()
            block = GroupBlock(
                group_id="g1",
                name="游戏",
                members=[entries[1].path.resolve(), entries[2].path.resolve()],
            )
            widget.set_entries(entries, groups=[block])
            self.app.processEvents()

            self.assertIn("g1", widget._cells_by_group_id)
            self.assertNotIn(entries[1].path.resolve(), widget._cells_by_path)
            self.assertNotIn(entries[2].path.resolve(), widget._cells_by_path)
            self.assertIn(entries[0].path.resolve(), widget._cells_by_path)

    def test_drag_icon_onto_folder_joins_group(self) -> None:
        from desktop_tidy.ui.item_grid import GroupBlock

        widget = make_item_grid(active_tab_id="tab-images")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = self._entries(root, ["a.png", "b.png", "c.png"])
            widget.resize(640, 400)
            widget.show()
            block = GroupBlock(
                group_id="g1",
                name="组",
                members=[entries[1].path.resolve(), entries[2].path.resolve()],
            )
            widget.set_entries(entries, groups=[block])
            self.app.processEvents()

            folder_cell = widget._cells_by_group_id["g1"]
            host_point = folder_cell.mapTo(
                widget._grid_host, folder_cell.rect().center()
            )

            spy = QSignalSpy(widget.group_join_requested)
            widget._handle_item_drop(entries[0].path, host_point)

            self.assertEqual(spy.count(), 1)
            group_id, members = spy.at(0)[0], spy.at(0)[1]
            self.assertEqual(group_id, "g1")
            self.assertEqual(
                [Path(p) for p in members],
                [entries[0].path.resolve()],
            )

    def test_drag_icon_onto_another_creates_group(self) -> None:
        widget = make_item_grid(active_tab_id="tab-images")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = self._entries(root, ["a.png", "b.png", "c.png"])
            widget.resize(640, 400)
            widget.show()
            widget.set_entries(entries)
            self.app.processEvents()

            target_cell = item_cell_for_path(widget, entries[0].path)
            host_point = target_cell.mapTo(
                widget._grid_host, target_cell.rect().center()
            )

            spy = QSignalSpy(widget.group_create_requested)
            widget._handle_item_drop(entries[2].path, host_point)

            self.assertEqual(spy.count(), 1)
            tab_id, members = spy.at(0)[0], spy.at(0)[1]
            self.assertEqual(tab_id, "tab-images")
            self.assertEqual(
                [Path(p) for p in members],
                [entries[0].path.resolve(), entries[2].path.resolve()],
            )
            for entry in entries:
                self.assertTrue(entry.path.is_file())

    def test_drag_icon_onto_another_uses_target_icon_as_group_anchor(self) -> None:
        widget = make_item_grid(active_tab_id="tab-images")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = self._entries(root, ["source.png", "target.png"])
            widget.resize(640, 400)
            widget.show()
            widget.set_entries(entries)
            self.app.processEvents()

            target_cell = item_cell_for_path(widget, entries[1].path)
            host_point = target_cell.mapTo(
                widget._grid_host, target_cell.rect().center()
            )

            spy = QSignalSpy(widget.group_create_requested)
            widget._handle_item_drop(entries[0].path, host_point)

            self.assertEqual(spy.count(), 1)
            _tab_id, members = spy.at(0)[0], spy.at(0)[1]
            self.assertEqual(
                [Path(p) for p in members],
                [entries[1].path.resolve(), entries[0].path.resolve()],
            )

    def test_drag_icon_onto_folder_joins_existing_group(self) -> None:
        from desktop_tidy.ui.item_grid import GroupBlock

        widget = make_item_grid(active_tab_id="tab-images")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = self._entries(root, ["a.png", "b.png", "c.png"])
            widget.resize(640, 400)
            widget.show()
            block = GroupBlock(group_id="g1", name="组", members=[entries[1].path.resolve()])
            widget.set_entries(entries, groups=[block])
            self.app.processEvents()

            folder_cell = widget._cells_by_group_id["g1"]
            host_point = folder_cell.mapTo(
                widget._grid_host, folder_cell.rect().center()
            )

            spy = QSignalSpy(widget.group_join_requested)
            widget._handle_item_drop(entries[0].path, host_point)

            self.assertEqual(spy.count(), 1)
            group_id, members = spy.at(0)[0], spy.at(0)[1]
            self.assertEqual(group_id, "g1")
            self.assertEqual([Path(p) for p in members], [entries[0].path.resolve()])

    def test_group_right_click_then_left_click_opens_folder(self) -> None:
        from desktop_tidy.ui.item_grid import GroupBlock

        widget = make_item_grid(active_tab_id="tab-images")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = self._entries(root, ["a.png", "b.png"])
            widget.resize(640, 400)
            widget.show()
            block = GroupBlock(
                group_id="g1",
                name="Group",
                members=[entry.path.resolve() for entry in entries],
            )
            widget.set_entries(entries, groups=[block])
            self.app.processEvents()

            folder_cell = widget._cells_by_group_id["g1"]
            center = folder_cell.rect().center()
            global_center = folder_cell.mapToGlobal(center)

            widget.eventFilter(
                folder_cell,
                QMouseEvent(
                    QEvent.Type.MouseButtonPress,
                    QPointF(center),
                    QPointF(global_center),
                    Qt.MouseButton.RightButton,
                    Qt.MouseButton.RightButton,
                    Qt.KeyboardModifier.NoModifier,
                ),
            )
            widget.eventFilter(
                folder_cell,
                QMouseEvent(
                    QEvent.Type.MouseButtonRelease,
                    QPointF(center),
                    QPointF(global_center),
                    Qt.MouseButton.RightButton,
                    Qt.MouseButton.NoButton,
                    Qt.KeyboardModifier.NoModifier,
                ),
            )
            widget._dismiss_context_menu()

            widget.eventFilter(
                folder_cell,
                QMouseEvent(
                    QEvent.Type.MouseButtonPress,
                    QPointF(center),
                    QPointF(global_center),
                    Qt.MouseButton.LeftButton,
                    Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier,
                ),
            )
            widget.eventFilter(
                folder_cell,
                QMouseEvent(
                    QEvent.Type.MouseButtonRelease,
                    QPointF(center),
                    QPointF(global_center),
                    Qt.MouseButton.LeftButton,
                    Qt.MouseButton.NoButton,
                    Qt.KeyboardModifier.NoModifier,
                ),
            )
            self.app.processEvents()

            self.assertEqual(widget._open_group_id, "g1")
            self.assertIsNone(widget._open_group_popup)
            expansion = widget._scroll_area.viewport().findChild(
                QWidget,
                "inlineGroupExpansion",
            )
            self.assertIsNotNone(expansion)
            self.assertTrue(expansion.isVisible())

    def test_double_click_group_does_not_start_rename_or_delay_opening(self) -> None:
        from desktop_tidy.ui.item_grid import GroupBlock

        widget = make_item_grid(active_tab_id="tab-images")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = self._entries(root, ["a.png", "b.png"])
            widget.resize(640, 400)
            widget.show()
            block = GroupBlock(
                group_id="g1",
                name="Group",
                members=[entry.path.resolve() for entry in entries],
            )
            widget.set_entries(entries, groups=[block])
            self.app.processEvents()

            folder_cell = widget._cells_by_group_id["g1"]
            QTest.mouseDClick(folder_cell, Qt.MouseButton.LeftButton, pos=folder_cell.rect().center())
            self.app.processEvents()

            self.assertEqual(widget._open_group_id, "g1")
            editor = widget._folder_rename_editors_by_group_id.get("g1")
            self.assertTrue(editor is None or not isValid(editor))

    def test_single_click_group_opens_inline_expansion_immediately(self) -> None:
        from desktop_tidy.ui.item_grid import GroupBlock

        widget = make_item_grid(active_tab_id="tab-images")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = self._entries(root, ["a.png", "b.png"])
            widget.resize(640, 400)
            widget.show()
            block = GroupBlock(
                group_id="g1",
                name="Group",
                members=[entry.path.resolve() for entry in entries],
            )
            widget.set_entries(entries, groups=[block])
            self.app.processEvents()

            folder_cell = widget._cells_by_group_id["g1"]
            center = folder_cell.rect().center()
            global_center = folder_cell.mapToGlobal(center)
            widget.eventFilter(
                folder_cell,
                QMouseEvent(
                    QEvent.Type.MouseButtonPress,
                    QPointF(center),
                    QPointF(global_center),
                    Qt.MouseButton.LeftButton,
                    Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier,
                ),
            )
            widget.eventFilter(
                folder_cell,
                QMouseEvent(
                    QEvent.Type.MouseButtonRelease,
                    QPointF(center),
                    QPointF(global_center),
                    Qt.MouseButton.LeftButton,
                    Qt.MouseButton.NoButton,
                    Qt.KeyboardModifier.NoModifier,
                ),
            )
            self.app.processEvents()
            self.assertEqual(widget._open_group_id, "g1")
            expansion = widget._scroll_area.viewport().findChild(
                QWidget,
                "inlineGroupExpansion",
            )
            self.assertIsNotNone(expansion)
            self.assertTrue(expansion.isVisible())

    def test_single_click_group_opens_inline_expansion_without_top_level_widget(self) -> None:
        from desktop_tidy.ui.item_grid import GroupBlock

        widget = make_item_grid(active_tab_id="tab-images")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = self._entries(root, ["a.png", "b.png", "c.png"])
            widget.resize(640, 400)
            widget.show()
            block = GroupBlock(
                group_id="g1",
                name="Group",
                members=[entry.path.resolve() for entry in entries],
            )
            widget.set_entries(entries, groups=[block])
            self.app.processEvents()

            before = {
                id(top_level)
                for top_level in QApplication.topLevelWidgets()
                if top_level.isVisible()
            }
            folder_cell = widget._cells_by_group_id["g1"]
            QTest.mouseClick(
                folder_cell,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                folder_cell.rect().center(),
            )
            self.app.processEvents()

            after = {
                id(top_level)
                for top_level in QApplication.topLevelWidgets()
                if top_level.isVisible()
            }
            expansion = widget._scroll_area.viewport().findChild(
                QWidget,
                "inlineGroupExpansion",
            )
            self.assertEqual(before, after)
            self.assertIsNotNone(expansion)
            self.assertEqual(widget._open_group_id, "g1")
            self.assertIsNone(widget._open_group_popup)
            self.assertIsNone(widget._group_backdrop)

    def test_pending_group_open_keeps_existing_inline_expansion_open(self) -> None:
        from desktop_tidy.ui.item_grid import GroupBlock

        widget = make_item_grid(active_tab_id="tab-images")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = self._entries(root, ["a.png", "b.png"])
            widget.resize(640, 400)
            widget.show()
            block = GroupBlock(
                group_id="g1",
                name="Group",
                members=[entry.path.resolve() for entry in entries],
            )
            widget.set_entries(entries, groups=[block])
            self.app.processEvents()

            widget._switch_group_folder("g1")
            self.app.processEvents()
            expansion = widget._inline_group_expansion
            self.assertIsNotNone(expansion)
            assert expansion is not None
            self.assertTrue(expansion.isVisible())

            widget._pending_group_open_id = "g1"
            widget._open_pending_group_folder()
            self.app.processEvents()

            self.assertEqual(widget._open_group_id, "g1")
            self.assertTrue(expansion.isVisible())

    def test_press_activation_keeps_existing_inline_expansion_open(self) -> None:
        from desktop_tidy.ui.item_grid import GroupBlock

        widget = make_item_grid(active_tab_id="tab-images")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = self._entries(root, ["a.png", "b.png"])
            widget.resize(640, 400)
            widget.show()
            block = GroupBlock(
                group_id="g1",
                name="Group",
                members=[entry.path.resolve() for entry in entries],
            )
            widget.set_entries(entries, groups=[block])
            self.app.processEvents()

            widget._switch_group_folder("g1")
            self.app.processEvents()
            expansion = widget._inline_group_expansion
            self.assertIsNotNone(expansion)
            assert expansion is not None
            self.assertTrue(expansion.isVisible())

            widget._activate_folder_on_press("g1")
            self.app.processEvents()

            self.assertEqual(widget._open_group_id, "g1")
            self.assertTrue(expansion.isVisible())

    def test_f2_renames_open_group_without_dialog(self) -> None:
        from desktop_tidy.ui.item_grid import GroupBlock

        widget = make_item_grid(active_tab_id="tab-images")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = self._entries(root, ["a.png", "b.png"])
            widget.resize(640, 400)
            widget.show()
            block = GroupBlock(
                group_id="g1",
                name="Group",
                members=[entry.path.resolve() for entry in entries],
            )
            widget.set_entries(entries, groups=[block])
            self.app.processEvents()

            folder_cell = widget._cells_by_group_id["g1"]
            QTest.mouseClick(
                folder_cell,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                folder_cell.rect().center(),
            )
            self.app.processEvents()
            self.assertEqual(widget._open_group_id, "g1")

            QTest.keyClick(widget, Qt.Key.Key_F2)
            self.app.processEvents()

            editor = widget._folder_rename_editors_by_group_id.get("g1")
            self.assertIsNotNone(editor)
            assert editor is not None
            self.assertTrue(isValid(editor))
            self.assertTrue(editor.isVisible())

    def test_reopening_same_group_reuses_expansion_without_rebuilding_unchanged_grid(
        self,
    ) -> None:
        from desktop_tidy.ui.item_grid import GroupBlock

        widget = make_item_grid(active_tab_id="tab-images")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = self._entries(root, ["a.png", "b.png", "c.png"])
            widget.resize(640, 400)
            widget.show()
            block = GroupBlock(
                group_id="g1",
                name="Group",
                members=[entry.path.resolve() for entry in entries],
            )
            widget.set_entries(entries, groups=[block])
            self.app.processEvents()

            widget._switch_group_folder("g1")
            self.app.processEvents()
            expansion = widget._inline_group_expansion
            self.assertIsNotNone(expansion)
            assert expansion is not None

            widget._close_group_folder()
            self.app.processEvents()

            with patch.object(
                expansion,
                "_rebuild_member_grid",
                wraps=expansion._rebuild_member_grid,
            ) as rebuild:
                widget._switch_group_folder("g1")
                self.app.processEvents()

            self.assertIs(widget._inline_group_expansion, expansion)
            rebuild.assert_not_called()

    def test_escape_closes_inline_group_expansion_immediately(self) -> None:
        from desktop_tidy.ui.item_grid import GroupBlock

        widget = make_item_grid(active_tab_id="tab-images")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = self._entries(root, ["a.png", "b.png"])
            widget.resize(640, 400)
            widget.show()
            block = GroupBlock(
                group_id="g1",
                name="Group",
                members=[entry.path.resolve() for entry in entries],
            )
            widget.set_entries(entries, groups=[block])
            self.app.processEvents()

            widget._switch_group_folder("g1")
            self.app.processEvents()
            expansion = widget._inline_group_expansion
            self.assertIsNotNone(expansion)
            assert expansion is not None
            self.assertTrue(expansion.isVisible())

            QTest.keyClick(widget, Qt.Key.Key_Escape)
            self.app.processEvents()

            self.assertEqual(widget._open_group_id, "")
            self.assertFalse(expansion.isVisible())

    def test_clicking_blank_viewport_closes_inline_group_expansion(self) -> None:
        from desktop_tidy.ui.item_grid import GroupBlock

        widget = make_item_grid(active_tab_id="tab-images")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = self._entries(root, ["a.png", "b.png"])
            widget.resize(640, 400)
            widget.show()
            block = GroupBlock(
                group_id="g1",
                name="Group",
                members=[entry.path.resolve() for entry in entries],
            )
            widget.set_entries(entries, groups=[block])
            self.app.processEvents()

            widget._switch_group_folder("g1")
            self.app.processEvents()
            self.assertEqual(widget._open_group_id, "g1")

            viewport = widget._scroll_area.viewport()
            QTest.mouseClick(
                viewport,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                viewport.rect().bottomRight() - QPoint(8, 8),
            )
            self.app.processEvents()

            self.assertEqual(widget._open_group_id, "")
            expansion = viewport.findChild(QWidget, "inlineGroupExpansion")
            self.assertTrue(expansion is None or not expansion.isVisible())

    def test_blank_click_after_group_click_closes_inline_group_expansion(self) -> None:
        from desktop_tidy.ui.item_grid import GroupBlock

        widget = make_item_grid(active_tab_id="tab-images")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = self._entries(root, ["a.png", "b.png"])
            widget.resize(640, 400)
            widget.show()
            block = GroupBlock(
                group_id="g1",
                name="Group",
                members=[entry.path.resolve() for entry in entries],
            )
            widget.set_entries(entries, groups=[block])
            self.app.processEvents()

            folder_cell = widget._cells_by_group_id["g1"]
            QTest.mouseClick(
                folder_cell,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                folder_cell.rect().center(),
            )
            self.app.processEvents()
            self.assertEqual(widget._open_group_id, "g1")

            viewport = widget._scroll_area.viewport()
            QTest.mouseClick(
                viewport,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                viewport.rect().bottomRight() - QPoint(8, 8),
            )
            self.app.processEvents()

            self.assertEqual(widget._open_group_id, "")
            expansion = viewport.findChild(QWidget, "inlineGroupExpansion")
            self.assertTrue(expansion is None or not expansion.isVisible())

    def test_drop_on_inline_group_expansion_joins_group(self) -> None:
        from desktop_tidy.ui.item_grid import GroupBlock, ITEM_MIME_TYPE

        widget = make_item_grid(active_tab_id="tab-images")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = self._entries(root, ["outside.png", "inside-a.png", "inside-b.png"])
            widget.resize(640, 400)
            widget.show()
            block = GroupBlock(
                group_id="g1",
                name="Group",
                members=[entries[1].path.resolve(), entries[2].path.resolve()],
            )
            widget.set_entries(entries, groups=[block])
            self.app.processEvents()
            widget._switch_group_folder("g1")
            self.app.processEvents()
            expansion = widget._scroll_area.viewport().findChild(
                QWidget,
                "inlineGroupExpansion",
            )
            self.assertIsNotNone(expansion)
            assert expansion is not None

            mime = QMimeData()
            mime.setData(ITEM_MIME_TYPE, str(entries[0].path.resolve()).encode("utf-8"))
            event = QDropEvent(
                QPointF(expansion.rect().center()),
                Qt.DropAction.CopyAction,
                mime,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
            spy = QSignalSpy(widget.group_join_requested)

            expansion.dropEvent(event)

            self.assertEqual(spy.count(), 1)
            group_id, paths = spy.at(0)[0], spy.at(0)[1]
            self.assertEqual(group_id, "g1")
            self.assertEqual([Path(path) for path in paths], [entries[0].path.resolve()])

    def test_group_drag_mime_marks_payload_as_group(self) -> None:
        from desktop_tidy.ui.item_grid import GroupBlock, item_drag_group_id

        widget = make_item_grid(active_tab_id="tab-documents")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = [root / name for name in ("a.txt", "b.txt")]
            for path in paths:
                path.write_text("x", encoding="utf-8")
            block = GroupBlock(
                group_id="g1",
                name="Group",
                members=[path.resolve() for path in paths],
            )
            widget.set_entries([IndexedItem(path) for path in paths], groups=[block])
            widget._drag_from_folder_group_id = "g1"

            drag = widget._build_item_drag(paths[0].resolve())
            mime = drag.mimeData()

            self.assertEqual(item_drag_group_id(mime), "g1")

    def test_dragging_folder_slot_reorders_without_dissolving_group(self) -> None:
        from desktop_tidy.ui.item_grid import GroupBlock

        widget = make_item_grid(active_tab_id="tab-documents")
        with TemporaryDirectory() as tmp:
            paths = [Path(tmp) / name for name in ("a.txt", "b.txt", "c.txt")]
            for path in paths:
                path.write_text("x", encoding="utf-8")
            block = GroupBlock(
                group_id="g1",
                name="组",
                members=[paths[0].resolve(), paths[1].resolve()],
            )
            widget.set_entries(
                [IndexedItem(paths[0]), IndexedItem(paths[1]), IndexedItem(paths[2])],
                groups=[block],
            )
            widget._drag_from_folder_group_id = "g1"
            remove_spy = QSignalSpy(widget.group_remove_requested)
            reorder_spy = QSignalSpy(widget.items_reordered)

            widget._handle_item_drop(
                paths[0],
                QPoint(9999, 9999),
            )

            self.assertEqual(remove_spy.count(), 0)
            self.assertEqual(reorder_spy.count(), 1)

    def test_dragging_folder_cell_starts_group_drag(self) -> None:
        from desktop_tidy.ui.item_grid import GroupBlock

        widget = make_item_grid(active_tab_id="tab-documents")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = [root / name for name in ("a.txt", "b.txt")]
            for path in paths:
                path.write_text("x", encoding="utf-8")
            block = GroupBlock(
                group_id="g1",
                name="组",
                members=[path.resolve() for path in paths],
            )
            widget.set_entries([IndexedItem(path) for path in paths], groups=[block])
            widget.resize(420, 260)
            widget.show()
            process_qt_events()
            folder_cell = widget._cells_by_group_id["g1"]
            calls: list[tuple[Path, str]] = []

            def fake_start(source_path: Path, *, ghost_widget=None) -> None:  # type: ignore[no-untyped-def]
                calls.append((source_path.resolve(), widget._drag_from_folder_group_id))

            widget._start_item_drag = fake_start  # type: ignore[method-assign]
            start = folder_cell.rect().center()
            global_start = folder_cell.mapToGlobal(start)
            move = start + QPoint(QApplication.startDragDistance() + 8, 0)
            global_move = folder_cell.mapToGlobal(move)

            press = QMouseEvent(
                QEvent.Type.MouseButtonPress,
                QPointF(start),
                QPointF(global_start),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
            move_event = QMouseEvent(
                QEvent.Type.MouseMove,
                QPointF(move),
                QPointF(global_move),
                Qt.MouseButton.NoButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )

            widget.eventFilter(folder_cell, press)
            widget.eventFilter(folder_cell, move_event)

            self.assertEqual(calls, [(paths[0].resolve(), "g1")])

    def test_group_popup_update_group_can_switch_twice_without_crash(self) -> None:
        from desktop_tidy.ui.group_folder_popup import GroupFolderPopup

        host = QWidget()
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            group_a = [root / "a.txt", root / "b.txt"]
            group_b = [root / "c.txt", root / "d.txt", root / "e.txt"]
            for path in [*group_a, *group_b]:
                path.write_text("x", encoding="utf-8")
            popup = GroupFolderPopup(
                group_id="g1",
                name="组A",
                members=group_a,
                icon_size=48,
                parent=host,
            )
            popup.update_group(
                group_id="g2",
                name="组B",
                members=group_b,
                icon_size=48,
                accent_color="#8264D2",
                host_width=220,
            )
            popup.update_group(
                group_id="g1",
                name="组A",
                members=group_a,
                icon_size=48,
                accent_color="#8264D2",
                host_width=220,
            )
            self.assertEqual(popup.group_id(), "g1")
            self.assertLessEqual(popup._card.width(), 220)

    def test_group_popup_recovers_after_presented_state_reset(self) -> None:
        from desktop_tidy.ui.group_folder_popup import GroupFolderPopup

        host = QWidget()
        host.resize(480, 640)
        anchor = QWidget(host)
        anchor.setGeometry(120, 420, 96, 110)
        with TemporaryDirectory() as tmp:
            paths = [Path(tmp) / f"{index}.txt" for index in range(3)]
            for path in paths:
                path.write_text("x", encoding="utf-8")
            popup = GroupFolderPopup(
                group_id="g1",
                name="组",
                members=paths,
                icon_size=48,
                parent=host,
            )
            popup._card.setMaximumHeight(56)
            popup.show_expanded_from(anchor, position_host=host, animate=False)
            self.assertGreaterEqual(popup._card.maximumHeight(), 16777200)
            self.assertGreater(popup._card.height(), 80)

    def test_group_popup_is_clamped_inside_short_viewport(self) -> None:
        from desktop_tidy.ui.group_folder_popup import GroupFolderPopup

        host = QWidget()
        host.resize(260, 120)
        anchor = QWidget(host)
        anchor.setGeometry(100, 72, 48, 40)
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = [root / f"item-{index}.txt" for index in range(6)]
            for path in paths:
                path.write_text("x", encoding="utf-8")
            popup = GroupFolderPopup(
                group_id="g1",
                name="短面板",
                members=paths,
                icon_size=48,
                parent=host,
            )
            popup.show_expanded_from(anchor, position_host=host, animate=False)

            self.assertLessEqual(popup.geometry().bottom(), host.rect().bottom() - 8)
            self.assertGreater(popup.height(), 72)

    def test_double_click_folder_cell_does_not_request_group_rename(self) -> None:
        from desktop_tidy.ui.item_grid import GroupBlock

        widget = make_item_grid(active_tab_id="tab-images")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = [IndexedItem(root / f"{name}.png") for name in ["a", "b"]]
            for entry in entries:
                entry.path.write_text("x", encoding="utf-8")
            block = GroupBlock(
                group_id="g1",
                name="游戏",
                members=[entry.path.resolve() for entry in entries],
            )
            widget.set_entries(entries, groups=[block])
            widget.show()
            process_qt_events()
            folder_cell = widget._cells_by_group_id["g1"]
            calls: list[tuple[str, str]] = []
            widget._prompt_rename_group = (  # type: ignore[method-assign]
                lambda group_id, current_name="": calls.append((group_id, current_name))
            )

            QTest.mouseDClick(
                folder_cell,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                folder_cell.rect().center(),
            )
            process_qt_events()

            self.assertEqual(calls, [])
            self.assertEqual(widget._open_group_id, "g1")

    def test_group_context_menu_is_deduplicated_for_context_and_right_release(self) -> None:
        from desktop_tidy.ui.item_grid import GroupBlock

        widget = make_item_grid(active_tab_id="tab-images")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = [IndexedItem(root / f"{name}.png") for name in ["a", "b"]]
            for entry in entries:
                entry.path.write_text("x", encoding="utf-8")
            block = GroupBlock(
                group_id="g1",
                name="游戏",
                members=[entry.path.resolve() for entry in entries],
            )
            widget.set_entries(entries, groups=[block])
            widget.show()
            process_qt_events()
            folder_cell = widget._cells_by_group_id["g1"]
            local = folder_cell.rect().center()
            global_pos = folder_cell.mapToGlobal(local)

            with patch("desktop_tidy.ui.item_grid.QMenu.popup") as popup:
                context_event = QContextMenuEvent(
                    QContextMenuEvent.Reason.Mouse,
                    local,
                    global_pos,
                )
                widget.eventFilter(folder_cell, context_event)
                right_release = QMouseEvent(
                    QEvent.Type.MouseButtonRelease,
                    QPointF(local),
                    QPointF(global_pos),
                    Qt.MouseButton.RightButton,
                    Qt.MouseButton.RightButton,
                    Qt.KeyboardModifier.NoModifier,
                )
                widget.eventFilter(folder_cell, right_release)
                process_qt_events()

            self.assertEqual(popup.call_count, 1)

    def test_left_click_group_after_context_menu_dismisses_menu_and_opens_folder(self) -> None:
        from desktop_tidy.ui.item_grid import GroupBlock

        widget = make_item_grid(active_tab_id="tab-images")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = [IndexedItem(root / f"{name}.png") for name in ["a", "b"]]
            for entry in entries:
                entry.path.write_text("x", encoding="utf-8")
            block = GroupBlock(
                group_id="g1",
                name="游戏",
                members=[entry.path.resolve() for entry in entries],
            )
            widget.set_entries(entries, groups=[block])
            widget.resize(420, 260)
            widget.show()
            process_qt_events()
            folder_cell = widget._cells_by_group_id["g1"]
            local = folder_cell.rect().center()
            global_pos = folder_cell.mapToGlobal(local)

            with patch("desktop_tidy.ui.item_grid.QMenu.popup"):
                context_event = QContextMenuEvent(
                    QContextMenuEvent.Reason.Mouse,
                    local,
                    global_pos,
                )
                widget.eventFilter(folder_cell, context_event)
            self.assertIsNotNone(widget._context_menu)

            QTest.mouseClick(
                folder_cell,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                local,
            )
            process_qt_events()

            self.assertIsNone(widget._context_menu)
            self.assertEqual(widget._open_group_id, "g1")

    def test_left_click_open_group_keeps_inline_expansion_open(self) -> None:
        from desktop_tidy.ui.item_grid import GroupBlock

        widget = make_item_grid(active_tab_id="tab-images")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = [IndexedItem(root / f"{name}.png") for name in ["a", "b"]]
            for entry in entries:
                entry.path.write_text("x", encoding="utf-8")
            block = GroupBlock(
                group_id="g1",
                name="Group",
                members=[entry.path.resolve() for entry in entries],
            )
            widget.set_entries(entries, groups=[block])
            widget.resize(420, 260)
            widget.show()
            process_qt_events()
            folder_cell = widget._cells_by_group_id["g1"]
            local = folder_cell.rect().center()

            widget._switch_group_folder("g1")
            process_qt_events()
            expansion = widget._inline_group_expansion
            self.assertIsNotNone(expansion)
            assert expansion is not None
            self.assertTrue(expansion.isVisible())

            QTest.mouseClick(
                folder_cell,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                local,
            )
            process_qt_events()

            self.assertEqual(widget._open_group_id, "g1")
            self.assertTrue(expansion.isVisible())

    def test_group_rename_uses_inline_editor_without_dialog(self) -> None:
        from desktop_tidy.ui.item_grid import GroupBlock

        widget = make_item_grid(active_tab_id="tab-images")
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            entries = [IndexedItem(root / f"{name}.png") for name in ["a", "b"]]
            for entry in entries:
                entry.path.write_text("x", encoding="utf-8")
            block = GroupBlock(
                group_id="g1",
                name="旧名字",
                members=[entry.path.resolve() for entry in entries],
            )
            widget.set_entries(entries, groups=[block])
            widget.show()
            process_qt_events()
            spy = QSignalSpy(widget.group_rename_requested)

            widget._prompt_rename_group("g1", "旧名字")

            editor = widget._cells_by_group_id["g1"].findChild(QLineEdit)
            self.assertIsNotNone(editor)
            assert editor is not None
            self.assertTrue(editor.isVisible())
            self.assertEqual(editor.text(), "旧名字")

            editor.setText("新名字")
            editor.editingFinished.emit()
            process_qt_events()

            self.assertEqual(spy.count(), 1)
            self.assertEqual(spy.at(0), ["g1", "新名字"])

    def test_drag_debug_uses_application_log_without_writing_cwd_file(self) -> None:
        from desktop_tidy.services.logging_setup import configure_logging, get_logger
        from desktop_tidy.ui import item_grid

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_path = configure_logging(root / "DesktopCleaner")
            work_dir = root / "work"
            work_dir.mkdir()
            previous_cwd = Path.cwd()
            previous_debug = item_grid._DRAG_DEBUG
            try:
                os.chdir(work_dir)
                item_grid._DRAG_DEBUG = True
                item_grid._drag_dbg("group-create", "count=2", "tab=tab-images")
                for handler in get_logger().handlers:
                    handler.flush()
            finally:
                item_grid._DRAG_DEBUG = previous_debug
                os.chdir(previous_cwd)
                close_desktop_logger_handlers()

            self.assertFalse((work_dir / "drag_debug.log").exists())
            self.assertIn(
                "[drag] group-create count=2 tab=tab-images",
                log_path.read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
