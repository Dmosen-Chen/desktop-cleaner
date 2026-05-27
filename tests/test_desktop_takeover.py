from __future__ import annotations

import unittest

from desktop_tidy.domain.defaults import build_default_configuration
from desktop_tidy.services.desktop_takeover import (
    DesktopRecoveryGuard,
    DesktopTakeoverService,
    TakeoverResult,
)


class FakeTakeover:
    def __init__(self, *, restore_result: bool = True) -> None:
        self.restore_result = restore_result
        self.calls: list[str] = []

    def restore_explorer_icons(self) -> bool:
        self.calls.append("restore")
        return self.restore_result


class DesktopRecoveryGuardTests(unittest.TestCase):
    def test_recover_if_needed_restores_icons_and_clears_persistent_flags(self) -> None:
        config = build_default_configuration(r"D:\Desktop")
        config.desktop.restore_required = True
        config.desktop.explorer_icons_hidden = True
        service = FakeTakeover(restore_result=True)

        changed = DesktopRecoveryGuard(service).recover_if_needed(config)

        self.assertTrue(changed)
        self.assertEqual(service.calls, ["restore"])
        self.assertFalse(config.desktop.restore_required)
        self.assertFalse(config.desktop.explorer_icons_hidden)

    def test_failed_recovery_keeps_restore_required_for_next_startup(self) -> None:
        config = build_default_configuration(r"D:\Desktop")
        config.desktop.restore_required = True
        config.desktop.explorer_icons_hidden = True
        service = FakeTakeover(restore_result=False)

        changed = DesktopRecoveryGuard(service).recover_if_needed(config)

        self.assertTrue(changed)
        self.assertEqual(service.calls, ["restore"])
        self.assertTrue(config.desktop.restore_required)
        self.assertTrue(config.desktop.explorer_icons_hidden)

    def test_no_leftover_state_does_not_call_restore(self) -> None:
        config = build_default_configuration(r"D:\Desktop")
        service = FakeTakeover()

        changed = DesktopRecoveryGuard(service).recover_if_needed(config)

        self.assertFalse(changed)
        self.assertEqual(service.calls, [])


class DesktopTakeoverServiceTests(unittest.TestCase):
    def test_non_windows_service_degrades_without_side_effects(self) -> None:
        service = DesktopTakeoverService(platform_name="linux")

        result = service.attach_panels([123])

        self.assertEqual(result, TakeoverResult(False, "unsupported-platform"))
        self.assertFalse(service.hide_explorer_icons())
        self.assertFalse(service.restore_explorer_icons())

    def test_windows_service_attaches_panels_and_toggles_desktop_list_view(self) -> None:
        class FakeUser32:
            def __init__(self) -> None:
                self.parents: list[tuple[int, int]] = []
                self.positions: list[tuple[int, int, int, int, int]] = []
                self.insert_after: list[int] = []
                self.flags: list[int] = []
                self.show_calls: list[tuple[int, int]] = []

            def FindWindowW(self, class_name, _title):
                return 10 if class_name == "Progman" else 0

            def SendMessageTimeoutW(self, *_args):
                return 1

            def EnumWindows(self, callback, lparam):
                callback(10, lparam)
                return 1

            def FindWindowExW(self, parent, after, class_name, title):
                if class_name == "SHELLDLL_DefView" and int(parent) == 10:
                    return 20
                if class_name == "WorkerW" and int(parent) == 0 and int(after) == 10:
                    return 40
                if (
                    class_name == "SysListView32"
                    and int(parent) == 20
                    and title == "FolderView"
                ):
                    return 30
                return 0

            def SetParent(self, hwnd, parent):
                self.parents.append((int(hwnd), int(parent)))
                return 1

            def GetWindowRect(self, hwnd, rect):
                rects = {
                    40: (-7680, 0, 0, 2160),
                    123: (-2880, 0, -1818, 1548),
                }
                left, top, right, bottom = rects[int(hwnd)]
                rect.contents.left = left
                rect.contents.top = top
                rect.contents.right = right
                rect.contents.bottom = bottom
                return 1

            def SetWindowPos(self, hwnd, _after, x, y, width, height, _flags):
                self.positions.append((int(hwnd), int(x), int(y), int(width), int(height)))
                self.insert_after.append(int(_after))
                self.flags.append(int(_flags))
                return 1

            def ShowWindow(self, hwnd, command):
                self.show_calls.append((int(hwnd), int(command)))
                return 0

        user32 = FakeUser32()
        service = DesktopTakeoverService(platform_name="win32", user32=user32)

        self.assertEqual(service.attach_panels([123]), TakeoverResult(True, ""))
        self.assertTrue(service.hide_explorer_icons())
        self.assertTrue(service.restore_explorer_icons())
        service.detach_panels()

        self.assertEqual(user32.parents, [(123, 0)])
        self.assertEqual(
            user32.positions,
            [
                (123, -2880, 0, 1062, 1548),
                (123, -2880, 0, 1062, 1548),
            ],
        )
        self.assertEqual(user32.insert_after[0], 1)
        self.assertFalse(user32.flags[0] & 0x0004)
        self.assertEqual(user32.show_calls, [(30, 0), (30, 5)])

    def test_attach_fails_and_restores_when_panel_lands_offscreen(self) -> None:
        class FakeUser32:
            def __init__(self) -> None:
                self.parents: list[tuple[int, int]] = []
                self.positions: list[tuple[int, int, int, int, int]] = []
                self._panel_rect = (-2628, 0, -1920, 1032)

            def FindWindowW(self, class_name, _title):
                return 10 if class_name == "Progman" else 0

            def SendMessageTimeoutW(self, *_args):
                return 1

            def EnumWindows(self, callback, lparam):
                callback(10, lparam)
                return 1

            def FindWindowExW(self, parent, after, class_name, _title):
                if class_name == "SHELLDLL_DefView" and int(parent) == 10:
                    return 20
                if class_name == "WorkerW" and int(parent) == 0 and int(after) == 10:
                    return 40
                return 0

            def GetSystemMetrics(self, metric):
                values = {76: -1920, 77: 0, 78: 3627, 79: 1032}
                return values[metric]

            def SetParent(self, hwnd, parent):
                self.parents.append((int(hwnd), int(parent)))
                return 1

            def GetWindowRect(self, hwnd, rect):
                rects = {
                    40: (-1920, 0, 2560, 1600),
                    123: self._panel_rect,
                }
                left, top, right, bottom = rects[int(hwnd)]
                rect.contents.left = left
                rect.contents.top = top
                rect.contents.right = right
                rect.contents.bottom = bottom
                return 1

            def SetWindowPos(self, hwnd, _after, x, y, width, height, _flags):
                self.positions.append((int(hwnd), int(x), int(y), int(width), int(height)))
                self._panel_rect = (int(x), int(y), int(x) + int(width), int(y) + int(height))
                return 1

        user32 = FakeUser32()
        service = DesktopTakeoverService(platform_name="win32", user32=user32)

        result = service.attach_panels([123])

        self.assertEqual(result, TakeoverResult(False, "attached-panel-offscreen"))
        self.assertEqual(user32.parents, [(123, 0)])
        self.assertEqual(
            user32.positions,
            [
                (123, -2628, 0, 708, 1032),
                (123, -2628, 0, 708, 1032),
            ],
        )

    def test_restore_icons_returns_false_when_desktop_window_is_missing(self) -> None:
        class FakeUser32:
            def FindWindowW(self, _class_name, _title):
                return None

            def EnumWindows(self, _callback, _lparam):
                return 1

            def FindWindowExW(self, _parent, _after, _class_name, _title):
                return None

        service = DesktopTakeoverService(platform_name="win32", user32=FakeUser32())

        self.assertFalse(service.restore_explorer_icons())


if __name__ == "__main__":
    unittest.main()
