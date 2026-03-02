"""Shared state flowing through all nodes in the appraisal pipeline."""

from typing import Any, Optional

from typing_extensions import TypedDict


class AppraisalState(TypedDict):
    """Shared state flowing through all nodes in the appraisal graph."""

    # Input
    listing_url: str
    item_type: Optional[str]          # "vehicle", "electronics", "furniture", etc.

    # Scraper output
    title: str
    item_name: str                    # Human-readable name (e.g. "2015 Honda Civic LX")
    item_fields: dict[str, Any]       # Type-specific extracted fields
    listed_price: Optional[float]
    description: str
    location: Optional[str]
    condition_listed: Optional[str]
    listing_age_text: Optional[str]
    listing_age_days: Optional[int]
    image_paths: list[str]

    # Seller info (from scraper)
    seller_name: Optional[str]
    seller_rating: Optional[str]
    seller_joined: Optional[str]
    seller_listings: Optional[str]
    seller_profile_url: Optional[str]

    # Seller investigation output (from seller node)
    seller_profile: Optional[dict]
    seller_active_listings: list[dict]
    seller_investigation: Optional[str]
    seller_risk_level: Optional[str]

    # Vision output
    image_analyses: list[str]
    flip_signals: list[str]

    # Condition synthesis output
    condition_report: str
    spotted_options: Optional[str]
    description_research: Optional[str]

    # Market research output
    market_analysis: str

    # Safety info
    safety_info: Optional[str]

    # Final output
    price_assessment: str
    seller_ethnicity: Optional[str]
    seller_ethnicity_reasoning: Optional[str]
    flip_risk_level: Optional[str]
    flip_risk_summary: Optional[str]

    # Email output
    email_to: Optional[str]
    email_sent: bool
    email_summary: str
