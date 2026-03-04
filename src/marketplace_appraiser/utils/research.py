"""Follow-on web research for unknown terms, claims, anomalies, and options."""

import base64
import mimetypes
import os
import time

from marketplace_appraiser.utils.llm import invoke_llm, invoke_llm_light
from marketplace_appraiser.utils.search import safe_search


# ---------------------------------------------------------------------------
# Options / features lookup and vision scan
# ---------------------------------------------------------------------------

def search_available_options(item_name: str) -> str:
    """Web search for known options, packages, and trim levels.

    Returns a block of text describing what options/packages are available
    for this item so the vision model knows what to look for.
    """
    queries = [
        f"{item_name} available options packages features list",
        f"{item_name} trim levels standard equipment differences",
    ]
    all_snippets: list[str] = []
    for query in queries:
        results = safe_search(query, max_results=5)
        for r in results:
            body = r.get("body", "")
            if body:
                all_snippets.append(body)

    return "\n".join(all_snippets) if all_snippets else ""


def identify_options_from_photos(
    image_paths: list[str],
    description: str,
    item_name: str,
    known_options: str = "",
) -> str:
    """Use the vision model to spot options/features visible in photos.

    Sends a small batch of photos (up to 4) to the vision model with a
    prompt that includes known available options for this item. The model
    identifies equipment visible in the photos but NOT mentioned in the
    seller's description. Returns the raw LLM text.
    """
    if not image_paths:
        return ""

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

    # Pick up to 4 representative images
    n = len(image_paths)
    if n <= 4:
        selected = image_paths
    else:
        idxs = sorted(set([0, n // 3, 2 * n // 3, n - 1]))
        selected = [image_paths[i] for i in idxs]

    known_options_section = ""
    if known_options:
        known_options_section = f"""

KNOWN AVAILABLE OPTIONS for this item (from web research):
{known_options[:3000]}

Use this list to identify which of these options are visible in the photos.
"""

    prompt = f"""\
You are inspecting listing photos for a {item_name}. The seller's \
description is shown below. Your job is to identify any options, packages, \
equipment, or features visible in these photos that the seller did NOT \
mention in their description.
{known_options_section}
SELLER'S DESCRIPTION:
{description or "(No description provided)"}

Look for notable features, accessories, or options visible in the photos \
but not mentioned in the description. List each on its own line with which \
photo you saw it in and whether it adds or subtracts value.

If you don't see any notable options beyond what the description covers, \
output exactly: NONE"""

    if use_claude:
        return _options_claude(prompt, selected, vision_model)
    else:
        return _options_ollama(prompt, selected, vision_model)


def _options_claude(prompt: str, image_paths: list[str], model: str) -> str:
    """Send multiple images in a single Claude message for options scan."""
    import anthropic

    MAX_RETRIES = 5
    INITIAL_BACKOFF = 2

    content: list[dict] = []
    for img_path in image_paths:
        try:
            with open(img_path, "rb") as f:
                img_data = base64.standard_b64encode(f.read()).decode("utf-8")
            media_type = mimetypes.guess_type(img_path)[0] or "image/jpeg"
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": img_data},
            })
        except Exception:
            continue

    if not content:
        return ""

    content.append({"type": "text", "text": prompt})

    client = anthropic.Anthropic()
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=1024,
                messages=[{"role": "user", "content": content}],
            )
            return response.content[0].text
        except (anthropic.OverloadedError, anthropic.InternalServerError,
                anthropic.RateLimitError) as e:
            if attempt == MAX_RETRIES:
                print(f"    Options scan failed after {MAX_RETRIES} retries: {e}")
                return ""
            wait = INITIAL_BACKOFF * (2 ** (attempt - 1))
            print(f"    Retry {attempt}/{MAX_RETRIES} after "
                  f"{type(e).__name__} — waiting {wait}s...")
            time.sleep(wait)
    return ""


def _options_ollama(prompt: str, image_paths: list[str], model: str) -> str:
    """Send images to Ollama for options scan."""
    import ollama as _ollama

    try:
        response = _ollama.chat(
            model=model,
            messages=[{
                "role": "user",
                "content": prompt,
                "images": image_paths,
            }],
        )
        return response["message"]["content"]
    except Exception as e:
        print(f"    Options scan failed: {e}")
        return ""


# ---------------------------------------------------------------------------
# Research question identification
# ---------------------------------------------------------------------------

def identify_research_questions(
    description: str,
    image_analyses: list[str],
    item_name: str,
    spotted_options: str = "",
) -> list[str]:
    """Ask the LLM to identify claims or terms that need web verification."""
    image_text = ""
    for i, analysis in enumerate(image_analyses):
        image_text += f"\n--- Photo {i + 1} ---\n{analysis}\n"

    options_section = ""
    if spotted_options and spotted_options.strip().upper() != "NONE":
        options_section = f"""

OPTIONS/FEATURES SPOTTED IN PHOTOS (not in seller's description):
{spotted_options}
"""

    prompt = f"""\
You are helping a buyer research a {item_name} listing. Below are the \
seller's description, photo analysis notes, and any additional options \
spotted in the photos. Identify specific claims, terms, or observations \
that a buyer should verify with web research.

SELLER'S DESCRIPTION:
{description or "(No description provided)"}

PHOTO ANALYSIS NOTES:
{image_text or "(No photo analyses available)"}
{options_section}
List 3-8 concise web search queries that would help verify or understand \
the most important items. Focus on:
- Seller claims about repairs, parts, or modifications
- Technical terms or abbreviations the buyer may not understand
- Anomalies or concerns spotted in the photos
- Options or features spotted in photos that aren't in the description
- Anything that could significantly affect the item's value or safety

Output ONLY the search queries, one per line. No numbering, no explanation. \
Each query should include "{item_name}" for context where relevant. \
If everything is straightforward and nothing needs research, output exactly: \
NONE"""

    raw = invoke_llm_light(prompt, temperature=0.2)
    lines = [line.strip() for line in raw.strip().splitlines() if line.strip()]

    if len(lines) == 1 and lines[0].upper() == "NONE":
        return []

    # Clean up: remove numbering prefixes
    cleaned = []
    for line in lines:
        for prefix in ("- ", "• ", "* "):
            if line.startswith(prefix):
                line = line[len(prefix):]
        if line and line[0].isdigit() and ". " in line[:4]:
            line = line.split(". ", 1)[1]
        if line:
            cleaned.append(line)

    return cleaned[:8]


# ---------------------------------------------------------------------------
# Web search execution and formatting
# ---------------------------------------------------------------------------

def research_questions(queries: list[str]) -> dict[str, str]:
    """Run DuckDuckGo searches for each query and return {query: snippets}."""
    if not queries:
        return {}

    results: dict[str, str] = {}
    for query in queries:
        snippets = []
        hits = safe_search(query, max_results=4)
        for hit in hits:
            body = hit.get("body", "")
            if body:
                snippets.append(body)
        results[query] = "\n".join(snippets)

    return results


def format_research_findings(findings: dict[str, str]) -> str:
    """Format research findings into a readable block for LLM context."""
    if not findings:
        return ""

    sections = []
    for query, snippets in findings.items():
        if snippets:
            sections.append(f"Q: {query}\n{snippets}")

    if not sections:
        return ""

    return "\n\n".join(sections)
