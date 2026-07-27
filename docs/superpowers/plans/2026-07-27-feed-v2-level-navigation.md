# Feed-v2 Level Navigation + Impact Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split feed-v2's stacked Level 1/2/3 modal into three real, separately-routed pages (each a complete stop with a door to the next, matching Level 4's existing pattern), and add the missing "Impact core" section (every directly-affected company + its own why) to Level 1.

**Architecture:** Backend adds one new pure read-time computation (`compute_impact_companies`, sibling to the existing `compute_alert_measurement`/`compute_ripple_companies`) and one new field on an existing endpoint response. Frontend replaces one modal-composing component (`Level1SummaryV2`) with three thin routed pages that each fetch the same existing `GET /api/feed-v2/{id}` endpoint and reuse the existing `RippleSection`/`TimelineSection` components verbatim — only their composition and navigation changes, not their content.

**Tech Stack:** FastAPI + SQLAlchemy (backend), React + react-router-dom + Tailwind (frontend), pytest (backend tests), Vitest + Testing Library (frontend tests), Playwright (screenshots).

## Global Constraints

- Spec source of truth: `docs/NEWS_IMPACT_APP_SPEC.md` §2 (progressive-disclosure levels — each a complete stop, reached via an explicit door to the next) and §1 (five data layers, including layer 2 "Directly affected stocks (impact core)").
- Design doc: `docs/superpowers/specs/2026-07-27-feed-v2-level-navigation-design.md` — read before starting; every task below implements one piece of it.
- Zero changes to the legacy `/` feed route (`FeedPage.tsx` and everything it renders) or its components — an established, repeatedly-enforced constraint across every prior feed-v2 phase.
- Zero changes to Level 4 (`StockDeepDivePage.tsx`, already a real route) or Level 0 (the feed list itself, `FeedRowV2.tsx`'s own rendering — only its `onOpen` wiring in `FeedV2.tsx` changes).
- Never fabricate: `why` is `null` when `refine_alert` never populated it (LLM call failure) — render nothing for that field, never a placeholder string.
- HARD RULE for any UI-facing task in this project: run the dev server and Playwright-screenshot every new/changed screen at 390px and 1920px, both dark and light mode, and actually look at the screenshots (via the Read tool) before calling the task done. This plan's final screenshot task is not optional.
- Full backend and frontend test suites must both pass with zero regressions before this plan is considered done.

---

## File Map

```
backend/app/market/alert_measurement.py   MODIFY — add compute_impact_companies
backend/app/routers/feed_v2.py            MODIFY — add impact_companies to GET /api/feed-v2/{id}
backend/tests/test_alert_measurement.py   MODIFY — tests for compute_impact_companies; extend _alert_company helper
backend/tests/test_feed_v2_router.py      MODIFY — router test for impact_companies key

frontend/src/lib/feedV2Api.ts             MODIFY — add ImpactCompany type, impact_companies field
frontend/src/pages/AlertLevel1Page.tsx    CREATE — Level 1: summary + impact core + door to ripple
frontend/src/pages/AlertLevel1Page.test.tsx CREATE
frontend/src/pages/AlertRipplePage.tsx    CREATE — Level 2: ripple + door to timeline
frontend/src/pages/AlertRipplePage.test.tsx CREATE
frontend/src/pages/AlertTimelinePage.tsx  CREATE — Level 3: timeline (no further door)
frontend/src/pages/AlertTimelinePage.test.tsx CREATE
frontend/src/App.tsx                      MODIFY — add 3 new routes
frontend/src/components/feed-v2/FeedV2.tsx MODIFY — onOpen navigates instead of opening a modal
frontend/src/components/feed-v2/FeedV2.test.tsx MODIFY — assert navigation, not modal content
frontend/src/components/feed-v2/Level1SummaryV2.tsx DELETE
frontend/src/components/feed-v2/Level1SummaryV2.test.tsx DELETE
frontend/e2e/feed-v2-screenshots.spec.ts  MODIFY — rewrite Level 1 case, add ripple/timeline cases
```

---

## Task 1: `compute_impact_companies` — the Impact core data layer

**Files:**
- Modify: `backend/app/market/alert_measurement.py`
- Test: `backend/tests/test_alert_measurement.py`

**Interfaces:**
- Consumes: `Session`, `Alert` (existing SQLAlchemy models — `Alert.companies` is a `relationship("AlertCompany", ...)`; `AlertCompany` has `impact_level: str` ("direct" | "indirect_l1" | "indirect_l2"), `direction: str`, `why: str | None`, `company: Company`; `Company` has `ticker: str`, `name: str`; `MarketMove` has `alert_id`, `company_id`, `excess_move_pct: float | None`, `measurement_status: str`).
- Produces: `compute_impact_companies(session: Session, alert: Alert) -> list[dict]`, each dict `{"ticker": str, "name": str, "direction": str, "excess_move_pct": float, "why": str | None}`. Consumed by Task 2.

**Context:** `compute_alert_measurement` (already in this file) picks exactly one "peak" company per alert — whichever measured company has the largest `|excess_move_pct|` — for the Level 0/1 headline number. That's correct for the headline, but the spec's data layer 2 ("Directly affected stocks") is the FULL list of every directly-named company, not just the peak. `AlertCompany.impact_level == "direct"` is exactly that set (see the field's own comment in `backend/app/models.py:145-150`: "direct" covers "both actually-direct mentions and sector-inference fan-out (both are the article's own primary impact)"; `indirect_l1`/`indirect_l2` are cascade/ripple companies, already handled by `compute_ripple_companies` in `app/market/ripple.py` — this task does not touch that file).

- [ ] **Step 1: Write the failing tests**

Open `backend/tests/test_alert_measurement.py`. First, extend the existing `_alert_company` helper (used by every test in this file) to accept an optional `impact_level`, defaulting to `"direct"` so every existing call site keeps working unchanged:

```python
def _alert_company(alert_id, company_id, direction="bullish", impact_level="direct"):
    return AlertCompany(
        alert_id=alert_id, company_id=company_id, direction=direction,
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", basis="direct_mention",
        impact_level=impact_level,
    )
```

Then add these tests at the end of the file:

```python
from app.market.alert_measurement import compute_impact_companies


def test_impact_companies_includes_every_direct_measured_company(db_session):
    a = _company("A.NS")
    b = _company("B.NS")
    db_session.add_all([a, b])
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, a.id, direction="bearish"))
    db_session.add(_alert_company(alert.id, b.id, direction="bullish"))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=a.id, benchmark_ticker="^CNXENERGY",
        excess_move_pct=-4.2, measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=b.id, benchmark_ticker="^CNXENERGY",
        excess_move_pct=1.5, measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    result = compute_impact_companies(db_session, alert)

    tickers = [r["ticker"] for r in result]
    assert tickers == ["A.NS", "B.NS"]  # sorted by |excess_move_pct| descending
    assert result[0]["direction"] == "bearish"
    assert result[0]["excess_move_pct"] == -4.2
    assert result[1]["name"] == "Company B.NS"


def test_impact_companies_excludes_indirect_companies(db_session):
    direct = _company("A.NS")
    indirect = _company("B.NS")
    db_session.add_all([direct, indirect])
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, direct.id))
    db_session.add(_alert_company(alert.id, indirect.id, impact_level="indirect_l1"))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=direct.id, benchmark_ticker="^CNXENERGY",
        excess_move_pct=2.0, measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=indirect.id, benchmark_ticker="^CNXENERGY",
        excess_move_pct=9.0, measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    result = compute_impact_companies(db_session, alert)

    assert [r["ticker"] for r in result] == ["A.NS"]


def test_impact_companies_excludes_unmeasured_companies(db_session):
    measured = _company("A.NS")
    unmeasured = _company("B.NS")
    db_session.add_all([measured, unmeasured])
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, measured.id))
    db_session.add(_alert_company(alert.id, unmeasured.id))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=measured.id, benchmark_ticker="^CNXENERGY",
        excess_move_pct=2.0, measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=unmeasured.id, benchmark_ticker="^NSEI",
        measurement_status="no_data", measured_at=utcnow(),
    ))
    db_session.commit()

    result = compute_impact_companies(db_session, alert)

    assert [r["ticker"] for r in result] == ["A.NS"]


def test_impact_companies_includes_why_when_present(db_session):
    company = _company("A.NS")
    db_session.add(company)
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    ac = _alert_company(alert.id, company.id)
    ac.why = "Higher crude prices lift upstream margins."
    db_session.add(ac)
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^CNXENERGY",
        excess_move_pct=2.0, measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    result = compute_impact_companies(db_session, alert)

    assert result[0]["why"] == "Higher crude prices lift upstream margins."


def test_impact_companies_why_is_none_when_not_populated(db_session):
    company = _company("A.NS")
    db_session.add(company)
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, company.id))  # why left unset -- defaults to None
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^CNXENERGY",
        excess_move_pct=2.0, measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    result = compute_impact_companies(db_session, alert)

    assert result[0]["why"] is None


def test_impact_companies_returns_empty_list_when_none_qualify(db_session):
    company = _company("A.NS")
    db_session.add(company)
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, company.id, impact_level="indirect_l1"))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^CNXENERGY",
        excess_move_pct=2.0, measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    assert compute_impact_companies(db_session, alert) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_alert_measurement.py -k impact_companies -v`
Expected: FAIL with `ImportError: cannot import name 'compute_impact_companies'`.

- [ ] **Step 3: Implement `compute_impact_companies`**

Add to `backend/app/market/alert_measurement.py`, after `compute_alert_measurement`:

```python
def compute_impact_companies(session: Session, alert: Alert) -> list[dict]:
    """Every directly-affected company for this alert (spec §1 layer 2,
    "Impact core") -- AlertCompany.impact_level == "direct" AND a real
    measured excess move (measurement_status == "ok"). Distinct from
    compute_alert_measurement's single "peak" company: this returns the
    FULL set (peak included), each with its own excess_move_pct, direction,
    and why (refine_alert-populated causal text, None if that LLM call
    never succeeded -- never fabricated). indirect_l1/indirect_l2 companies
    are excluded -- those are cascade/ripple companies, already surfaced by
    app.market.ripple.compute_ripple_companies. Sorted by |excess_move_pct|
    descending, same ordering discipline as the rest of this module. Never
    raises; returns [] when nothing qualifies (omit rather than fabricate).
    """
    moves_by_company_id = {
        m.company_id: m
        for m in session.query(MarketMove)
        .filter(MarketMove.alert_id == alert.id, MarketMove.measurement_status == "ok")
        .all()
    }

    results = []
    for alert_company in alert.companies:
        if alert_company.impact_level != "direct":
            continue
        move = moves_by_company_id.get(alert_company.company_id)
        if move is None or move.excess_move_pct is None:
            continue
        results.append({
            "ticker": alert_company.company.ticker,
            "name": alert_company.company.name,
            "direction": alert_company.direction,
            "excess_move_pct": move.excess_move_pct,
            "why": alert_company.why,
        })

    results.sort(key=lambda r: abs(r["excess_move_pct"]), reverse=True)
    return results
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_alert_measurement.py -v`
Expected: all PASS (existing tests + 6 new ones).

- [ ] **Step 5: Commit**

```bash
git add backend/app/market/alert_measurement.py backend/tests/test_alert_measurement.py
git commit -m "feat: add compute_impact_companies -- spec's Impact core data layer"
```

---

## Task 2: Wire `impact_companies` into `GET /api/feed-v2/{alert_id}`

**Files:**
- Modify: `backend/app/routers/feed_v2.py`
- Test: `backend/tests/test_feed_v2_router.py`

**Interfaces:**
- Consumes: `compute_impact_companies(session, alert) -> list[dict]` (Task 1).
- Produces: `GET /api/feed-v2/{alert_id}` response gains an `impact_companies` key. `GET /api/feed-v2` (the list endpoint) is unchanged.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_feed_v2_router.py`, after `_unmeasured_alert`:

```python
def _multi_company_alert(db_session):
    a = Company(ticker="A.NS", name="Company A", sector="oil_gas", index_tier="NIFTY50")
    b = Company(ticker="B.NS", name="Company B", sector="oil_gas", index_tier="NIFTY50")
    db_session.add_all([a, b])
    db_session.commit()
    article = Article(source="test", url="https://example.com/multi", title="Oil news", content="c")
    db_session.add(article)
    db_session.commit()
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=a.id, direction="bearish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", basis="direct_mention",
        impact_level="direct", why="Crude spike raises input costs.",
    ))
    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=b.id, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", basis="direct_mention",
        impact_level="direct",
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=a.id, benchmark_ticker="^CNXENERGY",
        excess_move_pct=-4.2, measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=b.id, benchmark_ticker="^CNXENERGY",
        excess_move_pct=1.1, measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()
    return alert


def test_get_feed_v2_alert_includes_impact_companies(db_session):
    _override_db(db_session)
    alert = _multi_company_alert(db_session)
    client = TestClient(app)

    response = client.get(f"/api/feed-v2/{alert.id}")

    assert response.status_code == 200
    body = response.json()
    assert len(body["impact_companies"]) == 2
    assert body["impact_companies"][0]["ticker"] == "A.NS"
    assert body["impact_companies"][0]["why"] == "Crude spike raises input costs."
    assert body["impact_companies"][1]["why"] is None
    app.dependency_overrides.clear()


def test_list_feed_v2_does_not_include_impact_companies(db_session):
    _override_db(db_session)
    _measured_alert(db_session)
    client = TestClient(app)

    response = client.get("/api/feed-v2")

    assert response.status_code == 200
    assert "impact_companies" not in response.json()[0]
    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_feed_v2_router.py -k impact_companies -v`
Expected: FAIL — `KeyError: 'impact_companies'`.

- [ ] **Step 3: Wire it in**

In `backend/app/routers/feed_v2.py`, add the import:

```python
from app.market.alert_measurement import compute_alert_measurement, compute_impact_companies
```

And in `get_feed_v2_alert`, after the existing `result["ripple"] = ...` line, add:

```python
    result["impact_companies"] = compute_impact_companies(db, alert)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_feed_v2_router.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/feed_v2.py backend/tests/test_feed_v2_router.py
git commit -m "feat: expose impact_companies on GET /api/feed-v2/{alert_id}"
```

---

## Task 3: `AlertLevel1Page` — Level 1 as a real route, with Impact core

**Files:**
- Modify: `frontend/src/lib/feedV2Api.ts`
- Create: `frontend/src/pages/AlertLevel1Page.tsx`
- Test: `frontend/src/pages/AlertLevel1Page.test.tsx`

**Interfaces:**
- Consumes: `getFeedV2Alert(id, token) -> Promise<FeedV2Alert>` (existing, `frontend/src/lib/feedV2Api.ts`); `verdictLabel(verdict) -> string`, `formatExcess(pct) -> {arrow, text}` (existing, `frontend/src/lib/feedV2Format.ts`); `useAuth() -> {token}` (existing, `frontend/src/lib/auth.tsx`).
- Produces: default-exported `AlertLevel1Page` component, rendered at route `/feed-v2/alert/:id` (wired in Task 6). Renders a `Link` to `/feed-v2/alert/:id/ripple` (consumed by Task 6's route wiring and Task 7's screenshot test) and impact-core rows that `navigate` to `/feed-v2/stock/:ticker?alertId=:id` (Level 4, already exists).

- [ ] **Step 1: Add the `ImpactCompany` type**

In `frontend/src/lib/feedV2Api.ts`, add after the `TimelineEntry` interface:

```ts
export interface ImpactCompany {
  ticker: string;
  name: string;
  direction: 'bullish' | 'bearish';
  excess_move_pct: number;
  why: string | null;
}
```

And add to `FeedV2Alert` (after the existing `timeline?: TimelineEntry[];` line):

```ts
  impact_companies?: ImpactCompany[];
```

- [ ] **Step 2: Write the failing test**

Create `frontend/src/pages/AlertLevel1Page.test.tsx`:

```tsx
import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import AlertLevel1Page from './AlertLevel1Page';
import * as feedV2Api from '../lib/feedV2Api';
import { AuthProvider } from '../lib/auth';
import type { FeedV2Alert } from '../lib/feedV2Api';

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return { ...actual, useNavigate: () => mockNavigate };
});

function makeAlert(overrides: Partial<FeedV2Alert> = {}): FeedV2Alert {
  return {
    id: 1,
    category: 'oil_gas',
    created_at: '2026-07-22T10:00:00Z',
    summary_short: 'Oil supply shock lifts refiners',
    summary_long: 'Crude prices jumped on a supply disruption. Refiners face wider margin pressure.',
    article: { id: 1, title: 'Oil surges', url: 'https://example.com/a', source: 'Economic Times', published_at: null },
    excess_move_pct: -4.2,
    direction: 'bearish',
    raw_move_pct: -4.8,
    sector_move_pct: -0.6,
    volume_multiple: 3.1,
    benchmark_ticker: '^CNXENERGY',
    is_fallback_benchmark: false,
    peak_ticker: 'RELIANCE.NS',
    peak_company_name: 'Reliance Industries',
    verdict: 'COMPANY_SPECIFIC',
    intensity: { score: 82, band: 'High', components: [] },
    breadth_score: 40,
    in_my_holdings: false,
    impact_companies: [
      { ticker: 'RELIANCE.NS', name: 'Reliance Industries', direction: 'bearish', excess_move_pct: -4.2, why: 'Refining margins compress as crude input costs rise.' },
      { ticker: 'ONGC.NS', name: 'ONGC', direction: 'bullish', excess_move_pct: 2.1, why: null },
    ],
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/feed-v2/alert/1']}>
      <AuthProvider>
        <Routes>
          <Route path="/feed-v2/alert/:id" element={<AlertLevel1Page />} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe('AlertLevel1Page', () => {
  it('renders the summary, raw/sector move, and volume', async () => {
    vi.spyOn(feedV2Api, 'getFeedV2Alert').mockResolvedValue(makeAlert());
    renderPage();
    await waitFor(() => expect(screen.getByText(/Crude prices jumped/)).toBeInTheDocument());
    expect(screen.getByText('-4.8%')).toBeInTheDocument();
    expect(screen.getByText('-0.6%')).toBeInTheDocument();
    expect(screen.getByText('3.1× average volume')).toBeInTheDocument();
  });

  it('renders one impact-core row per directly-affected company, with why when present', async () => {
    vi.spyOn(feedV2Api, 'getFeedV2Alert').mockResolvedValue(makeAlert());
    renderPage();
    await waitFor(() => expect(screen.getByText('RELIANCE.NS')).toBeInTheDocument());
    expect(screen.getByText('ONGC.NS')).toBeInTheDocument();
    expect(screen.getByText('Refining margins compress as crude input costs rise.')).toBeInTheDocument();
  });

  it('navigates to the stock deep-dive when an impact-core row is clicked', async () => {
    vi.spyOn(feedV2Api, 'getFeedV2Alert').mockResolvedValue(makeAlert());
    renderPage();
    await waitFor(() => screen.getByText('RELIANCE.NS'));
    fireEvent.click(screen.getByRole('button', { name: /RELIANCE\.NS/ }));
    expect(mockNavigate).toHaveBeenCalledWith('/feed-v2/stock/RELIANCE.NS?alertId=1');
  });

  it('renders a door to the ripple level', async () => {
    vi.spyOn(feedV2Api, 'getFeedV2Alert').mockResolvedValue(makeAlert());
    renderPage();
    await waitFor(() => screen.getByText(/Crude prices jumped/));
    expect(screen.getByRole('link', { name: /See ripple/ })).toHaveAttribute('href', '/feed-v2/alert/1/ripple');
  });

  it('shows "Alert not found" when the fetch fails', async () => {
    vi.spyOn(feedV2Api, 'getFeedV2Alert').mockRejectedValue(new Error('404'));
    renderPage();
    await waitFor(() => expect(screen.getByText('Alert not found.')).toBeInTheDocument());
  });
});
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd frontend && npm test -- --run AlertLevel1Page`
Expected: FAIL — `Failed to resolve import "./AlertLevel1Page"`.

- [ ] **Step 4: Implement `AlertLevel1Page`**

Create `frontend/src/pages/AlertLevel1Page.tsx`:

```tsx
import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { formatExcess, verdictLabel } from '../lib/feedV2Format';
import { getFeedV2Alert, type FeedV2Alert } from '../lib/feedV2Api';
import { useAuth } from '../lib/auth';

function signedPct(value: number): string {
  const sign = value >= 0 ? '+' : '';
  return `${sign}${value.toFixed(1)}%`;
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

export default function AlertLevel1Page() {
  const { id } = useParams<{ id: string }>();
  const alertId = id !== undefined ? Number(id) : undefined;
  const { token } = useAuth();
  const navigate = useNavigate();

  const [alert, setAlert] = useState<FeedV2Alert | null | undefined>(undefined);

  useEffect(() => {
    if (alertId === undefined) return;
    let active = true;
    setAlert(undefined);
    getFeedV2Alert(alertId, token)
      .then((data) => {
        if (active) setAlert(data);
      })
      .catch(() => {
        if (active) setAlert(null);
      });
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [alertId, token]);

  if (alert === undefined) return null;

  if (alert === null) {
    return (
      <main className="mx-auto w-full max-w-3xl px-4 py-8">
        <p className="font-sans text-sm text-muted">Alert not found.</p>
      </main>
    );
  }

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-col gap-3 px-4 py-8">
      <Link to="/feed-v2" className="font-sans text-xs text-muted underline">
        ← Feed
      </Link>

      <div className="rounded-lg bg-surface p-5">
        <span className="rounded-full bg-elevated px-2 py-0.5 text-[11px] uppercase tracking-widest text-muted">
          {verdictLabel(alert.verdict)}
        </span>
        {alert.summary_long && (
          <p className="mt-3 font-sans text-sm text-ink">{alert.summary_long}</p>
        )}
      </div>

      <div className="rounded-lg bg-surface p-5">
        <div className="flex gap-6">
          <div>
            <div className="font-sans text-xs text-muted">Raw move</div>
            <div
              className={`font-data text-lg font-medium ${
                alert.raw_move_pct >= 0 ? 'text-bullish' : 'text-bearish'
              }`}
            >
              {signedPct(alert.raw_move_pct)}
            </div>
          </div>
          <div>
            <div className="font-sans text-xs text-muted">Sector move</div>
            <div className="font-data text-lg font-medium text-muted">{signedPct(alert.sector_move_pct)}</div>
          </div>
        </div>
        {alert.volume_multiple !== null && (
          <div className="mt-3 font-data text-sm text-ink">
            {alert.volume_multiple.toFixed(1)}× average volume
          </div>
        )}
      </div>

      <div className="rounded-lg bg-surface p-5">
        <div className="font-sans text-xs text-muted">
          {alert.article.source} &middot; {alert.is_fallback_benchmark ? 'vs Nifty 50' : 'vs sector index'}
        </div>
        <time className="mt-1 block font-sans text-xs text-muted" dateTime={alert.created_at}>
          {formatTime(alert.created_at)}
        </time>
      </div>

      {alert.impact_companies && alert.impact_companies.length > 0 && (
        <div className="rounded-lg bg-surface p-5">
          <div className="font-sans text-[11px] uppercase tracking-widest text-muted">Affected companies</div>
          <div className="mt-3 flex flex-col gap-4">
            {alert.impact_companies.map((company) => (
              <div
                key={company.ticker}
                role="button"
                tabIndex={0}
                aria-label={company.ticker}
                onClick={() => navigate(`/feed-v2/stock/${company.ticker}?alertId=${alert.id}`)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    navigate(`/feed-v2/stock/${company.ticker}?alertId=${alert.id}`);
                  }
                }}
                className="cursor-pointer"
              >
                <div className="flex items-center gap-3">
                  <span className="font-data text-[11px] text-muted">{company.ticker}</span>
                  <span
                    className={`font-data text-xs ${
                      company.direction === 'bullish' ? 'text-bullish' : 'text-bearish'
                    }`}
                  >
                    {formatExcess(company.excess_move_pct).text}
                  </span>
                </div>
                {company.why && <p className="mt-1 font-sans text-[13px] text-ink">{company.why}</p>}
              </div>
            ))}
          </div>
        </div>
      )}

      <Link to={`/feed-v2/alert/${alert.id}/ripple`} className="self-end font-sans text-xs text-muted underline">
        See ripple →
      </Link>
    </main>
  );
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd frontend && npm test -- --run AlertLevel1Page`
Expected: all 5 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/feedV2Api.ts frontend/src/pages/AlertLevel1Page.tsx frontend/src/pages/AlertLevel1Page.test.tsx
git commit -m "feat: AlertLevel1Page -- Level 1 as a real route, with Impact core"
```

---

## Task 4: `AlertRipplePage` — Level 2 as a real route

**Files:**
- Create: `frontend/src/pages/AlertRipplePage.tsx`
- Test: `frontend/src/pages/AlertRipplePage.test.tsx`

**Interfaces:**
- Consumes: `getFeedV2Alert` (existing); `RippleSection` (existing, `frontend/src/components/feed-v2/RippleSection.tsx`, props `{companies: RippleCompany[], alertId: number}`, unchanged).
- Produces: default-exported `AlertRipplePage`, rendered at `/feed-v2/alert/:id/ripple` (wired in Task 6). Renders a `Link` back to `/feed-v2/alert/:id` and forward to `/feed-v2/alert/:id/timeline`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/pages/AlertRipplePage.test.tsx`:

```tsx
import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import AlertRipplePage from './AlertRipplePage';
import * as feedV2Api from '../lib/feedV2Api';
import { AuthProvider } from '../lib/auth';
import type { FeedV2Alert } from '../lib/feedV2Api';

function makeAlert(overrides: Partial<FeedV2Alert> = {}): FeedV2Alert {
  return {
    id: 1,
    category: 'oil_gas',
    created_at: '2026-07-22T10:00:00Z',
    summary_short: 'Oil supply shock lifts refiners',
    summary_long: null,
    article: { id: 1, title: 'Oil surges', url: 'https://example.com/a', source: 'test', published_at: null },
    excess_move_pct: -4.2,
    direction: 'bearish',
    raw_move_pct: -4.8,
    sector_move_pct: -0.6,
    volume_multiple: 3.1,
    benchmark_ticker: '^CNXENERGY',
    is_fallback_benchmark: false,
    peak_ticker: 'RELIANCE.NS',
    peak_company_name: 'Reliance Industries',
    verdict: 'COMPANY_SPECIFIC',
    intensity: { score: 82, band: 'High', components: [] },
    breadth_score: 40,
    in_my_holdings: false,
    ripple: [
      {
        ticker: 'BPCL.NS', name: 'Bharat Petroleum', sector: 'oil_gas', cap_tier: 'LARGE',
        business_desc: 'Refines petroleum.', relationship: 'BENEFICIARY', direction: 'bullish',
        excess_move_pct: 3.0, intensity: { score: 70, band: 'Moderate', components: [] },
        is_exposure_only: false, in_my_holdings: false,
      },
    ],
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/feed-v2/alert/1/ripple']}>
      <AuthProvider>
        <Routes>
          <Route path="/feed-v2/alert/:id/ripple" element={<AlertRipplePage />} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe('AlertRipplePage', () => {
  it('renders the ripple companies', async () => {
    vi.spyOn(feedV2Api, 'getFeedV2Alert').mockResolvedValue(makeAlert());
    renderPage();
    await waitFor(() => expect(screen.getByText('BPCL.NS')).toBeInTheDocument());
    expect(screen.getByText('Beneficiary (1)')).toBeInTheDocument();
  });

  it('renders a door back to Level 1 and forward to the timeline', async () => {
    vi.spyOn(feedV2Api, 'getFeedV2Alert').mockResolvedValue(makeAlert());
    renderPage();
    await waitFor(() => screen.getByText('BPCL.NS'));
    expect(screen.getByRole('link', { name: /Summary/ })).toHaveAttribute('href', '/feed-v2/alert/1');
    expect(screen.getByRole('link', { name: /See timeline/ })).toHaveAttribute(
      'href', '/feed-v2/alert/1/timeline',
    );
  });

  it('shows "Alert not found" when the fetch fails', async () => {
    vi.spyOn(feedV2Api, 'getFeedV2Alert').mockRejectedValue(new Error('404'));
    renderPage();
    await waitFor(() => expect(screen.getByText('Alert not found.')).toBeInTheDocument());
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npm test -- --run AlertRipplePage`
Expected: FAIL — `Failed to resolve import "./AlertRipplePage"`.

- [ ] **Step 3: Implement `AlertRipplePage`**

Create `frontend/src/pages/AlertRipplePage.tsx`:

```tsx
import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import RippleSection from '../components/feed-v2/RippleSection';
import { getFeedV2Alert, type FeedV2Alert } from '../lib/feedV2Api';
import { useAuth } from '../lib/auth';

export default function AlertRipplePage() {
  const { id } = useParams<{ id: string }>();
  const alertId = id !== undefined ? Number(id) : undefined;
  const { token } = useAuth();

  const [alert, setAlert] = useState<FeedV2Alert | null | undefined>(undefined);

  useEffect(() => {
    if (alertId === undefined) return;
    let active = true;
    setAlert(undefined);
    getFeedV2Alert(alertId, token)
      .then((data) => {
        if (active) setAlert(data);
      })
      .catch(() => {
        if (active) setAlert(null);
      });
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [alertId, token]);

  if (alert === undefined) return null;

  if (alert === null) {
    return (
      <main className="mx-auto w-full max-w-3xl px-4 py-8">
        <p className="font-sans text-sm text-muted">Alert not found.</p>
      </main>
    );
  }

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-col gap-3 px-4 py-8">
      <Link to={`/feed-v2/alert/${alert.id}`} className="font-sans text-xs text-muted underline">
        ← Summary
      </Link>

      {alert.ripple && <RippleSection companies={alert.ripple} alertId={alert.id} />}

      <Link
        to={`/feed-v2/alert/${alert.id}/timeline`}
        className="self-end font-sans text-xs text-muted underline"
      >
        See timeline →
      </Link>
    </main>
  );
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npm test -- --run AlertRipplePage`
Expected: all 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/AlertRipplePage.tsx frontend/src/pages/AlertRipplePage.test.tsx
git commit -m "feat: AlertRipplePage -- Level 2 as a real route"
```

---

## Task 5: `AlertTimelinePage` — Level 3 as a real route

**Files:**
- Create: `frontend/src/pages/AlertTimelinePage.tsx`
- Test: `frontend/src/pages/AlertTimelinePage.test.tsx`

**Interfaces:**
- Consumes: `getFeedV2Alert` (existing); `TimelineSection` (existing, `frontend/src/components/feed-v2/TimelineSection.tsx`, props `{entries: TimelineEntry[]}`, unchanged).
- Produces: default-exported `AlertTimelinePage`, rendered at `/feed-v2/alert/:id/timeline` (wired in Task 6). Renders a `Link` back to `/feed-v2/alert/:id/ripple`. No forward door — Level 3 is the last of the news-event levels (Level 4 is reached from Level 1's impact-core rows or Level 2's peer rows, not from the timeline).

- [ ] **Step 1: Write the failing test**

Create `frontend/src/pages/AlertTimelinePage.test.tsx`:

```tsx
import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import AlertTimelinePage from './AlertTimelinePage';
import * as feedV2Api from '../lib/feedV2Api';
import { AuthProvider } from '../lib/auth';
import type { FeedV2Alert } from '../lib/feedV2Api';

function makeAlert(overrides: Partial<FeedV2Alert> = {}): FeedV2Alert {
  return {
    id: 1,
    category: 'oil_gas',
    created_at: '2026-07-22T10:00:00Z',
    summary_short: 'Oil supply shock lifts refiners',
    summary_long: null,
    article: { id: 1, title: 'Oil surges', url: 'https://example.com/a', source: 'test', published_at: null },
    excess_move_pct: -4.2,
    direction: 'bearish',
    raw_move_pct: -4.8,
    sector_move_pct: -0.6,
    volume_multiple: 3.1,
    benchmark_ticker: '^CNXENERGY',
    is_fallback_benchmark: false,
    peak_ticker: 'RELIANCE.NS',
    peak_company_name: 'Reliance Industries',
    verdict: 'COMPANY_SPECIFIC',
    intensity: { score: 82, band: 'High', components: [] },
    breadth_score: 40,
    in_my_holdings: false,
    timeline: [{ horizon: 'TODAY', description: 'Markets react immediately to the supply shock.' }],
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/feed-v2/alert/1/timeline']}>
      <AuthProvider>
        <Routes>
          <Route path="/feed-v2/alert/:id/timeline" element={<AlertTimelinePage />} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe('AlertTimelinePage', () => {
  it('renders the timeline entries', async () => {
    vi.spyOn(feedV2Api, 'getFeedV2Alert').mockResolvedValue(makeAlert());
    renderPage();
    await waitFor(() =>
      expect(screen.getByText('Markets react immediately to the supply shock.')).toBeInTheDocument(),
    );
    expect(screen.getByText('Today')).toBeInTheDocument();
  });

  it('renders a door back to the ripple level', async () => {
    vi.spyOn(feedV2Api, 'getFeedV2Alert').mockResolvedValue(makeAlert());
    renderPage();
    await waitFor(() => screen.getByText('Today'));
    expect(screen.getByRole('link', { name: /Ripple/ })).toHaveAttribute('href', '/feed-v2/alert/1/ripple');
  });

  it('shows "Alert not found" when the fetch fails', async () => {
    vi.spyOn(feedV2Api, 'getFeedV2Alert').mockRejectedValue(new Error('404'));
    renderPage();
    await waitFor(() => expect(screen.getByText('Alert not found.')).toBeInTheDocument());
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npm test -- --run AlertTimelinePage`
Expected: FAIL — `Failed to resolve import "./AlertTimelinePage"`.

- [ ] **Step 3: Implement `AlertTimelinePage`**

Create `frontend/src/pages/AlertTimelinePage.tsx`:

```tsx
import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import TimelineSection from '../components/feed-v2/TimelineSection';
import { getFeedV2Alert, type FeedV2Alert } from '../lib/feedV2Api';
import { useAuth } from '../lib/auth';

export default function AlertTimelinePage() {
  const { id } = useParams<{ id: string }>();
  const alertId = id !== undefined ? Number(id) : undefined;
  const { token } = useAuth();

  const [alert, setAlert] = useState<FeedV2Alert | null | undefined>(undefined);

  useEffect(() => {
    if (alertId === undefined) return;
    let active = true;
    setAlert(undefined);
    getFeedV2Alert(alertId, token)
      .then((data) => {
        if (active) setAlert(data);
      })
      .catch(() => {
        if (active) setAlert(null);
      });
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [alertId, token]);

  if (alert === undefined) return null;

  if (alert === null) {
    return (
      <main className="mx-auto w-full max-w-3xl px-4 py-8">
        <p className="font-sans text-sm text-muted">Alert not found.</p>
      </main>
    );
  }

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-col gap-3 px-4 py-8">
      <Link to={`/feed-v2/alert/${alert.id}/ripple`} className="font-sans text-xs text-muted underline">
        ← Ripple
      </Link>

      {alert.timeline && <TimelineSection entries={alert.timeline} />}
    </main>
  );
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npm test -- --run AlertTimelinePage`
Expected: all 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/AlertTimelinePage.tsx frontend/src/pages/AlertTimelinePage.test.tsx
git commit -m "feat: AlertTimelinePage -- Level 3 as a real route"
```

---

## Task 6: Wire the routes, retire the modal, delete `Level1SummaryV2`

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/feed-v2/FeedV2.tsx`
- Modify: `frontend/src/components/feed-v2/FeedV2.test.tsx`
- Delete: `frontend/src/components/feed-v2/Level1SummaryV2.tsx`
- Delete: `frontend/src/components/feed-v2/Level1SummaryV2.test.tsx`

**Interfaces:**
- Consumes: `AlertLevel1Page`, `AlertRipplePage`, `AlertTimelinePage` (Tasks 3-5).
- Produces: `/feed-v2/alert/:id`, `/feed-v2/alert/:id/ripple`, `/feed-v2/alert/:id/timeline` become live, reachable routes. `FeedRowV2`'s `onOpen` now triggers navigation instead of a modal fetch — `FeedRowV2.tsx` itself is untouched (its `onOpen` prop was already a generic callback).

**Context:** This is the task that actually retires the old behavior — Tasks 3-5 only added new, not-yet-reachable pages. `Level1SummaryV2.tsx` is deleted whole: its summary/raw-move/volume/source-time markup already moved into `AlertLevel1Page.tsx` verbatim in Task 3, and its `<RippleSection>`/`<TimelineSection>` calls are superseded by `AlertRipplePage`/`AlertTimelinePage`.

- [ ] **Step 1: Update `App.tsx`**

In `frontend/src/App.tsx`, add the three new imports (alphabetically, alongside the existing page imports):

```tsx
import AlertLevel1Page from './pages/AlertLevel1Page';
import AlertRipplePage from './pages/AlertRipplePage';
import AlertTimelinePage from './pages/AlertTimelinePage';
```

And add the three routes, immediately after the existing `<Route path="/feed-v2" element={<FeedV2Page />} />` line:

```tsx
        <Route path="/feed-v2/alert/:id" element={<AlertLevel1Page />} />
        <Route path="/feed-v2/alert/:id/ripple" element={<AlertRipplePage />} />
        <Route path="/feed-v2/alert/:id/timeline" element={<AlertTimelinePage />} />
```

- [ ] **Step 2: Update `FeedV2.tsx`**

Replace the full contents of `frontend/src/components/feed-v2/FeedV2.tsx`:

```tsx
import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../../lib/auth';
import { getFeedV2Alerts, type FeedV2Alert } from '../../lib/feedV2Api';
import FeedRowV2 from './FeedRowV2';

export default function FeedV2() {
  const { token } = useAuth();
  const navigate = useNavigate();
  const [alerts, setAlerts] = useState<FeedV2Alert[]>([]);

  useEffect(() => {
    getFeedV2Alerts(token).then(setAlerts).catch(() => setAlerts([]));
  }, [token]);

  return (
    <div className="mx-auto w-full max-w-3xl px-4">
      <div className="mb-2 flex justify-end">
        <Link to="/feed-v2/directory" className="font-sans text-xs text-muted underline">
          Browse all stocks
        </Link>
      </div>
      <div className="rounded-lg bg-surface p-5">
        {alerts.map((alert) => (
          <FeedRowV2 key={alert.id} alert={alert} onOpen={() => navigate(`/feed-v2/alert/${alert.id}`)} />
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Delete `Level1SummaryV2`**

```bash
git rm frontend/src/components/feed-v2/Level1SummaryV2.tsx frontend/src/components/feed-v2/Level1SummaryV2.test.tsx
```

- [ ] **Step 4: Update `FeedV2.test.tsx`**

Replace the full contents of `frontend/src/components/feed-v2/FeedV2.test.tsx`:

```tsx
import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import FeedV2 from './FeedV2';
import * as feedV2Api from '../../lib/feedV2Api';
import { AuthProvider } from '../../lib/auth';
import type { FeedV2Alert } from '../../lib/feedV2Api';

function makeAlert(overrides: Partial<FeedV2Alert> = {}): FeedV2Alert {
  return {
    id: 1,
    category: 'oil_gas',
    created_at: '2026-07-22T10:00:00Z',
    summary_short: 'Oil supply shock lifts refiners',
    summary_long: 'Crude prices jumped on a supply disruption. Refiners face wider margin pressure.',
    article: { id: 1, title: 'Oil surges', url: 'https://example.com/a', source: 'Economic Times', published_at: null },
    excess_move_pct: -4.2,
    direction: 'bearish',
    raw_move_pct: -4.8,
    sector_move_pct: -0.6,
    volume_multiple: 3.1,
    benchmark_ticker: '^CNXENERGY',
    is_fallback_benchmark: false,
    peak_ticker: 'RELIANCE.NS',
    peak_company_name: 'Reliance Industries',
    verdict: 'COMPANY_SPECIFIC',
    intensity: { score: 82, band: 'High', components: [] },
    breadth_score: 40,
    in_my_holdings: false,
    ...overrides,
  };
}

function renderFeedV2() {
  return render(
    <MemoryRouter initialEntries={['/feed-v2']}>
      <AuthProvider>
        <Routes>
          <Route path="/feed-v2" element={<FeedV2 />} />
          <Route path="/feed-v2/alert/:id" element={<div>Alert Level 1 Page</div>} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe('FeedV2', () => {
  it('fetches and renders feed rows', async () => {
    vi.spyOn(feedV2Api, 'getFeedV2Alerts').mockResolvedValue([makeAlert()]);
    renderFeedV2();
    await waitFor(() => expect(screen.getByText('Oil supply shock lifts refiners')).toBeInTheDocument());
  });

  it('navigates to the Level 1 page when a row is clicked', async () => {
    vi.spyOn(feedV2Api, 'getFeedV2Alerts').mockResolvedValue([makeAlert()]);
    const { user } = await import('@testing-library/user-event').then((m) => ({ user: m.default.setup() }));
    renderFeedV2();
    await waitFor(() => screen.getByText('Oil supply shock lifts refiners'));
    await user.click(screen.getByText('Oil supply shock lifts refiners'));
    await waitFor(() => expect(screen.getByText('Alert Level 1 Page')).toBeInTheDocument());
  });

  it('renders nothing extra when the feed is empty', async () => {
    vi.spyOn(feedV2Api, 'getFeedV2Alerts').mockResolvedValue([]);
    renderFeedV2();
    await waitFor(() => expect(feedV2Api.getFeedV2Alerts).toHaveBeenCalled());
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('renders a link to the stock directory', async () => {
    vi.spyOn(feedV2Api, 'getFeedV2Alerts').mockResolvedValue([]);
    renderFeedV2();
    await waitFor(() => expect(feedV2Api.getFeedV2Alerts).toHaveBeenCalled());
    expect(screen.getByRole('link', { name: 'Browse all stocks' })).toHaveAttribute(
      'href',
      '/feed-v2/directory',
    );
  });
});
```

- [ ] **Step 5: Run the affected frontend tests**

Run: `cd frontend && npm test -- --run FeedV2 App`
Expected: all PASS. (`App.test.tsx` may not exist as a dedicated file — if `npm test -- --run App` reports no matching files, that's fine; the important suite is `FeedV2.test.tsx`.)

- [ ] **Step 6: Run the full frontend suite**

Run: `cd frontend && npm test -- --run`
Expected: all PASS, zero failures (confirms nothing else referenced the now-deleted `Level1SummaryV2`).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/App.tsx frontend/src/components/feed-v2/FeedV2.tsx frontend/src/components/feed-v2/FeedV2.test.tsx
git add frontend/src/components/feed-v2/Level1SummaryV2.tsx frontend/src/components/feed-v2/Level1SummaryV2.test.tsx
git commit -m "feat: wire real routes for Levels 1-3, retire the stacked Level1SummaryV2 modal"
```

---

## Task 7: Playwright screenshot verification (HARD RULE)

**Files:**
- Modify: `frontend/e2e/feed-v2-screenshots.spec.ts`

**Context:** This task rewrites the Level 1 screenshot case (was: click a row, screenshot the modal `[role="dialog"]` element with clipping-fix `evaluate` calls; now: click a row, land on a real page, screenshot it `fullPage` like `StockDeepDivePage`/`DirectoryPage` already do), adds two brand-new cases (ripple, timeline), and updates the "stock deep-dive with alert context" case's navigation chain (it used to reach the peer row inside the Level 1 modal directly; now it must go feed → Level 1 page → "See ripple" → Level 2 page → peer row). The intensity-breakdown, directory, and "stock deep-dive without alert context" cases are unchanged. Per this project's established convention (see the file's own comments), `waitForSelector` on real content is used instead of a fixed `waitForTimeout` wherever a page issues its own async fetch after navigation, and the mobile `BottomNav` is hidden before any `fullPage` screenshot of a plain routed page tall enough to scroll (the same `position:fixed`-vs-`fullPage` compositing issue already fixed for the deep-dive page).

- [ ] **Step 1: Replace the full contents of `frontend/e2e/feed-v2-screenshots.spec.ts`**

```ts
import { test } from '@playwright/test';

const THEMES = ['dark', 'light'] as const;

function hideBottomNav(page: import('@playwright/test').Page) {
  return page.evaluate(() => {
    const bottomNav = document.querySelector('nav.fixed') as HTMLElement | null;
    if (bottomNav) bottomNav.style.display = 'none';
  });
}

for (const theme of THEMES) {
  test(`feed-v2 Level 0 (${theme})`, async ({ page }) => {
    await page.goto('/feed-v2');
    if (theme === 'light') {
      await page.evaluate(() => document.documentElement.classList.add('light'));
    }
    await page.waitForSelector('text=/./', { timeout: 10_000 }).catch(() => {});
    await page.screenshot({
      path: `.superpowers-screenshots/feed-v2-level0-${theme}-${test.info().project.name}.png`,
      fullPage: true,
    });
  });

  test(`feed-v2 Level 1 (${theme})`, async ({ page }) => {
    await page.goto('/feed-v2');
    if (theme === 'light') {
      await page.evaluate(() => document.documentElement.classList.add('light'));
    }
    const firstRow = page.locator('[role="button"]').first();
    await firstRow.waitFor({ timeout: 10_000 });
    await firstRow.click();
    // AlertLevel1Page is now a real routed page (not a modal) that issues
    // its own async fetch after navigation -- wait for content that only
    // renders once that fetch resolves, same discipline as the deep-dive
    // page's "What they do" wait below.
    await page.waitForSelector('text=Raw move', { timeout: 10_000 });
    await hideBottomNav(page);
    await page.screenshot({
      path: `.superpowers-screenshots/feed-v2-level1-${theme}-${test.info().project.name}.png`,
      fullPage: true,
    });
  });

  test(`feed-v2 Level 2 ripple (${theme})`, async ({ page }) => {
    await page.goto('/feed-v2');
    if (theme === 'light') {
      await page.evaluate(() => document.documentElement.classList.add('light'));
    }
    const firstRow = page.locator('[role="button"]').first();
    await firstRow.waitFor({ timeout: 10_000 });
    await firstRow.click();
    await page.waitForSelector('text=Raw move', { timeout: 10_000 });
    const rippleDoor = page.getByRole('link', { name: /See ripple/ });
    await rippleDoor.click();
    // "See timeline" always renders once AlertRipplePage's own fetch
    // resolves, regardless of whether this alert has any ripple companies
    // -- a stable anchor independent of ripple content.
    await page.waitForSelector('text=See timeline', { timeout: 10_000 });
    await hideBottomNav(page);
    await page.screenshot({
      path: `.superpowers-screenshots/feed-v2-level2-ripple-${theme}-${test.info().project.name}.png`,
      fullPage: true,
    });
  });

  test(`feed-v2 Level 3 timeline (${theme})`, async ({ page }) => {
    await page.goto('/feed-v2');
    if (theme === 'light') {
      await page.evaluate(() => document.documentElement.classList.add('light'));
    }
    const firstRow = page.locator('[role="button"]').first();
    await firstRow.waitFor({ timeout: 10_000 });
    await firstRow.click();
    await page.waitForSelector('text=Raw move', { timeout: 10_000 });
    await page.getByRole('link', { name: /See ripple/ }).click();
    await page.waitForSelector('text=See timeline', { timeout: 10_000 });
    await page.getByRole('link', { name: /See timeline/ }).click();
    // "← Ripple" always renders once AlertTimelinePage's own fetch
    // resolves, regardless of whether this alert has any timeline entries.
    await page.waitForSelector('text=Ripple', { timeout: 10_000 });
    await hideBottomNav(page);
    await page.screenshot({
      path: `.superpowers-screenshots/feed-v2-level3-timeline-${theme}-${test.info().project.name}.png`,
      fullPage: true,
    });
  });

  test(`feed-v2 intensity breakdown (${theme})`, async ({ page }) => {
    await page.goto('/feed-v2');
    if (theme === 'light') {
      await page.evaluate(() => document.documentElement.classList.add('light'));
    }
    const intensityTarget = page.getByTestId('intensity-tap-target').first();
    await intensityTarget.waitFor({ timeout: 10_000 });
    await intensityTarget.click();
    await page.waitForTimeout(300);
    await page.screenshot({
      path: `.superpowers-screenshots/feed-v2-intensity-breakdown-${theme}-${test.info().project.name}.png`,
      fullPage: true,
    });
  });

  test(`feed-v2 stock deep-dive with alert context (${theme})`, async ({ page }) => {
    await page.goto('/feed-v2');
    if (theme === 'light') {
      await page.evaluate(() => document.documentElement.classList.add('light'));
    }
    const firstRow = page.locator('[role="button"]').first();
    await firstRow.waitFor({ timeout: 10_000 });
    await firstRow.click();
    await page.waitForSelector('text=Raw move', { timeout: 10_000 });
    await page.getByRole('link', { name: /See ripple/ }).click();
    await page.waitForSelector('text=See timeline', { timeout: 10_000 });
    // Ripple's peer rows are now on a plain page (no longer scoped inside
    // a `[role="dialog"]`) -- same selector shape PeerRow has always used.
    const peerRow = page.locator('[role="button"][aria-label]').first();
    await peerRow.waitFor({ timeout: 10_000 });
    await peerRow.click();
    await page.waitForSelector('text=What they do', { timeout: 10_000 });
    await hideBottomNav(page);
    await page.screenshot({
      path: `.superpowers-screenshots/feed-v2-stock-deep-dive-with-alert-${theme}-${test.info().project.name}.png`,
      fullPage: true,
    });
  });

  test(`feed-v2 directory (${theme})`, async ({ page }) => {
    await page.goto('/feed-v2/directory');
    if (theme === 'light') {
      await page.evaluate(() => document.documentElement.classList.add('light'));
    }
    await page.waitForSelector('text=/./', { timeout: 10_000 }).catch(() => {});
    await page.screenshot({
      path: `.superpowers-screenshots/feed-v2-directory-${theme}-${test.info().project.name}.png`,
      fullPage: true,
    });
  });

  test(`feed-v2 stock deep-dive without alert context (${theme})`, async ({ page }) => {
    await page.goto('/feed-v2/directory');
    if (theme === 'light') {
      await page.evaluate(() => document.documentElement.classList.add('light'));
    }
    const firstCompanyLink = page.locator('a[href^="/feed-v2/stock/"]').first();
    await firstCompanyLink.waitFor({ timeout: 10_000 });
    await firstCompanyLink.click();
    await page.waitForSelector('text=What they do', { timeout: 10_000 });
    await hideBottomNav(page);
    await page.screenshot({
      path: `.superpowers-screenshots/feed-v2-stock-deep-dive-no-alert-${theme}-${test.info().project.name}.png`,
      fullPage: true,
    });
  });
}
```

- [ ] **Step 2: Seed data and start both servers**

```bash
cd backend && python seed_feed_v2_demo.py
```

Start the backend (`cd backend && uvicorn app.main:app --reload` or this project's usual dev command) and the frontend (`cd frontend && npm run dev`) as background processes. Check port availability first; use alternates + temporary config repointing if needed, reverting before any commit.

- [ ] **Step 3: Run the screenshot spec**

Run: `cd frontend && npx playwright test feed-v2-screenshots`
Expected: all tests pass — 8 test names × 2 themes × 2 projects (mobile/desktop) = 32 screenshots.

- [ ] **Step 4: Look at every new/changed screenshot — THE ACTUAL VERIFICATION STEP**

Open each of these with the Read tool (both themes, both 390px/mobile and 1920px/desktop projects) and check against `docs/superpowers/specs/2026-07-27-feed-v2-level-navigation-design.md` and spec §2/§9:
- **`feed-v2-level1-*`:** verdict badge + summary paragraph; raw/sector move + volume tile; source + timestamp; **Affected companies** section — one row per direct company, ticker + signed excess % + why text where present, no row for a company with no why (blank, not a placeholder); "See ripple →" link at the bottom, right-aligned; "← Feed" link at the top. No ripple or timeline content on this page (that moved to Levels 2/3).
- **`feed-v2-level2-ripple-*`:** ripple content identical in appearance to the old Level 1 modal's ripple section (grouped by relationship, `PeerRow` cap tag/bar/score/(i)/chevron per row); "← Summary" link at top; "See timeline →" link at bottom.
- **`feed-v2-level3-timeline-*`:** timeline content identical in appearance to the old modal's timeline section (horizon dots + descriptions); "← Ripple" link at top; no forward door.
- **`feed-v2-stock-deep-dive-with-alert-*`:** unchanged from Phase 7 (re-confirm nothing regressed now that it's reached via a different navigation chain).
- Every page: both themes legible, no clipped/overlapping text, mobile `BottomNav` correctly hidden (no floating nav bar composited mid-page).

Write down every concrete discrepancy found. Fix it in the relevant component. Re-run Step 3 and re-check. Repeat until clean.

- [ ] **Step 5: Stop the background servers**

Kill the specific PIDs — never a broad process-kill.

- [ ] **Step 6: Run both full test suites one more time**

Run: `cd backend && python -m pytest -q` and `cd frontend && npm test -- --run` — confirm zero regressions from any Step 4 fixes.

- [ ] **Step 7: Commit**

Commit the e2e spec rewrite, and separately any fixes Step 4's review required, describing exactly what was found and corrected.

```bash
git add frontend/e2e/feed-v2-screenshots.spec.ts
git commit -m "test: rewrite feed-v2 screenshots for real Level 1-3 routes, add ripple/timeline cases"
```

---

## Task 8: Full-suite regression check

- [ ] **Step 1: Run the entire backend test suite**

Run: `cd backend && python -m pytest -q`
Expected: all tests PASS, zero failures.

- [ ] **Step 2: Run the entire frontend test suite**

Run: `cd frontend && npm test -- --run`
Expected: all tests PASS, zero failures.

- [ ] **Step 3: Confirm the legacy `/` feed is untouched**

Run: `git diff master --stat -- frontend/src/pages/FeedPage.tsx`
Expected: no output (zero changes to the legacy feed page across this entire plan).

- [ ] **Step 4: Report**

Summarize: total commits, final test counts (backend/frontend), confirmation that all 32 screenshots were opened and reviewed (list any discrepancies found during Task 7 and how each was fixed, or "clean on first pass").
