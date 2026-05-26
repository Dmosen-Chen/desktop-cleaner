"""Versioned configuration storage with atomic writes."""

from __future__ import annotations

import json
import os
from pathlib import Path

from desktop_tidy.domain.models import (
    Configuration,
    InvalidConfiguration,
    validate_configuration,
    validate_configuration_payload,
)

from .migration import load_or_migrate


class ConfigurationStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    @classmethod
    def default(cls) -> ConfigurationStore:
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "DesktopTidy"
        return cls(base / "config.json")

    def load(self) -> Configuration:
        return load_or_migrate(self.path)

    def save(self, config: Configuration) -> None:
        validate_configuration_payload(config.to_dict())
        validate_configuration(config)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(config.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.path)
