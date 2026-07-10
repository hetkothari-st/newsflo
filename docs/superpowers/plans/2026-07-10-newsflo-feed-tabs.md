# NewsFlo India / Global / Custom Feed Tabs Implementation Plan (Plan 5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three page-level feed tabs — **India** (Nifty 50/100/500 companies and Indian news), **Global** (a curated static list of ~50 real large-cap global companies spanning the same sector taxonomy), and **Custom** (a per-user, backend-persisted filter over news categories and specific companies) — filtering which alert cards appear in the CRED-style dashboard built in Plan 4.

**Architecture:** The market of a company (`"IN"` vs `"GLOBAL"`) is *derived from the ticker string at read time* (`.NS`/`.BO` ⇒ `IN`, else `GLOBAL`) — no new DB column, no migration. A new curated `GLOBAL_COMPANIES` seed list is loaded into the existing `companies` table with a new `index_tier` label `"GLOBAL_LARGE_CAP"` (which the existing `resolve_companies` tier-ranking `case()` already handles via its `else_=3` fallback — no change to `resolution.py`). The backend exposes the computed `market` per company on `GET /api/alerts` (and the WebSocket broadcast payload), plus three new read endpoints (`GET /api/companies`, `GET /api/categories`) and a per-user watchlist resource (`GET`/`PUT /api/watchlist`) backed by two relational join tables. The frontend adds a page-level `FeedTabs` bar above the existing card list; India/Global filtering is pure client-side logic over the `market` field, and the Custom tab renders an inline `WatchlistSettings` editor plus alerts filtered through the user's saved categories/companies.

**Tech Stack:** Backend — Python 3.11+, FastAPI, SQLAlchemy 2.0, Pydantic v2, `pytest` + `httpx`/`TestClient`. Frontend — React 18, TypeScript 5, Vite 5, Tailwind CSS 3, React Router 6, Vitest 2, React Testing Library, jsdom.

## Global Constraints

These carry forward **verbatim** from Plans 1-4 and remain binding for every task:

- Database schema must stay portable between SQLite (tests) and PostgreSQL (production) — no native Postgres-only column types (no `ENUM`, no `ARRAY`); enums are plain `String` columns validated in Python.
- No live network calls in any test — news fetching, Claude API calls, price lookups (yfinance), and email sending are always mocked/monkeypatched or routed through the console backend. Never any real HTTP call to Resend/SendGrid; the console email backend is what every test exercises by default (no `RESEND_API_KEY` set in the test environment).
- News sources for v1 are free RSS/APIs only (per spec) — no paid data sources.
- Market focus is Indian stocks (NSE/BSE) for v1 — Indian tickers use `.NS` suffix. (Plan 5 adds curated global companies with plain NYSE/NASDAQ symbols alongside the Indian set; the v1 Indian pipeline focus is unchanged.)
- Claude structured output must go through forced tool-use (a `record_analysis` tool), never free-text JSON parsing.
- Company sector values are constrained to a fixed taxonomy (`oil_gas`, `banking`, `auto`, `it`, `pharma`, `fmcg`, `metals`, `telecom`, `infra`, `other`) so sector-based company resolution is an exact match, not fuzzy text matching.
- The outcome-tracker scheduler must never start automatically during tests or default `uvicorn app.main:app` runs — it is strictly opt-in via `ENABLE_SCHEDULER=true`.
- Calibration blending uses **population** standard deviation (`statistics.pstdev`).
- Passwords are never stored or logged in plaintext — only `bcrypt` hashes are persisted.
- The JWT secret key comes from `Settings.jwt_secret_key` (env `JWT_SECRET_KEY`), never hardcoded inline in a route handler.
- No live broker API integration — holdings are manual entry / CSV upload only.
- WebSocket broadcast failures for one connection must never crash the broadcast to others; `manager.broadcast_sync` must be a safe no-op when the app hasn't started or has no active connections.
- Frontend: no inline `style={{...}}` for anything expressible via the Tailwind config's design tokens (`bg-page`, `text-ink`, `border-hairline`, `text-bullish`, `bg-swatch-*`, `font-display`, `max-w-feed`, etc.); where a value genuinely cannot be a named token, use Tailwind arbitrary-value syntax (`border-[1.5px]`) consistently.
- Frontend: no `any` in TypeScript — every API response has a typed interface matching the backend's exact JSON field names. The single source of truth for these shapes is `src/lib/api.ts`; every component imports its types from there.
- Frontend components must be keyboard-accessible where interactive — buttons/tabs are real `<button>`s (Enter/Space native), chips that expand respond to Enter/Space, and any transition respects `prefers-reduced-motion` (Tailwind `motion-safe:`).
- One commit per task, at the end of that task's steps.

Additional constraints introduced by this plan:

- **No new DB columns / migrations required.** `market` is computed from the ticker string at read time, never stored. If you find yourself needing a schema migration for anything in this plan, stop and reconsider the design — the plan is deliberately migration-free. (The two new watchlist *tables* are created by the existing `Base.metadata.create_all` in `init_db()` — that is table creation on a fresh schema, not an `ALTER` migration on an existing table.)
- **Global company seed data must use REAL, factually-correct company names and tickers** — this is public-knowledge data; do not invent placeholder companies. Indian tickers keep `.NS`/`.BO`; global tickers are plain NYSE/NASDAQ symbols with **no** suffix.
- **Custom-tab filtering defaults to SHOWING NOTHING when unconfigured, never "show everything."** This is a deliberate privacy/intentionality property: an unconfigured custom filter shows an empty/configure state, not the unfiltered feed. The user's whole request is a tab that shows ONLY their selections.

---

## Task 1: Market Inference Helper

**Files:**
- Create: `backend/app/companies/market.py`
- Test: `backend/tests/test_market.py`

**Interfaces:**
- Produces: `infer_market(ticker: str) -> str` (`app.companies.market`) returning `"IN"` for `.NS`/`.BO` tickers and `"GLOBAL"` otherwise. Tasks 3 (companies endpoint), 5 (alerts/broadcast `market` field) import this by name.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_market.py`:

```python
from app.companies.market import infer_market


def test_infer_market_ns_is_india():
    assert infer_market("RELIANCE.NS") == "IN"


def test_infer_market_bo_is_india():
    assert infer_market("500325.BO") == "IN"


def test_infer_market_plain_ticker_is_global():
    assert infer_market("AAPL") == "GLOBAL"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/pytest tests/test_market.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.companies.market'`.

- [ ] **Step 3: Implement the helper**

`backend/app/companies/market.py`:

```python
def infer_market(ticker: str) -> str:
    """Derive the market ("IN" | "GLOBAL") from the ticker suffix.

    Indian NSE/BSE tickers carry a ".NS"/".BO" suffix (Plan 1 convention);
    everything else is a plain NYSE/NASDAQ-style symbol treated as GLOBAL.
    Computed at read time so no market column is stored (no migration).
    """
    return "IN" if ticker.endswith((".NS", ".BO")) else "GLOBAL"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/pytest tests/test_market.py -v`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/companies/market.py backend/tests/test_market.py
git commit -m "feat: add infer_market ticker-suffix helper"
```

---

## Task 2: Global Company Seed Data + Loader

**Files:**
- Create: `backend/app/companies/global_seed.py`
- Test: `backend/tests/test_global_seed.py`

**Interfaces:**
- Consumes: `Company` model (`app.models`, Plan 1), `SECTORS` (`app.analysis.schemas`, Plan 1).
- Produces: `GLOBAL_COMPANIES: list[dict]` (each `{"ticker", "name", "sector"}`) and `load_global_companies(session: Session) -> int` (`app.companies.global_seed`) — upserts every entry as a `Company` with `index_tier="GLOBAL_LARGE_CAP"` and `market_cap=None`, mirroring `load_companies_from_csv`'s query-before-insert pattern; returns the number of entries processed. Task 8 (e2e) and the Task 14 manual verification invoke this loader.

> Note: `index_tier="GLOBAL_LARGE_CAP"` is a new label. The existing `_TIER_RANK` `case()` in `backend/app/companies/resolution.py` ranks `NIFTY50/100/500` and defaults every other value via `else_=3`, so `GLOBAL_LARGE_CAP` falls through to rank 3 safely — **no change to `resolution.py` is required.** (Verified against the current `case(...)` expression which ends in `else_=3`.)

- [ ] **Step 1: Write the failing test**

`backend/tests/test_global_seed.py`:

```python
from app.analysis.schemas import SECTORS
from app.companies.global_seed import GLOBAL_COMPANIES, load_global_companies
from app.models import Company


def test_load_global_companies_inserts_all_entries(db_session):
    count = load_global_companies(db_session)

    assert count == len(GLOBAL_COMPANIES)
    rows = db_session.query(Company).filter_by(index_tier="GLOBAL_LARGE_CAP").all()
    assert len(rows) == len(GLOBAL_COMPANIES)


def test_load_global_companies_is_idempotent_upsert(db_session):
    load_global_companies(db_session)
    load_global_companies(db_session)

    rows = db_session.query(Company).filter_by(index_tier="GLOBAL_LARGE_CAP").all()
    assert len(rows) == len(GLOBAL_COMPANIES)  # no duplicates on re-run


def test_every_global_company_sector_is_valid():
    for entry in GLOBAL_COMPANIES:
        assert entry["sector"] in SECTORS, entry


def test_every_global_ticker_is_non_indian():
    # No global seed ticker may end in .NS/.BO, so infer_market classifies
    # them all as GLOBAL.
    for entry in GLOBAL_COMPANIES:
        assert not entry["ticker"].endswith((".NS", ".BO")), entry
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/pytest tests/test_global_seed.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.companies.global_seed'`.

- [ ] **Step 3: Implement the seed data and loader**

`backend/app/companies/global_seed.py`:

```python
from sqlalchemy.orm import Session

from app.models import Company

# Curated static list of ~50 real, well-known global large-cap companies, ~5 per
# sector, spanning the SAME fixed SECTORS taxonomy used for Indian companies so
# sector-inference resolution works identically for both markets. Tickers are
# real NYSE/NASDAQ symbols with NO .NS/.BO suffix -> infer_market -> "GLOBAL".
GLOBAL_COMPANIES: list[dict] = [
    # it
    {"ticker": "AAPL", "name": "Apple", "sector": "it"},
    {"ticker": "MSFT", "name": "Microsoft", "sector": "it"},
    {"ticker": "GOOGL", "name": "Alphabet", "sector": "it"},
    {"ticker": "NVDA", "name": "NVIDIA", "sector": "it"},
    {"ticker": "META", "name": "Meta Platforms", "sector": "it"},
    # banking
    {"ticker": "JPM", "name": "JPMorgan Chase", "sector": "banking"},
    {"ticker": "BAC", "name": "Bank of America", "sector": "banking"},
    {"ticker": "WFC", "name": "Wells Fargo", "sector": "banking"},
    {"ticker": "HSBC", "name": "HSBC Holdings", "sector": "banking"},
    {"ticker": "C", "name": "Citigroup", "sector": "banking"},
    # oil_gas
    {"ticker": "XOM", "name": "ExxonMobil", "sector": "oil_gas"},
    {"ticker": "CVX", "name": "Chevron", "sector": "oil_gas"},
    {"ticker": "SHEL", "name": "Shell", "sector": "oil_gas"},
    {"ticker": "BP", "name": "BP", "sector": "oil_gas"},
    {"ticker": "COP", "name": "ConocoPhillips", "sector": "oil_gas"},
    # auto
    {"ticker": "TSLA", "name": "Tesla", "sector": "auto"},
    {"ticker": "TM", "name": "Toyota Motor", "sector": "auto"},
    {"ticker": "VWAGY", "name": "Volkswagen", "sector": "auto"},
    {"ticker": "F", "name": "Ford Motor", "sector": "auto"},
    {"ticker": "GM", "name": "General Motors", "sector": "auto"},
    # pharma
    {"ticker": "PFE", "name": "Pfizer", "sector": "pharma"},
    {"ticker": "JNJ", "name": "Johnson & Johnson", "sector": "pharma"},
    {"ticker": "RHHBY", "name": "Roche Holding", "sector": "pharma"},
    {"ticker": "NVS", "name": "Novartis", "sector": "pharma"},
    {"ticker": "MRK", "name": "Merck & Co.", "sector": "pharma"},
    # fmcg
    {"ticker": "PG", "name": "Procter & Gamble", "sector": "fmcg"},
    {"ticker": "KO", "name": "Coca-Cola", "sector": "fmcg"},
    {"ticker": "PEP", "name": "PepsiCo", "sector": "fmcg"},
    {"ticker": "UL", "name": "Unilever", "sector": "fmcg"},
    {"ticker": "NSRGY", "name": "Nestle", "sector": "fmcg"},
    # metals
    {"ticker": "MT", "name": "ArcelorMittal", "sector": "metals"},
    {"ticker": "RIO", "name": "Rio Tinto", "sector": "metals"},
    {"ticker": "BHP", "name": "BHP Group", "sector": "metals"},
    {"ticker": "VALE", "name": "Vale", "sector": "metals"},
    {"ticker": "AA", "name": "Alcoa", "sector": "metals"},
    # telecom
    {"ticker": "VZ", "name": "Verizon Communications", "sector": "telecom"},
    {"ticker": "T", "name": "AT&T", "sector": "telecom"},
    {"ticker": "VOD", "name": "Vodafone Group", "sector": "telecom"},
    {"ticker": "DTEGY", "name": "Deutsche Telekom", "sector": "telecom"},
    {"ticker": "TMUS", "name": "T-Mobile US", "sector": "telecom"},
    # infra
    {"ticker": "CAT", "name": "Caterpillar", "sector": "infra"},
    {"ticker": "DE", "name": "Deere & Company", "sector": "infra"},
    {"ticker": "HON", "name": "Honeywell International", "sector": "infra"},
    {"ticker": "MMM", "name": "3M", "sector": "infra"},
    {"ticker": "GE", "name": "General Electric", "sector": "infra"},
    # other
    {"ticker": "BRK.B", "name": "Berkshire Hathaway", "sector": "other"},
    {"ticker": "DIS", "name": "Walt Disney", "sector": "other"},
    {"ticker": "AMZN", "name": "Amazon.com", "sector": "other"},
    {"ticker": "V", "name": "Visa", "sector": "other"},
    {"ticker": "MA", "name": "Mastercard", "sector": "other"},
]


def load_global_companies(session: Session) -> int:
    """Upsert every GLOBAL_COMPANIES entry as a Company row.

    Mirrors load_companies_from_csv's query-before-insert upsert pattern
    (no reliance on catching a unique-constraint error). All rows get
    index_tier="GLOBAL_LARGE_CAP" and market_cap=None.
    """
    count = 0
    for entry in GLOBAL_COMPANIES:
        existing = session.query(Company).filter_by(ticker=entry["ticker"]).one_or_none()
        if existing:
            existing.name = entry["name"]
            existing.sector = entry["sector"]
            existing.index_tier = "GLOBAL_LARGE_CAP"
        else:
            session.add(Company(
                ticker=entry["ticker"], name=entry["name"], sector=entry["sector"],
                index_tier="GLOBAL_LARGE_CAP", market_cap=None,
            ))
        count += 1
    session.commit()
    return count
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/pytest tests/test_global_seed.py -v`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/companies/global_seed.py backend/tests/test_global_seed.py
git commit -m "feat: add curated global company seed data and loader"
```

---

## Task 3: `GET /api/companies` Endpoint

**Files:**
- Create: `backend/app/routers/companies.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_companies_api.py`

**Interfaces:**
- Consumes: `infer_market` (Task 1), `Company` model (Plan 1), `get_db` (`app.routers.articles`, Plan 1).
- Produces: `router` (`app.routers.companies`) exposing `GET /api/companies` (no auth) with optional query param `market: "IN" | "GLOBAL"`. Response is a JSON list of `{"id", "ticker", "name", "sector", "index_tier", "market"}`. `main.py` includes it. Task 13 (`WatchlistSettings`) fetches this.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_companies_api.py`:

```python
from fastapi.testclient import TestClient

from app.main import app
from app.models import Company
from app.routers.articles import get_db


def _seed(db_session):
    db_session.add_all([
        Company(ticker="RELIANCE.NS", name="Reliance", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0),
        Company(ticker="500325.BO", name="Reliance BSE", sector="oil_gas", index_tier="NIFTY50", market_cap=1.0),
        Company(ticker="AAPL", name="Apple", sector="it", index_tier="GLOBAL_LARGE_CAP", market_cap=None),
        Company(ticker="XOM", name="ExxonMobil", sector="oil_gas", index_tier="GLOBAL_LARGE_CAP", market_cap=None),
    ])
    db_session.commit()


def test_list_companies_unfiltered_returns_all(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    _seed(db_session)
    client = TestClient(app)

    body = client.get("/api/companies").json()

    assert {c["ticker"] for c in body} == {"RELIANCE.NS", "500325.BO", "AAPL", "XOM"}
    reliance = next(c for c in body if c["ticker"] == "RELIANCE.NS")
    assert reliance["market"] == "IN"
    assert reliance["sector"] == "oil_gas"
    apple = next(c for c in body if c["ticker"] == "AAPL")
    assert apple["market"] == "GLOBAL"
    assert apple["index_tier"] == "GLOBAL_LARGE_CAP"

    app.dependency_overrides.clear()


def test_list_companies_filter_india(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    _seed(db_session)
    client = TestClient(app)

    body = client.get("/api/companies?market=IN").json()

    assert {c["ticker"] for c in body} == {"RELIANCE.NS", "500325.BO"}
    assert all(c["market"] == "IN" for c in body)

    app.dependency_overrides.clear()


def test_list_companies_filter_global(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    _seed(db_session)
    client = TestClient(app)

    body = client.get("/api/companies?market=GLOBAL").json()

    assert {c["ticker"] for c in body} == {"AAPL", "XOM"}
    assert all(c["market"] == "GLOBAL" for c in body)

    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/pytest tests/test_companies_api.py -v`
Expected: FAIL — `/api/companies` is not registered (404), or `ModuleNotFoundError: No module named 'app.routers.companies'`.

- [ ] **Step 3: Implement the router and register it**

`backend/app/routers/companies.py`:

```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.companies.market import infer_market
from app.models import Company
from app.routers.articles import get_db

router = APIRouter(prefix="/api/companies", tags=["companies"])


@router.get("")
def list_companies(market: str | None = None, db: Session = Depends(get_db)):
    # Public reference data (no auth), matching GET /api/articles' pattern.
    # market is computed in Python (not a DB column); for v1 scale a full scan
    # + in-Python filter is fine — no SQL-level LIKE filter needed.
    companies = db.query(Company).order_by(Company.name.asc()).all()
    result = []
    for c in companies:
        c_market = infer_market(c.ticker)
        if market is not None and c_market != market:
            continue
        result.append({
            "id": c.id, "ticker": c.ticker, "name": c.name,
            "sector": c.sector, "index_tier": c.index_tier, "market": c_market,
        })
    return result
```

In `backend/app/main.py`, add `companies` to the routers import and include it. Change the import line:

```python
from app.routers import alerts, articles, auth, holdings, ws
```

to:

```python
from app.routers import alerts, articles, auth, companies, holdings, ws
```

and add, immediately after `app.include_router(holdings.router)`:

```python
app.include_router(companies.router)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/pytest tests/test_companies_api.py -v`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/companies.py backend/app/main.py backend/tests/test_companies_api.py
git commit -m "feat: add GET /api/companies with optional market filter"
```

---

## Task 4: `GET /api/categories` Endpoint

**Files:**
- Create: `backend/app/routers/categories.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_categories_api.py`

**Interfaces:**
- Consumes: `Alert` model (Plan 1), `get_db` (`app.routers.articles`, Plan 1).
- Produces: `router` (`app.routers.categories`) exposing `GET /api/categories` (no auth) — the distinct set of `Alert.category` values currently in the DB, as a flat, alphabetically-sorted `list[str]`. `main.py` includes it. Task 13 (`WatchlistSettings`) fetches this to populate the category checkboxes dynamically (`Alert.category` is free text — not the fixed `SECTORS` enum — so the list must come from the DB, not a hardcoded constant).

- [ ] **Step 1: Write the failing test**

`backend/tests/test_categories_api.py`:

```python
from fastapi.testclient import TestClient

from app.main import app
from app.models import Alert, Article
from app.routers.articles import get_db


def _seed(db_session):
    article = Article(source="test", url="https://example.com/cat", title="t", status="ANALYZED")
    db_session.add(article)
    db_session.commit()
    # Two "oil_energy" (a duplicate) plus "banking" and a free-text category.
    for cat in ["oil_energy", "banking", "oil_energy", "Treasury / Rates"]:
        db_session.add(Alert(article_id=article.id, category=cat))
    db_session.commit()


def test_list_categories_returns_distinct_sorted(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    _seed(db_session)
    client = TestClient(app)

    body = client.get("/api/categories").json()

    assert body == ["Treasury / Rates", "banking", "oil_energy"]

    app.dependency_overrides.clear()


def test_list_categories_empty_when_no_alerts(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    assert client.get("/api/categories").json() == []

    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/pytest tests/test_categories_api.py -v`
Expected: FAIL — `/api/categories` is not registered (404), or `ModuleNotFoundError: No module named 'app.routers.categories'`.

- [ ] **Step 3: Implement the router and register it**

`backend/app/routers/categories.py`:

```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.models import Alert
from app.routers.articles import get_db

router = APIRouter(prefix="/api/categories", tags=["categories"])


@router.get("")
def list_categories(db: Session = Depends(get_db)):
    # Alert.category is free text (whatever the LLM returned), so the list of
    # selectable categories must come from the DB, not a hardcoded enum.
    rows = db.query(Alert.category).distinct().all()
    return sorted(row[0] for row in rows)
```

In `backend/app/main.py`, add `categories` to the routers import and include it. Change:

```python
from app.routers import alerts, articles, auth, companies, holdings, ws
```

to:

```python
from app.routers import alerts, articles, auth, categories, companies, holdings, ws
```

and add, immediately after `app.include_router(companies.router)`:

```python
app.include_router(categories.router)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/pytest tests/test_categories_api.py -v`
Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/categories.py backend/app/main.py backend/tests/test_categories_api.py
git commit -m "feat: add GET /api/categories returning distinct alert categories"
```

---

## Task 5: Expose `market` in `GET /api/alerts` and the WebSocket Broadcast

**Files:**
- Modify: `backend/app/routers/alerts.py`
- Modify: `backend/app/pipeline.py`
- Test: `backend/tests/test_api.py` (update the existing nested-companies test)
- Test: `backend/tests/test_ws_endpoint.py` (update the existing broadcast test)

**Interfaces:**
- Consumes: `infer_market` (Task 1).
- Produces: an added `"market"` key on every per-company dict in **both** the `GET /api/alerts` response (`list_alerts`) **and** the WebSocket live-push payload (`_alert_broadcast_payload`). Both response builders are updated together so the frontend `AlertCompany` type (Task 9) — from which `WsAlertCompany = Omit<AlertCompany, 'in_my_holdings'>` is derived — stays honest: every company the frontend ever sees, whether REST-fetched or live-pushed, carries `market`. Tasks 11/14 rely on `market` being present on live alerts for the India/Global tab filter to work.

- [ ] **Step 1: Update the failing tests**

In `backend/tests/test_api.py`, in `test_list_alerts_returns_nested_companies`, after the existing assertion on `body[0]["companies"][0]["ticker"] == "RELIANCE.NS"`, add:

```python
    assert body[0]["companies"][0]["market"] == "IN"
```

In `backend/tests/test_ws_endpoint.py`, in `test_pipeline_broadcasts_new_alert_to_connected_client`, after the existing assertion on `payload["companies"][0]["direction"] == "bullish"`, add:

```python
    assert payload["companies"][0]["market"] == "IN"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/pytest tests/test_api.py::test_list_alerts_returns_nested_companies tests/test_ws_endpoint.py::test_pipeline_broadcasts_new_alert_to_connected_client -v`
Expected: FAIL — `KeyError: 'market'` (the field is not in either payload yet).

- [ ] **Step 3: Add `market` to both response builders**

In `backend/app/routers/alerts.py`, add the import near the top (after the existing `from app.models import ...` line):

```python
from app.companies.market import infer_market
```

and in `list_alerts`, add `"market": infer_market(ac.company.ticker),` to the per-company dict. The company dict becomes:

```python
        "companies": [{
            "company_id": ac.company_id, "ticker": ac.company.ticker, "name": ac.company.name,
            "index_tier": ac.company.index_tier, "direction": ac.direction,
            "magnitude_low": ac.magnitude_low, "magnitude_high": ac.magnitude_high,
            "rationale": ac.rationale, "basis": ac.basis, "confidence": ac.confidence,
            "market": infer_market(ac.company.ticker),
            "in_my_holdings": ac.company_id in held_company_ids,
        } for ac in alert.companies],
```

In `backend/app/pipeline.py`, add the import alongside the other `app.` imports at the top of the file:

```python
from app.companies.market import infer_market
```

and in `_alert_broadcast_payload`, add `"market": infer_market(ac.company.ticker),` to the per-company dict. That dict becomes:

```python
        "companies": [{
            "company_id": ac.company_id,
            "ticker": ac.company.ticker,
            "name": ac.company.name,
            "index_tier": ac.company.index_tier,
            "direction": ac.direction,
            "magnitude_low": ac.magnitude_low,
            "magnitude_high": ac.magnitude_high,
            "rationale": ac.rationale,
            "basis": ac.basis,
            "confidence": ac.confidence,
            "market": infer_market(ac.company.ticker),
        } for ac in alert.companies],
```

(The live-push payload still intentionally omits `in_my_holdings` — that per-viewer flag is unchanged by this task.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/pytest tests/test_api.py tests/test_ws_endpoint.py -v`
Expected: all pass — the two updated assertions plus every other test in both files.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/alerts.py backend/app/pipeline.py backend/tests/test_api.py backend/tests/test_ws_endpoint.py
git commit -m "feat: expose computed market per company on alerts REST + WS payloads"
```

---

## Task 6: Watchlist Models

**Files:**
- Modify: `backend/app/models.py`
- Test: `backend/tests/test_watchlist_models.py`

**Interfaces:**
- Consumes: `Base`, `utcnow` (`app.models`, Plan 1), `User`/`Company` FKs.
- Produces: `UserWatchlistCategory` and `UserWatchlistCompany` models (`app.models`) — per-user join tables with the exact columns and unique constraints below. Task 7 (watchlist API) reads/writes both. Tables are created on a fresh schema by `Base.metadata.create_all` in the existing `init_db()` — no migration.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_watchlist_models.py`:

```python
import pytest

from app.models import Company, User, UserWatchlistCategory, UserWatchlistCompany


def _make_user_and_company(session):
    user = User(email="w@example.com", hashed_password="x")
    company = Company(ticker="AAPL", name="Apple", sector="it", index_tier="GLOBAL_LARGE_CAP", market_cap=None)
    session.add_all([user, company])
    session.commit()
    return user, company


def test_create_watchlist_rows(db_session):
    user, company = _make_user_and_company(db_session)
    db_session.add(UserWatchlistCategory(user_id=user.id, category="oil_energy"))
    db_session.add(UserWatchlistCompany(user_id=user.id, company_id=company.id))
    db_session.commit()

    assert db_session.query(UserWatchlistCategory).one().category == "oil_energy"
    assert db_session.query(UserWatchlistCompany).one().company_id == company.id


def test_watchlist_category_unique_per_user(db_session):
    user, _ = _make_user_and_company(db_session)
    db_session.add(UserWatchlistCategory(user_id=user.id, category="oil_energy"))
    db_session.commit()

    db_session.add(UserWatchlistCategory(user_id=user.id, category="oil_energy"))
    with pytest.raises(Exception):
        db_session.commit()


def test_watchlist_company_unique_per_user(db_session):
    user, company = _make_user_and_company(db_session)
    db_session.add(UserWatchlistCompany(user_id=user.id, company_id=company.id))
    db_session.commit()

    db_session.add(UserWatchlistCompany(user_id=user.id, company_id=company.id))
    with pytest.raises(Exception):
        db_session.commit()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/pytest tests/test_watchlist_models.py -v`
Expected: FAIL with `ImportError: cannot import name 'UserWatchlistCategory' from 'app.models'`.

- [ ] **Step 3: Add the models**

Append to `backend/app/models.py` (after the existing `EmailNotification` class; `Column`, `DateTime`, `ForeignKey`, `Integer`, `String`, `UniqueConstraint`, and `utcnow` are already imported/defined at the top of the file):

```python
class UserWatchlistCategory(Base):
    __tablename__ = "user_watchlist_categories"
    __table_args__ = (
        UniqueConstraint("user_id", "category", name="uq_watchlist_category_user_category"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    category = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)


class UserWatchlistCompany(Base):
    __tablename__ = "user_watchlist_companies"
    __table_args__ = (
        UniqueConstraint("user_id", "company_id", name="uq_watchlist_company_user_company"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    company_id = Column(Integer, ForeignKey("companies.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utcnow)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/pytest tests/test_watchlist_models.py -v`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/models.py backend/tests/test_watchlist_models.py
git commit -m "feat: add per-user watchlist category/company join tables"
```

---

## Task 7: Watchlist API (`GET`/`PUT /api/watchlist`)

**Files:**
- Create: `backend/app/routers/watchlist.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_watchlist_api.py`

**Interfaces:**
- Consumes: `get_current_user` (`app.auth.dependencies`, Plan 3), `get_db` (`app.routers.articles`, Plan 1), `Company`/`User`/`UserWatchlistCategory`/`UserWatchlistCompany` (Task 6).
- Produces: `router` (`app.routers.watchlist`) exposing `GET /api/watchlist` and `PUT /api/watchlist` (both auth-required). GET returns `{"categories": list[str], "companies": [{"company_id", "ticker", "name"}, ...]}` for the current user. PUT accepts `{"categories": list[str], "company_ids": list[int]}`, **replaces** the user's full set (delete-all then insert), and returns the same shape as GET. `main.py` includes it. Task 9 (`getWatchlist`/`putWatchlist`), Task 13 (`WatchlistSettings`), and Task 14 (`Feed`) consume this contract — the JSON shape must match the frontend `Watchlist` type exactly.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_watchlist_api.py`:

```python
from fastapi.testclient import TestClient

from app.main import app
from app.models import Company
from app.routers.articles import get_db


def _client_and_token(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)
    resp = client.post("/api/auth/register", json={"email": "wl@example.com", "password": "pw12345"})
    return client, resp.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _seed_company(db_session, ticker, name):
    company = Company(ticker=ticker, name=name, sector="it", index_tier="GLOBAL_LARGE_CAP", market_cap=None)
    db_session.add(company)
    db_session.commit()
    return company


def test_get_watchlist_empty_by_default(db_session):
    client, token = _client_and_token(db_session)

    body = client.get("/api/watchlist", headers=_auth(token)).json()

    assert body == {"categories": [], "companies": []}
    app.dependency_overrides.clear()


def test_put_then_get_reflects_saved_selection(db_session):
    client, token = _client_and_token(db_session)
    company = _seed_company(db_session, "AAPL", "Apple")

    put = client.put(
        "/api/watchlist",
        json={"categories": ["oil_energy"], "company_ids": [company.id]},
        headers=_auth(token),
    )
    assert put.status_code == 200
    assert put.json()["categories"] == ["oil_energy"]
    assert put.json()["companies"] == [{"company_id": company.id, "ticker": "AAPL", "name": "Apple"}]

    get = client.get("/api/watchlist", headers=_auth(token)).json()
    assert get["categories"] == ["oil_energy"]
    assert [c["company_id"] for c in get["companies"]] == [company.id]

    app.dependency_overrides.clear()


def test_put_replaces_previous_selection(db_session):
    client, token = _client_and_token(db_session)
    apple = _seed_company(db_session, "AAPL", "Apple")
    msft = _seed_company(db_session, "MSFT", "Microsoft")

    client.put(
        "/api/watchlist",
        json={"categories": ["oil_energy"], "company_ids": [apple.id]},
        headers=_auth(token),
    )
    # Second PUT with a DIFFERENT set must fully replace the first.
    client.put(
        "/api/watchlist",
        json={"categories": ["banking"], "company_ids": [msft.id]},
        headers=_auth(token),
    )

    get = client.get("/api/watchlist", headers=_auth(token)).json()
    assert get["categories"] == ["banking"]
    assert [c["company_id"] for c in get["companies"]] == [msft.id]

    app.dependency_overrides.clear()


def test_watchlist_requires_auth(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app)

    assert client.get("/api/watchlist").status_code in (401, 403)
    assert client.put("/api/watchlist", json={"categories": [], "company_ids": []}).status_code in (401, 403)

    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/pytest tests/test_watchlist_api.py -v`
Expected: FAIL — `/api/watchlist` is not registered (404), or `ModuleNotFoundError: No module named 'app.routers.watchlist'`.

- [ ] **Step 3: Implement the router and register it**

`backend/app/routers/watchlist.py`:

```python
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.models import Company, User, UserWatchlistCategory, UserWatchlistCompany
from app.routers.articles import get_db

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


class WatchlistRequest(BaseModel):
    categories: list[str]
    company_ids: list[int]


def _serialize_watchlist(db: Session, user_id: int) -> dict:
    categories = [
        row.category
        for row in db.query(UserWatchlistCategory).filter_by(user_id=user_id).all()
    ]
    company_rows = (
        db.query(UserWatchlistCompany, Company)
        .join(Company, UserWatchlistCompany.company_id == Company.id)
        .filter(UserWatchlistCompany.user_id == user_id)
        .all()
    )
    companies = [
        {"company_id": company.id, "ticker": company.ticker, "name": company.name}
        for _, company in company_rows
    ]
    return {"categories": sorted(categories), "companies": companies}


@router.get("")
def get_watchlist(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _serialize_watchlist(db, current_user.id)


@router.put("")
def put_watchlist(
    payload: WatchlistRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Replace-all semantics: wipe this user's selection, then insert the new set.
    # set(...) dedupes any repeats in the body so the unique constraints hold.
    db.query(UserWatchlistCategory).filter_by(user_id=current_user.id).delete()
    db.query(UserWatchlistCompany).filter_by(user_id=current_user.id).delete()
    for category in set(payload.categories):
        db.add(UserWatchlistCategory(user_id=current_user.id, category=category))
    for company_id in set(payload.company_ids):
        db.add(UserWatchlistCompany(user_id=current_user.id, company_id=company_id))
    db.commit()
    return _serialize_watchlist(db, current_user.id)
```

In `backend/app/main.py`, add `watchlist` to the routers import and include it. Change:

```python
from app.routers import alerts, articles, auth, categories, companies, holdings, ws
```

to:

```python
from app.routers import alerts, articles, auth, categories, companies, holdings, watchlist, ws
```

and add, immediately after `app.include_router(categories.router)`:

```python
app.include_router(watchlist.router)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/pytest tests/test_watchlist_api.py -v`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/watchlist.py backend/app/main.py backend/tests/test_watchlist_api.py
git commit -m "feat: add GET/PUT /api/watchlist with replace-all semantics"
```

---

## Task 8: Backend End-to-End Test

**Files:**
- Modify: `backend/tests/test_end_to_end.py`

**Interfaces:**
- Consumes: the real `/api/auth/register`, `/api/watchlist`, `/api/companies`, `/api/categories` endpoints (Tasks 3/4/7), `fetch_new_articles` (Plan 1), `process_new_articles` (Plan 4), `load_global_companies` (Task 2) — exercises the full chain end-to-end with only Claude analysis mocked, matching this file's established style.

- [ ] **Step 1: Add the end-to-end test**

Append this test to `backend/tests/test_end_to_end.py` (keep the existing tests and imports; add the `load_global_companies` import at the top of the file next to the existing imports):

```python
from app.companies.global_seed import load_global_companies


def test_feed_tabs_end_to_end(db_session, monkeypatch):
    from app.main import app as fastapi_app
    from app.routers.articles import get_db
    from fastapi.testclient import TestClient

    fastapi_app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(fastapi_app)

    # Seed the Indian company the analysis will resolve to, plus the global set.
    db_session.add(Company(
        ticker="RELIANCE.NS", name="Reliance Industries",
        sector="oil_gas", index_tier="NIFTY50", market_cap=1_800_000.0,
    ))
    db_session.commit()
    loaded = load_global_companies(db_session)
    assert loaded == len(GLOBAL_COMPANIES)

    # Register a real user and save a watchlist (one category, one company).
    token = client.post(
        "/api/auth/register", json={"email": "tabs@example.com", "password": "pw12345"},
    ).json()["access_token"]
    auth = {"Authorization": f"Bearer {token}"}

    reliance = db_session.query(Company).filter_by(ticker="RELIANCE.NS").one()
    put = client.put(
        "/api/watchlist",
        json={"categories": ["oil_energy"], "company_ids": [reliance.id]},
        headers=auth,
    )
    assert put.status_code == 200

    # Ingest one RSS article and run the pipeline (Claude analysis mocked).
    feed_entries = [{
        "link": "https://example.com/breaking-oil-news-tabs",
        "title": "US strikes Iran oil export sites",
        "summary": "Crude oil markets react sharply to the strikes.",
    }]
    monkeypatch.setattr(
        "app.ingestion.poller.feedparser.parse",
        lambda url: SimpleNamespace(entries=feed_entries),
    )
    inserted = fetch_new_articles(db_session, [{"source": "test_feed", "url": "http://feed.test/rss"}])
    assert inserted == 1

    fake_output = AnalysisOutput(
        category="oil_energy",
        companies=[CompanyMention(
            name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
            direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin up",
        )],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article", lambda client, title, content: fake_output)

    created = process_new_articles(db_session, claude_client=object())
    assert created == 1

    # (a) GET /api/watchlist reflects the saved selection.
    watchlist = client.get("/api/watchlist", headers=auth).json()
    assert watchlist["categories"] == ["oil_energy"]
    assert [c["ticker"] for c in watchlist["companies"]] == ["RELIANCE.NS"]

    # (b) GET /api/companies?market=IN returns the Indian company (and no global).
    india = client.get("/api/companies?market=IN").json()
    india_tickers = {c["ticker"] for c in india}
    assert "RELIANCE.NS" in india_tickers
    assert all(c["market"] == "IN" for c in india)
    assert "AAPL" not in india_tickers

    # ...and ?market=GLOBAL returns the seeded global set.
    glob = client.get("/api/companies?market=GLOBAL").json()
    glob_tickers = {c["ticker"] for c in glob}
    assert "AAPL" in glob_tickers
    assert "RELIANCE.NS" not in glob_tickers

    # (c) GET /api/categories reflects the analyzed alert's category.
    assert client.get("/api/categories").json() == ["oil_energy"]

    # (d) The alert itself carries the computed market on its company.
    alert_body = client.get("/api/alerts", headers=auth).json()
    assert alert_body[0]["companies"][0]["market"] == "IN"

    fastapi_app.dependency_overrides.clear()
```

Add `GLOBAL_COMPANIES` to the `load_global_companies` import line so both names are available:

```python
from app.companies.global_seed import GLOBAL_COMPANIES, load_global_companies
```

- [ ] **Step 2: Run the full backend suite**

Run: `cd backend && .venv/Scripts/pytest tests/ -v`
Expected: every test passes (this new e2e test plus all of Tasks 1-7 and every Plan 1-4 test), no live network calls.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_end_to_end.py
git commit -m "test: add feed-tabs end-to-end (watchlist + companies + categories)"
```

---

## Task 9: Frontend API Client Additions

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Test: `frontend/src/lib/api.test.ts` (extend the existing file)

**Interfaces:**
- Produces (all in `src/lib/api.ts`): the `market: 'IN' | 'GLOBAL'` field added to the `AlertCompany` interface (so `WsAlertCompany`/`WsAlert` inherit it automatically), plus new types `Company`, `WatchlistCompany`, `Watchlist`, and new functions `getCompanies(market?)`, `getCategories()`, `getWatchlist(token)`, `putWatchlist(token, categories, companyIds)`. Tasks 11 (filters), 13 (`WatchlistSettings`), 14 (`Feed`) import these.

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/lib/api.test.ts` — add the four new functions to the existing import at the top:

```ts
import {
  addHolding,
  getAlerts,
  getCategories,
  getCompanies,
  getWatchlist,
  login,
  putWatchlist,
  register,
} from './api';
```

and add these tests inside the existing `describe('api client', ...)` block:

```ts
  it('getCompanies fetches all companies with no query when no market given', async () => {
    const fetchMock = mockFetchOnce([]);
    await getCompanies();
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/companies');
  });

  it('getCompanies appends the market query param', async () => {
    const fetchMock = mockFetchOnce([]);
    await getCompanies('IN');
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/companies?market=IN');
  });

  it('getCategories fetches the categories endpoint', async () => {
    const fetchMock = mockFetchOnce(['banking', 'oil_energy']);
    const result = await getCategories();
    const [url] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/categories');
    expect(result).toEqual(['banking', 'oil_energy']);
  });

  it('getWatchlist attaches the Bearer token', async () => {
    const fetchMock = mockFetchOnce({ categories: [], companies: [] });
    await getWatchlist('tok');
    const [url, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/watchlist');
    expect((opts.headers as Record<string, string>).Authorization).toBe('Bearer tok');
  });

  it('putWatchlist PUTs categories and company_ids with the Bearer token', async () => {
    const fetchMock = mockFetchOnce({ categories: ['oil_energy'], companies: [] });
    await putWatchlist('tok', ['oil_energy'], [7]);
    const [url, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/watchlist');
    expect(opts.method).toBe('PUT');
    expect((opts.headers as Record<string, string>).Authorization).toBe('Bearer tok');
    expect(JSON.parse(opts.body as string)).toEqual({ categories: ['oil_energy'], company_ids: [7] });
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `frontend/`): `npm run test -- src/lib/api.test.ts`
Expected: FAIL — `getCompanies`, `getCategories`, `getWatchlist`, `putWatchlist` are not exported yet.

- [ ] **Step 3: Extend the API client**

In `frontend/src/lib/api.ts`, add `market` to the `AlertCompany` interface (after the `basis`/`confidence` fields, before `in_my_holdings`):

```ts
export interface AlertCompany {
  company_id: number;
  ticker: string;
  name: string;
  index_tier: string; // NIFTY50 | NIFTY100 | NIFTY500 | GLOBAL_LARGE_CAP | OTHER
  direction: string; // bullish | bearish
  magnitude_low: number;
  magnitude_high: number;
  rationale: string;
  basis: string; // direct_mention | sector_inference
  confidence: string; // llm_estimate | calibrated
  market: 'IN' | 'GLOBAL';
  in_my_holdings: boolean;
}
```

Add these new type declarations after the existing `CsvUploadResponse` interface:

```ts
export interface Company {
  id: number;
  ticker: string;
  name: string;
  sector: string;
  index_tier: string;
  market: 'IN' | 'GLOBAL';
}

export interface WatchlistCompany {
  company_id: number;
  ticker: string;
  name: string;
}

export interface Watchlist {
  categories: string[];
  companies: WatchlistCompany[];
}
```

Add these new functions at the end of the file:

```ts
export async function getCompanies(market?: 'IN' | 'GLOBAL'): Promise<Company[]> {
  const query = market ? `?market=${market}` : '';
  const res = await fetch(`/api/companies${query}`);
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as Company[];
}

export async function getCategories(): Promise<string[]> {
  const res = await fetch('/api/categories');
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as string[];
}

export async function getWatchlist(token: string): Promise<Watchlist> {
  const res = await fetch('/api/watchlist', { headers: authHeaders(token) });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as Watchlist;
}

export async function putWatchlist(
  token: string,
  categories: string[],
  companyIds: number[],
): Promise<Watchlist> {
  const res = await fetch('/api/watchlist', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify({ categories, company_ids: companyIds }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as Watchlist;
}
```

> The `market` field is now required on `AlertCompany`. Existing test fixtures that construct an `AlertCompany` literal (in `AlertCard.test.tsx`, `CompanyChip.test.tsx`, `ReasoningPanel.test.tsx`, `useAlertsSocket.test.tsx`) will need `market` added — but `WsAlertCompany = Omit<AlertCompany, 'in_my_holdings'>` still includes `market`, so the WS fixtures need it too. Those fixtures are only touched if a task in this plan re-renders them; they are updated as part of Task 14 where the Feed/AlertCard tests are extended. If `npm run test` (all files) is run now it will surface type errors in those fixtures — that is expected until Task 14. Run only `src/lib/api.test.ts` for this task's gate.

- [ ] **Step 4: Run test to verify it passes**

Run (from `frontend/`): `npm run test -- src/lib/api.test.ts`
Expected: all `api client` tests pass (the 5 original + 5 new).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/lib/api.test.ts
git commit -m "feat: add companies/categories/watchlist API client functions and market field"
```

---

## Task 10: `FeedTabs` Component

**Files:**
- Create: `frontend/src/components/FeedTabs.tsx`
- Test: `frontend/src/components/FeedTabs.test.tsx`

**Interfaces:**
- Produces: `FeedTab` type (`'india' | 'global' | 'custom'`) and default-exported `FeedTabs` component (`{ active: FeedTab; onChange: (tab: FeedTab) => void }`) — a controlled, page-level tab bar. Styling reuses the existing tab-button token pattern from `AlertCard.tsx` (tracked-uppercase, `border-b-2` active underline, `text-ink`/`text-muted`) but larger (`text-sm`, `pb-3`) since it is a page-level control. Tasks 11/14 import `FeedTab`; Task 14 (`FeedPage`) renders `FeedTabs`.

- [ ] **Step 1: Write the failing test**

`frontend/src/components/FeedTabs.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import FeedTabs from './FeedTabs';

describe('FeedTabs', () => {
  it('renders all three tabs', () => {
    render(<FeedTabs active="india" onChange={() => {}} />);
    expect(screen.getByRole('tab', { name: /india/i })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /global/i })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /custom/i })).toBeInTheDocument();
  });

  it('marks the active tab as selected', () => {
    render(<FeedTabs active="global" onChange={() => {}} />);
    expect(screen.getByRole('tab', { name: /global/i })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: /india/i })).toHaveAttribute('aria-selected', 'false');
  });

  it('calls onChange with the tab key when a tab is clicked', async () => {
    const onChange = vi.fn();
    render(<FeedTabs active="india" onChange={onChange} />);
    await userEvent.click(screen.getByRole('tab', { name: /custom/i }));
    expect(onChange).toHaveBeenCalledWith('custom');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `frontend/`): `npm run test -- src/components/FeedTabs.test.tsx`
Expected: FAIL — `FeedTabs` does not exist yet.

- [ ] **Step 3: Implement the component**

`frontend/src/components/FeedTabs.tsx`:

```tsx
export type FeedTab = 'india' | 'global' | 'custom';

const TABS: { key: FeedTab; label: string }[] = [
  { key: 'india', label: 'India' },
  { key: 'global', label: 'Global' },
  { key: 'custom', label: 'Custom' },
];

export default function FeedTabs({
  active,
  onChange,
}: {
  active: FeedTab;
  onChange: (tab: FeedTab) => void;
}) {
  return (
    <div className="mb-6 flex gap-6 border-b border-hairline" role="tablist" aria-label="Feed markets">
      {TABS.map((t) => {
        const isActive = t.key === active;
        return (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={isActive}
            onClick={() => onChange(t.key)}
            className={`border-b-2 pb-3 text-sm uppercase tracking-widest ${
              isActive ? 'border-ink text-ink' : 'border-transparent text-muted hover:text-ink'
            }`}
          >
            {t.label}
          </button>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `frontend/`): `npm run test -- src/components/FeedTabs.test.tsx`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/FeedTabs.tsx frontend/src/components/FeedTabs.test.tsx
git commit -m "feat: add page-level FeedTabs (India/Global/Custom) tab bar"
```

---

## Task 11: Market + Custom Feed Filter Logic

**Files:**
- Create: `frontend/src/lib/feedFilters.ts`
- Test: `frontend/src/lib/feedFilters.test.ts`

**Interfaces:**
- Consumes: `Alert`, `Watchlist` types (Task 9).
- Produces (all in `src/lib/feedFilters.ts`): `Market` type (`'IN' | 'GLOBAL'`), `alertMatchesMarket(alert: Alert, market: Market): boolean` (an alert matches a market if ANY of its companies has that market; a zero-company alert matches NEITHER), and `alertMatchesWatchlist(alert: Alert, watchlist: Watchlist): boolean` (true if the alert's `category` is in the watchlist categories OR any of its companies is in the watchlist companies; an **empty** watchlist matches NOTHING — never "show everything"). Task 14 (`Feed`) imports both.

- [ ] **Step 1: Write the failing test**

`frontend/src/lib/feedFilters.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { alertMatchesMarket, alertMatchesWatchlist } from './feedFilters';
import type { Alert, AlertCompany, Watchlist } from './api';

function company(overrides: Partial<AlertCompany>): AlertCompany {
  return {
    company_id: 1,
    ticker: 'RELIANCE.NS',
    name: 'Reliance',
    index_tier: 'NIFTY50',
    direction: 'bullish',
    magnitude_low: 1,
    magnitude_high: 2,
    rationale: 'x',
    basis: 'direct_mention',
    confidence: 'llm_estimate',
    market: 'IN',
    in_my_holdings: false,
    ...overrides,
  };
}

function alert(overrides: Partial<Alert>): Alert {
  return {
    id: 1,
    category: 'oil_energy',
    created_at: '2026-07-10T10:00:00+00:00',
    article: { id: 1, title: 't', url: 'https://example.com/1' },
    companies: [],
    ...overrides,
  };
}

describe('alertMatchesMarket', () => {
  it('an alert with only .NS companies matches India, not Global', () => {
    const a = alert({ companies: [company({ market: 'IN' })] });
    expect(alertMatchesMarket(a, 'IN')).toBe(true);
    expect(alertMatchesMarket(a, 'GLOBAL')).toBe(false);
  });

  it('an alert with only non-.NS companies matches Global, not India', () => {
    const a = alert({ companies: [company({ company_id: 2, ticker: 'AAPL', market: 'GLOBAL' })] });
    expect(alertMatchesMarket(a, 'GLOBAL')).toBe(true);
    expect(alertMatchesMarket(a, 'IN')).toBe(false);
  });

  it('an alert with companies from BOTH markets matches both', () => {
    const a = alert({
      companies: [company({ market: 'IN' }), company({ company_id: 2, ticker: 'AAPL', market: 'GLOBAL' })],
    });
    expect(alertMatchesMarket(a, 'IN')).toBe(true);
    expect(alertMatchesMarket(a, 'GLOBAL')).toBe(true);
  });

  it('an alert with ZERO companies matches neither market', () => {
    const a = alert({ companies: [] });
    expect(alertMatchesMarket(a, 'IN')).toBe(false);
    expect(alertMatchesMarket(a, 'GLOBAL')).toBe(false);
  });
});

describe('alertMatchesWatchlist', () => {
  const watchlist: Watchlist = {
    categories: ['oil_energy'],
    companies: [{ company_id: 5, ticker: 'AAPL', name: 'Apple' }],
  };

  it('matches on category alone', () => {
    const a = alert({ category: 'oil_energy', companies: [] });
    expect(alertMatchesWatchlist(a, watchlist)).toBe(true);
  });

  it('matches on company alone', () => {
    const a = alert({ category: 'banking', companies: [company({ company_id: 5 })] });
    expect(alertMatchesWatchlist(a, watchlist)).toBe(true);
  });

  it('matches when BOTH category and company match (still true)', () => {
    const a = alert({ category: 'oil_energy', companies: [company({ company_id: 5 })] });
    expect(alertMatchesWatchlist(a, watchlist)).toBe(true);
  });

  it('does not match when neither category nor company match', () => {
    const a = alert({ category: 'banking', companies: [company({ company_id: 99 })] });
    expect(alertMatchesWatchlist(a, watchlist)).toBe(false);
  });

  it('an empty watchlist matches NOTHING (never show-all)', () => {
    const empty: Watchlist = { categories: [], companies: [] };
    const a = alert({ category: 'oil_energy', companies: [company({ company_id: 5 })] });
    expect(alertMatchesWatchlist(a, empty)).toBe(false);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `frontend/`): `npm run test -- src/lib/feedFilters.test.ts`
Expected: FAIL — `./feedFilters` does not exist yet.

- [ ] **Step 3: Implement the filters**

`frontend/src/lib/feedFilters.ts`:

```ts
import type { Alert, Watchlist } from './api';

export type Market = 'IN' | 'GLOBAL';

// An alert belongs to a market tab if ANY of its companies is in that market.
// A zero-company alert matches NEITHER tab (correct: neither India nor Global
// claims it, per the feature design — there is no unfiltered "all" tab).
export function alertMatchesMarket(alert: Alert, market: Market): boolean {
  return alert.companies.some((c) => c.market === market);
}

// The Custom tab shows an alert if its category is watchlisted OR any of its
// companies is watchlisted (OR, not AND — two independent filter facets). An
// EMPTY watchlist matches nothing: an unconfigured custom filter must never
// silently show the whole feed.
export function alertMatchesWatchlist(alert: Alert, watchlist: Watchlist): boolean {
  if (watchlist.categories.length === 0 && watchlist.companies.length === 0) {
    return false;
  }
  if (watchlist.categories.includes(alert.category)) {
    return true;
  }
  return alert.companies.some((c) =>
    watchlist.companies.some((w) => w.company_id === c.company_id),
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `frontend/`): `npm run test -- src/lib/feedFilters.test.ts`
Expected: `9 passed`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/feedFilters.ts frontend/src/lib/feedFilters.test.ts
git commit -m "feat: add pure market and watchlist feed-filter functions"
```

---

## Task 12: `WatchlistSettings` Component

**Files:**
- Create: `frontend/src/components/WatchlistSettings.tsx`
- Test: `frontend/src/components/WatchlistSettings.test.tsx`

**Interfaces:**
- Consumes: `getCategories`, `getCompanies`, `getWatchlist`, `putWatchlist`, `Company` type (Task 9), `useAuth()` (Plan 4).
- Produces: default-exported `WatchlistSettings` component (`{ onSaved?: () => void }`) — on mount (when authenticated) fetches the live category list, the full company list, and the user's current watchlist; renders a checkbox per category, a text filter + scrollable checkbox list of companies (filtered by name/ticker substring, client-side), pre-checks boxes from the current watchlist, and a "Save" button that calls `putWatchlist` and shows a `role="alert"` success/error message. Task 14 (`Feed`) renders this inline on the Custom tab and passes `onSaved` to refresh its filter.

- [ ] **Step 1: Write the failing test**

`frontend/src/components/WatchlistSettings.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import WatchlistSettings from './WatchlistSettings';
import { AuthProvider } from '../lib/auth';
import * as api from '../lib/api';
import type { Company, Watchlist } from '../lib/api';

const companies: Company[] = [
  { id: 1, ticker: 'AAPL', name: 'Apple', sector: 'it', index_tier: 'GLOBAL_LARGE_CAP', market: 'GLOBAL' },
  { id: 2, ticker: 'RELIANCE.NS', name: 'Reliance', sector: 'oil_gas', index_tier: 'NIFTY50', market: 'IN' },
];

function setToken() {
  localStorage.setItem('newsflo.token', 'tok');
  localStorage.setItem('newsflo.email', 'a@example.com');
}

function mockApis(watchlist: Watchlist) {
  vi.spyOn(api, 'getCategories').mockResolvedValue(['banking', 'oil_energy']);
  vi.spyOn(api, 'getCompanies').mockResolvedValue(companies);
  vi.spyOn(api, 'getWatchlist').mockResolvedValue(watchlist);
}

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe('WatchlistSettings', () => {
  it('renders categories and companies from the API', async () => {
    setToken();
    mockApis({ categories: [], companies: [] });
    render(
      <AuthProvider>
        <WatchlistSettings />
      </AuthProvider>,
    );
    expect(await screen.findByLabelText('oil_energy')).toBeInTheDocument();
    expect(screen.getByLabelText('banking')).toBeInTheDocument();
    expect(screen.getByLabelText(/Apple/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Reliance/)).toBeInTheDocument();
  });

  it('pre-checks boxes from the existing watchlist', async () => {
    setToken();
    mockApis({ categories: ['oil_energy'], companies: [{ company_id: 1, ticker: 'AAPL', name: 'Apple' }] });
    render(
      <AuthProvider>
        <WatchlistSettings />
      </AuthProvider>,
    );
    expect(await screen.findByLabelText('oil_energy')).toBeChecked();
    expect(screen.getByLabelText('banking')).not.toBeChecked();
    expect(screen.getByLabelText(/Apple/)).toBeChecked();
    expect(screen.getByLabelText(/Reliance/)).not.toBeChecked();
  });

  it('saves the selected category and company via putWatchlist', async () => {
    setToken();
    mockApis({ categories: [], companies: [] });
    const put = vi
      .spyOn(api, 'putWatchlist')
      .mockResolvedValue({ categories: ['oil_energy'], companies: [{ company_id: 1, ticker: 'AAPL', name: 'Apple' }] });
    render(
      <AuthProvider>
        <WatchlistSettings />
      </AuthProvider>,
    );
    await userEvent.click(await screen.findByLabelText('oil_energy'));
    await userEvent.click(screen.getByLabelText(/Apple/));
    await userEvent.click(screen.getByRole('button', { name: /save/i }));
    await waitFor(() => expect(put).toHaveBeenCalledWith('tok', ['oil_energy'], [1]));
    expect(await screen.findByRole('alert')).toHaveTextContent(/saved/i);
  });

  it('filters the company list by the text input', async () => {
    setToken();
    mockApis({ categories: [], companies: [] });
    render(
      <AuthProvider>
        <WatchlistSettings />
      </AuthProvider>,
    );
    await screen.findByLabelText(/Apple/);
    await userEvent.type(screen.getByLabelText(/filter companies/i), 'relian');
    expect(screen.getByLabelText(/Reliance/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/Apple/)).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `frontend/`): `npm run test -- src/components/WatchlistSettings.test.tsx`
Expected: FAIL — `WatchlistSettings` does not exist yet.

- [ ] **Step 3: Implement the component**

`frontend/src/components/WatchlistSettings.tsx`:

```tsx
import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { getCategories, getCompanies, getWatchlist, putWatchlist, type Company } from '../lib/api';
import { useAuth } from '../lib/auth';

export default function WatchlistSettings({ onSaved }: { onSaved?: () => void }) {
  const { token } = useAuth();
  const [categories, setCategories] = useState<string[]>([]);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [selectedCategories, setSelectedCategories] = useState<Set<string>>(new Set());
  const [selectedCompanyIds, setSelectedCompanyIds] = useState<Set<number>>(new Set());
  const [filter, setFilter] = useState('');
  const [message, setMessage] = useState<string | null>(null);
  const [isError, setIsError] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!token) return;
    let active = true;
    Promise.all([getCategories(), getCompanies(), getWatchlist(token)])
      .then(([cats, comps, watchlist]) => {
        if (!active) return;
        setCategories(cats);
        setCompanies(comps);
        setSelectedCategories(new Set(watchlist.categories));
        setSelectedCompanyIds(new Set(watchlist.companies.map((c) => c.company_id)));
      })
      .catch((err: unknown) => {
        if (!active) return;
        setIsError(true);
        setMessage(err instanceof Error ? err.message : 'Failed to load filters.');
      });
    return () => {
      active = false;
    };
  }, [token]);

  const filteredCompanies = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return companies;
    return companies.filter(
      (c) => c.name.toLowerCase().includes(q) || c.ticker.toLowerCase().includes(q),
    );
  }, [companies, filter]);

  function toggleCategory(category: string) {
    setSelectedCategories((prev) => {
      const next = new Set(prev);
      if (next.has(category)) next.delete(category);
      else next.add(category);
      return next;
    });
  }

  function toggleCompany(companyId: number) {
    setSelectedCompanyIds((prev) => {
      const next = new Set(prev);
      if (next.has(companyId)) next.delete(companyId);
      else next.add(companyId);
      return next;
    });
  }

  async function handleSave(e: FormEvent) {
    e.preventDefault();
    if (!token) return;
    setSaving(true);
    setMessage(null);
    try {
      await putWatchlist(token, [...selectedCategories], [...selectedCompanyIds]);
      setIsError(false);
      setMessage('Filters saved.');
      onSaved?.();
    } catch (err) {
      setIsError(true);
      setMessage(err instanceof Error ? err.message : 'Could not save filters.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <form
      onSubmit={handleSave}
      className="flex flex-col gap-5 rounded-lg border border-hairline bg-surface p-5"
      aria-label="Custom filters"
    >
      <div className="flex flex-col gap-2">
        <p className="text-xs uppercase tracking-widest text-muted">Categories</p>
        {categories.length === 0 ? (
          <p className="text-xs text-muted">No categories yet.</p>
        ) : (
          <div className="flex flex-col gap-2">
            {categories.map((category) => (
              <label key={category} className="flex items-center gap-2 text-sm text-ink">
                <input
                  type="checkbox"
                  checked={selectedCategories.has(category)}
                  onChange={() => toggleCategory(category)}
                />
                <span>{category}</span>
              </label>
            ))}
          </div>
        )}
      </div>

      <div className="flex flex-col gap-2">
        <p className="text-xs uppercase tracking-widest text-muted">Companies</p>
        <input
          type="text"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter by name or ticker"
          aria-label="Filter companies"
          className="rounded-lg border border-hairline bg-page px-3 py-2 text-ink outline-none focus:border-muted"
        />
        <div className="flex max-h-64 flex-col gap-2 overflow-y-auto">
          {filteredCompanies.map((company) => (
            <label key={company.id} className="flex items-center gap-2 text-sm text-ink">
              <input
                type="checkbox"
                checked={selectedCompanyIds.has(company.id)}
                onChange={() => toggleCompany(company.id)}
              />
              <span>{company.name}</span>
              <span className="text-xs text-muted">{company.ticker}</span>
            </label>
          ))}
        </div>
      </div>

      {message && (
        <p role="alert" className={`text-xs ${isError ? 'text-bearish' : 'text-bullish'}`}>
          {message}
        </p>
      )}
      <button
        type="submit"
        disabled={saving}
        className="self-start rounded-lg border border-hairline bg-surface px-4 py-2 text-xs uppercase tracking-widest text-ink disabled:opacity-50"
      >
        {saving ? 'Saving…' : 'Save'}
      </button>
    </form>
  );
}
```

> Accessibility note: each company checkbox's accessible name is the concatenation of the name + ticker `<span>`s (RTL matches `getByLabelText(/Apple/)`), and the filter input is labeled via `aria-label="Filter companies"`.

- [ ] **Step 4: Run test to verify it passes**

Run (from `frontend/`): `npm run test -- src/components/WatchlistSettings.test.tsx`
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/WatchlistSettings.tsx frontend/src/components/WatchlistSettings.test.tsx
git commit -m "feat: add WatchlistSettings inline custom-filter editor"
```

---

## Task 13: Update Existing Fixtures for the New `market` Field

**Files:**
- Modify: `frontend/src/components/AlertCard.test.tsx`
- Modify: `frontend/src/components/CompanyChip.test.tsx`
- Modify: `frontend/src/components/ReasoningPanel.test.tsx`
- Modify: `frontend/src/lib/useAlertsSocket.test.tsx`

**Interfaces:**
- Consumes: the updated `AlertCompany`/`WsAlertCompany` types (Task 9). No production code changes — this task adds the now-required `market` field to the four existing test fixtures that build `AlertCompany`/`WsAlertCompany` literals, so the full suite type-checks again. This is a focused, mechanical task split out so a reviewer can verify "existing tests still green" independently of the new feature wiring in Task 14.

- [ ] **Step 1: Add `market` to each fixture**

In `frontend/src/components/ReasoningPanel.test.tsx`, in the `const base: AlertCompany = {...}` literal, add `market: 'IN',` before `in_my_holdings: false,`.

In `frontend/src/components/CompanyChip.test.tsx`, in the `const company: AlertCompany = {...}` literal, add `market: 'IN',` before `in_my_holdings: false,`.

In `frontend/src/components/AlertCard.test.tsx`, add `market: 'IN',` to the first company object (`RELIANCE.NS`) and `market: 'IN',` to the second (`ONGC.NS`) — both before their respective `in_my_holdings` fields. (Both companies are `.NS` Indian tickers, so `market: 'IN'` is correct.)

In `frontend/src/lib/useAlertsSocket.test.tsx`, in `makeWsAlert`'s company object (type `WsAlertCompany`, which now includes `market`), add `market: 'IN',` after `basis: 'direct_mention', confidence: 'llm_estimate',`.

- [ ] **Step 2: Run the affected suites to verify they pass**

Run (from `frontend/`): `npm run test -- src/components/AlertCard.test.tsx src/components/CompanyChip.test.tsx src/components/ReasoningPanel.test.tsx src/lib/useAlertsSocket.test.tsx`
Expected: all pass (same counts as Plan 4: 4 AlertCard + 4 CompanyChip + 3 ReasoningPanel + 3 useAlertsSocket), now type-checking cleanly with the `market` field present.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/AlertCard.test.tsx frontend/src/components/CompanyChip.test.tsx frontend/src/components/ReasoningPanel.test.tsx frontend/src/lib/useAlertsSocket.test.tsx
git commit -m "test: add required market field to existing AlertCompany fixtures"
```

---

## Task 14: Wire Tabs into `FeedPage`/`Feed` + Final Full-App Verification

**Files:**
- Modify: `frontend/src/components/Feed.tsx`
- Modify: `frontend/src/pages/FeedPage.tsx`
- Modify: `frontend/src/components/Feed.test.tsx`
- Create: `frontend/src/pages/FeedPage.test.tsx`

**Interfaces:**
- Consumes: `getAlerts`, `getWatchlist`, `Alert`, `Watchlist` types (Task 9), `useAuth()` (Plan 4), `useAlertsSocket` (Plan 4), `alertMatchesMarket`/`alertMatchesWatchlist` (Task 11), `FeedTabs` + `FeedTab` (Task 10), `WatchlistSettings` (Task 12), `AlertCard` (Plan 4).
- Produces: `Feed` gains an `activeTab: FeedTab` prop and filters the merged alert list per the active tab (India/Global via market, Custom via watchlist), fetching the user's watchlist only when `activeTab === 'custom'` and authenticated, rendering the inline `WatchlistSettings` and the two distinct Custom empty states (not-logged-in vs. empty-watchlist). `FeedPage` owns the `activeTab` state and renders `<FeedTabs>` above `<Feed>`. `mergeAlerts` is unchanged. Leaf of the plan.

- [ ] **Step 1: Rewrite the Feed test and add the FeedPage test**

Replace the entire contents of `frontend/src/components/Feed.test.tsx` with:

```tsx
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ReactElement } from 'react';
import Feed, { mergeAlerts } from './Feed';
import { AuthProvider } from '../lib/auth';
import * as api from '../lib/api';
import type { Alert, AlertCompany } from '../lib/api';

// Isolate Feed from the real socket in these tests.
vi.mock('../lib/useAlertsSocket', () => ({ useAlertsSocket: () => [] }));

function company(overrides: Partial<AlertCompany>): AlertCompany {
  return {
    company_id: 1,
    ticker: 'RELIANCE.NS',
    name: 'Reliance',
    index_tier: 'NIFTY50',
    direction: 'bullish',
    magnitude_low: 1,
    magnitude_high: 2,
    rationale: 'x',
    basis: 'direct_mention',
    confidence: 'llm_estimate',
    market: 'IN',
    in_my_holdings: false,
    ...overrides,
  };
}

function makeAlert(id: number, title: string, companies: AlertCompany[], category = 'oil_energy'): Alert {
  return {
    id,
    category,
    created_at: '2026-07-10T10:00:00+00:00',
    article: { id, title, url: `https://example.com/${id}` },
    companies,
  };
}

function renderFeed(ui: ReactElement) {
  return render(
    <MemoryRouter>
      <AuthProvider>{ui}</AuthProvider>
    </MemoryRouter>,
  );
}

function setToken() {
  localStorage.setItem('newsflo.token', 'tok');
  localStorage.setItem('newsflo.email', 'a@example.com');
}

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe('mergeAlerts', () => {
  it('prepends live alerts and dedupes by id (fetched data wins on collision)', () => {
    const merged = mergeAlerts([makeAlert(2, 'two-live', [])], [makeAlert(1, 'one', []), makeAlert(2, 'two', [])]);
    expect(merged.map((a) => a.id)).toEqual([2, 1]);
    expect(merged[0].article.title).toBe('two');
  });
});

describe('Feed tabs', () => {
  const indiaAlert = makeAlert(1, 'India oil headline', [company({ market: 'IN' })]);
  const globalAlert = makeAlert(2, 'Global tech headline', [
    company({ company_id: 2, ticker: 'AAPL', name: 'Apple', market: 'GLOBAL' }),
  ], 'it');

  it('India tab shows only IN-market alerts', async () => {
    vi.spyOn(api, 'getAlerts').mockResolvedValue([indiaAlert, globalAlert]);
    renderFeed(<Feed activeTab="india" />);
    expect(await screen.findByText('India oil headline')).toBeInTheDocument();
    expect(screen.queryByText('Global tech headline')).not.toBeInTheDocument();
  });

  it('Global tab shows only GLOBAL-market alerts', async () => {
    vi.spyOn(api, 'getAlerts').mockResolvedValue([indiaAlert, globalAlert]);
    renderFeed(<Feed activeTab="global" />);
    expect(await screen.findByText('Global tech headline')).toBeInTheDocument();
    expect(screen.queryByText('India oil headline')).not.toBeInTheDocument();
  });

  it('Custom tab shows a login prompt when logged out', async () => {
    vi.spyOn(api, 'getAlerts').mockResolvedValue([indiaAlert]);
    renderFeed(<Feed activeTab="custom" />);
    expect(await screen.findByText(/log in to build your custom feed/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /log in/i })).toBeInTheDocument();
  });

  it('Custom tab shows a configure prompt when logged in with an empty watchlist', async () => {
    setToken();
    vi.spyOn(api, 'getAlerts').mockResolvedValue([indiaAlert]);
    vi.spyOn(api, 'getWatchlist').mockResolvedValue({ categories: [], companies: [] });
    vi.spyOn(api, 'getCategories').mockResolvedValue([]);
    vi.spyOn(api, 'getCompanies').mockResolvedValue([]);
    renderFeed(<Feed activeTab="custom" />);
    expect(await screen.findByText(/choose categories or companies/i)).toBeInTheDocument();
    // The inline editor is present on the Custom tab.
    expect(screen.getByRole('button', { name: /save/i })).toBeInTheDocument();
  });

  it('Custom tab shows watchlist-matched alerts when configured', async () => {
    setToken();
    vi.spyOn(api, 'getAlerts').mockResolvedValue([indiaAlert, globalAlert]);
    vi.spyOn(api, 'getWatchlist').mockResolvedValue({ categories: ['oil_energy'], companies: [] });
    vi.spyOn(api, 'getCategories').mockResolvedValue(['oil_energy']);
    vi.spyOn(api, 'getCompanies').mockResolvedValue([]);
    renderFeed(<Feed activeTab="custom" />);
    await waitFor(() => expect(screen.getByText('India oil headline')).toBeInTheDocument());
    expect(screen.queryByText('Global tech headline')).not.toBeInTheDocument();
  });
});
```

`frontend/src/pages/FeedPage.test.tsx` (new file):

```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import FeedPage from './FeedPage';
import { AuthProvider } from '../lib/auth';
import * as api from '../lib/api';
import type { Alert, AlertCompany } from '../lib/api';

vi.mock('../lib/useAlertsSocket', () => ({ useAlertsSocket: () => [] }));

function company(overrides: Partial<AlertCompany>): AlertCompany {
  return {
    company_id: 1,
    ticker: 'RELIANCE.NS',
    name: 'Reliance',
    index_tier: 'NIFTY50',
    direction: 'bullish',
    magnitude_low: 1,
    magnitude_high: 2,
    rationale: 'x',
    basis: 'direct_mention',
    confidence: 'llm_estimate',
    market: 'IN',
    in_my_holdings: false,
    ...overrides,
  };
}

function makeAlert(id: number, title: string, companies: AlertCompany[]): Alert {
  return {
    id,
    category: 'oil_energy',
    created_at: '2026-07-10T10:00:00+00:00',
    article: { id, title, url: `https://example.com/${id}` },
    companies,
  };
}

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe('FeedPage', () => {
  it('defaults to the India tab and switches to Global on click', async () => {
    const indiaAlert = makeAlert(1, 'India oil headline', [company({ market: 'IN' })]);
    const globalAlert = makeAlert(2, 'Global tech headline', [
      company({ company_id: 2, ticker: 'AAPL', name: 'Apple', market: 'GLOBAL' }),
    ]);
    vi.spyOn(api, 'getAlerts').mockResolvedValue([indiaAlert, globalAlert]);

    render(
      <MemoryRouter>
        <AuthProvider>
          <FeedPage />
        </AuthProvider>
      </MemoryRouter>,
    );

    // India tab is active by default.
    expect(await screen.findByText('India oil headline')).toBeInTheDocument();
    expect(screen.queryByText('Global tech headline')).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('tab', { name: /global/i }));
    expect(await screen.findByText('Global tech headline')).toBeInTheDocument();
    expect(screen.queryByText('India oil headline')).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `frontend/`): `npm run test -- src/components/Feed.test.tsx src/pages/FeedPage.test.tsx`
Expected: FAIL — `Feed` does not accept an `activeTab` prop yet, and the Custom-tab/tab-switching behavior is not implemented.

- [ ] **Step 3: Update `Feed` and `FeedPage`**

Replace the entire contents of `frontend/src/components/Feed.tsx` with:

```tsx
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { getAlerts, getWatchlist, type Alert, type Watchlist } from '../lib/api';
import { useAuth } from '../lib/auth';
import { useAlertsSocket } from '../lib/useAlertsSocket';
import { alertMatchesMarket, alertMatchesWatchlist } from '../lib/feedFilters';
import AlertCard from './AlertCard';
import WatchlistSettings from './WatchlistSettings';
import type { FeedTab } from './FeedTabs';

// Prepend live pushes ahead of the fetched list, deduping by id. On an id
// collision the `fetched` copy's data wins: REST-fetched alerts carry the
// accurate per-viewer `in_my_holdings` flag, while live WS-pushed payloads
// always report `in_my_holdings: false` (the pipeline has no per-viewer
// context at broadcast time). Live entries only contribute brand-new ids
// (and their own data) that aren't yet present in `fetched`, so a fresh
// push still appears immediately at the top of the feed.
export function mergeAlerts(live: Alert[], fetched: Alert[]): Alert[] {
  const fetchedById = new Map(fetched.map((alert) => [alert.id, alert]));
  const seen = new Set<number>();
  const merged: Alert[] = [];
  for (const alert of [...live, ...fetched]) {
    if (seen.has(alert.id)) continue;
    seen.add(alert.id);
    merged.push(fetchedById.get(alert.id) ?? alert);
  }
  return merged;
}

const EMPTY_WATCHLIST: Watchlist = { categories: [], companies: [] };

export default function Feed({ activeTab }: { activeTab: FeedTab }) {
  const { token } = useAuth();
  const [fetched, setFetched] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [watchlist, setWatchlist] = useState<Watchlist>(EMPTY_WATCHLIST);
  const live = useAlertsSocket();

  useEffect(() => {
    let active = true;
    setLoading(true);
    getAlerts(token)
      .then((data) => {
        if (active) {
          setFetched(data);
          setError(null);
        }
      })
      .catch((err: unknown) => {
        if (active) setError(err instanceof Error ? err.message : 'Failed to load alerts.');
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [token]);

  // Only fetch the watchlist for the Custom tab, and only when authenticated.
  const refreshWatchlist = useCallback(() => {
    if (!token) return;
    getWatchlist(token)
      .then(setWatchlist)
      .catch(() => setWatchlist(EMPTY_WATCHLIST));
  }, [token]);

  useEffect(() => {
    if (activeTab === 'custom' && token) {
      refreshWatchlist();
    }
  }, [activeTab, token, refreshWatchlist]);

  const alerts = useMemo(() => mergeAlerts(live, fetched), [live, fetched]);

  const visibleAlerts = useMemo(() => {
    if (activeTab === 'india') return alerts.filter((a) => alertMatchesMarket(a, 'IN'));
    if (activeTab === 'global') return alerts.filter((a) => alertMatchesMarket(a, 'GLOBAL'));
    return alerts.filter((a) => alertMatchesWatchlist(a, watchlist));
  }, [alerts, activeTab, watchlist]);

  if (loading) {
    return <p className="text-xs uppercase tracking-widest text-muted">Loading…</p>;
  }
  if (error) {
    return <p className="text-xs uppercase tracking-widest text-bearish">{error}</p>;
  }

  const cardList = (
    <div className="flex flex-col gap-5">
      {visibleAlerts.map((alert) => (
        <AlertCard key={alert.id} alert={alert} isAuthenticated={token !== null} />
      ))}
    </div>
  );

  if (activeTab === 'custom') {
    if (!token) {
      return (
        <p className="text-xs uppercase tracking-widest text-muted">
          Log in to build your custom feed.{' '}
          <Link to="/login" className="text-ink underline">
            Log in
          </Link>
        </p>
      );
    }
    const configured = watchlist.categories.length > 0 || watchlist.companies.length > 0;
    return (
      <div className="flex flex-col gap-6">
        <WatchlistSettings onSaved={refreshWatchlist} />
        {!configured ? (
          <p className="text-xs uppercase tracking-widest text-muted">
            Choose categories or companies above to build your custom feed.
          </p>
        ) : visibleAlerts.length === 0 ? (
          <p className="text-xs uppercase tracking-widest text-muted">
            No alerts match your custom filters yet.
          </p>
        ) : (
          cardList
        )}
      </div>
    );
  }

  if (visibleAlerts.length === 0) {
    return (
      <p className="text-xs uppercase tracking-widest text-muted">
        No {activeTab === 'india' ? 'India' : 'Global'} alerts yet. New stories will appear here live.
      </p>
    );
  }
  return cardList;
}
```

Replace the entire contents of `frontend/src/pages/FeedPage.tsx` with:

```tsx
import { useState } from 'react';
import Feed from '../components/Feed';
import FeedTabs, { type FeedTab } from '../components/FeedTabs';

export default function FeedPage() {
  const [tab, setTab] = useState<FeedTab>('india');
  return (
    <main className="mx-auto max-w-feed px-4 py-8">
      <FeedTabs active={tab} onChange={setTab} />
      <Feed activeTab={tab} />
    </main>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run (from `frontend/`): `npm run test -- src/components/Feed.test.tsx src/pages/FeedPage.test.tsx`
Expected: `6 passed` (1 mergeAlerts + 5 Feed tabs) + `1 passed` (FeedPage).

- [ ] **Step 5: Run the full frontend suite and typecheck**

Run (from `frontend/`): `npm run test`
Expected: every frontend test passes (all Plan 4 suites plus Tasks 9-14).

Run (from `frontend/`): `npm run build`
Expected: `tsc --noEmit` passes with no `any`/type errors, and `vite build` succeeds.

- [ ] **Step 6: Run the full backend suite**

Run: `cd backend && .venv/Scripts/pytest tests/ -v`
Expected: every backend test passes.

- [ ] **Step 7: Manual full-app verification (real data, all three tabs)**

Load real Indian index data and the global seed, then click through the app.

1. **Download the NSE index CSVs** (into `backend/`):

```bash
cd backend
curl -o ind_nifty50list.csv https://archives.nseindia.com/content/indices/ind_nifty50list.csv
curl -o ind_nifty100list.csv https://archives.nseindia.com/content/indices/ind_nifty100list.csv
curl -o ind_nifty500list.csv https://archives.nseindia.com/content/indices/ind_nifty500list.csv
```

2. **Load Indian companies + global seed** into the dev DB (order matters: broadest tier last so `index_tier` reflects the most inclusive membership; global seed is independent):

```bash
cd backend
.venv/Scripts/python -c "from app.db import SessionLocal, init_db; from app.companies.loader import load_companies_from_csv; from app.companies.global_seed import load_global_companies; init_db(); s=SessionLocal(); print('nifty50', load_companies_from_csv(s, 'ind_nifty50list.csv', 'NIFTY50')); print('nifty100', load_companies_from_csv(s, 'ind_nifty100list.csv', 'NIFTY100')); print('nifty500', load_companies_from_csv(s, 'ind_nifty500list.csv', 'NIFTY500')); print('global', load_global_companies(s)); s.close()"
```

Expected: prints non-zero counts for each Nifty tier and `global 50`.

3. **Start both servers** (two terminals):

```bash
cd backend && .venv/Scripts/uvicorn app.main:app --reload
```

```bash
cd frontend && npm run dev
```

4. **Seed a couple of alerts** so the tabs have content — either run the pipeline against real RSS with a real `ANTHROPIC_API_KEY` set, or insert a fake analyzed alert for one Indian and one global company via a Python shell (`process_new_articles` with a monkeypatched analysis, mirroring the e2e test). Confirm `GET http://127.0.0.1:8000/api/alerts` returns entries whose companies include a `"market"` field.

5. **Open** `http://127.0.0.1:5173/` and verify:
   - **India tab** (default): shows only alerts with at least one `.NS`/`.BO` company. Screenshot.
   - **Global tab**: shows only alerts with at least one non-`.NS` company. Screenshot.
   - **Custom tab, logged out**: shows the "Log in to build your custom feed" prompt with a working `/login` link. Screenshot.
   - Register a user (`/register`), return to **Custom tab**: the `WatchlistSettings` editor renders category checkboxes (from `GET /api/categories`) and a filterable company list (from `GET /api/companies`). With nothing selected, the "Choose categories or companies…" prompt shows. Screenshot.
   - Select one category and one company, click **Save** (success message appears), and confirm the alert list now shows only the matching alerts. Reload the page and re-open the Custom tab — the selection persists (proving backend persistence). Screenshot.

6. Confirm no console errors and no horizontal page scroll at mobile width.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/Feed.tsx frontend/src/pages/FeedPage.tsx frontend/src/components/Feed.test.tsx frontend/src/pages/FeedPage.test.tsx
git commit -m "feat: wire India/Global/Custom feed tabs into FeedPage and Feed"
```

---

## Definition of Done (Plan 5)

- `cd backend && .venv/Scripts/pytest tests/ -v` passes fully (Tasks 1-8 plus every Plan 1-4 test), with zero live network calls.
- `cd frontend && npm run test` passes fully (Tasks 9-14 plus every Plan 4 suite), and `npm run build` (`tsc --noEmit && vite build`) succeeds with no `any` and no type errors.
- A human can load real Indian index data and the global seed:
  - Download `https://archives.nseindia.com/content/indices/ind_nifty50list.csv`, `ind_nifty100list.csv`, and `ind_nifty500list.csv`.
  - Run the documented one-liner invoking `load_companies_from_csv(...)` for each Nifty tier and `load_global_companies(session)` for the ~50 global companies.
- With both dev servers running and a few alerts seeded, the dashboard shows three working tabs:
  - **India** — only alerts with at least one `.NS`/`.BO` company.
  - **Global** — only alerts with at least one non-`.NS` company.
  - **Custom** — logged-out login prompt; logged-in inline `WatchlistSettings` editor with dynamic categories (`GET /api/categories`) and a filterable company list (`GET /api/companies`); an empty watchlist shows the configure prompt (never the unfiltered feed); saving a selection filters the feed and persists across reloads via `PUT`/`GET /api/watchlist`.
- No schema migration was required: `market` is computed from the ticker at read time on both `GET /api/alerts` and the WebSocket broadcast, and the two new watchlist tables are created by the existing `init_db()` on a fresh schema.
- This plan deliberately excludes: any change to `resolve_companies` (the `GLOBAL_LARGE_CAP` tier falls through the existing `else_=3` rank), live global market data (the global list is a curated static seed), and any per-card behavior (the existing Predicted / My Demat per-card tabs are untouched — the India/Global/Custom tabs are a separate page-level control over which cards appear).
```