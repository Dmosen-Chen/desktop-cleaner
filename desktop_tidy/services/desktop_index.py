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
    def __init__(self, desktop: Path) -> None:
        self.desktop = Path(desktop)
        self._last: dict[str, IndexedItem] = {}

    def scan(self) -> list[IndexedItem]:
        if not self.desktop.is_dir():
            return []
        try:
            entries = sorted(self.desktop.iterdir(), key=lambda entry: entry.name.casefold())
        except OSError:
            return []
        return [
            IndexedItem(entry.resolve())
            for entry in entries
            if should_display(entry)
        ]

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
        desktop_path = str(self._index.desktop)
        if self._index.desktop.is_dir():
            self._watcher.addPath(desktop_path)
        self._watcher.directoryChanged.connect(self._on_directory_changed)

    def _on_directory_changed(self, _path: str) -> None:
        self.changed.emit(self._index.rescan())
