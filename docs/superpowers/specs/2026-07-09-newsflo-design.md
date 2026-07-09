# NewsFlo — News-Driven Stock Impact Dashboard

## Purpose

Continuously ingest financial news, determine which companies are affected — directly named or indirectly via sector/event reasoning (e.g. a strike on Iran → oil companies) — and surface a live, ranked view of impact with trading-style signals (direction + magnitude estimate), backed by a growing historical-outcomes database that calibrates predictions over time.

## Scope (v1)

- Market focus: **Indian stocks primarily** (NSE/BSE, Nifty 50/100/500), global markets as a later phase.
- News sources: **free APIs/RSS** (NewsAPI, GDELT, Indian financial RSS feeds — Economic Times, Moneycontrol, Business Standard).
- Multi-user product with auth; each user has their own demat holdings and receives their own alerts.
- Dashboard is the primary surface; email alerts for holdings-affecting news are also in v1 (push notification is a fast-follow).

## Architecture

Modular monolith — single deployable service with clean internal module boundaries, so any module (e.g. ingestion, or analysis) can be split into its own service later without a rewrite.

**Modules:**

1. **Ingestion** — polls news sources every 1-2 min, dedupes (Redis hash check), stores raw articles.
2. **Filter** — cheap keyword/category heuristic drops obviously irrelevant articles before they cost an LLM call.
3. **Analysis** — one Claude API call per surviving article, structured output: category, direct company mentions, sector/event reasoning, direction (bullish/bearish), magnitude range, rationale text.
4. **Company Resolution** — expands sector-level reasoning into concrete companies via the company master table (sector, market cap, index membership); direct mentions pass through as-is.
5. **Calibration** — maintains a historical outcomes database of (news category, company) → actual subsequent price move. Blends empirical stats into the magnitude estimate once a (category, company) pair has enough samples (threshold, e.g. 5); otherwise the LLM's estimate stands, flagged `low_confidence`.
6. **Holdings** — per-user demat holdings, populated via manual entry/CSV upload (v1 default) or broker API (Zerodha Kite Connect first integration).
7. **Alerting** — matches newly resolved affected-companies against each user's holdings; queues an email alert on match.
8. **Outcome Tracker** — scheduled job; for alerts past fixed horizons (1d/3d/7d), fetches actual price move (yfinance) and writes a new sample into the calibration database. This is what makes the system improve over time — it starts with LLM-only estimates and gradually earns empirical confidence.
9. **API + WebSocket layer** — serves the dashboard, pushes new alerts to connected clients live.
10. **Frontend** — the dashboard (see UI section).

## Data Flow (single article)

1. Poller fetches → dedup check → store raw (`status: new`).
2. Heuristic filter → non-matches marked `filtered`, pipeline stops.
3. Claude call → structured result attached to article.
4. Company resolution → concrete company list, each tagged with its index membership (Nifty 50 / 100 / 500 / other).
5. Calibration check per (category, company) → magnitude estimate finalized, confidence flagged.
6. Result stored as an `alert`, pushed via WebSocket.
7. Holdings match per user → email queued if overlap.
8. (Async, later) Outcome tracker revisits the alert at 1d/3d/7d, records actual move.

## Tech Stack

- **Backend**: Python + FastAPI (async, suits polling + WebSocket + LLM calls).
- **Database**: PostgreSQL — articles, companies, users, holdings, alerts, calibration/outcome samples.
- **Scheduler**: APScheduler in-process for v1; Celery + Redis if polling/analysis volume outgrows a single process.
- **Cache/pubsub**: Redis — article dedup, WebSocket fan-out.
- **Price data**: yfinance (`.NS` / `.BO` suffixes for NSE/BSE; global tickers supported for phase 2).
- **Company master data**: NSE official index constituent CSVs (niftyindices.com), refreshed periodically (e.g. weekly job), storing sector + index membership per company.
- **LLM**: Claude API (Anthropic) for category classification, entity extraction, and sector-impact reasoning.
- **Auth**: email/password or OAuth, JWT sessions, multi-tenant from day one.
- **Email**: transactional provider (e.g. Resend/SendGrid free tier) for holdings alerts.
- **Frontend**: React + Vite + Tailwind.
- **Hosting**: single container/VPS (Railway/Render) running FastAPI + Postgres + Redis + built frontend, to start.

## Error Handling

- Claude call failure/timeout → retry once, then mark article `analysis_failed` (visible in an internal ops view, never silently dropped).
- Outcome-tracker price fetch failure → retry on the next scheduled run; failure on one ticker never blocks others in the same batch.
- Broker API integration (phase 2 of Holdings) must degrade gracefully to manual/CSV entry if the broker connection fails — manual entry is always available as a fallback path, not replaced by the API integration.

## Testing

- Unit tests per module: filter heuristic, company-resolution mapping, calibration blending math.
- Integration test: one article through the full pipeline with a mocked Claude response (no live news/price API calls in CI).
- Outcome tracker tested against a mocked price series, not live yfinance calls.

## UI / UX Design

Visual direction: CRED-inspired — true black page background, cards as a distinct dark-gray surface (not pure black, so they visually separate from the page and each other), bold serif display font (Georgia/serif stack) for news headlines, small tracked-uppercase sans-serif for metadata/tabs/buttons, color used sparingly (a small swatch dot per category, outlined pills for sentiment) rather than heavy gradients or emoji.

**Feed structure** (validated via mockup iteration, final approved version "v9"):

- Live-updating vertical feed, one card per news story.
- Each card: category swatch + label, timestamp, bold serif headline.
- Two tabs per card: **Predicted** (LLM-determined affected companies) and **My Demat** (subset that overlaps the logged-in user's holdings).
- Under the active tab, affected companies are grouped by index tier — **Nifty 50 / Nifty 100 / Nifty 500 / Other** — each shown as a chip with company name and magnitude estimate (colored +/− percentage range).
- A "Net Bullish/Bearish" outlined pill per card gives the at-a-glance overall read.
- Clicking a company chip expands a reasoning panel: which company, why it's affected, and the historical-precedent line (e.g. "6 similar past events averaged +3.1% over 3 days") — sourced from the calibration database once enough samples exist, otherwise from the LLM's own rationale.
- Cards collapse to just headline + tabs + net sentiment by default; expand to full chip/reasoning detail on click.

## Out of Scope (v1)

- Global market coverage (Indian markets only for v1).
- Paid news data sources.
- Push notifications (email only; push is a fast-follow).
- Automated trading / order execution — this system produces signals and reasoning only, it does not place trades.
