from __future__ import annotations

import ast
import subprocess
import unittest
from pathlib import Path


def _find_top_level_call(tree: ast.Module, name: str) -> ast.Call:
    for statement in tree.body:
        if not isinstance(statement, ast.Assign):
            continue
        call = statement.value
        if (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == name
        ):
            return call
    raise AssertionError(f"DesktopCleaner.spec has no {name} call")


def _keyword_values(call: ast.Call) -> dict[str, object]:
    return {
        keyword.arg: ast.literal_eval(keyword.value)
        for keyword in call.keywords
        if keyword.arg is not None
    }


class BuildConfigTests(unittest.TestCase):
    def test_canonical_spec_is_present_tracked_and_not_ignored(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        spec_path = repo_root / "DesktopCleaner.spec"

        self.assertTrue(spec_path.is_file(), "DesktopCleaner.spec is missing")

        tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", spec_path.name],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        ignored = subprocess.run(
            ["git", "check-ignore", "--no-index", "--quiet", "--", spec_path.name],
            cwd=repo_root,
            check=False,
        )

        self.assertEqual(
            tracked.returncode,
            0,
            f"DesktopCleaner.spec is not tracked by Git: {tracked.stderr.strip()}",
        )
        self.assertEqual(
            ignored.returncode,
            1,
            "DesktopCleaner.spec is still matched by a Git ignore rule",
        )

    def test_build_script_uses_spec_as_pyinstaller_source_of_truth(self) -> None:
        script = Path("scripts/build_exe.bat").read_text(encoding="utf-8")

        pyinstaller_commands = [
            line.strip()
            for line in script.splitlines()
            if line.strip().startswith("python -m PyInstaller")
        ]

        self.assertEqual(
            pyinstaller_commands,
            ["python -m PyInstaller --noconfirm --clean DesktopCleaner.spec"],
        )
        self.assertNotIn("--hidden-import", script)
        self.assertNotIn("--add-data", script)
        self.assertNotIn("--icon", script)

    def test_spec_defines_windows_build_configuration(self) -> None:
        spec_tree = ast.parse(
            Path("DesktopCleaner.spec").read_text(encoding="utf-8"),
            filename="DesktopCleaner.spec",
        )

        analysis_options = _keyword_values(_find_top_level_call(spec_tree, "Analysis"))
        self.assertIn(
            (r"assets\icons", r"assets\icons"),
            analysis_options["datas"],
        )
        self.assertEqual(
            set(analysis_options["hiddenimports"]),
            {
                "pythoncom",
                "pywintypes",
                "win32gui",
                "win32con",
                "win32com.shell",
                "win32com.client",
            },
        )

        exe_options = _keyword_values(_find_top_level_call(spec_tree, "EXE"))
        self.assertEqual(exe_options["name"], "DesktopCleaner")
        self.assertIs(exe_options["console"], False)
        self.assertIn(r"assets\icons\app.ico", exe_options["icon"])
        self.assertFalse(
            any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "COLLECT"
                for node in ast.walk(spec_tree)
            )
        )


if __name__ == "__main__":
    unittest.main()
