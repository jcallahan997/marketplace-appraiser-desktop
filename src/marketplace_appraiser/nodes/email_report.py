"""Node 7: Build appraisal report email and send via Gmail SMTP."""

import os
import re
import smtplib
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import markdown

from marketplace_appraiser.state import AppraisalState
from marketplace_appraiser.utils.llm import invoke_llm_light


def _shorten_analysis(text: str, max_sentences: int = 2) -> str:
    """Truncate a vision analysis to the first few sentences."""
    if not text:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    short = " ".join(sentences[:max_sentences])
    if len(sentences) > max_sentences:
        short += "..."
    return short


_DOCUMENT_KEYWORDS = re.compile(
    r"\b(?:document|report|carfax|hagerty|screenshot|valuation|"
    r"certificate|receipt|invoice|title\s+document|paperwork|"
    r"service record|maintenance record|warranty|inspection report|"
    r"vin\s*check|vehicle history|registration|bill of sale|"
    r"window sticker|spec sheet|printout|pdf|scan)\b",
    re.IGNORECASE,
)


def _is_document_photo(analysis_text: str) -> bool:
    """Return True if the vision analysis suggests a document/screenshot."""
    if not analysis_text:
        return False
    return bool(_DOCUMENT_KEYWORDS.search(analysis_text))


def _filter_document_photos(
    image_paths: list,
    image_analyses: list[str],
    max_photos: int,
) -> list:
    """Select up to max_photos actual item photos, filtering out documents.

    Only filters photos that have a corresponding analysis.
    Falls back to original order if all analyzed photos are documents.
    """
    item_photos = []
    document_photos = []
    for i, path in enumerate(image_paths):
        if i < len(image_analyses) and _is_document_photo(image_analyses[i]):
            document_photos.append(path)
        else:
            item_photos.append(path)
    selected = item_photos[:max_photos]
    if len(selected) < max_photos:
        selected.extend(document_photos[: max_photos - len(selected)])
    return selected or list(image_paths[:max_photos])


def _collapsible_html(title: str, content_html: str) -> str:
    """Wrap content in a collapsible <details> block for email brevity."""
    return (
        f'<details style="margin-top: 8px;">'
        f'<summary style="cursor: pointer; color: #008080; font-weight: bold;">'
        f'{title}</summary>'
        f'<div style="padding: 8px 0;">{content_html}</div>'
        f'</details>'
    )


def _truncate_seller_investigation(text: str) -> str:
    """Keep only key sections of seller investigation for email brevity."""
    if not text:
        return ""
    # Keep: Seller Type, Account & Activity, Risk Assessment, Key Findings
    # Drop: Categories Sold, Reputation Signals, Location Consistency
    keep = {"seller type", "account & activity", "account and activity",
            "risk assessment", "key findings"}
    drop = {"categories sold", "reputation signals", "location consistency",
            "professional background"}

    lines = text.split("\n")
    result = []
    include = True
    for line in lines:
        stripped = line.strip().lstrip("#").strip().lower()
        if stripped in keep:
            include = True
        elif stripped in drop:
            include = False
            continue
        if include:
            result.append(line)
    return "\n".join(result).strip()


def _condense_section(text: str, section_name: str, max_words: int = 80) -> str:
    """Use Haiku to condense a long section into a brief summary."""
    if not text or len(text.split()) <= max_words:
        return text
    prompt = f"""\
Condense this {section_name} into {max_words} words or fewer. \
Keep the most important facts. Use bullet points. No preamble.

{text[:2000]}"""
    try:
        result = invoke_llm_light(prompt, max_tokens=512)
        return result.strip()
    except Exception:
        # Fallback: just truncate
        words = text.split()[:max_words]
        return " ".join(words) + "..."


def _extract_section(text: str, section_name: str) -> str:
    """Extract a ## Section from markdown text, returning its body."""
    if not text:
        return ""
    pattern = rf"##\s*{re.escape(section_name)}\s*\n(.*?)(?=\n##\s|\Z)"
    m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _parse_assessment_metrics(text: str) -> dict:
    """Extract key metrics from the price assessment markdown."""
    metrics: dict = {
        "recommendation": "",
        "fair_value": "",
        "target_price": "",
        "confidence": "",
        "price_verdict": "",
        "key_concerns": [],
        "summary": "",
    }
    if not text:
        return metrics

    # Strip markdown bold for parsing
    text_clean = text.replace("**", "")

    # Parse recommendation
    m = re.search(r"RECOMMENDATION[:\s]*(BUY|NEGOTIATE|PASS)", text_clean, re.I)
    if m:
        metrics["recommendation"] = m.group(1).upper()
    else:
        # Fallback: look for standalone BUY/NEGOTIATE/PASS near top
        m = re.search(r"\b(BUY|NEGOTIATE|PASS)\b", text_clean[:500])
        if m:
            metrics["recommendation"] = m.group(1).upper()

    # Parse fair value — same line or next line after header
    m = re.search(
        r"(?:FAIR VALUE|CONDITION[- ]ADJUSTED(?:\s+FAIR)?\s+VALUE)"
        r"[:\s]*\$?([\d,]+)",
        text_clean, re.I,
    )
    if not m:
        # Next-line: header then \n then $amount
        m = re.search(
            r"(?:FAIR VALUE|CONDITION[- ]ADJUSTED(?:\s+FAIR)?\s+VALUE)"
            r"\s*\n+\s*\$?([\d,]+)",
            text_clean, re.I,
        )
    if not m:
        # Inline: "fair market value of $X" or "fair value around $X"
        m = re.search(
            r"fair\s+(?:market\s+)?value\s+(?:of|around|at|is|:)\s*\$?([\d,]+)",
            text_clean, re.I,
        )
    if m:
        metrics["fair_value"] = f"${m.group(1)}"

    # Parse target price — same line or next line
    m = re.search(r"TARGET PRICE[:\s]*\$?([\d,]+)", text_clean, re.I)
    if not m:
        m = re.search(r"TARGET PRICE\s*\n+\s*\$?([\d,]+)", text_clean, re.I)
    if not m:
        # "negotiate to $X" or "target of $X"
        m = re.search(
            r"(?:negotiate\s+(?:to|down to|around)|target\s+(?:of|:))\s*\$?([\d,]+)",
            text_clean, re.I,
        )
    if m:
        metrics["target_price"] = f"${m.group(1)}"

    # Parse confidence — same line or next line
    m = re.search(
        r"CONFIDENCE\s*(?:LEVEL)?[:\s]*(HIGH|MEDIUM|LOW)", text_clean, re.I,
    )
    if not m:
        m = re.search(
            r"CONFIDENCE\s*(?:LEVEL)?\s*\n+\s*(HIGH|MEDIUM|LOW)",
            text_clean, re.I,
        )
    if m:
        metrics["confidence"] = m.group(1).upper()

    # Parse price verdict — try labeled first, then standalone
    m = re.search(
        r"(?:PRICE\s+(?:IS|ASSESSMENT|VERDICT|EVALUATION))[:\s]*"
        r"(SEVERELY\s+OVERPRICED|OVERPRICED|UNDERPRICED|FAIRLY?\s*PRICED|FAIR)\b",
        text_clean, re.I,
    )
    if not m:
        # Fallback: standalone verdict word NOT followed by "Value"
        m = re.search(
            r"\b(SEVERELY\s+OVERPRICED|OVERPRICED|UNDERPRICED)\b",
            text_clean, re.I,
        )
    if m:
        metrics["price_verdict"] = m.group(1).strip().upper()

    # Parse key concerns — look for bulleted lists under concern headers.
    # Use specific prefixes to avoid matching "Flip Risk" or "Seller Risk".
    concerns_pattern = re.search(
        r"(?:KEY CONCERNS?|NOTABLE (?:ISSUES|CONCERNS?)|"
        r"(?:ISSUES|CONCERNS)\s+(?:AND|&)\s+(?:RISKS?|CONCERNS?)|"
        r"MAJOR CONCERNS?)"
        r"\s*:?\s*\n(.*?)(?=\n[A-Z][A-Z ]{3,}|\n##|\n\d+\.\s+[A-Z]|\Z)",
        text_clean, re.DOTALL | re.I,
    )
    if concerns_pattern:
        for line in concerns_pattern.group(1).strip().splitlines():
            line = re.sub(r"^\s*(?:\d+[.)]\s*|[-•*]\s+)", "", line).strip()
            if line and len(line) > 10:
                metrics["key_concerns"].append(
                    line[:120] + ("..." if len(line) > 120 else "")
                )
        metrics["key_concerns"] = metrics["key_concerns"][:5]

    # Fallback: if no concerns found, look for a numbered "Notable Issues"
    # or "Concerns" section with list items
    if not metrics["key_concerns"]:
        issues_match = re.search(
            r"(?:NOTABLE ISSUES|LIST OF (?:NOTABLE )?(?:ISSUES|CONCERNS))"
            r"\s*:?\s*\n(.*?)(?=\n[A-Z][A-Z ]{3,}|\n##|\n\d+\.\s+[A-Z]|\Z)",
            text_clean, re.DOTALL | re.I,
        )
        if issues_match:
            for line in issues_match.group(1).strip().splitlines():
                line = re.sub(r"^\s*(?:\d+[.)]\s*|[-•*]\s+)", "", line).strip()
                if line and len(line) > 10:
                    metrics["key_concerns"].append(
                        line[:120] + ("..." if len(line) > 120 else "")
                    )
            metrics["key_concerns"] = metrics["key_concerns"][:5]

    # Second fallback: extract concern-like bullet points from body text
    if not metrics["key_concerns"]:
        concern_keywords = (
            r"(?:concern|risk|issue|caution|warning|red flag|"
            r"problem|drawback|downside|caveat)"
        )
        for line in text_clean.splitlines():
            stripped = re.sub(
                r"^\s*(?:\d+[.)]\s*|[-•*]\s+)", "", line,
            ).strip()
            if (
                stripped
                and len(stripped) > 10
                and re.search(concern_keywords, stripped, re.I)
                and not stripped.isupper()  # skip section headers
            ):
                metrics["key_concerns"].append(
                    stripped[:120] + ("..." if len(stripped) > 120 else "")
                )
            if len(metrics["key_concerns"]) >= 5:
                break

    # Parse summary paragraph
    summary_match = re.search(
        r"(?:SUMMARY|BUYER(?:'?S)? SUMMARY)[:\s]*\n(.*?)(?=\n[A-Z][A-Z ]{3,}|\n##|\Z)",
        text_clean, re.DOTALL | re.I,
    )
    if summary_match:
        metrics["summary"] = summary_match.group(1).strip()

    return metrics


def _section_card(
    title: str,
    content_html: str,
    title_color: str = "#008080",
    border_color: str = "#e0e0e0",
) -> str:
    """Wrap content in a bordered card table for email layout."""
    return (
        f'<table width="100%" cellpadding="0" cellspacing="0" '
        f'style="margin-top: 20px; border: 1px solid {border_color}; '
        f'border-radius: 8px;">'
        f'<tr><td style="padding: 16px;">'
        f'<h2 style="color: {title_color}; margin: 0 0 12px 0; '
        f'font-size: 18px;">{title}</h2>'
        f'{content_html}'
        f'</td></tr></table>'
    )


def build_report(state: AppraisalState) -> dict:
    """Build the appraisal email content from pipeline state.

    Returns a dict with keys:
        subject (str): Email subject line
        html_body (str): Full HTML email body
        plain_body (str): Plain-text fallback
        email_image_paths (list[Path]): Image files to embed
        item_name (str): For display/logging
    """
    # --- Extract state fields ---
    item_name = state.get("item_name", "Unknown Item")
    item_type = state.get("item_type", "vehicle")
    listed_price_raw = state.get("listed_price", "N/A")
    location = state.get("location", "N/A")
    listing_url = state.get("listing_url", "")

    # Format price cleanly — avoid "$123.0", prefer "$123" or "$1,234"
    if isinstance(listed_price_raw, (int, float)):
        if listed_price_raw == int(listed_price_raw):
            listed_price = f"{int(listed_price_raw):,}"
        else:
            listed_price = f"{listed_price_raw:,.2f}"
    else:
        listed_price = str(listed_price_raw).rstrip("0").rstrip(".")
    price_assessment = state.get("price_assessment", "")
    condition_report = state.get("condition_report", "")
    image_analyses = state.get("image_analyses", [])
    seller_name = state.get("seller_name", "")
    seller_rating = state.get("seller_rating", "")
    description = state.get("description", "")
    condition_listed = state.get("condition_listed", "")

    # --- LLM generates subject line ---
    prompt = f"""\
Write a single email subject line for this {item_type} appraisal.

Item: {item_name}
Listed Price: ${listed_price}

Assessment excerpt:
{price_assessment[:500]}

Format: [RECOMMENDATION] Item Name — $ListedPrice (Fair value: $FairValue)
Example: [NEGOTIATE] 2015 Toyota Camry — $12,000 (Fair value: $9,500)

Output ONLY the subject line, nothing else. No quotes, no prefix."""

    subject_raw = invoke_llm_light(prompt)
    subject = subject_raw.strip().split("\n")[0].strip()

    for prefix in ("Subject:", "Subject Line:", "**Subject:**", "**Subject Line:**"):
        if subject.lower().startswith(prefix.lower()):
            subject = subject[len(prefix):].strip()
    if len(subject) > 2 and subject[0] in ('"', "'") and subject[-1] == subject[0]:
        subject = subject[1:-1]

    if not re.search(r"\[.+\]\s+.+\s+—\s+\$[\d,]+", subject):
        price_display = f"${listed_price:,.0f}" if isinstance(listed_price, (int, float)) else str(listed_price)
        subject = f"[REVIEW] {item_name} — {price_display}"
        print(f"  Subject (fallback): {subject}")
    else:
        print(f"  Subject: {subject}")

    # --- Collect images ---
    image_paths = [
        Path(p) for p in state.get("image_paths", []) if Path(p).exists()
    ]

    # --- Build HTML email body ---

    seller_joined = state.get("seller_joined", "")
    seller_listings = state.get("seller_listings", "")
    seller_ethnicity = state.get("seller_ethnicity", "")
    seller_ethnicity_reasoning = state.get("seller_ethnicity_reasoning", "")
    listing_age_text = state.get("listing_age_text", "")
    listing_age_days = state.get("listing_age_days")
    seller_investigation = state.get("seller_investigation", "")
    seller_risk_level = state.get("seller_risk_level", "")

    # --- Parse key metrics from price assessment ---
    metrics = _parse_assessment_metrics(price_assessment)
    recommendation = metrics["recommendation"] or "REVIEW"
    fair_value = metrics["fair_value"]
    target_price = metrics["target_price"]
    confidence = metrics["confidence"] or "—"
    key_concerns = metrics["key_concerns"]
    summary = metrics["summary"]

    # ===================================================================
    # 1. COMPACT HEADER
    # ===================================================================
    seller_info_parts = []
    if seller_name:
        seller_info_parts.append(seller_name)
    if seller_ethnicity:
        seller_info_parts.append(f"({seller_ethnicity})")
    if seller_rating:
        seller_info_parts.append(seller_rating)
    if seller_joined:
        seller_info_parts.append(f"joined {seller_joined}")
    if seller_listings:
        seller_info_parts.append(f"{seller_listings} listings")
    seller_info_line = (
        f'Seller: {" &middot; ".join(seller_info_parts)}'
        if seller_info_parts else ""
    )

    listing_age_line = ""
    if listing_age_text:
        age_display = listing_age_text
        if listing_age_days is not None:
            age_display = f"{listing_age_text} (~{listing_age_days} days)"
        age_color = "#c0392b" if (listing_age_days and listing_age_days > 30) else "#666"
        listing_age_line = (
            f'<span style="color: {age_color};">Listed {age_display}</span>'
        )

    meta_parts = [item_type.title(), f"${listed_price}", location]
    if condition_listed:
        meta_parts.append(condition_listed)
    meta_line = " &middot; ".join(meta_parts)

    link_html = ""
    if listing_url:
        link_html = (
            f' &middot; <a href="{listing_url}" style="color: #008080;">'
            f"View Listing &rarr;</a>"
        )

    header_html = (
        f'<h1 style="color: #008080; margin: 0 0 4px 0; font-size: 24px;">'
        f"{item_name}</h1>"
        f'<p style="color: #666; font-size: 14px; margin: 0 0 4px 0;">'
        f"{meta_line}</p>"
        f'<p style="color: #666; font-size: 14px; margin: 0 0 12px 0;">'
        f"{seller_info_line}"
        f'{f" &middot; {listing_age_line}" if listing_age_line else ""}'
        f"{link_html}</p>"
    )

    # ===================================================================
    # 2. VERDICT BANNER
    # ===================================================================
    rec_colors = {"BUY": "#27ae60", "NEGOTIATE": "#f39c12", "PASS": "#c0392b"}
    rec_bg = {"BUY": "#eafaf1", "NEGOTIATE": "#fef9e7", "PASS": "#fdedec"}
    rec_color = rec_colors.get(recommendation, "#333")
    rec_background = rec_bg.get(recommendation, "#f5f5f5")

    target_td = ""
    if target_price and recommendation == "NEGOTIATE":
        target_td = (
            f'<td style="padding-right: 24px;">'
            f'<span style="color: #888; font-size: 12px; '
            f'text-transform: uppercase;">Target</span><br>'
            f'<span style="font-size: 22px; font-weight: bold;">'
            f"{target_price}</span></td>"
        )

    summary_p = ""
    if summary:
        summary_p = (
            f'<p style="color: #555; font-size: 14px; margin: 12px 0 0 0; '
            f'line-height: 1.5;">{summary}</p>'
        )

    verdict_html = (
        f'<table width="100%" cellpadding="0" cellspacing="0" '
        f'style="margin: 16px 0;">'
        f"<tr><td style=\"background: {rec_background}; "
        f"border-left: 5px solid {rec_color}; "
        f'border-radius: 8px; padding: 20px;">'
        f'<div style="font-size: 28px; font-weight: bold; color: {rec_color}; '
        f'margin-bottom: 8px;">{recommendation}</div>'
        f'<table cellpadding="0" cellspacing="0" '
        f'style="font-size: 15px; color: #333;">'
        f"<tr>"
        f'<td style="padding-right: 24px;">'
        f'<span style="color: #888; font-size: 12px; '
        f'text-transform: uppercase;">Fair Value</span><br>'
        f'<span style="font-size: 22px; font-weight: bold;">'
        f'{fair_value or "—"}</span></td>'
        f'<td style="padding-right: 24px;">'
        f'<span style="color: #888; font-size: 12px; '
        f'text-transform: uppercase;">Listed</span><br>'
        f'<span style="font-size: 22px; font-weight: bold;">'
        f"${listed_price}</span></td>"
        f"{target_td}"
        f"<td>"
        f'<span style="color: #888; font-size: 12px; '
        f'text-transform: uppercase;">Confidence</span><br>'
        f'<span style="font-size: 16px; font-weight: bold;">'
        f"{confidence}</span></td>"
        f"</tr></table>"
        f"{summary_p}"
        f"</td></tr></table>"
    )

    # ===================================================================
    # 3. STATS INDICATOR ROW
    # ===================================================================
    flip_risk_level = state.get("flip_risk_level", "NONE")
    flip_risk_summary = state.get("flip_risk_summary", "")

    risk_color_map = {
        "NONE": "#27ae60", "LOW": "#f39c12",
        "MEDIUM": "#e67e22", "HIGH": "#c0392b",
    }
    flip_color = risk_color_map.get(flip_risk_level, "#333")
    flip_display = flip_risk_level if flip_risk_level != "NONE" else "None"

    # Seller risk color
    seller_risk_colors = {"LOW": "#27ae60", "MEDIUM": "#f39c12", "HIGH": "#c0392b"}
    seller_risk_color = seller_risk_colors.get(seller_risk_level, "#333")
    seller_risk_display = seller_risk_level or "—"

    # Parse condition rating from condition report
    condition_rating = "—"
    if condition_report:
        cond_match = re.search(
            r"(EXCELLENT|VERY GOOD|GOOD|FAIR|POOR|LIKE NEW)",
            condition_report[:500], re.I,
        )
        if cond_match:
            condition_rating = cond_match.group(1).title()

    stats_html = (
        f'<table width="100%" cellpadding="0" cellspacing="8" '
        f'style="margin-bottom: 16px;">'
        f"<tr>"
        f'<td width="33%" style="background: #f8f9fa; border-radius: 6px; '
        f'padding: 12px; text-align: center;">'
        f'<div style="font-size: 11px; color: #888; '
        f'text-transform: uppercase;">Flip Risk</div>'
        f'<div style="font-size: 18px; font-weight: bold; '
        f'color: {flip_color};">{flip_display}</div></td>'
        f'<td width="33%" style="background: #f8f9fa; border-radius: 6px; '
        f'padding: 12px; text-align: center;">'
        f'<div style="font-size: 11px; color: #888; '
        f'text-transform: uppercase;">Seller Risk</div>'
        f'<div style="font-size: 18px; font-weight: bold; '
        f'color: {seller_risk_color};">{seller_risk_display}</div></td>'
        f'<td width="33%" style="background: #f8f9fa; border-radius: 6px; '
        f'padding: 12px; text-align: center;">'
        f'<div style="font-size: 11px; color: #888; '
        f'text-transform: uppercase;">Condition</div>'
        f'<div style="font-size: 18px; font-weight: bold; '
        f'color: #333;">{condition_rating}</div></td>'
        f"</tr></table>"
    )

    # ===================================================================
    # 4. KEY CONCERNS BOX
    # ===================================================================
    concerns_html = ""
    if key_concerns:
        items = "".join(
            f'<tr><td style="color: #e74c3c; padding: 0 8px 0 0; '
            f'vertical-align: top; font-size: 16px;">&#9888;</td>'
            f'<td style="padding-bottom: 6px; font-size: 14px;">{c}</td></tr>'
            for c in key_concerns[:5]
        )
        concerns_html = (
            f'<table width="100%" cellpadding="0" cellspacing="0" '
            f'style="background: #fff5f5; border-left: 4px solid #e74c3c; '
            f'border-radius: 6px; padding: 14px; margin-bottom: 16px;">'
            f"<tr><td>"
            f'<div style="font-weight: bold; color: #c0392b; '
            f'margin-bottom: 8px;">Key Concerns</div>'
            f"<table>{items}</table>"
            f"</td></tr></table>"
        )

    # ===================================================================
    # 5. FULL PRICE ASSESSMENT (collapsible)
    # ===================================================================
    assessment_html = markdown.markdown(
        price_assessment, extensions=["tables", "fenced_code"]
    )
    assessment_section = _collapsible_html(
        "Full Price Assessment", assessment_html
    )

    # ===================================================================
    # 6. SELLER PROFILE CARD
    # ===================================================================
    seller_profile_html = ""
    if seller_investigation:
        risk_badge_colors = {"LOW": "#27ae60", "MEDIUM": "#f39c12", "HIGH": "#c0392b"}
        risk_color = risk_badge_colors.get(seller_risk_level, "#333")

        seller_brief = _truncate_seller_investigation(seller_investigation)
        seller_rendered = markdown.markdown(
            seller_brief, extensions=["tables", "fenced_code"]
        )

        # Active listings from profile — collapsible
        active_listings = state.get("seller_active_listings", [])
        listings_html = ""
        if active_listings:
            listings_items = []
            for lst in active_listings[:10]:
                title = lst.get("title", "Unknown")
                price = lst.get("price", "")
                listings_items.append(f"<li>{title} — {price}</li>")
            inner = f'<ul style="font-size: 14px;">{"".join(listings_items)}</ul>'
            listings_html = _collapsible_html(
                f"Other Active Listings ({len(active_listings)})", inner
            )

        # Seller bio parts
        seller_profile_data = state.get("seller_profile", {}) or {}
        bio_text = seller_profile_data.get("bio", "")
        bio_html_inner = ""
        if bio_text:
            bio_escaped = (
                bio_text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace("\n", "<br>")
            )
            bio_html_inner += (
                f'<p style="font-size: 14px;"><strong>Bio:</strong> '
                f"{bio_escaped}</p>"
            )
        biz_name = seller_profile_data.get("business_name", "")
        biz_info = seller_profile_data.get("business_info", "")
        if biz_name:
            bio_html_inner += (
                f'<p style="font-size: 14px;"><strong>Business:</strong> '
                f"{biz_name}"
                + (f" — {biz_info}" if biz_info else "")
                + "</p>"
            )
        prof_bg = _extract_section(seller_investigation, "Professional Background")
        if prof_bg and prof_bg.lower() != "no professional profile found.":
            prof_rendered = markdown.markdown(prof_bg, extensions=["tables"])
            bio_html_inner += (
                f'<div style="font-size: 14px;">'
                f"<strong>Professional Background:</strong>"
                f"{prof_rendered}</div>"
            )
        bio_collapsible = ""
        if bio_html_inner:
            bio_collapsible = _collapsible_html(
                "Bio &amp; Background", bio_html_inner
            )

        seller_card_content = (
            f'<span style="color: {risk_color}; font-size: 14px; '
            f'font-weight: bold;">[{seller_risk_level} RISK]</span>'
            f"{seller_rendered}{listings_html}{bio_collapsible}"
        )
        seller_profile_html = _section_card("Seller Profile", seller_card_content)
    else:
        # Minimal seller card even without investigation
        seller_profile_data = state.get("seller_profile", {}) or {}
        bio_text = seller_profile_data.get("bio", "")
        biz_name = seller_profile_data.get("business_name", "")
        biz_info = seller_profile_data.get("business_info", "")
        prof_bg = ""

    # ===================================================================
    # 7. FLIP RISK CARD
    # ===================================================================
    # Check if price assessment identified flip risk as a false positive
    fp_indicators = [
        "false positive", "not a flip", "not flipping",
        "collector", "classic car", "enthusiast",
    ]
    assessment_lower = price_assessment.lower()
    is_flip_fp = (
        flip_risk_level == "HIGH"
        and any(ind in assessment_lower for ind in fp_indicators)
    )

    flip_html = ""
    if flip_risk_level and flip_risk_level != "NONE":
        badge_color = risk_color_map.get(flip_risk_level, "#333")
        if is_flip_fp:
            badge_color = "#f39c12"
            flip_risk_display_detail = f"{flip_risk_level}*"
        else:
            flip_risk_display_detail = flip_risk_level

        flip_rendered = markdown.markdown(
            flip_risk_summary, extensions=["tables", "fenced_code"]
        )
        fp_note = ""
        if is_flip_fp:
            fp_note = (
                '<p style="color: #888; font-size: 13px; font-style: italic;">'
                "Note: Price assessment identifies this as a likely false "
                "positive.</p>"
            )
        flip_card_content = (
            f'<span style="color: {badge_color}; font-size: 16px; '
            f'font-weight: bold;">{flip_risk_display_detail}</span>'
            f"{flip_rendered}{fp_note}"
        )
        flip_html = _section_card(
            "Flip Risk", flip_card_content, border_color="#f5c6cb"
        )

    # ===================================================================
    # 8. SAFETY RECALLS CARD (condensed)
    # ===================================================================
    safety_info = state.get("safety_info", "")
    safety_html = ""
    if safety_info:
        # Count recalls and extract short summaries
        recall_blocks = re.split(r"\n\s*-\s+\[", safety_info)
        # First block is the header line, rest are recalls
        header_line = recall_blocks[0].strip()
        recalls = [f"[{b}" for b in recall_blocks[1:]] if len(recall_blocks) > 1 else []
        recall_count = len(recalls)

        if recall_count > 0:
            # Build short summary list (ID + first sentence only)
            summary_items = []
            for recall in recalls[:3]:
                # Extract recall ID and category
                id_match = re.match(r"\[(\w+)\]\s*(.*?):", recall)
                if id_match:
                    rid = id_match.group(1)
                    category = id_match.group(2).strip()
                    # Get first sentence of description
                    desc_start = recall.find(":") + 1
                    desc = recall[desc_start:].strip()
                    first_sentence = re.split(r"(?<=[.!])\s", desc)[0]
                    if len(first_sentence) > 120:
                        first_sentence = first_sentence[:117] + "..."
                    summary_items.append(
                        f'<li style="margin-bottom: 4px; font-size: 13px;">'
                        f"<strong>{rid}</strong> {category}: "
                        f"{first_sentence}</li>"
                    )
                else:
                    short = recall[:120].replace("\n", " ")
                    summary_items.append(
                        f'<li style="margin-bottom: 4px; font-size: 13px;">'
                        f"{short}...</li>"
                    )

            visible = f'<ul style="padding-left: 18px;">{"".join(summary_items)}</ul>'
            if recall_count > 3:
                visible += (
                    f'<p style="color: #888; font-size: 12px;">'
                    f"+ {recall_count - 3} more recall(s)</p>"
                )

            # Full details in collapsible
            full_rendered = markdown.markdown(
                safety_info, extensions=["tables", "fenced_code"],
            )
            full_details = _collapsible_html("View All Recall Details", full_rendered)

            safety_card_content = f"{visible}{full_details}"
        else:
            safety_card_content = markdown.markdown(
                safety_info, extensions=["tables", "fenced_code"],
            )

        recall_badge = (
            f' <span style="background: #c0392b; color: white; '
            f"font-size: 12px; padding: 2px 8px; border-radius: 10px; "
            f'margin-left: 8px;">{recall_count}</span>'
            if recall_count > 0 else ""
        )
        safety_html = _section_card(
            f"Safety Recalls{recall_badge}", safety_card_content,
            title_color="#c0392b", border_color="#f5c6cb",
        )

    # ===================================================================
    # 9. PHOTO GRID (2-column, 4 photos)
    # ===================================================================
    max_photos = 4
    photos_html = ""
    email_image_paths = _filter_document_photos(
        image_paths, image_analyses, max_photos,
    )
    if email_image_paths:
        rows_html = ""
        for row_start in range(0, len(email_image_paths), 2):
            cells = []
            for offset in range(2):
                idx = row_start + offset
                if idx < len(email_image_paths):
                    cid = f"listing_photo_{idx}"
                    caption = ""
                    try:
                        orig_idx = list(image_paths).index(
                            email_image_paths[idx]
                        )
                    except ValueError:
                        orig_idx = idx
                    if orig_idx < len(image_analyses):
                        caption = _shorten_analysis(
                            image_analyses[orig_idx], max_sentences=1,
                        )
                    caption_p = ""
                    if caption:
                        caption_p = (
                            f'<p style="color: #666; font-size: 12px; '
                            f'margin: 4px 0 8px 0;">{caption}</p>'
                        )
                    cells.append(
                        f'<td width="50%" style="padding: 4px; '
                        f'vertical-align: top;">'
                        f'<img src="cid:{cid}" style="width: 100%; '
                        f'border-radius: 6px;" alt="Photo {idx + 1}">'
                        f"{caption_p}</td>"
                    )
                else:
                    cells.append('<td width="50%"></td>')
            rows_html += f'<tr>{"".join(cells)}</tr>'

        extra_note = ""
        if len(image_paths) > max_photos:
            extra_note = (
                f'<p style="color: #888; font-size: 13px; margin-top: 4px;">'
                f"{len(image_paths) - max_photos} more photo(s) in listing</p>"
            )
        photos_html = (
            f'<h2 style="color: #008080; margin-top: 24px;">Photos</h2>'
            f'<table width="100%" cellpadding="0" cellspacing="0">'
            f"{rows_html}</table>{extra_note}"
        )

    # ===================================================================
    # 10-12. COLLAPSIBLE BOTTOM SECTIONS
    # ===================================================================
    # Condense once and reuse for both HTML and plain text
    condensed_condition = ""
    condition_html = ""
    if condition_report:
        condensed_condition = _condense_section(condition_report, "condition report")
        print(f"  Condition (condensed): {condensed_condition[:120]}...")
        rendered = markdown.markdown(condensed_condition, extensions=["tables"])
        condition_html = _collapsible_html("Condition Summary", rendered)

    description_research = state.get("description_research", "")
    condensed_research = ""
    research_html = ""
    if description_research:
        condensed_research = _condense_section(
            description_research, "research findings",
        )
        print(f"  Research (condensed): {condensed_research[:120]}...")
        rendered = markdown.markdown(condensed_research, extensions=["tables"])
        research_html = _collapsible_html("Research Findings", rendered)

    description_html = ""
    if description:
        desc_escaped = (
            description.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace("\n", "<br>")
        )
        description_html = _collapsible_html(
            "Seller's Description",
            f'<p style="font-size: 14px;">{desc_escaped}</p>',
        )

    # ===================================================================
    # ASSEMBLE HTML — new section order
    # ===================================================================
    html_body = f"""\
<html><body style="font-family: -apple-system, BlinkMacSystemFont, sans-serif; \
max-width: 700px; margin: 0 auto; padding: 16px; color: #222;">
{header_html}
{verdict_html}
{stats_html}
{concerns_html}
{assessment_section}
{seller_profile_html}
{flip_html}
{safety_html}
{photos_html}
{condition_html}
{research_html}
{description_html}
</body></html>"""

    # --- Plain text fallback ---
    seller_text = ""
    if seller_name or seller_rating:
        parts = []
        if seller_name:
            parts.append(seller_name)
        if seller_ethnicity:
            parts.append(f"({seller_ethnicity})")
        if seller_rating:
            parts.append(seller_rating)
        if seller_joined:
            parts.append(f"joined {seller_joined}")
        if seller_listings:
            parts.append(f"{seller_listings} listings")
        seller_text = f"\nSeller: {' — '.join(parts)}"
        if seller_ethnicity_reasoning:
            seller_text += f"\n  Background reasoning: {seller_ethnicity_reasoning}"

    condition_text = f"\nCondition: {condition_listed}" if condition_listed else ""
    listing_age_plain = ""
    if listing_age_text:
        if listing_age_days is not None:
            listing_age_plain = f"\nListed: {listing_age_text} (~{listing_age_days} days)"
        else:
            listing_age_plain = f"\nListed: {listing_age_text}"

    plain_body = f"""\
{item_name}
Listed Price: ${listed_price} | Location: {location}{condition_text}{seller_text}{listing_age_plain}
Listing: {listing_url}

--- PRICE ASSESSMENT ---

{price_assessment}

"""
    if seller_investigation:
        plain_body += f"--- SELLER PROFILE ({seller_risk_level} RISK) ---\n\n{seller_investigation}\n\n"

    # Plain text seller bio — use seller_profile_data from HTML section
    bio_plain_parts = []
    pt_bio = (state.get("seller_profile") or {}).get("bio", "")
    pt_biz = (state.get("seller_profile") or {}).get("business_name", "")
    pt_biz_info = (state.get("seller_profile") or {}).get("business_info", "")
    pt_prof_bg = _extract_section(seller_investigation, "Professional Background")
    if pt_bio:
        bio_plain_parts.append(f"Bio: {pt_bio}")
    if pt_biz:
        bio_plain_parts.append(f"Business: {pt_biz}" + (f" — {pt_biz_info}" if pt_biz_info else ""))
    if pt_prof_bg and pt_prof_bg.lower() != "no professional profile found.":
        bio_plain_parts.append(f"Professional Background:\n{pt_prof_bg}")
    if bio_plain_parts:
        plain_body += "--- SELLER BIO & BACKGROUND ---\n\n" + "\n\n".join(bio_plain_parts) + "\n\n"

    if flip_risk_level and flip_risk_level != "NONE":
        fp_suffix = ""
        if is_flip_fp:
            fp_suffix = "\n\n(Note: Price assessment identifies this as a likely false positive.)"
        plain_body += f"--- FLIP RISK: {flip_risk_level} ---\n\n{flip_risk_summary}{fp_suffix}\n\n"

    if safety_info:
        plain_body += f"--- SAFETY RECALLS ---\n\n{safety_info}\n\n"

    if email_image_paths:
        plain_body += "--- LISTING PHOTOS ---\n\n"
        for i, img_path in enumerate(email_image_paths):
            caption = ""
            try:
                orig_idx = list(image_paths).index(img_path)
            except ValueError:
                orig_idx = i
            if orig_idx < len(image_analyses):
                caption = _shorten_analysis(
                    image_analyses[orig_idx], max_sentences=1,
                )
            plain_body += f"Photo {i + 1}: {caption}\n\n"
        if len(image_paths) > max_photos:
            plain_body += f"({len(image_paths) - max_photos} more photo(s) in listing)\n\n"

    if condensed_condition:
        plain_body += f"--- CONDITION SUMMARY ---\n\n{condensed_condition}\n\n"

    if condensed_research:
        plain_body += f"--- RESEARCH FINDINGS ---\n\n{condensed_research}\n\n"

    if description:
        plain_body += f"--- SELLER'S DESCRIPTION ---\n\n{description}\n\n"

    return {
        "subject": subject,
        "html_body": html_body,
        "plain_body": plain_body,
        "email_image_paths": email_image_paths,
        "item_name": item_name,
    }


def send_report_email(
    subject: str,
    html_body: str,
    plain_body: str,
    email_image_paths: list,
    email_to: str,
    gmail_user: str | None = None,
    gmail_app_password: str | None = None,
) -> tuple[bool, str]:
    """Send the appraisal email via Gmail SMTP.

    Args:
        subject: Email subject line.
        html_body: Full HTML email body.
        plain_body: Plain-text fallback.
        email_image_paths: Image files to embed as inline attachments.
        email_to: Recipient address.
        gmail_user: Gmail sender (defaults to env GMAIL_USER).
        gmail_app_password: Gmail app password (defaults to env GMAIL_APP_PASSWORD).

    Returns:
        (success: bool, error_message: str) — error_message is "" on success.
    """
    gmail_user = gmail_user or os.getenv("GMAIL_USER", "")
    gmail_app_password = gmail_app_password or os.getenv("GMAIL_APP_PASSWORD", "")

    missing = []
    if not gmail_user:
        missing.append("GMAIL_USER")
    if not gmail_app_password:
        missing.append("GMAIL_APP_PASSWORD")
    if missing:
        return False, f"Missing env vars: {', '.join(missing)}"

    try:
        msg = MIMEMultipart("related")
        msg["From"] = gmail_user
        msg["To"] = email_to
        msg["Subject"] = subject

        msg_alt = MIMEMultipart("alternative")
        msg_alt.attach(MIMEText(plain_body, "plain"))
        msg_alt.attach(MIMEText(html_body, "html"))
        msg.attach(msg_alt)

        for i, img_path in enumerate(email_image_paths):
            cid = f"listing_photo_{i}"
            img_data = Path(img_path).read_bytes()
            suffix = Path(img_path).suffix.lower().lstrip(".")
            subtype = "jpeg" if suffix in ("jpg", "jpeg") else suffix
            img_part = MIMEImage(img_data, _subtype=subtype)
            img_part.add_header("Content-ID", f"<{cid}>")
            img_part.add_header(
                "Content-Disposition", "inline",
                filename=Path(img_path).name,
            )
            msg.attach(img_part)

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_user, gmail_app_password)
            server.sendmail(gmail_user, email_to, msg.as_string())

        return True, ""

    except Exception as e:
        return False, str(e)


def email_report(state: AppraisalState) -> dict:
    """LangGraph node: build the appraisal as an HTML email and send it.

    Backward-compatible — calls build_report() then send_report_email().
    """
    email_to = state.get("email_to") or os.getenv("EMAIL_TO", "")

    if not email_to:
        print("\n  No email recipient configured — skipping email.")
        print("  To fix: set EMAIL_TO or GMAIL_USER in .env,")
        print("  or pass --email recipient@example.com")
        return {"email_sent": False, "email_summary": ""}

    gmail_user = os.getenv("GMAIL_USER", "")
    gmail_app_password = os.getenv("GMAIL_APP_PASSWORD", "")

    missing = []
    if not gmail_user:
        missing.append("GMAIL_USER")
    if not gmail_app_password:
        missing.append("GMAIL_APP_PASSWORD")
    if missing:
        print(f"\n  Missing env vars: {', '.join(missing)} — skipping email.")
        return {"email_sent": False, "email_summary": ""}

    print(f"\n{'='*60}")
    print("STEP 7: Building appraisal email")
    print(f"{'='*60}\n")

    report = build_report(state)
    subject = report["subject"]
    email_image_paths = report["email_image_paths"]
    image_paths = [
        Path(p) for p in state.get("image_paths", []) if Path(p).exists()
    ]

    print(f"  Sending to {email_to}...")
    if email_image_paths:
        print(f"  Embedded {len(email_image_paths)} of {len(image_paths)} photo(s)")

    success, error = send_report_email(
        subject=report["subject"],
        html_body=report["html_body"],
        plain_body=report["plain_body"],
        email_image_paths=report["email_image_paths"],
        email_to=email_to,
        gmail_user=gmail_user,
        gmail_app_password=gmail_app_password,
    )

    if success:
        print("  Email sent successfully.")
        return {"email_sent": True, "email_summary": subject}
    else:
        print(f"  Error sending email: {error}")
        return {"email_sent": False, "email_summary": subject}
