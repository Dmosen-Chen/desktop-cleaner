"""Small Windows window-style helpers for desktop-like Qt panels."""

from __future__ import annotations

import ctypes
import sys
from typing import Protocol

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_FRAMECHANGED = 0x0020


class _User32Like(Protocol):
    def GetWindowLongPtrW(self, hwnd: int, index: int) -> int: ...

    def SetWindowLongPtrW(self, hwnd: int, index: int, value: int) -> int: ...

    def SetWindowPos(
        self,
        hwnd: int,
        insert_after: int,
        x: int,
        y: int,
        cx: int,
        cy: int,
        flags: int,
    ) -> int: ...


def hide_window_from_taskbar(
    hwnd: int,
    *,
    user32: _User32Like | None = None,
) -> bool:
    """Hide a native Windows window from the taskbar without changing Qt ownership."""

    if not hwnd or (user32 is None and sys.platform != "win32"):
        return False
    api = user32 or ctypes.windll.user32  # type: ignore[attr-defined]
    style = int(api.GetWindowLongPtrW(hwnd, GWL_EXSTYLE))
    updated = (style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
    if updated == style:
        return True
    api.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, updated)
    api.SetWindowPos(
        hwnd,
        0,
        0,
        0,
        0,
        0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED,
    )
    return True
