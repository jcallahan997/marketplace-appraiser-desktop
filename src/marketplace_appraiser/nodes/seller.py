"""Node 5: Seller investigation — profile scrape + web research + LLM synthesis.

This is a NEW node not present in the vehicle-only appraiser. It consolidates
all seller research into a dedicated pipeline step that produces a structured
seller profile with risk assessment.

Pipeline within this node:
  1. Navigate to seller's FB Marketplace profile page (Playwright CDP)
  2. Scrape their active listings, bio, business info
  3. Web search for seller across platforms (DDG)
  4. LLM synthesis into structured seller profile
"""

import asyncio
import os
import re

from playwright.async_api import async_playwright

from marketplace_appraiser.state import AppraisalState
from marketplace_appraiser.utils.llm import invoke_llm, invoke_llm_light
from marketplace_appraiser.utils.search import safe_search


# ---------------------------------------------------------------------------
# Phase 1: Profile scrape via Playwright
# ---------------------------------------------------------------------------

async def _scrape_seller_profile(profile_url: str) -> dict:
    """Navigate to the seller's FB Marketplace profile and scrape details.

    Returns dict with keys:
        bio, business_name, business_info, active_listings (list of dicts),
        total_listings_count, categories_found (list of str)
    """
    if not profile_url:
        return {}

    cdp_url = os.getenv("CHROME_CDP_URL", "http://localhost:9222")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(cdp_url)
            context = browser.contexts[0]
            page = await context.new_page()

            try:
                await page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(5000)

                # Scroll to load more listings
                for _ in range(5):
                    await page.evaluate("window.scrollBy(0, 800)")
                    await page.wait_for_timeout(600)

                # Extract profile data
                profile_data = await page.evaluate(
                    r"""() => {
                        const data = {
                            bio: '',
                            business_name: '',
                            business_info: '',
                            listings: [],
                            total_text: ''
                        };

                        // Bio / about text
                        const aboutEls = document.querySelectorAll(
                            'span, div'
                        );
                        for (const el of aboutEls) {
                            const t = el.textContent.trim();
                            if (t.length > 50 && t.length < 500
                                && !t.includes('Marketplace')
                                && !t.includes('Privacy')) {
                                // Likely a bio or about section
                                if (el.closest('[role="main"]')) {
                                    data.bio = t;
                                    break;
                                }
                            }
                        }

                        // Check for business indicators
                        const pageText = document.body.innerText || '';
                        const bizMatch = pageText.match(
                            /(?:Business|Shop|Store)\s*(?:name|:)\s*([^\n]+)/i
                        );
                        if (bizMatch) data.business_name = bizMatch[1].trim();

                        // Business hours, website, etc.
                        const hoursMatch = pageText.match(
                            /(?:Hours|Open|Business hours)[:\s]*([^\n]+)/i
                        );
                        if (hoursMatch) {
                            data.business_info = hoursMatch[1].trim();
                        }

                        // Scrape visible listings — scoped to seller's
                        // own listing grid, NOT the whole page.
                        // Facebook profile pages show the seller's listings
                        // in the main content area.  Recommendation links,
                        // sidebar items, and "items near you" must be
                        // excluded.

                        // Strategy: walk up from each marketplace link and
                        // only keep it if the link lives inside the main
                        // content area AND the link's URL is on the same
                        // seller's profile (the profile_url path contains
                        // the seller ID).
                        const profilePath = window.location.pathname;
                        const mainContent = document.querySelector('[role="main"]');
                        const listingLinks = (mainContent || document).querySelectorAll(
                            'a[href*="/marketplace/item/"]'
                        );

                        const seen = new Set();
                        for (const link of listingLinks) {
                            const href = link.href;
                            if (seen.has(href)) continue;
                            seen.add(href);

                            // Skip links inside "Recommended" / "Related"
                            // / "Items near you" sections
                            const ancestors = [];
                            let el = link;
                            while (el && ancestors.length < 12) {
                                ancestors.push(el);
                                el = el.parentElement;
                            }
                            const ancestorText = ancestors
                                .map(a => a.getAttribute && a.getAttribute('aria-label') || '')
                                .join(' ').toLowerCase();
                            if (ancestorText.includes('recommend')
                                || ancestorText.includes('related')
                                || ancestorText.includes('near you')
                                || ancestorText.includes('suggested')
                                || ancestorText.includes('more from marketplace')) {
                                continue;
                            }

                            // Find price and title near this link
                            const container = link.closest('div');
                            if (!container) continue;

                            const text = container.innerText || '';
                            const priceMatch = text.match(/\$[\d,]+/);
                            const lines = text.split('\n').filter(
                                l => l.trim().length > 3
                            );

                            data.listings.push({
                                title: lines[0] || '',
                                price: priceMatch ? priceMatch[0] : '',
                                url: href
                            });
                        }

                        // Total listings indicator — try strict first, then broad
                        // FB shows "N active listings", "N listings for sale", etc.
                        let totalMatch = pageText.match(
                            /(\d+)\s+(?:listings?|items?)\s+(?:for sale|available)/i
                        );
                        if (!totalMatch) {
                            // "N active listings" pattern (common on profile pages)
                            totalMatch = pageText.match(
                                /(?<!Browse\s)(\d+)\s+active\s+listings?\b/i
                            );
                        }
                        if (!totalMatch) {
                            // Broader fallback: "N listings" without suffix,
                            // but exclude "Browse N listings" (FB recommendation UI)
                            totalMatch = pageText.match(
                                /(?<!Browse\s)(\d+)\s+listings?\b/i
                            );
                        }
                        if (totalMatch) data.total_text = totalMatch[0];

                        return data;
                    }"""
                )

                return profile_data

            finally:
                await page.close()

    except Exception as e:
        print(f"  Error scraping seller profile: {e}")
        return {}


# ---------------------------------------------------------------------------
# Phase 2: Web research
# ---------------------------------------------------------------------------

def _research_seller_web(
    seller_name: str, location: str, description: str = ""
) -> dict:
    """Web search for seller reputation across platforms.

    Runs 4 targeted searches (down from 8) using combined queries
    to maximize signal per API call.

    Returns dict with keys: reputation_snippets, platform_hits,
        complaint_snippets, linkedin_snippets
    """
    if not seller_name:
        return {
            "reputation_snippets": [],
            "platform_hits": [],
            "complaint_snippets": [],
            "linkedin_snippets": [],
        }

    reputation_snippets = []
    complaint_snippets = []
    platform_hits = []
    linkedin_snippets = []

    # 1. Combined reputation + Facebook presence (replaces 2 old queries)
    results = safe_search(
        f'"{seller_name}" {location} seller review facebook marketplace',
        max_results=5,
    )
    for r in results:
        body = r.get("body", "")
        if body:
            reputation_snippets.append(body)

    # 2. Complaints / scams / BBB (combined)
    results = safe_search(
        f'"{seller_name}" {location} scam complaints BBB reviews',
        max_results=5,
    )
    for r in results:
        body = r.get("body", "")
        title = r.get("title", "")
        if body:
            complaint_snippets.append(f"{title}: {body}")

    # 3. Cross-platform marketplace presence (single combined query)
    name_lower = seller_name.lower().split()[0] if seller_name else ""
    results = safe_search(
        f'"{seller_name}" {location} OfferUp OR Craigslist OR Mercari',
        max_results=5,
    )
    for r in results:
        body = r.get("body", "").lower()
        title = r.get("title", "").lower()
        combined = body + " " + title
        if name_lower and name_lower in combined:
            platform_hits.append(r.get("title", ""))

    # 4. LinkedIn professional profile
    results = safe_search(
        f'"{seller_name}" {location} site:linkedin.com OR linkedin.com/in',
        max_results=3,
    )
    for r in results:
        body = r.get("body", "")
        title = r.get("title", "")
        href = r.get("href", "")
        if "linkedin" in href.lower() or "linkedin" in title.lower():
            linkedin_snippets.append(f"{title}: {body[:300]}")
        elif body and name_lower and name_lower in (body + title).lower():
            linkedin_snippets.append(f"{title}: {body[:300]}")

    # Optional: phone number in description
    phone_match = re.search(r"\b(\d{3}[-. )]+\d{3}[-. )]+\d{4})", description)
    if phone_match:
        phone = phone_match.group(1)
        results = safe_search(f'"{phone}" for sale listing', max_results=3)
        for r in results:
            body = r.get("body", "")
            if body:
                platform_hits.append(f"Phone: {body[:200]}")

    return {
        "reputation_snippets": reputation_snippets,
        "platform_hits": platform_hits,
        "complaint_snippets": complaint_snippets,
        "linkedin_snippets": linkedin_snippets,
    }


# ---------------------------------------------------------------------------
# Phase 3: LLM synthesis
# ---------------------------------------------------------------------------

def _synthesize_seller_profile(
    seller_name: str,
    seller_rating: str,
    seller_joined: str,
    seller_listings_count: str,
    profile_data: dict,
    web_research: dict,
    location: str,
) -> tuple[str, str]:
    """Use LLM to synthesize all seller findings into a structured profile.

    Returns (investigation_text, risk_level).
    """
    # Build context sections
    profile_section = ""
    if profile_data:
        listings = profile_data.get("listings", [])
        listing_summary = ""
        if listings:
            listing_lines = []
            for lst in listings[:15]:
                listing_lines.append(
                    f"  - {lst.get('title', 'Unknown')} — {lst.get('price', 'N/A')}"
                )
            listing_summary = "\n".join(listing_lines)

        profile_section = f"""
SELLER PROFILE PAGE DATA:
- Bio: {profile_data.get('bio', 'None found')}
- Business name: {profile_data.get('business_name', 'None')}
- Business info: {profile_data.get('business_info', 'None')}
- Active listings found: {len(listings)}
{listing_summary if listing_summary else '  (no listings scraped)'}
"""

    web_section = ""
    rep_snippets = web_research.get("reputation_snippets", [])
    complaint_snippets = web_research.get("complaint_snippets", [])
    platform_hits = web_research.get("platform_hits", [])
    linkedin_snippets = web_research.get("linkedin_snippets", [])

    if rep_snippets or complaint_snippets or platform_hits or linkedin_snippets:
        parts = []
        if linkedin_snippets:
            parts.append("LinkedIn / Professional profile:\n" + "\n".join(linkedin_snippets[:3]))
        if rep_snippets:
            parts.append("Reputation snippets:\n" + "\n".join(rep_snippets[:5]))
        if complaint_snippets:
            parts.append("Complaints found:\n" + "\n".join(complaint_snippets[:5]))
        if platform_hits:
            parts.append("Cross-platform presence:\n" + "\n".join(platform_hits[:5]))
        web_section = f"""
WEB RESEARCH FINDINGS:
{chr(10).join(parts)}
"""

    # Basic seller info
    seller_info_section = f"""
BASIC SELLER INFO:
- Name: {seller_name or 'Unknown'}
- Rating: {seller_rating or 'Not available'}
- Joined Facebook: {seller_joined or 'Unknown'}
- Listed items count: {seller_listings_count or 'Unknown'}
- Location: {location or 'Unknown'}
"""

    prompt = f"""\
Analyze all available information about this Facebook Marketplace seller \
and produce a structured seller profile.

{seller_info_section}{profile_section}{web_section}

CRITICAL: Web search results may contain information about DIFFERENT PEOPLE \
with the same or similar name. Do NOT attribute criminal records, lawsuits, \
scam reports, or negative information to this seller unless there is STRONG \
corroborating evidence that connects it to THIS specific person (matching \
location, matching business, matching profile details). Common names like \
"John Smith", "David Lee", "Victor Ramirez" etc. will return many \
irrelevant results — be explicit when web findings may not be about this \
seller. Say "A person with a similar name..." rather than attributing it.

Produce a structured assessment with these exact sections:

## Seller Type
Classify as: Individual / Casual Reseller / Volume Reseller / Business/Dealer
Explain your reasoning based on listing volume, categories, and language.

## Account & Activity
Summarize account age, listing frequency, and total active listings.

## Categories Sold
What types of items do they sell? Is there a pattern?

## Professional Background
If LinkedIn or professional profile data is available, summarize their \
occupation, employer, and any relevant background. Note whether their \
professional background is consistent with their selling activity \
(e.g. a car dealer selling cars, an IT worker selling electronics, \
or a suspicious mismatch like a student selling 50+ items per month). \
If no LinkedIn data found, state "No professional profile found."

## Reputation Signals
Summarize any reviews, complaints, or platform presence found. \
Clearly distinguish between findings that are LIKELY about this seller \
vs. findings that may be about a different person with the same name.

## Location Consistency
Do they list from consistent locations?

## Risk Assessment
Rate as LOW, MEDIUM, or HIGH risk with a 2-3 sentence explanation. \
Do NOT inflate risk based on unverified web findings about people with \
similar names.

## Key Findings
3-5 bullet points of the most noteworthy discoveries.

Be direct and factual. If information is missing, say so. If web results \
are ambiguous about identity, explicitly note the uncertainty."""

    investigation = invoke_llm(prompt, temperature=0.2)

    # Extract risk level from the investigation text
    risk_level = "MEDIUM"  # default
    risk_match = re.search(
        r"Risk Assessment.*?(LOW|MEDIUM|HIGH)",
        investigation,
        re.IGNORECASE | re.DOTALL,
    )
    if risk_match:
        risk_level = risk_match.group(1).upper()

    return investigation, risk_level


# ---------------------------------------------------------------------------
# Public node function
# ---------------------------------------------------------------------------

def investigate_seller(state: AppraisalState) -> dict:
    """LangGraph node: deep-dive investigation of the seller."""
    print(f"\n{'='*60}")
    print("STEP 5: Investigating seller")
    print(f"{'='*60}\n")

    seller_name = state.get("seller_name", "")
    seller_rating = state.get("seller_rating", "")
    seller_joined = state.get("seller_joined", "")
    seller_listings = state.get("seller_listings", "")
    seller_profile_url = state.get("seller_profile_url", "")
    location = state.get("location", "")
    description = state.get("description", "")

    if not seller_name and not seller_profile_url:
        print("  No seller information available — skipping investigation")
        return {
            "seller_profile": {},
            "seller_active_listings": [],
            "seller_investigation": "No seller information was available for investigation.",
            "seller_risk_level": "MEDIUM",
        }

    print(f"  Seller: {seller_name or 'Unknown'}")
    if seller_profile_url:
        print(f"  Profile: {seller_profile_url[:80]}")

    # Phase 1: Profile scrape
    profile_data = {}
    if seller_profile_url:
        print("  Phase 1: Scraping seller's profile page...")
        profile_data = asyncio.run(_scrape_seller_profile(seller_profile_url))
        listings = profile_data.get("listings", [])
        total_text = profile_data.get("total_text", "")
        print(f"  Scraped {len(listings)} visible item(s) from profile "
              f"(shown in email; NOT used as count — may include FB recommendations)")
        if total_text:
            print(f"  Profile page explicit count: \"{total_text}\"")

        # Listing count priority:
        # 1. Explicit "N listings for sale" text from profile page (most reliable)
        # 2. "N listings" from listing page's Seller Information section
        # 3. Nothing — do NOT use scraped link count; FB injects recommended
        #    items everywhere so it's almost always inflated.
        explicit_count = None
        if total_text:
            m = re.match(r"(\d+)", total_text)
            if m:
                explicit_count = int(m.group(1))

        if explicit_count is not None:
            seller_listings = str(explicit_count)
            print(f"  Listing count → profile page text: {explicit_count}")
        elif seller_listings:
            print(f"  Listing count → listing page: {seller_listings}")
        else:
            print(f"  Listing count → unknown (no reliable text found)")

        # Sanity check: if count looks inflated (>50), mark as unverified
        if seller_listings:
            try:
                count_val = int(seller_listings)
                if count_val > 50:
                    print(f"  WARNING: Listing count {count_val} seems high — "
                          f"marking as unverified")
                    seller_listings = f"~{count_val} (unverified)"
            except ValueError:
                pass

        if profile_data.get("business_name"):
            print(f"  Business: {profile_data['business_name']}")
    else:
        print("  Phase 1: No profile URL — skipping profile scrape")

    # Phase 2: Web research
    print(f"  Phase 2: Searching for seller reputation online...")
    web_research = _research_seller_web(seller_name, location, description)

    rep_count = len(web_research.get("reputation_snippets", []))
    complaint_count = len(web_research.get("complaint_snippets", []))
    platform_count = len(web_research.get("platform_hits", []))
    linkedin_count = len(web_research.get("linkedin_snippets", []))
    print(f"  Found: {rep_count} reputation, {complaint_count} complaint, "
          f"{platform_count} platform, {linkedin_count} LinkedIn hit(s)")

    # Phase 3: LLM synthesis
    print("  Phase 3: Synthesizing seller profile...")
    investigation, risk_level = _synthesize_seller_profile(
        seller_name=seller_name,
        seller_rating=seller_rating,
        seller_joined=seller_joined,
        seller_listings_count=seller_listings,
        profile_data=profile_data,
        web_research=web_research,
        location=location,
    )

    print(f"  Seller risk level: {risk_level}")
    print(f"  Investigation report: {len(investigation)} chars")

    active_listings = profile_data.get("listings", [])

    result = {
        "seller_profile": profile_data,
        "seller_active_listings": active_listings,
        "seller_investigation": investigation,
        "seller_risk_level": risk_level,
    }
    # Propagate corrected listing count back into state
    if seller_listings:
        result["seller_listings"] = seller_listings
    return result
