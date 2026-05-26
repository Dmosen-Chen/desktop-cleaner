"""Qt screen discovery helpers for preview panel placement."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QScreen
from PySide6.QtWidgets import QApplication

_FALLBACK_SCREEN = QRect(0, 0, 1920, 1080)


@dataclass(frozen=True)
class ScreenInfo:
    screen_id: str
    label: str
    geometry: QRect


def _usable_geometry(screen: QScreen) -> QRect:
    geometry = screen.availableGeometry()
    if geometry.isValid() and geometry.width() > 0 and geometry.height() > 0:
        return QRect(geometry)
    return QRect(screen.geometry())


def available_screens() -> list[ScreenInfo]:
    app = QApplication.instance()
    if app is None:
        return [ScreenInfo("primary", "\u4e3b\u5c4f", QRect(_FALLBACK_SCREEN))]
    screens = list(app.screens())
    if not screens:
        return [ScreenInfo("primary", "\u4e3b\u5c4f", QRect(_FALLBACK_SCREEN))]

    primary = app.primaryScreen()
    secondary_count = 0
    result: list[ScreenInfo] = []
    for index, screen in enumerate(screens):
        if screen is primary:
            result.append(ScreenInfo("primary", "\u4e3b\u5c4f", _usable_geometry(screen)))
            continue
        secondary_count += 1
        result.append(
            ScreenInfo(
                f"screen-{index}",
                f"\u526f\u5c4f {secondary_count}",
                _usable_geometry(screen),
            )
        )
    if not any(entry.screen_id == "primary" for entry in result):
        first = result[0]
        result[0] = ScreenInfo("primary", "\u4e3b\u5c4f", first.geometry)
    return result


def available_screen_options() -> list[tuple[str, str]]:
    return [(screen.screen_id, screen.label) for screen in available_screens()]


def available_screen_geometries() -> dict[str, QRect]:
    return {screen.screen_id: QRect(screen.geometry) for screen in available_screens()}


def screen_id_containing_point(
    point: QPoint,
    geometries: dict[str, QRect],
    *,
    fallback: str = "primary",
) -> str:
    if not geometries:
        return fallback
    for screen_id, geometry in geometries.items():
        if geometry.contains(point):
            return screen_id
    nearest_id = fallback if fallback in geometries else next(iter(geometries))
    nearest_distance = None
    for screen_id, geometry in geometries.items():
        center = geometry.center()
        distance = abs(center.x() - point.x()) + abs(center.y() - point.y())
        if nearest_distance is None or distance < nearest_distance:
            nearest_id = screen_id
            nearest_distance = distance
    return nearest_id
