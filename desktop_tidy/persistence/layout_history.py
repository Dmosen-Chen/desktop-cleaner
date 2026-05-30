"""Persistent layout snapshots for recovering panel arrangements."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Callable
import uuid

from desktop_tidy.domain.models import Configuration, validate_configuration


@dataclass(frozen=True)
class LayoutSnapshot:
    id: str
    created_at: str
    reason: str
    configuration: Configuration
    preview_kind: str = "layout"
    preview_path: str = ""

    @property
    def group_count(self) -> int:
        return len(self.configuration.panel_groups)

    @property
    def tab_count(self) -> int:
        return len(self.configuration.panel_tabs)

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "id": self.id,
            "created_at": self.created_at,
            "reason": self.reason,
            "configuration": self.configuration.to_dict(),
        }
        if self.preview_kind != "layout":
            payload["preview_kind"] = self.preview_kind
        if self.preview_path:
            payload["preview_path"] = self.preview_path
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> LayoutSnapshot:
        return cls(
            id=str(payload["id"]),
            created_at=str(payload["created_at"]),
            reason=str(payload.get("reason", "")),
            configuration=Configuration.from_dict(dict(payload["configuration"])),
            preview_kind=str(payload.get("preview_kind", "layout")),
            preview_path=str(payload.get("preview_path", "")),
        )


class LayoutHistoryStore:
    """Stores recent configuration snapshots without touching source files."""

    def __init__(
        self,
        path: Path,
        *,
        limit: int = 10,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.path = Path(path)
        self.limit = limit
        self._clock = clock or datetime.now

    def load(self) -> list[LayoutSnapshot]:
        if not self.path.is_file():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return []
        raw_snapshots = payload.get("snapshots", []) if isinstance(payload, dict) else []
        snapshots: list[LayoutSnapshot] = []
        for raw in raw_snapshots:
            if not isinstance(raw, dict):
                continue
            try:
                snapshot = LayoutSnapshot.from_dict(raw)
            except Exception:
                continue
            upgraded = self._upgrade_snapshot_config(snapshot.configuration)
            if upgraded is None:
                continue
            if upgraded is not snapshot.configuration:
                snapshot = LayoutSnapshot(
                    id=snapshot.id,
                    created_at=snapshot.created_at,
                    reason=snapshot.reason,
                    configuration=upgraded,
                    preview_kind=snapshot.preview_kind,
                    preview_path=snapshot.preview_path,
                )
            snapshots.append(snapshot)
        return snapshots[-self.limit :]

    @staticmethod
    def _upgrade_snapshot_config(config: Configuration) -> Configuration | None:
        # 旧 schema 快照(如 v4)就地迁移升级到当前版本,而不是静默丢弃,
        # 避免用户升级后历史布局突然消失、无法恢复。
        from desktop_tidy.persistence.migration import (
            CURRENT_SCHEMA_VERSION,
            _migrate_schema_four_to_five,
            _migrate_schema_three_to_four,
        )

        try:
            upgraded = config
            if upgraded.schema_version == 3:
                upgraded = _migrate_schema_three_to_four(upgraded)
            if upgraded.schema_version == 4:
                upgraded = _migrate_schema_four_to_five(upgraded)
            if upgraded.schema_version != CURRENT_SCHEMA_VERSION:
                return None
            validate_configuration(upgraded)
            return upgraded
        except Exception:
            return None

    def push(
        self,
        config: Configuration,
        reason: str,
        *,
        merge_key: str = "",
        merge_window_seconds: int = 300,
    ) -> LayoutSnapshot | None:
        validate_configuration(config)
        snapshots = self.load()
        fingerprint = self.fingerprint(config)
        if snapshots and self.fingerprint(snapshots[-1].configuration) == fingerprint:
            return None
        now = self._clock()
        if snapshots and merge_key:
            last = snapshots[-1]
            try:
                last_created = datetime.fromisoformat(last.created_at)
            except ValueError:
                last_created = None
            if (
                last.reason == merge_key
                and last_created is not None
                and (now - last_created).total_seconds() <= merge_window_seconds
            ):
                snapshot = LayoutSnapshot(
                    id=last.id,
                    created_at=last.created_at,
                    reason=merge_key,
                    configuration=Configuration.from_dict(config.to_dict()),
                    preview_kind=last.preview_kind,
                    preview_path=last.preview_path,
                )
                snapshots[-1] = snapshot
                self._save(snapshots)
                return snapshot
        snapshot = LayoutSnapshot(
            id=f"layout-{uuid.uuid4().hex}",
            created_at=now.isoformat(timespec="seconds"),
            reason=merge_key or reason,
            configuration=Configuration.from_dict(config.to_dict()),
        )
        snapshots.append(snapshot)
        snapshots = snapshots[-self.limit :]
        self._save(snapshots)
        return snapshot

    def set_preview(
        self,
        snapshot_id: str,
        *,
        preview_path: Path,
        preview_kind: str = "screenshot",
    ) -> LayoutSnapshot:
        snapshots = self.load()
        updated: list[LayoutSnapshot] = []
        result: LayoutSnapshot | None = None
        for snapshot in snapshots:
            if snapshot.id == snapshot_id:
                result = LayoutSnapshot(
                    id=snapshot.id,
                    created_at=snapshot.created_at,
                    reason=snapshot.reason,
                    configuration=snapshot.configuration,
                    preview_kind=preview_kind,
                    preview_path=str(preview_path),
                )
                updated.append(result)
            else:
                updated.append(snapshot)
        if result is None:
            raise KeyError(f"unknown layout snapshot: {snapshot_id}")
        self._save(updated)
        return result

    def restore(self, snapshot_id: str) -> Configuration:
        for snapshot in self.load():
            if snapshot.id == snapshot_id:
                return Configuration.from_dict(snapshot.configuration.to_dict())
        raise KeyError(f"unknown layout snapshot: {snapshot_id}")

    def _save(self, snapshots: list[LayoutSnapshot]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {"snapshots": [snapshot.to_dict() for snapshot in snapshots]},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def fingerprint(self, config: Configuration) -> str:
        layout_payload = {
            "desktop": {"primary_screen_id": config.desktop.primary_screen_id},
            "appearance_defaults": config.appearance_defaults.to_dict(),
            "panel_groups": [group.to_dict() for group in config.panel_groups],
            "panel_tabs": [tab.to_dict() for tab in config.panel_tabs],
        }
        return json.dumps(layout_payload, ensure_ascii=False, sort_keys=True)
