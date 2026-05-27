"""Windows desktop-layer takeover helpers.

The service is deliberately defensive: unsupported platforms and failed Win32
lookups return False instead of raising, so the Qt app can fall back to its
ordinary window mode.
"""

from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass
from typing import Protocol

from desktop_tidy.domain.models import Configuration

WM_SPAWN_WORKERW = 0x052C
SMTO_NORMAL = 0x0000
SW_HIDE = 0
SW_SHOW = 5
_CALLBACK_FACTORY = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)


@dataclass(frozen=True)
class TakeoverResult:
    success: bool
    message: str = ""


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
        if restored:
            config.desktop.restore_required = False
            config.desktop.explorer_icons_hidden = False
        else:
            config.desktop.restore_required = True
        return True


class DesktopTakeoverService:
    """Attach Qt panel windows to the Windows desktop layer and hide icons."""

    def __init__(
        self,
        *,
        platform_name: str | None = None,
        user32: object | None = None,
    ) -> None:
        self._platform = platform_name or sys.platform
        self._user32 = user32
        self._attached_hwnds: list[int] = []

    def attach_panels(self, panel_hwnds: list[int]) -> TakeoverResult:
        api = self._api()
        if api is None:
            return TakeoverResult(False, "unsupported-platform")
        workerw = self._desktop_parent_window(api)
        if not workerw:
            return TakeoverResult(False, "desktop-layer-unavailable")
        attached: list[int] = []
        for hwnd in panel_hwnds:
            if not hwnd:
                continue
            api.SetParent(int(hwnd), workerw)
            attached.append(int(hwnd))
        if not attached and panel_hwnds:
            return TakeoverResult(False, "no-valid-panel-handles")
        self._attached_hwnds = attached
        return TakeoverResult(True, "")

    def hide_explorer_icons(self) -> bool:
        return self._set_explorer_icons_visible(False)

    def restore_explorer_icons(self) -> bool:
        return self._set_explorer_icons_visible(True)

    def detach_panels(self) -> None:
        api = self._api()
        if api is None:
            self._attached_hwnds = []
            return
        for hwnd in list(self._attached_hwnds):
            if hwnd:
                api.SetParent(int(hwnd), 0)
        self._attached_hwnds = []

    def _api(self):
        if self._platform != "win32":
            return None
        if self._user32 is not None:
            return self._user32
        return ctypes.windll.user32  # type: ignore[attr-defined]

    def _set_explorer_icons_visible(self, visible: bool) -> bool:
        api = self._api()
        if api is None:
            return False
        list_view = self._desktop_list_view(api)
        if not list_view:
            return False
        api.ShowWindow(list_view, SW_SHOW if visible else SW_HIDE)
        return True

    def _desktop_parent_window(self, api) -> int:
        progman = int(api.FindWindowW("Progman", None))
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
            view = int(api.FindWindowExW(hwnd, 0, "SHELLDLL_DefView", None))
            if not view:
                return False
            list_view = int(api.FindWindowExW(view, 0, "SysListView32", "FolderView"))
            if list_view:
                found["hwnd"] = list_view
                return True
            return False

        progman = int(api.FindWindowW("Progman", None))
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
