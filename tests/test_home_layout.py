from desktop_tidy.widgets.home_layout import (
    HomeLayoutSpec,
    build_default_module_layout,
    normalize_home_module_layout,
    resize_module,
    set_module_position,
)


SPECS = {
    "recent": HomeLayoutSpec(default_w=4, default_h=1),
    "schedule": HomeLayoutSpec(default_w=2, default_h=1),
    "bookmarks": HomeLayoutSpec(default_w=2, default_h=1),
    "calendar": HomeLayoutSpec(default_w=3, default_h=2),
    "weather": HomeLayoutSpec(default_w=2, default_h=1),
}


def test_default_home_layout_is_bounded_and_non_overlapping():
    layout = build_default_module_layout(
        ["recent", "schedule", "bookmarks", "calendar", "weather"],
        SPECS,
    )

    occupied = set()
    for item in layout.values():
        assert 0 <= item["x"] <= 7
        assert 0 <= item["y"] <= 5
        assert 1 <= item["w"] <= 8
        assert 1 <= item["h"] <= 3
        assert item["x"] + item["w"] <= 8
        assert item["y"] + item["h"] <= 6
        cells = {
            (row, column)
            for row in range(item["y"], item["y"] + item["h"])
            for column in range(item["x"], item["x"] + item["w"])
        }
        assert not occupied & cells
        occupied |= cells


def test_legacy_spans_and_positions_migrate_to_module_layout():
    settings = {
        "module_spans": {
            "recent": 4,
            "calendar": {"w": 3, "h": 2},
        },
        "module_positions": {
            "recent": {"x": 4, "y": 1},
            "calendar": {"x": 0, "y": 2},
        },
    }

    layout = normalize_home_module_layout(["recent", "calendar"], SPECS, settings)

    assert layout["recent"] == {"x": 4, "y": 1, "w": 4, "h": 1}
    assert layout["calendar"] == {"x": 0, "y": 2, "w": 3, "h": 2}


def test_module_position_rejects_overlap_and_keeps_existing_layout():
    layout = {
        "recent": {"x": 0, "y": 0, "w": 4, "h": 1},
        "calendar": {"x": 4, "y": 0, "w": 3, "h": 2},
    }

    changed, next_layout = set_module_position(
        layout,
        "calendar",
        2,
        0,
        ["recent", "calendar"],
        SPECS,
    )

    assert not changed
    assert next_layout == layout


def test_module_position_moves_to_empty_grid_cell():
    layout = {
        "recent": {"x": 0, "y": 0, "w": 4, "h": 1},
        "calendar": {"x": 4, "y": 0, "w": 3, "h": 2},
    }

    changed, next_layout = set_module_position(
        layout,
        "calendar",
        0,
        1,
        ["recent", "calendar"],
        SPECS,
    )

    assert changed
    assert next_layout["calendar"] == {"x": 0, "y": 1, "w": 3, "h": 2}
    assert next_layout["recent"] == layout["recent"]


def test_resizing_one_module_does_not_change_other_module_size():
    layout = {
        "recent": {"x": 0, "y": 0, "w": 4, "h": 1},
        "calendar": {"x": 4, "y": 1, "w": 3, "h": 2},
    }

    changed, next_layout = resize_module(
        layout,
        "recent",
        2,
        3,
        ["recent", "calendar"],
        SPECS,
    )

    assert changed
    assert next_layout["recent"] == {"x": 0, "y": 0, "w": 2, "h": 3}
    assert next_layout["calendar"] == layout["calendar"]


def test_module_size_is_clamped_to_grid_limits():
    layout = {"weather": {"x": 7, "y": 5, "w": 2, "h": 1}}

    normalized = normalize_home_module_layout(["weather"], SPECS, {"module_layout": layout})

    assert normalized["weather"] == {"x": 6, "y": 5, "w": 2, "h": 1}

    changed, resized = resize_module(
        normalized,
        "weather",
        10,
        5,
        ["weather"],
        SPECS,
    )

    assert changed
    assert resized["weather"] == {"x": 0, "y": 3, "w": 8, "h": 3}
