"""Metadata-only domain commands for arranging visible desktop entrances."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import uuid

from .classification import canonical_key, is_inside
from .defaults import build_default_configuration
from .models import Configuration, ItemRef, ManualOverride, PanelGroup, PanelTab


class WorkspaceModel:
    def __init__(self, config: Configuration) -> None:
        self.config = config
        self.ensure_minimum_default_group()

    def group(self, group_id: str) -> PanelGroup:
        for group in self.config.panel_groups:
            if group.id == group_id:
                return group
        raise KeyError(f"unknown panel group: {group_id}")

    def tab(self, tab_id: str) -> PanelTab:
        for tab in self.config.panel_tabs:
            if tab.id == tab_id:
                return tab
        raise KeyError(f"unknown panel tab: {tab_id}")

    def set_manual_override(self, path: Path, tab_id: str) -> None:
        self.tab(tab_id)
        key = canonical_key(path)
        self.config.manual_overrides = [
            entry for entry in self.config.manual_overrides if entry.canonical_path != key
        ]
        self.config.manual_overrides.append(ManualOverride(key, tab_id))

    def add_external_reference(self, path: Path, tab_id: str) -> ItemRef:
        self.tab(tab_id)
        resolved = Path(path).resolve()
        key = canonical_key(resolved)
        existing = next(
            (
                entry
                for entry in self.config.external_refs
                if canonical_key(Path(entry.canonical_path)) == key
            ),
            None,
        )
        if existing is not None:
            existing.target_tab_id = tab_id
            existing.canonical_path = str(resolved)
            return existing
        reference = ItemRef(
            id=f"external-{uuid.uuid4().hex}",
            source_kind="external",
            canonical_path=str(resolved),
            target_tab_id=tab_id,
        )
        self.config.external_refs.append(reference)
        return reference

    def add_paths_to_tab(self, paths: list[Path], tab_id: str) -> None:
        self.tab(tab_id)
        desktop = Path(self.config.desktop.path)
        for path in paths:
            resolved = Path(path).resolve()
            if is_inside(resolved, desktop):
                self.set_manual_override(resolved, tab_id)
            else:
                self.add_external_reference(resolved, tab_id)

    def restore_auto_classification(self, path: Path) -> None:
        key = canonical_key(path)
        self.config.manual_overrides = [
            entry for entry in self.config.manual_overrides if entry.canonical_path != key
        ]

    def add_tab(self, group_id: str, name: str = "新标签", *, tab_id: str | None = None) -> PanelTab:
        group = self.group(group_id)
        label = name.strip()
        if not label:
            raise ValueError("tab name must not be empty")
        tab = PanelTab(
            id=tab_id or f"tab-{uuid.uuid4().hex}",
            group_id=group_id,
            name=label,
            order=len(group.tab_ids),
        )
        if any(existing.id == tab.id for existing in self.config.panel_tabs):
            raise ValueError(f"duplicate panel tab id: {tab.id}")
        self.config.panel_tabs.append(tab)
        group.tab_ids.append(tab.id)
        group.active_tab_id = tab.id
        return tab

    def rename_tab(self, tab_id: str, name: str) -> None:
        label = name.strip()
        if not label:
            raise ValueError("tab name must not be empty")
        self.tab(tab_id).name = label

    def delete_tab(self, tab_id: str) -> None:
        tab = self.tab(tab_id)
        group = self.group(tab.group_id)
        self.config.panel_tabs = [entry for entry in self.config.panel_tabs if entry.id != tab_id]
        group.tab_ids = [entry for entry in group.tab_ids if entry != tab_id]
        self.config.rules = [rule for rule in self.config.rules if rule.target_tab_id != tab_id]
        self.config.manual_overrides = [
            entry for entry in self.config.manual_overrides if entry.target_tab_id != tab_id
        ]
        self.config.external_refs = [
            entry for entry in self.config.external_refs if entry.target_tab_id != tab_id
        ]
        if group.active_tab_id == tab_id:
            group.active_tab_id = group.tab_ids[0] if group.tab_ids else ""
        if not group.tab_ids:
            self.config.panel_groups = [
                entry for entry in self.config.panel_groups if entry.id != group.id
            ]
        self.ensure_minimum_default_group()
        self._reindex_tabs()

    def delete_group(self, group_id: str) -> None:
        group = self.group(group_id)
        for tab_id in list(group.tab_ids):
            if any(entry.id == tab_id for entry in self.config.panel_tabs):
                self.delete_tab(tab_id)
        self.ensure_minimum_default_group()

    def ensure_minimum_default_group(self) -> PanelGroup:
        if self.config.panel_groups:
            return self.config.panel_groups[0]
        defaults = build_default_configuration(self.config.desktop.path)
        defaults.panel_groups[0].appearance = deepcopy(self.config.appearance_defaults)
        self.config.panel_groups = defaults.panel_groups
        self.config.panel_tabs = defaults.panel_tabs
        self.config.rules = defaults.rules
        return self.config.panel_groups[0]

    def _reindex_tabs(self) -> None:
        by_id = {tab.id: tab for tab in self.config.panel_tabs}
        for group in self.config.panel_groups:
            for order, tab_id in enumerate(group.tab_ids):
                if tab_id in by_id:
                    by_id[tab_id].order = order
