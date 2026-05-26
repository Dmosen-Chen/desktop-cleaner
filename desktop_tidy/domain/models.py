"""Persisted entities for the Qt v1 desktop entrance manager."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AppearanceSettings:
    background_color: str = "#111111"
    background_opacity: float = 0.60

    def to_dict(self) -> dict[str, object]:
        return {
            "background_color": self.background_color,
            "background_opacity": self.background_opacity,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> AppearanceSettings:
        return cls(
            background_color=str(payload.get("background_color", "#111111")),
            background_opacity=float(payload.get("background_opacity", 0.60)),
        )


@dataclass
class PanelGeometry:
    rx: float = 0.04
    ry: float = 0.04
    rw: float = 0.72
    rh: float = 0.62

    def to_dict(self) -> dict[str, object]:
        return {"rx": self.rx, "ry": self.ry, "rw": self.rw, "rh": self.rh}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> PanelGeometry:
        return cls(
            rx=float(payload.get("rx", 0.04)),
            ry=float(payload.get("ry", 0.04)),
            rw=float(payload.get("rw", 0.72)),
            rh=float(payload.get("rh", 0.62)),
        )


@dataclass
class PanelGroup:
    id: str
    screen_id: str
    geometry: PanelGeometry
    tab_ids: list[str]
    active_tab_id: str
    appearance: AppearanceSettings
    locked: bool = False
    collapsed: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "screen_id": self.screen_id,
            "geometry": self.geometry.to_dict(),
            "tab_ids": list(self.tab_ids),
            "active_tab_id": self.active_tab_id,
            "appearance": self.appearance.to_dict(),
            "locked": self.locked,
            "collapsed": self.collapsed,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> PanelGroup:
        return cls(
            id=str(payload["id"]),
            screen_id=str(payload.get("screen_id", "primary")),
            geometry=PanelGeometry.from_dict(dict(payload.get("geometry", {}))),
            tab_ids=[str(tab_id) for tab_id in payload.get("tab_ids", [])],
            active_tab_id=str(payload.get("active_tab_id", "")),
            appearance=AppearanceSettings.from_dict(dict(payload.get("appearance", {}))),
            locked=bool(payload.get("locked", False)),
            collapsed=bool(payload.get("collapsed", False)),
        )


@dataclass
class PanelTab:
    id: str
    group_id: str
    name: str
    order: int
    category_role: str = "custom"

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "group_id": self.group_id,
            "name": self.name,
            "order": self.order,
            "category_role": self.category_role,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> PanelTab:
        return cls(
            id=str(payload["id"]),
            group_id=str(payload["group_id"]),
            name=str(payload["name"]),
            order=int(payload.get("order", 0)),
            category_role=str(payload.get("category_role", "custom")),
        )


@dataclass
class ItemRef:
    id: str
    source_kind: str
    canonical_path: str
    target_tab_id: str

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "source_kind": self.source_kind,
            "canonical_path": self.canonical_path,
            "target_tab_id": self.target_tab_id,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ItemRef:
        return cls(
            id=str(payload["id"]),
            source_kind=str(payload["source_kind"]),
            canonical_path=str(payload["canonical_path"]),
            target_tab_id=str(payload["target_tab_id"]),
        )


@dataclass
class ClassificationRule:
    id: str
    name: str
    matcher_kind: str
    target_tab_id: str
    extensions: list[str] = field(default_factory=list)
    enabled: bool = True
    order: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "matcher_kind": self.matcher_kind,
            "target_tab_id": self.target_tab_id,
            "extensions": list(self.extensions),
            "enabled": self.enabled,
            "order": self.order,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ClassificationRule:
        return cls(
            id=str(payload["id"]),
            name=str(payload["name"]),
            matcher_kind=str(payload["matcher_kind"]),
            target_tab_id=str(payload["target_tab_id"]),
            extensions=[str(extension) for extension in payload.get("extensions", [])],
            enabled=bool(payload.get("enabled", True)),
            order=int(payload.get("order", 0)),
        )


@dataclass
class ManualOverride:
    canonical_path: str
    target_tab_id: str

    def to_dict(self) -> dict[str, object]:
        return {
            "canonical_path": self.canonical_path,
            "target_tab_id": self.target_tab_id,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ManualOverride:
        return cls(
            canonical_path=str(payload["canonical_path"]),
            target_tab_id=str(payload["target_tab_id"]),
        )


@dataclass
class DesktopIntegrationState:
    path: str
    takeover_enabled: bool = False
    restore_required: bool = False
    explorer_icons_hidden: bool = False
    startup_enabled: bool = False
    primary_screen_id: str = "primary"

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "takeover_enabled": self.takeover_enabled,
            "restore_required": self.restore_required,
            "explorer_icons_hidden": self.explorer_icons_hidden,
            "startup_enabled": self.startup_enabled,
            "primary_screen_id": self.primary_screen_id,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DesktopIntegrationState:
        return cls(
            path=str(payload.get("path", "")),
            takeover_enabled=bool(payload.get("takeover_enabled", False)),
            restore_required=bool(payload.get("restore_required", False)),
            explorer_icons_hidden=bool(payload.get("explorer_icons_hidden", False)),
            startup_enabled=bool(payload.get("startup_enabled", False)),
            primary_screen_id=str(payload.get("primary_screen_id", "primary")),
        )


@dataclass
class Configuration:
    schema_version: int
    desktop: DesktopIntegrationState
    appearance_defaults: AppearanceSettings
    panel_groups: list[PanelGroup]
    panel_tabs: list[PanelTab]
    rules: list[ClassificationRule]
    manual_overrides: list[ManualOverride] = field(default_factory=list)
    external_refs: list[ItemRef] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "desktop": self.desktop.to_dict(),
            "appearance_defaults": self.appearance_defaults.to_dict(),
            "panel_groups": [group.to_dict() for group in self.panel_groups],
            "panel_tabs": [tab.to_dict() for tab in self.panel_tabs],
            "rules": [rule.to_dict() for rule in self.rules],
            "manual_overrides": [entry.to_dict() for entry in self.manual_overrides],
            "external_refs": [entry.to_dict() for entry in self.external_refs],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Configuration:
        return cls(
            schema_version=int(payload["schema_version"]),
            desktop=DesktopIntegrationState.from_dict(dict(payload["desktop"])),
            appearance_defaults=AppearanceSettings.from_dict(
                dict(payload.get("appearance_defaults", {}))
            ),
            panel_groups=[
                PanelGroup.from_dict(dict(item)) for item in payload.get("panel_groups", [])
            ],
            panel_tabs=[PanelTab.from_dict(dict(item)) for item in payload.get("panel_tabs", [])],
            rules=[
                ClassificationRule.from_dict(dict(item)) for item in payload.get("rules", [])
            ],
            manual_overrides=[
                ManualOverride.from_dict(dict(item))
                for item in payload.get("manual_overrides", [])
            ],
            external_refs=[
                ItemRef.from_dict(dict(item)) for item in payload.get("external_refs", [])
            ],
        )
