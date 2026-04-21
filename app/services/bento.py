from __future__ import annotations
from dataclasses import dataclass
from app.models.registry import Module

_PRIORITY: dict[str, int] = {"maps": 0, "medical": 1}


def _sort_key(m: Module) -> tuple[int, str]:
    return (_PRIORITY.get(m.category, 99), m.id)


@dataclass
class TileLayout:
    module: Module
    grid_area: str
    size: str  # "center" | "regular"
    url: str = ""


@dataclass
class BentoLayout:
    tiles: list[TileLayout]
    system_tiles: list[TileLayout]
    grid_template_areas: str
    columns: int
    rows: int
    empty: bool


# Each preset: (areas_no_wifi, areas_wifi, slot_names, columns, rows)
# areas: one quoted string per row, separated by spaces
# slot_names: grid-area names for non-center content modules, in fill order
_PRESETS: dict[int, tuple[str, str, list[str], int, int]] = {
    0: (
        "'empty empty empty empty' 'pkg   pkg   pkg   pkg  '",
        "'empty empty empty inet ' 'pkg   pkg   pkg   inet '",
        [], 4, 2,
    ),
    1: (
        "'.    center center' '.    center center' 'pkg  pkg    pkg  '",
        "'.    center center' '.    center center' 'pkg  pkg    inet '",
        [], 3, 3,
    ),
    2: (
        "'slot1 center center' 'slot1 center center' 'pkg   pkg    pkg  '",
        "'slot1 center center' 'slot1 center center' 'pkg   pkg    inet '",
        ["slot1"], 3, 3,
    ),
    3: (
        "'slot1 center center slot2' 'slot3 center center slot2' 'pkg   pkg    pkg    pkg  '",
        "'slot1 center center slot2' 'slot3 center center slot2' 'pkg   pkg    pkg    inet '",
        ["slot1", "slot2", "slot3"], 4, 3,
    ),
    4: (
        "'slot1 center center slot2' 'slot3 center center slot4' 'pkg   pkg    pkg    pkg  '",
        "'slot1 center center slot2' 'slot3 center center slot4' 'pkg   pkg    pkg    inet '",
        ["slot1", "slot2", "slot3", "slot4"], 4, 3,
    ),
    5: (
        "'slot1 slot1  slot2  slot3' 'slot4 center center slot3' 'slot4 center center slot5' 'pkg   pkg    pkg    slot5'",
        "'slot1 slot1  slot2  slot3' 'slot4 center center slot3' 'slot4 center center inet ' 'pkg   pkg    pkg    inet '",
        ["slot1", "slot2", "slot3", "slot4", "slot5"], 4, 4,
    ),
}
# 6+ uses same shape as 5 but with an extra row of slots above
_PRESET_6PLUS: tuple[str, str, list[str], int, int] = (
    "'slot6 slot6  slot7  slot8' 'slot1 slot1  slot2  slot3' 'slot4 center center slot3' 'slot4 center center slot5' 'pkg   pkg    pkg    slot5'",
    "'slot6 slot6  slot7  slot8' 'slot1 slot1  slot2  slot3' 'slot4 center center slot3' 'slot4 center center inet ' 'pkg   pkg    pkg    inet '",
    ["slot1", "slot2", "slot3", "slot4", "slot5", "slot6", "slot7", "slot8"], 4, 5,
)

_PACKAGES_MODULE = Module(
    id="_packages",
    display_name="Packages",
    category="packages",
    description="Manage content modules",
    latest_version="",
    size_gb=0,
    checksum="",
)
_INTERNET_MODULE = Module(
    id="_internet",
    display_name="Internet",
    category="internet",
    description="Live web access",
    latest_version="",
    size_gb=0,
    checksum="",
)


def compute_layout(modules: list[Module], wifi_connected: bool) -> BentoLayout:
    active = sorted(modules, key=_sort_key)
    n = len(active)

    if n >= 6:
        areas_no_wifi, areas_wifi, slot_names, columns, rows = _PRESET_6PLUS
    else:
        areas_no_wifi, areas_wifi, slot_names, columns, rows = _PRESETS[n]

    areas = areas_wifi if wifi_connected else areas_no_wifi

    # Assign content tiles
    tiles: list[TileLayout] = []
    if active:
        tiles.append(TileLayout(module=active[0], grid_area="center", size="center"))
        for module, slot in zip(active[1:], slot_names):
            tiles.append(TileLayout(module=module, grid_area=slot, size="regular"))

    # System tiles
    system_tiles = [TileLayout(module=_PACKAGES_MODULE.model_copy(), grid_area="pkg", size="regular")]
    if wifi_connected:
        system_tiles.append(TileLayout(module=_INTERNET_MODULE.model_copy(), grid_area="inet", size="regular"))

    return BentoLayout(
        tiles=tiles,
        system_tiles=system_tiles,
        grid_template_areas=areas,
        columns=columns,
        rows=rows,
        empty=len(active) == 0,
    )
