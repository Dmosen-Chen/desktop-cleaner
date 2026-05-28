"""Metadata-only domain commands for arranging visible desktop entrances."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import uuid

from .classification import canonical_key, is_inside
from .defaults import build_default_configuration
from .models import (
    ClassificationRule,
    Configuration,
    ItemRef,
    ManualOverride,
    PanelGeometry,
    PanelGroup,
    PanelTab,
)


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

    def _require_item_tab(self, tab_id: str) -> PanelTab:
        tab = self.tab(tab_id)
        if tab.content_kind != "items":
            raise ValueError(f"tab {tab_id} does not accept item entries")
        return tab

    def set_manual_override(self, path: Path, tab_id: str) -> None:
        self._require_item_tab(tab_id)
        key = canonical_key(path)
        self.config.manual_overrides = [
            entry for entry in self.config.manual_overrides if entry.canonical_path != key
        ]
        self.config.manual_overrides.append(ManualOverride(key, tab_id))

    def add_external_reference(self, path: Path, tab_id: str) -> ItemRef:
        self._require_item_tab(tab_id)
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
        self._require_item_tab(tab_id)
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

    def create_custom_classification_type(
        self,
        group_id: str,
        name: str,
        extensions: list[str] | None = None,
    ) -> tuple[PanelTab, ClassificationRule]:
        label = name.strip()
        if not label:
            raise ValueError("custom classification type name must not be empty")
        tab = self.add_tab(group_id, label)
        fallback_order = min(
            (rule.order for rule in self.config.rules if rule.matcher_kind == "fallback"),
            default=1000,
        )
        previous_order = max(
            (rule.order for rule in self.config.rules if rule.order < fallback_order),
            default=0,
        )
        rule = ClassificationRule(
            id=f"rule-custom-{uuid.uuid4().hex}",
            name=label,
            matcher_kind="extension",
            target_tab_id=tab.id,
            extensions=list(extensions or []),
            enabled=True,
            order=min(fallback_order - 1, previous_order + 10),
        )
        self.config.rules.append(rule)
        return tab, rule

    def delete_classification_rule(self, rule_id: str) -> bool:
        before = len(self.config.rules)
        self.config.rules = [rule for rule in self.config.rules if rule.id != rule_id]
        return len(self.config.rules) != before

    def add_widget_tab(
        self,
        group_id: str,
        widget_type: str,
        *,
        name: str | None = None,
        widget_settings: dict[str, object] | None = None,
    ) -> PanelTab:
        group = self.group(group_id)
        label = (name or self._default_widget_name(widget_type)).strip()
        if not label:
            raise ValueError("tab name must not be empty")
        tab = PanelTab(
            id=f"tab-{uuid.uuid4().hex}",
            group_id=group_id,
            name=label,
            order=len(group.tab_ids),
            category_role="custom",
            content_kind="widget",
            widget_type=widget_type,
            widget_settings=dict(widget_settings or {}),
        )
        self.config.panel_tabs.append(tab)
        group.tab_ids.append(tab.id)
        group.active_tab_id = tab.id
        return tab

    def add_widget_panel(
        self,
        widget_type: str,
        *,
        name: str | None = None,
        widget_settings: dict[str, object] | None = None,
    ) -> PanelGroup:
        group_id = f"group-{uuid.uuid4().hex}"
        tab_id = f"tab-{uuid.uuid4().hex}"
        label = (name or self._default_widget_name(widget_type)).strip()
        group = PanelGroup(
            id=group_id,
            screen_id=self.config.desktop.primary_screen_id or "primary",
            geometry=PanelGeometry(0.08, 0.08, 0.24, 0.22),
            tab_ids=[tab_id],
            active_tab_id=tab_id,
            appearance=deepcopy(self.config.appearance_defaults),
            locked=False,
            collapsed=False,
            name=label or self._default_widget_name(widget_type),
        )
        tab = PanelTab(
            id=tab_id,
            group_id=group_id,
            name=label or self._default_widget_name(widget_type),
            order=0,
            category_role="custom",
            content_kind="widget",
            widget_type=widget_type,
            widget_settings=dict(widget_settings or {}),
        )
        self.config.panel_groups.append(group)
        self.config.panel_tabs.append(tab)
        return group

    def add_item_panel(self, name: str = "") -> PanelGroup:
        group_id = f"group-{uuid.uuid4().hex}"
        tab_id = f"tab-{uuid.uuid4().hex}"
        group_name = name.strip() or self._next_panel_name()
        group = PanelGroup(
            id=group_id,
            screen_id=self.config.desktop.primary_screen_id or "primary",
            geometry=PanelGeometry(0.10, 0.10, 0.34, 0.34),
            tab_ids=[tab_id],
            active_tab_id=tab_id,
            appearance=deepcopy(self.config.appearance_defaults),
            locked=False,
            collapsed=False,
            name=group_name,
        )
        tab = PanelTab(
            id=tab_id,
            group_id=group_id,
            name="新标签",
            order=0,
            category_role="custom",
            content_kind="items",
        )
        self.config.panel_groups.append(group)
        self.config.panel_tabs.append(tab)
        return group

    def _default_widget_name(self, widget_type: str) -> str:
        if widget_type == "clock":
            return "时间"
        return widget_type or "功能"

    def _next_panel_name(self) -> str:
        used = {group.name for group in self.config.panel_groups}
        index = len(self.config.panel_groups) + 1
        while f"面板 {index}" in used:
            index += 1
        return f"面板 {index}"

    def rename_group(self, group_id: str, name: str) -> None:
        label = name.strip() or "未命名面板"
        self.group(group_id).name = label

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
        old_index = group.tab_ids.index(tab_id) if tab_id in group.tab_ids else 0
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
            if group.tab_ids:
                next_index = max(0, min(old_index - 1, len(group.tab_ids) - 1))
                group.active_tab_id = group.tab_ids[next_index]
            else:
                group.active_tab_id = ""
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

    def reorder_tab(self, tab_id: str, target_index: int) -> bool:
        tab = self.tab(tab_id)
        group = self.group(tab.group_id)
        if group.locked or tab_id not in group.tab_ids:
            return False
        current_index = group.tab_ids.index(tab_id)
        clamped = max(0, min(int(target_index), len(group.tab_ids) - 1))
        if current_index == clamped:
            return False
        group.tab_ids.pop(current_index)
        group.tab_ids.insert(clamped, tab_id)
        group.active_tab_id = tab_id
        self._reindex_tabs()
        return True

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
            name=tab.name,
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
