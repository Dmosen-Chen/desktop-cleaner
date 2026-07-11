"""Validate the inputs and outputs of a DesktopCleaner release."""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path
from typing import Sequence


_DEFAULT_VERSION_PATH = Path(__file__).resolve().parents[1] / "desktop_tidy" / "version.py"
_SIMPLE_SEMANTIC_VERSION = re.compile(
    r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
)


class ReleaseContractError(Exception):
    """Raised when release metadata or artifacts violate the release contract."""


def read_app_version(path: str | Path = _DEFAULT_VERSION_PATH) -> str:
    """Read a simple semantic APP_VERSION assignment without importing the app."""
    version_path = Path(path)
    source = version_path.read_text(encoding="utf-8")
    try:
        module = ast.parse(source, filename=str(version_path))
    except SyntaxError as exc:
        raise ReleaseContractError(
            f"Cannot parse APP_VERSION from {version_path}: {exc.msg}"
        ) from exc

    assignments = [
        node
        for node in module.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "APP_VERSION"
    ]
    if len(assignments) != 1:
        raise ReleaseContractError(
            f'{version_path} must contain exactly one simple APP_VERSION = "X.Y.Z" assignment'
        )

    value = assignments[0].value
    if (
        not isinstance(value, ast.Constant)
        or not isinstance(value.value, str)
        or _SIMPLE_SEMANTIC_VERSION.fullmatch(value.value) is None
    ):
        raise ReleaseContractError(
            f'{version_path} must contain a simple APP_VERSION = "X.Y.Z" assignment'
        )
    return value.value


def validate_release_tag(tag: str, version: str) -> None:
    """Require a release tag to exactly match the canonical application version."""
    expected = f"v{version}"
    if tag != expected:
        raise ReleaseContractError(
            f"Release tag {tag!r} does not match APP_VERSION {version!r}; expected {expected!r}"
        )


def validate_artifact(path: str | Path) -> None:
    """Require an artifact path to identify a non-empty file."""
    artifact_path = Path(path)
    try:
        stat = artifact_path.stat()
    except FileNotFoundError:
        raise ReleaseContractError(
            f"Release artifact does not exist: {artifact_path}"
        ) from None

    if not artifact_path.is_file():
        raise ReleaseContractError(f"Release artifact is not a file: {artifact_path}")
    if stat.st_size == 0:
        raise ReleaseContractError(f"Release artifact is empty: {artifact_path}")


def main(argv: Sequence[str] | None = None) -> int:
    """Validate optional release inputs and print the canonical version."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", help="release tag to validate")
    parser.add_argument("--artifact", type=Path, help="release artifact to validate")
    args = parser.parse_args(argv)

    try:
        version = read_app_version()
        if args.tag is not None:
            validate_release_tag(args.tag, version)
        if args.artifact is not None:
            validate_artifact(args.artifact)
    except (ReleaseContractError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
