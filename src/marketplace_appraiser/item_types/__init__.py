"""Item type registry and auto-detection."""

from marketplace_appraiser.item_types._base import ItemTypeConfig
from marketplace_appraiser.item_types.electronics import ELECTRONICS_CONFIG
from marketplace_appraiser.item_types.furniture import FURNITURE_CONFIG
from marketplace_appraiser.item_types.general import GENERAL_CONFIG
from marketplace_appraiser.item_types.vehicle import VEHICLE_CONFIG

# Registry of all available item type configs
ITEM_TYPE_REGISTRY: dict[str, ItemTypeConfig] = {
    "vehicle": VEHICLE_CONFIG,
    "electronics": ELECTRONICS_CONFIG,
    "furniture": FURNITURE_CONFIG,
    "general": GENERAL_CONFIG,
}


def get_config(item_type: str) -> ItemTypeConfig:
    """Look up an item type config by name.

    Returns GENERAL_CONFIG for unknown item types instead of raising.
    """
    return ITEM_TYPE_REGISTRY.get(item_type, GENERAL_CONFIG)


def detect_item_type(title: str, description: str = "") -> str:
    """Use the LLM to classify an item from its title and description.

    Returns one of the registered item type names (e.g. "vehicle").
    Falls back to "general" if classification fails or the item doesn't
    fit any specific category.
    """
    from marketplace_appraiser.utils.llm import invoke_llm

    # Specific categories (excluding "general" — it's the catch-all)
    specific = ", ".join(sorted(k for k in ITEM_TYPE_REGISTRY if k != "general"))

    prompt = f"""\
Classify this Facebook Marketplace listing into one of these categories: {specific}, general

Title: {title}
Description: {description[:500] if description else "(no description)"}

Use "general" for items that don't clearly fit vehicle, electronics, or \
furniture (e.g. clothing, sporting goods, musical instruments, tools, \
toys, collectibles, bicycles, appliances, etc.).

Output ONLY the category name, nothing else."""

    try:
        result = invoke_llm(prompt, temperature=0.1).strip().lower()
        # Clean up any extra text the LLM might add
        for item_type in ITEM_TYPE_REGISTRY:
            if item_type in result:
                return item_type
    except Exception:
        pass

    return "general"
