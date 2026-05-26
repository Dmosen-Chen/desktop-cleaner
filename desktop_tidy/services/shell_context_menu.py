"""Optional Windows Shell context menu bridge for preview item cells."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QWidget


class ShellContextMenuService:
    """Show the native Windows context menu when pywin32 is available."""

    def show(self, owner: QWidget, path: Path, global_pos: QPoint) -> bool:
        if sys.platform != "win32":
            return False
        try:
            import pythoncom
            import win32con
            import win32gui
            from win32com.shell import shell, shellcon
        except ImportError:
            return False

        hwnd = int(owner.winId()) if owner is not None else 0
        popup_hwnd = 0
        menu = None
        com_initialized = False
        try:
            pythoncom.CoInitialize()
            com_initialized = True
            context_menu = _context_menu_for_path(shell, hwnd, Path(path).resolve())
            menu = win32gui.CreatePopupMenu()
            context_menu.QueryContextMenu(
                menu,
                0,
                1,
                0x7FFF,
                shellcon.CMF_NORMAL,
            )
            if _menu_item_count(win32gui, menu) <= 0:
                return False
            popup_hwnd = _create_popup_owner(win32con, win32gui, global_pos)
            menu_owner = popup_hwnd or hwnd
            if menu_owner:
                try:
                    win32gui.SetForegroundWindow(menu_owner)
                except Exception:
                    pass
            command = win32gui.TrackPopupMenu(
                menu,
                win32con.TPM_LEFTALIGN
                | win32con.TPM_RETURNCMD
                | win32con.TPM_RIGHTBUTTON,
                int(global_pos.x()),
                int(global_pos.y()),
                0,
                menu_owner,
                None,
            )
            if command:
                context_menu.InvokeCommand(
                    (
                        0,
                        hwnd,
                        None,
                        command - 1,
                        None,
                        None,
                        0,
                        0,
                        None,
                    )
                )
            if hwnd:
                try:
                    win32gui.PostMessage(menu_owner, win32con.WM_NULL, 0, 0)
                except Exception:
                    pass
            return True
        except Exception:
            return False
        finally:
            if menu is not None:
                try:
                    win32gui.DestroyMenu(menu)
                except Exception:
                    pass
            if popup_hwnd:
                try:
                    win32gui.DestroyWindow(popup_hwnd)
                except Exception:
                    pass
            if com_initialized:
                pythoncom.CoUninitialize()


def _context_menu_for_path(shell, hwnd: int, path: Path):  # type: ignore[no-untyped-def]
    desktop = shell.SHGetDesktopFolder()
    try:
        _eaten, parent_pidl, _attrs = desktop.ParseDisplayName(hwnd, None, str(path.parent))
        parent_folder = desktop.BindToObject(parent_pidl, None, shell.IID_IShellFolder)
        _eaten, child_pidl, _attrs = parent_folder.ParseDisplayName(hwnd, None, path.name)
        return _unwrap_context_menu(
            _get_ui_object_of(parent_folder, hwnd, [child_pidl], shell.IID_IContextMenu)
        )
    except Exception:
        pidl, _flags = shell.SHParseDisplayName(str(path), 0)
        return _unwrap_context_menu(
            _get_ui_object_of(desktop, hwnd, [pidl], shell.IID_IContextMenu)
        )


def _get_ui_object_of(folder, hwnd: int, children: list[Any], iid):  # type: ignore[no-untyped-def]
    try:
        return folder.GetUIObjectOf(hwnd, children, iid, 0)
    except TypeError:
        return folder.GetUIObjectOf(hwnd, children, iid)


def _unwrap_context_menu(result):  # type: ignore[no-untyped-def]
    if hasattr(result, "QueryContextMenu"):
        return result
    if isinstance(result, tuple):
        for value in result:
            if hasattr(value, "QueryContextMenu"):
                return value
    raise TypeError("GetUIObjectOf did not return an IContextMenu object")


def _menu_item_count(win32gui, menu) -> int:  # type: ignore[no-untyped-def]
    try:
        return int(win32gui.GetMenuItemCount(menu))
    except Exception:
        return 1


def _create_popup_owner(win32con, win32gui, global_pos: QPoint) -> int:  # type: ignore[no-untyped-def]
    try:
        return int(
            win32gui.CreateWindowEx(
                win32con.WS_EX_TOOLWINDOW | win32con.WS_EX_TOPMOST,
                "STATIC",
                "DesktopTidyContextMenu",
                win32con.WS_POPUP,
                int(global_pos.x()),
                int(global_pos.y()),
                1,
                1,
                0,
                0,
                0,
                None,
            )
        )
    except Exception:
        return 0
