"""Stable identity keys for desktop shortcuts and duplicate detection."""

from __future__ import annotations

from pathlib import Path
import sys
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from .classification import canonical_key, is_inside


def item_identity_key(path: Path) -> str:
    """Return a key that treats duplicate shortcuts to the same target as one item."""
    resolved = Path(path).resolve()
    suffix = resolved.suffix.casefold()
    if suffix == ".lnk":
        target = _lnk_target(resolved)
        if target:
            return f"lnk:{target.casefold()}"
    if suffix == ".url":
        target = _url_target(resolved)
        if target:
            return f"url:{target.casefold()}"
    return f"path:{canonical_key(resolved)}"


def desktop_entry_rank(path: Path, *, primary_desktop: Path) -> int:
    """Lower rank wins when two entries share the same identity key."""
    resolved = Path(path).resolve()
    if is_inside(resolved, Path(primary_desktop)):
        return 0
    return 1


def _lnk_target(path: Path) -> str:
    if sys.platform != "win32" or not path.is_file():
        return ""
    try:
        import win32com.client  # type: ignore[import-not-found]
    except Exception:
        return ""
    try:
        shortcut = win32com.client.Dispatch("WScript.Shell").CreateShortcut(str(path))
    except Exception:
        return ""
    target = str(getattr(shortcut, "TargetPath", "") or "").strip()
    arguments = str(getattr(shortcut, "Arguments", "") or "").strip()
    if not target:
        return ""
    if arguments:
        return f"{target} {arguments}".strip()
    return target


def _url_target(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return ""
    raw_url = next(
        (line.split("=", 1)[1].strip() for line in lines if line.casefold().startswith("url=")),
        "",
    )
    if not raw_url:
        return ""
    parsed = urlparse(raw_url)
    if parsed.scheme.casefold() == "file":
        raw_path = url2pathname(unquote(parsed.path))
        if parsed.netloc and parsed.netloc.casefold() != "localhost":
            raw_path = f"//{parsed.netloc}{raw_path}"
        elif len(raw_path) >= 3 and raw_path[0] == "/" and raw_path[2] == ":":
            raw_path = raw_path[1:]
        return str(Path(raw_path).resolve())
    return raw_url.casefold()
