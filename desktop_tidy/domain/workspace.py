"""Metadata-only domain commands for arranging visible desktop entrances."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import uuid

from .classification import canonical_key, is_inside
from .defaults import build_default_configuration
from .models import Configuration, ItemRef, ManualOverride, PanelGeometry, PanelGroup, PanelTab


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

    def _pending_organize_tab_id(self) -> str:
        for tab in self.config.panel_tabs:
            if tab.category_role == "other":
                return tab.id
        for tab in self.config.panel_tabs:
            if tab.id == "tab-other":
                return tab.id
        if self.config.panel_groups:
            active = self.config.panel_groups[0].active_tab_id
            if any(tab.id == active for tab in self.config.panel_tabs):
                return active
        return self.config.panel_tabs[0].id

    def mark_desktop_items_pending_organize(self, paths: list[Path]) -> None:
        tab_id = self._pending_organize_tab_id()
        desktop = Path(self.config.desktop.path)
        for path in paths:
            resolved = Path(path).resolve()
            if is_inside(resolved, desktop):
                self.set_manual_override(resolved, tab_id)

    def organize_by_rules(self) -> None:
        """Return desktop-owned items to automatic classification without touching files."""
        self.config.manual_overrides = []

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
        label = name.strip() or "未命名面板"
        self.tab(tab_id).name = label

    def can_delete_tab(self, tab_id: str) -> bool:
        self.tab(tab_id)
        return len(self.config.panel_tabs) > 1

    def delete_tab(self, tab_id: str) -> bool:
        if not self.can_delete_tab(tab_id):
            return False
        tab = self.tab(tab_id)
        group = self.group(tab.group_id)
        self.config.panel_tabs = [entry for entry in self.config.panel_tabs if entry.id != tab_id]
        group.tab_ids = [entry for entry in group.tab_ids if entry != tab_id]
        for rule in self.config.rules:
            if rule.target_tab_id == tab_id:
                rule.enabled = False
                rule.target_tab_id = ""
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
        return True

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
        existing_rule_ids = {rule.id for rule in self.config.rules}
        missing_default_rules = [
            rule for rule in defaults.rules if rule.id not in existing_rule_ids
        ]
        defaults.panel_groups[0].appearance = deepcopy(self.config.appearance_defaults)
        self.config.panel_groups = defaults.panel_groups
        self.config.panel_tabs = defaults.panel_tabs
        self.config.rules.extend(missing_default_rules)
        return self.config.panel_groups[0]

    def _reindex_tabs(self) -> None:
        by_id = {tab.id: tab for tab in self.config.panel_tabs}
        for group in self.config.panel_groups:
            for order, tab_id in enumerate(group.tab_ids):
                if tab_id in by_id:
                    by_id[tab_id].order = order

    def detach_tab(self, tab_id: str, geometry: PanelGeometry) -> PanelGroup:
        tab = self.tab(tab_id)
        source = self.group(tab.group_id)
        if source.locked:
            raise ValueError(f"panel group {source.id} is locked")
        if len(source.tab_ids) <= 1:
            raise ValueError(f"panel group {source.id} must retain at least one tab")
        source.tab_ids = [entry for entry in source.tab_ids if entry != tab_id]
        if source.active_tab_id == tab_id:
            source.active_tab_id = source.tab_ids[0]
        detached = PanelGroup(
            id=f"group-{uuid.uuid4().hex}",
            screen_id=source.screen_id,
            geometry=deepcopy(geometry),
            tab_ids=[tab_id],
            active_tab_id=tab_id,
            appearance=deepcopy(self.config.appearance_defaults),
        )
        tab.group_id = detached.id
        self.config.panel_groups.append(detached)
        self._reindex_tabs()
        return detached

    def merge_group_at_point(
        self,
        source_group_id: str,
        *,
        point: tuple[int, int] | tuple[float, float],
        bounds: dict[str, tuple[int, int, int, int] | tuple[float, float, float, float]],
    ) -> bool:
        source = self.group(source_group_id)
        if source.locked:
            return False
        px, py = point
        target_id = ""
        for group_id, rect in bounds.items():
            if group_id == source_group_id:
                continue
            x, y, width, height = rect
            if x <= px < x + width and y <= py < y + height:
                target_id = group_id
                break
        if not target_id:
            return False
        target = self.group(target_id)
        if target.locked:
            return False
        for tab_id in list(source.tab_ids):
            tab = self.tab(tab_id)
            tab.group_id = target_id
            target.tab_ids.append(tab_id)
        target.active_tab_id = source.active_tab_id
        self.config.panel_groups = [
            group for group in self.config.panel_groups if group.id != source_group_id
        ]
        self._reindex_tabs()
        return True
