"""Pure domain objects and commands for desktop entrance management."""

from .defaults import build_default_configuration
from .classification import canonical_key, classify_path, is_inside
from .models import (
    AppearanceSettings,
    ClassificationRule,
    Configuration,
    DesktopIntegrationState,
    InvalidConfiguration,
    ItemRef,
    ManualOverride,
    PanelGeometry,
    PanelGroup,
    PanelTab,
    validate_configuration,
)

__all__ = [
    "AppearanceSettings",
    "ClassificationRule",
    "Configuration",
    "DesktopIntegrationState",
    "InvalidConfiguration",
    "ItemRef",
    "ManualOverride",
    "PanelGeometry",
    "PanelGroup",
    "PanelTab",
    "validate_configuration",
    "build_default_configuration",
    "canonical_key",
    "classify_path",
    "is_inside",
]
