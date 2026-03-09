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


def email_report(state: AppraisalState) -> dict:
    """LangGraph node: build the appraisal as an HTML email and send it."""
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

    seller_row = ""
    if seller_name or seller_rating:
        seller_parts = []
        if seller_name:
            seller_parts.append(seller_name)
        if seller_ethnicity:
            seller_parts.append(
                f'<span style="color: #888; font-size: 13px;">'
                f'({seller_ethnicity})</span>'
            )
        if seller_rating:
            try:
                rating_num = float(seller_rating.split("/")[0])
                color = "#c0392b" if rating_num < 4.0 else "#333"
                seller_parts.append(
                    f'<span style="color: {color}; font-weight: bold;">'
                    f'{seller_rating}</span>'
                )
            except (ValueError, IndexError):
                seller_parts.append(seller_rating)
        if seller_joined:
            seller_parts.append(f"joined {seller_joined}")
        if seller_listings:
            seller_parts.append(f"{seller_listings} listings")
        seller_row = (
            f'<tr><td style="padding: 2px 12px 2px 0; font-weight: bold;">'
            f'Seller</td><td>{" — ".join(seller_parts)}</td></tr>'
        )
        # Add reasoning row below seller if available
        if seller_ethnicity_reasoning:
            seller_row += (
                f'<tr><td></td><td style="color: #999; font-size: 12px; '
                f'font-style: italic; padding: 0 0 4px 0;">'
                f'{seller_ethnicity_reasoning}</td></tr>'
            )

    condition_row = ""
    if condition_listed:
        condition_row = (
            f'<tr><td style="padding: 2px 12px 2px 0; font-weight: bold;">'
            f'Condition</td><td>{condition_listed}</td></tr>'
        )

    listing_age_row = ""
    if listing_age_text:
        age_display = listing_age_text
        if listing_age_days is not None:
            age_display = f"{listing_age_text} (~{listing_age_days} days)"
        age_color = "#c0392b" if (listing_age_days and listing_age_days > 30) else "#333"
        listing_age_row = (
            f'<tr><td style="padding: 2px 12px 2px 0; font-weight: bold;">'
            f'Listed</td><td><span style="color: {age_color};">'
            f'{age_display}</span></td></tr>'
        )

    type_row = (
        f'<tr><td style="padding: 2px 12px 2px 0; font-weight: bold;">'
        f'Type</td><td>{item_type.title()}</td></tr>'
    )

    header_html = f"""\
<h1 style="color: #008080; margin-bottom: 4px;">{item_name}</h1>
<table style="font-size: 15px; color: #333; border-collapse: collapse; margin-bottom: 16px;">
{type_row}
<tr><td style="padding: 2px 12px 2px 0; font-weight: bold;">Listed Price</td><td>${listed_price}</td></tr>
<tr><td style="padding: 2px 12px 2px 0; font-weight: bold;">Location</td><td>{location}</td></tr>
{condition_row}
{seller_row}
{listing_age_row}
<tr><td style="padding: 2px 12px 2px 0; font-weight: bold;">Listing</td><td><a href="{listing_url}" style="color: #008080;">View on Facebook</a></td></tr>
</table>"""

    # Price assessment
    assessment_html = markdown.markdown(
        price_assessment, extensions=["tables", "fenced_code"]
    )
    assessment_section = f"""\
<hr style="border: 1px solid #ddd;">
<h2 style="color: #008080;">Price Assessment</h2>
{assessment_html}"""

    # Seller Profile section (NEW — from seller investigation node)
    seller_investigation = state.get("seller_investigation", "")
    seller_risk_level = state.get("seller_risk_level", "")
    seller_profile_html = ""
    if seller_investigation:
        risk_colors = {"LOW": "#27ae60", "MEDIUM": "#f39c12", "HIGH": "#c0392b"}
        risk_color = risk_colors.get(seller_risk_level, "#333")

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

        seller_profile_html = f"""\
<hr style="border: 1px solid #ddd;">
<h2 style="color: #008080;">
  Seller Profile
  <span style="color: {risk_color}; font-size: 16px; margin-left: 8px;">
    [{seller_risk_level} RISK]
  </span>
</h2>
{seller_rendered}
{listings_html}"""

    # Seller Bio & Background — collapsible section from profile data + LinkedIn
    seller_profile = state.get("seller_profile", {}) or {}
    seller_bio_parts = []
    bio_text = seller_profile.get("bio", "")
    if bio_text:
        bio_escaped = (
            bio_text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace("\n", "<br>")
        )
        seller_bio_parts.append(
            f'<p style="font-size: 14px;"><strong>Bio:</strong> {bio_escaped}</p>'
        )
    biz_name = seller_profile.get("business_name", "")
    biz_info = seller_profile.get("business_info", "")
    if biz_name:
        seller_bio_parts.append(
            f'<p style="font-size: 14px;"><strong>Business:</strong> {biz_name}'
            + (f" — {biz_info}" if biz_info else "")
            + "</p>"
        )
    prof_bg = _extract_section(seller_investigation, "Professional Background")
    if prof_bg and prof_bg.lower() != "no professional profile found.":
        prof_rendered = markdown.markdown(prof_bg, extensions=["tables"])
        seller_bio_parts.append(
            f'<div style="font-size: 14px;"><strong>Professional Background:</strong>'
            f'{prof_rendered}</div>'
        )
    seller_bio_html = ""
    if seller_bio_parts:
        inner = "\n".join(seller_bio_parts)
        seller_bio_html = (
            '<hr style="border: 1px solid #ddd;">'
            + _collapsible_html("Seller Bio &amp; Background", inner)
        )

    # Flip risk section
    flip_risk_level = state.get("flip_risk_level", "NONE")
    flip_risk_summary = state.get("flip_risk_summary", "")
    flip_html = ""
    if flip_risk_level and flip_risk_level != "NONE":
        color_map = {"LOW": "#f39c12", "MEDIUM": "#e67e22", "HIGH": "#c0392b"}
        badge_color = color_map.get(flip_risk_level, "#333")
        flip_rendered = markdown.markdown(
            flip_risk_summary, extensions=["tables", "fenced_code"]
        )
        flip_html = f"""\
<hr style="border: 1px solid #ddd;">
<h2 style="color: #008080;">
  Flip Risk: <span style="color: {badge_color}; font-weight: bold;">{flip_risk_level}</span>
</h2>
{flip_rendered}"""

    # Safety recalls section
    safety_info = state.get("safety_info", "")
    safety_html = ""
    if safety_info:
        safety_rendered = markdown.markdown(
            safety_info, extensions=["tables", "fenced_code"]
        )
        safety_html = f"""\
<hr style="border: 1px solid #ddd;">
<h2 style="color: #c0392b;">Safety Recalls</h2>
{safety_rendered}"""

    # Photos — limit to first 3 for brevity
    max_photos = 3
    photos_html = ""
    email_image_paths = image_paths[:max_photos]
    if email_image_paths:
        photos_html = '\n<hr style="border: 1px solid #ddd;">\n'
        photos_html += '<h2 style="color: #008080;">Listing Photos</h2>\n'
        for i, img_path in enumerate(email_image_paths):
            cid = f"listing_photo_{i}"
            caption = ""
            if i < len(image_analyses):
                caption = _shorten_analysis(image_analyses[i], max_sentences=1)
            photos_html += (
                f'<div style="margin-bottom: 24px;">'
                f'<h3 style="color: #444; margin-bottom: 6px;">Photo {i + 1}</h3>'
                f'<img src="cid:{cid}" style="max-width: 100%; '
                f'height: auto; border-radius: 6px;" alt="Photo {i + 1}">'
            )
            if caption:
                photos_html += (
                    f'<p style="color: #555; font-size: 14px; '
                    f'margin: 8px 0 0 0; line-height: 1.4;">{caption}</p>'
                )
            photos_html += '</div>\n'
        if len(image_paths) > max_photos:
            photos_html += (
                f'<p style="color: #888; font-size: 13px;">'
                f'{len(image_paths) - max_photos} more photo(s) in listing</p>\n'
            )

    # Condensed collapsible sections — condition, research, description
    # Condense once and reuse for both HTML and plain text to avoid
    # duplicate Haiku calls.
    condensed_condition = ""
    condition_html = ""
    if condition_report:
        condensed_condition = _condense_section(condition_report, "condition report")
        print(f"  Condition (condensed): {condensed_condition[:120]}...")
        rendered = markdown.markdown(condensed_condition, extensions=["tables"])
        condition_html = (
            '<hr style="border: 1px solid #ddd;">'
            + _collapsible_html("Condition Summary", rendered)
        )

    description_research = state.get("description_research", "")
    condensed_research = ""
    research_html = ""
    if description_research:
        condensed_research = _condense_section(description_research, "research findings")
        print(f"  Research (condensed): {condensed_research[:120]}...")
        rendered = markdown.markdown(condensed_research, extensions=["tables"])
        research_html = (
            '<hr style="border: 1px solid #ddd;">'
            + _collapsible_html("Research Findings", rendered)
        )

    description_html = ""
    if description:
        desc_escaped = (
            description.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace("\n", "<br>")
        )
        description_html = (
            '<hr style="border: 1px solid #ddd;">'
            + _collapsible_html(
                "Seller's Description",
                f'<p style="font-size: 14px;">{desc_escaped}</p>'
            )
        )

    html_body = f"""\
<html><body style="font-family: -apple-system, BlinkMacSystemFont, sans-serif; \
max-width: 700px; margin: 0 auto; padding: 16px; color: #222;">
{header_html}
{assessment_section}
{seller_profile_html}
{seller_bio_html}
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

    # Plain text seller bio
    bio_plain_parts = []
    if bio_text:
        bio_plain_parts.append(f"Bio: {bio_text}")
    if biz_name:
        bio_plain_parts.append(f"Business: {biz_name}" + (f" — {biz_info}" if biz_info else ""))
    if prof_bg and prof_bg.lower() != "no professional profile found.":
        bio_plain_parts.append(f"Professional Background:\n{prof_bg}")
    if bio_plain_parts:
        plain_body += "--- SELLER BIO & BACKGROUND ---\n\n" + "\n\n".join(bio_plain_parts) + "\n\n"

    if flip_risk_level and flip_risk_level != "NONE":
        plain_body += f"--- FLIP RISK: {flip_risk_level} ---\n\n{flip_risk_summary}\n\n"

    if safety_info:
        plain_body += f"--- SAFETY RECALLS ---\n\n{safety_info}\n\n"

    if email_image_paths:
        plain_body += "--- LISTING PHOTOS ---\n\n"
        for i in range(len(email_image_paths)):
            caption = ""
            if i < len(image_analyses):
                caption = _shorten_analysis(image_analyses[i], max_sentences=1)
            plain_body += f"Photo {i + 1}: {caption}\n\n"
        if len(image_paths) > max_photos:
            plain_body += f"({len(image_paths) - max_photos} more photo(s) in listing)\n\n"

    if condensed_condition:
        plain_body += f"--- CONDITION SUMMARY ---\n\n{condensed_condition}\n\n"

    if condensed_research:
        plain_body += f"--- RESEARCH FINDINGS ---\n\n{condensed_research}\n\n"

    if description:
        plain_body += f"--- SELLER'S DESCRIPTION ---\n\n{description}\n\n"

    print(f"  Sending to {email_to}...")

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
            img_data = img_path.read_bytes()
            suffix = img_path.suffix.lower().lstrip(".")
            subtype = "jpeg" if suffix in ("jpg", "jpeg") else suffix
            img_part = MIMEImage(img_data, _subtype=subtype)
            img_part.add_header("Content-ID", f"<{cid}>")
            img_part.add_header("Content-Disposition", "inline", filename=img_path.name)
            msg.attach(img_part)
        if email_image_paths:
            print(f"  Embedded {len(email_image_paths)} of {len(image_paths)} photo(s)")

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_user, gmail_app_password)
            server.sendmail(gmail_user, email_to, msg.as_string())

        print("  Email sent successfully.")
        return {"email_sent": True, "email_summary": subject}

    except Exception as e:
        print(f"  Error sending email: {e}")
        return {"email_sent": False, "email_summary": subject}
