"""Generic parsing utilities for extracting structured data from listing text.

Vehicle-specific parsing (parse_title, extract_mileage, etc.) lives in
item_types/vehicle.py. This module contains only item-type-agnostic parsers.
"""

import re
from datetime import datetime
from typing import Optional


def parse_price(text: str) -> Optional[float]:
    """Extract a dollar price from text.

    Handles:
        "$15,000"
        "$8500"
        "Price: $12,500"
        "$3,200.00"
    """
    if not text:
        return None

    match = re.search(r"\$\s*([\d,]+(?:\.\d{2})?)", text)
    if match:
        return float(match.group(1).replace(",", ""))

    return None


def parse_listing_age(text: str) -> Optional[int]:
    """Convert Facebook listing age text to approximate days.

    Handles:
        "today"                -> 0
        "yesterday"            -> 1
        "about an hour ago"    -> 0
        "5 hours ago"          -> 0
        "2 days ago"           -> 2
        "3 weeks ago"          -> 21
        "2 months ago"         -> 60
        "a week ago"           -> 7
        "a month ago"          -> 30
        "January 15"           -> delta from today
        "March 2, 2025"        -> delta from today
    """
    if not text:
        return None

    t = text.strip().lower()

    if t == "today":
        return 0
    if t == "yesterday":
        return 1

    # "about an hour ago", "X hours ago"
    if "hour" in t:
        return 0

    # "a day ago"
    if t in ("a day ago", "1 day ago"):
        return 1

    # "X days ago"
    m = re.search(r"(\d+)\s*days?\s*ago", t)
    if m:
        return int(m.group(1))

    # "a week ago"
    if t in ("a week ago", "1 week ago"):
        return 7

    # "X weeks ago"
    m = re.search(r"(\d+)\s*weeks?\s*ago", t)
    if m:
        return int(m.group(1)) * 7

    # "a month ago"
    if t in ("a month ago", "1 month ago"):
        return 30

    # "X months ago"
    m = re.search(r"(\d+)\s*months?\s*ago", t)
    if m:
        return int(m.group(1)) * 30

    # Absolute date: "January 15" or "January 15, 2025" or "March 2, 2025"
    for fmt in ("%B %d, %Y", "%B %d %Y", "%B %d"):
        try:
            parsed = datetime.strptime(t.title(), fmt)
            # If no year in format, assume current year
            if "%Y" not in fmt:
                parsed = parsed.replace(year=datetime.now().year)
                # If parsed date is in the future, it was last year
                if parsed > datetime.now():
                    parsed = parsed.replace(year=datetime.now().year - 1)
            delta = (datetime.now() - parsed).days
            return max(0, delta)
        except ValueError:
            continue

    return None
