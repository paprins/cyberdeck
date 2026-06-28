"""Canonical category registry.

Single source of truth for the fixed set of content categories. Every imported
module is assigned exactly one of these. The list is static and small; adding a
category means adding an entry here (and dropping a cover image at
``app/static/images/categories/{slug}.png``).
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class CategoryDef:
    slug: str   # filesystem/URL-safe; also the cover-image filename stem
    label: str  # human label for cards and the wizard dropdown
    icon: str   # Material Symbols Outlined name (fallback when no cover image)

    @property
    def cover_image(self) -> str:
        """URL path to the static cover image (may not exist yet on disk)."""
        return f"/static/images/categories/{self.slug}.png"


# Ordered — this is the display order on the homepage.
CATEGORIES: tuple[CategoryDef, ...] = (
    CategoryDef("medical", "First Aid & Medical", "medication"),
    CategoryDef("food", "Food & Water", "inventory"),
    CategoryDef("energy", "Power & Energy", "bolt"),
    CategoryDef("shelter", "Shelter & Construction", "foundation"),
    CategoryDef("mechanic", "Tools & Repair", "build"),
    CategoryDef("gardening", "Farming & Gardening", "potted_plant"),
    CategoryDef("animal_care", "Animals & Livestock", "pets"),
    CategoryDef("navigation", "Maps & Navigation", "map"),
    CategoryDef("communication", "Comms & Radio", "cell_tower"),
    CategoryDef("reference", "Knowledge & Reference", "menu_book"),
    CategoryDef("security", "Security & Defense", "security"),
)

CATEGORY_MAP: dict[str, CategoryDef] = {c.slug: c for c in CATEGORIES}
CATEGORY_SLUGS: frozenset[str] = frozenset(CATEGORY_MAP)

# Legacy category values found in pre-existing registries, mapped onto the fixed
# set. Applied transparently on load so old data keeps validating.
LEGACY_CATEGORY_MAP: dict[str, str] = {
    "maps": "navigation",
    "library": "reference",
    "internet": "reference",
    "packages": "reference",
}


def migrate_category(raw: str) -> str:
    """Map a legacy category value onto a canonical slug; pass through otherwise."""
    return LEGACY_CATEGORY_MAP.get(raw, raw)


# The fallback slug for anything that isn't a recognised category.
FALLBACK_CATEGORY = "reference"


def coerce_category(raw: str | None) -> str:
    """Best-effort map any input onto a valid slug, never raising.

    Used at import time so a malformed/unknown manifest category can't crash
    registration — the user's wizard choice is always a valid slug anyway.
    """
    slug = migrate_category(raw or "")
    return slug if slug in CATEGORY_MAP else FALLBACK_CATEGORY
