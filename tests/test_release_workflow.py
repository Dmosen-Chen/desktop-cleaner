from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Any

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "windows-release.yml"
BUILD_REQUIREMENTS_PATH = ROOT / "requirements-build.txt"


@pytest.fixture
def workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


@pytest.fixture
def workflow(workflow_text: str) -> dict[str, Any]:
    loaded = yaml.load(workflow_text, Loader=yaml.BaseLoader)
    assert isinstance(loaded, dict)
    return loaded


def _job(workflow: dict[str, Any], name: str) -> dict[str, Any]:
    return workflow["jobs"][name]


def _step(job: dict[str, Any], name: str) -> dict[str, Any]:
    return next(step for step in job["steps"] if step.get("name") == name)


def _assert_windows_python_setup(job: dict[str, Any]) -> None:
    checkout = _step(job, "Check out repository")
    setup = _step(job, "Set up Python")
    install = _step(job, "Install build requirements")
    steps = job["steps"]

    assert steps.index(checkout) < steps.index(setup) < steps.index(install)
    assert checkout["uses"] == "actions/checkout@v4"
    assert setup["uses"] == "actions/setup-python@v5"
    assert setup["with"] == {
        "python-version": "3.13",
        "cache": "pip",
        "cache-dependency-path": "requirements-build.txt",
    }
    assert install["run"] == "python -m pip install -r requirements-build.txt"


def test_build_requirements_declare_yaml_parser() -> None:
    requirements = BUILD_REQUIREMENTS_PATH.read_text(encoding="utf-8").splitlines()

    assert "PyYAML>=6,<7" in requirements


def test_triggers_root_permissions_and_concurrency(
    workflow: dict[str, Any],
) -> None:
    triggers = workflow["on"]

    assert set(triggers) == {"pull_request", "push", "workflow_dispatch"}
    assert triggers["push"]["branches"] == ["main"]
    assert triggers["push"]["tags"] == ["v*"]
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"] == {
        "group": "windows-release-${{ github.workflow }}-${{ github.ref }}",
        "cancel-in-progress": "true",
    }


def test_test_job_runs_the_full_suite_on_windows(workflow: dict[str, Any]) -> None:
    test_job = _job(workflow, "test")

    assert test_job["runs-on"] == "windows-latest"
    _assert_windows_python_setup(test_job)
    test_step = _step(test_job, "Run tests")
    assert test_step["run"] == "python -m pytest -q"
    assert test_job["steps"].index(_step(test_job, "Install build requirements")) < (
        test_job["steps"].index(test_step)
    )


def test_build_job_depends_on_tests_and_uses_only_the_spec(
    workflow: dict[str, Any],
) -> None:
    build_job = _job(workflow, "build")
    build_step = _step(build_job, "Build executable")

    assert build_job["needs"] == "test"
    assert build_job["runs-on"] == "windows-latest"
    _assert_windows_python_setup(build_job)
    assert (
        build_step["run"]
        == "python -m PyInstaller --noconfirm --clean DesktopCleaner.spec"
    )
    assert build_job["steps"].index(
        _step(build_job, "Install build requirements")
    ) < build_job["steps"].index(build_step)
    assert (
        sum(
            "pyinstaller" in step.get("run", "").lower()
            for step in build_job["steps"]
        )
        == 1
    )


def test_build_metadata_validates_and_publishes_checksum_outputs(
    workflow: dict[str, Any],
) -> None:
    build_job = _job(workflow, "build")
    metadata = _step(build_job, "Validate release metadata and create checksum")
    script = metadata["run"]

    assert build_job["outputs"] == {
        "version": "${{ steps.metadata.outputs.version }}",
        "artifact_name": "${{ steps.metadata.outputs.artifact_name }}",
    }
    assert metadata["id"] == "metadata"
    assert metadata["shell"] == "pwsh"
    assert metadata["env"] == {
        "RELEASE_TAG": "${{ github.ref_type == 'tag' && github.ref_name || '' }}"
    }
    assert (
        'python scripts/release_contract.py --tag "$env:RELEASE_TAG" '
        '--artifact "dist\\DesktopCleaner.exe"'
        in script
    )
    assert "if ($LASTEXITCODE -ne 0)" in script
    assert "exit $LASTEXITCODE" in script
    assert (
        'Get-FileHash -Algorithm SHA256 -LiteralPath "dist\\DesktopCleaner.exe"'
        in script
    )
    assert ".Hash.ToLowerInvariant()" in script
    assert (
        '"$hash  DesktopCleaner.exe" | Set-Content -LiteralPath '
        '"dist\\DesktopCleaner.exe.sha256" -Encoding ascii'
        in script
    )
    assert '"version=$version" >> $env:GITHUB_OUTPUT' in script
    assert (
        '"artifact_name=DesktopCleaner-v$version-windows-x64" '
        ">> $env:GITHUB_OUTPUT"
        in script
    )


def test_build_uploads_only_the_executable_and_checksum(
    workflow: dict[str, Any],
) -> None:
    build_job = _job(workflow, "build")
    upload = _step(build_job, "Upload Windows artifact")

    assert upload["uses"] == "actions/upload-artifact@v4"
    assert upload["with"] == {
        "name": "${{ steps.metadata.outputs.artifact_name }}",
        "path": "dist\\DesktopCleaner.exe\ndist\\DesktopCleaner.exe.sha256\n",
        "if-no-files-found": "error",
    }


def test_release_job_is_tag_only_build_dependent_and_write_scoped(
    workflow: dict[str, Any],
) -> None:
    release_job = _job(workflow, "release")

    assert workflow["permissions"] == {"contents": "read"}
    assert release_job["if"] == "startsWith(github.ref, 'refs/tags/v')"
    assert release_job["needs"] == "build"
    assert release_job["permissions"] == {"contents": "write"}
    assert release_job["env"]["GH_TOKEN"] == "${{ github.token }}"


def test_run_scripts_never_interpolate_github_expressions(
    workflow: dict[str, Any],
) -> None:
    scripts = [
        (job_name, step["name"], step["run"])
        for job_name, job in workflow["jobs"].items()
        for step in job["steps"]
        if "run" in step
    ]

    for job_name, step_name, script in scripts:
        assert "${{" not in script, (
            f"{job_name}/{step_name} directly interpolates an expression in a run script"
        )
        assert "${{ github.ref_name }}" not in script


def test_existing_release_lookup_is_explicit_and_fail_closed(
    workflow: dict[str, Any],
) -> None:
    release_job = _job(workflow, "release")
    guard = _step(release_job, "Ensure release does not already exist")
    script = guard["run"]

    assert guard["shell"] == "pwsh"
    assert guard["env"] == {
        "RELEASE_TAG": "${{ github.ref_name }}",
        "RELEASE_REPOSITORY": "${{ github.repository }}",
    }
    assert '$ErrorActionPreference = "Stop"' in script
    assert (
        "$encodedTag = [System.Uri]::EscapeDataString($env:RELEASE_TAG)" in script
    )
    assert "Invoke-WebRequest" in script
    assert "-SkipHttpErrorCheck" in script
    assert 'Authorization = "Bearer $env:GH_TOKEN"' in script
    assert 'Accept = "application/vnd.github+json"' in script
    assert "switch ([int]$response.StatusCode)" in script
    assert "gh release view" not in script
    assert "-ErrorAction" not in script
    assert "SilentlyContinue" not in script
    assert not re.search(r"(?im)^\s*(try|catch)\b", script)

    cases = dict(
        re.findall(r"(?ms)^\s+(200|404|default)\s+\{(.*?)^\s+\}", script)
    )
    assert set(cases) == {"200", "404", "default"}
    assert "throw" in cases["200"]
    assert "throw" not in cases["404"]
    assert "throw" in cases["default"]


def test_release_downloads_and_creates_with_exact_assets(
    workflow: dict[str, Any],
) -> None:
    release_job = _job(workflow, "release")
    download = _step(release_job, "Download Windows artifact")
    guard = _step(release_job, "Ensure release does not already exist")
    create = _step(release_job, "Create release")
    script = create["run"]

    assert download["uses"] == "actions/download-artifact@v4"
    assert download["with"] == {
        "name": "${{ needs.build.outputs.artifact_name }}",
        "path": "dist",
    }
    assert release_job["steps"].index(guard) < release_job["steps"].index(create)
    assert create["shell"] == "pwsh"
    assert create["env"] == {
        "RELEASE_TAG": "${{ github.ref_name }}",
        "RELEASE_REPOSITORY": "${{ github.repository }}",
    }
    assert 'gh release create "$env:RELEASE_TAG"' in script
    assert '--repo "$env:RELEASE_REPOSITORY"' in script
    assert "--verify-tag" in script
    assert '--title "DesktopCleaner $env:RELEASE_TAG"' in script
    assert "--generate-notes" in script
    tokens = shlex.split(script.replace("`\n", " "))
    assert [token for token in tokens if token.startswith("dist/")] == [
        "dist/DesktopCleaner.exe",
        "dist/DesktopCleaner.exe.sha256",
    ]
