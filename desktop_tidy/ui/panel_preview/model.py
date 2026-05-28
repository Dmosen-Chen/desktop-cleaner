"""Preview view-models separated from painting and mouse handling."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from desktop_tidy.domain.models import Configuration, PanelGroup, PanelTab
from desktop_tidy.services.screens import ScreenInfo

PreviewInteractionMode = Literal["idle", "select", "drag-panel", "drag-tab"]


@dataclass
class PanelPreviewModel:
    """Render-only state for a desktop-layout preview surface."""

    config: Configuration
    screens: list[ScreenInfo]
    selected_group_id: str = ""
    selected_tab_id: str = ""
    interaction_mode: PreviewInteractionMode = "idle"
    focused_screen_id: str = ""
    groups: list[PanelGroup] = field(default_factory=list)
    tabs: list[PanelTab] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.groups:
            self.groups = list(self.config.panel_groups)
        if not self.tabs:
            self.tabs = list(self.config.panel_tabs)
