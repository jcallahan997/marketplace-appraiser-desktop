"""Vehicle item type configuration — ported from vehicle_appraiser."""

import re
from datetime import datetime
from typing import Any, Optional

from marketplace_appraiser.item_types._base import ItemTypeConfig


# ---------------------------------------------------------------------------
# Multi-word automotive makes/models for title parsing
# ---------------------------------------------------------------------------

MULTI_WORD_MAKES = sorted(
    [
        "Land Rover",
        "Range Rover",
        "Mercedes-Benz",
        "Mercedes Benz",
        "Alfa Romeo",
        "Rolls-Royce",
        "Rolls Royce",
        "Aston Martin",
        "AM General",
    ],
    key=len,
    reverse=True,
)

MULTI_WORD_MODELS: dict[str, list[str]] = {
    "land rover": ["Range Rover Sport", "Range Rover Velar", "Range Rover"],
}


# ---------------------------------------------------------------------------
# Title parser
# ---------------------------------------------------------------------------

def parse_vehicle_title(title: str) -> dict[str, Any]:
    """Extract year, make, model, and trim from a vehicle listing title.

    Returns dict with keys: year, make, model, trim (any may be None).
    """
    if not title:
        return {"year": None, "make": None, "model": None, "trim": None}

    text = title.strip()

    # Extract year (must start with 4 digits)
    year_match = re.match(r"(\d{4})\s+", text)
    if not year_match:
        return {"year": None, "make": None, "model": None, "trim": None}

    year = int(year_match.group(1))
    if year < 1900 or year > datetime.now().year + 2:
        return {"year": None, "make": None, "model": None, "trim": None}

    rest = text[year_match.end():]

    # Try multi-word makes first (case-insensitive)
    make = None
    for mw_make in MULTI_WORD_MAKES:
        if rest.lower().startswith(mw_make.lower()):
            make = mw_make
            rest = rest[len(mw_make):].lstrip()
            break

    # Fall back to single-word make
    if make is None:
        parts = rest.split(None, 1)
        if not parts:
            return {"year": year, "make": None, "model": None, "trim": None}
        make = parts[0]
        rest = parts[1] if len(parts) > 1 else ""

    # Try multi-word models for this make
    model = None
    mw_models = MULTI_WORD_MODELS.get((make or "").lower(), [])
    for mw_model in mw_models:
        if rest.lower().startswith(mw_model.lower()):
            model = mw_model
            rest = rest[len(mw_model):].lstrip()
            break

    # Fall back to single-word model
    if model is None:
        model_match = re.match(r"(\S+(?:-\S+)?)\s*(.*)", rest)
        if not model_match:
            return {"year": year, "make": make, "model": None, "trim": None}
        model = model_match.group(1)
        rest = model_match.group(2).strip()

    trim = rest if rest else None

    return {"year": year, "make": make, "model": model, "trim": trim}


def extract_mileage(text: str) -> Optional[int]:
    """Extract mileage from free-form text."""
    if not text:
        return None

    match = re.search(r"Driven\s+([\d,]+)\s*miles", text, re.IGNORECASE)
    if match:
        return int(match.group(1).replace(",", ""))

    match = re.search(r"([\d,]+)\s*(?:miles|mi\b)", text, re.IGNORECASE)
    if match:
        return int(match.group(1).replace(",", ""))

    match = re.search(r"(\d+)\s*k\s*(?:miles|mi\b)", text, re.IGNORECASE)
    if match:
        return int(match.group(1)) * 1000

    match = re.search(r"(?:mileage|odometer)\s*[:=]\s*([\d,]+)", text, re.IGNORECASE)
    if match:
        return int(match.group(1).replace(",", ""))

    return None


# ---------------------------------------------------------------------------
# Config instance
# ---------------------------------------------------------------------------

VEHICLE_CONFIG = ItemTypeConfig(
    name="vehicle",
    display_name="Vehicle",

    parse_title=parse_vehicle_title,

    detail_labels=[
        "Drivetrain", "Fuel type", "Transmission", "Mileage", "Condition",
        "Color", "Body style", "Clean title", "Type", "Exterior color",
        "Interior color",
    ],

    vision_role="a used car inspector",
    vision_checklist="""\
- BODY: dents, scratches, rust, paint fade, mismatched panels (repaint \
after accident), sagging body lines, gaps between panels
- WHEELS/TIRES: tread depth, uneven wear (alignment issues), curb rash, \
mismatched tires, spare tire in use
- GLASS: chips, cracks, foggy headlights/taillights
- INTERIOR: seat wear/tears, dashboard cracks, stains, aftermarket \
modifications, warning lights on dash, odometer reading
- UNDERBODY/ENGINE: leaks, corrosion, aftermarket parts, missing covers
- POSITIVES: clean paint, new tires, well-maintained interior, original \
parts, recent maintenance evidence
- PLATES/TAGS: Is there a license plate visible, or is it missing/removed? \
Are there temporary/paper tags, dealer plates, or drive-out tags? Does the \
background look like a dealer lot (multiple cars, commercial setting, \
professional staging)? Note any "for sale" signage style.""",

    condition_role="a senior vehicle condition analyst",
    condition_scale="EXCELLENT, GOOD, FAIR, or POOR",

    market_search_templates=[
        "{item_name} for sale price",
        "{item_name} Kelley Blue Book value",
        "{item_name} common problems reliability",
    ],

    fraud_patterns=[
        (r"call or text", "call or text"),
        (r"\b\d{3}[-. )]+\d{3}[-. )]+\d{4}", "phone number"),
        (r"\bas[- ]?is\b", "as-is"),
        (r"\bno warranty\b", "no warranty"),
        (r"\bstock\s*#?\s*\d+", "stock number"),
        (r"\bwe\s+(finance|offer|have|accept)\b", "dealer language"),
        (r"\bdealer\b", "dealer"),
        (r"\bin[- ]house financing\b", "in-house financing"),
        (r"\bbuy here pay here\b", "buy here pay here"),
        # Curbstoner / flipper signals
        (r"selling for (?:a |my )?(?:friend|family|relative|buddy|coworker)",
         "selling for friend/family"),
        (r"(?:must sell|need gone|has to go)\s+(?:today|tonight|asap|immediately|this week)",
         "high-pressure urgency"),
        (r"first come first served|won'?t last|serious (?:buyers|inquiries) only",
         "high-pressure sales language"),
        (r"clean title in hand", "over-emphasis on clean title"),
        (r"sold\s+as\s*[-]?\s*is\s+where\s*[-]?\s*is",
         "legal 'sold as is where is' language"),
        (r"\bruns and drives\b", "minimalist 'runs and drives' claim"),
        (r"\bneeds nothing\b|\bturn[- ]key\b", "vague positive claims"),
        (r"[\w.-]+@[\w.-]+\.\w{2,}", "email address in description"),
        (r"\bfirm on price\b|\bno low\s*ball", "aggressive pricing language"),
    ],

    safety_api="nhtsa",

    price_role="a vehicle purchase advisor",
)
