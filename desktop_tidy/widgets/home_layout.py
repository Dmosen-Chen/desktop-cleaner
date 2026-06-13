"""Pure grid layout helpers for the Home dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

HOME_GRID_UNITS = 8
HOME_GRID_MAX_ROWS = 6
HOME_MODULE_MAX_HEIGHT_UNITS = 3

HomeModuleLayout = dict[str, dict[str, int]]


@dataclass(frozen=True)
class HomeLayoutSpec:
    default_w: int
    default_h: int = 1
    min_w: int = 1
    max_w: int = HOME_GRID_UNITS
    min_h: int = 1
    max_h: int = HOME_MODULE_MAX_HEIGHT_UNITS


def _int_value(value: object, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


def _spec_for(module_id: str, specs: Mapping[str, HomeLayoutSpec]) -> HomeLayoutSpec:
    return specs.get(module_id, HomeLayoutSpec(default_w=2, default_h=1))


def _normalize_size(
    module_id: str,
    specs: Mapping[str, HomeLayoutSpec],
    *,
    width: object | None = None,
    height: object | None = None,
) -> tuple[int, int]:
    spec = _spec_for(module_id, specs)
    raw_width = _int_value(width, spec.default_w)
    raw_height = _int_value(height, spec.default_h)
    max_width = _clamp(spec.max_w, spec.min_w, HOME_GRID_UNITS)
    max_height = _clamp(spec.max_h, spec.min_h, HOME_MODULE_MAX_HEIGHT_UNITS)
    return (
        _clamp(raw_width, spec.min_w, max_width),
        _clamp(raw_height, spec.min_h, max_height),
    )


def _normalize_item(
    module_id: str,
    specs: Mapping[str, HomeLayoutSpec],
    value: Mapping[str, object] | None,
) -> dict[str, int]:
    item = dict(value or {})
    width, height = _normalize_size(
        module_id,
        specs,
        width=item.get("w", item.get("width")),
        height=item.get("h", item.get("height")),
    )
    x = _clamp(_int_value(item.get("x", item.get("column")), 0), 0, HOME_GRID_UNITS - width)
    y = _clamp(_int_value(item.get("y", item.get("row")), 0), 0, HOME_GRID_MAX_ROWS - height)
    return {"x": x, "y": y, "w": width, "h": height}


def occupied_cells_for(item: Mapping[str, int]) -> set[tuple[int, int]]:
    return {
        (row, column)
        for row in range(int(item["y"]), int(item["y"]) + int(item["h"]))
        for column in range(int(item["x"]), int(item["x"]) + int(item["w"]))
    }


def _is_free(
    item: Mapping[str, int],
    layout: Mapping[str, Mapping[str, int]],
    *,
    exclude_module_id: str = "",
) -> bool:
    cells = occupied_cells_for(item)
    for module_id, existing in layout.items():
        if module_id == exclude_module_id:
            continue
        if cells & occupied_cells_for(existing):
            return False
    return True


def _first_free_item(
    module_id: str,
    specs: Mapping[str, HomeLayoutSpec],
    layout: Mapping[str, Mapping[str, int]],
    *,
    preferred: Mapping[str, int] | None = None,
) -> dict[str, int]:
    base = _normalize_item(module_id, specs, preferred)
    if _is_free(base, layout, exclude_module_id=module_id):
        return base
    for row in range(0, HOME_GRID_MAX_ROWS - base["h"] + 1):
        for column in range(0, HOME_GRID_UNITS - base["w"] + 1):
            candidate = dict(base)
            candidate["x"] = column
            candidate["y"] = row
            if _is_free(candidate, layout, exclude_module_id=module_id):
                return candidate
    return base


def _legacy_span(
    module_id: str,
    specs: Mapping[str, HomeLayoutSpec],
    spans: Mapping[str, object],
) -> dict[str, int]:
    value = spans.get(module_id)
    if isinstance(value, Mapping):
        width = value.get("w", value.get("width"))
        height = value.get("h", value.get("height"))
    else:
        width = value
        height = None
    w, h = _normalize_size(module_id, specs, width=width, height=height)
    return {"x": 0, "y": 0, "w": w, "h": h}


def _legacy_position(positions: Mapping[str, object], module_id: str) -> dict[str, int]:
    value = positions.get(module_id)
    if not isinstance(value, Mapping):
        return {"x": 0, "y": 0}
    return {
        "x": _int_value(value.get("x", value.get("column")), 0),
        "y": _int_value(value.get("y", value.get("row")), 0),
    }


def build_default_module_layout(
    modules: list[str],
    specs: Mapping[str, HomeLayoutSpec],
) -> HomeModuleLayout:
    layout: HomeModuleLayout = {}
    for module_id in modules:
        layout[module_id] = _first_free_item(module_id, specs, layout)
    return layout


def normalize_home_module_layout(
    modules: list[str],
    specs: Mapping[str, HomeLayoutSpec],
    settings: Mapping[str, object],
) -> HomeModuleLayout:
    configured = settings.get("module_layout")
    spans = settings.get("module_spans")
    positions = settings.get("module_positions")
    configured_layout = configured if isinstance(configured, Mapping) else {}
    legacy_spans = spans if isinstance(spans, Mapping) else {}
    legacy_positions = positions if isinstance(positions, Mapping) else {}
    layout: HomeModuleLayout = {}
    for module_id in modules:
        if module_id in configured_layout and isinstance(configured_layout[module_id], Mapping):
            preferred = _normalize_item(module_id, specs, configured_layout[module_id])  # type: ignore[arg-type]
        else:
            preferred = _legacy_span(module_id, specs, legacy_spans)
            preferred.update(_legacy_position(legacy_positions, module_id))
        layout[module_id] = _first_free_item(
            module_id,
            specs,
            layout,
            preferred=preferred,
        )
    return layout


def set_module_position(
    layout: Mapping[str, Mapping[str, int]],
    module_id: str,
    x: int,
    y: int,
    modules: list[str],
    specs: Mapping[str, HomeLayoutSpec],
) -> tuple[bool, HomeModuleLayout]:
    if module_id not in modules or module_id not in layout:
        return False, {key: dict(value) for key, value in layout.items()}
    next_layout = {key: dict(value) for key, value in layout.items()}
    current = next_layout[module_id]
    candidate = _normalize_item(
        module_id,
        specs,
        {"x": x, "y": y, "w": current["w"], "h": current["h"]},
    )
    if candidate == current or not _is_free(candidate, next_layout, exclude_module_id=module_id):
        return False, next_layout
    next_layout[module_id] = candidate
    return True, next_layout


def resize_module(
    layout: Mapping[str, Mapping[str, int]],
    module_id: str,
    width: int,
    height: int,
    modules: list[str],
    specs: Mapping[str, HomeLayoutSpec],
) -> tuple[bool, HomeModuleLayout]:
    if module_id not in modules or module_id not in layout:
        return False, {key: dict(value) for key, value in layout.items()}
    next_layout = {key: dict(value) for key, value in layout.items()}
    current = next_layout[module_id]
    candidate = _normalize_item(
        module_id,
        specs,
        {"x": current["x"], "y": current["y"], "w": width, "h": height},
    )
    if candidate["x"] + candidate["w"] > HOME_GRID_UNITS:
        candidate["x"] = max(0, HOME_GRID_UNITS - candidate["w"])
    if candidate["y"] + candidate["h"] > HOME_GRID_MAX_ROWS:
        candidate["y"] = max(0, HOME_GRID_MAX_ROWS - candidate["h"])
    if candidate == current:
        return False, next_layout
    if not _is_free(candidate, next_layout, exclude_module_id=module_id):
        return False, next_layout
    next_layout[module_id] = candidate
    return True, next_layout
