from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QPoint

from desktop_tidy.services.shell_context_menu import ShellContextMenuService


class _Owner:
    def winId(self) -> int:
        return 123


class ShellContextMenuServiceTests(unittest.TestCase):
    def test_windows_menu_uses_shell_desktop_folder_and_unwraps_pywin32_result(self) -> None:
        calls: dict[str, object] = {}

        pythoncom = types.ModuleType("pythoncom")
        pythoncom.CoInitialize = lambda: calls.setdefault("coinit", True)
        pythoncom.CoUninitialize = lambda: calls.setdefault("couninit", True)

        win32con = types.ModuleType("win32con")
        win32con.TPM_LEFTALIGN = 0x0000
        win32con.TPM_RETURNCMD = 0x0100
        win32con.TPM_RIGHTBUTTON = 0x0002
        win32con.WM_NULL = 0
        win32con.WS_EX_TOOLWINDOW = 0x00000080
        win32con.WS_EX_TOPMOST = 0x00000008
        win32con.WS_POPUP = 0x80000000

        win32gui = types.ModuleType("win32gui")
        win32gui.CreatePopupMenu = lambda: 77
        win32gui.DestroyMenu = lambda menu: calls.setdefault("destroy_menu", menu)
        win32gui.DestroyWindow = lambda hwnd: calls.setdefault("destroy_window", hwnd)
        win32gui.GetMenuItemCount = lambda menu: 3
        win32gui.SetForegroundWindow = lambda hwnd: calls.setdefault("foreground", hwnd)
        win32gui.PostMessage = lambda hwnd, msg, wparam, lparam: calls.setdefault(
            "post_message",
            (hwnd, msg, wparam, lparam),
        )

        def create_window_ex(ex_style, class_name, title, style, x, y, width, height, parent, menu, instance, param):
            calls["helper_style"] = ex_style
            calls["helper_parent"] = parent
            return 4242

        def track_popup_menu(menu, flags, x, y, reserved, hwnd, rect):
            calls["track_hwnd"] = hwnd
            calls["track_pos"] = (x, y)
            return 0

        win32gui.CreateWindowEx = create_window_ex
        win32gui.TrackPopupMenu = track_popup_menu

        shellcon = types.ModuleType("shellcon")
        shellcon.CMF_NORMAL = 0

        class _ContextMenu:
            def QueryContextMenu(self, menu, index, first, last, flags):
                calls["query"] = (menu, index, first, last, flags)

            def InvokeCommand(self, info):
                calls["invoke"] = info

        class _ParentFolder:
            def ParseDisplayName(self, hwnd, bindctx, display_name):
                calls["child_name"] = display_name
                return -1, "child-pidl", 0

            def GetUIObjectOf(self, hwnd, children, iid, reserved):
                calls["get_ui_hwnd"] = hwnd
                calls["children"] = children
                return 0, _ContextMenu()

        class _DesktopFolder:
            def ParseDisplayName(self, hwnd, bindctx, display_name):
                calls["parent_name"] = display_name
                return 0, "parent-pidl", 0

            def BindToObject(self, pidl, bindctx, iid):
                calls["bind_pidl"] = pidl
                return _ParentFolder()

        shell = types.ModuleType("shell")
        shell.IID_IShellFolder = "IID_IShellFolder"
        shell.IID_IContextMenu = "IID_IContextMenu"
        shell.SHParseDisplayName = lambda path, bindctx: ("pidl", 0)
        shell.SHGetDesktopFolder = lambda: _DesktopFolder()

        win32com = types.ModuleType("win32com")
        win32com_shell_pkg = types.ModuleType("win32com.shell")
        win32com_shell_pkg.shell = shell
        win32com_shell_pkg.shellcon = shellcon

        modules = {
            "pythoncom": pythoncom,
            "win32con": win32con,
            "win32gui": win32gui,
            "win32com": win32com,
            "win32com.shell": win32com_shell_pkg,
            "win32com.shell.shell": shell,
            "win32com.shell.shellcon": shellcon,
        }

        with patch.object(sys, "platform", "win32"), patch.dict(sys.modules, modules):
            shown = ShellContextMenuService().show(
                _Owner(),  # type: ignore[arg-type]
                Path("C:/Desktop/report.pdf"),
                QPoint(10, 20),
            )

        self.assertTrue(shown)
        self.assertEqual(calls["track_hwnd"], 4242)
        self.assertEqual(calls["foreground"], 4242)
        self.assertEqual(calls["destroy_window"], 4242)
        self.assertEqual(calls["track_pos"], (10, 20))
        self.assertEqual(calls["helper_style"], win32con.WS_EX_TOOLWINDOW | win32con.WS_EX_TOPMOST)
        self.assertEqual(calls["bind_pidl"], "parent-pidl")
        self.assertEqual(calls["children"], ["child-pidl"])
