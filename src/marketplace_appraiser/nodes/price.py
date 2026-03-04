"""Node 6: Final price assessment and recommendation."""

import re
from datetime import datetime

from marketplace_appraiser.item_types import get_config
from marketplace_appraiser.state import AppraisalState
from marketplace_appraiser.utils.llm import invoke_llm
from marketplace_appraiser.utils.safety_apis import check_safety
from marketplace_appraiser.utils.search import safe_search


# ---------------------------------------------------------------------------
# Seller ethnicity inference (informational only)
# ---------------------------------------------------------------------------

def _infer_seller_ethnicity(name: str) -> tuple[str, str]:
    """Infer likely ethnicity from the seller's name using web search + LLM.

    Returns (background_label, reasoning) where:
    - background_label is a short 3-10 word label (e.g. "Polish or Polish-American")
    - reasoning is a 2-3 sentence explanation citing web research

    This is informational context for the buyer only — NOT used in the
    price assessment prompt or recommendations.
    """
    if not name:
        return "", ""

    # Split name into parts for targeted searches
    parts = name.strip().split()
    given_name = parts[0] if parts else ""
    surname = parts[-1] if len(parts) > 1 else ""

    # Web search for name origins
    search_context = ""
    if surname:
        results = safe_search(f'"{surname}" surname origin ethnicity', max_results=3)
        snippets = [r.get("body", "") for r in results if r.get("body")]
        if snippets:
            search_context += f"Surname research for \"{surname}\":\n"
            search_context += "\n".join(f"- {s[:300]}" for s in snippets[:3])
            search_context += "\n\n"

    if given_name and given_name != surname:
        results = safe_search(f'"{given_name}" name origin meaning', max_results=3)
        snippets = [r.get("body", "") for r in results if r.get("body")]
        if snippets:
            search_context += f"Given name research for \"{given_name}\":\n"
            search_context += "\n".join(f"- {s[:300]}" for s in snippets[:3])
            search_context += "\n\n"

    prompt = f"""\
Analyze the name "{name}" and infer the most likely specific ethnic, \
cultural, or regional background. Use the web research below AND your \
knowledge of global naming conventions.

WEB RESEARCH ON THIS NAME:
{search_context if search_context else "(no web results found)"}

Naming convention guidance:
- **Surname patterns**: "-ez" = Spanish patronymic; "-ski/-ska" = Polish; \
  "-ov/-ova" = Slavic; "-ian/-yan" = Armenian; "O'" = Irish; "Mc/Mac" = \
  Scottish/Irish; "-sen/-son" = Scandinavian; "-ić" = South Slavic; \
  "Al-/El-" = Arabic; "Van/Von" = Dutch/German; "-escu" = Romanian; \
  "-nen" = Finnish; "-oğlu" = Turkish; "-dze/-shvili" = Georgian.
- **Given names**: cultural/religious traditions (Muhammad/Fatima = Muslim; \
  Moshe/Yael = Jewish; Priya/Arjun = Hindu; Singh/Kaur = Sikh).
- **Regional specificity**: Mexican vs. Colombian; Yoruba vs. Igbo; \
  North Indian vs. South Indian; Ashkenazi vs. Sephardic Jewish.
- **Common American names**: "Smith", "Johnson", "Williams" are common \
  across white and Black Americans — note the ambiguity.

Output format — exactly two sections:
BACKGROUND: <specific background, 3-10 words>
REASONING: <2-3 sentences explaining your inference, citing the web \
research findings where relevant>

Be specific. "West African (likely Nigerian Yoruba)" > "African". \
"Mexican or Central American" > "Hispanic". If ambiguous, say so."""

    try:
        result = invoke_llm(prompt, temperature=0.1)

        background = ""
        reasoning = ""

        # Parse BACKGROUND line
        bg_match = re.search(
            r"BACKGROUND:\s*(.+?)(?:\n|$)", result, re.IGNORECASE
        )
        if bg_match:
            background = bg_match.group(1).strip()

        # Parse REASONING section (everything after REASONING:)
        reason_match = re.search(
            r"REASONING:\s*(.+)", result, re.IGNORECASE | re.DOTALL
        )
        if reason_match:
            reasoning = reason_match.group(1).strip()

        # Fallback: if no structured output, use full result as background
        if not background:
            background = result.strip().split("\n")[0].strip()

        return background, reasoning

    except Exception:
        return "", ""


# ---------------------------------------------------------------------------
# Flip detection helpers
# ---------------------------------------------------------------------------

def _detect_data_flip_signals(state: dict, fraud_patterns: list[tuple[str, str]]) -> list[str]:
    """Detect flip indicators from scraped listing data."""
    signals = []

    # Many marketplace listings
    listings_str = state.get("seller_listings", "")
    if listings_str:
        try:
            first_num = re.search(r"\d+", listings_str)
            if not first_num:
                raise ValueError("no digits")
            count = int(first_num.group())
            if count > 10:
                signals.append(
                    f"DATA: Seller has {count} active listings — likely dealer/reseller"
                )
            elif count > 5:
                signals.append(
                    f"DATA: Seller has {count} active listings — possible reseller"
                )
        except (ValueError, TypeError):
            pass

    # New Facebook account
    joined = state.get("seller_joined", "")
    if joined:
        try:
            years_on_fb = datetime.now().year - int(joined)
            if years_on_fb <= 2:
                signals.append(
                    f"DATA: Relatively new Facebook account (joined {joined}, "
                    f"~{years_on_fb} year(s))"
                )
        except (ValueError, TypeError):
            pass

    # Config-driven fraud patterns in description
    description = state.get("description", "")
    if description:
        desc_lower = description.lower()
        for pattern, label in fraud_patterns:
            if re.search(pattern, desc_lower, re.IGNORECASE):
                signals.append(
                    f"DATA: Description contains suspicious language ('{label}')"
                )
                break  # one signal from description patterns is enough

    # Dealer pricing: prices ending just below a round thousand
    # e.g. $12,995, $14,999, $9,998 — NOT normal round amounts
    # like $1,250, $2,500, $3,750 which are typical private-sale prices
    listed_price_val = state.get("listed_price")
    if listed_price_val and listed_price_val > 1000:
        last_digits = int(listed_price_val) % 1000
        if last_digits in (990, 995, 998, 999):
            signals.append(
                f"DATA: Price ${listed_price_val:,.0f} uses dealer-style "
                f"pricing (ends in {last_digits})"
            )

    return signals


def _assess_flip_risk(signals: list[str]) -> tuple[str, str]:
    """Aggregate flip signals into a risk level and summary."""
    if not signals:
        return "NONE", ""

    vision_count = sum(1 for s in signals if s.startswith("VISION:"))
    data_count = sum(1 for s in signals if s.startswith("DATA:"))
    web_count = sum(1 for s in signals if s.startswith("WEB:"))
    total = len(signals)

    if total >= 5 or (vision_count >= 3 and data_count >= 2):
        level = "HIGH"
    elif total >= 3 or (web_count >= 2):
        level = "MEDIUM"
    elif total >= 1:
        level = "LOW"
    else:
        level = "NONE"

    summary = f"Flip risk: {level} ({total} indicator(s) found)\n"
    for signal in signals:
        summary += f"  - {signal}\n"

    return level, summary


# ---------------------------------------------------------------------------
# Main price assessment node
# ---------------------------------------------------------------------------

def assess_price(state: AppraisalState) -> dict:
    """LangGraph node: produce final price assessment with recommendation."""
    print(f"\n{'='*60}")
    print("STEP 6: Generating price assessment")
    print(f"{'='*60}\n")

    item_name = state.get("item_name", "Unknown Item")
    item_type = state.get("item_type", "vehicle")
    config = get_config(item_type)
    item_fields = state.get("item_fields", {})

    listed_price = state.get("listed_price", "Unknown")
    location = state.get("location", "Unknown")
    description = state.get("description", "")
    condition_report = state.get("condition_report", "")
    market_analysis = state.get("market_analysis", "")
    seller_name = state.get("seller_name", "")
    seller_rating = state.get("seller_rating", "")
    seller_joined = state.get("seller_joined", "")
    seller_listings = state.get("seller_listings", "")

    # --- Seller summary line ---
    seller_line = ""
    if seller_name or seller_rating:
        parts = []
        if seller_name:
            parts.append(seller_name)
        if seller_rating:
            parts.append(f"rated {seller_rating}")
        if seller_joined:
            parts.append(f"joined Facebook in {seller_joined}")
        if seller_listings:
            parts.append(f"{seller_listings} marketplace listings")
        seller_line = f"\n- Seller: {', '.join(parts)}"

    # --- Seller investigation context ---
    seller_investigation = state.get("seller_investigation", "")
    seller_risk_level = state.get("seller_risk_level", "")
    seller_context = ""
    if seller_investigation:
        seller_context = f"""
SELLER INVESTIGATION:
{seller_investigation}

Seller Risk Level: {seller_risk_level}
"""

    # --- Build seller trust warning for low ratings ---
    seller_warning = ""
    if seller_rating:
        try:
            rating_num = float(seller_rating.split("/")[0])
            if rating_num < 4.0:
                seller_warning = f"""
SELLER TRUST WARNING:
The seller's rating is {seller_rating}, which is below 4.0/5. This is a \
significant red flag. Factor this heavily into your recommendation.\
"""
        except (ValueError, IndexError):
            pass

    # New account warning
    account_warning = ""
    if seller_joined:
        try:
            years_on_fb = datetime.now().year - int(seller_joined)
            if years_on_fb <= 2:
                account_warning = f"""
NEW ACCOUNT WARNING:
The seller joined Facebook in {seller_joined} (~{years_on_fb} year(s) ago). \
Newer accounts selling items are a common scam pattern.\
"""
        except (ValueError, TypeError):
            pass

    # --- Stale listing warning ---
    listing_age_warning = ""
    listing_age_days = state.get("listing_age_days")
    listing_age_text = state.get("listing_age_text", "")
    if listing_age_days is not None and listing_age_days > 30:
        listing_age_warning = f"""
STALE LISTING WARNING:
This item has been listed for {listing_age_text} (approximately \
{listing_age_days} days). This is a negotiation advantage — factor it \
into your recommendation.\
"""

    # --- Flip detection ---
    flip_signals = list(state.get("flip_signals", []))

    print("  Checking for flip/reseller indicators...")
    data_signals = _detect_data_flip_signals(state, config.fraud_patterns)
    flip_signals.extend(data_signals)

    flip_risk_level, flip_risk_summary = _assess_flip_risk(flip_signals)
    if flip_risk_level != "NONE":
        print(f"  Flip risk: {flip_risk_level}")
        for sig in flip_signals:
            print(f"    - {sig}")
    else:
        print("  No flip risk detected")

    flip_block = ""
    if flip_risk_level and flip_risk_level != "NONE":
        flip_block = f"""
FLIP/RESELLER RISK ASSESSMENT:
{flip_risk_summary}

FLIP RISK GUIDANCE:
- If flip risk is HIGH: default to NEGOTIATE with caution. Only recommend \
PASS if there are ALSO other serious red flags (very low seller trust, \
missing key info, suspicious pricing). A legitimate dealer listing with \
transparent disclosure is NOT a reason to PASS.
- If flip risk is MEDIUM: note it as a caution but let price/condition \
analysis drive the recommendation. NEGOTIATE is often appropriate.
- If flip risk is LOW: this is a MINOR concern only. It should NOT override \
price and condition analysis. If the price is at or below fair market value \
and seller reputation is good, you CAN recommend BUY.
- A listing from a disclosed dealer or business is NOT inherently deceptive. \
Judge it on price and condition like any other listing.\
"""

    # --- Seller ethnicity (informational only — not used in prompt) ---
    seller_ethnicity = ""
    seller_ethnicity_reasoning = ""
    if seller_name:
        print(f"  Inferring seller background: {seller_name}...")
        seller_ethnicity, seller_ethnicity_reasoning = _infer_seller_ethnicity(seller_name)
        if seller_ethnicity:
            print(f"  Seller background: {seller_ethnicity}")
        if seller_ethnicity_reasoning:
            print(f"  Reasoning: {seller_ethnicity_reasoning[:200]}")

    # --- Safety checks ---
    print("  Running safety checks...")
    safety_info = check_safety(config.safety_api, item_fields, item_name)
    safety_block = ""
    if safety_info:
        safety_block = f"""
{safety_info}
Open safety recalls affect the item's value and the buyer's safety. \
Factor recall severity into your recommendation.\
"""

    description_block = ""
    if description:
        description_block = f"""
SELLER'S DESCRIPTION:
{description}
"""

    # Follow-on research from condition node
    description_research = state.get("description_research", "")
    research_block = ""
    if description_research:
        research_block = f"""
FOLLOW-ON RESEARCH (verified claims from description & photos):
{description_research}
"""

    prompt = f"""\
You are {config.price_role}. Produce a final price assessment for \
this listing.

ITEM DETAILS:
- Item: {item_name}
- Listed Price: ${listed_price}
- Location: {location}{seller_line}
{seller_warning}{account_warning}{listing_age_warning}{flip_block}\
{safety_block}{seller_context}{description_block}{research_block}
CONDITION REPORT:
{condition_report}

MARKET RESEARCH:
{market_analysis}

IMPORTANT DECISION RULES:
- HIGH flip risk → default to NEGOTIATE (only PASS if combined with very \
low seller trust or other serious red flags)
- Seller rating below 4.0/5 → bias toward NEGOTIATE, not automatic PASS
- Unrated/unverifiable seller alone is NOT a reason to PASS — most FB \
Marketplace sellers are unrated
- For vehicles: brand reliability problems (e.g. Range Rover, Jaguar, \
high-mileage German luxury) → factor in expected repair costs
- Vision-derived readings from photos (odometers, serial numbers) are \
UNRELIABLE — note as approximate, do NOT flag as confirmed discrepancies
- Multiple red flags compound: 3+ serious concerns → recommend PASS
- Price significantly below market (30%+) → strong signal for BUY unless \
there are concrete red flags (not just theoretical risks)

Based on ALL available information, determine:

1. Whether the listed price is FAIR, OVERPRICED, or UNDERPRICED
2. A condition-adjusted fair value (a single dollar amount)
3. Your recommendation: BUY (low risk, fair price), NEGOTIATE (moderate \
risk, worth pursuing at lower price), or PASS (too many risk factors, \
untrustworthy seller, or far above market)
4. If NEGOTIATE: provide a specific target price and rationale
5. Confidence level: HIGH, MEDIUM, or LOW
6. Seller trust assessment — weight seller reputation HEAVILY. An \
unverifiable or suspicious seller is a major risk even if the item looks good.
7. Flip/reseller risk assessment if any indicators were found.
8. Listing age impact on negotiation strategy (if applicable)
9. A 3-4 sentence summary paragraph for the buyer

Format your response clearly with labeled sections."""

    result = invoke_llm(prompt)

    return {
        "price_assessment": result,
        "seller_ethnicity": seller_ethnicity,
        "seller_ethnicity_reasoning": seller_ethnicity_reasoning,
        "safety_info": safety_info,
        "flip_signals": flip_signals,
        "flip_risk_level": flip_risk_level,
        "flip_risk_summary": flip_risk_summary,
    }
