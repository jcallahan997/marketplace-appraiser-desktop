"""Electronics item type configuration."""

import re
from typing import Any

from marketplace_appraiser.item_types._base import ItemTypeConfig


def parse_electronics_title(title: str) -> dict[str, Any]:
    """Extract brand, model, and specs from an electronics listing title.

    Handles formats like:
        "Apple MacBook Pro 16-inch M2 Max"
        "Samsung 65\" QLED 4K Smart TV"
        "Sony PlayStation 5 Digital Edition"
        "iPhone 15 Pro Max 256GB"
    """
    if not title:
        return {"brand": None, "product": None, "specs": None}

    text = title.strip()

    # Common electronics brands (case-insensitive match)
    brands = [
        "Apple", "Samsung", "Sony", "LG", "Dell", "HP", "Lenovo", "Asus",
        "Acer", "Microsoft", "Google", "Nintendo", "Canon", "Nikon",
        "Bose", "JBL", "Sonos", "Dyson", "KitchenAid", "iRobot",
        "Garmin", "Fitbit", "Roku", "Xbox", "PlayStation", "Meta",
        "OnePlus", "Motorola", "Nothing", "Razer", "Corsair", "Logitech",
    ]

    brand = None
    rest = text
    for b in brands:
        if text.lower().startswith(b.lower()):
            brand = b
            rest = text[len(b):].strip()
            break

    if brand is None:
        parts = text.split(None, 1)
        brand = parts[0] if parts else None
        rest = parts[1] if len(parts) > 1 else ""

    # Try to split remaining into product name and specs
    # Specs often start with a number (e.g. "256GB", "65\"", "16-inch")
    spec_match = re.search(r"\b(\d+\s*(?:GB|TB|inch|\"|\'))", rest, re.IGNORECASE)
    if spec_match:
        product = rest[:spec_match.start()].strip() or rest
        specs = rest[spec_match.start():].strip() if spec_match.start() > 0 else None
    else:
        product = rest
        specs = None

    return {"brand": brand, "product": product or None, "specs": specs}


ELECTRONICS_CONFIG = ItemTypeConfig(
    name="electronics",
    display_name="Electronics",

    parse_title=parse_electronics_title,

    detail_labels=[
        "Condition", "Brand", "Model", "Color", "Storage", "Memory",
        "Screen size", "Processor", "Battery",
    ],

    vision_role="an electronics buyer inspecting a used device",
    vision_checklist="""\
- SCREEN: scratches, dead pixels, discoloration, burn-in, cracks
- BODY/HOUSING: dents, scratches, scuffs, missing screws, warping
- PORTS/BUTTONS: damage, debris, corrosion, missing port covers
- ACCESSORIES: original charger, cables, box, documentation included?
- COSMETIC: overall wear level, yellowing on white plastics
- FUNCTIONALITY CLUES: is the device powered on? What's on screen?
- SERIAL/MODEL NUMBERS: visible serial numbers, model identifiers
- COMPLETENESS: all components present? Missing parts?
- RED FLAGS: signs of water damage (stickers, corrosion), \
unauthorized repairs, mismatched parts, third-party components""",

    condition_role="an electronics condition analyst",
    condition_scale="LIKE NEW, GOOD, FAIR, or POOR",

    market_search_templates=[
        "{item_name} used price",
        "{item_name} refurbished price buy",
    ],

    fraud_patterns=[
        (r"\bas[- ]?is\b", "as-is"),
        (r"\bno returns?\b", "no returns"),
        (r"\bfinal sale\b", "final sale"),
        (r"\breplica\b|\bclone\b", "possible counterfeit"),
        (r"\brefurbished\b(?!.*by (?:apple|samsung|manufacturer))",
         "third-party refurbished"),
        (r"\blocked\b|\bicloud\b|\bfrp\b", "possibly locked device"),
        (r"\bparts only\b|\bfor parts\b", "for parts only"),
        (r"\bno charger\b|\bno cable\b", "missing accessories"),
        (r"\bcracked screen\b", "cracked screen"),
        (r"\b\d{3}[-. )]+\d{3}[-. )]+\d{4}", "phone number in listing"),
    ],

    safety_api=None,

    price_role="an electronics purchase advisor",
)
