"""Shared item grouping helpers for the desktop item grid."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from desktop_tidy.services.desktop_index import IndexedItem
from desktop_tidy.services.logging_setup import get_logger


@dataclass
class GroupBlock:
    """Rendered item group: a display name plus resolved member paths."""

    group_id: str
    name: str
    members: list[Path] = field(default_factory=list)


@dataclass
class DisplaySlot:
    kind: str
    entry: IndexedItem | None = None
    group: GroupBlock | None = None


def debug_drag(enabled: bool, *parts: object) -> None:
    """Write optional drag diagnostics to the application log only."""
    if not enabled:
        return
    line = "[drag] " + " ".join(str(part) for part in parts)
    get_logger().info(line)
