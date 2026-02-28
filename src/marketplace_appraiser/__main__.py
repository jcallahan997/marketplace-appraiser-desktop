"""CLI entry point for the agentic marketplace appraiser.

Usage:
    python -m marketplace_appraiser <facebook_marketplace_url> [--item-type TYPE] [--email [recipient]]
"""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


def main():
    load_dotenv()

    from marketplace_appraiser.item_types import ITEM_TYPE_REGISTRY

    available_types = sorted(ITEM_TYPE_REGISTRY.keys())

    parser = argparse.ArgumentParser(
        description="Appraise a Facebook Marketplace listing.",
        usage="python -m marketplace_appraiser <url> [--item-type TYPE] [--email [recipient]]",
    )
    parser.add_argument("url", help="Facebook Marketplace listing URL")
    parser.add_argument(
        "--item-type",
        choices=available_types,
        default=None,
        metavar="TYPE",
        help=f"Item type ({', '.join(available_types)}). Auto-detected if omitted.",
    )
    parser.add_argument(
        "--email",
        nargs="?",
        const="",
        default=None,
        metavar="RECIPIENT",
        help="Email the report. Uses RECIPIENT, or EMAIL_TO env var, or GMAIL_USER.",
    )

    if len(sys.argv) < 2:
        parser.print_help()
        print()
        print("Prerequisites:")
        print("  1. Launch Chrome with remote debugging:")
        print("     ./scripts/launch_chrome.sh")
        print("  2. Log into Facebook in that Chrome window")
        print("  3. Make sure Ollama is running (if using local models): ollama serve")
        print()
        print(f"Supported item types: {', '.join(available_types)}")
        sys.exit(1)

    args = parser.parse_args()
    url = args.url

    if "facebook.com" not in url:
        print(f"WARNING: URL does not look like a Facebook Marketplace listing:")
        print(f"  {url}")
        print("Expected format: https://www.facebook.com/marketplace/item/<id>/")
        resp = input("Continue anyway? (y/N): ")
        if resp.lower() != "y":
            sys.exit(0)

    # Ensure output directory exists
    Path("output/images").mkdir(parents=True, exist_ok=True)

    # Detect actual models
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    vision_model = os.getenv("VISION_MODEL", "")
    text_model = os.getenv("TEXT_MODEL", "")

    if not vision_model:
        vision_model = "claude-sonnet-4-20250514" if anthropic_key else "llava:latest"
    if not text_model:
        text_model = "claude-sonnet-4-20250514" if anthropic_key else "qwen3:8b"

    cdp_url = os.getenv("CHROME_CDP_URL", "http://localhost:9222")

    send_email = args.email is not None
    email_to = ""
    if send_email:
        email_to = args.email or os.getenv("EMAIL_TO", "") or os.getenv("GMAIL_USER", "")

    item_type_display = args.item_type or "auto-detect"

    print()
    print("=" * 60)
    print("  AGENTIC MARKETPLACE APPRAISER")
    print("=" * 60)
    print(f"  Listing URL:   {url}")
    print(f"  Item Type:     {item_type_display}")
    print(f"  Vision Model:  {vision_model}")
    print(f"  Text Model:    {text_model}")
    print(f"  Chrome CDP:    {cdp_url}")
    if send_email:
        print(f"  Email To:      {email_to or '(will use GMAIL_USER)'}")
    print("=" * 60)

    from marketplace_appraiser.graph import build_graph

    app = build_graph(send_email=send_email)
    initial_state = {"listing_url": url}
    if args.item_type:
        initial_state["item_type"] = args.item_type
    if email_to:
        initial_state["email_to"] = email_to

    result = app.invoke(initial_state)

    print()
    print("=" * 60)
    print("  APPRAISAL COMPLETE")
    print("=" * 60)
    print()
    print(result["price_assessment"])
    if send_email and result.get("email_sent"):
        print(f"\nEmail sent to: {email_to}")
    elif send_email:
        print("\nEmail was not sent — check credentials and config above.")


if __name__ == "__main__":
    main()
