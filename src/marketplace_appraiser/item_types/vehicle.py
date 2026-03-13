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
# Model-code → manufacturer lookup (for titles missing the make)
# ---------------------------------------------------------------------------

_MODEL_CODE_EXPLICIT: dict[str, str] = {
    # Porsche (must precede BMW digit patterns)
    "911": "Porsche", "718": "Porsche", "boxster": "Porsche",
    "cayman": "Porsche", "cayenne": "Porsche", "panamera": "Porsche",
    "macan": "Porsche", "taycan": "Porsche",
    # Common standalone American model names
    "corvette": "Chevrolet", "camaro": "Chevrolet",
    "mustang": "Ford", "bronco": "Ford",
    "challenger": "Dodge", "charger": "Dodge",
    "wrangler": "Jeep", "gladiator": "Jeep",
    # Standalone keywords
    "amg": "Mercedes-Benz", "g-wagon": "Mercedes-Benz",
    "tt": "Audi", "r8": "Audi", "e-tron": "Audi",
}

# Mercedes: multi-letter prefix + 2-3 digits (E320, ML350, GLE450, CLA250)
_MERCEDES_MULTI = re.compile(
    r"^(?:CL[AKES]?|GL[ABCEKS]?|ML|SL[CKR]?)\d{2,3}$", re.I,
)
# Mercedes: single-letter class + 3 digits (A220, C300, E320, G500, S550)
_MERCEDES_SINGLE3 = re.compile(r"^[ACEGS]\d{3}$", re.I)
# Mercedes: single-letter class + 2 digits (C63, E55, G63, S65)
_MERCEDES_SINGLE2 = re.compile(r"^[CEGS]\d{2}$", re.I)
# BMW: 3 digits + optional letter suffix (325i, 528i, 740il)
_BMW_DIGITS = re.compile(r"^\d{3}[a-z]{0,2}$", re.I)
# BMW: letter-series (M3, X5, Z4, i4, iX)
_BMW_SERIES = re.compile(r"^[MXZI]\d{1,2}[a-z]?$", re.I)
# Audi: A/Q/S + digit (A4, Q5, S6) or RS + digit (RS3, RS7)
_AUDI_PATTERN = re.compile(r"^(?:[AQS]\d|RS\d)$", re.I)


def _lookup_make_from_model_code(code: str) -> str | None:
    """If *code* is a known model code, return the manufacturer name."""
    key = code.lower().strip()
    if key in _MODEL_CODE_EXPLICIT:
        return _MODEL_CODE_EXPLICIT[key]
    if _MERCEDES_MULTI.match(key) or _MERCEDES_SINGLE3.match(key) or _MERCEDES_SINGLE2.match(key):
        return "Mercedes-Benz"
    if _AUDI_PATTERN.match(key):
        return "Audi"
    # BMW last — digit patterns are broad; exclude known Porsche codes
    if key not in ("911", "718") and (_BMW_DIGITS.match(key) or _BMW_SERIES.match(key)):
        return "BMW"
    return None


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

    # Check if parsed "make" is actually a model code (e.g. E320 → Mercedes-Benz)
    real_make = _lookup_make_from_model_code(make)
    if real_make:
        rest = f"{make} {rest}".strip() if rest else make
        make = real_make

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
# Generation / chassis-code lookup
# ---------------------------------------------------------------------------

def lookup_vehicle_generation(year: int, make: str, model: str) -> dict | None:
    """Look up the generation/chassis code for a vehicle via LLM-light.

    Returns {"code": "W211", "name": "E-Class", "years": "2003-2009"}
    or None if unknown.
    """
    from marketplace_appraiser.utils.llm import invoke_llm_light

    prompt = f"""\
What is the generation or chassis code for a {year} {make} {model}?

Reply with ONLY a single line in this exact format:
CODE | COMMON_NAME | START_YEAR-END_YEAR

Examples:
W211 | E-Class | 2003-2009
E46 | 3 Series | 1999-2006
10th gen | Civic | 2016-2021
997 | 911 | 2005-2012
SN95 | Mustang | 1994-2004

Use the most widely recognized chassis/platform/generation code among \
enthusiasts and mechanics. COMMON_NAME should be the model family name \
(not the specific sub-model). If there is no well-known generation code, \
use a format like "3rd gen" or "Mk4".

If you truly cannot determine the generation, reply exactly: UNKNOWN"""

    try:
        raw = invoke_llm_light(prompt, temperature=0.0)
        line = raw.strip().splitlines()[0].strip()
        if line.upper() == "UNKNOWN":
            return None
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 3:
            return None
        return {"code": parts[0], "name": parts[1], "years": parts[2]}
    except Exception:
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
