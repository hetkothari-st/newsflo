# NewsFlo WebSocket Live Push & CRED-Style React Dashboard Implementation Plan (Plan 4 of 4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Push newly-analyzed alerts to connected clients live over a WebSocket, and build the CRED-inspired React/TypeScript dashboard (feed, holdings, auth) that consumes the existing backend API and the new live-push socket — completing the v1 spec's "API + WebSocket layer" (module #9) and "UI / UX Design" sections.

**Architecture:** Part A extends the Plan 1-3 FastAPI modular monolith with a new `app.ws` package: a thread-safe `ConnectionManager` singleton whose captured event loop lets the synchronous pipeline fire an async broadcast, a `/ws/alerts` WebSocket endpoint, and a one-line broadcast hook at the end of the pipeline loop. Part B creates a brand-new `frontend/` directory (sibling to `backend/`) — a React 18 + TypeScript + Vite + Tailwind app with React Router, built test-first with Vitest + React Testing Library. The frontend fetches `GET /api/alerts` on load and merges live WebSocket pushes into the same feed.

**Tech Stack:** Backend — Python 3.11+, FastAPI/Starlette WebSockets, `websockets` (ASGI WS server), `pytest`. Frontend — React 18, TypeScript 5, Vite 5, Tailwind CSS 3, React Router 6, Vitest 2, React Testing Library, jsdom.

## Global Constraints

These carry forward verbatim from Plans 1-3 and remain binding for all Part A (backend) tasks:

- Database schema must stay portable between SQLite (tests) and PostgreSQL (production) — no native Postgres-only column types (no `ENUM`, no `ARRAY`); enums are plain `String` columns validated in Python.
- No live network calls in any test — news fetching, Claude API calls, price lookups (yfinance), and email sending are always mocked/monkeypatched or routed through the console backend. Never any real HTTP call to Resend/SendGrid; the console email backend is what every test exercises by default (no `RESEND_API_KEY` set in the test environment).
- News sources for v1 are free RSS/APIs only (per spec) — no paid data sources.
- Market focus is Indian stocks (NSE/BSE) for v1 — tickers use `.NS` suffix.
- Claude structured output must go through forced tool-use (a `record_analysis` tool), never free-text JSON parsing.
- Company sector values are constrained to a fixed taxonomy (`oil_gas`, `banking`, `auto`, `it`, `pharma`, `fmcg`, `metals`, `telecom`, `infra`, `other`) so sector-based company resolution is an exact match, not fuzzy text matching.
- The outcome-tracker scheduler must never start automatically during tests or default `uvicorn app.main:app` runs — it is strictly opt-in via `ENABLE_SCHEDULER=true`.
- Calibration blending uses **population** standard deviation (`statistics.pstdev`).
- Passwords are never stored or logged in plaintext — only `bcrypt` hashes are persisted.
- The JWT secret key comes from `Settings.jwt_secret_key` (env `JWT_SECRET_KEY`), never hardcoded inline in a route handler.
- No live broker API integration — holdings are manual entry / CSV upload only.
- One commit per task, at the end of that task's steps.

Additional constraints introduced by this plan:

- **WebSocket broadcast failures for one connection must never crash the broadcast to others** — a failed `send_json` for one connection is caught and that connection is dropped; the loop continues to every remaining connection.
- **`manager.broadcast_sync` must be a safe no-op when the app hasn't started** (no captured event loop) **or has no active connections** — pipeline code must never crash because nobody is listening. This is what keeps every existing Plan 1-3 pipeline/e2e test green without a running server.
- **Frontend: no inline `style={{...}}`** for anything expressible via the Tailwind config's design tokens. The exact colors/fonts/spacing/radii from the spec are registered as named tokens in `tailwind.config.ts` (`bg-page`, `text-ink`, `border-hairline`, `text-bullish`, `bg-swatch-oil_energy`, `font-display`, `max-w-feed`, etc.) and referenced by name everywhere. Where a value genuinely cannot be a named token, use Tailwind arbitrary-value syntax (`border-[1.5px]`) consistently.
- **Frontend: no `any` in TypeScript** — every API response has a typed interface matching the backend's exact JSON field names. The single source of truth for these shapes is `src/lib/api.ts`; every component imports its types from there.
- **Frontend components must be keyboard-accessible where interactive** — chips/cards that expand on click also respond to Enter/Space when focused (`role="button"`, `tabIndex={0}`, `onKeyDown`), and any transition respects `prefers-reduced-motion` (use Tailwind's `motion-safe:` variant; keep motion subtle per the spec's "color used sparingly" restraint).
- **Design direction is already approved** (spec's "UI / UX Design" section, final version "v9") — this plan is faithful execution of a pinned design, not fresh creative exploration.

---

# Part A — Backend: WebSocket Live Push (spec module #9)

## Task 1: ConnectionManager

**Files:**
- Create: `backend/app/ws/__init__.py`
- Create: `backend/app/ws/manager.py`
- Test: `backend/tests/test_ws_manager.py`

**Interfaces:**
- Consumes: `fastapi.WebSocket` (type hint only).
- Produces: `ConnectionManager` class and a module-level singleton `manager` (`app.ws.manager`) with `active_connections: list[WebSocket]`, `loop: asyncio.AbstractEventLoop | None`, `async connect(websocket)`, `disconnect(websocket)`, `async broadcast(message: dict)`, and `broadcast_sync(message: dict)`. Task 2 (endpoint) imports `manager` and calls `connect`/`disconnect`; Task 2 (`main.py`) sets `manager.loop`; Task 3 (pipeline) calls `broadcast_sync`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_ws_manager.py`:

```python
import asyncio

from app.ws.manager import ConnectionManager


class FakeWebSocket:
    """Minimal stand-in for starlette.WebSocket — records accept/send calls."""

    def __init__(self, fail_on_send: bool = False):
        self.accepted = False
        self.sent: list = []
        self.fail_on_send = fail_on_send

    async def accept(self):
        self.accepted = True

    async def send_json(self, message):
        if self.fail_on_send:
            raise RuntimeError("connection gone")
        self.sent.append(message)


def test_connect_accepts_and_registers():
    manager = ConnectionManager()
    ws = FakeWebSocket()

    asyncio.run(manager.connect(ws))

    assert ws.accepted is True
    assert ws in manager.active_connections


def test_disconnect_removes_connection():
    manager = ConnectionManager()
    ws = FakeWebSocket()
    asyncio.run(manager.connect(ws))

    manager.disconnect(ws)

    assert ws not in manager.active_connections


def test_disconnect_is_safe_when_not_present():
    manager = ConnectionManager()
    ws = FakeWebSocket()

    # Never connected — must not raise.
    manager.disconnect(ws)

    assert ws not in manager.active_connections


def test_broadcast_sends_to_all_connections():
    manager = ConnectionManager()
    a, b = FakeWebSocket(), FakeWebSocket()
    asyncio.run(manager.connect(a))
    asyncio.run(manager.connect(b))

    asyncio.run(manager.broadcast({"hello": "world"}))

    assert a.sent == [{"hello": "world"}]
    assert b.sent == [{"hello": "world"}]


def test_broadcast_drops_failed_connection_and_continues():
    manager = ConnectionManager()
    good, bad = FakeWebSocket(), FakeWebSocket(fail_on_send=True)
    asyncio.run(manager.connect(good))
    asyncio.run(manager.connect(bad))

    asyncio.run(manager.broadcast({"x": 1}))

    assert good.sent == [{"x": 1}]        # the healthy one still received it
    assert bad not in manager.active_connections  # the dead one was dropped
    assert good in manager.active_connections


def test_broadcast_sync_is_noop_without_loop():
    manager = ConnectionManager()

    # No captured loop and no connections — must return silently, never raise.
    manager.broadcast_sync({"x": 1})


def test_broadcast_sync_is_noop_without_connections():
    manager = ConnectionManager()
    loop = asyncio.new_event_loop()
    manager.loop = loop

    # Loop set but no connections -> still a no-op, no crash.
    manager.broadcast_sync({"x": 1})

    loop.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/pytest tests/test_ws_manager.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.ws'`.

- [ ] **Step 3: Implement the ConnectionManager**

`backend/app/ws/__init__.py`: empty file.

`backend/app/ws/manager.py`:

```python
import asyncio

from fastapi import WebSocket


class ConnectionManager:
    """Tracks live dashboard WebSocket connections and fans out alert pushes.

    ``loop`` is captured from ``main.py``'s startup event. It is what lets the
    synchronous pipeline (which runs in a worker thread, not the event loop)
    schedule an async broadcast via ``broadcast_sync`` -> ``run_coroutine_threadsafe``.
    """

    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []
        self.loop: asyncio.AbstractEventLoop | None = None

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        # Idempotent — never raise if the connection was already removed.
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict) -> None:
        # Iterate a COPY: a failed send drops the connection mid-loop, which
        # must not mutate the list we are iterating.
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                # One dead connection must not stop the broadcast to the others.
                self.disconnect(connection)

    def broadcast_sync(self, message: dict) -> None:
        """Entrypoint the synchronous pipeline calls. Fire-and-forget.

        No-op if the app hasn't started (no captured loop) or nobody is
        connected — so headless pipeline runs and tests never crash because
        there is nothing to broadcast to.
        """
        if self.loop is None or not self.active_connections:
            return
        asyncio.run_coroutine_threadsafe(self.broadcast(message), self.loop)


manager = ConnectionManager()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/pytest tests/test_ws_manager.py -v`
Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/app/ws/__init__.py backend/app/ws/manager.py backend/tests/test_ws_manager.py
git commit -m "feat: add ConnectionManager for WebSocket alert fan-out"
```

---

## Task 2: WebSocket Endpoint & App Wiring

**Files:**
- Modify: `backend/requirements.txt`
- Create: `backend/app/routers/ws.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_ws_endpoint.py`

**Interfaces:**
- Consumes: `manager` (`app.ws.manager`, Task 1), existing `main.py` wiring (Plans 1-3).
- Produces: `router` (`app.routers.ws`) exposing `WS /ws/alerts`; `main.py` now sets `manager.loop` on startup and includes `ws.router`. Task 3 (pipeline) relies on `manager.loop` being set when the app is running, so its live-push e2e test can receive a broadcast.

- [ ] **Step 1: Add the `websockets` dependency**

Replace the entire contents of `backend/requirements.txt` with:

```
fastapi
uvicorn
sqlalchemy
pydantic
pydantic-settings
anthropic
feedparser
httpx
pytest
yfinance
pandas
apscheduler
bcrypt
PyJWT
python-multipart
email-validator
websockets
```

Install into the existing venv (needed so `uvicorn` can serve the WebSocket route for the manual demo; Starlette's `TestClient.websocket_connect` itself works over the in-process ASGI transport):

```bash
cd backend
.venv/Scripts/pip install -r requirements.txt
```

- [ ] **Step 2: Write the failing test**

`backend/tests/test_ws_endpoint.py`:

```python
from fastapi.testclient import TestClient

from app.main import app
from app.ws.manager import manager


def test_websocket_connect_registers_then_unregisters_on_close():
    client = TestClient(app)

    with client.websocket_connect("/ws/alerts"):
        assert len(manager.active_connections) == 1

    # Leaving the context closes the socket -> handler catches
    # WebSocketDisconnect -> the connection is unregistered.
    assert len(manager.active_connections) == 0


def test_startup_event_captures_running_loop():
    # Entering the TestClient context runs the ASGI lifespan, firing the
    # startup event, which captures the portal's running loop for threadsafe
    # broadcasts.
    with TestClient(app):
        assert manager.loop is not None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/pytest tests/test_ws_endpoint.py -v`
Expected: FAIL — `/ws/alerts` is not registered yet, so `websocket_connect` raises (and `manager.loop` is `None`).

- [ ] **Step 4: Implement the endpoint and wire it in**

`backend/app/routers/ws.py`:

```python
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.ws.manager import manager

router = APIRouter()


@router.websocket("/ws/alerts")
async def alerts_websocket(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        # The client never needs to send anything; this just parks the
        # coroutine so a client-initiated close raises WebSocketDisconnect.
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
```

Replace the entire contents of `backend/app/main.py` with:

```python
import asyncio
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.db import init_db
from app.routers import alerts, articles, auth, holdings, ws
from app.scheduler import start_scheduler
from app.ws.manager import manager

app = FastAPI(title="NewsFlo")

app.include_router(articles.router)
app.include_router(alerts.router)
app.include_router(auth.router)
app.include_router(holdings.router)
app.include_router(ws.router)

init_db()

if settings.enable_scheduler:
    start_scheduler()


@app.on_event("startup")
async def _capture_event_loop() -> None:
    # Capture the running loop so the synchronous pipeline can schedule async
    # broadcasts onto it from a worker thread via run_coroutine_threadsafe.
    manager.loop = asyncio.get_running_loop()


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && .venv/Scripts/pytest tests/test_ws_endpoint.py -v`
Expected: `2 passed`

- [ ] **Step 6: Commit**

```bash
git add backend/requirements.txt backend/app/routers/ws.py backend/app/main.py backend/tests/test_ws_endpoint.py
git commit -m "feat: add /ws/alerts WebSocket endpoint and capture the event loop"
```

---

## Task 3: Broadcast New Alerts From the Pipeline

**Files:**
- Modify: `backend/app/pipeline.py`
- Test: `backend/tests/test_ws_endpoint.py`

**Interfaces:**
- Consumes: `manager` (Task 1), everything the pipeline already consumes (Plans 1-3).
- Produces: unchanged `process_new_articles(session, claude_client) -> int` signature, but after each alert is committed and email notifications fan out, it broadcasts one live-push payload (shaped like a single `GET /api/alerts` entry, minus `in_my_holdings`). No later backend task depends on this; Part B's `useAlertsSocket` consumes the payload shape.

- [ ] **Step 1: Add the live-push e2e test**

Append the following test to `backend/tests/test_ws_endpoint.py` (keep the two existing tests; add these imports at the top of the file and the new test at the bottom):

```python
import app.pipeline as pipeline_module
from app.analysis.schemas import AnalysisOutput, CompanyMention
from app.models import Article, Company
from app.pipeline import process_new_articles
from app.routers.articles import get_db


def test_pipeline_broadcasts_new_alert_to_connected_client(db_session, monkeypatch):
    app.dependency_overrides[get_db] = lambda: db_session

    db_session.add(Company(
        ticker="RELIANCE.NS", name="Reliance Industries",
        sector="oil_gas", index_tier="NIFTY50", market_cap=1_800_000.0,
    ))
    db_session.commit()
    db_session.add(Article(
        source="test", url="https://example.com/ws-live",
        title="US strikes Iran oil export sites", content="crude oil markets react",
    ))
    db_session.commit()

    fake_output = AnalysisOutput(
        category="oil_energy",
        companies=[CompanyMention(
            name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
            direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin up",
        )],
    )
    monkeypatch.setattr(pipeline_module, "analyze_article", lambda client, title, content: fake_output)

    # Entering the TestClient context runs startup (captures manager.loop);
    # the nested websocket_connect registers a live client.
    with TestClient(app) as client:
        with client.websocket_connect("/ws/alerts") as websocket:
            created = process_new_articles(db_session, claude_client=object())
            assert created == 1
            payload = websocket.receive_json()

    assert payload["article"]["title"] == "US strikes Iran oil export sites"
    assert payload["category"] == "oil_energy"
    assert payload["companies"][0]["ticker"] == "RELIANCE.NS"
    assert payload["companies"][0]["direction"] == "bullish"
    assert payload["companies"][0]["confidence"] == "llm_estimate"
    # The pipeline has no per-viewer context at broadcast time, so the payload
    # intentionally omits in_my_holdings (the frontend defaults it to false).
    assert "in_my_holdings" not in payload["companies"][0]

    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/pytest tests/test_ws_endpoint.py::test_pipeline_broadcasts_new_alert_to_connected_client -v`
Expected: FAIL — the pipeline does not broadcast yet, so `websocket.receive_json()` blocks/times out (no message arrives).

- [ ] **Step 3: Wire the broadcast into the pipeline**

Replace the entire contents of `backend/app/pipeline.py` with:

```python
from sqlalchemy.orm import Session

from app.alerting.matcher import match_alert_to_holdings
from app.alerting.sender import send_pending_notifications
from app.analysis.claude_client import analyze_article
from app.calibration.blender import get_calibrated_magnitude
from app.companies.resolution import resolve_companies
from app.filtering.heuristic import filter_new_articles
from app.models import Alert, AlertCompany, Article
from app.ws.manager import manager


def _alert_broadcast_payload(alert: Alert) -> dict:
    """Shape one live-push payload identical to a single GET /api/alerts entry,
    MINUS the per-viewer ``in_my_holdings`` flag.

    Known simplification: the pipeline has no viewer context at broadcast time,
    so live-pushed companies carry no holdings-match. The frontend defaults
    live-pushed companies to ``in_my_holdings: false`` and the next full
    ``GET /api/alerts`` refresh reconciles them — correct-eventually, and
    simpler than threading per-user state through the broadcast.
    """
    return {
        "id": alert.id,
        "category": alert.category,
        "created_at": alert.created_at.isoformat(),
        "article": {
            "id": alert.article.id,
            "title": alert.article.title,
            "url": alert.article.url,
        },
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
        } for ac in alert.companies],
    }


def process_new_articles(session: Session, claude_client) -> int:
    filter_new_articles(session)

    alerts_created = 0
    pending = session.query(Article).filter_by(status="CATEGORIZED").all()

    for article in pending:
        analysis = None
        for _ in range(2):  # try once, retry once
            try:
                analysis = analyze_article(claude_client, article.title, article.content)
                break
            except Exception:
                continue

        if analysis is None:
            article.status = "ANALYSIS_FAILED"
            session.commit()
            continue

        resolved = resolve_companies(session, analysis.companies)

        alert = Alert(article_id=article.id, category=analysis.category)
        session.add(alert)
        session.flush()

        for entry in resolved:
            calibrated = get_calibrated_magnitude(
                session, category=analysis.category, company_id=entry["company_id"],
            )
            if calibrated is not None:
                low, high = calibrated
                entry["magnitude_low"] = low
                entry["magnitude_high"] = high
                entry["confidence"] = "calibrated"
            else:
                entry["confidence"] = "llm_estimate"
            session.add(AlertCompany(alert_id=alert.id, **entry))

        article.status = "ANALYZED"
        article.category = analysis.category
        session.commit()
        alerts_created += 1

        # Plan 3: fan out email alerts to any users holding an affected company.
        # With no matching holdings this is a no-op.
        new_notifications = match_alert_to_holdings(session, alert)
        send_pending_notifications(session, new_notifications)

        # Plan 4: push the new alert to every connected dashboard over WebSocket.
        # Safe no-op if the app hasn't started (no captured loop) or nobody is
        # connected — this never crashes headless pipeline runs or tests.
        manager.broadcast_sync(_alert_broadcast_payload(alert))

    return alerts_created
```

- [ ] **Step 4: Run the full backend suite**

Run: `cd backend && .venv/Scripts/pytest tests/ -v`
Expected: all tests pass — every Plan 1-3 test plus the three new WS tests. The Plan 3 pipeline/e2e tests still pass because `broadcast_sync` is a no-op when no client is connected (no captured loop / empty `active_connections`), so the added broadcast call has zero effect on them.

- [ ] **Step 5: Commit**

```bash
git add backend/app/pipeline.py backend/tests/test_ws_endpoint.py
git commit -m "feat: broadcast newly analyzed alerts to WebSocket clients"
```

---

# Part B — Frontend: CRED-Style React Dashboard (spec "UI / UX Design")

> All Part B tasks run from the new `frontend/` directory (sibling to `backend/`). Design tokens (colors, fonts, radii, widths) are defined once in `tailwind.config.ts` (Task 4) and referenced by name in every component. TypeScript response types are defined once in `src/lib/api.ts` (Task 5) and imported everywhere. Test convention: one `*.test.tsx` co-located next to each source file.

## Task 4: Frontend Scaffold + Tailwind Tokens + Vitest

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/tailwind.config.ts`
- Create: `frontend/postcss.config.js`
- Create: `frontend/index.html`
- Create: `frontend/src/index.css`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/test/setup.ts`
- Test: `frontend/src/App.test.tsx`

**Interfaces:**
- Produces: the Vite/Tailwind/Vitest toolchain and the named design tokens every later frontend task references — colors `page`/`surface`/`hairline`/`ink`/`muted`/`bullish`/`bearish`/`swatch.{oil_energy,banking,auto_ev,geopolitics,other}`, fonts `display`/`sans`, `rounded-lg` = 12px, `max-w-feed` = 680px, `tracking-widest` = 0.08em. `src/App.tsx` (placeholder, replaced in Task 7) and `src/main.tsx` (replaced in Task 7).

- [ ] **Step 1: Create the toolchain files**

`frontend/package.json`:

```json
{
  "name": "newsflo-frontend",
  "private": true,
  "version": "0.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc --noEmit && vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.26.2"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.4.8",
    "@testing-library/react": "^16.0.1",
    "@testing-library/user-event": "^14.5.2",
    "@types/react": "^18.3.5",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "autoprefixer": "^10.4.20",
    "jsdom": "^25.0.0",
    "postcss": "^8.4.45",
    "tailwindcss": "^3.4.10",
    "typescript": "^5.5.4",
    "vite": "^5.4.3",
    "vitest": "^2.0.5"
  }
}
```

`frontend/vite.config.ts`:

```ts
/// <reference types="vitest" />
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    // Dev-time proxy so the browser talks to the FastAPI backend on :8000
    // through the Vite dev server on :5173 (same-origin fetch + WebSocket).
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/ws': { target: 'ws://127.0.0.1:8000', ws: true },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
  },
});
```

`frontend/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "types": ["vitest/globals", "@testing-library/jest-dom"]
  },
  "include": ["src", "vite.config.ts"]
}
```

`frontend/tailwind.config.ts`:

```ts
import type { Config } from 'tailwindcss';

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        page: '#0A0A0A',       // near-true-black page background
        surface: '#161616',    // card surface, one step up from page bg
        hairline: '#262626',   // card border, hairline
        ink: '#F2F2F2',        // primary text
        muted: '#8E8E93',      // secondary / metadata text
        bullish: '#34C759',
        bearish: '#FF453A',
        swatch: {
          oil_energy: '#F5A623',   // amber
          banking: '#4A90D9',      // blue
          auto_ev: '#2DD4BF',      // teal
          geopolitics: '#E85D4C',  // red-orange
          other: '#8E8E93',        // gray (fallback)
        },
      },
      fontFamily: {
        display: ['Georgia', "'Times New Roman'", 'serif'],
        sans: [
          '-apple-system',
          'BlinkMacSystemFont',
          'Inter',
          "'Segoe UI'",
          'sans-serif',
        ],
      },
      borderRadius: {
        lg: '12px', // CRED-style moderate radius (~12px), per spec token
      },
      maxWidth: {
        feed: '680px',
      },
      letterSpacing: {
        widest: '0.08em', // tracked-uppercase metadata/tabs/buttons
      },
    },
  },
  plugins: [],
} satisfies Config;
```

`frontend/postcss.config.js`:

```js
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
```

`frontend/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>NewsFlo</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

`frontend/src/index.css`:

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

body {
  @apply bg-page text-ink font-sans antialiased;
}
```

`frontend/src/main.tsx` (placeholder — Task 7 replaces this to add Router + AuthProvider):

```tsx
import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './index.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
```

`frontend/src/App.tsx` (placeholder — Task 7 replaces this with routing):

```tsx
export default function App() {
  return (
    <main className="min-h-screen bg-page p-6 font-sans text-ink">
      <h1 className="font-display text-3xl font-bold">NewsFlo</h1>
    </main>
  );
}
```

`frontend/src/test/setup.ts`:

```ts
import '@testing-library/jest-dom';
```

- [ ] **Step 2: Write the failing smoke test**

`frontend/src/App.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import App from './App';

describe('App smoke test', () => {
  it('renders the NewsFlo heading', () => {
    render(<App />);
    expect(screen.getByRole('heading', { name: /newsflo/i })).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Install dependencies and run the test**

From `frontend/`, install the exact dependency set:

```bash
cd frontend
npm install react react-dom react-router-dom
npm install -D vite @vitejs/plugin-react typescript @types/react @types/react-dom tailwindcss postcss autoprefixer vitest jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event
```

(These match `package.json` exactly; running `npm install` with the `package.json` above already present is equivalent.)

Run: `npm run test`
Expected: `1 passed` — the smoke test renders the placeholder `App` and finds the heading, proving the Vitest + RTL + jsdom toolchain works end-to-end.

- [ ] **Step 4: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/vite.config.ts frontend/tsconfig.json frontend/tailwind.config.ts frontend/postcss.config.js frontend/index.html frontend/src/index.css frontend/src/main.tsx frontend/src/App.tsx frontend/src/test/setup.ts frontend/src/App.test.tsx
git commit -m "feat: scaffold React/Vite/Tailwind/Vitest frontend with design tokens"
```

---

## Task 5: Typed API Client

**Files:**
- Create: `frontend/src/lib/api.ts`
- Test: `frontend/src/lib/api.test.ts`

**Interfaces:**
- Produces: the single source of truth for backend response types — `AlertArticle`, `AlertCompany`, `Alert`, `WsAlertCompany` (= `Omit<AlertCompany, 'in_my_holdings'>`), `WsAlert`, `Article`, `TokenResponse`, `Holding`, `CsvUploadResponse` — and typed fetch functions `getAlerts(token?)`, `getArticles()`, `register(email, password)`, `login(email, password)`, `getHoldings(token)`, `addHolding(token, ticker, quantity)`, `uploadHoldingsCsv(token, file)`. Every later frontend task imports these types and functions. Field names copied verbatim from the current backend routers (`alerts.py`, `articles.py`, `auth.py`, `holdings.py`).

- [ ] **Step 1: Write the failing test**

`frontend/src/lib/api.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from 'vitest';
import { addHolding, getAlerts, login, register } from './api';

function mockFetchOnce(body: unknown, ok = true, status = 200) {
  const fn = vi.fn().mockResolvedValue({
    ok,
    status,
    json: async () => body,
  } as Response);
  vi.stubGlobal('fetch', fn);
  return fn;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('api client', () => {
  it('getAlerts sends no Authorization header when no token is passed', async () => {
    const fetchMock = mockFetchOnce([]);
    await getAlerts();
    const [url, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/alerts');
    expect((opts.headers as Record<string, string>).Authorization).toBeUndefined();
  });

  it('getAlerts attaches a Bearer token when provided', async () => {
    const fetchMock = mockFetchOnce([]);
    await getAlerts('tok123');
    const [, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect((opts.headers as Record<string, string>).Authorization).toBe('Bearer tok123');
  });

  it('register posts a JSON body and returns the token', async () => {
    const fetchMock = mockFetchOnce({ access_token: 'abc', token_type: 'bearer' });
    const result = await register('a@example.com', 'pw12345');
    const [url, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/auth/register');
    expect(opts.method).toBe('POST');
    expect(JSON.parse(opts.body as string)).toEqual({ email: 'a@example.com', password: 'pw12345' });
    expect(result.access_token).toBe('abc');
  });

  it('addHolding attaches the Bearer token and posts ticker/quantity', async () => {
    const fetchMock = mockFetchOnce({ company_id: 1, ticker: 'RELIANCE.NS', name: 'Reliance', quantity: 5 });
    await addHolding('tok', 'RELIANCE.NS', 5);
    const [url, opts] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/holdings');
    expect((opts.headers as Record<string, string>).Authorization).toBe('Bearer tok');
    expect(JSON.parse(opts.body as string)).toEqual({ ticker: 'RELIANCE.NS', quantity: 5 });
  });

  it('login throws the backend detail message on error', async () => {
    mockFetchOnce({ detail: 'Invalid email or password' }, false, 401);
    await expect(login('a@example.com', 'wrong')).rejects.toThrow('Invalid email or password');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `frontend/`): `npm run test -- src/lib/api.test.ts`
Expected: FAIL — `./api` does not exist yet (module resolution error).

- [ ] **Step 3: Implement the API client**

`frontend/src/lib/api.ts`:

```ts
// Response shapes copied verbatim from the backend routers. These interfaces
// are the single source of truth for every component in the app.

export interface AlertArticle {
  id: number;
  title: string;
  url: string;
}

export interface AlertCompany {
  company_id: number;
  ticker: string;
  name: string;
  index_tier: string; // NIFTY50 | NIFTY100 | NIFTY500 | OTHER
  direction: string; // bullish | bearish
  magnitude_low: number;
  magnitude_high: number;
  rationale: string;
  basis: string; // direct_mention | sector_inference
  confidence: string; // llm_estimate | calibrated
  in_my_holdings: boolean;
}

export interface Alert {
  id: number;
  category: string;
  created_at: string;
  article: AlertArticle;
  companies: AlertCompany[];
}

// The WebSocket live-push payload is one alert entry MINUS the per-viewer
// in_my_holdings flag (see Part A). useAlertsSocket normalizes it back to Alert
// by defaulting in_my_holdings to false.
export type WsAlertCompany = Omit<AlertCompany, 'in_my_holdings'>;
export type WsAlert = Omit<Alert, 'companies'> & { companies: WsAlertCompany[] };

export interface Article {
  id: number;
  source: string;
  title: string;
  url: string;
  status: string;
  category: string | null;
  fetched_at: string | null;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface Holding {
  company_id: number;
  ticker: string;
  name: string;
  quantity: number;
}

export interface CsvUploadResponse {
  loaded: number;
}

interface ApiError {
  detail: string;
}

function authHeaders(token: string | null): Record<string, string> {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function parseError(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as ApiError;
    if (typeof body.detail === 'string') return body.detail;
    return `Request failed (${res.status})`;
  } catch {
    return `Request failed (${res.status})`;
  }
}

export async function getAlerts(token: string | null = null): Promise<Alert[]> {
  const res = await fetch('/api/alerts', { headers: authHeaders(token) });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as Alert[];
}

export async function getArticles(): Promise<Article[]> {
  const res = await fetch('/api/articles');
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as Article[];
}

export async function register(email: string, password: string): Promise<TokenResponse> {
  const res = await fetch('/api/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as TokenResponse;
}

export async function login(email: string, password: string): Promise<TokenResponse> {
  const res = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as TokenResponse;
}

export async function getHoldings(token: string): Promise<Holding[]> {
  const res = await fetch('/api/holdings', { headers: authHeaders(token) });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as Holding[];
}

export async function addHolding(token: string, ticker: string, quantity: number): Promise<Holding> {
  const res = await fetch('/api/holdings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify({ ticker, quantity }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as Holding;
}

export async function uploadHoldingsCsv(token: string, file: File): Promise<CsvUploadResponse> {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch('/api/holdings/csv', {
    method: 'POST',
    headers: authHeaders(token),
    body: form,
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as CsvUploadResponse;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `frontend/`): `npm run test -- src/lib/api.test.ts`
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/api.ts frontend/src/lib/api.test.ts
git commit -m "feat: add typed API client matching backend contracts"
```

---

## Task 6: Auth Context, Login & Register Forms/Pages

**Files:**
- Create: `frontend/src/lib/auth.tsx`
- Create: `frontend/src/components/LoginForm.tsx`
- Create: `frontend/src/components/RegisterForm.tsx`
- Create: `frontend/src/pages/LoginPage.tsx`
- Create: `frontend/src/pages/RegisterPage.tsx`
- Test: `frontend/src/components/LoginForm.test.tsx`
- Test: `frontend/src/components/RegisterForm.test.tsx`

**Interfaces:**
- Consumes: `login`, `register` from `src/lib/api.ts` (Task 5).
- Produces: `AuthProvider` and `useAuth()` (`src/lib/auth`) returning `{ token: string | null, email: string | null, login(email, password), register(email, password), logout() }`, backed by `localStorage` keys `newsflo.token` / `newsflo.email`. `LoginForm`/`RegisterForm` (accept `onSuccess?: () => void`), `LoginPage`/`RegisterPage`. Tasks 7, 12, 13 all consume `useAuth()`; Task 7 routes to the pages.

- [ ] **Step 1: Write the failing tests**

`frontend/src/components/LoginForm.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ReactElement } from 'react';
import LoginForm from './LoginForm';
import { AuthProvider } from '../lib/auth';
import * as api from '../lib/api';

function renderWithAuth(ui: ReactElement) {
  return render(<AuthProvider>{ui}</AuthProvider>);
}

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe('LoginForm', () => {
  it('shows a validation error when fields are empty', async () => {
    renderWithAuth(<LoginForm />);
    await userEvent.click(screen.getByRole('button', { name: /log in/i }));
    expect(screen.getByRole('alert')).toHaveTextContent(/email and password/i);
  });

  it('stores a token in localStorage on successful login', async () => {
    vi.spyOn(api, 'login').mockResolvedValue({ access_token: 'tok-1', token_type: 'bearer' });
    const onSuccess = vi.fn();
    renderWithAuth(<LoginForm onSuccess={onSuccess} />);
    await userEvent.type(screen.getByLabelText(/email/i), 'a@example.com');
    await userEvent.type(screen.getByLabelText(/password/i), 'pw12345');
    await userEvent.click(screen.getByRole('button', { name: /log in/i }));
    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    expect(localStorage.getItem('newsflo.token')).toBe('tok-1');
    expect(localStorage.getItem('newsflo.email')).toBe('a@example.com');
  });

  it('shows the backend error message on failed login', async () => {
    vi.spyOn(api, 'login').mockRejectedValue(new Error('Invalid email or password'));
    renderWithAuth(<LoginForm />);
    await userEvent.type(screen.getByLabelText(/email/i), 'a@example.com');
    await userEvent.type(screen.getByLabelText(/password/i), 'wrong');
    await userEvent.click(screen.getByRole('button', { name: /log in/i }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid email or password');
  });
});
```

`frontend/src/components/RegisterForm.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ReactElement } from 'react';
import RegisterForm from './RegisterForm';
import { AuthProvider } from '../lib/auth';
import * as api from '../lib/api';

function renderWithAuth(ui: ReactElement) {
  return render(<AuthProvider>{ui}</AuthProvider>);
}

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe('RegisterForm', () => {
  it('rejects a password shorter than 6 characters', async () => {
    renderWithAuth(<RegisterForm />);
    await userEvent.type(screen.getByLabelText(/email/i), 'a@example.com');
    await userEvent.type(screen.getByLabelText(/password/i), 'short');
    await userEvent.click(screen.getByRole('button', { name: /create account/i }));
    expect(screen.getByRole('alert')).toHaveTextContent(/at least 6 characters/i);
  });

  it('stores a token on successful registration', async () => {
    vi.spyOn(api, 'register').mockResolvedValue({ access_token: 'tok-9', token_type: 'bearer' });
    const onSuccess = vi.fn();
    renderWithAuth(<RegisterForm onSuccess={onSuccess} />);
    await userEvent.type(screen.getByLabelText(/email/i), 'new@example.com');
    await userEvent.type(screen.getByLabelText(/password/i), 'pw12345');
    await userEvent.click(screen.getByRole('button', { name: /create account/i }));
    await waitFor(() => expect(onSuccess).toHaveBeenCalled());
    expect(localStorage.getItem('newsflo.token')).toBe('tok-9');
  });

  it('shows the backend error message on a duplicate email', async () => {
    vi.spyOn(api, 'register').mockRejectedValue(new Error('Email already registered'));
    renderWithAuth(<RegisterForm />);
    await userEvent.type(screen.getByLabelText(/email/i), 'dup@example.com');
    await userEvent.type(screen.getByLabelText(/password/i), 'pw12345');
    await userEvent.click(screen.getByRole('button', { name: /create account/i }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Email already registered');
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `frontend/`): `npm run test -- src/components/LoginForm.test.tsx src/components/RegisterForm.test.tsx`
Expected: FAIL — `../lib/auth`, `./LoginForm`, `./RegisterForm` do not exist yet.

- [ ] **Step 3: Implement the auth context**

`frontend/src/lib/auth.tsx`:

```tsx
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { login as apiLogin, register as apiRegister } from './api';

interface AuthState {
  token: string | null;
  email: string | null;
}

interface AuthContextValue extends AuthState {
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const TOKEN_KEY = 'newsflo.token';
const EMAIL_KEY = 'newsflo.email';

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>(() => ({
    token: localStorage.getItem(TOKEN_KEY),
    email: localStorage.getItem(EMAIL_KEY),
  }));

  const persist = useCallback((token: string, email: string) => {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(EMAIL_KEY, email);
    setState({ token, email });
  }, []);

  const login = useCallback(
    async (email: string, password: string) => {
      const res = await apiLogin(email, password);
      persist(res.access_token, email);
    },
    [persist],
  );

  const register = useCallback(
    async (email: string, password: string) => {
      const res = await apiRegister(email, password);
      persist(res.access_token, email);
    },
    [persist],
  );

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(EMAIL_KEY);
    setState({ token: null, email: null });
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({ ...state, login, register, logout }),
    [state, login, register, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (ctx === null) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return ctx;
}
```

- [ ] **Step 4: Implement the forms and pages**

`frontend/src/components/LoginForm.tsx`:

```tsx
import { useState, type FormEvent } from 'react';
import { useAuth } from '../lib/auth';

export default function LoginForm({ onSuccess }: { onSuccess?: () => void }) {
  const { login } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!email || !password) {
      setError('Enter your email and password.');
      return;
    }
    setSubmitting(true);
    try {
      await login(email, password);
      onSuccess?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4" aria-label="Log in">
      <label className="flex flex-col gap-1">
        <span className="text-xs uppercase tracking-widest text-muted">Email</span>
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="rounded-lg border border-hairline bg-surface px-3 py-2 text-ink outline-none focus:border-muted"
        />
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-xs uppercase tracking-widest text-muted">Password</span>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="rounded-lg border border-hairline bg-surface px-3 py-2 text-ink outline-none focus:border-muted"
        />
      </label>
      {error && <p role="alert" className="text-xs text-bearish">{error}</p>}
      <button
        type="submit"
        disabled={submitting}
        className="rounded-lg border border-hairline bg-surface px-4 py-2 text-xs uppercase tracking-widest text-ink disabled:opacity-50"
      >
        {submitting ? 'Signing in…' : 'Log in'}
      </button>
    </form>
  );
}
```

`frontend/src/components/RegisterForm.tsx`:

```tsx
import { useState, type FormEvent } from 'react';
import { useAuth } from '../lib/auth';

export default function RegisterForm({ onSuccess }: { onSuccess?: () => void }) {
  const { register } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!email) {
      setError('Enter your email.');
      return;
    }
    if (password.length < 6) {
      setError('Password must be at least 6 characters.');
      return;
    }
    setSubmitting(true);
    try {
      await register(email, password);
      onSuccess?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Registration failed.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4" aria-label="Register">
      <label className="flex flex-col gap-1">
        <span className="text-xs uppercase tracking-widest text-muted">Email</span>
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="rounded-lg border border-hairline bg-surface px-3 py-2 text-ink outline-none focus:border-muted"
        />
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-xs uppercase tracking-widest text-muted">Password</span>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="rounded-lg border border-hairline bg-surface px-3 py-2 text-ink outline-none focus:border-muted"
        />
      </label>
      {error && <p role="alert" className="text-xs text-bearish">{error}</p>}
      <button
        type="submit"
        disabled={submitting}
        className="rounded-lg border border-hairline bg-surface px-4 py-2 text-xs uppercase tracking-widest text-ink disabled:opacity-50"
      >
        {submitting ? 'Creating…' : 'Create account'}
      </button>
    </form>
  );
}
```

`frontend/src/pages/LoginPage.tsx`:

```tsx
import { Link, useNavigate } from 'react-router-dom';
import LoginForm from '../components/LoginForm';

export default function LoginPage() {
  const navigate = useNavigate();
  return (
    <div className="mx-auto mt-16 w-full max-w-sm px-4">
      <h1 className="mb-6 font-display text-2xl font-bold text-ink">Log in</h1>
      <LoginForm onSuccess={() => navigate('/')} />
      <p className="mt-4 text-xs uppercase tracking-widest text-muted">
        No account?{' '}
        <Link to="/register" className="text-ink underline">
          Register
        </Link>
      </p>
    </div>
  );
}
```

`frontend/src/pages/RegisterPage.tsx`:

```tsx
import { Link, useNavigate } from 'react-router-dom';
import RegisterForm from '../components/RegisterForm';

export default function RegisterPage() {
  const navigate = useNavigate();
  return (
    <div className="mx-auto mt-16 w-full max-w-sm px-4">
      <h1 className="mb-6 font-display text-2xl font-bold text-ink">Create account</h1>
      <RegisterForm onSuccess={() => navigate('/')} />
      <p className="mt-4 text-xs uppercase tracking-widest text-muted">
        Already registered?{' '}
        <Link to="/login" className="text-ink underline">
          Log in
        </Link>
      </p>
    </div>
  );
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run (from `frontend/`): `npm run test -- src/components/LoginForm.test.tsx src/components/RegisterForm.test.tsx`
Expected: `6 passed`

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/auth.tsx frontend/src/components/LoginForm.tsx frontend/src/components/RegisterForm.tsx frontend/src/pages/LoginPage.tsx frontend/src/pages/RegisterPage.tsx frontend/src/components/LoginForm.test.tsx frontend/src/components/RegisterForm.test.tsx
git commit -m "feat: add auth context, login/register forms and pages"
```

---

## Task 7: NavBar + App Routing (protected /holdings)

**Files:**
- Create: `frontend/src/components/NavBar.tsx`
- Create: `frontend/src/pages/FeedPage.tsx` (placeholder — replaced in Task 12)
- Create: `frontend/src/pages/HoldingsPage.tsx` (placeholder — replaced in Task 13)
- Modify: `frontend/src/App.tsx` (replace placeholder from Task 4)
- Modify: `frontend/src/main.tsx` (replace placeholder from Task 4)
- Modify: `frontend/src/App.test.tsx` (replace smoke test from Task 4)
- Test: `frontend/src/components/NavBar.test.tsx`

**Interfaces:**
- Consumes: `useAuth()` (Task 6), `LoginPage`/`RegisterPage` (Task 6).
- Produces: `NavBar`, the four routes `/`, `/holdings` (auth-protected via `<Navigate to="/login">`), `/login`, `/register`, and the `main.tsx` that wraps `<App />` in `<BrowserRouter>` + `<AuthProvider>`. Placeholder `FeedPage`/`HoldingsPage` (Tasks 12/13 replace their full contents). Tasks 12/13 render inside these routes.

- [ ] **Step 1: Write the failing tests**

`frontend/src/components/NavBar.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it } from 'vitest';
import NavBar from './NavBar';
import { AuthProvider } from '../lib/auth';

function renderNav() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <NavBar />
      </AuthProvider>
    </MemoryRouter>,
  );
}

afterEach(() => localStorage.clear());

describe('NavBar', () => {
  it('shows Login and Register when logged out', () => {
    renderNav();
    expect(screen.getByRole('link', { name: /login/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /register/i })).toBeInTheDocument();
  });

  it('shows the user email and a Logout button when logged in', () => {
    localStorage.setItem('newsflo.token', 'tok');
    localStorage.setItem('newsflo.email', 'me@example.com');
    renderNav();
    expect(screen.getByText('me@example.com')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /logout/i })).toBeInTheDocument();
  });
});
```

`frontend/src/App.test.tsx` (replace the entire file from Task 4):

```tsx
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App';
import { AuthProvider } from './lib/auth';

// Minimal no-op WebSocket + empty fetch so the (later) live FeedPage mounts
// cleanly inside these routing tests without touching the network.
class NoopSocket {
  onopen: (() => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onclose: (() => void) | null = null;
  close() {}
}

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => [] } as unknown as Response),
  );
  vi.stubGlobal('WebSocket', NoopSocket as unknown as typeof WebSocket);
});

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe('App routing', () => {
  it('renders the feed nav at /', () => {
    renderAt('/');
    expect(screen.getByRole('link', { name: /^feed$/i })).toBeInTheDocument();
  });

  it('redirects /holdings to /login when logged out', () => {
    renderAt('/holdings');
    expect(screen.getByRole('heading', { name: /log in/i })).toBeInTheDocument();
  });

  it('renders the holdings page at /holdings when logged in', () => {
    localStorage.setItem('newsflo.token', 'tok');
    localStorage.setItem('newsflo.email', 'me@example.com');
    renderAt('/holdings');
    expect(screen.getByRole('heading', { name: /holdings/i })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `frontend/`): `npm run test -- src/components/NavBar.test.tsx src/App.test.tsx`
Expected: FAIL — `NavBar`, `FeedPage`, `HoldingsPage`, and the routing `App` do not exist yet.

- [ ] **Step 3: Implement NavBar, placeholder pages, App, and main**

`frontend/src/components/NavBar.tsx`:

```tsx
import { Link } from 'react-router-dom';
import { useAuth } from '../lib/auth';

export default function NavBar() {
  const { token, email, logout } = useAuth();
  return (
    <nav className="border-b border-hairline bg-page">
      <div className="mx-auto flex max-w-feed items-center justify-between px-4 py-4">
        <div className="flex items-center gap-6">
          <Link to="/" className="font-display text-lg font-bold text-ink">
            NewsFlo
          </Link>
          <Link to="/" className="text-xs uppercase tracking-widest text-muted hover:text-ink">
            Feed
          </Link>
          <Link to="/holdings" className="text-xs uppercase tracking-widest text-muted hover:text-ink">
            Holdings
          </Link>
        </div>
        <div className="flex items-center gap-4 text-xs uppercase tracking-widest">
          {token ? (
            <>
              <span className="text-muted">{email}</span>
              <button type="button" onClick={logout} className="text-ink hover:text-muted">
                Logout
              </button>
            </>
          ) : (
            <>
              <Link to="/login" className="text-ink hover:text-muted">
                Login
              </Link>
              <Link to="/register" className="text-ink hover:text-muted">
                Register
              </Link>
            </>
          )}
        </div>
      </div>
    </nav>
  );
}
```

`frontend/src/pages/FeedPage.tsx` (placeholder — Task 12 replaces the entire file):

```tsx
export default function FeedPage() {
  return (
    <main className="mx-auto max-w-feed px-4 py-8">
      <p className="text-xs uppercase tracking-widest text-muted">Feed coming soon.</p>
    </main>
  );
}
```

`frontend/src/pages/HoldingsPage.tsx` (placeholder — Task 13 replaces the entire file):

```tsx
export default function HoldingsPage() {
  return (
    <main className="mx-auto max-w-feed px-4 py-8">
      <h1 className="font-display text-2xl font-bold text-ink">My Holdings</h1>
    </main>
  );
}
```

`frontend/src/App.tsx` (replace the placeholder from Task 4):

```tsx
import { Navigate, Route, Routes } from 'react-router-dom';
import type { ReactElement } from 'react';
import NavBar from './components/NavBar';
import FeedPage from './pages/FeedPage';
import HoldingsPage from './pages/HoldingsPage';
import LoginPage from './pages/LoginPage';
import RegisterPage from './pages/RegisterPage';
import { useAuth } from './lib/auth';

function RequireAuth({ children }: { children: ReactElement }) {
  const { token } = useAuth();
  if (!token) return <Navigate to="/login" replace />;
  return children;
}

export default function App() {
  return (
    <div className="min-h-screen bg-page font-sans text-ink">
      <NavBar />
      <Routes>
        <Route path="/" element={<FeedPage />} />
        <Route
          path="/holdings"
          element={
            <RequireAuth>
              <HoldingsPage />
            </RequireAuth>
          }
        />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
      </Routes>
    </div>
  );
}
```

`frontend/src/main.tsx` (replace the placeholder from Task 4):

```tsx
import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import { AuthProvider } from './lib/auth';
import './index.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <App />
      </AuthProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
```

- [ ] **Step 4: Run tests to verify they pass**

Run (from `frontend/`): `npm run test -- src/components/NavBar.test.tsx src/App.test.tsx`
Expected: `5 passed` (2 NavBar + 3 App routing).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/NavBar.tsx frontend/src/components/NavBar.test.tsx frontend/src/pages/FeedPage.tsx frontend/src/pages/HoldingsPage.tsx frontend/src/App.tsx frontend/src/App.test.tsx frontend/src/main.tsx
git commit -m "feat: add NavBar and React Router wiring with protected holdings route"
```

---

## Task 8: CategorySwatch + SentimentPill (net majority-vote logic)

**Files:**
- Create: `frontend/src/components/CategorySwatch.tsx`
- Create: `frontend/src/components/SentimentPill.tsx`
- Test: `frontend/src/components/CategorySwatch.test.tsx`
- Test: `frontend/src/components/SentimentPill.test.tsx`

**Interfaces:**
- Consumes: `AlertCompany` type (Task 5).
- Produces: `CategorySwatch` (`{ category: string }`) rendering a colored dot + tracked-uppercase label; `SentimentPill` (`{ companies: Pick<AlertCompany, 'direction'>[] }`) plus the exported pure function `netSentiment(companies): 'bullish' | 'bearish' | 'mixed'`. Task 10 (`AlertCard`) composes both.

- [ ] **Step 1: Write the failing tests**

`frontend/src/components/SentimentPill.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import SentimentPill, { netSentiment } from './SentimentPill';

const bull = { direction: 'bullish' };
const bear = { direction: 'bearish' };

describe('netSentiment majority vote', () => {
  it('returns bullish when more than 50% are bullish', () => {
    expect(netSentiment([bull, bull, bear])).toBe('bullish');
  });
  it('returns bearish when more than 50% are bearish', () => {
    expect(netSentiment([bear, bear, bull])).toBe('bearish');
  });
  it('returns mixed on an exact two-way tie', () => {
    expect(netSentiment([bull, bear])).toBe('mixed');
  });
  it('returns mixed for an empty list (the empty My Demat case)', () => {
    expect(netSentiment([])).toBe('mixed');
  });
  it('treats exactly 50% bullish as mixed (not a majority)', () => {
    expect(netSentiment([bull, bull, bear, bear])).toBe('mixed');
  });
});

describe('SentimentPill', () => {
  it('renders Net Bullish with bullish text styling', () => {
    render(<SentimentPill companies={[bull, bull, bear]} />);
    expect(screen.getByText('Net Bullish')).toHaveClass('text-bullish');
  });
  it('renders Net Bearish with bearish text styling', () => {
    render(<SentimentPill companies={[bear, bear, bull]} />);
    expect(screen.getByText('Net Bearish')).toHaveClass('text-bearish');
  });
  it('renders Mixed with muted styling for an empty list', () => {
    render(<SentimentPill companies={[]} />);
    expect(screen.getByText('Mixed')).toHaveClass('text-muted');
  });
});
```

`frontend/src/components/CategorySwatch.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import CategorySwatch from './CategorySwatch';

describe('CategorySwatch', () => {
  it('renders a known category label', () => {
    render(<CategorySwatch category="oil_energy" />);
    expect(screen.getByText('Oil & Energy')).toBeInTheDocument();
  });
  it('humanizes an unknown category label', () => {
    render(<CategorySwatch category="some_other" />);
    expect(screen.getByText('some other')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `frontend/`): `npm run test -- src/components/SentimentPill.test.tsx src/components/CategorySwatch.test.tsx`
Expected: FAIL — neither component exists yet.

- [ ] **Step 3: Implement the components**

`frontend/src/components/CategorySwatch.tsx`:

```tsx
// Full static class strings (not built by interpolation) so Tailwind's content
// scanner keeps them. Each maps a backend category to its named swatch color.
const SWATCH_CLASS: Record<string, string> = {
  oil_energy: 'bg-swatch-oil_energy',
  banking: 'bg-swatch-banking',
  auto_ev: 'bg-swatch-auto_ev',
  geopolitics: 'bg-swatch-geopolitics',
};

const CATEGORY_LABEL: Record<string, string> = {
  oil_energy: 'Oil & Energy',
  banking: 'Banking',
  auto_ev: 'Auto & EV',
  geopolitics: 'Geopolitics',
};

export default function CategorySwatch({ category }: { category: string }) {
  const dotClass = SWATCH_CLASS[category] ?? 'bg-swatch-other';
  const label = CATEGORY_LABEL[category] ?? category.replace(/_/g, ' ');
  return (
    <span className="inline-flex items-center gap-2">
      <span className={`h-2 w-2 rounded-full ${dotClass}`} aria-hidden="true" />
      <span className="text-xs uppercase tracking-widest text-muted">{label}</span>
    </span>
  );
}
```

`frontend/src/components/SentimentPill.tsx`:

```tsx
import type { AlertCompany } from '../lib/api';

export type Sentiment = 'bullish' | 'bearish' | 'mixed';

// Majority (>50%) of the visible companies decides the pill. An exact tie —
// including the empty (zero-company) case — is Mixed.
export function netSentiment(companies: Pick<AlertCompany, 'direction'>[]): Sentiment {
  const total = companies.length;
  const bullish = companies.filter((c) => c.direction === 'bullish').length;
  const bearish = companies.filter((c) => c.direction === 'bearish').length;
  if (bullish > total / 2) return 'bullish';
  if (bearish > total / 2) return 'bearish';
  return 'mixed';
}

const PILL: Record<Sentiment, { label: string; className: string }> = {
  bullish: { label: 'Net Bullish', className: 'border-bullish text-bullish' },
  bearish: { label: 'Net Bearish', className: 'border-bearish text-bearish' },
  mixed: { label: 'Mixed', className: 'border-muted text-muted' },
};

export default function SentimentPill({
  companies,
}: {
  companies: Pick<AlertCompany, 'direction'>[];
}) {
  const { label, className } = PILL[netSentiment(companies)];
  return (
    <span
      className={`inline-flex items-center rounded-full border-[1.5px] bg-transparent px-3 py-1 text-xs uppercase tracking-widest ${className}`}
    >
      {label}
    </span>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run (from `frontend/`): `npm run test -- src/components/SentimentPill.test.tsx src/components/CategorySwatch.test.tsx`
Expected: `10 passed` (8 SentimentPill + 2 CategorySwatch).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/CategorySwatch.tsx frontend/src/components/SentimentPill.tsx frontend/src/components/CategorySwatch.test.tsx frontend/src/components/SentimentPill.test.tsx
git commit -m "feat: add CategorySwatch and SentimentPill with net majority-vote logic"
```

---

## Task 9: CompanyChip + ReasoningPanel

**Files:**
- Create: `frontend/src/components/ReasoningPanel.tsx`
- Create: `frontend/src/components/CompanyChip.tsx`
- Test: `frontend/src/components/ReasoningPanel.test.tsx`
- Test: `frontend/src/components/CompanyChip.test.tsx`

**Interfaces:**
- Consumes: `AlertCompany` type (Task 5).
- Produces: `ReasoningPanel` (`{ company: AlertCompany }`) plus the exported pure function `precedentLine(company)` implementing the confidence-based fallback (`calibrated` → historical-precedent framing citing the blended range; otherwise → note it is the model's own estimate); `CompanyChip` (`{ company: AlertCompany }`) — chip with name + colored magnitude range, collapsed by default, expands `ReasoningPanel` on click/Enter/Space. Task 10 (`AlertCard`) renders `CompanyChip`.

- [ ] **Step 1: Write the failing tests**

`frontend/src/components/ReasoningPanel.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import ReasoningPanel, { precedentLine } from './ReasoningPanel';
import type { AlertCompany } from '../lib/api';

const base: AlertCompany = {
  company_id: 1,
  ticker: 'RELIANCE.NS',
  name: 'Reliance',
  index_tier: 'NIFTY50',
  direction: 'bullish',
  magnitude_low: 2,
  magnitude_high: 4,
  rationale: 'Margins up.',
  basis: 'direct_mention',
  confidence: 'llm_estimate',
  in_my_holdings: false,
};

describe('precedentLine', () => {
  it('cites the blended range as historical precedent when calibrated', () => {
    const line = precedentLine({ ...base, confidence: 'calibrated' });
    expect(line).toMatch(/historical precedent/i);
    expect(line).toContain('+2.0% to +4.0%');
  });
  it('notes the model estimate when not calibrated', () => {
    expect(precedentLine(base)).toMatch(/model's own estimate/i);
  });
});

describe('ReasoningPanel', () => {
  it('renders the company, ticker and rationale', () => {
    render(<ReasoningPanel company={base} />);
    expect(screen.getByText(/RELIANCE\.NS/)).toBeInTheDocument();
    expect(screen.getByText('Margins up.')).toBeInTheDocument();
  });
});
```

`frontend/src/components/CompanyChip.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import CompanyChip from './CompanyChip';
import type { AlertCompany } from '../lib/api';

const company: AlertCompany = {
  company_id: 1,
  ticker: 'RELIANCE.NS',
  name: 'Reliance Industries',
  index_tier: 'NIFTY50',
  direction: 'bullish',
  magnitude_low: 2,
  magnitude_high: 4,
  rationale: 'Refiner margins expand.',
  basis: 'direct_mention',
  confidence: 'llm_estimate',
  in_my_holdings: false,
};

describe('CompanyChip', () => {
  it('shows the company name and a signed magnitude range', () => {
    render(<CompanyChip company={company} />);
    expect(screen.getByText('Reliance Industries')).toBeInTheDocument();
    expect(screen.getByText('+2.0% to +4.0%')).toBeInTheDocument();
  });

  it('is collapsed by default and expands the reasoning panel on click', async () => {
    render(<CompanyChip company={company} />);
    expect(screen.queryByText('Refiner margins expand.')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /reliance/i }));
    expect(screen.getByText('Refiner margins expand.')).toBeInTheDocument();
  });

  it('expands on the Enter key when focused', async () => {
    render(<CompanyChip company={company} />);
    const chip = screen.getByRole('button', { name: /reliance/i });
    chip.focus();
    await userEvent.keyboard('{Enter}');
    expect(screen.getByText('Refiner margins expand.')).toBeInTheDocument();
  });

  it('colors a bearish range with bearish styling', () => {
    render(<CompanyChip company={{ ...company, direction: 'bearish', magnitude_low: -3, magnitude_high: -1 }} />);
    expect(screen.getByText('-3.0% to -1.0%')).toHaveClass('text-bearish');
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `frontend/`): `npm run test -- src/components/ReasoningPanel.test.tsx src/components/CompanyChip.test.tsx`
Expected: FAIL — neither component exists yet.

- [ ] **Step 3: Implement the components**

`frontend/src/components/ReasoningPanel.tsx`:

```tsx
import type { AlertCompany } from '../lib/api';

function fmtPct(v: number): string {
  return `${v > 0 ? '+' : ''}${v.toFixed(1)}%`;
}

// Spec fallback rule: once the calibration DB has enough samples the confidence
// is "calibrated" and the blended range is framed as historical precedent;
// otherwise the LLM's own estimate stands.
export function precedentLine(company: AlertCompany): string {
  if (company.confidence === 'calibrated') {
    return `Historical precedent: similar past events averaged ${fmtPct(company.magnitude_low)} to ${fmtPct(
      company.magnitude_high,
    )} over comparable horizons.`;
  }
  return `No calibrated history yet — showing the model's own estimate.`;
}

export default function ReasoningPanel({ company }: { company: AlertCompany }) {
  return (
    <div className="rounded-lg border border-hairline bg-surface px-3 py-3">
      <p className="text-xs uppercase tracking-widest text-muted">
        {company.name} · {company.ticker}
      </p>
      <p className="mt-2 text-sm text-ink">{company.rationale}</p>
      <p className="mt-2 text-xs text-muted">{precedentLine(company)}</p>
    </div>
  );
}
```

`frontend/src/components/CompanyChip.tsx`:

```tsx
import { useState, type KeyboardEvent } from 'react';
import type { AlertCompany } from '../lib/api';
import ReasoningPanel from './ReasoningPanel';

function fmtPct(v: number): string {
  return `${v > 0 ? '+' : ''}${v.toFixed(1)}%`;
}

export default function CompanyChip({ company }: { company: AlertCompany }) {
  const [expanded, setExpanded] = useState(false);
  const magnitudeClass = company.direction === 'bullish' ? 'text-bullish' : 'text-bearish';

  function toggle() {
    setExpanded((v) => !v);
  }

  function onKeyDown(e: KeyboardEvent) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      toggle();
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <div
        role="button"
        tabIndex={0}
        aria-expanded={expanded}
        onClick={toggle}
        onKeyDown={onKeyDown}
        className="flex cursor-pointer items-center justify-between rounded-lg border border-hairline bg-surface px-3 py-2 motion-safe:transition-colors hover:border-muted"
      >
        <span className="text-sm text-ink">{company.name}</span>
        <span className={`text-xs tabular-nums ${magnitudeClass}`}>
          {fmtPct(company.magnitude_low)} to {fmtPct(company.magnitude_high)}
        </span>
      </div>
      {expanded && <ReasoningPanel company={company} />}
    </div>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run (from `frontend/`): `npm run test -- src/components/ReasoningPanel.test.tsx src/components/CompanyChip.test.tsx`
Expected: `7 passed` (3 ReasoningPanel + 4 CompanyChip).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ReasoningPanel.tsx frontend/src/components/CompanyChip.tsx frontend/src/components/ReasoningPanel.test.tsx frontend/src/components/CompanyChip.test.tsx
git commit -m "feat: add CompanyChip and confidence-aware ReasoningPanel"
```

---

## Task 10: AlertCard (tabs, tier grouping, collapse/expand)

**Files:**
- Create: `frontend/src/components/AlertCard.tsx`
- Test: `frontend/src/components/AlertCard.test.tsx`

**Interfaces:**
- Consumes: `Alert`, `AlertCompany` types (Task 5), `CategorySwatch` (Task 8), `SentimentPill` (Task 8), `CompanyChip` (Task 9).
- Produces: `AlertCard` (`{ alert: Alert; isAuthenticated: boolean }`) — the full card: swatch + label + timestamp + serif headline; Predicted / My Demat tabs; index-tier-grouped chip groups (Nifty 50 / Nifty 100 / Nifty 500 / Other); per-tab `SentimentPill`; collapse/expand. My Demat filters `in_my_holdings === true`. Task 12 (`Feed`) renders a list of these.

- [ ] **Step 1: Write the failing test**

`frontend/src/components/AlertCard.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import AlertCard from './AlertCard';
import type { Alert } from '../lib/api';

const alert: Alert = {
  id: 1,
  category: 'oil_energy',
  created_at: '2026-07-09T10:00:00+00:00',
  article: { id: 1, title: 'US strikes Iran oil export sites', url: 'https://example.com/a' },
  companies: [
    {
      company_id: 1, ticker: 'RELIANCE.NS', name: 'Reliance Industries', index_tier: 'NIFTY50',
      direction: 'bullish', magnitude_low: 2, magnitude_high: 4, rationale: 'Refiner up.',
      basis: 'direct_mention', confidence: 'llm_estimate', in_my_holdings: true,
    },
    {
      company_id: 2, ticker: 'ONGC.NS', name: 'ONGC', index_tier: 'NIFTY100',
      direction: 'bearish', magnitude_low: -3, magnitude_high: -1, rationale: 'Cost pressure.',
      basis: 'sector_inference', confidence: 'llm_estimate', in_my_holdings: false,
    },
  ],
};

describe('AlertCard', () => {
  it('renders the serif headline and is collapsed by default', () => {
    render(<AlertCard alert={alert} isAuthenticated />);
    expect(screen.getByText('US strikes Iran oil export sites')).toBeInTheDocument();
    // Chips are hidden until the card is expanded.
    expect(screen.queryByText('Reliance Industries')).not.toBeInTheDocument();
  });

  it('expands to show tier-grouped chips on headline click', async () => {
    render(<AlertCard alert={alert} isAuthenticated />);
    await userEvent.click(screen.getByText('US strikes Iran oil export sites'));
    expect(screen.getByText('Nifty 50')).toBeInTheDocument();
    expect(screen.getByText('Nifty 100')).toBeInTheDocument();
    expect(screen.getByText('Reliance Industries')).toBeInTheDocument();
    expect(screen.getByText('ONGC')).toBeInTheDocument();
  });

  it('filters to held companies only on the My Demat tab', async () => {
    render(<AlertCard alert={alert} isAuthenticated />);
    await userEvent.click(screen.getByRole('button', { name: /my demat/i }));
    expect(screen.getByText('Reliance Industries')).toBeInTheDocument();
    expect(screen.queryByText('ONGC')).not.toBeInTheDocument();
  });

  it('shows the login prompt on My Demat when logged out and nothing matches', async () => {
    const anon: Alert = { ...alert, companies: alert.companies.map((c) => ({ ...c, in_my_holdings: false })) };
    render(<AlertCard alert={anon} isAuthenticated={false} />);
    await userEvent.click(screen.getByRole('button', { name: /my demat/i }));
    expect(screen.getByText(/log in to see holdings-matched alerts/i)).toBeInTheDocument();
  });

  it('shows an empty-holdings message on My Demat when logged in with no matches', async () => {
    const noneHeld: Alert = { ...alert, companies: alert.companies.map((c) => ({ ...c, in_my_holdings: false })) };
    render(<AlertCard alert={noneHeld} isAuthenticated />);
    await userEvent.click(screen.getByRole('button', { name: /my demat/i }));
    expect(screen.getByText(/none of your holdings are affected/i)).toBeInTheDocument();
  });

  it('shows a Mixed net-sentiment pill on the Predicted tab (1 bullish, 1 bearish)', () => {
    render(<AlertCard alert={alert} isAuthenticated />);
    expect(screen.getByText('Mixed')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `frontend/`): `npm run test -- src/components/AlertCard.test.tsx`
Expected: FAIL — `AlertCard` does not exist yet.

- [ ] **Step 3: Implement AlertCard**

`frontend/src/components/AlertCard.tsx`:

```tsx
import { useState, type KeyboardEvent, type MouseEvent } from 'react';
import type { Alert, AlertCompany } from '../lib/api';
import CategorySwatch from './CategorySwatch';
import CompanyChip from './CompanyChip';
import SentimentPill from './SentimentPill';

type Tab = 'predicted' | 'my_demat';

const TIER_ORDER = ['NIFTY50', 'NIFTY100', 'NIFTY500', 'OTHER'] as const;
const TIER_LABEL: Record<string, string> = {
  NIFTY50: 'Nifty 50',
  NIFTY100: 'Nifty 100',
  NIFTY500: 'Nifty 500',
  OTHER: 'Other',
};

function tierKey(company: AlertCompany): string {
  return TIER_LABEL[company.index_tier] ? company.index_tier : 'OTHER';
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export default function AlertCard({ alert, isAuthenticated }: { alert: Alert; isAuthenticated: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const [tab, setTab] = useState<Tab>('predicted');

  const visible = tab === 'predicted' ? alert.companies : alert.companies.filter((c) => c.in_my_holdings);

  const grouped = TIER_ORDER.map((tier) => ({
    tier,
    label: TIER_LABEL[tier],
    companies: visible.filter((c) => tierKey(c) === tier),
  })).filter((g) => g.companies.length > 0);

  function toggleExpand() {
    setExpanded((v) => !v);
  }

  function onHeaderKeyDown(e: KeyboardEvent) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      toggleExpand();
    }
  }

  function selectTab(e: MouseEvent, next: Tab) {
    e.stopPropagation(); // tab click must not toggle the card
    setTab(next);
    setExpanded(true);
  }

  const tabClass = (active: boolean) =>
    `pb-1 text-xs uppercase tracking-widest border-b-2 ${
      active ? 'border-ink text-ink' : 'border-transparent text-muted'
    }`;

  const emptyCopy =
    tab === 'my_demat'
      ? isAuthenticated
        ? 'None of your holdings are affected by this story.'
        : 'Log in to see holdings-matched alerts.'
      : 'No affected companies for this story.';

  return (
    <article className="rounded-lg border border-hairline bg-surface p-6">
      <div
        role="button"
        tabIndex={0}
        aria-expanded={expanded}
        onClick={toggleExpand}
        onKeyDown={onHeaderKeyDown}
        className="flex cursor-pointer flex-col gap-3"
      >
        <div className="flex items-center justify-between">
          <CategorySwatch category={alert.category} />
          <time className="text-xs uppercase tracking-widest text-muted">{formatTime(alert.created_at)}</time>
        </div>
        <h2 className="font-display text-xl font-bold leading-snug text-ink">{alert.article.title}</h2>
      </div>

      <div className="mt-4 flex items-center justify-between">
        <div className="flex gap-4">
          <button type="button" onClick={(e) => selectTab(e, 'predicted')} className={tabClass(tab === 'predicted')}>
            Predicted
          </button>
          <button type="button" onClick={(e) => selectTab(e, 'my_demat')} className={tabClass(tab === 'my_demat')}>
            My Demat
          </button>
        </div>
        <SentimentPill companies={visible} />
      </div>

      {expanded && (
        <div className="mt-4 flex flex-col gap-4 motion-safe:transition-all">
          {visible.length === 0 ? (
            <p className="text-xs text-muted">{emptyCopy}</p>
          ) : (
            grouped.map((group) => (
              <div key={group.tier} className="flex flex-col gap-2">
                <p className="text-xs uppercase tracking-widest text-muted">{group.label}</p>
                {group.companies.map((company) => (
                  <CompanyChip key={company.company_id} company={company} />
                ))}
              </div>
            ))
          )}
        </div>
      )}
    </article>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `frontend/`): `npm run test -- src/components/AlertCard.test.tsx`
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/AlertCard.tsx frontend/src/components/AlertCard.test.tsx
git commit -m "feat: add AlertCard with tabs, tier grouping and collapse/expand"
```

---

## Task 11: useAlertsSocket Hook (connect, reconnect, dedupe)

**Files:**
- Create: `frontend/src/lib/useAlertsSocket.ts`
- Test: `frontend/src/lib/useAlertsSocket.test.tsx`

**Interfaces:**
- Consumes: `Alert`, `WsAlert` types (Task 5).
- Produces: `useAlertsSocket(): Alert[]` — connects to `ws(s)://<host>/ws/alerts`, normalizes each incoming `WsAlert` to `Alert` (defaulting `in_my_holdings: false`), prepends new alerts, dedupes by `id`, and reconnects on close after a fixed 3s backoff. Task 12 (`Feed`) consumes the returned array.

- [ ] **Step 1: Write the failing test**

`frontend/src/lib/useAlertsSocket.test.tsx`:

```tsx
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useAlertsSocket } from './useAlertsSocket';
import type { WsAlert } from './api';

class MockWebSocket {
  static instances: MockWebSocket[] = [];
  url: string;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onclose: (() => void) | null = null;
  onopen: (() => void) | null = null;
  closed = false;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  emit(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) } as MessageEvent);
  }

  triggerClose() {
    this.onclose?.();
  }

  close() {
    this.closed = true;
  }
}

function makeWsAlert(id: number): WsAlert {
  return {
    id,
    category: 'oil_energy',
    created_at: '2026-07-09T10:00:00+00:00',
    article: { id, title: `Story ${id}`, url: `https://example.com/${id}` },
    companies: [
      {
        company_id: id, ticker: 'RELIANCE.NS', name: 'Reliance', index_tier: 'NIFTY50',
        direction: 'bullish', magnitude_low: 1, magnitude_high: 2, rationale: 'x',
        basis: 'direct_mention', confidence: 'llm_estimate',
      },
    ],
  };
}

beforeEach(() => {
  MockWebSocket.instances = [];
  vi.stubGlobal('WebSocket', MockWebSocket as unknown as typeof WebSocket);
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('useAlertsSocket', () => {
  it('normalizes incoming alerts with in_my_holdings=false and prepends them', () => {
    const { result } = renderHook(() => useAlertsSocket());
    act(() => MockWebSocket.instances[0].emit(makeWsAlert(1)));
    act(() => MockWebSocket.instances[0].emit(makeWsAlert(2)));
    expect(result.current.map((a) => a.id)).toEqual([2, 1]);
    expect(result.current[0].companies[0].in_my_holdings).toBe(false);
  });

  it('dedupes repeated alert ids', () => {
    const { result } = renderHook(() => useAlertsSocket());
    act(() => MockWebSocket.instances[0].emit(makeWsAlert(1)));
    act(() => MockWebSocket.instances[0].emit(makeWsAlert(1)));
    expect(result.current).toHaveLength(1);
  });

  it('reconnects after a fixed backoff when the socket closes', () => {
    renderHook(() => useAlertsSocket());
    expect(MockWebSocket.instances).toHaveLength(1);
    act(() => {
      MockWebSocket.instances[0].triggerClose();
      vi.advanceTimersByTime(3000);
    });
    expect(MockWebSocket.instances).toHaveLength(2);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `frontend/`): `npm run test -- src/lib/useAlertsSocket.test.tsx`
Expected: FAIL — the hook does not exist yet.

- [ ] **Step 3: Implement the hook**

`frontend/src/lib/useAlertsSocket.ts`:

```ts
import { useEffect, useRef, useState } from 'react';
import type { Alert, WsAlert } from './api';

const RECONNECT_DELAY_MS = 3000;

function wsUrl(): string {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
  return `${proto}://${window.location.host}/ws/alerts`;
}

function normalize(ws: WsAlert): Alert {
  return {
    ...ws,
    companies: ws.companies.map((c) => ({ ...c, in_my_holdings: false })),
  };
}

export function useAlertsSocket(): Alert[] {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const socketRef = useRef<WebSocket | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const closedRef = useRef(false);

  useEffect(() => {
    closedRef.current = false;

    function connect() {
      const socket = new WebSocket(wsUrl());
      socketRef.current = socket;

      socket.onmessage = (event: MessageEvent) => {
        const raw = JSON.parse(event.data as string) as WsAlert;
        const incoming = normalize(raw);
        setAlerts((prev) => {
          if (prev.some((a) => a.id === incoming.id)) return prev; // dedupe by id
          return [incoming, ...prev]; // prepend newest
        });
      };

      socket.onclose = () => {
        if (closedRef.current) return; // intentional unmount close -> do not retry
        timerRef.current = setTimeout(connect, RECONNECT_DELAY_MS);
      };
    }

    connect();

    return () => {
      closedRef.current = true;
      if (timerRef.current) clearTimeout(timerRef.current);
      socketRef.current?.close();
    };
  }, []);

  return alerts;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `frontend/`): `npm run test -- src/lib/useAlertsSocket.test.tsx`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/useAlertsSocket.ts frontend/src/lib/useAlertsSocket.test.tsx
git commit -m "feat: add useAlertsSocket hook with reconnect and id dedupe"
```

---

## Task 12: Feed + FeedPage (initial fetch + live merge)

**Files:**
- Create: `frontend/src/components/Feed.tsx`
- Modify: `frontend/src/pages/FeedPage.tsx` (replace the Task 7 placeholder)
- Test: `frontend/src/components/Feed.test.tsx`

**Interfaces:**
- Consumes: `getAlerts` + `Alert` type (Task 5), `useAuth()` (Task 6), `useAlertsSocket` (Task 11), `AlertCard` (Task 10).
- Produces: exported pure function `mergeAlerts(live, fetched)` (prepend live, dedupe by id) and the `Feed` component (fetches `GET /api/alerts` on mount, merges live pushes, renders an `AlertCard` list with loading/error/empty states); `FeedPage` renders `Feed` in the centered feed column. No later task depends on these (leaf of the feed branch).

- [ ] **Step 1: Write the failing test**

`frontend/src/components/Feed.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import Feed, { mergeAlerts } from './Feed';
import { AuthProvider } from '../lib/auth';
import * as api from '../lib/api';
import type { Alert } from '../lib/api';

// Isolate Feed from the real socket in these tests.
vi.mock('../lib/useAlertsSocket', () => ({ useAlertsSocket: () => [] }));

function makeAlert(id: number, title: string): Alert {
  return {
    id,
    category: 'oil_energy',
    created_at: '2026-07-09T10:00:00+00:00',
    article: { id, title, url: `https://example.com/${id}` },
    companies: [],
  };
}

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe('mergeAlerts', () => {
  it('prepends live alerts and dedupes by id (live wins)', () => {
    const merged = mergeAlerts([makeAlert(2, 'two-live')], [makeAlert(1, 'one'), makeAlert(2, 'two')]);
    expect(merged.map((a) => a.id)).toEqual([2, 1]);
    expect(merged[0].article.title).toBe('two-live');
  });
});

describe('Feed', () => {
  it('renders alert cards from the initial fetch', async () => {
    vi.spyOn(api, 'getAlerts').mockResolvedValue([makeAlert(1, 'Oil news headline')]);
    render(
      <AuthProvider>
        <Feed />
      </AuthProvider>,
    );
    expect(await screen.findByText('Oil news headline')).toBeInTheDocument();
  });

  it('shows an empty state when there are no alerts', async () => {
    vi.spyOn(api, 'getAlerts').mockResolvedValue([]);
    render(
      <AuthProvider>
        <Feed />
      </AuthProvider>,
    );
    expect(await screen.findByText(/no alerts yet/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `frontend/`): `npm run test -- src/components/Feed.test.tsx`
Expected: FAIL — `Feed` does not exist yet.

- [ ] **Step 3: Implement Feed and replace FeedPage**

`frontend/src/components/Feed.tsx`:

```tsx
import { useEffect, useMemo, useState } from 'react';
import { getAlerts, type Alert } from '../lib/api';
import { useAuth } from '../lib/auth';
import { useAlertsSocket } from '../lib/useAlertsSocket';
import AlertCard from './AlertCard';

// Prepend live pushes ahead of the fetched list, deduping by id (a live entry
// for an id already present wins, since it is iterated first).
export function mergeAlerts(live: Alert[], fetched: Alert[]): Alert[] {
  const seen = new Set<number>();
  const merged: Alert[] = [];
  for (const alert of [...live, ...fetched]) {
    if (seen.has(alert.id)) continue;
    seen.add(alert.id);
    merged.push(alert);
  }
  return merged;
}

export default function Feed() {
  const { token } = useAuth();
  const [fetched, setFetched] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
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

  const alerts = useMemo(() => mergeAlerts(live, fetched), [live, fetched]);

  if (loading) {
    return <p className="text-xs uppercase tracking-widest text-muted">Loading…</p>;
  }
  if (error) {
    return <p className="text-xs uppercase tracking-widest text-bearish">{error}</p>;
  }
  if (alerts.length === 0) {
    return (
      <p className="text-xs uppercase tracking-widest text-muted">
        No alerts yet. New stories will appear here live.
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-5">
      {alerts.map((alert) => (
        <AlertCard key={alert.id} alert={alert} isAuthenticated={token !== null} />
      ))}
    </div>
  );
}
```

`frontend/src/pages/FeedPage.tsx` (replace the entire Task 7 placeholder):

```tsx
import Feed from '../components/Feed';

export default function FeedPage() {
  return (
    <main className="mx-auto max-w-feed px-4 py-8">
      <Feed />
    </main>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run (from `frontend/`): `npm run test -- src/components/Feed.test.tsx`
Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Feed.tsx frontend/src/components/Feed.test.tsx frontend/src/pages/FeedPage.tsx
git commit -m "feat: add live-merging Feed and wire it into FeedPage"
```

---

## Task 13: Holdings Form, CSV Upload, List & Page

**Files:**
- Create: `frontend/src/components/HoldingsForm.tsx`
- Create: `frontend/src/components/HoldingsCsvUpload.tsx`
- Create: `frontend/src/components/HoldingsList.tsx`
- Modify: `frontend/src/pages/HoldingsPage.tsx` (replace the Task 7 placeholder)
- Test: `frontend/src/components/HoldingsForm.test.tsx`
- Test: `frontend/src/components/HoldingsCsvUpload.test.tsx`
- Test: `frontend/src/components/HoldingsList.test.tsx`
- Test: `frontend/src/pages/HoldingsPage.test.tsx`

**Interfaces:**
- Consumes: `addHolding`, `uploadHoldingsCsv`, `getHoldings`, `Holding` type (Task 5), `useAuth()` (Task 6).
- Produces: `HoldingsForm` (`{ onAdded: (holding: Holding) => void }`), `HoldingsCsvUpload` (`{ onUploaded: () => void }`), `HoldingsList` (`{ holdings: Holding[] }`), and `HoldingsPage` (fetches holdings on mount, wires the three holdings endpoints, re-fetches after add/upload). Route guarding is already handled by `RequireAuth` in `App.tsx` (Task 7). Leaf of the holdings branch.

- [ ] **Step 1: Write the failing tests**

`frontend/src/components/HoldingsList.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import HoldingsList from './HoldingsList';

describe('HoldingsList', () => {
  it('shows an empty state with no holdings', () => {
    render(<HoldingsList holdings={[]} />);
    expect(screen.getByText(/no holdings yet/i)).toBeInTheDocument();
  });

  it('lists holdings with name, ticker and quantity', () => {
    render(<HoldingsList holdings={[{ company_id: 1, ticker: 'RELIANCE.NS', name: 'Reliance', quantity: 12 }]} />);
    expect(screen.getByText('Reliance')).toBeInTheDocument();
    expect(screen.getByText('RELIANCE.NS')).toBeInTheDocument();
    expect(screen.getByText('12')).toBeInTheDocument();
  });
});
```

`frontend/src/components/HoldingsForm.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import HoldingsForm from './HoldingsForm';
import { AuthProvider } from '../lib/auth';
import * as api from '../lib/api';

function setToken() {
  localStorage.setItem('newsflo.token', 'tok');
  localStorage.setItem('newsflo.email', 'a@example.com');
}

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe('HoldingsForm', () => {
  it('validates ticker and a positive quantity', async () => {
    setToken();
    render(
      <AuthProvider>
        <HoldingsForm onAdded={() => {}} />
      </AuthProvider>,
    );
    await userEvent.click(screen.getByRole('button', { name: /add/i }));
    expect(screen.getByRole('alert')).toHaveTextContent(/ticker and a positive quantity/i);
  });

  it('adds a holding and calls onAdded', async () => {
    setToken();
    const spy = vi
      .spyOn(api, 'addHolding')
      .mockResolvedValue({ company_id: 1, ticker: 'RELIANCE.NS', name: 'Reliance', quantity: 5 });
    const onAdded = vi.fn();
    render(
      <AuthProvider>
        <HoldingsForm onAdded={onAdded} />
      </AuthProvider>,
    );
    await userEvent.type(screen.getByLabelText(/ticker/i), 'RELIANCE.NS');
    await userEvent.type(screen.getByLabelText(/quantity/i), '5');
    await userEvent.click(screen.getByRole('button', { name: /add/i }));
    await waitFor(() => expect(onAdded).toHaveBeenCalled());
    expect(spy).toHaveBeenCalledWith('tok', 'RELIANCE.NS', 5);
  });
});
```

`frontend/src/components/HoldingsCsvUpload.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import HoldingsCsvUpload from './HoldingsCsvUpload';
import { AuthProvider } from '../lib/auth';
import * as api from '../lib/api';

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe('HoldingsCsvUpload', () => {
  it('uploads a selected CSV file and reports the loaded count', async () => {
    localStorage.setItem('newsflo.token', 'tok');
    localStorage.setItem('newsflo.email', 'a@example.com');
    const spy = vi.spyOn(api, 'uploadHoldingsCsv').mockResolvedValue({ loaded: 2 });
    const onUploaded = vi.fn();
    render(
      <AuthProvider>
        <HoldingsCsvUpload onUploaded={onUploaded} />
      </AuthProvider>,
    );
    const file = new File(['Ticker,Quantity\nRELIANCE.NS,10\n'], 'holdings.csv', { type: 'text/csv' });
    await userEvent.upload(screen.getByLabelText(/upload holdings csv/i), file);
    await waitFor(() => expect(onUploaded).toHaveBeenCalled());
    expect(spy).toHaveBeenCalled();
    expect(screen.getByText(/loaded 2 holdings/i)).toBeInTheDocument();
  });
});
```

`frontend/src/pages/HoldingsPage.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import HoldingsPage from './HoldingsPage';
import { AuthProvider } from '../lib/auth';
import * as api from '../lib/api';

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe('HoldingsPage', () => {
  it('fetches and lists the user holdings on mount', async () => {
    localStorage.setItem('newsflo.token', 'tok');
    localStorage.setItem('newsflo.email', 'a@example.com');
    vi.spyOn(api, 'getHoldings').mockResolvedValue([
      { company_id: 1, ticker: 'RELIANCE.NS', name: 'Reliance', quantity: 3 },
    ]);
    render(
      <AuthProvider>
        <HoldingsPage />
      </AuthProvider>,
    );
    expect(await screen.findByText('Reliance')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from `frontend/`): `npm run test -- src/components/HoldingsForm.test.tsx src/components/HoldingsCsvUpload.test.tsx src/components/HoldingsList.test.tsx src/pages/HoldingsPage.test.tsx`
Expected: FAIL — none of the holdings components exist yet.

- [ ] **Step 3: Implement the holdings components and page**

`frontend/src/components/HoldingsForm.tsx`:

```tsx
import { useState, type FormEvent } from 'react';
import { addHolding, type Holding } from '../lib/api';
import { useAuth } from '../lib/auth';

export default function HoldingsForm({ onAdded }: { onAdded: (holding: Holding) => void }) {
  const { token } = useAuth();
  const [ticker, setTicker] = useState('');
  const [quantity, setQuantity] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!token) return;
    const qty = Number(quantity);
    if (!ticker.trim() || !Number.isFinite(qty) || qty <= 0) {
      setError('Enter a ticker and a positive quantity.');
      return;
    }
    setSubmitting(true);
    try {
      const holding = await addHolding(token, ticker.trim(), qty);
      onAdded(holding);
      setTicker('');
      setQuantity('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not add holding.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-3 sm:flex-row sm:items-end" aria-label="Add holding">
      <label className="flex flex-1 flex-col gap-1">
        <span className="text-xs uppercase tracking-widest text-muted">Ticker</span>
        <input
          value={ticker}
          onChange={(e) => setTicker(e.target.value)}
          placeholder="RELIANCE.NS"
          className="rounded-lg border border-hairline bg-surface px-3 py-2 text-ink outline-none focus:border-muted"
        />
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-xs uppercase tracking-widest text-muted">Quantity</span>
        <input
          value={quantity}
          onChange={(e) => setQuantity(e.target.value)}
          inputMode="decimal"
          className="rounded-lg border border-hairline bg-surface px-3 py-2 text-ink tabular-nums outline-none focus:border-muted"
        />
      </label>
      {error && <p role="alert" className="text-xs text-bearish">{error}</p>}
      <button
        type="submit"
        disabled={submitting}
        className="rounded-lg border border-hairline bg-surface px-4 py-2 text-xs uppercase tracking-widest text-ink disabled:opacity-50"
      >
        Add
      </button>
    </form>
  );
}
```

`frontend/src/components/HoldingsCsvUpload.tsx`:

```tsx
import { useRef, useState, type ChangeEvent } from 'react';
import { uploadHoldingsCsv } from '../lib/api';
import { useAuth } from '../lib/auth';

export default function HoldingsCsvUpload({ onUploaded }: { onUploaded: () => void }) {
  const { token } = useAuth();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleChange(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file || !token) return;
    setError(null);
    setStatus(null);
    try {
      const res = await uploadHoldingsCsv(token, file);
      setStatus(`Loaded ${res.loaded} holdings.`);
      onUploaded();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed.');
    } finally {
      if (inputRef.current) inputRef.current.value = '';
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <span className="text-xs uppercase tracking-widest text-muted">Upload CSV (Ticker,Quantity)</span>
      <input
        ref={inputRef}
        type="file"
        accept=".csv,text/csv"
        onChange={handleChange}
        aria-label="Upload holdings CSV"
        className="text-xs text-muted file:mr-3 file:rounded-lg file:border file:border-hairline file:bg-surface file:px-3 file:py-2 file:text-xs file:uppercase file:tracking-widest file:text-ink"
      />
      {status && <p className="text-xs text-bullish">{status}</p>}
      {error && <p role="alert" className="text-xs text-bearish">{error}</p>}
    </div>
  );
}
```

`frontend/src/components/HoldingsList.tsx`:

```tsx
import type { Holding } from '../lib/api';

export default function HoldingsList({ holdings }: { holdings: Holding[] }) {
  if (holdings.length === 0) {
    return <p className="text-xs uppercase tracking-widest text-muted">No holdings yet. Add one above.</p>;
  }
  return (
    <ul className="flex flex-col divide-y divide-hairline rounded-lg border border-hairline">
      {holdings.map((h) => (
        <li key={h.company_id} className="flex items-center justify-between px-4 py-3">
          <span className="flex flex-col">
            <span className="text-sm text-ink">{h.name}</span>
            <span className="text-xs uppercase tracking-widest text-muted">{h.ticker}</span>
          </span>
          <span className="text-sm tabular-nums text-ink">{h.quantity}</span>
        </li>
      ))}
    </ul>
  );
}
```

`frontend/src/pages/HoldingsPage.tsx` (replace the entire Task 7 placeholder):

```tsx
import { useCallback, useEffect, useState } from 'react';
import { getHoldings, type Holding } from '../lib/api';
import { useAuth } from '../lib/auth';
import HoldingsForm from '../components/HoldingsForm';
import HoldingsCsvUpload from '../components/HoldingsCsvUpload';
import HoldingsList from '../components/HoldingsList';

export default function HoldingsPage() {
  const { token } = useAuth();
  const [holdings, setHoldings] = useState<Holding[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    if (!token) return;
    getHoldings(token)
      .then((data) => {
        setHoldings(data);
        setError(null);
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : 'Failed to load holdings.'));
  }, [token]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return (
    <main className="mx-auto max-w-feed px-4 py-8">
      <h1 className="mb-6 font-display text-2xl font-bold text-ink">My Holdings</h1>
      <div className="flex flex-col gap-6">
        <HoldingsForm onAdded={refresh} />
        <HoldingsCsvUpload onUploaded={refresh} />
        {error && <p role="alert" className="text-xs text-bearish">{error}</p>}
        <HoldingsList holdings={holdings} />
      </div>
    </main>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run (from `frontend/`): `npm run test -- src/components/HoldingsForm.test.tsx src/components/HoldingsCsvUpload.test.tsx src/components/HoldingsList.test.tsx src/pages/HoldingsPage.test.tsx`
Expected: `6 passed` (2 form + 1 csv + 2 list + 1 page).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/HoldingsForm.tsx frontend/src/components/HoldingsCsvUpload.tsx frontend/src/components/HoldingsList.tsx frontend/src/pages/HoldingsPage.tsx frontend/src/components/HoldingsForm.test.tsx frontend/src/components/HoldingsCsvUpload.test.tsx frontend/src/components/HoldingsList.test.tsx frontend/src/pages/HoldingsPage.test.tsx
git commit -m "feat: add holdings form, CSV upload, list and page"
```

---

## Task 14: Full-App Verification — Build, Test Suites & Live-Push Demo

This task has no new automated test file. It (a) proves the frontend type-checks and builds, (b) runs both full test suites, and (c) verifies the end-to-end live-push experience a human can watch. It also adds one throwaway dev-only backend script used to trigger a demo alert.

**Files:**
- Create: `backend/demo_push.py` (dev-only demo runner — not imported by the app or tests)

- [ ] **Step 1: Confirm the frontend builds with zero TypeScript errors**

Run (from `frontend/`): `npm run build`
Expected: `tsc --noEmit` reports no errors, then `vite build` completes and writes `dist/`. Any `any`, unused local, or type mismatch fails this step — fix it before continuing.

- [ ] **Step 2: Run the full frontend test suite**

Run (from `frontend/`): `npm run test`
Expected: every Vitest suite from Tasks 4-13 passes (api, auth forms, NavBar, App routing, CategorySwatch, SentimentPill, CompanyChip, ReasoningPanel, AlertCard, useAlertsSocket, Feed, holdings).

- [ ] **Step 3: Run the full backend test suite**

Run (from `backend/`): `.venv/Scripts/pytest tests/ -v`
Expected: every Plan 1-3 test plus the three new WS tests pass, with no live network calls and the scheduler never starting (`ENABLE_SCHEDULER` unset).

- [ ] **Step 4: Add the dev-only live-push demo script**

`backend/demo_push.py`:

```python
"""Dev-only demo: run the NewsFlo backend and push one live alert on demand.

Not part of the test suite and not imported by the app. It starts uvicorn in a
background thread so the WebSocket server and the pipeline share ONE process
(therefore one ConnectionManager instance and one captured event loop). When you
press Enter it seeds an article and runs the pipeline, which broadcasts the new
alert to every browser connected to /ws/alerts — no page refresh required.

Usage (from the backend/ directory, so `app` is importable):
    .venv/Scripts/python demo_push.py
Then open the frontend (npm run dev -> http://localhost:5173) in a browser.
"""
import threading
import time

import uvicorn

import app.pipeline as pipeline_module
from app.analysis.schemas import AnalysisOutput, CompanyMention
from app.db import SessionLocal, init_db
from app.models import Article, Company


def _seed_company() -> None:
    session = SessionLocal()
    try:
        if session.query(Company).filter_by(ticker="RELIANCE.NS").one_or_none() is None:
            session.add(Company(
                ticker="RELIANCE.NS", name="Reliance Industries",
                sector="oil_gas", index_tier="NIFTY50", market_cap=1_800_000.0,
            ))
            session.commit()
    finally:
        session.close()


def _fake_analysis(client, title, content):
    return AnalysisOutput(
        category="oil_energy",
        companies=[CompanyMention(
            name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
            direction="bullish", magnitude_low=2.0, magnitude_high=4.0,
            rationale="Top refiner benefits from a crude price spike.",
        )],
    )


def _push_one_alert() -> None:
    # Same monkeypatch pattern as the pipeline tests — no real Claude call.
    pipeline_module.analyze_article = _fake_analysis
    session = SessionLocal()
    try:
        session.add(Article(
            source="demo", url=f"https://example.com/demo-{int(time.time())}",
            title="US strikes Iran oil export sites", content="Crude oil markets react sharply.",
        ))
        session.commit()
        created = pipeline_module.process_new_articles(session, claude_client=object())
        print(f"Pushed {created} alert(s) to connected clients.")
    finally:
        session.close()


def main() -> None:
    init_db()
    _seed_company()
    config = uvicorn.Config("app.main:app", host="127.0.0.1", port=8000, log_level="info")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    time.sleep(2)  # let the server start and its startup event capture the loop
    print("Backend running on http://127.0.0.1:8000")
    print("Open http://localhost:5173, then press Enter here to push a live alert (Ctrl+C to quit).")
    try:
        while True:
            input()
            _push_one_alert()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Manual end-to-end verification**

Run these two processes:

1. Backend + demo runner (from `backend/`): `.venv/Scripts/python demo_push.py` — serves the API and WebSocket on `:8000` and waits for Enter. (For a plain backend without the demo trigger you could instead run `.venv/Scripts/uvicorn app.main:app`, but `demo_push.py` is what lets you fire a mocked live alert with no Claude key.)
2. Frontend (from `frontend/`): `npm run dev` — serves the dashboard on `http://localhost:5173`, proxying `/api` and `/ws` to `:8000`.

Then, in a browser at `http://localhost:5173`, verify each of the following and note the expected observation:

- **Feed loads (anonymous):** the `/` feed renders. With an empty DB it shows "No alerts yet. New stories will appear here live." The page background is true-black, cards (once present) are a distinct dark-gray with a hairline border, headlines are bold serif, tabs/metadata are small tracked-uppercase — matching the CRED direction.
- **Register + login:** click Register, create `demo@example.com` / `pw12345`; you are redirected to the feed and the NavBar now shows your email + Logout.
- **Holdings CRUD:** go to Holdings; add `RELIANCE.NS` quantity `10` via the manual form — it appears in the list. Optionally upload a `Ticker,Quantity` CSV and confirm the loaded count and list update. (Navigating to `/holdings` while logged out instead redirects to `/login`.)
- **Live push without refresh:** with the feed open, switch back to the `demo_push.py` terminal and press Enter. A new card ("US strikes Iran oil export sites") appears at the top of the feed instantly, with no page reload. Expand it: the Predicted tab shows Reliance Industries under "Nifty 50" with a green `+2.0% to +4.0%` range; clicking the chip expands the reasoning panel. (The live-pushed card shows Reliance under My Demat only after the next full refresh, since live pushes carry `in_my_holdings: false` by design — reload the page and the held company now appears under My Demat too.)
- **Screenshot (if a browser tool is available):** if Playwright (or another browser automation tool) is available in the environment, navigate to `http://localhost:5173`, trigger the demo push, and capture a screenshot of the feed with the live card for the record. Otherwise, capture it manually.

- [ ] **Step 6: Commit**

```bash
git add backend/demo_push.py
git commit -m "chore: add dev-only live-push demo runner and verify full app"
```

---

## Definition of Done (Plan 4)

- **Backend WS tests pass:** `cd backend && .venv/Scripts/pytest tests/ -v` is green — every Plan 1-3 test plus `test_ws_manager.py` (7), `test_ws_endpoint.py` (3, including the pipeline→WebSocket live-push e2e). No live network calls; the scheduler never starts (`ENABLE_SCHEDULER` unset); `broadcast_sync` is a proven no-op when no client is connected, so no existing test regressed.
- **Frontend Vitest suite passes:** `cd frontend && npm run test` is green across every suite (api client, auth forms, NavBar, App routing, CategorySwatch, SentimentPill net majority-vote arithmetic, CompanyChip, ReasoningPanel, AlertCard tabs/tier-grouping/empty-states, useAlertsSocket reconnect+dedupe, Feed merge, holdings).
- **Frontend builds clean:** `cd frontend && npm run build` succeeds with zero TypeScript errors (`tsc --noEmit` clean — no `any`, no unused symbols, all API response types matching the backend's exact JSON field names).
- **Human-observable outcome:** with both dev servers running, a human can register/log in, add a holding (manual or CSV), and — with the feed open — watch a demo-triggered alert appear live at the top of the feed with **no page refresh**, rendered in the CRED-style treatment (true-black page, dark-gray hairline-bordered cards, bold serif headline, category swatch dot + tracked-uppercase label, Predicted/My Demat tabs, index-tier-grouped chips with colored +/- ranges, outlined Net Bullish/Bearish/Mixed pill, click-to-expand reasoning panel with the confidence-based historical-precedent line).
- **This is the final plan.** All four plans together deliver the v1 spec's full scope EXCEPT the following deliberately deferred/out-of-scope items, restated here for completeness:
  - Deferred from Plan 3 (documented there, no real credentials to build/test against): **OAuth** login (email/password + JWT is implemented), **real broker/demat integration** (Zerodha Kite Connect — manual entry + CSV upload is the built fallback path), and a **real transactional email provider** (Resend/SendGrid — the console/log email backend stands in, with a loud `NotImplementedError` where the real HTTP sender would go).
  - Spec's own "Out of Scope (v1)": **global market coverage** (Indian NSE/BSE only), **paid news data sources** (free RSS/APIs only), **push notifications** (email only; push is a fast-follow), and **automated trading / order execution** (the system produces signals and reasoning only — it never places trades).
