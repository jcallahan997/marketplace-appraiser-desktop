"""Furniture item type configuration."""

from typing import Any

from marketplace_appraiser.item_types._base import ItemTypeConfig


def parse_furniture_title(title: str) -> dict[str, Any]:
    """Extract brand, type, and material from a furniture listing title.

    Handles formats like:
        "West Elm Mid-Century Modern Sofa"
        "IKEA KALLAX Shelf Unit"
        "Pottery Barn Leather Sectional Couch"
        "Vintage Oak Dining Table and 6 Chairs"
    """
    if not title:
        return {"brand": None, "furniture_type": None, "material": None}

    text = title.strip()

    # Common furniture brands
    brands = [
        "West Elm", "Pottery Barn", "Crate & Barrel", "Crate and Barrel",
        "IKEA", "Restoration Hardware", "RH", "CB2", "Article", "Arhaus",
        "Ethan Allen", "La-Z-Boy", "Ashley", "Ashley Furniture",
        "Rooms To Go", "Wayfair", "Herman Miller", "Steelcase",
        "Room & Board", "Room and Board", "Joybird", "Burrow",
    ]

    brand = None
    rest = text
    for b in sorted(brands, key=len, reverse=True):
        if text.lower().startswith(b.lower()):
            brand = b
            rest = text[len(b):].strip()
            break

    # Detect furniture type keywords
    furniture_types = [
        "sectional", "sofa", "couch", "loveseat", "recliner", "chair",
        "armchair", "ottoman", "bench", "stool", "table", "desk",
        "dining table", "coffee table", "end table", "nightstand",
        "dresser", "chest", "wardrobe", "bookshelf", "shelf", "shelving",
        "cabinet", "hutch", "buffet", "credenza", "console",
        "bed", "bed frame", "headboard", "mattress", "futon",
        "rug", "mirror", "lamp", "chandelier",
    ]

    furniture_type = None
    rest_lower = rest.lower()
    for ft in sorted(furniture_types, key=len, reverse=True):
        if ft in rest_lower:
            furniture_type = ft.title()
            break

    # Detect material keywords
    materials = [
        "leather", "velvet", "linen", "fabric", "microfiber",
        "wood", "oak", "walnut", "maple", "pine", "teak", "bamboo",
        "metal", "steel", "iron", "brass", "chrome", "aluminum",
        "glass", "marble", "granite", "concrete", "rattan", "wicker",
    ]

    material = None
    for mat in materials:
        if mat in rest_lower:
            material = mat.title()
            break

    return {"brand": brand, "furniture_type": furniture_type, "material": material}


FURNITURE_CONFIG = ItemTypeConfig(
    name="furniture",
    display_name="Furniture",

    parse_title=parse_furniture_title,

    detail_labels=[
        "Condition", "Brand", "Color", "Material", "Dimensions", "Type",
    ],

    vision_role="a furniture buyer inspecting a used piece",
    vision_checklist="""\
- STRUCTURE: wobbling, sagging, broken joints, missing hardware, cracks
- UPHOLSTERY: stains, tears, pilling, fading, pet damage, odor indicators \
(pet hair visible, smoking environment clues)
- WOOD/SURFACE: scratches, water rings, sun fading, veneer peeling, \
finish wear, dents
- HARDWARE: drawer slides working, hinges intact, knobs/pulls present, \
missing screws
- CUSHIONS: sagging, flattening, uneven wear, removable covers
- LEGS/BASE: scratches from moving, uneven legs, floor protectors
- COMPLETENESS: all pieces present (sets), matching components
- QUALITY INDICATORS: dovetail joints, solid wood vs particle board, \
brand labels visible
- RED FLAGS: smoke smell indicators (yellowing), bed bug signs (black \
spots, shed skins), mold/mildew, structural cracks""",

    condition_role="a furniture condition analyst",
    condition_scale="LIKE NEW, GOOD, FAIR, or POOR",

    market_search_templates=[
        "{item_name} used price resale value",
        "{item_name} retail price new",
        "{item_name} review quality",
    ],

    fraud_patterns=[
        # Note: "smoke-free" and "pet-free" are NORMAL for furniture — not fraud signals
        (r"\bfirm on price\b|\bno low\s*ball", "aggressive pricing"),
        (r"\b\d{3}[-. )]+\d{3}[-. )]+\d{4}", "phone number in listing"),
        (r"\bwe deliver\b|\bdelivery available\b", "delivery offered — possible reseller"),
        (r"\bwarehouse\b|\bshowroom\b", "possible business seller"),
        (r"\bstock\s*#?\s*\d+", "stock number"),
        (r"\bwe\s+(finance|offer|have|accept)\b", "dealer language"),
    ],

    safety_api="cpsc",

    price_role="a furniture purchase advisor",
)
