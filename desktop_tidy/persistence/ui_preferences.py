"""Small local UI preferences that do not belong in the main config schema."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


@dataclass
class UiPreferences:
    confirm_delete_panel: bool = True
    confirm_delete_tab: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "confirm_delete_panel": self.confirm_delete_panel,
            "confirm_delete_tab": self.confirm_delete_tab,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> UiPreferences:
        return cls(
            confirm_delete_panel=bool(payload.get("confirm_delete_panel", True)),
            confirm_delete_tab=bool(payload.get("confirm_delete_tab", True)),
        )


class UiPreferencesStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> UiPreferences:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return UiPreferences()
        if not isinstance(payload, dict):
            return UiPreferences()
        return UiPreferences.from_dict(payload)

    def save(self, preferences: UiPreferences) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(preferences.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def reset_delete_confirmations(self) -> UiPreferences:
        preferences = self.load()
        preferences.confirm_delete_panel = True
        preferences.confirm_delete_tab = True
        self.save(preferences)
        return preferences
