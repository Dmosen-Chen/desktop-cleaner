"""Platform-independent services available to the Qt application."""

from .desktop_index import DesktopIndex, IndexChanges, IndexedItem

__all__ = ["DesktopIndex", "IndexChanges", "IndexedItem"]
