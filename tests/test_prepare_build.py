from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from desktop_tidy.domain.defaults import build_default_configuration


class FakeStore:
    def __init__(self) -> None:
        self.config = build_default_configuration(Path("C:/Users/CXHY3/Desktop"))
        self.saved: list[tuple[bool, bool]] = []

    def load(self):
        return self.config

    def save(self, config) -> None:
        self.saved.append(
            (
                config.desktop.restore_required,
                config.desktop.explorer_icons_hidden,
            )
        )


class FakeTakeover:
    def __init__(self, restored: bool) -> None:
        self.restored = restored
        self.calls: list[str] = []

    def restore_explorer_icons(self) -> bool:
        self.calls.append("restore")
        return self.restored


class PrepareBuildTests(unittest.TestCase):
    def test_guard_restores_required_desktop_state_before_stopping_processes(self) -> None:
        from scripts.prepare_build import run_guard

        events: list[str] = []
        store = FakeStore()
        store.config.desktop.restore_required = True
        store.config.desktop.explorer_icons_hidden = True
        takeover = FakeTakeover(restored=True)

        def stop_processes() -> None:
            events.append("stop")

        run_guard(store=store, takeover=takeover, stop_processes=stop_processes)

        self.assertEqual(takeover.calls, ["restore"])
        self.assertEqual(store.saved, [(False, False)])
        self.assertEqual(events, ["stop"])

    def test_guard_aborts_when_required_restore_fails(self) -> None:
        from scripts.prepare_build import BuildGuardError, run_guard

        store = FakeStore()
        store.config.desktop.restore_required = True
        takeover = FakeTakeover(restored=False)
        stopped = False

        def stop_processes() -> None:
            nonlocal stopped
            stopped = True

        with self.assertRaises(BuildGuardError):
            run_guard(store=store, takeover=takeover, stop_processes=stop_processes)

        self.assertFalse(stopped)
        self.assertEqual(store.saved, [])

    def test_guard_aborts_when_restore_raises(self) -> None:
        from scripts.prepare_build import BuildGuardError, run_guard

        class RaisingTakeover:
            def restore_explorer_icons(self) -> bool:
                raise RuntimeError("boom")

        store = FakeStore()
        store.config.desktop.explorer_icons_hidden = True

        with self.assertRaises(BuildGuardError):
            run_guard(store=store, takeover=RaisingTakeover(), stop_processes=lambda: None)

    def test_build_script_runs_guard_before_cleanup_and_pyinstaller(self) -> None:
        script = Path("scripts/build_exe.bat").read_text(encoding="utf-8")

        guard_index = script.index(r"python scripts\prepare_build.py")
        build_cleanup_index = script.index("if exist build rmdir /s /q build")
        dist_cleanup_index = script.index("if exist dist rmdir /s /q dist")
        pyinstaller_index = script.index("python -m PyInstaller")

        self.assertLess(guard_index, build_cleanup_index)
        self.assertLess(guard_index, dist_cleanup_index)
        self.assertLess(guard_index, pyinstaller_index)

    def test_stop_running_app_tolerates_no_matching_process(self) -> None:
        from scripts.prepare_build import stop_running_desktop_cleaner

        class Result:
            returncode = 1
            stdout = ""
            stderr = ""

        with patch("scripts.prepare_build.sys.platform", "win32"):
            stop_running_desktop_cleaner(runner=lambda *_args, **_kwargs: Result())


if __name__ == "__main__":
    unittest.main()
