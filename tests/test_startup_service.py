from __future__ import annotations

import unittest
from pathlib import Path

from desktop_tidy.services.startup import StartupService


class FakeKey:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class FakeWinreg:
    HKEY_CURRENT_USER = object()
    KEY_SET_VALUE = 0x0002
    REG_SZ = 1

    def __init__(self) -> None:
        self.opened: list[tuple[object, str, int, int]] = []
        self.values: dict[str, str] = {}
        self.deleted: list[str] = []

    def OpenKey(self, root, path: str, reserved: int, access: int):
        self.opened.append((root, path, reserved, access))
        return FakeKey()

    def SetValueEx(self, _key, name: str, _reserved: int, kind: int, value: str) -> None:
        self.values[name] = value
        self.value_kind = kind

    def DeleteValue(self, _key, name: str) -> None:
        self.deleted.append(name)


class StartupServiceTests(unittest.TestCase):
    def test_enable_writes_run_key_with_quoted_executable(self) -> None:
        registry = FakeWinreg()
        service = StartupService(platform_name="win32", registry=registry)

        enabled = service.set_enabled(True, Path(r"C:\Program Files\DesktopCleaner.exe"))

        self.assertTrue(enabled)
        self.assertEqual(
            registry.values["DesktopCleaner"],
            r'"C:\Program Files\DesktopCleaner.exe"',
        )
        self.assertEqual(registry.value_kind, registry.REG_SZ)
        self.assertEqual(len(registry.opened), 1)

    def test_disable_removes_run_key_and_treats_missing_value_as_success(self) -> None:
        class MissingValueWinreg(FakeWinreg):
            def DeleteValue(self, _key, name: str) -> None:
                super().DeleteValue(_key, name)
                raise FileNotFoundError(name)

        registry = MissingValueWinreg()
        service = StartupService(platform_name="win32", registry=registry)

        disabled = service.set_enabled(False, Path(r"C:\DesktopCleaner.exe"))

        self.assertTrue(disabled)
        self.assertEqual(registry.deleted, ["DesktopCleaner"])

    def test_non_windows_startup_is_reported_as_unsupported(self) -> None:
        service = StartupService(platform_name="linux")

        self.assertFalse(service.set_enabled(True, Path("/tmp/DesktopCleaner")))


if __name__ == "__main__":
    unittest.main()
