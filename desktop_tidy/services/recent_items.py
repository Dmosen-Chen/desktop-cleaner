"""Local recent-entry tracking for items opened through DesktopCleaner."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

ShortcutResolver = Callable[[Path], Path | None]


@dataclass(frozen=True)
class RecentItemRecord:
    name: str
    path: str
    kind: str
    opened_at: str

    def to_json(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_json(cls, payload: Any) -> "RecentItemRecord | None":
        if not isinstance(payload, dict):
            return None
        name = payload.get("name")
        path = payload.get("path")
        kind = payload.get("kind")
        opened_at = payload.get("opened_at")
        if not all(isinstance(value, str) and value for value in (name, path, kind, opened_at)):
            return None
        return cls(name=name, path=str(Path(path).resolve()), kind=kind, opened_at=opened_at)


def default_windows_recent_dir() -> Path | None:
    """Return the Windows shell Recent folder when available."""

    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    recent = Path(appdata) / "Microsoft" / "Windows" / "Recent"
    return recent if recent.is_dir() else None


def resolve_shortcut_target(path: Path) -> Path | None:
    """Best-effort target resolution for Windows .lnk and .url recent items."""

    suffix = path.suffix.casefold()
    if suffix == ".url":
        return _url_file_target(path)
    if suffix != ".lnk" or sys.platform != "win32" or not path.is_file():
        return None
    try:
        import win32com.client  # type: ignore[import-not-found]
    except Exception:
        return None
    try:
        shortcut = win32com.client.Dispatch("WScript.Shell").CreateShortcut(str(path))
    except Exception:
        return None
    target = str(getattr(shortcut, "TargetPath", "") or "").strip()
    if not target:
        return None
    return Path(target).resolve()


def _url_file_target(path: Path) -> Path | None:
    if not path.is_file():
        return None
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return None
    raw_url = next(
        (line.split("=", 1)[1].strip() for line in lines if line.casefold().startswith("url=")),
        "",
    )
    if not raw_url:
        return None
    parsed = urlparse(raw_url)
    if parsed.scheme.casefold() != "file":
        return None
    raw_path = url2pathname(unquote(parsed.path))
    if parsed.netloc and parsed.netloc.casefold() != "localhost":
        raw_path = f"//{parsed.netloc}{raw_path}"
    elif len(raw_path) >= 3 and raw_path[0] == "/" and raw_path[2] == ":":
        raw_path = raw_path[1:]
    return Path(raw_path).resolve()


class RecentItemsStore:
    """Persist app-opened items and expose Windows Recent items for Home."""

    def __init__(
        self,
        path: Path,
        *,
        limit: int = 20,
        windows_recent_dir: Path | None = None,
        shortcut_resolver: ShortcutResolver | None = None,
    ) -> None:
        self.path = Path(path)
        self.limit = max(1, int(limit))
        self.windows_recent_dir = Path(windows_recent_dir) if windows_recent_dir else None
        self.shortcut_resolver = shortcut_resolver or resolve_shortcut_target

    def load(self) -> list[RecentItemRecord]:
        if not self.path.is_file():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return []
        if not isinstance(raw, list):
            return []
        records: list[RecentItemRecord] = []
        for payload in raw:
            record = RecentItemRecord.from_json(payload)
            if record is not None:
                records.append(record)
        return records[: self.limit]

    def record(self, path: Path) -> None:
        resolved = Path(path).resolve()
        record = RecentItemRecord(
            name=resolved.name,
            path=str(resolved),
            kind=self._kind_for_path(resolved),
            opened_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        current = [
            entry
            for entry in self.load()
            if entry.path.casefold() != record.path.casefold()
        ]
        self._save([record, *current][: self.limit])

    def clear(self) -> None:
        """Remove DesktopCleaner-owned recent records without touching Windows Recent."""

        try:
            self.path.unlink()
        except FileNotFoundError:
            return

    def snapshot(self, *, limit: int | None = None) -> list[dict[str, str]]:
        count = self.limit if limit is None else max(0, int(limit))
        return [
            {
                "name": entry.name,
                "path": str(entry.path),
                "kind": entry.kind,
                "source": "app",
            }
            for entry in self.load()[:count]
        ]

    def windows_recent_snapshot(self, *, limit: int | None = None) -> list[dict[str, str]]:
        count = self.limit if limit is None else max(0, int(limit))
        if count <= 0 or self.windows_recent_dir is None or not self.windows_recent_dir.is_dir():
            return []

        candidates: list[tuple[float, dict[str, str]]] = []
        for shortcut in self.windows_recent_dir.iterdir():
            if shortcut.suffix.casefold() not in {".lnk", ".url"} or not shortcut.is_file():
                continue
            try:
                modified = shortcut.stat().st_mtime
            except OSError:
                continue
            try:
                target = self.shortcut_resolver(shortcut)
            except Exception:
                target = None
            resolved = Path(target).resolve() if target is not None else shortcut.resolve()
            candidates.append(
                (
                    modified,
                    {
                        "name": shortcut.stem or resolved.name,
                        "path": str(resolved),
                        "kind": self._kind_for_path(resolved),
                        "source": "windows",
                    },
                )
            )

        candidates.sort(key=lambda item: item[0], reverse=True)
        return [payload for _, payload in candidates[:count]]

    def dashboard_snapshot(self, *, limit: int | None = None) -> list[dict[str, str]]:
        return self.windows_recent_snapshot(limit=limit)

    def _save(self, records: list[RecentItemRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(
            json.dumps([record.to_json() for record in records], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(self.path)

    def _kind_for_path(self, path: Path) -> str:
        if path.is_dir():
            return "folder"
        if path.is_file():
            return "file"
        return "missing"
