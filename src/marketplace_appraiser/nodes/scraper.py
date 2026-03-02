"""Node 1: Scrape a Facebook Marketplace listing via Playwright CDP."""

import asyncio
import os
import re
from pathlib import Path

from playwright.async_api import async_playwright

from marketplace_appraiser.item_types import detect_item_type, get_config
from marketplace_appraiser.state import AppraisalState
from marketplace_appraiser.utils.image_utils import download_images_parallel
from marketplace_appraiser.utils.parsing import parse_listing_age, parse_price

OUTPUT_DIR = Path("output/images")
SCREENSHOT_DIR = Path("output/debug")
DEBUG_SCREENSHOTS = os.getenv("SCRAPER_DEBUG_SCREENSHOTS", "").lower() in (
    "1",
    "true",
    "yes",
)


# ---------------------------------------------------------------------------
# Debug helpers
# ---------------------------------------------------------------------------

async def _take_debug_screenshot(page, name: str):
    """Save a debug screenshot if SCRAPER_DEBUG_SCREENSHOTS is enabled."""
    if not DEBUG_SCREENSHOTS:
        return
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SCREENSHOT_DIR / f"{name}.png"
    await page.screenshot(path=str(path), full_page=False)
    print(f"  [debug] Screenshot saved: {path}")


# ---------------------------------------------------------------------------
# Modal detection
# ---------------------------------------------------------------------------

async def _wait_for_modal(page):
    """Wait for the Facebook listing modal/dialog to appear and return it."""
    for selector in ('[role="dialog"]', '[aria-modal="true"]'):
        try:
            await page.wait_for_selector(selector, timeout=8000)
            modals = await page.query_selector_all(selector)
            best = None
            best_area = 0
            for modal in modals:
                box = await modal.bounding_box()
                if box:
                    area = box["width"] * box["height"]
                    if area > best_area:
                        best_area = area
                        best = modal
            if best and best_area > 50000:
                print(f"  Modal detected via {selector} (area={best_area:.0f}px)")
                return best
        except Exception:
            continue

    try:
        close_btn = await page.query_selector('[aria-label="Close"]')
        if close_btn:
            modal = await page.evaluate_handle(
                """(closeBtn) => {
                    let el = closeBtn;
                    for (let i = 0; i < 15; i++) {
                        el = el.parentElement;
                        if (!el) return null;
                        const role = el.getAttribute('role');
                        const style = window.getComputedStyle(el);
                        if ((role === 'dialog' || style.position === 'fixed'
                             || style.position === 'absolute')
                            && el.offsetWidth > 400 && el.offsetHeight > 400) {
                            return el;
                        }
                    }
                    return null;
                }""",
                close_btn,
            )
            element = modal.as_element()
            if element:
                print("  Modal detected via Close-button ancestor traversal")
                return element
    except Exception:
        pass

    try:
        container = await page.evaluate_handle(
            """() => {
                const titleMatch = document.title.match(
                    /Marketplace\\s*-\\s*(.+?)\\s*\\|/
                );
                if (!titleMatch) return null;
                const itemName = titleMatch[1].trim();

                const headings = document.querySelectorAll('h1');
                let listingH1 = null;
                for (const h of headings) {
                    const t = h.textContent.trim();
                    if (t && itemName.startsWith(t.substring(0, 8))) {
                        listingH1 = h;
                        break;
                    }
                }
                if (!listingH1) return null;

                let el = listingH1;
                for (let i = 0; i < 20; i++) {
                    el = el.parentElement;
                    if (!el) return null;
                    const text = el.innerText || '';
                    if (text.includes("Seller's description")
                        || text.includes('Seller information')
                        || text.includes('About this vehicle')
                        || text.includes('Description')) {
                        const r = el.getBoundingClientRect();
                        if (r.width < window.innerWidth * 0.9) {
                            return el;
                        }
                    }
                }
                return null;
            }"""
        )
        element = container.as_element()
        if element:
            box = await element.bounding_box()
            if box:
                print(
                    f"  Direct-page layout detected — listing container at "
                    f"x={box['x']:.0f}, w={box['width']:.0f}x{box['height']:.0f}"
                )
                return element
    except Exception:
        pass

    print("  WARNING: No modal or listing container detected — scraping full page")
    return None


# ---------------------------------------------------------------------------
# Scoped evaluation helper
# ---------------------------------------------------------------------------

async def _eval(page, scope, js):
    """Run JS in the modal scope if available, otherwise on the full page."""
    if scope:
        return await scope.evaluate(js, scope)
    return await page.evaluate(js, None)


# ---------------------------------------------------------------------------
# Generic extraction helpers — all scoped to modal when available
# ---------------------------------------------------------------------------

async def _extract_title(page, scope) -> str:
    """Extract listing title from the page or modal."""
    try:
        result = await page.evaluate(
            """() => {
                const m = document.title.match(/Marketplace\\s*-\\s*(.+?)\\s*\\|/);
                return m ? m[1].trim() : null;
            }"""
        )
        if result and len(result) > 3:
            return result
    except Exception:
        pass

    try:
        result = await _eval(
            page, scope,
            """(root) => {
                const c = root || document.body;
                const h1 = c.querySelector('h1');
                if (h1) {
                    const t = h1.textContent.trim();
                    if (t.length > 3 && t !== 'Chats' && t !== 'Marketplace')
                        return t;
                }
                return null;
            }""",
        )
        if result:
            return result
    except Exception:
        pass

    try:
        result = await _eval(
            page, scope,
            """(root) => {
                const c = root || document.body;
                const el = c.querySelector('[data-testid="marketplace_listing_title"]');
                if (el) return el.textContent.trim();
                const headings = c.querySelectorAll('h1, h2, [role="heading"]');
                for (const h of headings) {
                    const t = h.textContent.trim();
                    if (t.length > 5 && t !== 'Chats' && t !== 'Marketplace')
                        return t;
                }
                return null;
            }""",
        )
        if result:
            return result
    except Exception:
        pass

    return ""


async def _extract_price_text(page, scope) -> str:
    """Extract the listed price text from the modal."""
    try:
        result = await _eval(
            page, scope,
            """(root) => {
                const c = root || document.body;
                const spans = c.querySelectorAll('span');
                for (const s of spans) {
                    const t = s.textContent.trim();
                    if (/^\\$[\\d,]+$/.test(t)) return t;
                }
                const match = c.innerText.match(/\\$[\\d,]+/);
                return match ? match[0] : '';
            }""",
        )
        if result:
            return result
    except Exception:
        pass
    return ""


async def _extract_description(page, scope) -> str:
    """Extract the seller's description text from the modal."""
    try:
        if scope:
            await _eval(
                page, scope,
                """(root) => {
                    const els = root.querySelectorAll('span, div');
                    for (const el of els) {
                        const t = el.textContent.trim();
                        if (t === 'See more' || t === 'See More') {
                            el.click();
                            return true;
                        }
                    }
                    return false;
                }""",
            )
            await page.wait_for_timeout(500)
        else:
            see_more = page.locator("text=See more").first
            if await see_more.count() > 0:
                try:
                    await see_more.click()
                    await page.wait_for_timeout(500)
                except Exception:
                    pass
    except Exception:
        pass

    try:
        result = await _eval(
            page, scope,
            """(root) => {
                const c = root || document.body;
                const spans = c.querySelectorAll('span');
                let longest = '';
                for (const s of spans) {
                    const t = s.textContent.trim();
                    if (t.length > 50 && t.length > longest.length && t.length < 5000) {
                        if (!t.includes('Marketplace') || t.length > 200)
                            longest = t;
                    }
                }
                return longest;
            }""",
        )
        if result:
            return result
    except Exception:
        pass
    return ""


async def _extract_details(page, scope, labels: list[str]) -> dict:
    """Extract structured details based on config-provided labels."""
    details = {}
    if not labels:
        return details

    labels_js = ", ".join(f"'{label}'" for label in labels)
    try:
        raw = await _eval(
            page, scope,
            f"""(root) => {{
                const c = root || document.body;
                const result = {{}};
                const labels = [{labels_js}];
                const allText = c.innerText;
                for (const label of labels) {{
                    const regex = new RegExp(label + '\\\\n([^\\\\n]+)', 'i');
                    const match = allText.match(regex);
                    if (match)
                        result[label.toLowerCase().replace(/ /g, '_')] = match[1].trim();
                }}
                // "Driven 165,000 miles" format (vehicle-specific but harmless)
                if (!result.mileage) {{
                    const drivenMatch = allText.match(
                        /Driven\\s+([\\d,]+)\\s*miles/i
                    );
                    if (drivenMatch)
                        result.mileage = drivenMatch[1].trim() + ' miles';
                }}
                return result;
            }}""",
        )
        details.update(raw)
    except Exception:
        pass
    return details


async def _extract_location(page, scope) -> str:
    """Extract the listing location from the modal."""
    try:
        result = await _eval(
            page, scope,
            """(root) => {
                const c = root || document.body;
                const allText = c.innerText;
                const m = allText.match(/Listed .+ in (.+)/);
                if (m) return m[1].trim();
                const m2 = allText.match(/Location\\n([^\\n]+)/i);
                if (m2) return m2[1].trim();
                return '';
            }""",
        )
        return result or ""
    except Exception:
        return ""


async def _extract_listing_age(page, scope) -> str:
    """Extract how long the listing has been up."""
    try:
        result = await _eval(
            page, scope,
            r"""(root) => {
                const c = root || document.body;
                const allText = c.innerText;
                const m = allText.match(/Listed\s+((?:about\s+)?(?:an?\s+)?(?:\d+\s+)?(?:weeks?|days?|months?|hours?|minutes?)\s+ago|today|yesterday)\s+in\s+/i);
                if (m) return m[1].trim();
                const m2 = allText.match(/Listed\s+(.*?\s+ago)/i);
                if (m2) return m2[1].trim();
                return '';
            }""",
        )
        return result or ""
    except Exception:
        return ""


async def _scroll_to_seller_section(page, scope) -> bool:
    """Scroll the listing container/modal until the seller section loads."""
    MAX_SCROLLS = 8
    SCROLL_PX = 600
    WAIT_MS = 800

    check_js = """(root) => {
        const c = root || document.body;
        const text = c.innerText || '';
        return text.includes('Seller information')
            || text.includes('Seller details')
            || !!c.querySelector('a[href*="/marketplace/profile/"]');
    }"""

    for i in range(MAX_SCROLLS):
        try:
            found = await _eval(page, scope, check_js)
            if found:
                print(f"  Seller section found after {i} scroll(s)")
                return True
        except Exception:
            pass

        try:
            if scope:
                await scope.evaluate(
                    f"(el) => el.scrollTop += {SCROLL_PX}", scope
                )
            else:
                await page.evaluate(f"window.scrollBy(0, {SCROLL_PX})")
        except Exception:
            pass

        await page.wait_for_timeout(WAIT_MS)

    try:
        found = await _eval(page, scope, check_js)
        if found:
            print(f"  Seller section found after {MAX_SCROLLS} scroll(s)")
            return True
    except Exception:
        pass

    print("  WARNING: Seller section not found after scrolling")
    return False


async def _extract_seller_info(page, scope) -> dict:
    """Extract seller name, rating, listings count, and join date."""
    js_extract = r"""(root) => {
        const c = root || document.body;
        const info = {name: '', rating: '', joined: '', listings: '',
                      profile_url: ''};
        const text = c.innerText || '';

        const uiNoise = new Set([
            'marketplace', 'see more', 'see less', 'message',
            'seller details', 'seller information', "seller's description",
            'about this vehicle', 'send seller a message', 'save',
            'share', 'report listing', 'hide listing',
            'buy now', 'make offer', 'is this still available'
        ]);

        // --- Rating ---
        const ratingMatch = text.match(/(\d\.?\d?)\s+out of\s+5/i);
        if (ratingMatch) info.rating = ratingMatch[1] + '/5';
        if (!info.rating) {
            const rated = text.match(/(?:Rated|Rating)[:\s]+(\d\.?\d?)(?:\/5)?/i);
            if (rated) info.rating = rated[1] + '/5';
        }
        if (!info.rating) {
            const ratingEls = c.querySelectorAll(
                '[aria-label*="rating"], [aria-label*="Rating"], ' +
                '[aria-label*="star"], [aria-label*="Star"]'
            );
            for (const el of ratingEls) {
                const label = el.getAttribute('aria-label');
                const m = label && label.match(/(\d\.?\d?)\s/);
                if (m) { info.rating = m[1] + '/5'; break; }
            }
        }

        // --- Joined date ---
        const joinMatch = text.match(/Joined (?:Facebook )?in (\d{4})/i);
        if (joinMatch) info.joined = joinMatch[1];
        if (!info.joined) {
            const memberMatch = text.match(/Member since (\d{4})/i);
            if (memberMatch) info.joined = memberMatch[1];
        }

        // --- Listings count ---
        const listingsMatch = text.match(
            /(?:Seller|profile)[\s\S]{0,200}?(\d+)\s+(?:listing|item|product)s?/i
        );
        if (listingsMatch) info.listings = listingsMatch[1];
        if (!info.listings) {
            const altMatch = text.match(
                /Seller information[\s\S]{0,300}?(\d+)\s+listings?/i
            );
            if (altMatch) info.listings = altMatch[1];
        }

        // --- Seller name + profile URL ---
        const sellerLinks = c.querySelectorAll(
            'a[href*="/marketplace/profile/"]'
        );
        for (const link of sellerLinks) {
            const name = link.textContent.trim();
            if (name && name.length > 1 && name.length < 50
                && !uiNoise.has(name.toLowerCase())) {
                info.name = name;
                info.profile_url = link.href;
                break;
            }
        }

        if (!info.name) {
            const headings = c.querySelectorAll(
                'span, h2, h3, [role="heading"]'
            );
            for (const h of headings) {
                if (h.textContent.trim().toLowerCase()
                    .includes('seller information')) {
                    const container = h.closest('div')?.parentElement;
                    if (container) {
                        const nameLink = container.querySelector(
                            'a[href*="/marketplace/profile/"]'
                        );
                        if (nameLink) {
                            const n = nameLink.textContent.trim();
                            if (n && !uiNoise.has(n.toLowerCase())) {
                                info.name = n;
                                info.profile_url = nameLink.href;
                            }
                        }
                    }
                    break;
                }
            }
        }

        return info;
    }"""

    result = {}

    try:
        result = await _eval(page, scope, js_extract)
        result = result or {}
    except Exception:
        result = {}

    if not result.get("name") and scope:
        print("  Seller info: scoped extraction found no name, trying full page...")
        try:
            fallback = await page.evaluate(js_extract, None)
            fallback = fallback or {}
            for key in ("name", "rating", "joined", "listings", "profile_url"):
                if not result.get(key) and fallback.get(key):
                    result[key] = fallback[key]
        except Exception:
            pass

    found_fields = [k for k in ("name", "rating", "joined", "listings")
                    if result.get(k)]
    missing_fields = [k for k in ("name", "rating", "joined", "listings")
                      if not result.get(k)]
    if found_fields:
        print(f"  Seller info extracted: {', '.join(found_fields)}")
        if result.get("name"):
            print(f"    name={result['name']}")
        if result.get("rating"):
            print(f"    rating={result['rating']}")
    if missing_fields:
        print(f"  Seller info MISSING: {', '.join(missing_fields)}")
    if not found_fields:
        print("  WARNING: No seller information extracted at all")

    return result


async def _extract_image_urls(page, scope) -> list[str]:
    """Extract listing images by navigating the carousel."""
    urls: list[str] = []
    seen: set[str] = set()

    async def _get_current_image():
        try:
            return await page.evaluate(
                """() => {
                    const imgs = document.querySelectorAll('img[src*="scontent"]');
                    let best = null;
                    let bestArea = 0;
                    for (const img of imgs) {
                        const r = img.getBoundingClientRect();
                        const area = r.width * r.height;
                        if (area > bestArea && r.width > 300 && r.height > 200
                            && r.y < 600) {
                            bestArea = area;
                            best = img.src;
                        }
                    }
                    return best;
                }"""
            )
        except Exception:
            return None

    first_url = await _get_current_image()
    if first_url:
        urls.append(first_url)
        seen.add(first_url)

    MAX_CLICKS = 20
    for _ in range(MAX_CLICKS):
        try:
            clicked = await page.evaluate(
                """() => {
                    const labels = [
                        'Next', 'Next photo', 'Next image',
                        'View next image', 'View next photo'
                    ];
                    for (const label of labels) {
                        const btn = document.querySelector(
                            '[aria-label="' + label + '"]'
                        );
                        if (btn && btn.offsetParent !== null) {
                            btn.click();
                            return true;
                        }
                    }
                    return false;
                }"""
            )

            if not clicked:
                break

            await page.wait_for_timeout(800)

            new_url = await _get_current_image()
            if not new_url or new_url in seen:
                break
            urls.append(new_url)
            seen.add(new_url)
        except Exception:
            break

    if not urls:
        try:
            fallback = await page.evaluate(
                """() => {
                    const imgs = document.querySelectorAll('img[src*="scontent"]');
                    const result = [];
                    const seen = new Set();
                    for (const img of imgs) {
                        const r = img.getBoundingClientRect();
                        if (img.src && !seen.has(img.src)
                            && r.width > 200 && r.height > 200
                            && r.y < 700) {
                            seen.add(img.src);
                            result.push(img.src);
                        }
                    }
                    return result;
                }"""
            )
            urls.extend(fallback or [])
        except Exception:
            pass

    return urls


# ---------------------------------------------------------------------------
# Main scraping logic
# ---------------------------------------------------------------------------

async def _scrape(url: str) -> dict:
    """Core async scraping logic — connects to Chrome via CDP."""
    cdp_url = os.getenv("CHROME_CDP_URL", "http://localhost:9222")

    listing_id_match = re.search(r"marketplace/item/(\d+)", url)
    listing_id = listing_id_match.group(1) if listing_id_match else None

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(cdp_url)
        context = browser.contexts[0]

        page = None
        opened_new_page = False
        if listing_id:
            for existing_page in context.pages:
                if listing_id in existing_page.url:
                    page = existing_page
                    print(f"  Reusing existing Chrome tab: {existing_page.url[:80]}")
                    break

        if page is None:
            page = await context.new_page()
            opened_new_page = True
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)

        try:
            # Wait for Facebook's dynamic content to render
            await page.wait_for_timeout(5000)

            await _take_debug_screenshot(page, "01_after_load")

            scope = await _wait_for_modal(page)

            await _take_debug_screenshot(page, "02_modal_detected")

            title = await _extract_title(page, scope)
            price_text = await _extract_price_text(page, scope)
            description = await _extract_description(page, scope)
            location = await _extract_location(page, scope)
            listing_age_text = await _extract_listing_age(page, scope)

            # Always auto-detect item type from listing content
            print("  Auto-detecting item type...")
            item_type = detect_item_type(title, description)
            print(f"  Detected item type: {item_type}")

            config = get_config(item_type)

            # Extract item-specific details using config labels
            details = await _extract_details(page, scope, config.detail_labels)

            # Parse structured fields using config's title parser
            item_fields = {}
            if config.parse_title:
                item_fields = config.parse_title(title)

            # Build item_name from parsed fields or raw title
            if item_type == "vehicle":
                year = item_fields.get("year", "")
                make = item_fields.get("make", "")
                model = item_fields.get("model", "")
                trim = item_fields.get("trim", "")
                trim_str = f" {trim}" if trim else ""
                item_name = f"{year} {make} {model}{trim_str}".strip() or title
                # Extract mileage for vehicles
                from marketplace_appraiser.item_types.vehicle import extract_mileage
                mileage = (
                    details.get("mileage_int")
                    or extract_mileage(details.get("mileage", ""))
                    or extract_mileage(description)
                    or extract_mileage(str(details))
                )
                if not mileage:
                    try:
                        scope_text = await _eval(
                            page, scope,
                            "(root) => (root || document.body).innerText",
                        )
                        mileage = extract_mileage(scope_text or "")
                    except Exception:
                        pass
                item_fields["mileage"] = mileage
            else:
                item_name = title

            # Merge detail values into item_fields
            for k, v in details.items():
                if k not in item_fields:
                    item_fields[k] = v

            # Scroll to and extract seller info
            await _scroll_to_seller_section(page, scope)
            await _take_debug_screenshot(page, "03_after_scroll_to_seller")

            seller_info = await _extract_seller_info(page, scope)

            # Scroll back to top for image extraction
            try:
                if scope:
                    await scope.evaluate("(el) => el.scrollTop = 0", scope)
                else:
                    await page.evaluate("window.scrollTo(0, 0)")
                await page.wait_for_timeout(500)
            except Exception:
                pass

            image_urls = await _extract_image_urls(page, scope)

            image_paths = download_images_parallel(image_urls, OUTPUT_DIR)

            listed_price = parse_price(price_text) if price_text else None
            listing_age_days = parse_listing_age(listing_age_text) if listing_age_text else None

            return {
                "title": title or "Unknown Item",
                "item_type": item_type,
                "item_name": item_name,
                "item_fields": item_fields,
                "listed_price": listed_price,
                "description": description,
                "location": location,
                "listing_age_text": listing_age_text,
                "listing_age_days": listing_age_days,
                "condition_listed": details.get("condition"),
                "image_paths": image_paths,
                "seller_name": seller_info.get("name", ""),
                "seller_rating": seller_info.get("rating", ""),
                "seller_joined": seller_info.get("joined", ""),
                "seller_listings": seller_info.get("listings", ""),
                "seller_profile_url": seller_info.get("profile_url", ""),
            }
        finally:
            if opened_new_page:
                await page.close()


# ---------------------------------------------------------------------------
# Public node function
# ---------------------------------------------------------------------------

def scrape_listing(state: AppraisalState) -> dict:
    """LangGraph node: scrape a Facebook Marketplace listing."""
    url = state["listing_url"]

    print(f"\n{'='*60}")
    print("STEP 1: Scraping listing from Facebook Marketplace")
    print(f"URL: {url}")
    print(f"{'='*60}\n")

    result = asyncio.run(_scrape(url))

    print(f"  Title: {result.get('title', 'Unknown')}")
    print(f"  Item type: {result.get('item_type', 'Unknown')}")
    print(f"  Item name: {result.get('item_name', 'Unknown')}")
    print(f"  Price: ${result.get('listed_price', 'N/A')}")
    print(f"  Location: {result.get('location', 'N/A')}")

    age_text = result.get("listing_age_text", "")
    age_days = result.get("listing_age_days")
    if age_text:
        age_display = f"{age_text} (~{age_days} days)" if age_days is not None else age_text
        print(f"  Listed: {age_display}")

    print(f"  Description: {len(result.get('description', ''))} chars")

    seller_parts = [result.get("seller_name") or "Unknown"]
    if result.get("seller_rating"):
        seller_parts.append(result["seller_rating"])
    if result.get("seller_joined"):
        seller_parts.append(f"joined {result['seller_joined']}")
    if result.get("seller_listings"):
        seller_parts.append(f"{result['seller_listings']} listings")
    print(f"  Seller: {' · '.join(seller_parts)}")
    print(f"  Images: {len(result.get('image_paths', []))}")

    if result.get("title") in ("Chats", "Marketplace", "", "Unknown Item"):
        print("  WARNING: Title looks like UI text — modal scoping may have failed.")
    if len(result.get("image_paths", [])) > 15:
        print("  WARNING: Unusually many images — may have scraped feed thumbnails.")

    return result
