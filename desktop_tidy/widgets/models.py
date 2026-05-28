"""Models and protocols for built-in function panels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from PySide6.QtWidgets import QWidget


@dataclass(frozen=True)
class WidgetVisualPreset:
    preset_id: str = "default"
    accent_color: str = "#d99abd"
    background: str = "#51344a"
    foreground: str = "#ffe4f0"
    secondary_foreground: str = "rgba(255,255,255,0.82)"
    card_background: str = "rgba(34,31,40,0.90)"
    recommended_width: int = 320
    recommended_height: int = 190
    min_width: int = 260
    min_height: int = 130
    max_width: int = 340
    max_height: int = 190


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
    visual_preset: str = "default"
    preview_background: str = "#51344a"
    preview_foreground: str = "#ffe4f0"
    preview_secondary_foreground: str = "rgba(255,255,255,0.82)"
    visual: WidgetVisualPreset | None = None

    def __post_init__(self) -> None:
        visual = self.visual or WidgetVisualPreset(
            preset_id=self.visual_preset,
            accent_color=self.accent_color,
            background=self.preview_background,
            foreground=self.preview_foreground,
            secondary_foreground=self.preview_secondary_foreground,
            recommended_width=self.default_width,
            recommended_height=self.default_height,
            min_width=self.min_width,
            min_height=self.min_height,
            max_width=self.max_width,
            max_height=self.max_height,
        )
        object.__setattr__(self, "visual", visual)
        object.__setattr__(self, "accent_color", visual.accent_color)
        object.__setattr__(self, "visual_preset", visual.preset_id)
        object.__setattr__(self, "preview_background", visual.background)
        object.__setattr__(self, "preview_foreground", visual.foreground)
        object.__setattr__(
            self,
            "preview_secondary_foreground",
            visual.secondary_foreground,
        )
        object.__setattr__(self, "default_width", visual.recommended_width)
        object.__setattr__(self, "default_height", visual.recommended_height)
        object.__setattr__(self, "min_width", visual.min_width)
        object.__setattr__(self, "min_height", visual.min_height)
        object.__setattr__(self, "max_width", visual.max_width)
        object.__setattr__(self, "max_height", visual.max_height)


class WidgetPlugin(Protocol):
    id: str
    display_name: str

    def definition(self) -> WidgetDefinition:
        ...

    def default_settings(self) -> dict[str, object]:
        ...

    def create_widget(self, settings: dict[str, object]) -> QWidget:
        ...
