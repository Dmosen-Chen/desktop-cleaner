"""Construction of the required first-run layout and classification rules."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from .models import (
    AppearanceSettings,
    ClassificationRule,
    Configuration,
    DesktopIntegrationState,
    PanelGeometry,
    PanelGroup,
    PanelTab,
)

DEFAULT_GROUP_ID = "group-default"
DEFAULT_APPEARANCE = AppearanceSettings("#111111", 0.60)
DEFAULT_TABS = (
    ("tab-folders", "文件夹", "folders"),
    ("tab-documents", "文档", "documents"),
    ("tab-images", "图片", "images"),
    ("tab-archives", "压缩包", "archives"),
    ("tab-apps", "应用", "apps"),
    ("tab-other", "其它", "other"),
)


def _default_rules() -> list[ClassificationRule]:
    return [
        ClassificationRule("rule-folders", "文件夹", "folder", "tab-folders", order=0),
        ClassificationRule(
            "rule-documents",
            "文档",
            "extension",
            "tab-documents",
            [
                ".pdf",
                ".doc",
                ".docx",
                ".rtf",
                ".odt",
                ".wps",
                ".xls",
                ".xlsx",
                ".xlsm",
                ".csv",
                ".ods",
                ".ppt",
                ".pptx",
                ".pptm",
                ".pps",
                ".ppsx",
                ".txt",
                ".md",
            ],
            order=10,
        ),
        ClassificationRule(
            "rule-images",
            "图片",
            "extension",
            "tab-images",
            [".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".svg"],
            order=20,
        ),
        ClassificationRule(
            "rule-archives",
            "压缩包",
            "extension",
            "tab-archives",
            [".zip", ".rar", ".7z", ".tar", ".gz", ".xz", ".bz2", ".iso"],
            order=30,
        ),
        ClassificationRule(
            "rule-apps",
            "应用",
            "extension",
            "tab-apps",
            [".lnk", ".url", ".exe", ".msi"],
            order=40,
        ),
        ClassificationRule("rule-other", "其它", "fallback", "tab-other", order=1000),
    ]


def build_default_configuration(desktop_path: str | Path | None = None) -> Configuration:
    if desktop_path is None:
        from desktop_tidy.services.desktop_location import resolve_desktop_path

        desktop_path = resolve_desktop_path()
    path = str(desktop_path)
    tabs = [
        PanelTab(tab_id, DEFAULT_GROUP_ID, name, index, category_role)
        for index, (tab_id, name, category_role) in enumerate(DEFAULT_TABS)
    ]
    group = PanelGroup(
        id=DEFAULT_GROUP_ID,
        screen_id="primary",
        geometry=PanelGeometry(),
        tab_ids=[tab.id for tab in tabs],
        active_tab_id=tabs[0].id,
        appearance=deepcopy(DEFAULT_APPEARANCE),
        locked=False,
        collapsed=False,
    )
    return Configuration(
        schema_version=2,
        desktop=DesktopIntegrationState(path=path, primary_screen_id="primary"),
        appearance_defaults=deepcopy(DEFAULT_APPEARANCE),
        panel_groups=[group],
        panel_tabs=tabs,
        rules=_default_rules(),
    )
