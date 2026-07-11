from __future__ import annotations

import builtins
from pathlib import Path

import pytest


def test_read_app_version_parses_simple_assignment_without_gui_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts.release_contract import read_app_version

    version_file = tmp_path / "version.py"
    version_file.write_text(
        'from desktop_tidy.application import DesktopApplication\n'
        'APP_VERSION = "1.2.3"\n',
        encoding="utf-8",
    )
    real_import = builtins.__import__

    def guarded_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "desktop_tidy.application":
            raise AssertionError("Qt application module was imported")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    assert read_app_version(version_file) == "1.2.3"


@pytest.mark.parametrize(
    "assignment",
    [
        'APP_VERSION = "1.2"',
        'APP_VERSION = "v1.2.3"',
        'APP_VERSION = "1.2.3.4"',
        'APP_VERSION = VERSION',
    ],
)
def test_read_app_version_rejects_non_simple_semantic_versions(
    tmp_path: Path, assignment: str
) -> None:
    from scripts.release_contract import ReleaseContractError, read_app_version

    version_file = tmp_path / "version.py"
    version_file.write_text(f"{assignment}\n", encoding="utf-8")

    with pytest.raises(ReleaseContractError, match="APP_VERSION"):
        read_app_version(version_file)


def test_validate_release_tag_accepts_matching_tag() -> None:
    from scripts.release_contract import validate_release_tag

    validate_release_tag("v1.2.3", "1.2.3")


def test_validate_release_tag_rejects_mismatch() -> None:
    from scripts.release_contract import ReleaseContractError, validate_release_tag

    with pytest.raises(ReleaseContractError, match="does not match"):
        validate_release_tag("v1.2.4", "1.2.3")


def test_validate_artifact_rejects_missing_file(tmp_path: Path) -> None:
    from scripts.release_contract import ReleaseContractError, validate_artifact

    with pytest.raises(ReleaseContractError, match="does not exist"):
        validate_artifact(tmp_path / "missing.exe")


def test_validate_artifact_rejects_empty_file(tmp_path: Path) -> None:
    from scripts.release_contract import ReleaseContractError, validate_artifact

    artifact = tmp_path / "DesktopCleaner.exe"
    artifact.touch()

    with pytest.raises(ReleaseContractError, match="empty"):
        validate_artifact(artifact)


def test_validate_artifact_accepts_non_empty_file(tmp_path: Path) -> None:
    from scripts.release_contract import validate_artifact

    artifact = tmp_path / "DesktopCleaner.exe"
    artifact.write_bytes(b"release artifact")

    validate_artifact(artifact)


def test_cli_prints_only_version_on_success(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from desktop_tidy.version import APP_VERSION
    from scripts.release_contract import main

    artifact = tmp_path / "DesktopCleaner.exe"
    artifact.write_bytes(b"release artifact")

    assert main(["--tag", f"v{APP_VERSION}", "--artifact", str(artifact)]) == 0
    captured = capsys.readouterr()
    assert captured.out == f"{APP_VERSION}\n"
    assert captured.err == ""


def test_cli_reports_contract_failure_to_stderr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from desktop_tidy.version import APP_VERSION
    from scripts.release_contract import main

    assert main(["--tag", "v0.0.0"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "does not match" in captured.err
    assert APP_VERSION in captured.err


def test_cli_reports_version_read_oserror_to_stderr(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import scripts.release_contract as release_contract

    def fail_to_read_version() -> str:
        raise OSError("version file is unreadable")

    monkeypatch.setattr(release_contract, "read_app_version", fail_to_read_version)

    assert release_contract.main([]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "version file is unreadable\n"


def test_package_version_uses_canonical_app_version() -> None:
    import desktop_tidy
    from desktop_tidy.version import APP_VERSION

    assert desktop_tidy.__version__ == APP_VERSION
