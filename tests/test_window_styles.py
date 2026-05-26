from __future__ import annotations

import unittest

from desktop_tidy.services.window_styles import (
    GWL_EXSTYLE,
    SWP_FRAMECHANGED,
    SWP_NOMOVE,
    SWP_NOSIZE,
    SWP_NOZORDER,
    WS_EX_APPWINDOW,
    WS_EX_TOOLWINDOW,
    hide_window_from_taskbar,
)


class FakeUser32:
    def __init__(self, initial_style: int) -> None:
        self.initial_style = initial_style
        self.updated_style: int | None = None
        self.set_window_pos_flags: int | None = None

    def GetWindowLongPtrW(self, hwnd: int, index: int) -> int:
        self.hwnd = hwnd
        self.index = index
        return self.initial_style

    def SetWindowLongPtrW(self, hwnd: int, index: int, style: int) -> int:
        self.hwnd = hwnd
        self.index = index
        self.updated_style = style
        return self.initial_style

    def SetWindowPos(
        self,
        hwnd: int,
        insert_after: int,
        x: int,
        y: int,
        cx: int,
        cy: int,
        flags: int,
    ) -> int:
        self.hwnd = hwnd
        self.set_window_pos_flags = flags
        return 1


class WindowStyleTests(unittest.TestCase):
    def test_hide_window_from_taskbar_sets_toolwindow_and_removes_appwindow(self) -> None:
        user32 = FakeUser32(WS_EX_APPWINDOW | 0x40)

        changed = hide_window_from_taskbar(1234, user32=user32)

        self.assertTrue(changed)
        self.assertEqual(user32.index, GWL_EXSTYLE)
        self.assertIsNotNone(user32.updated_style)
        assert user32.updated_style is not None
        self.assertFalse(bool(user32.updated_style & WS_EX_APPWINDOW))
        self.assertTrue(bool(user32.updated_style & WS_EX_TOOLWINDOW))
        self.assertEqual(
            user32.set_window_pos_flags,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED,
        )

    def test_hide_window_from_taskbar_ignores_empty_handle(self) -> None:
        user32 = FakeUser32(WS_EX_APPWINDOW)

        self.assertFalse(hide_window_from_taskbar(0, user32=user32))
        self.assertIsNone(user32.updated_style)


if __name__ == "__main__":
    unittest.main()
