"""Migration of older configuration shapes into the current schema."""

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

from desktop_tidy.domain.classification import canonical_key, is_inside
from desktop_tidy.domain.defaults import build_default_configuration
from desktop_tidy.domain.models import (
    AppearanceSettings,
    Configuration,
    DEFAULT_NEW_ITEM_PLACEMENT,
    InvalidConfiguration,
    ItemRef,
    _is_absolute_desktop_path,
    validate_configuration,
    validate_configuration_payload,
)

_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
CURRENT_SCHEMA_VERSION = 5


class UnsupportedConfigurationVersion(ValueError):
    """Raised when a configuration declares a schema this application cannot read."""

    def __init__(self, schema_version: object) -> None:
        super().__init__(f"unsupported configuration schema version: {schema_version}")
        self.schema_version = schema_version


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _copy_aside(path: Path, marker: str) -> Path:
    base = path.with_name(f"{path.stem}.{marker}-{_timestamp()}{path.suffix}")
    candidate = base
    counter = 1
    while candidate.exists():
        candidate = base.with_name(f"{base.stem}-{counter}{base.suffix}")
        counter += 1
    shutil.copy2(path, candidate)
    return candidate


def _atomic_save(path: Path, config: Configuration) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(config.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _desktop_path(payload: dict[str, Any]) -> str | None:
    raw = payload.get("desktop")
    if isinstance(raw, str) and raw.strip():
        path = raw.strip()
        if _is_absolute_desktop_path(path):
            return str(Path(path).expanduser())
    return None


def _legacy_ui(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("ui")
    return raw if isinstance(raw, dict) else {}


def _partitions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    ui = _legacy_ui(payload)
    raw = ui.get("partitions", payload.get("partitions", []))
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _legacy_startup_enabled(payload: dict[str, Any]) -> bool:
    ui = _legacy_ui(payload)
    return bool(ui.get("startup_enabled", payload.get("startup_enabled", False)))


def _valid_appearance(raw: dict[str, Any]) -> AppearanceSettings | None:
    color = str(raw.get("color", raw.get("background_color", ""))).strip()
    alpha = raw.get("alpha", raw.get("background_opacity"))
    try:
        opacity = float(alpha)
    except (TypeError, ValueError):
        return None
    if not _COLOR.fullmatch(color) or not 0.0 <= opacity <= 1.0:
        return None
    return AppearanceSettings(color, opacity)


def _legacy_appearance(payload: dict[str, Any]) -> AppearanceSettings | None:
    candidates = _partitions(payload)
    if not candidates:
        ui = _legacy_ui(payload)
        candidates = [ui] if ui else [payload]
    appearances = [_valid_appearance(candidate) for candidate in candidates]
    if not appearances or any(appearance is None for appearance in appearances):
        return None
    first = appearances[0]
    if all(appearance == first for appearance in appearances[1:]):
        return first
    return None


def _iter_item_paths(payload: dict[str, Any]) -> Iterable[str]:
    sources: list[object] = []
    for partition in _partitions(payload):
        raw_items = partition.get("items", [])
        if isinstance(raw_items, list):
            sources.extend(raw_items)
    for parent in (payload, _legacy_ui(payload)):
        raw_items = parent.get("items", [])
        if isinstance(raw_items, list):
            sources.extend(raw_items)
    for raw in sources:
        if isinstance(raw, dict):
            value = raw.get("path")
        else:
            value = raw
        if isinstance(value, str) and value.strip():
            yield value.strip()


def _file_url_target(path: Path) -> Path | None:
    if path.suffix.casefold() != ".url" or not path.is_file():
        return None
    try:
        lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    except OSError:
        return None
    raw_url = next(
        (line.split("=", 1)[1].strip() for line in lines if line.casefold().startswith("url=")),
        "",
    )
    parsed = urlparse(raw_url)
    if parsed.scheme.casefold() != "file":
        return None
    raw_path = url2pathname(unquote(parsed.path))
    if parsed.netloc and parsed.netloc.casefold() != "localhost":
        raw_path = f"//{parsed.netloc}{raw_path}"
    elif len(raw_path) >= 3 and raw_path[0] == "/" and raw_path[2] == ":":
        raw_path = raw_path[1:]
    return Path(raw_path).resolve()


def _external_paths(payload: dict[str, Any], desktop: Path) -> list[Path]:
    results: list[Path] = []
    seen: set[str] = set()
    for raw in _iter_item_paths(payload):
        path = Path(raw).expanduser()
        if not path.is_absolute():
            continue
        resolved = path.resolve()
        target = _file_url_target(resolved) if is_inside(resolved, desktop) else None
        candidate = target or resolved
        if is_inside(candidate, desktop):
            continue
        key = canonical_key(candidate)
        if key not in seen:
            seen.add(key)
            results.append(candidate)
    return results


def _migrate_legacy(payload: dict[str, Any]) -> Configuration:
    desktop_path = _desktop_path(payload)
    config = build_default_configuration(desktop_path)
    config.desktop.startup_enabled = _legacy_startup_enabled(payload)
    appearance = _legacy_appearance(payload)
    if appearance is not None:
        config.appearance_defaults = appearance
        config.panel_groups[0].appearance = AppearanceSettings.from_dict(appearance.to_dict())
    desktop = Path(config.desktop.path)
    config.external_refs = [
        ItemRef(
            id=f"external-{index}",
            source_kind="external",
            canonical_path=str(path),
            target_tab_id="tab-other",
        )
        for index, path in enumerate(_external_paths(payload, desktop), start=1)
    ]
    return config


def _assign_generated_panel_names(config: Configuration) -> None:
    for index, group in enumerate(config.panel_groups, start=1):
        if not group.name.strip():
            group.name = f"面板 {index}"


def _migrate_schema_three_to_four(config: Configuration) -> Configuration:
    config.schema_version = 4
    _assign_generated_panel_names(config)
    return config


def _migrate_schema_four_to_five(config: Configuration) -> Configuration:
    # 纯增量迁移:不改变任何已有行为,只补齐排序/分组/落位默认值。
    config.schema_version = 5
    config.manual_orders = {}
    config.item_groups = []
    config.new_item_placement = DEFAULT_NEW_ITEM_PLACEMENT
    return config


def load_or_migrate(path: Path) -> Configuration:
    path = Path(path)
    if not path.exists():
        return build_default_configuration()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("configuration root must be an object")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        _copy_aside(path, "corrupt")
        return build_default_configuration()
    if "schema_version" in payload:
        if payload["schema_version"] == CURRENT_SCHEMA_VERSION:
            try:
                validate_configuration_payload(payload, expected_schema_version=CURRENT_SCHEMA_VERSION)
                config = Configuration.from_dict(payload)
                validate_configuration(config, expected_schema_version=CURRENT_SCHEMA_VERSION)
                return config
            except (KeyError, TypeError, ValueError, InvalidConfiguration):
                _copy_aside(path, "corrupt")
                return build_default_configuration()
        if payload["schema_version"] == 4:
            try:
                validate_configuration_payload(payload, expected_schema_version=4)
                config = Configuration.from_dict(payload)
                validate_configuration(config, expected_schema_version=4)
            except (KeyError, TypeError, ValueError, InvalidConfiguration):
                _copy_aside(path, "corrupt")
                return build_default_configuration()
            _copy_aside(path, "pre-schema-v5")
            config = _migrate_schema_four_to_five(config)
            validate_configuration(config, expected_schema_version=CURRENT_SCHEMA_VERSION)
            _atomic_save(path, config)
            return config
        if payload["schema_version"] == 3:
            try:
                validate_configuration_payload(payload, expected_schema_version=3)
                config = Configuration.from_dict(payload)
                validate_configuration(config, expected_schema_version=3)
            except (KeyError, TypeError, ValueError, InvalidConfiguration):
                _copy_aside(path, "corrupt")
                return build_default_configuration()
            _copy_aside(path, "pre-schema-v4")
            config = _migrate_schema_three_to_four(config)
            config = _migrate_schema_four_to_five(config)
            validate_configuration(config, expected_schema_version=CURRENT_SCHEMA_VERSION)
            _atomic_save(path, config)
            return config
        if payload["schema_version"] == 2:
            try:
                validate_configuration_payload(payload, expected_schema_version=2)
                config = Configuration.from_dict(payload)
                validate_configuration(config, expected_schema_version=2)
            except (KeyError, TypeError, ValueError, InvalidConfiguration):
                _copy_aside(path, "corrupt")
                return build_default_configuration()
            _copy_aside(path, "pre-schema-v3")
            config.schema_version = 3
            for tab in config.panel_tabs:
                tab.content_kind = "items"
                tab.widget_type = ""
                tab.widget_settings = {}
            config = _migrate_schema_three_to_four(config)
            config = _migrate_schema_four_to_five(config)
            validate_configuration(config, expected_schema_version=CURRENT_SCHEMA_VERSION)
            _atomic_save(path, config)
            return config
        else:
            raise UnsupportedConfigurationVersion(payload["schema_version"])
    _copy_aside(path, "pre-qt-v1")
    config = _migrate_legacy(payload)
    config = _migrate_schema_three_to_four(config)
    config = _migrate_schema_four_to_five(config)
    _atomic_save(path, config)
    return config
