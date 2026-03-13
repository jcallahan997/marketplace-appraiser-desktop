"""Node 4: Research fair market value using web search + LLM analysis."""

from marketplace_appraiser.item_types import get_config
from marketplace_appraiser.state import AppraisalState
from marketplace_appraiser.utils.llm import invoke_llm_light
from marketplace_appraiser.utils.search import safe_search


def _search_market_data(item_name: str, search_templates: list[str]) -> str:
    """Run DuckDuckGo searches for real pricing data and return combined results."""
    all_results = []

    for template in search_templates:
        query = template.format(item_name=item_name)
        results = safe_search(query, max_results=5)
        for r in results:
            title = r.get("title", "")
            body = r.get("body", "")
            href = r.get("href", "")
            all_results.append(f"[{title}]({href})\n{body}")

    if not all_results:
        return "(No web search results found — using LLM knowledge only)"

    return "\n\n".join(all_results)


def research_market(state: AppraisalState) -> dict:
    """LangGraph node: search the web for real pricing data, then analyze with LLM."""
    print(f"\n{'='*60}")
    print("STEP 4: Researching market value with web search")
    print(f"{'='*60}\n")

    item_name = state.get("item_name", "Unknown Item")
    item_type = state.get("item_type", "vehicle")
    config = get_config(item_type)
    item_fields = state.get("item_fields", {})

    listed_price = state.get("listed_price")
    location = state.get("location", "Unknown")
    description = state.get("description", "")
    condition_report = state.get("condition_report", "No condition report available")

    price_str = f"${listed_price:,.0f}" if listed_price else "Unknown"

    # Item-type-specific details line for the prompt
    item_details_str = ""
    if item_type == "vehicle":
        mileage = item_fields.get("mileage")
        item_details_str = f"\n- Mileage: {mileage:,} miles" if mileage else ""

    # --- Web search for real pricing data ---
    print("  Searching for market data...")
    search_results = _search_market_data(item_name, config.market_search_templates)
    result_count = search_results.count("[")
    print(f"  Found {result_count} search results")

    description_block = ""
    if description:
        description_block = f"""
SELLER'S DESCRIPTION (may contain value-relevant details):
{description}
"""

    from datetime import date as _date

    prompt = f"""\
You are a market research analyst for used {config.display_name.lower()} items. \
Use the web search results below AND your own knowledge to produce an accurate \
market value assessment.

Today's date: {_date.today().isoformat()}

ITEM DETAILS:
- Item: {item_name}
- Listed Price: {price_str}
- Location: {location}{item_details_str}
{description_block}
CONDITION ASSESSMENT:
{condition_report}

WEB SEARCH RESULTS (real listings, pricing data, and reviews):
{search_results}

Based on the search results and your knowledge, provide your analysis \
using these exact section headers:

## Market Value Range
The typical fair market value RANGE (low, mid, high) in USD for this \
specific item given its condition. Cite specific prices from search \
results where available.

## Price Assessment
How the listed price of {price_str} compares to the market range.

## Condition Impact
How the assessed condition affects value within that range.

## Description Red Flags
Any value-adds or red flags from the seller's description.

## Known Issues
Common issues known for this type of item.

## Value Factors
Any factors that significantly affect value (recalls, defects, \
high demand, collectibility, etc.).

Be specific with dollar amounts. When uncertain, provide wider ranges \
rather than false precision."""

    result = invoke_llm_light(prompt, temperature=0.3, max_tokens=2048)

    print(f"  Market analysis generated ({len(result)} chars)")
    return {"market_analysis": result}
