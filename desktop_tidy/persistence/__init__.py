"""Configuration storage and legacy migration."""

from .config_store import ConfigurationStore
from .migration import load_or_migrate

__all__ = ["ConfigurationStore", "load_or_migrate"]
