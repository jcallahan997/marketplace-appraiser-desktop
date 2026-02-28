"""Base item type configuration dataclass."""

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class ItemTypeConfig:
    """Configuration for a specific item type (vehicle, electronics, etc.).

    Each item type provides its own prompts, field definitions, fraud patterns,
    and search templates. The pipeline nodes use this config to customize their
    behavior without needing item-type-specific code paths.
    """

    # Identity
    name: str                         # e.g. "vehicle", "electronics", "furniture"
    display_name: str                 # e.g. "Vehicle", "Electronics", "Furniture"

    # Title parsing — callable that extracts structured fields from a listing title.
    # Returns a dict of extracted fields (e.g. {"year": 2015, "make": "Honda", ...}).
    # If None, no structured parsing is done and the raw title is used.
    parse_title: Optional[Callable[[str], dict[str, Any]]] = None

    # Detail extraction — JS expressions to extract item-specific structured data
    # from the listing page. Each key is a field name, value is a JS snippet that
    # returns the field value when evaluated in the page context.
    detail_labels: list[str] = field(default_factory=list)

    # Vision analysis prompt components
    vision_role: str = "a potential buyer"
    vision_checklist: str = ""        # Item-specific things to look for in photos

    # Condition assessment
    condition_role: str = "an item condition analyst"
    condition_scale: str = "EXCELLENT, GOOD, FAIR, or POOR"

    # Market research — search query templates. Use {item_name} as placeholder.
    market_search_templates: list[str] = field(default_factory=list)

    # Fraud/flip detection patterns — regex patterns to look for in descriptions.
    # Each tuple is (pattern, label).
    fraud_patterns: list[tuple[str, str]] = field(default_factory=list)

    # Safety API type — which safety database to check (if any).
    # "nhtsa" for vehicles, "cpsc" for furniture/consumer goods, None for skip.
    safety_api: Optional[str] = None

    # Price assessment prompt customization
    price_role: str = "a purchase advisor"

    # Email report section headers
    report_header_color: str = "#008080"
