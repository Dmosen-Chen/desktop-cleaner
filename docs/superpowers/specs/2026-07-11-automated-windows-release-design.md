# DesktopCleaner Automated Windows Release Design

## Status

Approved on 2026-07-11.

## Problem

The checked-in Windows executable can lag behind `main`, the batch script and
`DesktopCleaner.spec` currently duplicate PyInstaller options, and the repository
has no CI release pipeline. This makes it possible to publish source changes while
users continue running an older executable.

## Goals

- Make `DesktopCleaner.spec` the single source of truth for executable packaging.
- Run the full test suite before accepting or publishing a Windows build.
- Produce a Windows executable and SHA256 checksum for CI builds.
- Create a GitHub Release only for an explicit `v*` tag whose version matches
  `desktop_tidy/version.py`.
- Rebuild the local executable from the latest `main` and keep the desktop shortcut
  pointed at the verified output.

## Non-Goals

- Automatically creating version tags.
- Overwriting an existing GitHub Release.
- Code signing before a certificate is available.
- Changing the in-application update protocol or configuration schema.

## Build Architecture

`DesktopCleaner.spec` owns hidden imports, bundled assets, executable metadata,
windowed mode, and the application icon. `scripts/build_exe.bat` keeps the local
desktop-recovery guard, installs build dependencies, removes stale output, and then
invokes `python -m PyInstaller --noconfirm --clean DesktopCleaner.spec`.

CI invokes the same spec directly after installing `requirements-build.txt`. It
does not run the local desktop-recovery guard because a clean GitHub runner cannot
have an active DesktopCleaner takeover session.

## Version Contract

`desktop_tidy/version.py::APP_VERSION` is the release version source. A small
dependency-free verification script accepts an optional tag and artifact path.
It must:

- parse `APP_VERSION` without importing the GUI application;
- normalize a leading `v` from the supplied tag;
- fail when a release tag and `APP_VERSION` differ;
- fail when the expected executable is missing or empty;
- print the resolved version for subsequent workflow steps.

The pipeline never changes `APP_VERSION` automatically.

## GitHub Actions Workflow

One Windows workflow handles validation, build artifacts, and tagged releases:

- `pull_request` and pushes to `main`: run tests, build the executable, generate a
  SHA256 file, and upload both as a workflow artifact.
- `workflow_dispatch`: perform the same test and build path without publishing.
- pushes of `v*` tags: run the same gates, validate the tag/version contract, then
  create a GitHub Release containing the executable and checksum.

The test/build jobs use read-only repository permissions. Only the tag-gated
release job receives `contents: write`. The release job must fail if the release
already exists rather than silently replacing assets.

Release assets preserve the executable name required by the in-application
updater:

- `DesktopCleaner.exe`
- `DesktopCleaner.exe.sha256`

The downloadable workflow artifact is named
`DesktopCleaner-v<version>-windows-x64`, so non-release CI builds remain
identifiable without changing the executable name inside the artifact.

## Failure Handling

- Test failure prevents packaging.
- Version mismatch prevents release creation.
- Missing or zero-byte executables fail verification before checksum generation.
- Build and release artifacts are uploaded only from the current workflow run.
- No force-push, implicit tagging, or release replacement is permitted.

## Testing

- Unit tests cover version parsing, tag matching, and missing/empty artifact errors.
- Build configuration tests assert that the batch script invokes
  `DesktopCleaner.spec` and no longer duplicates PyInstaller options.
- Workflow contract tests check triggers, least-privilege permissions, test/build
  ordering, checksum generation, artifact upload, and tag-only release gating.
- The complete Python test suite runs locally and in CI.
- A local PyInstaller build verifies that the final executable exists, is non-empty,
  starts successfully on Windows, and remains the desktop shortcut target.

## Acceptance Criteria

- Local and CI builds use `DesktopCleaner.spec`.
- Pull requests and `main` builds cannot bypass tests.
- Every CI executable has a SHA256 checksum.
- Only matching `v*` tags can create a GitHub Release.
- Tagged releases retain the exact `DesktopCleaner.exe` asset name required by the
  existing update service.
- The locally rebuilt executable comes from the latest source and the desktop
  shortcut resolves to that verified file.
