"""Persisted entities for the Qt v1 desktop entrance manager."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any


_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")


@dataclass
class AppearanceSettings:
    background_color: str = "#111111"
    background_opacity: float = 0.60
    item_icon_size: int = 48

    def to_dict(self) -> dict[str, object]:
        return {
            "background_color": self.background_color,
            "background_opacity": self.background_opacity,
            "item_icon_size": self.item_icon_size,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> AppearanceSettings:
        return cls(
            background_color=str(payload.get("background_color", "#111111")),
            background_opacity=float(payload.get("background_opacity", 0.60)),
            item_icon_size=int(payload.get("item_icon_size", 48)),
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
    name: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
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
            name=str(payload.get("name", "")),
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
    content_kind: str = "items"
    widget_type: str = ""
    widget_settings: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "group_id": self.group_id,
            "name": self.name,
            "order": self.order,
            "category_role": self.category_role,
            "content_kind": self.content_kind,
            "widget_type": self.widget_type,
            "widget_settings": dict(self.widget_settings),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> PanelTab:
        return cls(
            id=str(payload["id"]),
            group_id=str(payload["group_id"]),
            name=str(payload["name"]),
            order=int(payload.get("order", 0)),
            category_role=str(payload.get("category_role", "custom")),
            content_kind=str(payload.get("content_kind", "items")),
            widget_type=str(payload.get("widget_type", "")),
            widget_settings=dict(payload.get("widget_settings", {})),
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


class InvalidConfiguration(ValueError):
    """Raised when a configuration violates its structural contract."""


def _required_object(payload: dict[str, Any], key: str) -> dict[str, Any]:
    raw = payload.get(key)
    if not isinstance(raw, dict):
        raise InvalidConfiguration(f"{key} must be an object")
    return raw


def _required_string(payload: dict[str, Any], key: str, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise InvalidConfiguration(f"{label} must be a string")
    return value


def _required_text(payload: dict[str, Any], key: str, label: str) -> None:
    if not _required_string(payload, key, label).strip():
        raise InvalidConfiguration(f"{label} must not be blank")


def _required_bool(payload: dict[str, Any], key: str, label: str) -> None:
    if key not in payload or type(payload[key]) is not bool:
        raise InvalidConfiguration(f"{label} must be a boolean")


def _required_number(payload: dict[str, Any], key: str, label: str) -> None:
    if key not in payload or type(payload[key]) not in (int, float):
        raise InvalidConfiguration(f"{label} must be a number")


def _required_integer(payload: dict[str, Any], key: str, label: str) -> None:
    if key not in payload or type(payload[key]) is not int:
        raise InvalidConfiguration(f"{label} must be an integer")


def _required_list(payload: dict[str, Any], key: str) -> list[Any]:
    raw = payload.get(key)
    if not isinstance(raw, list):
        raise InvalidConfiguration(f"{key} must be a list")
    return raw


def _required_string_list(payload: dict[str, Any], key: str, label: str) -> list[str]:
    raw = _required_list(payload, key)
    if not all(isinstance(item, str) for item in raw):
        raise InvalidConfiguration(f"{label} must contain only strings")
    return raw


def _validate_appearance_payload(payload: dict[str, Any], label: str) -> None:
    _required_string(payload, "background_color", f"{label}.background_color")
    _required_number(payload, "background_opacity", f"{label}.background_opacity")
    if "item_icon_size" in payload:
        _required_integer(payload, "item_icon_size", f"{label}.item_icon_size")


def _is_absolute_desktop_path(path: str) -> bool:
    normalized = path.strip()
    if not normalized:
        return False
    if Path(normalized).is_absolute():
        return True
    return _WINDOWS_ABSOLUTE.match(normalized) is not None


def _reference_is_inside_desktop(canonical_path: str, desktop_path: str) -> bool:
    ref = Path(canonical_path)
    desktop = Path(desktop_path)
    if ref.is_absolute() and desktop.is_absolute():
        from desktop_tidy.domain.classification import is_inside

        try:
            return is_inside(ref, desktop)
        except OSError:
            pass
    ref_norm = str(canonical_path).casefold().replace("/", "\\").rstrip("\\")
    desktop_norm = str(desktop_path).casefold().replace("/", "\\").rstrip("\\")
    if not desktop_norm:
        return False
    if ref_norm == desktop_norm:
        return True
    return ref_norm.startswith(desktop_norm + "\\")


def _validate_desktop_path_value(path: str) -> None:
    if not path.strip():
        raise InvalidConfiguration("desktop.path must not be blank")
    if not _is_absolute_desktop_path(path):
        raise InvalidConfiguration("desktop.path must be an absolute path")


def validate_configuration_payload(
    payload: dict[str, Any],
    *,
    expected_schema_version: int = 4,
) -> None:
    """Validate the persisted schema shape before any tolerant conversion."""
    if (
        type(payload.get("schema_version")) is not int
        or payload["schema_version"] != expected_schema_version
    ):
        raise InvalidConfiguration(
            f"schema_version must be the integer {expected_schema_version}"
        )

    desktop = _required_object(payload, "desktop")
    _validate_desktop_path_value(_required_string(desktop, "path", "desktop.path"))
    for key in (
        "takeover_enabled",
        "restore_required",
        "explorer_icons_hidden",
        "startup_enabled",
    ):
        _required_bool(desktop, key, f"desktop.{key}")
    _required_text(desktop, "primary_screen_id", "desktop.primary_screen_id")

    appearance_defaults = _required_object(payload, "appearance_defaults")
    _validate_appearance_payload(appearance_defaults, "appearance_defaults")

    groups = _required_list(payload, "panel_groups")
    for index, raw_group in enumerate(groups):
        if not isinstance(raw_group, dict):
            raise InvalidConfiguration(f"panel_groups[{index}] must be an object")
        label = f"panel_groups[{index}]"
        _required_text(raw_group, "id", f"{label}.id")
        if expected_schema_version >= 4:
            _required_text(raw_group, "name", f"{label}.name")
        _required_text(raw_group, "screen_id", f"{label}.screen_id")
        geometry = _required_object(raw_group, "geometry")
        for key in ("rx", "ry", "rw", "rh"):
            _required_number(geometry, key, f"{label}.geometry.{key}")
        _required_string_list(raw_group, "tab_ids", f"{label}.tab_ids")
        _required_string(raw_group, "active_tab_id", f"{label}.active_tab_id")
        appearance = _required_object(raw_group, "appearance")
        _validate_appearance_payload(appearance, f"{label}.appearance")
        _required_bool(raw_group, "locked", f"{label}.locked")
        _required_bool(raw_group, "collapsed", f"{label}.collapsed")

    tabs = _required_list(payload, "panel_tabs")
    for index, raw_tab in enumerate(tabs):
        if not isinstance(raw_tab, dict):
            raise InvalidConfiguration(f"panel_tabs[{index}] must be an object")
        label = f"panel_tabs[{index}]"
        for key in ("id", "group_id", "name", "category_role"):
            _required_text(raw_tab, key, f"{label}.{key}")
        _required_integer(raw_tab, "order", f"{label}.order")
        if expected_schema_version >= 3:
            content_kind = _required_string(raw_tab, "content_kind", f"{label}.content_kind")
            if content_kind not in {"items", "widget"}:
                raise InvalidConfiguration(f"{label}.content_kind is invalid")
            _required_string(raw_tab, "widget_type", f"{label}.widget_type")
            widget_settings = raw_tab.get("widget_settings")
            if not isinstance(widget_settings, dict):
                raise InvalidConfiguration(f"{label}.widget_settings must be an object")
            if content_kind == "widget" and not str(raw_tab.get("widget_type", "")).strip():
                raise InvalidConfiguration(f"{label}.widget_type must not be blank")

    rules = _required_list(payload, "rules")
    for index, raw_rule in enumerate(rules):
        if not isinstance(raw_rule, dict):
            raise InvalidConfiguration(f"rules[{index}] must be an object")
        label = f"rules[{index}]"
        for key in ("id", "name", "matcher_kind"):
            _required_text(raw_rule, key, f"{label}.{key}")
        _required_string(raw_rule, "target_tab_id", f"{label}.target_tab_id")
        _required_string_list(raw_rule, "extensions", f"{label}.extensions")
        _required_bool(raw_rule, "enabled", f"{label}.enabled")
        _required_integer(raw_rule, "order", f"{label}.order")

    overrides = _required_list(payload, "manual_overrides")
    for index, raw_override in enumerate(overrides):
        if not isinstance(raw_override, dict):
            raise InvalidConfiguration(f"manual_overrides[{index}] must be an object")
        label = f"manual_overrides[{index}]"
        _required_text(raw_override, "canonical_path", f"{label}.canonical_path")
        _required_string(raw_override, "target_tab_id", f"{label}.target_tab_id")

    references = _required_list(payload, "external_refs")
    for index, raw_reference in enumerate(references):
        if not isinstance(raw_reference, dict):
            raise InvalidConfiguration(f"external_refs[{index}] must be an object")
        label = f"external_refs[{index}]"
        for key in ("id", "source_kind", "canonical_path"):
            _required_text(raw_reference, key, f"{label}.{key}")
        _required_string(raw_reference, "target_tab_id", f"{label}.target_tab_id")


def _validate_appearance(label: str, appearance: AppearanceSettings) -> None:
    if not _COLOR.fullmatch(appearance.background_color):
        raise InvalidConfiguration(f"{label} color must use #RRGGBB format")
    if not 0.0 <= appearance.background_opacity <= 1.0:
        raise InvalidConfiguration(f"{label} opacity must be between 0 and 1")
    if not 32 <= appearance.item_icon_size <= 96:
        raise InvalidConfiguration(f"{label} icon size must be between 32 and 96")


def _validate_geometry(group: PanelGroup) -> None:
    geometry = group.geometry
    if not 0.0 <= geometry.rx <= 1.0 or not 0.0 <= geometry.ry <= 1.0:
        raise InvalidConfiguration(f"panel group {group.id} position is outside the desktop")
    if not 0.0 < geometry.rw <= 1.0 or not 0.0 < geometry.rh <= 1.0:
        raise InvalidConfiguration(f"panel group {group.id} size is outside the desktop")
    if geometry.rx + geometry.rw > 1.0 or geometry.ry + geometry.rh > 1.0:
        raise InvalidConfiguration(f"panel group {group.id} extends outside the desktop")


def validate_configuration(
    config: Configuration,
    *,
    expected_schema_version: int = 4,
) -> None:
    """Validate the references and normalized values required by the current schema."""
    if config.schema_version != expected_schema_version:
        raise InvalidConfiguration(
            f"schema version {config.schema_version} is not version {expected_schema_version}"
        )
    _validate_desktop_path_value(config.desktop.path)
    if not config.panel_groups:
        raise InvalidConfiguration("configuration must contain at least one panel group")

    group_ids = {group.id for group in config.panel_groups}
    tab_ids = {tab.id for tab in config.panel_tabs}
    if len(group_ids) != len(config.panel_groups):
        raise InvalidConfiguration("panel group ids must be unique")
    if len(tab_ids) != len(config.panel_tabs):
        raise InvalidConfiguration("panel tab ids must be unique")

    tabs_by_id = {tab.id: tab for tab in config.panel_tabs}
    item_tab_ids: set[str] = set()
    for tab in config.panel_tabs:
        if tab.content_kind not in {"items", "widget"}:
            raise InvalidConfiguration(f"panel tab {tab.id} has an invalid content kind")
        if tab.content_kind == "widget":
            if not tab.widget_type.strip():
                raise InvalidConfiguration(f"panel tab {tab.id} widget type must not be blank")
            if not isinstance(tab.widget_settings, dict):
                raise InvalidConfiguration(f"panel tab {tab.id} widget settings must be a dict")
        else:
            item_tab_ids.add(tab.id)
    _validate_appearance("default appearance", config.appearance_defaults)
    listed_tab_ids: set[str] = set()
    for group in config.panel_groups:
        if expected_schema_version >= 4 and not group.name.strip():
            raise InvalidConfiguration(f"panel group {group.id} name must not be blank")
        if not group.tab_ids:
            raise InvalidConfiguration(f"panel group {group.id} must contain at least one tab")
        if len(set(group.tab_ids)) != len(group.tab_ids):
            raise InvalidConfiguration(f"panel group {group.id} contains duplicate tabs")
        if group.active_tab_id not in group.tab_ids:
            raise InvalidConfiguration(f"panel group {group.id} has an unknown active tab")
        for tab_id in group.tab_ids:
            tab = tabs_by_id.get(tab_id)
            if tab is None or tab.group_id != group.id:
                raise InvalidConfiguration(f"panel group {group.id} references an unknown tab")
            if tab_id in listed_tab_ids:
                raise InvalidConfiguration(f"panel tab {tab_id} belongs to multiple groups")
            listed_tab_ids.add(tab_id)
        _validate_geometry(group)
        _validate_appearance(f"panel group {group.id} appearance", group.appearance)

    if listed_tab_ids != tab_ids:
        raise InvalidConfiguration("configuration contains tabs outside panel groups")
    for rule in config.rules:
        valid_rule_targets = item_tab_ids if expected_schema_version >= 3 else tab_ids
        if rule.target_tab_id in valid_rule_targets:
            continue
        if not rule.enabled and rule.target_tab_id == "":
            continue
        if expected_schema_version >= 3 and rule.target_tab_id in tab_ids:
            raise InvalidConfiguration(f"classification rule {rule.id} targets a widget tab")
        raise InvalidConfiguration(f"classification rule {rule.id} targets an unknown tab")
    for override in config.manual_overrides:
        valid_item_targets = item_tab_ids if expected_schema_version >= 3 else tab_ids
        if override.target_tab_id not in valid_item_targets:
            raise InvalidConfiguration("manual override targets an unknown tab")
    for reference in config.external_refs:
        if reference.source_kind != "external":
            raise InvalidConfiguration(f"external reference {reference.id} has an invalid source kind")
        valid_item_targets = item_tab_ids if expected_schema_version >= 3 else tab_ids
        if reference.target_tab_id not in valid_item_targets:
            raise InvalidConfiguration(f"external reference {reference.id} targets an unknown tab")
        if not _is_absolute_desktop_path(reference.canonical_path):
            raise InvalidConfiguration(
                f"external reference {reference.id} must use an absolute path"
            )
        if _reference_is_inside_desktop(reference.canonical_path, config.desktop.path):
            raise InvalidConfiguration(
                f"external reference {reference.id} must point outside the desktop"
            )
