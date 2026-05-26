"""Platform-independent services available to the Qt application."""

from .desktop_index import DesktopIndex, IndexChanges, IndexedItem
from .desktop_location import resolve_desktop_path, windows_known_folder_desktop

__all__ = [
    "DesktopIndex",
    "IndexChanges",
    "IndexedItem",
    "resolve_desktop_path",
    "windows_known_folder_desktop",
]
