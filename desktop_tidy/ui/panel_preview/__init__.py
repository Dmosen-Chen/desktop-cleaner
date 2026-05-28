"""Shared panel preview package for settings surfaces."""

from desktop_tidy.ui.panel_preview.model import PanelPreviewModel
from desktop_tidy.ui.panel_preview.renderer import (
    PanelPreviewRenderer,
    detail_tab_preview_rects,
    group_preview_rect,
    layout_preview_tab_names,
    map_preview_rect,
    render_layout_preview_pixmap,
    safe_screen_infos,
    screen_preview_rects,
    screen_z_order,
    selected_panel_detail_rect,
    tab_preview_rects,
)
from desktop_tidy.ui.panel_preview.widget import PanelPreviewWidget

__all__ = [
    "PanelPreviewModel",
    "PanelPreviewRenderer",
    "PanelPreviewWidget",
    "detail_tab_preview_rects",
    "group_preview_rect",
    "layout_preview_tab_names",
    "map_preview_rect",
    "render_layout_preview_pixmap",
    "safe_screen_infos",
    "screen_preview_rects",
    "screen_z_order",
    "selected_panel_detail_rect",
    "tab_preview_rects",
]
