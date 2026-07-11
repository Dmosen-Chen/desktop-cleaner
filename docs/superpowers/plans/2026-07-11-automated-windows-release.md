# Automated Windows Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and verify DesktopCleaner from one PyInstaller configuration, then publish tested Windows executables and SHA256 checksums through a tag-gated GitHub Release workflow.

**Architecture:** `DesktopCleaner.spec` is the only packaging definition. A dependency-free release contract script validates `APP_VERSION`, optional `v*` tags, and executable artifacts; a Windows GitHub Actions workflow composes tests, packaging, checksums, workflow artifacts, and least-privilege tagged releases. The Release executable keeps the exact `DesktopCleaner.exe` name required by the existing updater.

**Tech Stack:** Python 3.13, unittest/pytest, PyInstaller, Windows batch, PowerShell, GitHub Actions, GitHub CLI.

---

## File Structure

- Create `scripts/release_contract.py`: version, tag, and artifact validation without importing Qt.
- Create `tests/test_release_contract.py`: pure unit tests for the release contract and package version export.
- Modify `scripts/build_exe.bat`: preserve the recovery guard but invoke only `DesktopCleaner.spec`.
- Modify `tests/test_build_config.py`: enforce the single-source PyInstaller contract.
- Modify `tests/test_app_icons.py`: verify icon/data packaging through the spec instead of duplicated CLI flags.
- Create `.github/workflows/windows-release.yml`: test, build, checksum, artifact, and tag-only Release jobs.
- Create `tests/test_release_workflow.py`: repository-level workflow contract tests.
- Modify `desktop_tidy/__init__.py`: export the canonical `APP_VERSION` instead of stale `0.1.0` metadata.
- Modify `README.md`: document local builds, CI artifacts, and tag release procedure.

### Task 1: Release Contract and Canonical Version

**Files:**
- Create: `scripts/release_contract.py`
- Create: `tests/test_release_contract.py`
- Modify: `desktop_tidy/__init__.py`

- [ ] **Step 1: Write failing release contract tests**

```python
from pathlib import Path

import pytest

from scripts.release_contract import (
    ReleaseContractError,
    read_app_version,
    validate_artifact,
    validate_release_tag,
)


def test_reads_app_version_without_importing_gui(tmp_path: Path) -> None:
    version_file = tmp_path / "version.py"
    version_file.write_text('APP_VERSION = "2.3.4"\n', encoding="utf-8")
    assert read_app_version(version_file) == "2.3.4"


def test_release_tag_must_match_app_version() -> None:
    assert validate_release_tag("v2.3.4", "2.3.4") == "2.3.4"
    with pytest.raises(ReleaseContractError, match="does not match"):
        validate_release_tag("v2.3.5", "2.3.4")


def test_artifact_must_exist_and_be_non_empty(tmp_path: Path) -> None:
    artifact = tmp_path / "DesktopCleaner.exe"
    with pytest.raises(ReleaseContractError, match="missing"):
        validate_artifact(artifact)
    artifact.write_bytes(b"")
    with pytest.raises(ReleaseContractError, match="empty"):
        validate_artifact(artifact)
    artifact.write_bytes(b"MZ")
    assert validate_artifact(artifact) == artifact


def test_package_version_matches_release_version() -> None:
    from desktop_tidy import __version__
    from desktop_tidy.version import APP_VERSION

    assert __version__ == APP_VERSION
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_release_contract.py -q`

Expected: collection fails because `scripts.release_contract` does not exist, or the package version assertion reports `0.1.0 != 1.0.22`.

- [ ] **Step 3: Implement the release contract**

```python
"""Dependency-free validation for Windows build and release artifacts."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_VERSION_FILE = PROJECT_ROOT / "desktop_tidy" / "version.py"
_VERSION_RE = re.compile(r'^APP_VERSION\s*=\s*["\'](?P<version>\d+\.\d+\.\d+)["\']\s*$', re.MULTILINE)


class ReleaseContractError(ValueError):
    """Raised when release metadata or artifacts violate the contract."""


def read_app_version(path: Path = DEFAULT_VERSION_FILE) -> str:
    match = _VERSION_RE.search(path.read_text(encoding="utf-8"))
    if match is None:
        raise ReleaseContractError(f"APP_VERSION missing or invalid in {path}")
    return match.group("version")


def validate_release_tag(tag: str, version: str) -> str:
    normalized = tag.strip().removeprefix("v")
    if normalized != version:
        raise ReleaseContractError(
            f"release tag {tag!r} does not match APP_VERSION {version!r}"
        )
    return version


def validate_artifact(path: Path) -> Path:
    if not path.is_file():
        raise ReleaseContractError(f"release artifact is missing: {path}")
    if path.stat().st_size <= 0:
        raise ReleaseContractError(f"release artifact is empty: {path}")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default="")
    parser.add_argument("--artifact", type=Path)
    args = parser.parse_args(argv)
    try:
        version = read_app_version()
        if args.tag:
            validate_release_tag(args.tag, version)
        if args.artifact is not None:
            validate_artifact(args.artifact)
    except (OSError, ReleaseContractError) as exc:
        print(exc, file=sys.stderr)
        return 2
    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Change `desktop_tidy/__init__.py` to:

```python
"""Core package for the Desktop Tidy Qt application."""

from desktop_tidy.version import APP_VERSION

__version__ = APP_VERSION
```

- [ ] **Step 4: Run release contract tests**

Run: `python -m pytest tests/test_release_contract.py -q`

Expected: `4 passed`.

- [ ] **Step 5: Commit the release contract**

```bash
git add scripts/release_contract.py tests/test_release_contract.py desktop_tidy/__init__.py
git commit -m "Add Windows release contract validation"
```

### Task 2: Make the Spec the Single Build Source

**Files:**
- Modify: `scripts/build_exe.bat`
- Modify: `tests/test_build_config.py`
- Modify: `tests/test_app_icons.py`
- Verify: `DesktopCleaner.spec`

- [ ] **Step 1: Replace duplicated CLI expectations with spec expectations**

Add these assertions to `tests/test_build_config.py`:

```python
def test_build_script_uses_pyinstaller_spec_as_single_source() -> None:
    script = Path("scripts/build_exe.bat").read_text(encoding="utf-8")

    assert "PyInstaller --noconfirm --clean DesktopCleaner.spec" in script
    assert "--hidden-import" not in script
    assert "--add-data" not in script
    assert "--icon assets" not in script


def test_spec_includes_windows_recent_dependencies() -> None:
    spec = Path("DesktopCleaner.spec").read_text(encoding="utf-8")

    assert "'win32com.client'" in spec
    assert "('assets\\\\icons', 'assets\\\\icons')" in spec
```

Update `tests/test_app_icons.py::test_pyinstaller_build_includes_icon_assets` to read `DesktopCleaner.spec` and assert:

```python
self.assertIn("('assets\\\\icons', 'assets\\\\icons')", spec)
self.assertIn("icon=['assets\\\\icons\\\\app.ico']", spec)
```

- [ ] **Step 2: Run build configuration tests to verify failure**

Run: `python -m pytest tests/test_build_config.py tests/test_app_icons.py -q`

Expected: failures show that `build_exe.bat` still duplicates hidden imports, data, and icon flags.

- [ ] **Step 3: Simplify the local build command**

Keep dependency installation, `prepare_build.py`, and output cleanup unchanged. Replace the PyInstaller command with:

```bat
python -m PyInstaller --noconfirm --clean DesktopCleaner.spec
if errorlevel 1 exit /b 1
```

- [ ] **Step 4: Run build and guard tests**

Run: `python -m pytest tests/test_build_config.py tests/test_app_icons.py tests/test_prepare_build.py -q`

Expected: all tests pass and the guard still appears before cleanup.

- [ ] **Step 5: Commit the single-source build change**

```bash
git add scripts/build_exe.bat tests/test_build_config.py tests/test_app_icons.py
git commit -m "Use PyInstaller spec for Windows builds"
```

### Task 3: Windows CI and Tag-Gated Release Workflow

**Files:**
- Create: `.github/workflows/windows-release.yml`
- Create: `tests/test_release_workflow.py`

- [ ] **Step 1: Write a failing workflow contract test**

```python
from pathlib import Path


def test_windows_release_workflow_contract() -> None:
    workflow = Path(".github/workflows/windows-release.yml").read_text(
        encoding="utf-8"
    )

    assert "pull_request:" in workflow
    assert "branches: [main]" in workflow
    assert 'tags: ["v*"]' in workflow
    assert "workflow_dispatch:" in workflow
    assert "contents: read" in workflow
    assert "python -m pytest -q" in workflow
    assert "needs: test" in workflow
    assert "DesktopCleaner.spec" in workflow
    assert "scripts/release_contract.py" in workflow
    assert "Get-FileHash" in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "DesktopCleaner.exe.sha256" in workflow
    assert "if: startsWith(github.ref, 'refs/tags/v')" in workflow
    assert "contents: write" in workflow
    assert "gh release create" in workflow
```

- [ ] **Step 2: Run the workflow test to verify failure**

Run: `python -m pytest tests/test_release_workflow.py -q`

Expected: failure because `.github/workflows/windows-release.yml` is missing.

- [ ] **Step 3: Create the workflow**

Create a workflow with this job graph:

```yaml
permissions:
  contents: read

jobs:
  test:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
          cache: pip
      - run: python -m pip install -r requirements-build.txt
      - run: python -m pytest -q

  build:
    needs: test
    runs-on: windows-latest
    outputs:
      version: ${{ steps.metadata.outputs.version }}
      artifact_name: ${{ steps.metadata.outputs.artifact_name }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
          cache: pip
      - run: python -m pip install -r requirements-build.txt
      - run: python -m PyInstaller --noconfirm --clean DesktopCleaner.spec
      - id: metadata
        shell: pwsh
        run: |
          $tag = if ("${{ github.ref_type }}" -eq "tag") { "${{ github.ref_name }}" } else { "" }
          $version = python scripts/release_contract.py --tag $tag --artifact dist\DesktopCleaner.exe
          if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
          $hash = (Get-FileHash -Algorithm SHA256 dist\DesktopCleaner.exe).Hash.ToLowerInvariant()
          "$hash  DesktopCleaner.exe" | Set-Content dist\DesktopCleaner.exe.sha256 -Encoding ascii
          "version=$version" >> $env:GITHUB_OUTPUT
          "artifact_name=DesktopCleaner-v$version-windows-x64" >> $env:GITHUB_OUTPUT
      - uses: actions/upload-artifact@v4
        with:
          name: ${{ steps.metadata.outputs.artifact_name }}
          path: |
            dist/DesktopCleaner.exe
            dist/DesktopCleaner.exe.sha256
          if-no-files-found: error

  release:
    if: startsWith(github.ref, 'refs/tags/v')
    needs: build
    runs-on: windows-latest
    permissions:
      contents: write
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: ${{ needs.build.outputs.artifact_name }}
          path: dist
      - shell: pwsh
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          gh release view $env:GITHUB_REF_NAME 2>$null
          if ($LASTEXITCODE -eq 0) { throw "Release already exists: $env:GITHUB_REF_NAME" }
          gh release create $env:GITHUB_REF_NAME dist\DesktopCleaner.exe dist\DesktopCleaner.exe.sha256 --verify-tag --title "DesktopCleaner $env:GITHUB_REF_NAME" --generate-notes
```

Add triggers for `pull_request`, pushes to `main`, pushes of `v*` tags, and `workflow_dispatch`. Add concurrency keyed by workflow and ref with `cancel-in-progress: true`.

- [ ] **Step 4: Run workflow contract and release contract tests**

Run: `python -m pytest tests/test_release_workflow.py tests/test_release_contract.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit the workflow**

```bash
git add .github/workflows/windows-release.yml tests/test_release_workflow.py
git commit -m "Add tested Windows release workflow"
```

### Task 4: Release Documentation

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Document local and automated builds**

Add commands and rules equivalent to:

```markdown
## Windows builds and releases

Local build:

    scripts\build_exe.bat

CI runs tests and uploads `DesktopCleaner.exe` plus
`DesktopCleaner.exe.sha256` for pull requests, `main`, and manual runs.

To publish a release:

1. Update `APP_VERSION` in `desktop_tidy/version.py`.
2. Commit and push the version change.
3. Create and push the matching tag, for example `v1.0.23`.

The workflow rejects mismatched tags and does not overwrite existing releases.
The Release executable must remain named `DesktopCleaner.exe` for the built-in
updater.
```

- [ ] **Step 2: Verify documented commands and names**

Run:

```powershell
rg -n "DesktopCleaner.spec|DesktopCleaner.exe.sha256|APP_VERSION|v1.0.23" README.md scripts .github
```

Expected: every documented file, command, and asset name matches the implementation.

- [ ] **Step 3: Commit release documentation**

```bash
git add README.md
git commit -m "Document automated Windows releases"
```

### Task 5: Local Build and Executable Verification

**Files:**
- Build output: `dist/DesktopCleaner.exe` (ignored generated artifact)
- Desktop shortcut: `DesktopCleaner.lnk` (outside repository)

- [ ] **Step 1: Run the complete test suite before building**

Run: `python -m pytest -q`

Expected: all tests pass.

- [ ] **Step 2: Build through the guarded local entry point**

Run: `scripts\build_exe.bat`

Expected: the guard restores desktop state, PyInstaller succeeds through `DesktopCleaner.spec`, and `dist\DesktopCleaner.exe` exists.

- [ ] **Step 3: Validate and hash the executable**

Run:

```powershell
python scripts\release_contract.py --artifact dist\DesktopCleaner.exe
Get-FileHash -Algorithm SHA256 dist\DesktopCleaner.exe
```

Expected: the first command prints the current `APP_VERSION`; the second prints a non-empty SHA256 hash.

- [ ] **Step 4: Smoke-test startup with recovery cleanup**

Start `dist\DesktopCleaner.exe`, wait for the process to initialize, then run `python scripts\prepare_build.py` to restore Explorer icons and stop the executable. Verify the application process existed before cleanup and no `DesktopCleaner` process remains afterward.

- [ ] **Step 5: Recreate and verify the desktop shortcut**

Use `WScript.Shell.CreateShortcut` to set:

```text
TargetPath       = <project>\dist\DesktopCleaner.exe
WorkingDirectory = <project>\dist
IconLocation     = <project>\dist\DesktopCleaner.exe,0
```

Reopen the `.lnk` and assert all three properties resolve to the rebuilt executable.

### Task 6: Final Release Audit

**Files:**
- Verify all changed files

- [ ] **Step 1: Run focused release tests**

Run:

```powershell
python -m pytest tests/test_release_contract.py tests/test_release_workflow.py tests/test_build_config.py tests/test_app_icons.py tests/test_prepare_build.py tests/test_update_service.py -q
```

Expected: all focused tests pass, including the existing updater requirement for `DesktopCleaner.exe`.

- [ ] **Step 2: Run the complete suite and patch checks**

Run:

```powershell
python -m pytest -q
git diff --check
git status --short
```

Expected: full suite passes, `git diff --check` reports no errors, and only intentional source/docs/workflow changes remain.

- [ ] **Step 3: Review workflow permissions and release gating**

Run:

```powershell
rg -n "permissions:|contents: write|refs/tags/v|gh release create|DesktopCleaner.exe" .github/workflows/windows-release.yml
```

Expected: repository default is read-only, only the release job has write permission, and release creation is tag-gated with the updater-compatible asset name.

- [ ] **Step 4: Commit any final test-only corrections**

```bash
git add tests scripts .github README.md desktop_tidy/__init__.py
git commit -m "Verify automated Windows release pipeline"
```

Skip this commit if the worktree is already clean.
