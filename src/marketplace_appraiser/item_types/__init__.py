"""Item type registry and auto-detection."""

from marketplace_appraiser.item_types._base import ItemTypeConfig
from marketplace_appraiser.item_types.electronics import ELECTRONICS_CONFIG
from marketplace_appraiser.item_types.furniture import FURNITURE_CONFIG
from marketplace_appraiser.item_types.vehicle import VEHICLE_CONFIG

# Registry of all available item type configs
ITEM_TYPE_REGISTRY: dict[str, ItemTypeConfig] = {
    "vehicle": VEHICLE_CONFIG,
    "electronics": ELECTRONICS_CONFIG,
    "furniture": FURNITURE_CONFIG,
}


def get_config(item_type: str) -> ItemTypeConfig:
    """Look up an item type config by name. Raises KeyError if not found."""
    if item_type not in ITEM_TYPE_REGISTRY:
        available = ", ".join(sorted(ITEM_TYPE_REGISTRY.keys()))
        raise KeyError(
            f"Unknown item type '{item_type}'. Available: {available}"
        )
    return ITEM_TYPE_REGISTRY[item_type]


def detect_item_type(title: str, description: str = "") -> str:
    """Use the LLM to classify an item from its title and description.

    Returns one of the registered item type names (e.g. "vehicle").
    Falls back to "vehicle" if classification fails.
    """
    from marketplace_appraiser.utils.llm import invoke_llm

    available = ", ".join(sorted(ITEM_TYPE_REGISTRY.keys()))

    prompt = f"""\
Classify this Facebook Marketplace listing into one of these categories: {available}

Title: {title}
Description: {description[:500] if description else "(no description)"}

Output ONLY the category name, nothing else. If unsure, output "vehicle"."""

    try:
        result = invoke_llm(prompt, temperature=0.1).strip().lower()
        # Clean up any extra text the LLM might add
        for item_type in ITEM_TYPE_REGISTRY:
            if item_type in result:
                return item_type
    except Exception:
        pass

    return "vehicle"
