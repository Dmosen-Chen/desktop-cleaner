"""Compatibility imports for the function-panel registry."""

from desktop_tidy.widgets.clock import ClockWidget, ClockWidgetPlugin
from desktop_tidy.widgets.home import HomeDashboardWidget, HomeWidgetPlugin
from desktop_tidy.widgets.models import WidgetDefinition, WidgetPlugin
from desktop_tidy.widgets.registry import BuiltinWidgetRegistry, UnknownWidgetPlugin

__all__ = [
    "BuiltinWidgetRegistry",
    "ClockWidget",
    "ClockWidgetPlugin",
    "HomeDashboardWidget",
    "HomeWidgetPlugin",
    "UnknownWidgetPlugin",
    "WidgetDefinition",
    "WidgetPlugin",
]
