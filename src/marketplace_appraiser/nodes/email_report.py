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
from marketplace_appraiser.utils.llm import invoke_llm


def _shorten_analysis(text: str, max_sentences: int = 2) -> str:
    """Truncate a vision analysis to the first few sentences."""
    if not text:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    short = " ".join(sentences[:max_sentences])
    if len(sentences) > max_sentences:
        short += "..."
    return short


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
    listed_price = state.get("listed_price", "N/A")
    location = state.get("location", "N/A")
    listing_url = state.get("listing_url", "")
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

    subject_raw = invoke_llm(prompt)
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

        seller_rendered = markdown.markdown(
            seller_investigation, extensions=["tables", "fenced_code"]
        )

        # Active listings from profile
        active_listings = state.get("seller_active_listings", [])
        listings_html = ""
        if active_listings:
            listings_items = []
            for lst in active_listings[:10]:
                title = lst.get("title", "Unknown")
                price = lst.get("price", "")
                listings_items.append(f"<li>{title} — {price}</li>")
            listings_html = (
                '<h3 style="color: #666; margin-top: 16px;">Other Active Listings</h3>'
                f'<ul style="font-size: 14px;">{"".join(listings_items)}</ul>'
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

    # Photos
    photos_html = ""
    if image_paths:
        photos_html = '\n<hr style="border: 1px solid #ddd;">\n'
        photos_html += '<h2 style="color: #008080;">Listing Photos</h2>\n'
        for i, img_path in enumerate(image_paths):
            cid = f"listing_photo_{i}"
            caption = ""
            if i < len(image_analyses):
                caption = _shorten_analysis(image_analyses[i])
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

    # Condition summary
    condition_html = ""
    if condition_report:
        rendered = markdown.markdown(
            condition_report, extensions=["tables", "fenced_code"]
        )
        condition_html = f"""\
<hr style="border: 1px solid #ddd;">
<h2 style="color: #008080;">Condition Summary</h2>
{rendered}"""

    # Research findings
    description_research = state.get("description_research", "")
    research_html = ""
    if description_research:
        research_rendered = markdown.markdown(
            description_research, extensions=["tables", "fenced_code"]
        )
        research_html = f"""\
<hr style="border: 1px solid #ddd;">
<h2 style="color: #008080;">Research Findings</h2>
{research_rendered}"""

    # Seller's description
    description_html = ""
    if description:
        desc_escaped = (
            description
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br>")
        )
        description_html = f"""\
<hr style="border: 1px solid #ddd;">
<h2 style="color: #008080;">Seller's Description</h2>
<p style="color: #444; font-size: 14px; line-height: 1.5; white-space: pre-wrap;">{desc_escaped}</p>"""

    html_body = f"""\
<html><body style="font-family: -apple-system, BlinkMacSystemFont, sans-serif; \
max-width: 700px; margin: 0 auto; padding: 16px; color: #222;">
{header_html}
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

    if flip_risk_level and flip_risk_level != "NONE":
        plain_body += f"--- FLIP RISK: {flip_risk_level} ---\n\n{flip_risk_summary}\n\n"

    if safety_info:
        plain_body += f"--- SAFETY RECALLS ---\n\n{safety_info}\n\n"

    plain_body += "--- LISTING PHOTOS ---\n\n"
    for i in range(len(image_paths)):
        caption = ""
        if i < len(image_analyses):
            caption = _shorten_analysis(image_analyses[i])
        plain_body += f"Photo {i + 1}: {caption}\n\n"

    if condition_report:
        plain_body += f"--- CONDITION SUMMARY ---\n\n{condition_report}\n"

    if description_research:
        plain_body += f"\n--- RESEARCH FINDINGS ---\n\n{description_research}\n"

    if description:
        plain_body += f"\n--- SELLER'S DESCRIPTION ---\n\n{description}\n"

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

        for i, img_path in enumerate(image_paths):
            cid = f"listing_photo_{i}"
            img_data = img_path.read_bytes()
            suffix = img_path.suffix.lower().lstrip(".")
            subtype = "jpeg" if suffix in ("jpg", "jpeg") else suffix
            img_part = MIMEImage(img_data, _subtype=subtype)
            img_part.add_header("Content-ID", f"<{cid}>")
            img_part.add_header("Content-Disposition", "inline", filename=img_path.name)
            msg.attach(img_part)
        if image_paths:
            print(f"  Embedded {len(image_paths)} listing photo(s)")

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_user, gmail_app_password)
            server.sendmail(gmail_user, email_to, msg.as_string())

        print("  Email sent successfully.")
        return {"email_sent": True, "email_summary": subject}

    except Exception as e:
        print(f"  Error sending email: {e}")
        return {"email_sent": False, "email_summary": subject}
