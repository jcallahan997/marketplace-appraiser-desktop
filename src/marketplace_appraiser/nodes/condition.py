"""Node 3: Synthesize image analyses into a condition report."""

from marketplace_appraiser.item_types import get_config
from marketplace_appraiser.state import AppraisalState
from marketplace_appraiser.utils.llm import invoke_llm, invoke_llm_light
from marketplace_appraiser.utils.research import (
    format_research_findings,
    identify_research_questions,
    research_questions,
    search_available_options,
)


def _extract_options_from_analyses(
    image_analyses: list[str],
    description: str,
    item_name: str,
    known_options: str = "",
) -> str:
    """Extract options from existing image analyses via Haiku (no vision call).

    Instead of re-analyzing images with Sonnet vision, this reads the text
    of analyses already produced by the vision node and identifies options
    the seller didn't mention.
    """
    if not image_analyses:
        return ""

    combined = "\n".join(
        f"Photo {i + 1}: {a}" for i, a in enumerate(image_analyses)
    )

    known_section = ""
    if known_options:
        known_section = f"""

KNOWN AVAILABLE OPTIONS for this item (from web research):
{known_options[:2000]}

Use this list to identify which options are mentioned in the photo analyses.\
"""

    prompt = f"""\
Review these photo analyses of a {item_name} listing and identify any \
options, features, or equipment mentioned that the seller did NOT include \
in their description.
{known_section}
SELLER'S DESCRIPTION:
{description or "(No description provided)"}

PHOTO ANALYSES:
{combined}

List options/features visible in photos but not in description, one per line.
If none, output exactly: NONE"""

    return invoke_llm_light(prompt, temperature=0.2, max_tokens=512)


def assess_condition(state: AppraisalState) -> dict:
    """LangGraph node: synthesize image analyses into a condition report."""
    print(f"\n{'='*60}")
    print("STEP 3: Synthesizing condition report")
    print(f"{'='*60}\n")

    image_analyses = state.get("image_analyses", [])
    image_analyses_text = ""
    for i, analysis in enumerate(image_analyses):
        image_analyses_text += f"\n--- Image {i + 1} ---\n{analysis}\n"

    item_name = state.get("item_name", "Unknown Item")
    item_type = state.get("item_type", "vehicle")
    config = get_config(item_type)
    item_fields = state.get("item_fields", {})

    listed_price = state.get("listed_price")
    description = state.get("description", "No description provided")
    condition_listed = state.get("condition_listed", "Not specified")
    image_paths = state.get("image_paths", [])

    price_str = f"${listed_price:,.0f}" if listed_price else "Unknown"

    # Build item-type-specific details line for the prompt
    item_details_str = ""
    if item_type == "vehicle":
        mileage = item_fields.get("mileage")
        mileage_str = f"{mileage:,} miles" if mileage else "Unknown"
        item_details_str = f"\nMileage: {mileage_str}"

    generation = item_fields.get("generation")

    # --- Step 1: Search for known options/packages ---
    print(f"  Searching for {item_name} options and packages...")
    known_options = search_available_options(item_name, generation=generation)
    if known_options:
        print(f"  Found options context ({len(known_options)} chars)")
    else:
        print("  No options context found")

    # --- Step 2: Extract options from existing image analyses (Haiku text) ---
    spotted_options = ""
    if image_analyses:
        print("  Extracting options from image analyses (Haiku text)...")
        spotted_options = _extract_options_from_analyses(
            image_analyses, description, item_name, known_options
        )
        if spotted_options and spotted_options.strip().upper() != "NONE":
            print(f"  Spotted options ({len(spotted_options)} chars)")
        else:
            spotted_options = ""
            print("  No additional options spotted")

    # --- Step 3: Identify claims and terms to research ---
    print("  Identifying claims and terms to research...")
    queries = identify_research_questions(
        description, image_analyses, item_name, spotted_options,
        generation=generation,
    )

    research_block = ""
    if queries:
        print(f"  Researching {len(queries)} questions:")
        for q in queries:
            print(f"    - {q}")
        findings = research_questions(queries)
        research_block = format_research_findings(findings)
        if research_block:
            print(f"  Research complete ({len(research_block)} chars)")
        else:
            print("  No useful research results found")
    else:
        print("  Nothing flagged for follow-on research")

    # --- Step 4: Build condition synthesis prompt ---
    options_section = ""
    if spotted_options:
        options_section = f"""

OPTIONS/FEATURES SPOTTED IN PHOTOS (not mentioned in seller's description):
{spotted_options}

Include these in your assessment — they may add significant value.\
"""

    research_section = ""
    if research_block:
        research_section = f"""

FOLLOW-ON RESEARCH (web search results verifying claims and unknowns):
{research_block}

Use these research findings to validate or challenge the seller's claims.\
"""

    mileage_condition_check = ""
    if item_type == "vehicle" and item_fields.get("mileage"):
        mileage = item_fields["mileage"]
        mileage_str = f"{mileage:,} miles"
        mileage_condition_check = (
            f"\n8. Whether the condition is reasonable for {mileage_str} "
            f"on this type of vehicle"
        )

    from datetime import date as _date

    prompt = f"""\
You are {config.condition_role}. Review the following image \
analyses of a {item_name} and synthesize them into a \
comprehensive condition report.

Today's date: {_date.today().isoformat()}

Item: {item_name}
Listed Price: {price_str}{item_details_str}
Seller's description: {description}
Seller-listed condition: {condition_listed}

Image analyses from visual inspection:
{image_analyses_text}
{options_section}{research_section}
Based on ALL of this information, provide:
1. An overall condition rating: {config.condition_scale}
2. Exterior/surface condition summary
3. Interior/functional condition summary (if visible in any photos)
4. Notable options and equipment (including those spotted in photos \
but not mentioned in the listing)
5. List of notable issues or concerns
6. List of notable positives
7. Any discrepancies between the seller's claims and what the photos show{mileage_condition_check}

Be specific and evidence-based. If the photos don't show enough to assess \
something, say so."""

    result = invoke_llm(prompt)

    print(f"  Condition report generated ({len(result)} chars)")
    return {
        "condition_report": result,
        "spotted_options": spotted_options,
        "description_research": research_block,
    }
