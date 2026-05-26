"""Automatic classification and manual placement precedence."""

from __future__ import annotations

from pathlib import Path

from .models import Configuration


def canonical_key(path: Path) -> str:
    """Return the stable, case-insensitive key used for saved desktop overrides."""
    return str(Path(path).resolve()).casefold()


def is_inside(path: Path, parent: Path) -> bool:
    try:
        Path(path).resolve().relative_to(Path(parent).resolve())
        return True
    except ValueError:
        return False


def _existing_tab_ids(config: Configuration) -> set[str]:
    return {tab.id for tab in config.panel_tabs}


def _fallback_tab_id(config: Configuration) -> str:
    tab_ids = _existing_tab_ids(config)
    if "tab-other" in tab_ids:
        return "tab-other"
    if config.panel_groups and config.panel_groups[0].active_tab_id in tab_ids:
        return config.panel_groups[0].active_tab_id
    return config.panel_tabs[0].id if config.panel_tabs else "tab-other"


def classify_path(path: Path, config: Configuration) -> str:
    tab_ids = _existing_tab_ids(config)
    key = canonical_key(path)
    for override in config.manual_overrides:
        if override.canonical_path == key and override.target_tab_id in tab_ids:
            return override.target_tab_id

    fallback = _fallback_tab_id(config)
    for rule in sorted((entry for entry in config.rules if entry.enabled), key=lambda entry: entry.order):
        if rule.target_tab_id not in tab_ids:
            continue
        if rule.matcher_kind == "fallback":
            fallback = rule.target_tab_id
            continue
        if rule.matcher_kind == "folder" and Path(path).is_dir():
            return rule.target_tab_id
        if rule.matcher_kind == "extension" and Path(path).suffix.casefold() in {
            extension.casefold() for extension in rule.extensions
        }:
            return rule.target_tab_id
    return fallback
