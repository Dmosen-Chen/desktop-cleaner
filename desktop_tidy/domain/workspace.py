"""Metadata-only domain commands for arranging visible desktop entrances."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import uuid

from desktop_tidy.domain.classification import canonical_key, is_inside
from .shortcut_identity import desktop_entry_rank, item_identity_key
from .defaults import build_default_configuration
from .models import (
    NEW_ITEM_PLACEMENTS,
    ClassificationRule,
    Configuration,
    ItemGroup,
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
        self.config.external_refs = [
            ref for ref in self.config.external_refs if ref.canonical_path != key
        ]

    def move_paths_to_tab(
        self,
        paths: list[Path],
        tab_id: str,
        *,
        desktop_roots: list[Path] | None = None,
    ) -> None:
        """把图标归类到目标标签,并清理其它标签里的顺序/分组元数据。"""
        self._require_item_tab(tab_id)
        keys = {canonical_key(path) for path in paths}
        if keys:
            for path in paths:
                self.remove_items_from_group([path])
            for tid, order in list(self.config.manual_orders.items()):
                if tid == tab_id:
                    continue
                filtered = [entry for entry in order if entry not in keys]
                if filtered:
                    self.config.manual_orders[tid] = filtered
                else:
                    self.config.manual_orders.pop(tid, None)
        self.add_paths_to_tab(paths, tab_id, desktop_roots=desktop_roots)
        self.repair_metadata(desktop_roots=desktop_roots)

    def set_new_item_placement(self, placement: str) -> None:
        if placement not in NEW_ITEM_PLACEMENTS:
            raise ValueError(f"unknown new item placement: {placement}")
        self.config.new_item_placement = placement

    def reorder_tab_items(self, tab_id: str, ordered_paths: list[Path]) -> None:
        """记录标签内的手动显示顺序(仅元数据,不动真实文件)。

        传入当前可见项目的目标顺序;空列表表示清除手动顺序、回到自动排序。
        分组文件夹用组内第一个成员的路径作为占位。
        """
        self._require_item_tab(tab_id)
        keys: list[str] = []
        seen: set[str] = set()
        for path in ordered_paths:
            key = canonical_key(path)
            if key not in seen:
                seen.add(key)
                keys.append(key)
        if keys:
            self.config.manual_orders[tab_id] = keys
            self._collapse_manual_order_groups(tab_id)
        else:
            self.config.manual_orders.pop(tab_id, None)

    def _collapse_manual_order_groups(self, tab_id: str) -> None:
        order = self.config.manual_orders.get(tab_id)
        if not order:
            return
        anchor_by_group: dict[str, str] = {}
        member_to_group: dict[str, str] = {}
        for group in self.config.item_groups:
            if group.tab_id != tab_id or not group.member_paths:
                continue
            anchor_by_group[group.id] = group.member_paths[0]
            for member_key in group.member_paths:
                member_to_group[member_key] = group.id
        collapsed: list[str] = []
        seen_groups: set[str] = set()
        for key in order:
            group_id = member_to_group.get(key)
            if group_id is not None:
                if group_id in seen_groups:
                    continue
                seen_groups.add(group_id)
                collapsed.append(anchor_by_group[group_id])
                continue
            collapsed.append(key)
        self.config.manual_orders[tab_id] = collapsed

    def clear_manual_order(self, tab_id: str) -> None:
        self.config.manual_orders.pop(tab_id, None)

    # ----- 分组(小组)操作:全部仅改显示层元数据,绝不移动/删除真实文件 -----

    def _item_group(self, group_id: str) -> ItemGroup:
        for group in self.config.item_groups:
            if group.id == group_id:
                return group
        raise KeyError(f"unknown item group: {group_id}")

    def _prune_empty_item_groups(self) -> None:
        self.config.item_groups = [
            group for group in self.config.item_groups if group.member_paths
        ]

    def _dissolve_singleton_item_groups(self) -> None:
        """组内只剩 1 个图标时自动解散(无需保留分组壳)。"""
        self.config.item_groups = [
            group for group in self.config.item_groups if len(group.member_paths) >= 2
        ]

    def _prune_item_groups_after_member_change(self) -> None:
        self._prune_empty_item_groups()
        self._dissolve_singleton_item_groups()

    def _detach_keys_from_groups(
        self, tab_id: str, keys: set[str], *, except_group_id: str | None = None
    ) -> None:
        if not keys:
            return
        for group in self.config.item_groups:
            if group.tab_id != tab_id or group.id == except_group_id:
                continue
            group.member_paths = [k for k in group.member_paths if k not in keys]

    @staticmethod
    def _ordered_keys(paths: list[Path]) -> list[str]:
        keys: list[str] = []
        seen: set[str] = set()
        for path in paths:
            key = canonical_key(path)
            if key not in seen:
                seen.add(key)
                keys.append(key)
        return keys

    def create_item_group(
        self, tab_id: str, member_paths: list[Path], name: str = "新建分组"
    ) -> ItemGroup:
        self._require_item_tab(tab_id)
        keys = self._ordered_keys(member_paths)
        self._detach_keys_from_groups(tab_id, set(keys))
        order = 1 + max(
            (group.order for group in self.config.item_groups if group.tab_id == tab_id),
            default=-1,
        )
        group = ItemGroup(
            id=f"item-group-{uuid.uuid4().hex}",
            tab_id=tab_id,
            name=name.strip() or "新建分组",
            order=order,
            member_paths=keys,
        )
        self.config.item_groups.append(group)
        self._prune_empty_item_groups()
        self._collapse_manual_order_groups(tab_id)
        return group

    def add_items_to_group(self, group_id: str, member_paths: list[Path]) -> ItemGroup:
        group = self._item_group(group_id)
        keys = self._ordered_keys(member_paths)
        self._detach_keys_from_groups(group.tab_id, set(keys), except_group_id=group.id)
        for key in keys:
            if key not in group.member_paths:
                group.member_paths.append(key)
        self._prune_item_groups_after_member_change()
        self._collapse_manual_order_groups(group.tab_id)
        return group

    def remove_items_from_group(
        self, member_paths: list[Path], *, tab_id: str | None = None
    ) -> None:
        keys = set(self._ordered_keys(member_paths))
        affected_tabs: set[str] = set()
        for group in self.config.item_groups:
            if tab_id is not None and group.tab_id != tab_id:
                continue
            if any(key in group.member_paths for key in keys):
                affected_tabs.add(group.tab_id)
            group.member_paths = [k for k in group.member_paths if k not in keys]
        self._prune_item_groups_after_member_change()
        for affected_tab in affected_tabs:
            self._collapse_manual_order_groups(affected_tab)

    def rename_item_group(self, group_id: str, name: str) -> None:
        group = self._item_group(group_id)
        cleaned = name.strip()
        if cleaned:
            group.name = cleaned

    def dissolve_item_group(self, group_id: str) -> None:
        tab_id = next(
            (group.tab_id for group in self.config.item_groups if group.id == group_id),
            None,
        )
        self.config.item_groups = [
            group for group in self.config.item_groups if group.id != group_id
        ]
        if tab_id is not None:
            self._collapse_manual_order_groups(tab_id)

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

    def add_paths_to_tab(
        self,
        paths: list[Path],
        tab_id: str,
        *,
        desktop_roots: list[Path] | None = None,
    ) -> None:
        self._require_item_tab(tab_id)
        roots = [Path(self.config.desktop.path).resolve()]
        for root in desktop_roots or []:
            resolved_root = Path(root).resolve()
            if resolved_root not in roots:
                roots.append(resolved_root)
        for path in paths:
            resolved = Path(path).resolve()
            if any(is_inside(resolved, root) for root in roots):
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

    def organize_by_rules(
        self,
        *,
        desktop_roots: list[Path] | None = None,
    ) -> list[str]:
        """按规则整理:仅释放待整理(其它)里的临时归类,保留用户手动挪动的归类,并修复元数据。"""
        pending_tab = self._pending_organize_tab_id()
        self.config.manual_overrides = [
            entry
            for entry in self.config.manual_overrides
            if entry.target_tab_id != pending_tab
        ]
        return self.repair_metadata(desktop_roots=desktop_roots)

    def repair_metadata(
        self,
        *,
        desktop_roots: list[Path] | None = None,
    ) -> list[str]:
        """检测并修复重复图标等低级元数据错误,返回本次修复说明。"""
        issues: list[str] = []
        tab_ids = {tab.id for tab in self.config.panel_tabs}
        roots = [Path(self.config.desktop.path).resolve()]
        for root in desktop_roots or []:
            resolved_root = Path(root).resolve()
            if resolved_root not in roots:
                roots.append(resolved_root)

        override_by_key: dict[str, ManualOverride] = {}
        for entry in self.config.manual_overrides:
            if entry.canonical_path in override_by_key:
                issues.append(f"重复的手动归类: {entry.canonical_path}")
            override_by_key[entry.canonical_path] = entry
        self.config.manual_overrides = list(override_by_key.values())
        override_keys = set(override_by_key.keys())

        ref_by_key: dict[str, ItemRef] = {}
        for ref in self.config.external_refs:
            key = canonical_key(Path(ref.canonical_path))
            if key in override_keys:
                resolved = Path(ref.canonical_path).resolve()
                if any(is_inside(resolved, root) for root in roots):
                    issues.append(f"清理与手动归类重复的外部引用: {ref.canonical_path}")
                    continue
            if key in ref_by_key:
                issues.append(f"重复的外部引用: {ref.canonical_path}")
            ref_by_key[key] = ref
        self.config.external_refs = list(ref_by_key.values())

        for tab_id in list(self.config.manual_orders.keys()):
            if tab_id not in tab_ids:
                issues.append(f"清理无效标签的手动顺序: {tab_id}")
                self.config.manual_orders.pop(tab_id, None)
                continue
            seen: set[str] = set()
            deduped: list[str] = []
            for key in self.config.manual_orders[tab_id]:
                if key in seen:
                    issues.append(f"标签 {tab_id} 内重复顺序项: {key}")
                    continue
                seen.add(key)
                deduped.append(key)
            self.config.manual_orders[tab_id] = deduped

        self._repair_duplicate_identities(issues, roots)

        valid_keys = override_keys | set(ref_by_key.keys())
        for group in self.config.item_groups:
            if group.tab_id not in tab_ids:
                issues.append(f"清理无效标签的分组: {group.name}")
                continue
            seen_members: set[str] = set()
            deduped_members: list[str] = []
            for key in group.member_paths:
                if key in seen_members:
                    issues.append(f"分组 {group.name} 内重复成员: {key}")
                    continue
                seen_members.add(key)
                deduped_members.append(key)
            group.member_paths = deduped_members
        self._prune_item_groups_after_member_change()

        return issues

    def _path_from_canonical_key(self, key: str) -> Path | None:
        try:
            candidate = Path(key)
        except ValueError:
            return None
        if not candidate.exists():
            return None
        return candidate.resolve()

    def _repair_duplicate_identities(
        self,
        issues: list[str],
        _roots: list[Path],
    ) -> None:
        primary = Path(self.config.desktop.path)

        for tab_id, order in list(self.config.manual_orders.items()):
            kept: list[str] = []
            seen_identities: set[str] = set()
            for key in order:
                path = self._path_from_canonical_key(key)
                identity = item_identity_key(path) if path is not None else f"path:{key}"
                if identity in seen_identities:
                    label = path.name if path is not None else key
                    issues.append(f"标签 {tab_id} 内重复快捷方式: {label}")
                    continue
                seen_identities.add(identity)
                kept.append(key)
            self.config.manual_orders[tab_id] = kept

        best_overrides: dict[tuple[str, str], ManualOverride] = {}
        for entry in self.config.manual_overrides:
            path = self._path_from_canonical_key(entry.canonical_path)
            identity = (
                item_identity_key(path)
                if path is not None
                else f"path:{entry.canonical_path}"
            )
            bucket = (entry.target_tab_id, identity)
            existing = best_overrides.get(bucket)
            if existing is None:
                best_overrides[bucket] = entry
                continue
            existing_path = self._path_from_canonical_key(existing.canonical_path)
            if existing_path is None or path is None:
                issues.append(f"重复归类冲突: {entry.canonical_path}")
                continue
            if desktop_entry_rank(path, primary_desktop=primary) < desktop_entry_rank(
                existing_path, primary_desktop=primary
            ):
                issues.append(
                    f"清理重复归类,保留优先项: {existing_path.name} -> {path.name}"
                )
                best_overrides[bucket] = entry
            else:
                issues.append(
                    f"清理重复归类,保留优先项: {path.name} -> {existing_path.name}"
                )
        self.config.manual_overrides = list(best_overrides.values())

        best_refs: dict[tuple[str, str], ItemRef] = {}
        kept_refs: list[ItemRef] = []
        override_keys = {entry.canonical_path for entry in self.config.manual_overrides}
        for ref in self.config.external_refs:
            key = canonical_key(Path(ref.canonical_path))
            if key in override_keys:
                kept_refs.append(ref)
                continue
            path = self._path_from_canonical_key(key)
            identity = item_identity_key(path) if path is not None else f"path:{key}"
            bucket = (ref.target_tab_id, identity)
            existing = best_refs.get(bucket)
            if existing is None:
                best_refs[bucket] = ref
                continue
            existing_path = Path(existing.canonical_path).resolve()
            current_path = Path(ref.canonical_path).resolve()
            if desktop_entry_rank(current_path, primary_desktop=primary) < desktop_entry_rank(
                existing_path, primary_desktop=primary
            ):
                issues.append(f"清理重复外部引用: {existing_path.name}")
                best_refs[bucket] = ref
            else:
                issues.append(f"清理重复外部引用: {current_path.name}")
        self.config.external_refs = kept_refs + list(best_refs.values())

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

    def home_tab(self) -> PanelTab | None:
        for tab in self.config.panel_tabs:
            if tab.content_kind == "widget" and tab.widget_type == "home":
                return tab
        return None

    def ensure_home_tab(self, group_id: str | None = None) -> PanelTab:
        home_tabs = [
            tab
            for tab in self.config.panel_tabs
            if tab.content_kind == "widget" and tab.widget_type == "home"
        ]
        primary = home_tabs[0] if home_tabs else None
        for duplicate in home_tabs[1:]:
            duplicate_group = self.group(duplicate.group_id)
            duplicate_group.tab_ids = [
                tab_id for tab_id in duplicate_group.tab_ids if tab_id != duplicate.id
            ]
            if duplicate_group.active_tab_id == duplicate.id:
                duplicate_group.active_tab_id = (
                    duplicate_group.tab_ids[0] if duplicate_group.tab_ids else ""
                )
            self.config.panel_tabs = [
                tab for tab in self.config.panel_tabs if tab.id != duplicate.id
            ]
        self.config.panel_groups = [
            group for group in self.config.panel_groups if group.tab_ids
        ]
        target_group = self.group(group_id) if group_id else self.ensure_minimum_default_group()

        if primary is None:
            existing_ids = {tab.id for tab in self.config.panel_tabs}
            tab_id = "tab-home" if "tab-home" not in existing_ids else f"tab-home-{uuid.uuid4().hex}"
            primary = PanelTab(
                id=tab_id,
                group_id=target_group.id,
                name="主标签页",
                order=0,
                category_role="home",
                content_kind="widget",
                widget_type="home",
                widget_settings={},
            )
            self.config.panel_tabs.append(primary)
            target_group.tab_ids.insert(0, primary.id)
        else:
            target_group = self.group(primary.group_id)
            target_group.tab_ids = [
                tab_id for tab_id in target_group.tab_ids if tab_id != primary.id
            ]
            target_group.tab_ids.insert(0, primary.id)
            primary.name = primary.name.strip() or "主标签页"
            primary.category_role = primary.category_role or "home"

        target_group.active_tab_id = primary.id
        self._reindex_tabs()
        return primary

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
        if widget_type == "home":
            return "主标签页"
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
        # 仅清显示层元数据,绝不触碰真实文件。
        self.config.manual_orders.pop(tab_id, None)
        self.config.item_groups = [
            group_entry
            for group_entry in self.config.item_groups
            if group_entry.tab_id != tab_id
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
