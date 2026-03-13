# Marketplace Appraiser Desktop

A macOS desktop application that appraises Facebook Marketplace listings using an AI-powered agentic pipeline. Browse Marketplace in a split-panel Electron window, then run a 7-step LangGraph pipeline that scrapes the listing, analyzes images, researches comparable prices, investigates the seller, and delivers a detailed appraisal report via email.

## Features

- **Split-panel desktop app** -- Facebook Marketplace browser on the left, live dashboard on the right
- **Agentic AI pipeline** -- LangGraph orchestrates 7 autonomous steps from scrape to report
- **Real-time dashboard** -- WebSocket-driven progress tracking, console output, and email preview
- **Computer vision analysis** -- Claude vision describes and assesses item condition from listing photos
- **Market research** -- Tavily web search finds comparable listings and fair market value
- **Seller investigation** -- Evaluates seller profile, ratings, and history
- **Email reports** -- Sends a formatted appraisal with pricing recommendation
- **Run history** -- Review past appraisals from the dashboard
- **CLI mode** -- Run the pipeline from the terminal without the desktop app

## Prerequisites

- **Python** 3.11+
- **Node.js** 20+
- **Playwright** browsers (`playwright install chromium` after pip install)
- API keys (see [Environment Variables](#environment-variables))

## Setup

### Python pipeline

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .
playwright install chromium
```

### Dashboard

```bash
cd dashboard
npm install
npm run build
```

### Electron app

```bash
cd electron
npm install
```

## Usage

### Desktop app (recommended)

```bash
cd electron
npm start
```

This launches the split-panel window, spawns the FastAPI backend, and connects via CDP on port 9223. Navigate to any Marketplace listing in the left panel, then click **Start Appraisal** in the dashboard.

### CLI

Run the pipeline directly against a listing URL:

```bash
python -m marketplace_appraiser "https://www.facebook.com/marketplace/item/123456789"
```

### Build

Package the Electron app as a macOS `.app` bundle:

```bash
cd electron
npm run dist
```

Output is written to `electron/dist/mac-arm64/Marketplace Appraiser.app`.

## Architecture

```
marketplace-appraiser-desktop/
|-- electron/              Electron main process (split-panel shell, CDP, FastAPI spawn)
|   |-- main.js            App window, child process management, divider resize
|   +-- preload.js         Context bridge for renderer
|-- dashboard/             React + TypeScript + Tailwind CSS + Vite
|   +-- src/
|       |-- components/    PipelineProgress, ConsoleOutput, EmailPreview, Controls, StatusBar
|       +-- hooks/         WebSocket and API state hooks
|-- src/marketplace_appraiser/
|   |-- graph.py           LangGraph StateGraph assembly
|   |-- state.py           AppraisalState schema
|   |-- server.py          FastAPI + WebSocket server
|   +-- nodes/
|       |-- scraper.py     Step 1: Scrape listing via Playwright/CDP
|       |-- vision.py      Step 2: Analyze images with Claude vision
|       |-- condition.py   Step 3: Assess item condition
|       |-- market.py      Step 4: Research market via Tavily
|       |-- seller.py      Step 5: Investigate seller profile
|       |-- price.py       Step 6: Assess fair price
|       +-- email_report.py Step 7: Build and send email report
+-- pyproject.toml         Python project config and dependencies
```

### Pipeline flow

```
scrape_listing -> analyze_images -> assess_condition -> research_market
    -> investigate_seller -> assess_price -> email_report -> END
```

## Environment Variables

Create a `.env` file in the project root:

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key for Claude (vision + text) |
| `TAVILY_API_KEY` | No | Tavily API key for web search (falls back to DuckDuckGo) |
| `GMAIL_USER` | No | Gmail address for sending reports |
| `GMAIL_APP_PASSWORD` | No | Gmail app password (not your account password) |
| `EMAIL_TO` | No | Recipient email address for appraisal reports |
| `CHROME_CDP_URL` | No | CDP endpoint (set automatically in Electron mode; default `http://localhost:9223`) |

## License

MIT
