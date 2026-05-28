"""Built-in safe function panels."""

from desktop_tidy.widgets.models import WidgetDefinition, WidgetPlugin
from desktop_tidy.widgets.registry import BuiltinWidgetRegistry, UnknownWidgetPlugin

__all__ = [
    "BuiltinWidgetRegistry",
    "UnknownWidgetPlugin",
    "WidgetDefinition",
    "WidgetPlugin",
]
