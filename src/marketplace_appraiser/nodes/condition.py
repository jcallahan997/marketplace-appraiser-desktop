"""Node 3: Synthesize image analyses into a condition report."""

from marketplace_appraiser.item_types import get_config
from marketplace_appraiser.state import AppraisalState
from marketplace_appraiser.utils.llm import invoke_llm
from marketplace_appraiser.utils.research import (
    format_research_findings,
    identify_options_from_photos,
    identify_research_questions,
    research_questions,
    search_available_options,
)


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

    listed_price = state.get("listed_price")
    description = state.get("description", "No description provided")
    condition_listed = state.get("condition_listed", "Not specified")
    image_paths = state.get("image_paths", [])

    price_str = f"${listed_price:,.0f}" if listed_price else "Unknown"

    # --- Step 1: Search for known options/packages ---
    print(f"  Searching for {item_name} options and packages...")
    known_options = search_available_options(item_name)
    if known_options:
        print(f"  Found options context ({len(known_options)} chars)")
    else:
        print("  No options context found")

    # --- Step 2: Vision scan for options visible in photos ---
    spotted_options = ""
    if image_paths:
        print("  Scanning photos for options not in description...")
        spotted_options = identify_options_from_photos(
            image_paths, description, item_name, known_options
        )
        if spotted_options and spotted_options.strip().upper() != "NONE":
            print(f"  Spotted options ({len(spotted_options)} chars)")
        else:
            spotted_options = ""
            print("  No additional options spotted")

    # --- Step 3: Identify claims and terms to research ---
    print("  Identifying claims and terms to research...")
    queries = identify_research_questions(
        description, image_analyses, item_name, spotted_options
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

    prompt = f"""\
You are {config.condition_role}. Review the following image \
analyses of a {item_name} and synthesize them into a \
comprehensive condition report.

Item: {item_name}
Listed Price: {price_str}
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
7. Any discrepancies between the seller's claims and what the photos show
8. Verified or debunked seller claims (based on research findings, if any)

Be specific and evidence-based. If the photos don't show enough to assess \
something, say so."""

    result = invoke_llm(prompt)

    print(f"  Condition report generated ({len(result)} chars)")
    return {
        "condition_report": result,
        "spotted_options": spotted_options,
        "description_research": research_block,
    }
