from __future__ import annotations

import ctypes
import sys
from types import TracebackType
from typing import Protocol


ERROR_ALREADY_EXISTS = 183
DEFAULT_MUTEX_NAME = "Local\\DesktopCleaner.SingleInstance"


class _Kernel32(Protocol):
    def CreateMutexW(self, attributes: object, initial_owner: bool, name: str) -> int: ...

    def CloseHandle(self, handle: int) -> bool: ...


class SingleInstanceLock:
    def __init__(
        self,
        name: str = DEFAULT_MUTEX_NAME,
        *,
        platform_name: str | None = None,
        kernel32: _Kernel32 | None = None,
    ) -> None:
        self._name = name
        self._platform_name = platform_name or sys.platform
        self._kernel32 = kernel32
        self._handle: int | None = None

    def acquire(self) -> bool:
        if self._platform_name != "win32":
            return True

        kernel32 = self._api()
        handle = int(kernel32.CreateMutexW(None, False, self._name) or 0)
        if not handle:
            return True

        if self._last_error(kernel32) == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False

        self._handle = handle
        return True

    def release(self) -> None:
        if not self._handle:
            return

        self._api().CloseHandle(self._handle)
        self._handle = None

    def __enter__(self) -> SingleInstanceLock:
        self.acquire()
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self.release()

    def _api(self) -> _Kernel32:
        if self._kernel32 is not None:
            return self._kernel32

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.GetLastError.restype = ctypes.c_ulong
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_bool
        self._kernel32 = kernel32
        return kernel32

    def _last_error(self, kernel32: _Kernel32) -> int:
        get_last_error = getattr(kernel32, "GetLastError", None)
        if get_last_error is not None:
            return int(get_last_error())
        return int(ctypes.get_last_error())
