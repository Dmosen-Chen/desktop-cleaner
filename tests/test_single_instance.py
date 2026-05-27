from __future__ import annotations

import unittest
from unittest.mock import patch

from desktop_tidy.services.single_instance import (
    ERROR_ALREADY_EXISTS,
    SingleInstanceLock,
)


class FakeKernel32:
    def __init__(self, *, last_error: int = 0, handle: int = 99) -> None:
        self.last_error = last_error
        self.handle = handle
        self.created_names: list[str] = []
        self.closed_handles: list[int] = []

    def CreateMutexW(self, _attributes: object, _initial_owner: bool, name: str) -> int:
        self.created_names.append(name)
        return self.handle

    def GetLastError(self) -> int:
        return self.last_error

    def CloseHandle(self, handle: int) -> bool:
        self.closed_handles.append(int(handle))
        return True


class FakeWinDllFunction:
    def __init__(self, func):
        self._func = func
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        return self._func(*args)


class FakeWinDllKernel32:
    def __init__(self, *, last_error: int = 0, handle: int = 99) -> None:
        self.last_error = last_error
        self.handle = handle
        self.created_names: list[str] = []
        self.closed_handles: list[int] = []
        self.CreateMutexW = FakeWinDllFunction(self._create_mutex)
        self.GetLastError = FakeWinDllFunction(lambda: self.last_error)
        self.CloseHandle = FakeWinDllFunction(self._close_handle)

    def _create_mutex(self, _attributes: object, _initial_owner: bool, name: str) -> int:
        self.created_names.append(name)
        return self.handle

    def _close_handle(self, handle: int) -> bool:
        self.closed_handles.append(int(handle))
        return True


class SingleInstanceLockTests(unittest.TestCase):
    def test_non_windows_acquire_is_noop(self) -> None:
        kernel32 = FakeKernel32()

        lock = SingleInstanceLock(platform_name="linux", kernel32=kernel32)

        self.assertTrue(lock.acquire())
        self.assertEqual(kernel32.created_names, [])

    def test_first_windows_instance_holds_mutex_until_release(self) -> None:
        kernel32 = FakeKernel32()

        lock = SingleInstanceLock("DesktopCleanerTest", platform_name="win32", kernel32=kernel32)

        self.assertTrue(lock.acquire())
        self.assertEqual(kernel32.created_names, ["DesktopCleanerTest"])
        self.assertEqual(kernel32.closed_handles, [])

        lock.release()

        self.assertEqual(kernel32.closed_handles, [99])

    def test_duplicate_windows_instance_closes_duplicate_handle(self) -> None:
        kernel32 = FakeKernel32(last_error=ERROR_ALREADY_EXISTS, handle=123)

        lock = SingleInstanceLock("DesktopCleanerTest", platform_name="win32", kernel32=kernel32)

        self.assertFalse(lock.acquire())
        self.assertEqual(kernel32.closed_handles, [123])

    def test_duplicate_windows_instance_uses_real_api_last_error_path(self) -> None:
        kernel32 = FakeWinDllKernel32(last_error=ERROR_ALREADY_EXISTS, handle=456)

        with patch("desktop_tidy.services.single_instance.ctypes.WinDLL", return_value=kernel32):
            lock = SingleInstanceLock("DesktopCleanerTest", platform_name="win32")

            self.assertFalse(lock.acquire())

        self.assertEqual(kernel32.closed_handles, [456])


if __name__ == "__main__":
    unittest.main()
