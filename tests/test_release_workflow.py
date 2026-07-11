from __future__ import annotations

import re
from pathlib import Path

import pytest


WORKFLOW_PATH = (
    Path(__file__).resolve().parents[1] / ".github" / "workflows" / "windows-release.yml"
)


@pytest.fixture
def workflow() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def _top_level_block(workflow: str, key: str) -> str:
    lines = workflow.splitlines()
    start = lines.index(f"{key}:")
    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if lines[index] and not lines[index][0].isspace()
        ),
        len(lines),
    )
    return "\n".join(lines[start:end]).rstrip()


def _job(workflow: str, name: str) -> str:
    lines = workflow.splitlines()
    start = lines.index(f"  {name}:")
    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if re.fullmatch(r"  [A-Za-z0-9_-]+:", lines[index])
        ),
        len(lines),
    )
    return "\n".join(lines[start:end])


def _assert_windows_python_setup(job: str) -> None:
    checkout = job.index("uses: actions/checkout@v4")
    setup = job.index("uses: actions/setup-python@v5")
    install = job.index("run: python -m pip install -r requirements-build.txt")
    lines = {line.strip() for line in job.splitlines()}

    assert checkout < setup < install
    assert "run: python -m pip install -r requirements-build.txt" in lines
    assert 'python-version: "3.13"' in job
    assert "cache: pip" in job
    assert "cache-dependency-path: requirements-build.txt" in job


def test_triggers_root_permissions_and_concurrency(workflow: str) -> None:
    triggers = _top_level_block(workflow, "on")
    root_permissions = _top_level_block(workflow, "permissions")
    concurrency = _top_level_block(workflow, "concurrency")

    assert "  pull_request:" in triggers
    assert "  workflow_dispatch:" in triggers
    assert re.search(r"(?m)^  push:\n    branches:\n      - main$", triggers)
    assert re.search(r'(?m)^    tags:\n      - "v\*"$', triggers)
    assert root_permissions == "permissions:\n  contents: read"
    assert "contents: write" not in root_permissions
    assert (
        "group: windows-release-${{ github.workflow }}-${{ github.ref }}"
        in concurrency
    )
    assert "cancel-in-progress: true" in concurrency


def test_test_job_runs_the_full_suite_on_windows(workflow: str) -> None:
    test_job = _job(workflow, "test")

    assert "runs-on: windows-latest" in test_job
    _assert_windows_python_setup(test_job)
    assert "run: python -m pytest -q" in {
        line.strip() for line in test_job.splitlines()
    }
    assert test_job.index("requirements-build.txt") < test_job.index(
        "run: python -m pytest -q"
    )


def test_build_job_depends_on_tests_and_uses_only_the_spec(workflow: str) -> None:
    build_job = _job(workflow, "build")
    build_command = (
        "run: python -m PyInstaller --noconfirm --clean DesktopCleaner.spec"
    )

    lines = {line.strip() for line in build_job.splitlines()}
    assert "needs: test" in lines
    assert "runs-on: windows-latest" in build_job
    _assert_windows_python_setup(build_job)
    assert build_command in lines
    assert build_job.index("requirements-build.txt") < build_job.index(build_command)
    assert build_job.lower().count("pyinstaller") == 1


def test_build_metadata_validates_and_publishes_checksum_outputs(
    workflow: str,
) -> None:
    build_job = _job(workflow, "build")

    assert "id: metadata" in build_job
    assert "shell: pwsh" in build_job
    assert (
        "RELEASE_TAG: ${{ github.ref_type == 'tag' && github.ref_name || '' }}"
        in build_job
    )
    assert (
        'python scripts/release_contract.py --tag "$env:RELEASE_TAG" '
        '--artifact "dist\\DesktopCleaner.exe"'
        in build_job
    )
    assert "if ($LASTEXITCODE -ne 0)" in build_job
    assert "exit $LASTEXITCODE" in build_job
    assert (
        'Get-FileHash -Algorithm SHA256 -LiteralPath "dist\\DesktopCleaner.exe"'
        in build_job
    )
    assert ".Hash.ToLowerInvariant()" in build_job
    assert (
        '"$hash  DesktopCleaner.exe" | Set-Content -LiteralPath '
        '"dist\\DesktopCleaner.exe.sha256" -Encoding ascii'
        in build_job
    )
    assert '"version=$version" >> $env:GITHUB_OUTPUT' in build_job
    assert (
        '"artifact_name=DesktopCleaner-v$version-windows-x64" '
        ">> $env:GITHUB_OUTPUT"
        in build_job
    )
    assert "version: ${{ steps.metadata.outputs.version }}" in build_job
    assert (
        "artifact_name: ${{ steps.metadata.outputs.artifact_name }}" in build_job
    )


def test_build_uploads_only_the_executable_and_checksum(workflow: str) -> None:
    build_job = _job(workflow, "build")

    assert "uses: actions/upload-artifact@v4" in build_job
    assert "name: ${{ steps.metadata.outputs.artifact_name }}" in build_job
    assert re.search(
        r"(?m)^          path: \|\n"
        r"            dist\\DesktopCleaner\.exe\n"
        r"            dist\\DesktopCleaner\.exe\.sha256\n"
        r"          if-no-files-found: error$",
        build_job,
    )
    assert "if-no-files-found: error" in build_job


def test_release_job_is_tag_only_and_has_job_scoped_write_permission(
    workflow: str,
) -> None:
    release_job = _job(workflow, "release")
    root = workflow.split("\njobs:", maxsplit=1)[0]

    assert re.search(
        r"(?m)^    if: startsWith\(github\.ref, 'refs/tags/v'\)$", release_job
    )
    assert "needs: build" in {line.strip() for line in release_job.splitlines()}
    assert re.search(
        r"(?m)^    permissions:\n      contents: write$", release_job
    )
    assert "contents: write" not in root
    assert "GH_TOKEN: ${{ github.token }}" in release_job


def test_release_downloads_current_artifact_and_guards_creation(
    workflow: str,
) -> None:
    release_job = _job(workflow, "release")
    guard = release_job.index("gh release view")
    create = release_job.index("gh release create")

    assert "uses: actions/download-artifact@v4" in release_job
    assert "name: ${{ needs.build.outputs.artifact_name }}" in release_job
    assert "path: dist" in release_job
    assert guard < create
    assert 'gh release view "${{ github.ref_name }}"' in release_job
    assert "exit 1" in release_job[guard:create]
    assert 'gh release create "${{ github.ref_name }}"' in release_job
    assert "--verify-tag" in release_job
    assert "--title" in release_job
    assert "--generate-notes" in release_job
    assert re.findall(r'"dist/[^"\n]+"', release_job[create:]) == [
        '"dist/DesktopCleaner.exe"',
        '"dist/DesktopCleaner.exe.sha256"',
    ]
