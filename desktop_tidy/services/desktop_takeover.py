"""Windows desktop-layer takeover helpers.

The service is deliberately defensive: unsupported platforms and failed Win32
lookups return False instead of raising, so the Qt app can fall back to its
ordinary window mode.
"""

from __future__ import annotations

import ctypes
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from desktop_tidy.domain.models import Configuration

WM_SPAWN_WORKERW = 0x052C
SMTO_NORMAL = 0x0000
SW_HIDE = 0
SW_SHOW = 5
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
HWND_TOP = 0
HWND_BOTTOM = 1
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79
_CALLBACK_FACTORY = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


@dataclass(frozen=True)
class TakeoverResult:
    success: bool
    message: str = ""


class TakeoverSessionMarker:
    """进程被强杀时 config 可能来不及落盘,用独立 marker 触发下次启动恢复。"""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def mark_active(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text("active\n", encoding="utf-8")

    def clear(self) -> None:
        if self._path.is_file():
            self._path.unlink()

    def is_active(self) -> bool:
        return self._path.is_file()


def recover_abandoned_takeover(
    takeover: _TakeoverLike,
    marker: TakeoverSessionMarker,
) -> bool:
    if not marker.is_active():
        return False
    restored = takeover.restore_explorer_icons()
    detach = getattr(takeover, "detach_panels", None)
    if detach is not None:
        detach()
    marker.clear()
    return restored


_abnormal_exit_handler_ref: list[object] = []


def install_abnormal_exit_handler(callback: Callable[[], None]) -> None:
    """尽力在控制台/关机信号时恢复桌面(任务管理器强杀不一定触发)。"""
    if sys.platform != "win32":
        return

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_uint32)
    def handler(ctrl_type: int) -> bool:
        if ctrl_type in (0, 2, 5, 6):
            try:
                callback()
            except Exception:
                pass
        return False

    _abnormal_exit_handler_ref.clear()
    _abnormal_exit_handler_ref.append(handler)
    ctypes.windll.kernel32.SetConsoleCtrlHandler(handler, True)


class _TakeoverLike(Protocol):
    def restore_explorer_icons(self) -> bool: ...


class DesktopRecoveryGuard:
    """Restore Explorer desktop icons if the previous run left them hidden."""

    def __init__(self, takeover: _TakeoverLike) -> None:
        self._takeover = takeover

    def recover_if_needed(self, config: Configuration) -> bool:
        if not (
            config.desktop.restore_required
            or config.desktop.explorer_icons_hidden
        ):
            return False
        restored = self._takeover.restore_explorer_icons()
        detach = getattr(self._takeover, "detach_panels", None)
        if detach is not None:
            detach()
        if restored:
            config.desktop.restore_required = False
            config.desktop.explorer_icons_hidden = False
        else:
            config.desktop.restore_required = True
        return True


class DesktopTakeoverService:
    """Coordinate safe Windows desktop takeover behavior.

    Qt top-level windows are kept as bottom windows instead of being reparented
    into Progman/WorkerW. Reparenting is fragile on multi-monitor, high-DPI
    desktops and can leave visible HWNDs covered by Explorer's desktop layer.
    """

    def __init__(
        self,
        *,
        platform_name: str | None = None,
        user32: object | None = None,
    ) -> None:
        self._platform = platform_name or sys.platform
        self._user32 = user32
        self._attached_hwnds: list[int] = []
        self._attached_original_rects: dict[int, tuple[int, int, int, int]] = {}

    def attach_panels(self, panel_hwnds: list[int]) -> TakeoverResult:
        api = self._api()
        if api is None:
            return TakeoverResult(False, "unsupported-platform")
        attached: list[int] = []
        originals: dict[int, tuple[int, int, int, int]] = {}
        for hwnd in panel_hwnds:
            if not hwnd:
                continue
            panel_hwnd = int(hwnd)
            original = self._window_rect(api, panel_hwnd)
            if original is not None:
                originals[panel_hwnd] = original
            if original is not None:
                self._set_bottom_rect(api, panel_hwnd, original)
            attached.append(panel_hwnd)
        if not attached and panel_hwnds:
            return TakeoverResult(False, "no-valid-panel-handles")
        if not self._attached_panels_intersect_virtual_screen(api, attached):
            self._restore_panel_windows(api, attached, originals)
            return TakeoverResult(False, "attached-panel-offscreen")
        self._attached_hwnds = attached
        self._attached_original_rects = originals
        return TakeoverResult(True, "")

    def hide_explorer_icons(self) -> bool:
        return self._set_explorer_icons_visible(False)

    def restore_explorer_icons(self) -> bool:
        return self._set_explorer_icons_visible(True)

    def detach_panels(self) -> None:
        api = self._api()
        if api is None:
            self._attached_hwnds = []
            self._attached_original_rects = {}
            return
        self._restore_panel_windows(
            api,
            list(self._attached_hwnds),
            dict(self._attached_original_rects),
        )
        self._attached_hwnds = []
        self._attached_original_rects = {}

    def _api(self):
        if self._platform != "win32":
            return None
        if self._user32 is not None:
            return self._user32
        return self._real_user32()

    @staticmethod
    def _real_user32():
        api = ctypes.WinDLL("user32", use_last_error=True)  # type: ignore[attr-defined]
        api.FindWindowW.restype = ctypes.c_void_p
        api.FindWindowExW.restype = ctypes.c_void_p
        api.SetParent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        api.SetParent.restype = ctypes.c_void_p
        api.SetWindowPos.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint,
        ]
        api.SetWindowPos.restype = ctypes.c_bool
        api.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(_RECT)]
        api.GetWindowRect.restype = ctypes.c_bool
        api.GetSystemMetrics.argtypes = [ctypes.c_int]
        api.GetSystemMetrics.restype = ctypes.c_int
        api.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
        api.ShowWindow.restype = ctypes.c_bool
        api.IsWindowVisible.argtypes = [ctypes.c_void_p]
        api.IsWindowVisible.restype = ctypes.c_bool
        return api

    def _set_explorer_icons_visible(self, visible: bool) -> bool:
        api = self._api()
        if api is None:
            return False
        list_view = self._desktop_list_view(api)
        if not list_view:
            return False
        api.ShowWindow(list_view, SW_SHOW if visible else SW_HIDE)
        # ShowWindow 的返回值是窗口之前的可见状态,不能用来判断是否成功。
        # 改为复核 ListView 的实际可见性,避免恢复其实失败却误报成功、
        # 进而清掉恢复标志导致桌面图标长期隐藏。
        actual = self.explorer_icons_visible()
        if actual is None:
            return True
        return actual == visible

    def explorer_icons_visible(self) -> bool | None:
        api = self._api()
        if api is None:
            return None
        list_view = self._desktop_list_view(api)
        if not list_view:
            return None
        try:
            return bool(api.IsWindowVisible(list_view))
        except AttributeError:
            return None

    def _window_rect(self, api, hwnd: int) -> tuple[int, int, int, int] | None:
        try:
            rect = _RECT()
            if not api.GetWindowRect(hwnd, ctypes.pointer(rect)):
                return None
            return (
                int(rect.left),
                int(rect.top),
                int(rect.right),
                int(rect.bottom),
            )
        except AttributeError:
            return None

    def _set_child_rect(
        self,
        api,
        hwnd: int,
        parent_hwnd: int,
        rect: tuple[int, int, int, int],
    ) -> None:
        parent_rect = self._window_rect(api, parent_hwnd) or (0, 0, 0, 0)
        left, top, right, bottom = rect
        parent_left, parent_top, _parent_right, _parent_bottom = parent_rect
        api.SetWindowPos(
            hwnd,
            HWND_TOP,
            left - parent_left,
            top - parent_top,
            max(1, right - left),
            max(1, bottom - top),
            SWP_NOACTIVATE | SWP_SHOWWINDOW,
        )

    def _set_bottom_rect(
        self,
        api,
        hwnd: int,
        rect: tuple[int, int, int, int],
    ) -> None:
        left, top, right, bottom = rect
        # 保持 Qt 已经给面板设置好的 WindowStaysOnBottom 层级(壁纸之上、其它窗口之下),
        # 不要用原始 HWND_BOTTOM 把它压到壁纸 WorkerW 下面——那样面板会收不到鼠标,
        # 表现为"拖不动 / 点不动"。这里只校正位置,用 SWP_NOZORDER 保留 z 序。
        api.SetWindowPos(
            hwnd,
            0,
            left,
            top,
            max(1, right - left),
            max(1, bottom - top),
            SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW,
        )

    def _restore_panel_windows(
        self,
        api,
        hwnds: list[int],
        originals: dict[int, tuple[int, int, int, int]],
    ) -> None:
        for hwnd in hwnds:
            if not hwnd:
                continue
            api.SetParent(int(hwnd), 0)
            original = originals.get(int(hwnd))
            if original is None:
                continue
            left, top, right, bottom = original
            try:
                api.SetWindowPos(
                    int(hwnd),
                    0,
                    left,
                    top,
                    max(1, right - left),
                    max(1, bottom - top),
                    SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW,
                )
            except AttributeError:
                pass

    def _attached_panels_intersect_virtual_screen(self, api, hwnds: list[int]) -> bool:
        virtual_screen = self._virtual_screen_rect(api)
        if virtual_screen is None:
            return True
        for hwnd in hwnds:
            rect = self._window_rect(api, int(hwnd))
            if rect is None:
                return False
            if not self._rects_intersect(rect, virtual_screen):
                return False
        return True

    def _virtual_screen_rect(self, api) -> tuple[int, int, int, int] | None:
        try:
            left = int(api.GetSystemMetrics(SM_XVIRTUALSCREEN))
            top = int(api.GetSystemMetrics(SM_YVIRTUALSCREEN))
            width = int(api.GetSystemMetrics(SM_CXVIRTUALSCREEN))
            height = int(api.GetSystemMetrics(SM_CYVIRTUALSCREEN))
        except (AttributeError, KeyError):
            return None
        if width <= 0 or height <= 0:
            return None
        return (left, top, left + width, top + height)

    @staticmethod
    def _rects_intersect(
        first: tuple[int, int, int, int],
        second: tuple[int, int, int, int],
    ) -> bool:
        left = max(first[0], second[0])
        top = max(first[1], second[1])
        right = min(first[2], second[2])
        bottom = min(first[3], second[3])
        return right > left and bottom > top

    def _desktop_parent_window(self, api) -> int:
        progman = self._window_handle(api.FindWindowW("Progman", None))
        if progman:
            result = ctypes.c_ulong()
            try:
                api.SendMessageTimeoutW(
                    progman,
                    WM_SPAWN_WORKERW,
                    0,
                    0,
                    SMTO_NORMAL,
                    1000,
                    ctypes.byref(result),
                )
            except AttributeError:
                pass
        return self._find_workerw(api) or progman

    def _find_workerw(self, api) -> int:
        found = {"hwnd": 0}

        def callback(hwnd, _lparam):
            view = api.FindWindowExW(hwnd, 0, "SHELLDLL_DefView", None)
            if view:
                worker = api.FindWindowExW(0, hwnd, "WorkerW", None)
                if worker:
                    found["hwnd"] = int(worker)
                    return False
            return True

        enum_proc = _CALLBACK_FACTORY(
            ctypes.c_bool,
            ctypes.c_void_p,
            ctypes.c_void_p,
        )(callback)
        api.EnumWindows(enum_proc, 0)
        return found["hwnd"]

    def _desktop_list_view(self, api) -> int:
        found = {"hwnd": 0}

        def check_root(hwnd: int) -> bool:
            view = self._window_handle(api.FindWindowExW(hwnd, 0, "SHELLDLL_DefView", None))
            if not view:
                return False
            list_view = self._window_handle(
                api.FindWindowExW(view, 0, "SysListView32", "FolderView")
            )
            if list_view:
                found["hwnd"] = list_view
                return True
            return False

        progman = self._window_handle(api.FindWindowW("Progman", None))
        if progman and check_root(progman):
            return found["hwnd"]

        def callback(hwnd, _lparam):
            return not check_root(int(hwnd))

        enum_proc = _CALLBACK_FACTORY(
            ctypes.c_bool,
            ctypes.c_void_p,
            ctypes.c_void_p,
        )(callback)
        api.EnumWindows(enum_proc, 0)
        return found["hwnd"]

    @staticmethod
    def _window_handle(value) -> int:
        return int(value or 0)
