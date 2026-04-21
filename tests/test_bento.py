from __future__ import annotations
import pytest
from app.models.registry import Module
from app.services.bento import compute_layout, BentoLayout, TileLayout


def _mod(id: str, category: str, active: bool = True) -> Module:
    return Module(
        id=id,
        display_name=id.replace("-", " ").title(),
        category=category,
        description=f"{id} description",
        latest_version="2024-01",
        size_gb=1.0,
        checksum="sha256:abc",
        active=active,
    )


# ── empty state ──────────────────────────────────────────────────────────────

def test_empty_layout_when_no_active_modules():
    layout = compute_layout([], wifi_connected=False)
    assert layout.empty is True
    assert layout.tiles == []


def test_empty_layout_packages_tile_always_present():
    layout = compute_layout([], wifi_connected=False)
    assert any(t.grid_area == "pkg" for t in layout.system_tiles)


def test_empty_layout_no_internet_tile_when_no_wifi():
    layout = compute_layout([], wifi_connected=False)
    assert not any(t.grid_area == "inet" for t in layout.system_tiles)


def test_empty_layout_internet_tile_when_wifi():
    layout = compute_layout([], wifi_connected=True)
    assert any(t.grid_area == "inet" for t in layout.system_tiles)


# ── center tile priority ──────────────────────────────────────────────────────

def test_maps_module_gets_center():
    modules = [_mod("maps-world", "maps"), _mod("medical-wikimed", "medical")]
    layout = compute_layout(modules, wifi_connected=False)
    center = next(t for t in layout.tiles if t.grid_area == "center")
    assert center.module.category == "maps"


def test_medical_gets_center_when_no_maps():
    modules = [_mod("medical-wikimed", "medical"), _mod("survival-wikihow", "survival")]
    layout = compute_layout(modules, wifi_connected=False)
    center = next(t for t in layout.tiles if t.grid_area == "center")
    assert center.module.category == "medical"


def test_first_alphabetically_gets_center_when_no_maps_or_medical():
    modules = [_mod("survival-wikihow", "survival"), _mod("food-plants", "food")]
    layout = compute_layout(modules, wifi_connected=False)
    center = next(t for t in layout.tiles if t.grid_area == "center")
    assert center.module.id == "food-plants"


# ── center tile size ──────────────────────────────────────────────────────────

def test_center_tile_has_size_center():
    modules = [_mod("maps-world", "maps")]
    layout = compute_layout(modules, wifi_connected=False)
    center = next(t for t in layout.tiles if t.grid_area == "center")
    assert center.size == "center"


# ── layout presets ────────────────────────────────────────────────────────────

def test_one_module_grid_is_3x3():
    layout = compute_layout([_mod("maps-world", "maps")], wifi_connected=False)
    assert layout.columns == 3
    assert layout.rows == 3


def test_two_modules_grid_is_3x3():
    modules = [_mod("maps-world", "maps"), _mod("medical-wikimed", "medical")]
    layout = compute_layout(modules, wifi_connected=False)
    assert layout.columns == 3
    assert layout.rows == 3


def test_three_modules_grid_is_4x3():
    modules = [
        _mod("maps-world", "maps"),
        _mod("medical-wikimed", "medical"),
        _mod("survival-wikihow", "survival"),
    ]
    layout = compute_layout(modules, wifi_connected=False)
    assert layout.columns == 4
    assert layout.rows == 3


def test_four_modules_grid_is_4x3():
    modules = [
        _mod("maps-world", "maps"),
        _mod("medical-wikimed", "medical"),
        _mod("survival-wikihow", "survival"),
        _mod("food-plants", "food"),
    ]
    layout = compute_layout(modules, wifi_connected=False)
    assert layout.columns == 4
    assert layout.rows == 3


def test_five_modules_grid_is_4x4():
    modules = [
        _mod("maps-world", "maps"),
        _mod("medical-wikimed", "medical"),
        _mod("survival-wikihow", "survival"),
        _mod("food-plants", "food"),
        _mod("wikipedia-curated", "encyclopedia"),
    ]
    layout = compute_layout(modules, wifi_connected=False)
    assert layout.columns == 4
    assert layout.rows == 4


def test_six_plus_modules_grid_is_4x5():
    modules = [_mod(f"mod-{i}", "encyclopedia") for i in range(6)]
    layout = compute_layout(modules, wifi_connected=False)
    assert layout.columns == 4
    assert layout.rows == 5


def test_overflow_modules_beyond_slots_are_dropped():
    """Grid has 8 non-center slots for 6+ modules; extras are silently dropped."""
    modules = [_mod(f"mod-{i}", "encyclopedia") for i in range(10)]
    layout = compute_layout(modules, wifi_connected=False)
    # center tile + 8 slots = 9 total
    assert len(layout.tiles) == 9


# ── grid_template_areas format ────────────────────────────────────────────────

def test_grid_template_areas_contains_center():
    layout = compute_layout([_mod("maps-world", "maps")], wifi_connected=False)
    assert "center" in layout.grid_template_areas


def test_grid_template_areas_contains_pkg():
    layout = compute_layout([_mod("maps-world", "maps")], wifi_connected=False)
    assert "pkg" in layout.grid_template_areas


def test_grid_template_areas_is_quoted_rows():
    """Each row must be a quoted string, rows separated by newlines."""
    layout = compute_layout([_mod("maps-world", "maps")], wifi_connected=False)
    rows = layout.grid_template_areas.strip().splitlines()
    assert len(rows) == layout.rows
    for row in rows:
        assert row.strip().startswith("'") and row.strip().endswith("'")
