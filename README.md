# Marketplace Appraiser

**An agentic AI pipeline that appraises Facebook Marketplace listings end-to-end — from a single URL to a detailed buy/pass recommendation. Packaged as an Electron desktop app with a split-pane UI: browse Facebook Marketplace on the left, see real-time appraisal progress on the right.**

[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![LangGraph](https://img.shields.io/badge/LangGraph-Pipeline-1C3C3C?logo=langchain&logoColor=white)](https://github.com/langchain-ai/langgraph)
[![Anthropic Claude](https://img.shields.io/badge/Claude-Vision+Text-D4A574?logo=anthropic&logoColor=white)](https://www.anthropic.com/)
[![React 19](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)](https://react.dev/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Server-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)
[![Playwright](https://img.shields.io/badge/Playwright-Scraping-2EAD33?logo=playwright&logoColor=white)](https://playwright.dev/)
[![Langfuse](https://img.shields.io/badge/Langfuse-Observability-000000)](https://langfuse.com/)
[![Electron](https://img.shields.io/badge/Electron-Desktop-47848F?logo=electron&logoColor=white)](https://www.electronjs.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

<!-- TODO: Add a screenshot of the dashboard or email report here -->
<!-- ![Dashboard Screenshot](docs/screenshot.png) -->

## Background

This project started as a **vehicle-specific appraiser** built to evaluate used cars on Facebook Marketplace. It has since been generalized into a config-driven system that supports any item category — vehicles, electronics, furniture, and a general catch-all — each with its own prompts, search templates, fraud patterns, and safety API integrations.

## What It Does

Given a Facebook Marketplace listing URL, the appraiser autonomously:

1. **Scrapes** the listing (photos, price, description, seller info) via Chrome CDP
2. **Analyzes photos** with AI vision to assess condition and detect reseller/flip signals
3. **Researches the market** for comparable pricing using web search
4. **Investigates the seller** — profile age, listing history, reputation
5. **Produces a final appraisal** with a **BUY / NEGOTIATE / PASS** recommendation
6. **Sends an HTML email report** (optional) with all findings

The **Electron desktop app** presents a split-pane window: Facebook Marketplace on the left, the appraisal dashboard on the right. When you navigate to a listing, the app auto-detects the URL and fills it into the dashboard — no copy/paste needed. It also works as a standalone CLI or web dashboard.

It auto-detects the item category (vehicles, electronics, furniture, or general) and adjusts prompts, search queries, fraud patterns, and safety checks accordingly.

## Key Features

- **7-node agentic pipeline** orchestrated by LangGraph with shared state
- **AI vision analysis** — condition assessment, damage detection, reseller/flip signal identification
- **Market research** via Tavily web search (DuckDuckGo fallback) for comparable pricing
- **Seller investigation** — profile scraping, reputation research, risk scoring
- **Safety checks** — NHTSA vehicle recalls, CPSC consumer product alerts
- **Dual LLM support** — Claude API (recommended) or Ollama for fully local inference
- **Electron desktop app** — split-pane UI with Facebook Marketplace browser + live dashboard, auto-detects listing URLs
- **Real-time dashboard** — React + WebSocket UI with live pipeline progress (also runs standalone in browser)
- **LLM observability** — Langfuse integration for token usage, latency, and cost tracking
- **Email reports** — styled HTML summaries delivered via Gmail SMTP
- **Docker deployment** — multi-stage build with headless Chrome, Langfuse, and Postgres

## Architecture

The pipeline is a linear [LangGraph](https://github.com/langchain-ai/langgraph) `StateGraph`. Each node reads from and writes to a shared `AppraisalState`, and the dashboard streams progress in real time via WebSocket.

```
┌─────────────┐    ┌────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Scrape     │───▶│ Analyze Images │───▶│ Assess Condition │───▶│ Research Market  │
│   Listing    │    │   (Vision AI)  │    │                  │    │  (Web Search)    │
└─────────────┘    └────────────────┘    └──────────────────┘    └─────────────────┘
                                                                          │
┌─────────────┐    ┌────────────────┐    ┌──────────────────┐            │
│ Email Report │◀──│  Assess Price  │◀──│   Investigate    │◀───────────┘
│  (Optional)  │    │  (BUY/PASS)   │    │     Seller      │
└─────────────┘    └────────────────┘    └──────────────────┘
```

| Step | Node | What It Does |
|------|------|-------------|
| 1 | `scrape_listing` | Connects to Chrome via CDP, extracts listing data, downloads photos |
| 2 | `analyze_images` | Sends photos to a vision model for condition and flip signal analysis |
| 3 | `assess_condition` | Synthesizes image analyses + description into a structured condition report |
| 4 | `research_market` | Searches the web for comparable listings and recent sale prices |
| 5 | `investigate_seller` | Researches seller profile, listing history, and reputation |
| 6 | `assess_price` | Combines all findings into a final recommendation with fair value estimate |
| 7 | `email_report` | Builds a styled HTML report and optionally sends it via Gmail |

## Tech Stack

| Layer | Technology | Role |
|-------|-----------|------|
| **Orchestration** | LangGraph | Pipeline state machine with typed state |
| **LLM (Cloud)** | Anthropic Claude (Sonnet, Haiku, Opus) | Vision analysis, condition assessment, price synthesis |
| **LLM (Local)** | Ollama (qwen3:8b, llava) | Free local alternative for all LLM calls |
| **Web Search** | Tavily / DuckDuckGo | Market comps, seller research, safety recalls |
| **Scraping** | Playwright + Chrome CDP | Browser-based Facebook Marketplace extraction |
| **Backend** | FastAPI + Uvicorn | REST API + WebSocket server for dashboard |
| **Desktop App** | Electron | Split-pane UI: Marketplace browser + dashboard |
| **Frontend** | React 19, TypeScript, Tailwind CSS, Vite | Real-time dashboard with pipeline progress |
| **Observability** | Langfuse | Token/cost tracking, latency traces, LLM analytics |
| **Safety APIs** | NHTSA, CPSC | Vehicle recall checks, consumer product alerts |
| **Infrastructure** | Docker Compose | Multi-service deployment (app, Chrome, Langfuse, Postgres) |

## Project Structure

```
src/marketplace_appraiser/
├── __main__.py              # CLI entry point
├── graph.py                 # LangGraph pipeline assembly
├── state.py                 # AppraisalState TypedDict
├── server.py                # FastAPI + WebSocket server
├── history.py               # Run history persistence
├── feedback.py              # User feedback collection
├── nodes/
│   ├── scraper.py           # Step 1: Scrape listing via CDP
│   ├── vision.py            # Step 2: Vision analysis
│   ├── condition.py         # Step 3: Condition assessment
│   ├── market.py            # Step 4: Market research
│   ├── seller.py            # Step 5: Seller investigation
│   ├── price.py             # Step 6: Price assessment
│   └── email_report.py      # Step 7: HTML email report
├── item_types/
│   ├── _base.py             # ItemTypeConfig (prompts, patterns, search templates)
│   ├── vehicle.py           # Vehicle-specific config
│   ├── electronics.py       # Electronics config
│   ├── furniture.py         # Furniture config
│   └── general.py           # General catch-all config
└── utils/
    ├── llm.py               # LLM provider abstraction (Claude / Ollama)
    ├── search.py             # Web search (Tavily / DuckDuckGo)
    ├── langfuse_ctx.py       # Observability context + cost tracking
    ├── image_utils.py        # Image download and encoding
    ├── parsing.py            # Price and listing age parsers
    ├── research.py           # Seller research helpers
    └── safety_apis.py        # NHTSA / CPSC safety checks

dashboard/                    # React + Vite frontend
├── src/
│   ├── App.tsx               # Main app shell
│   ├── components/           # Controls, PipelineProgress, ConsoleOutput, etc.
│   └── hooks/                # useAppraisal, useWebSocket
├── package.json
└── vite.config.ts

electron/                     # Electron desktop app
├── main.js                   # Main process: split-pane window, CDP, FastAPI child process
├── preload.js                # Bridge: auto-fills listing URL into dashboard
├── package.json
└── scripts/make-icon.py      # Icon generation script

scripts/
├── launch_chrome.sh          # Start Chrome with CDP on port 9222
├── evaluate.py               # Eval framework for pipeline quality
└── test_listings.txt         # Test listing URLs

tests/
├── test_graph.py             # Graph construction tests
├── test_parsing.py           # Parsing utility tests
└── test_item_types.py        # Item type config tests
```

## Getting Started

### Prerequisites

- Python 3.11+
- Google Chrome installed
- An [Anthropic API key](https://console.anthropic.com/) (or [Ollama](https://ollama.com/) running locally with `qwen3:8b` and `llava`)
- A [Tavily API key](https://tavily.com/) for web search (optional — falls back to DuckDuckGo)

### Installation

```bash
git clone https://github.com/jcallahan997/marketplace-appraiser-desktop.git
cd marketplace-appraiser-desktop

python3.11 -m venv .venv
source .venv/bin/activate

pip install -e .
playwright install chromium
```

Copy the environment template and fill in your keys:

```bash
cp .env.template .env
# Edit .env with your API keys
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes* | Anthropic API key for Claude. Falls back to Ollama if unset. |
| `TAVILY_API_KEY` | No | Tavily API key for web search. Falls back to DuckDuckGo. |
| `CHROME_CDP_URL` | No | Chrome CDP endpoint. Default: `http://localhost:9222` |
| `TEXT_MODEL` | No | Override text LLM. Default: `claude-sonnet-4-20250514` |
| `VISION_MODEL` | No | Override vision LLM. Default: `claude-sonnet-4-20250514` |
| `GMAIL_USER` | No | Gmail address for sending email reports |
| `GMAIL_APP_PASSWORD` | No | Gmail [app password](https://support.google.com/accounts/answer/185833) (not your regular password) |
| `EMAIL_TO` | No | Default recipient for email reports |
| `LANGFUSE_PUBLIC_KEY` | No | Langfuse public key for observability |
| `LANGFUSE_SECRET_KEY` | No | Langfuse secret key |
| `LANGFUSE_HOST` | No | Langfuse server URL |

*Required unless using Ollama as the LLM backend.

### Usage

#### 1. Run the Electron desktop app (recommended)

```bash
# Install Electron dependencies
cd electron && npm install && cd ..

# Start the desktop app (launches FastAPI + dashboard automatically)
cd electron && npm start
```

The app opens a split-pane window: Facebook Marketplace on the left, the appraisal dashboard on the right. Browse to any listing and the URL auto-fills into the dashboard. Click "Start Appraisal" to run the pipeline.

#### 2. Launch Chrome with remote debugging (CLI / standalone dashboard)

```bash
./scripts/launch_chrome.sh
```

This opens Chrome on port 9222 with a dedicated profile. Log into Facebook in the browser window that opens.

#### 3. Run the appraiser (CLI)

```bash
# Basic appraisal
python -m marketplace_appraiser "https://www.facebook.com/marketplace/item/123456789/"

# With email report
python -m marketplace_appraiser "https://www.facebook.com/marketplace/item/123456789/" --email

# Email to a specific recipient
python -m marketplace_appraiser "https://www.facebook.com/marketplace/item/123456789/" --email you@example.com
```

#### 4. Run the dashboard (web UI)

```bash
# Terminal 1: Start the API server
pip install -e ".[server]"
uvicorn marketplace_appraiser.server:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2: Start the React dashboard
cd dashboard && npm install && npm run dev
```

Open `http://localhost:3000` to use the dashboard. It provides real-time pipeline progress, console output streaming, email report preview, and run history.

## Docker

The full stack (app + headless Chrome + Langfuse + Postgres) runs with a single command:

```bash
docker-compose up --build
```

| Service | URL | Description |
|---------|-----|-------------|
| Dashboard + API | `http://localhost:8000` | React UI + FastAPI backend |
| Langfuse | `http://localhost:3002` | LLM observability dashboard |
| Chrome | `localhost:9222` | Headless Chrome for scraping |

> **Note:** The containerized Chrome has no Facebook session. For Facebook Marketplace scraping, run Chrome on your host with `./scripts/launch_chrome.sh` and set `CHROME_CDP_URL=http://host.docker.internal:9222` in your `.env`.

## Cost Optimization

The pipeline is designed to keep API costs low while maintaining quality:

- **Tiered LLM calls** — The pipeline uses three Claude tiers strategically:
  - **Haiku** (`invoke_llm_light`) for cheap classification and extraction tasks (item type detection, field parsing)
  - **Sonnet** (`invoke_llm`) for standard analysis (condition assessment, market research, seller investigation)
  - **Sonnet/Opus** (`invoke_llm_premium`) for the highest-stakes final price assessment
- **Search result caching** — Tavily and DuckDuckGo results are cached in-process by `(query, max_results)`, so identical searches within a single run only hit the API once
- **DuckDuckGo fallback** — If no Tavily API key is set, all web searches use the free DuckDuckGo API at no cost
- **Langfuse cost tracking** — Every LLM call reports token counts and estimated costs to Langfuse, so you can monitor spend per appraisal

A typical appraisal using Claude costs roughly **$0.05–0.15** depending on the number of photos and search queries. Running fully local with Ollama costs nothing.

### Running Fully Local (Free)

To run without any paid APIs, use [Ollama](https://ollama.com/) as the LLM backend:

```bash
# Pull the required models
ollama pull qwen3:8b    # Text model
ollama pull llava       # Vision model

# Run without ANTHROPIC_API_KEY set — the pipeline auto-detects Ollama
unset ANTHROPIC_API_KEY
python -m marketplace_appraiser "https://www.facebook.com/marketplace/item/123456789/"
```

Web search will automatically fall back to DuckDuckGo (free) if `TAVILY_API_KEY` is not set.

## Testing

```bash
# Run unit tests
pytest tests/ -x -q

# Skip integration tests (which require Chrome, Ollama, or Facebook)
pytest tests/ -x -q -m "not integration"
```

## Disclaimer

This project is a **personal portfolio piece and learning exercise**. It is not intended for commercial use. The scraping component accesses Facebook Marketplace via browser automation, which may violate Facebook's Terms of Service. Use at your own risk and only for personal, non-commercial purposes.

## License

[MIT](LICENSE)
