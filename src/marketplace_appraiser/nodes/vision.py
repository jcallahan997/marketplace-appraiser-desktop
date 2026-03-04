"""Node 2: Analyze listing images with Claude vision (preferred) or Ollama LLaVA."""

import base64
import mimetypes
import os
import re
import time

import ollama

from marketplace_appraiser.item_types import get_config
from marketplace_appraiser.state import AppraisalState
from marketplace_appraiser.utils.search import safe_search


def _search_item_context(item_name: str) -> str:
    """Web search for context and known issues specific to this item."""
    queries = [
        f"{item_name} review buyer's guide what to know",
        f"{item_name} common problems what to look for buying",
    ]
    all_snippets = []
    for query in queries:
        results = safe_search(query, max_results=5)
        for r in results:
            body = r.get("body", "")
            if body:
                all_snippets.append(body)
    return "\n".join(all_snippets) if all_snippets else ""


def _build_prompt(state: AppraisalState, known_issues: str) -> str:
    """Build a vision prompt with item context from the scraper."""
    item_name = state.get("item_name", "Unknown Item")
    item_type = state.get("item_type", "vehicle")
    config = get_config(item_type)

    listed_price = state.get("listed_price")
    condition_listed = state.get("condition_listed", "")

    condition_line = ""
    if condition_listed:
        condition_line = f' The seller lists the condition as "{condition_listed}".'

    price_line = ""
    if listed_price:
        price_line = f" It is listed for ${listed_price:,.0f}."

    context_block = ""
    if known_issues:
        context_block = f"""

What buyers should know about this item (from web research):
{known_issues}

Look for any of these known issues in the photo.\
"""

    return f"""\
You are inspecting listing photos as {config.vision_role}. \
This is a photo from a listing for a {item_name}.{condition_line}{price_line}

Your job is to identify anything in this photo that would affect a \
buying decision — problems that cost money to fix, signs of damage \
or neglect, but also positives that add value.
{context_block}
Analyze this photo in 3-5 sentences. Focus ONLY on what is clearly \
visible — do not guess or assume anything you cannot see.

Look for:
{config.vision_checklist}

Be specific about location and severity.\
"""


def _analyze_with_claude(prompt: str, image_paths: list[str], model: str) -> list[str]:
    """Analyze images using the Anthropic Claude API with retry."""
    import anthropic

    MAX_RETRIES = 5
    INITIAL_BACKOFF = 2

    client = anthropic.Anthropic()
    analyses: list[str] = []

    for i, img_path in enumerate(image_paths):
        print(f"  Analyzing image {i + 1}/{len(image_paths)} with {model}: {img_path}")
        try:
            with open(img_path, "rb") as f:
                img_data = base64.standard_b64encode(f.read()).decode("utf-8")

            media_type = mimetypes.guess_type(img_path)[0] or "image/jpeg"

            analysis = None
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    response = client.messages.create(
                        model=model,
                        max_tokens=512,
                        messages=[
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "image",
                                        "source": {
                                            "type": "base64",
                                            "media_type": media_type,
                                            "data": img_data,
                                        },
                                    },
                                    {
                                        "type": "text",
                                        "text": prompt,
                                    },
                                ],
                            }
                        ],
                    )
                    analysis = response.content[0].text
                    break
                except (anthropic.OverloadedError, anthropic.InternalServerError,
                        anthropic.RateLimitError) as e:
                    if attempt == MAX_RETRIES:
                        raise
                    wait = INITIAL_BACKOFF * (2 ** (attempt - 1))
                    print(f"    Retry {attempt}/{MAX_RETRIES} after "
                          f"{type(e).__name__} — waiting {wait}s...")
                    time.sleep(wait)

            analyses.append(analysis)
            print(f"  Done ({len(analysis)} chars)")
        except Exception as e:
            print(f"  Error analyzing image {img_path}: {e}")

    return analyses


def _analyze_with_ollama(prompt: str, image_paths: list[str], model: str) -> list[str]:
    """Analyze images using Ollama local vision model."""
    analyses: list[str] = []

    for i, img_path in enumerate(image_paths):
        print(f"  Analyzing image {i + 1}/{len(image_paths)} with {model}: {img_path}")
        try:
            response = ollama.chat(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                        "images": [img_path],
                    }
                ],
            )
            analysis = response["message"]["content"]
            analyses.append(analysis)
            print(f"  Done ({len(analysis)} chars)")
        except Exception as e:
            print(f"  Error analyzing image {img_path}: {e}")

    return analyses


MAX_FLIP_SIGNALS = 15  # Hard cap — anything above this is hallucination


def _extract_flip_signals_from_vision(
    analyses: list[str], item_name: str, item_type: str = "vehicle"
) -> list[str]:
    """Scan all image analyses for flip/dealer indicators."""
    from marketplace_appraiser.utils.llm import invoke_llm_light

    combined = "\n".join(f"Photo {i+1}: {a}" for i, a in enumerate(analyses))

    # Category-specific guidance
    if item_type == "vehicle":
        category_note = """\
For VEHICLES, these are strong flip indicators:
- Dealer lot background, commercial setting, multiple other vehicles
- License plates removed or obscured
- Dealer plate frames or temporary tags
- Professional studio-quality photography with commercial backdrop"""
    else:
        category_note = f"""\
For {item_type.upper()}, be VERY conservative about flip indicators:
- Professional photos are NORMAL for {item_type} sellers — this alone \
is NOT a flip indicator
- Clean/staged appearance is NORMAL — people clean items before selling
- A tidy home background is NOT suspicious
- Only flag truly commercial/warehouse settings with multiple similar items"""

    prompt = f"""\
Review these photo analyses of a {item_name} listing. Identify ONLY \
genuine reseller or flipping indicators — things that suggest the seller \
is a dealer or flipper rather than a private owner.

{category_note}

Check for these specific red flags:
- Signs of a professional reseller (COMMERCIAL warehouse/lot setting, NOT just a clean home)
- Missing identifying information (for vehicles: plates removed; for electronics: serial numbers obscured)
- Multiple SIMILAR items visible (suggests volume seller)
- Commercially printed price tags or "for sale" signage

Do NOT flag these as flip indicators:
- Clean or well-lit photos (normal for any seller)
- Clean/detailed appearance (people clean things before selling)
- Protective staging like rugs or covers (normal care)
- A tidy home or garage background

Do NOT list general condition observations. Do NOT list things that are \
ABSENT. Only list things that ARE present and clearly indicate dealing.

PHOTO ANALYSES:
{combined}

If no flip/dealer indicators are found, output exactly: NONE
Otherwise output up to 10 signals, one per line, prefixed with "VISION: "."""

    result = invoke_llm_light(prompt, temperature=0.1, max_tokens=512)

    if not result or result.strip().upper() == "NONE":
        return []

    signals = []
    for line in result.strip().splitlines():
        line = line.strip().lstrip("-•* ")
        if not line or line.upper() == "NONE":
            continue
        # Skip lines that are reasoning about absence of indicators.
        # The LLM sometimes outputs its analysis ("No dealer lot found")
        # instead of the expected "NONE" when nothing was found.
        content = line.lower()
        if content.startswith("vision:"):
            content = content[len("vision:"):].strip()
        content = content.lstrip("-•* ")
        if (
            content.startswith("no ")
            or content.startswith("not ")
            or content.startswith("none ")
            or any(phrase in content for phrase in (
                "none found", "none detected", "no indicators",
                "all photos show", "looking through", "reviewing",
                "checking for", "after reviewing", "based on",
            ))
        ):
            continue
        if not line.upper().startswith("VISION:"):
            line = f"VISION: {line}"
        else:
            line = "VISION:" + line[len("VISION:"):]
        signals.append(line)

    # Hallucination guard
    if len(signals) > MAX_FLIP_SIGNALS:
        print(f"  WARNING: LLM generated {len(signals)} flip signals "
              f"(>{MAX_FLIP_SIGNALS}) — hallucination detected, discarding all")
        return []

    return signals


def analyze_images(state: AppraisalState) -> dict:
    """LangGraph node: analyze each listing image with the vision model."""
    image_paths = state.get("image_paths", [])
    item_name = state.get("item_name", "Unknown Item")
    item_type = state.get("item_type", "vehicle")

    # Detect vision provider
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    vision_model = os.getenv("VISION_MODEL", "")

    if vision_model:
        use_claude = vision_model.startswith("claude")
    elif anthropic_key:
        use_claude = True
        vision_model = "claude-sonnet-4-20250514"
    else:
        use_claude = False
        vision_model = "llava:latest"

    provider = "Claude API" if use_claude else "Ollama"

    if not image_paths:
        print("\n  No images found — skipping vision analysis.")
        return {"image_analyses": ["No images were available for analysis."]}

    print(f"\n{'='*60}")
    print(f"STEP 2: Analyzing {len(image_paths)} images with {vision_model} ({provider})")
    print(f"{'='*60}\n")

    print(f"  Searching for item context on {item_name}...")
    known_issues = _search_item_context(item_name)
    if known_issues:
        print(f"  Found item context ({len(known_issues)} chars)")
    else:
        print("  No web context found — using general inspection only")

    prompt = _build_prompt(state, known_issues)

    if use_claude:
        analyses = _analyze_with_claude(prompt, image_paths, vision_model)
    else:
        analyses = _analyze_with_ollama(prompt, image_paths, vision_model)

    print("  Scanning analyses for flip/reseller indicators...")
    flip_signals = _extract_flip_signals_from_vision(analyses, item_name, item_type)
    if flip_signals:
        print(f"  Found {len(flip_signals)} flip indicator(s):")
        for sig in flip_signals:
            print(f"    - {sig}")
    else:
        print("  No flip indicators detected")

    # Opportunistic VIN extraction for vehicles
    if item_type == "vehicle":
        all_analysis_text = " ".join(analyses)
        vin_match = re.search(r"\b([A-HJ-NPR-Z0-9]{17})\b", all_analysis_text)
        if vin_match:
            vin = vin_match.group(1)
            print(f"  VIN detected in photo analysis: {vin}")
            from marketplace_appraiser.utils.safety_apis import decode_vin

            decoded = decode_vin(vin)
            item_fields = state.get("item_fields", {})
            if not decoded["error"] and decoded["year"]:
                listed_year = item_fields.get("year")
                listed_make = (item_fields.get("make") or "").lower()
                decoded_make = decoded["make"].lower()
                if listed_year and decoded["year"] != listed_year:
                    flip_signals.append(
                        f"VISION: VIN decodes to {decoded['year']} but "
                        f"listing says {listed_year} — YEAR MISMATCH"
                    )
                if (
                    listed_make
                    and decoded_make
                    and listed_make not in decoded_make
                    and decoded_make not in listed_make
                ):
                    flip_signals.append(
                        f"VISION: VIN decodes to {decoded['make']} but "
                        f"listing says {item_fields.get('make')} — MAKE MISMATCH"
                    )

    return {"image_analyses": analyses, "flip_signals": flip_signals}
