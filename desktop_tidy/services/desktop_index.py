"""Read-only snapshots and differences for the configured desktop directory."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, Signal

from desktop_tidy.domain.classification import canonical_key

FILE_ATTRIBUTE_HIDDEN = 0x2
FILE_ATTRIBUTE_SYSTEM = 0x4
_IGNORED_ATTRIBUTES = FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM


@dataclass(frozen=True)
class IndexedItem:
    path: Path


@dataclass(frozen=True)
class IndexChanges:
    current: list[IndexedItem]
    added: list[IndexedItem]
    removed: list[IndexedItem]


def should_display(entry: Path) -> bool:
    lowered = entry.name.casefold()
    if lowered == "desktop.ini" or lowered.startswith("~$"):
        return False
    try:
        attributes = getattr(entry.stat(), "st_file_attributes", 0)
    except OSError:
        return False
    return not bool(attributes & _IGNORED_ATTRIBUTES)


class DesktopIndex:
    def __init__(self, desktop: Path, *, extra_desktops: list[Path] | None = None) -> None:
        self.desktop = Path(desktop)
        # 额外桌面目录(通常是公共桌面 C:\Users\Public\Desktop),
        # Explorer 会把它合并进桌面视图,我们也要一起显示。
        self.extra_desktops = [Path(entry) for entry in (extra_desktops or [])]
        self._last: dict[str, IndexedItem] = {}

    def directories(self) -> list[Path]:
        seen: set[str] = set()
        result: list[Path] = []
        for directory in [self.desktop, *self.extra_desktops]:
            key = str(directory).casefold()
            if key not in seen:
                seen.add(key)
                result.append(directory)
        return result

    def scan(self) -> list[IndexedItem]:
        items: list[IndexedItem] = []
        seen: set[str] = set()
        for directory in self.directories():
            if not directory.is_dir():
                continue
            try:
                entries = sorted(directory.iterdir(), key=lambda entry: entry.name.casefold())
            except OSError:
                continue
            for entry in entries:
                if not should_display(entry):
                    continue
                resolved = entry.resolve()
                key = canonical_key(resolved)
                if key in seen:
                    continue
                seen.add(key)
                items.append(IndexedItem(resolved))
        return items

    def rescan(self) -> IndexChanges:
        current = {canonical_key(item.path): item for item in self.scan()}
        changes = IndexChanges(
            current=list(current.values()),
            added=[item for key, item in current.items() if key not in self._last],
            removed=[item for key, item in self._last.items() if key not in current],
        )
        self._last = current
        return changes


class DesktopWatcher(QObject):
    """Emits rescan results when the indexed desktop directory changes."""

    changed = Signal(object)

    def __init__(self, index: DesktopIndex, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._index = index
        self._watcher = QFileSystemWatcher(self)
        for directory in self._index.directories():
            if directory.is_dir():
                self._watcher.addPath(str(directory))
        self._watcher.directoryChanged.connect(self._on_directory_changed)

    def _on_directory_changed(self, _path: str) -> None:
        self.changed.emit(self._index.rescan())
