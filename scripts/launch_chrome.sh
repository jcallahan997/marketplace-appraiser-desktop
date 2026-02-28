#!/bin/bash
# Launch Chrome with remote debugging enabled for the marketplace appraiser.
#
# Uses a separate user-data-dir so it doesn't interfere with your
# normal Chrome profile.
#
# Usage: ./scripts/launch_chrome.sh

echo "Launching Chrome with remote debugging on port 9222..."
echo "Log into Facebook in the Chrome window that opens."
echo "Then run the appraiser in another terminal:"
echo ""
echo "  python -m marketplace_appraiser <listing_url>"
echo ""

CHROME_PROFILE="$HOME/Library/Application Support/MarketplaceAppraiser/chrome-profile"
mkdir -p "$CHROME_PROFILE"

/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
    --remote-debugging-port=9222 \
    --user-data-dir="$CHROME_PROFILE" \
    https://www.facebook.com/marketplace 2>/dev/null &

echo "Chrome launched (PID: $!)"
