"""Persistent layout snapshots for recovering panel arrangements."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import uuid

from desktop_tidy.domain.models import Configuration, validate_configuration


@dataclass(frozen=True)
class LayoutSnapshot:
    id: str
    created_at: str
    reason: str
    configuration: Configuration

    @property
    def group_count(self) -> int:
        return len(self.configuration.panel_groups)

    @property
    def tab_count(self) -> int:
        return len(self.configuration.panel_tabs)

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "reason": self.reason,
            "configuration": self.configuration.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> LayoutSnapshot:
        return cls(
            id=str(payload["id"]),
            created_at=str(payload["created_at"]),
            reason=str(payload.get("reason", "")),
            configuration=Configuration.from_dict(dict(payload["configuration"])),
        )


class LayoutHistoryStore:
    """Stores recent configuration snapshots without touching source files."""

    def __init__(self, path: Path, *, limit: int = 30) -> None:
        self.path = Path(path)
        self.limit = limit

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
                validate_configuration(snapshot.configuration)
            except Exception:
                continue
            snapshots.append(snapshot)
        return snapshots[-self.limit :]

    def push(self, config: Configuration, reason: str) -> LayoutSnapshot | None:
        validate_configuration(config)
        snapshots = self.load()
        fingerprint = self._fingerprint(config)
        if snapshots and self._fingerprint(snapshots[-1].configuration) == fingerprint:
            return None
        snapshot = LayoutSnapshot(
            id=f"layout-{uuid.uuid4().hex}",
            created_at=datetime.now().isoformat(timespec="seconds"),
            reason=reason,
            configuration=Configuration.from_dict(config.to_dict()),
        )
        snapshots.append(snapshot)
        snapshots = snapshots[-self.limit :]
        self._save(snapshots)
        return snapshot

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

    def _fingerprint(self, config: Configuration) -> str:
        return json.dumps(config.to_dict(), ensure_ascii=False, sort_keys=True)
