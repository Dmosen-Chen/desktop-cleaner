"""Pure domain objects and commands for desktop entrance management."""

from .defaults import build_default_configuration
from .classification import canonical_key, classify_path, is_inside
from .models import (
    AppearanceSettings,
    ClassificationRule,
    Configuration,
    DesktopIntegrationState,
    ItemRef,
    ManualOverride,
    PanelGeometry,
    PanelGroup,
    PanelTab,
)

__all__ = [
    "AppearanceSettings",
    "ClassificationRule",
    "Configuration",
    "DesktopIntegrationState",
    "ItemRef",
    "ManualOverride",
    "PanelGeometry",
    "PanelGroup",
    "PanelTab",
    "build_default_configuration",
    "canonical_key",
    "classify_path",
    "is_inside",
]
