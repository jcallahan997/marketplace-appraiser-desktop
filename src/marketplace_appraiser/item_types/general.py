"""General / catch-all item type configuration.

Used for items that don't fit the specific categories (vehicle, electronics,
furniture). Provides generic vision checklists, market search templates,
and fraud patterns that work for any consumer good.
"""

from typing import Any

from marketplace_appraiser.item_types._base import ItemTypeConfig


def parse_general_title(title: str) -> dict[str, Any]:
    """Passthrough parser — returns the title as-is.

    Unlike vehicle/electronics/furniture parsers, we don't attempt to
    extract structured fields from an unknown item type.
    """
    return {"title": title.strip() if title else ""}


GENERAL_CONFIG = ItemTypeConfig(
    name="general",
    display_name="General",

    parse_title=parse_general_title,

    detail_labels=[
        "Condition", "Brand", "Color", "Size", "Material", "Type",
    ],

    vision_role="a buyer inspecting a used item",
    vision_checklist="""\
- OVERALL CONDITION: signs of wear, damage, scratches, dents, stains, \
discoloration, fading
- COMPLETENESS: all parts/accessories present? Missing components?
- AUTHENTICITY: brand markings, labels, serial numbers, signs of \
counterfeiting or knockoff products
- DAMAGE: cracks, chips, tears, broken pieces, water damage, rust, \
corrosion
- QUALITY: build quality indicators, materials used, craftsmanship
- FUNCTIONALITY CLUES: does the item appear functional? Any visible \
defects that would impair use?
- PACKAGING/ACCESSORIES: original packaging, manuals, accessories \
included?
- RED FLAGS: signs of heavy use, improper storage, pest damage, \
smoke/odor indicators""",

    condition_role="an item condition analyst",
    condition_scale="LIKE NEW, GOOD, FAIR, or POOR",

    market_search_templates=[
        "{item_name} used price for sale",
        "{item_name} retail price new",
    ],

    fraud_patterns=[
        (r"\b\d{3}[-. )]+\d{3}[-. )]+\d{4}", "phone number in listing"),
        (r"\bfirm on price\b|\bno low\s*ball", "aggressive pricing language"),
        (r"\bas[- ]?is\b", "as-is"),
        (r"\bno returns?\b", "no returns"),
        (r"\bfinal sale\b", "final sale"),
        (r"\breplica\b|\bclone\b|\bknockoff\b", "possible counterfeit"),
        (r"\bwe\s+(finance|offer|have|accept)\b", "dealer language"),
        (r"\bstock\s*#?\s*\d+", "stock number"),
        (r"(?:must sell|need gone|has to go)\s+(?:today|tonight|asap|immediately|this week)",
         "high-pressure urgency"),
        (r"first come first served|won'?t last|serious (?:buyers|inquiries) only",
         "high-pressure sales language"),
    ],

    safety_api=None,

    price_role="a purchase advisor for used goods",
)
