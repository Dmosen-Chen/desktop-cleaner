"""Models and protocols for built-in function panels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from PySide6.QtWidgets import QWidget


@dataclass(frozen=True)
class WidgetDefinition:
    id: str
    display_name: str
    description: str
    preview_title: str
    preview_body: str
    default_width: int = 320
    default_height: int = 190
    min_width: int = 260
    min_height: int = 130
    max_width: int = 340
    max_height: int = 190
    accent_color: str = "#d99abd"


class WidgetPlugin(Protocol):
    id: str
    display_name: str

    def definition(self) -> WidgetDefinition:
        ...

    def default_settings(self) -> dict[str, object]:
        ...

    def create_widget(self, settings: dict[str, object]) -> QWidget:
        ...
