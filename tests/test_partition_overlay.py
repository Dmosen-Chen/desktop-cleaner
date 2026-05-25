from __future__ import annotations

import unittest
import inspect

from pathlib import Path

from partition_overlay import DEFAULT_PANEL_ALPHA, DEFAULT_PANEL_COLOR, PartitionOverlay, make_item_from_path, normalize_extensions, normalize_items, normalize_partition_list


class PartitionOverlayTests(unittest.TestCase):
    def test_normalize_partition_list_adds_editable_fields(self) -> None:
        parts = normalize_partition_list([{"name": "发票", "rx": -1, "rw": 2}])

        self.assertEqual(len(parts), 1)
        self.assertTrue(parts[0]["id"])
        self.assertEqual(parts[0]["name"], "发票")
        self.assertEqual(parts[0]["folder"], "发票")
        self.assertEqual(parts[0]["rx"], 0.0)
        self.assertEqual(parts[0]["rw"], 1.0)
        self.assertFalse(parts[0]["locked"])
        self.assertFalse(parts[0]["hidden"])
        self.assertEqual(parts[0]["color"], DEFAULT_PANEL_COLOR)
        self.assertEqual(parts[0]["alpha"], DEFAULT_PANEL_ALPHA)
        self.assertFalse(parts[0]["collapsed"])
        self.assertEqual(parts[0]["group_id"], "")
        self.assertEqual(parts[0]["match_exts"], [])

    def test_normalize_partition_list_preserves_custom_folder(self) -> None:
        parts = normalize_partition_list([{"name": "临时", "folder": "收件箱"}])

        self.assertEqual(parts[0]["name"], "临时")
        self.assertEqual(parts[0]["folder"], "收件箱")

    def test_normalize_items_deduplicates_paths(self) -> None:
        items = normalize_items(
            [
                {"name": "Code", "path": r"C:\Apps\Code.lnk"},
                {"name": "Code Again", "path": r"C:\Apps\Code.lnk"},
                {"path": ""},
            ]
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["name"], "Code")

    def test_make_item_from_path_keeps_source_path_reference(self) -> None:
        item = make_item_from_path(Path(r"C:\Users\me\Desktop\App.lnk"))

        self.assertEqual(item["name"], "App")
        self.assertEqual(item["kind"], "shortcut")
        self.assertEqual(item["path"], r"C:\Users\me\Desktop\App.lnk")

    def test_make_item_from_path_treats_url_as_shortcut(self) -> None:
        item = make_item_from_path(Path(r"C:\Users\me\Desktop\App.url"))

        self.assertEqual(item["name"], "App")
        self.assertEqual(item["kind"], "shortcut")

    def test_normalize_extensions_accepts_space_and_comma_input(self) -> None:
        self.assertEqual(normalize_extensions(".png jpg, .jpeg;PNG"), [".png", ".jpg", ".jpeg"])

    def test_render_items_does_not_hook_child_widgets_for_drop(self) -> None:
        source = inspect.getsource(PartitionOverlay._render_items)

        self.assertNotIn("self._hook_drop(grid, workspace_id)", source)
        self.assertNotIn("self._hook_drop(empty, workspace_id)", source)
        self.assertNotIn("self._hook_drop(cell, workspace_id)", source)
        self.assertNotIn("self._hook_drop(widget, workspace_id)", source)

    def test_show_only_uses_toplevel_drop_hook(self) -> None:
        source = inspect.getsource(PartitionOverlay.show)

        self.assertIn("self._hook_drop(tl, workspace_id)", source)
        self.assertNotIn("self._hook_drop(border, workspace_id)", source)
        self.assertNotIn("self._hook_drop(inner, workspace_id)", source)

    def test_drop_handler_catches_callback_errors(self) -> None:
        class FakeRoot:
            def after(self, _delay, func):
                func()

        overlay = PartitionOverlay(FakeRoot(), [], on_drop=lambda _workspace_id, _paths: (_ for _ in ()).throw(RuntimeError("boom")))
        handler = overlay._make_drop_handler("a")

        handler([b"C:\\Temp\\file.txt"])

        self.assertTrue(overlay._drop_errors)

    def test_overlay_does_not_use_native_hwnd_subclassing(self) -> None:
        source = inspect.getsource(PartitionOverlay)

        self.assertNotIn("SetWindowLong", source)
        self.assertNotIn("DragAcceptFiles", source)
        self.assertNotIn("_hook_drop_native", source)


if __name__ == "__main__":
    unittest.main()
