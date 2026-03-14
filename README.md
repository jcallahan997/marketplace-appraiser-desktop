# Marketplace Appraiser

A command-line tool that appraises Facebook Marketplace listings using an agentic AI pipeline. It scrapes listing data, analyzes photos, researches comparable market prices, investigates the seller, and produces a detailed appraisal report -- all from a single URL.

Built with [LangGraph](https://github.com/langchain-ai/langgraph) for pipeline orchestration, [Anthropic Claude](https://www.anthropic.com/) for LLM-powered analysis (with Ollama fallback for local inference), and [Playwright](https://playwright.dev/) for browser-based scraping.

## Features

- **Automated scraping** of Facebook Marketplace listings via Chrome DevTools Protocol (CDP)
- **AI vision analysis** of listing photos to assess condition, spot damage, and detect flip signals
- **Market research** using Tavily web search (with DuckDuckGo fallback) for comparable pricing
- **Seller investigation** to evaluate seller history and trustworthiness
- **Price assessment** that synthesizes all findings into a buy/pass recommendation
- **Email reports** -- optional HTML report delivered via Gmail SMTP
- **Auto-detection** of item category (vehicles, electronics, furniture, general)
- **Dual LLM support** -- Claude API (recommended) or Ollama local models (qwen3:8b)

## Prerequisites

- Python 3.11+
- Google Chrome installed
- An Anthropic API key (or [Ollama](https://ollama.com/) running locally with `qwen3:8b` and `llava` pulled)
- A [Tavily](https://tavily.com/) API key for web search (optional, falls back to DuckDuckGo)

## Installation

```bash
git clone https://github.com/jcallahan997/agentic-marketplace-appraiser.git
cd agentic-marketplace-appraiser

python3.11 -m venv .venv
source .venv/bin/activate

pip install -e .
playwright install chromium
```

Copy the environment template and fill in your keys:

```bash
cp .env.template .env
```

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes* | Anthropic API key for Claude. If unset, falls back to Ollama. |
| `TAVILY_API_KEY` | No | Tavily API key for web search. Falls back to DuckDuckGo if unset. |
| `CHROME_CDP_URL` | No | Chrome CDP endpoint. Default: `http://localhost:9222` |
| `TEXT_MODEL` | No | Override the text LLM. Default: `claude-sonnet-4-20250514` (or `qwen3:8b` with Ollama) |
| `VISION_MODEL` | No | Override the vision LLM. Default: `claude-sonnet-4-20250514` (or `llava:latest` with Ollama) |
| `GMAIL_USER` | No | Gmail address for sending email reports |
| `GMAIL_APP_PASSWORD` | No | Gmail app password (not your regular password) |
| `EMAIL_TO` | No | Default recipient for email reports |
| `SCRAPER_DEBUG_SCREENSHOTS` | No | Set to `true` to save debug screenshots during scraping |

*Required unless using Ollama as the LLM backend.

## Usage

### 1. Launch Chrome with remote debugging

```bash
./scripts/launch_chrome.sh
```

This opens Chrome on port 9222 with a dedicated profile. Log into Facebook in the browser window that opens.

### 2. Run the appraiser

```bash
# Basic appraisal (terminal output only)
python -m marketplace_appraiser "https://www.facebook.com/marketplace/item/123456789/"

# With email report
python -m marketplace_appraiser "https://www.facebook.com/marketplace/item/123456789/" --email

# Email to a specific recipient
python -m marketplace_appraiser "https://www.facebook.com/marketplace/item/123456789/" --email recipient@example.com
```

The tool auto-detects the item type (vehicle, electronics, furniture, or general) from the listing content and adjusts its analysis accordingly.

## Architecture

The pipeline is a linear LangGraph `StateGraph` with 7 nodes. Each node reads from and writes to a shared `AppraisalState`.

```
scrape_listing -> analyze_images -> assess_condition -> research_market -> investigate_seller -> assess_price -> [email_report]
```

| Step | Node | Description |
|---|---|---|
| 1 | `scrape_listing` | Connects to Chrome via CDP, navigates to the listing, extracts title, price, description, seller info, and downloads photos |
| 2 | `analyze_images` | Sends listing photos to a vision model for detailed analysis of condition, features, and flip signals |
| 3 | `assess_condition` | Synthesizes image analyses and listing description into a structured condition report |
| 4 | `research_market` | Searches the web for comparable listings and recent sale prices |
| 5 | `investigate_seller` | Researches the seller's profile, listing history, and reputation |
| 6 | `assess_price` | Combines all prior findings into a final price assessment with buy/pass recommendation |
| 7 | `email_report` | (Optional) Builds an HTML report and sends it via Gmail SMTP |

### Project Structure

```
src/marketplace_appraiser/
    __main__.py          CLI entry point
    graph.py             LangGraph pipeline assembly
    state.py             AppraisalState TypedDict
    nodes/
        scraper.py       Step 1: Scrape listing via Playwright/CDP
        vision.py        Step 2: Analyze images with Claude vision
        condition.py     Step 3: Assess item condition
        market.py        Step 4: Research market via Tavily
        seller.py        Step 5: Investigate seller profile
        price.py         Step 6: Assess fair price
        email_report.py  Step 7: Build and send email report
    item_types/
        _base.py         Item-specific configs (prompts, search templates, fraud patterns)
    utils/
        image_utils.py   Image download and encoding helpers
        parsing.py       Price and listing age parsers
scripts/
    launch_chrome.sh     Helper to start Chrome with CDP enabled
tests/
    test_graph.py        Graph construction tests
    test_parsing.py      Parsing utility tests
```

## Testing

```bash
# Run unit tests
pytest tests/ -x -q

# Skip integration tests (which require Chrome, Ollama, or Facebook)
pytest tests/ -x -q -m "not integration"
```

## License

MIT
