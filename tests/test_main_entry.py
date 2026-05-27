from __future__ import annotations

import importlib
import unittest
from unittest.mock import patch


entrypoint = importlib.import_module("main")


class FakeLock:
    def __init__(self, acquired: bool) -> None:
        self.acquired = acquired
        self.released = False

    def acquire(self) -> bool:
        return self.acquired

    def release(self) -> None:
        self.released = True


class MainEntryTests(unittest.TestCase):
    def test_duplicate_instance_exits_without_creating_qt_application(self) -> None:
        lock = FakeLock(False)

        with (
            patch.object(entrypoint, "SingleInstanceLock", return_value=lock),
            patch.object(entrypoint, "ensure_application") as ensure_application,
            patch.object(entrypoint, "DesktopCleanerApplication") as application_type,
        ):
            exit_code = entrypoint.main()

        self.assertEqual(exit_code, 0)
        ensure_application.assert_not_called()
        application_type.assert_not_called()
        self.assertFalse(lock.released)

    def test_first_instance_runs_application_and_releases_lock(self) -> None:
        lock = FakeLock(True)
        application = _FakeApplication(exit_code=7)

        with (
            patch.object(entrypoint, "SingleInstanceLock", return_value=lock),
            patch.object(entrypoint, "ensure_application") as ensure_application,
            patch.object(entrypoint, "DesktopCleanerApplication", return_value=application) as application_type,
        ):
            exit_code = entrypoint.main()

        self.assertEqual(exit_code, 7)
        ensure_application.assert_called_once_with()
        application_type.assert_called_once_with()
        self.assertTrue(lock.released)


class _FakeApplication:
    def __init__(self, *, exit_code: int) -> None:
        self.exit_code = exit_code

    def run(self) -> int:
        return self.exit_code


if __name__ == "__main__":
    unittest.main()
