# Measurement-First Impact Architecture — Phase 7 (Level 4 Deep-Dive + Discovery Directory) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Level 4 (stock deep-dive — "what is this company & how hard hit?") and a discovery Directory screen per `docs/NEWS_IMPACT_APP_SPEC.md` §2, §9 and the task brief's Phase 7 section. Every stock row app-wide (ripple rows from Phase 6, and a new sector-peers list) becomes a door into a company's own deep-dive, reached via a dedicated route rather than another stacked modal — this is the level where recursive "peer → peer → peer" browsing needs real navigation, not a fourth layer of `AlertDetail`.

**Architecture:** New backend router `app/routers/stock_deep_dive.py` exposing `GET /api/feed-v2/stock/{ticker}` (optional `?alert_id=` — with it, the company's measured excess/intensity for that specific news event and its same-alert sector peers; without it, company facts only, for browse-without-news-context) and `GET /api/feed-v2/directory` (cap-tier/sector filterable company list, no news attached — spec Milestone 1's original ask, finally shipped). New frontend routes `/feed-v2/stock/:ticker` and `/feed-v2/directory`. A new shared `PeerRow` component replaces Phase 6's inline ripple-row markup so ripple rows and the new peers list share one canonical row format (spec §9's single "ripple/peers" row spec), each row opening either the deep-dive (row tap) or a lightweight business/sector popup (`(i)` tap, `stopPropagation`).

**Tech Stack:** Same as Phases 1-6 — FastAPI + SQLAlchemy backend, React + TypeScript + Vite + Tailwind frontend, Vitest + Testing Library, Playwright. This phase adds `react-router-dom`'s `useNavigate`/`Link` to the feed-v2 surface for the first time (`FeedV2.tsx`/`RippleSection.tsx` were previously modal-only, no routing).

## Global Constraints

- **Dedicated route, not a stacked modal** (confirmed with the user): deep-dive lives at `/feed-v2/stock/:ticker`, optionally with `?alertId=N` in the query string. Tapping a peer row from inside a deep-dive navigates to a NEW deep-dive URL (`/feed-v2/stock/:otherTicker?alertId=N`) rather than opening a 3rd nested modal — real back-button semantics for recursive browsing.
- **Ripple rows upgraded to the full canonical row format** (confirmed with the user): `RippleSection.tsx`'s rows gain a cap tag, `(i)` button, and tap-to-deep-dive, matching spec §9's single "ripple/peers" row spec (`[TICKER] [CAP TAG] [•owned] [intensity heat bar + score] [(i)] [›]`) instead of Phase 6's simpler `[TICKER] [excess%] [bar] [owned dot]`. Existing Phase 6 `RippleSection.test.tsx` tests are extended, not weakened — every assertion that survives (ticker text, exposure-only "no number" behavior, group headers/borders) stays exactly as strict.
- **Legacy `/company/:id` (`CompanyPage.tsx`) is untouched** — it's a different, older design system (Georgia serif headings, hairline-card layout) unrelated to this rebuild, same as Phase 4's decision to build `/feed-v2` as a new parallel screen rather than touch the legacy `/` feed. Zero edits to `CompanyPage.tsx`, `frontend/src/lib/api.ts`'s `getCompanyProfile`/etc., or any route under `/company/*`.
- **Deep-dive's sector-peers list is alert-scoped, not company-directory-scoped.** Per spec §9 ("Sort winners/losers and peers by intensity descending — the ordering is itself the discovery signal... same news swings them hardest"), peers shown in a deep-dive reached WITH an `alertId` are the other same-sector companies that were ALSO measured or exposure-flagged for that SAME alert (reusing Phase 6's `compute_ripple_companies`' underlying per-company computation, filtered to sector) — never a stale, unrelated intensity value borrowed from some other event. A deep-dive reached WITHOUT an `alertId` (from the Directory) shows no peers-by-intensity at all; the **Directory screen itself** is where news-free peer/company browsing lives (spec Milestone 1: "browse/filter by cap tier + sector, no news attached").
- **PE ratio is a live, degrade-to-`None` fetch**, extending the existing `price_series.py` "never raise" contract — no new persisted field, no fabricated number. If yfinance has no PE for a tic201ker (e.g., loss-making company, ETF), the deep-dive omits the PE tile rather than showing `0` or `N/A` as if it were data.
- **Cap tier is always recomputed** via the already-built, previously-unwired `app.market.cap_tier.compute_cap_tier_for_ticker` (Phase 2) — never hardcoded, never stored.
- **`(i)` tap always stops propagation** so it never also triggers the row's own tap-to-deep-dive (spec §9, and the same click/keydown-isolation discipline established in Phase 5 for the intensity tap target).
- **New cap-tier color tokens** (`capLarge`/`capMid`/`capSmall`) are a THIRD distinct hue family from bullish/bearish (green/red) and intensity (blue/amber/violet) — indigo/teal/orange — so a cap tag pill never reads as a direction or intensity signal by color alone.
- **No new nav-wide changes.** Directory is reached via a link from `FeedV2.tsx`'s own header, not by adding an item to the app-wide `NavBar`/`BottomNav` (those are shared across the legacy and feed-v2 surfaces; Phase 4-6 never touched them and this phase doesn't either).
- **Never fabricate a number.** Same discipline as every prior phase — a company with no measured move for the given alert context shows the same "Exposure" treatment already established in Phase 6's `RippleSection`/`ripple.py`, not a zero or a borrowed number.
- Full backend and frontend test suites must both pass with zero regressions at the end. This phase has UI components, so the HARD RULE applies: Playwright screenshots, actually looked at, before this phase is done.

---

## File Structure

```
backend/app/companies/price_series.py           MODIFY — add fetch_pe_ratio
backend/app/market/ripple.py                    MODIFY — extract _alert_company_rows, add get_sector_peers_for_alert
backend/app/routers/stock_deep_dive.py          NEW — GET /api/feed-v2/stock/{ticker}, GET /api/feed-v2/directory
backend/app/main.py                             MODIFY — register stock_deep_dive.router

backend/tests/test_price_series.py              MODIFY — cover fetch_pe_ratio
backend/tests/test_ripple.py                    MODIFY — cover get_sector_peers_for_alert
backend/tests/test_stock_deep_dive_router.py    NEW

frontend/tailwind.config.ts                     MODIFY — capLarge/capMid/capSmall tokens
frontend/src/index.css                          MODIFY — cap-tier CSS vars, both themes

frontend/src/lib/feedV2Api.ts                   MODIFY — StockDeepDive, DirectoryCompany, DirectoryFilters types; getStockDeepDive, getDirectory
frontend/src/lib/feedV2Format.ts                MODIFY — capTierColorClass

frontend/src/components/feed-v2/BusinessPopup.tsx        NEW
frontend/src/components/feed-v2/BusinessPopup.test.tsx   NEW
frontend/src/components/feed-v2/PeerRow.tsx               NEW
frontend/src/components/feed-v2/PeerRow.test.tsx          NEW
frontend/src/components/feed-v2/RippleSection.tsx         MODIFY — rows use PeerRow
frontend/src/components/feed-v2/RippleSection.test.tsx    MODIFY — extended for new row affordances

frontend/src/pages/StockDeepDivePage.tsx        NEW
frontend/src/pages/StockDeepDivePage.test.tsx   NEW
frontend/src/pages/DirectoryPage.tsx             NEW
frontend/src/pages/DirectoryPage.test.tsx        NEW
frontend/src/components/feed-v2/FeedV2.tsx      MODIFY — add a "Browse all stocks" link to Directory
frontend/src/components/feed-v2/FeedV2.test.tsx MODIFY — cover the new link
frontend/src/App.tsx                            MODIFY — register the two new routes

frontend/e2e/feed-v2-screenshots.spec.ts        MODIFY — deep-dive (with/without alert) + directory screenshots
```

---

## Task 1: `fetch_pe_ratio` — live PE lookup

**Files:**
- Modify: `backend/app/companies/price_series.py`
- Modify: `backend/tests/test_price_series.py`

**Interfaces:**
- Produces: `fetch_pe_ratio(ticker: str) -> float | None`. Consumed by `app/routers/stock_deep_dive.py` (Task 3).

- [ ] **Step 1: Write the failing tests**

Read the current `backend/tests/test_price_series.py` first (it mocks `yf.Ticker` for the existing functions — follow the same mocking pattern). Append:

```python
def test_fetch_pe_ratio_returns_trailing_pe(monkeypatch):
    class FakeTicker:
        def __init__(self, ticker):
            self.info = {"trailingPE": 24.7}

    monkeypatch.setattr("yfinance.Ticker", FakeTicker)

    assert fetch_pe_ratio("RELIANCE.NS") == 24.7


def test_fetch_pe_ratio_returns_none_when_missing(monkeypatch):
    class FakeTicker:
        def __init__(self, ticker):
            self.info = {}

    monkeypatch.setattr("yfinance.Ticker", FakeTicker)

    assert fetch_pe_ratio("SOMETICKER.NS") is None


def test_fetch_pe_ratio_returns_none_on_non_finite_value(monkeypatch):
    class FakeTicker:
        def __init__(self, ticker):
            self.info = {"trailingPE": float("nan")}

    monkeypatch.setattr("yfinance.Ticker", FakeTicker)

    assert fetch_pe_ratio("SOMETICKER.NS") is None


def test_fetch_pe_ratio_returns_none_on_exception(monkeypatch):
    class FakeTicker:
        def __init__(self, ticker):
            raise RuntimeError("network error")

    monkeypatch.setattr("yfinance.Ticker", FakeTicker)

    assert fetch_pe_ratio("SOMETICKER.NS") is None
```

Add the import at the top of the test file if not already present: `from app.companies.price_series import fetch_pe_ratio` (alongside the existing `fetch_price_series`/`fetch_daily_bars` imports).

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_price_series.py -v -k fetch_pe_ratio`
Expected: FAIL — `ImportError: cannot import name 'fetch_pe_ratio'`.

- [ ] **Step 3: Implement**

Append to `backend/app/companies/price_series.py`:

```python
def fetch_pe_ratio(ticker: str) -> float | None:
    """Return ``ticker``'s trailing P/E ratio, or ``None`` if yfinance has
    no value (loss-making company, ETF, data gap) or the fetch fails. Same
    "never raise, degrade to None" contract as fetch_price_series/
    fetch_daily_bars -- live, not cached or persisted (docs/
    NEWS_IMPACT_APP_SPEC.md §3.1 Stock.pe is a directory-facing fact, not a
    measured/derived spine number, so it carries no "never fabricate"
    weight beyond the ordinary honest-degrade discipline every live fetch
    in this module already follows).
    """
    try:
        info = yf.Ticker(ticker).info
        pe = info.get("trailingPE")
        if pe is None or not math.isfinite(float(pe)):
            return None
        return float(pe)
    except Exception:
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_price_series.py -v`
Expected: all PASS (existing tests plus the 4 new ones).

- [ ] **Step 5: Commit**

```bash
git add backend/app/companies/price_series.py backend/tests/test_price_series.py
git commit -m "feat: add fetch_pe_ratio -- live, degrade-to-None P/E lookup for the stock deep-dive"
```

---

## Task 2: Extract shared alert-company-row builder, add `get_sector_peers_for_alert`

**Files:**
- Modify: `backend/app/market/ripple.py`
- Modify: `backend/tests/test_ripple.py`

**Interfaces:**
- Consumes: same as Task 2 of Phase 6 (`_intensity_for_company_move`, `compute_breadth_score`, `is_exposure_only`, `relation_to_ripple_relationship`).
- Produces: `_alert_company_rows(session, alert, exclude_company_id, held_company_ids) -> list[dict]` (module-private, the per-company row shape WITHOUT relationship grouping — same fields `compute_ripple_companies` already returns per row, minus the `relationship` key, plus a new `sector` key). `compute_ripple_companies` is refactored to call this and add `relationship` per row (its own public return shape is UNCHANGED — every existing caller/test keeps working). New public function `get_sector_peers_for_alert(session, alert, company, held_company_ids) -> list[dict]` — same row shape as `_alert_company_rows`, filtered to `sector == company.sector` and excluding `company` itself, sorted by intensity descending (exposure-only last, matching `compute_ripple_companies`'s existing sort). Consumed by `app/routers/stock_deep_dive.py` (Task 3).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_ripple.py` (reuse the file's existing `_company`/`_article`/`_alert_company`/`_edge` helpers):

```python
from app.market.ripple import get_sector_peers_for_alert


def test_sector_peers_excludes_self_and_other_sectors(db_session):
    target = _company("TARGET.NS", sector="oil_gas")
    same_sector = _company("PEER.NS", sector="oil_gas")
    other_sector = _company("OTHER.NS", sector="it")
    db_session.add_all([target, same_sector, other_sector])
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    for c in (target, same_sector, other_sector):
        db_session.add(_alert_company(alert.id, c.id))
    for c, excess in ((target, -3.0), (same_sector, 1.5), (other_sector, 2.0)):
        db_session.add(MarketMove(
            alert_id=alert.id, company_id=c.id, benchmark_ticker="^CNXENERGY",
            raw_move_pct=excess, sector_move_pct=0.0, excess_move_pct=excess,
            measurement_status="ok", measured_at=utcnow(),
        ))
    db_session.commit()

    result = get_sector_peers_for_alert(db_session, alert, target, held_company_ids=set())

    tickers = {r["ticker"] for r in result}
    assert tickers == {"PEER.NS"}


def test_sector_peers_row_shape_matches_ripple_row_shape(db_session):
    target = _company("TARGET.NS", sector="oil_gas")
    peer = _company("PEER.NS", sector="oil_gas")
    db_session.add_all([target, peer])
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, target.id))
    db_session.add(_alert_company(alert.id, peer.id))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=target.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-3.0, sector_move_pct=0.0, excess_move_pct=-3.0,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=peer.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=1.5, sector_move_pct=0.0, excess_move_pct=1.5,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    result = get_sector_peers_for_alert(db_session, alert, target, held_company_ids=set())

    assert set(result[0].keys()) == {
        "ticker", "name", "direction", "excess_move_pct", "intensity",
        "is_exposure_only", "in_my_holdings",
    }


def test_sector_peers_sorted_by_intensity_exposure_only_last(db_session):
    target = _company("TARGET.NS", sector="oil_gas")
    small = _company("SMALL.NS", sector="oil_gas")
    big = _company("BIG.NS", sector="oil_gas")
    unmeasured = _company("UNMEASURED.NS", sector="oil_gas")
    db_session.add_all([target, small, big, unmeasured])
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    for c in (target, small, big, unmeasured):
        db_session.add(_alert_company(alert.id, c.id))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=target.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-3.0, sector_move_pct=0.0, excess_move_pct=-3.0,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=small.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=0.2, sector_move_pct=0.0, excess_move_pct=0.2,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=big.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=2.7, sector_move_pct=0.0, excess_move_pct=2.7,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=unmeasured.id, benchmark_ticker="^CNXENERGY",
        measurement_status="no_data", measured_at=utcnow(),
    ))
    db_session.commit()

    result = get_sector_peers_for_alert(db_session, alert, target, held_company_ids=set())

    tickers_in_order = [r["ticker"] for r in result]
    assert tickers_in_order[-1] == "UNMEASURED.NS"
    assert tickers_in_order.index("BIG.NS") < tickers_in_order.index("SMALL.NS")


def test_compute_ripple_companies_still_includes_relationship_after_refactor(db_session):
    """Regression guard for the Task 2 refactor: compute_ripple_companies'
    PUBLIC return shape (with 'relationship') must be byte-for-byte
    unchanged even though its internals now delegate to the shared
    _alert_company_rows helper."""
    peak = _company("PEAK.NS")
    beneficiary = _company("BEN.NS")
    db_session.add_all([peak, beneficiary])
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, peak.id))
    db_session.add(_alert_company(alert.id, beneficiary.id))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=peak.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-4.0, sector_move_pct=-0.5, excess_move_pct=-3.5,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=beneficiary.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=2.0, sector_move_pct=0.3, excess_move_pct=1.7,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(_edge(alert.id, peak.id, beneficiary.id, relation="commodity", direction="bullish"))
    db_session.commit()

    result = compute_ripple_companies(db_session, alert, exclude_company_id=peak.id, held_company_ids=set())

    assert set(result[0].keys()) == {
        "ticker", "name", "sector", "relationship", "direction", "excess_move_pct",
        "intensity", "is_exposure_only", "in_my_holdings",
    }
    assert result[0]["relationship"] == "BENEFICIARY"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_ripple.py -v -k "sector_peers or still_includes_relationship"`
Expected: FAIL — `ImportError: cannot import name 'get_sector_peers_for_alert'`.

- [ ] **Step 3: Refactor**

Replace `backend/app/market/ripple.py`'s content with:

```python
"""Level 2 ripple data: every OTHER measured/exposed company tied to an
alert (excluding the event's own peak, already shown at Level 0/1), grouped
by relationship type (docs/NEWS_IMPACT_APP_SPEC.md §2 Level 2, §3.1
RippleLink). A company with no real measured move renders as a flagged
EXPOSURE, never a fabricated impact number (spec: "ripple companies that
have not moved... show it as a flagged relationship with no number and no
score -- never a fabricated magnitude").

Also home to get_sector_peers_for_alert (Phase 7, Level 4's "sector peers"
discovery doorway) -- the same per-company row computation as ripple,
just filtered to one company's sector instead of grouped by relationship,
since both need the exact same intensity-normalization discipline against
this alert's companies.
"""
from sqlalchemy.orm import Session

from app.market.alert_measurement import _intensity_for_company_move
from app.market.breadth import compute_breadth_score
from app.models import Alert, Company, ImpactEdge, MarketMove
from app.reasoning.ripple_relationship import is_exposure_only, relation_to_ripple_relationship


def _alert_company_rows(
    session: Session, alert: Alert, exclude_company_id: int, held_company_ids: set[int],
) -> list[dict]:
    """Every AlertCompany on ``alert`` other than ``exclude_company_id``,
    each: {ticker, name, sector, direction, excess_move_pct (float|None),
    intensity (dict|None), is_exposure_only (bool), in_my_holdings (bool)}.
    excess_move_pct/intensity are None whenever is_exposure_only is True --
    never a fabricated number for an unmeasured company. Sorted by
    intensity score descending; exposure-only entries (no score) sort
    last. Shared by compute_ripple_companies (adds `relationship`, groups
    by it) and get_sector_peers_for_alert (filters by `sector`) -- the one
    place this per-company computation lives.
    """
    moves_by_company_id = {
        m.company_id: m for m in session.query(MarketMove).filter_by(alert_id=alert.id).all()
    }
    ok_excess_values = [m.excess_move_pct for m in moves_by_company_id.values() if m.measurement_status == "ok"]
    breadth_score = compute_breadth_score(ok_excess_values)

    results = []
    for alert_company in alert.companies:
        if alert_company.company_id == exclude_company_id:
            continue
        company = alert_company.company
        move = moves_by_company_id.get(alert_company.company_id)
        status = move.measurement_status if move else None
        exposure_only = is_exposure_only(status)

        entry = {
            "ticker": company.ticker,
            "name": company.name,
            "sector": company.sector,
            "direction": alert_company.direction,
            "excess_move_pct": None,
            "intensity": None,
            "is_exposure_only": exposure_only,
            "in_my_holdings": alert_company.company_id in held_company_ids,
        }
        if not exposure_only and move is not None and move.excess_move_pct is not None:
            entry["excess_move_pct"] = move.excess_move_pct
            entry["intensity"] = _intensity_for_company_move(session, company, move, breadth_score)
        results.append(entry)

    results.sort(key=lambda r: r["intensity"]["score"] if r["intensity"] else -1, reverse=True)
    return results


def compute_ripple_companies(
    session: Session, alert: Alert, exclude_company_id: int, held_company_ids: set[int],
) -> list[dict]:
    """Returns one entry per AlertCompany on this alert OTHER than
    exclude_company_id (the event's peak, already shown at Level 0/1),
    each: {ticker, name, relationship, direction, excess_move_pct
    (float|None), intensity (dict|None), is_exposure_only (bool),
    in_my_holdings (bool)}. Sorted by intensity score descending;
    exposure-only entries (no score) sort last.
    """
    rows = _alert_company_rows(session, alert, exclude_company_id, held_company_ids)

    edges = session.query(ImpactEdge).filter_by(alert_id=alert.id).all()
    relation_by_company_id: dict[int, str] = {}
    for edge in edges:
        for company_id in (edge.to_company_id, edge.from_company_id):
            if company_id is not None and company_id not in relation_by_company_id:
                relation_by_company_id[company_id] = edge.relation

    ticker_to_company_id = {ac.company.ticker: ac.company_id for ac in alert.companies}
    results = []
    for row in rows:
        company_id = ticker_to_company_id[row["ticker"]]
        relationship = relation_to_ripple_relationship(relation_by_company_id.get(company_id, ""))
        results.append({**row, "relationship": relationship})
    return results


def get_sector_peers_for_alert(
    session: Session, alert: Alert, company: Company, held_company_ids: set[int],
) -> list[dict]:
    """Other companies measured/exposed within THIS alert that share
    ``company``'s sector (Level 4's "sector peers" discovery doorway,
    docs/NEWS_IMPACT_APP_SPEC.md §2, §9) -- never a peer's intensity
    borrowed from some other, unrelated event (spec §9: "same news swings
    them hardest" -- the ordering only means something within one event).
    Same row shape as _alert_company_rows minus `sector` (the caller
    already knows it -- it's the filter key).
    """
    rows = _alert_company_rows(session, alert, exclude_company_id=company.id, held_company_ids=held_company_ids)
    return [
        {k: v for k, v in row.items() if k != "sector"}
        for row in rows
        if row["sector"] == company.sector
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_ripple.py -v`
Expected: all PASS (the 7 existing Phase 6 tests plus the 4 new ones — the refactor must not change `compute_ripple_companies`'s existing behavior for any of them).

- [ ] **Step 5: Run the full backend suite to confirm no regressions**

Run: `cd backend && python -m pytest -q`
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/market/ripple.py backend/tests/test_ripple.py
git commit -m "refactor: extract _alert_company_rows, add get_sector_peers_for_alert for Level 4"
```

---

## Task 3: `GET /api/feed-v2/stock/{ticker}` — Level 4 deep-dive endpoint

**Files:**
- Create: `backend/app/routers/stock_deep_dive.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_stock_deep_dive_router.py`

**Interfaces:**
- Consumes: `fetch_pe_ratio` (Task 1), `get_sector_peers_for_alert` (Task 2), `compute_cap_tier_for_ticker` (`app.market.cap_tier`, already built in Phase 2), `_held_company_ids` (import directly from `app.routers.feed_v2`, matching the existing cross-module-import convention `app.routers.calendar` already uses for `app.routers.alerts._held_company_ids`).
- Produces: `GET /api/feed-v2/stock/{ticker}?alert_id=<optional int>` response.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_stock_deep_dive_router.py`:

```python
from fastapi.testclient import TestClient

from app.main import app
from app.models import Alert, AlertCompany, Article, Company, MarketMove, utcnow
from app.routers.articles import get_db


def _override_db(db_session):
    def _get_db():
        yield db_session
    app.dependency_overrides[get_db] = _get_db


def _company(ticker, sector="oil_gas", business_desc=None, market_cap=None):
    return Company(
        ticker=ticker, name=f"Company {ticker}", sector=sector, index_tier="NIFTY50",
        business_desc=business_desc, market_cap=market_cap,
    )


def _article(db_session, url="https://example.com/stock-deep-dive"):
    article = Article(source="test", url=url, title="Oil surges", content="c")
    db_session.add(article)
    db_session.commit()
    return article


def _alert_company(alert_id, company_id, direction="bearish"):
    return AlertCompany(
        alert_id=alert_id, company_id=company_id, direction=direction,
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", basis="direct_mention",
    )


def test_stock_deep_dive_without_alert_id_returns_company_facts_only(db_session, monkeypatch):
    monkeypatch.setattr("app.routers.stock_deep_dive.fetch_pe_ratio", lambda ticker: None)
    _override_db(db_session)
    company = _company("RELIANCE.NS", business_desc="Refines crude oil.", market_cap=1500000.0)
    db_session.add(company)
    db_session.commit()
    client = TestClient(app)

    response = client.get("/api/feed-v2/stock/RELIANCE.NS")

    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "RELIANCE.NS"
    assert body["business_desc"] == "Refines crude oil."
    assert body["market_cap"] == 1500000.0
    assert body["pe"] is None
    assert body["excess_move_pct"] is None
    assert body["intensity"] is None
    assert body["peers"] == []
    app.dependency_overrides.clear()


def test_stock_deep_dive_with_alert_id_returns_measurement_and_peers(db_session, monkeypatch):
    monkeypatch.setattr("app.routers.stock_deep_dive.fetch_pe_ratio", lambda ticker: 22.5)
    _override_db(db_session)
    target = _company("RELIANCE.NS", business_desc="Refines crude oil.")
    peer = _company("PEER.NS")
    db_session.add_all([target, peer])
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, target.id))
    db_session.add(_alert_company(alert.id, peer.id))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=target.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-4.8, sector_move_pct=-0.6, excess_move_pct=-4.2,
        volume=300.0, avg_volume_20d=100.0, volume_multiple=3.0,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=peer.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=1.0, sector_move_pct=0.2, excess_move_pct=0.8,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    client = TestClient(app)
    response = client.get(f"/api/feed-v2/stock/RELIANCE.NS?alert_id={alert.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["excess_move_pct"] == -4.2
    assert body["pe"] == 22.5
    assert set(body["intensity"].keys()) == {"score", "band", "components"}
    assert len(body["peers"]) == 1
    assert body["peers"][0]["ticker"] == "PEER.NS"
    app.dependency_overrides.clear()


def test_stock_deep_dive_404_when_ticker_not_found(db_session, monkeypatch):
    monkeypatch.setattr("app.routers.stock_deep_dive.fetch_pe_ratio", lambda ticker: None)
    _override_db(db_session)
    client = TestClient(app)

    response = client.get("/api/feed-v2/stock/NOPE.NS")

    assert response.status_code == 404
    app.dependency_overrides.clear()


def test_stock_deep_dive_with_alert_id_but_company_not_in_that_alert_ignores_alert_context(db_session, monkeypatch):
    """The ticker exists and the alert exists, but this company was never
    part of that alert -- degrade to the no-alert-context shape rather
    than erroring or fabricating a measurement."""
    monkeypatch.setattr("app.routers.stock_deep_dive.fetch_pe_ratio", lambda ticker: None)
    _override_db(db_session)
    company = _company("UNRELATED.NS")
    other_company = _company("INALERT.NS")
    db_session.add_all([company, other_company])
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, other_company.id))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=other_company.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=1.0, sector_move_pct=0.2, excess_move_pct=0.8,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    client = TestClient(app)
    response = client.get(f"/api/feed-v2/stock/UNRELATED.NS?alert_id={alert.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["excess_move_pct"] is None
    assert body["peers"] == []
    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_stock_deep_dive_router.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.routers.stock_deep_dive'`.

- [ ] **Step 3: Implement**

Create `backend/app/routers/stock_deep_dive.py`:

```python
"""Level 4 stock deep-dive endpoint (docs/NEWS_IMPACT_APP_SPEC.md §2, §9) --
"what is this company & how hard hit?". Reached either WITH an alert_id
(from a ripple/peer row tap, within one news event's context: shows that
event's measured excess/intensity for this company plus its same-alert
sector peers) or WITHOUT one (from the Directory, browsing with no news
context: company facts only -- name, sector, cap tier, business_desc,
market cap, PE -- no excess/intensity/peers, since none of those mean
anything without a specific event to measure against). Never fabricates a
number for either path (see this phase's Global Constraints).
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user_optional
from app.companies.price_series import fetch_pe_ratio
from app.market.alert_measurement import _intensity_for_company_move
from app.market.breadth import compute_breadth_score
from app.market.cap_tier import compute_cap_tier_for_ticker
from app.market.ripple import get_sector_peers_for_alert
from app.models import Alert, AlertCompany, Company, MarketMove, User
from app.routers.articles import get_db
from app.routers.feed_v2 import _held_company_ids

router = APIRouter(prefix="/api/feed-v2", tags=["feed-v2"])


def _company_facts(session: Session, company: Company, held_company_ids: set[int]) -> dict:
    return {
        "ticker": company.ticker,
        "name": company.name,
        "sector": company.sector,
        "cap_tier": compute_cap_tier_for_ticker(session, company.ticker),
        "business_desc": company.business_desc,
        "market_cap": company.market_cap,
        "pe": fetch_pe_ratio(company.ticker),
        "in_my_holdings": company.id in held_company_ids,
        "excess_move_pct": None,
        "raw_move_pct": None,
        "sector_move_pct": None,
        "volume_multiple": None,
        "intensity": None,
        "is_exposure_only": None,
        "peers": [],
    }


@router.get("/stock/{ticker}")
def get_stock_deep_dive(
    ticker: str,
    alert_id: int | None = None,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    company = db.query(Company).filter(Company.ticker == ticker).one_or_none()
    if company is None:
        raise HTTPException(status_code=404, detail="Stock not found")

    held_company_ids = _held_company_ids(db, current_user)
    result = _company_facts(db, company, held_company_ids)

    if alert_id is None:
        return result

    alert = db.query(Alert).filter(Alert.id == alert_id).one_or_none()
    if alert is None:
        return result

    alert_company = (
        db.query(AlertCompany)
        .filter(AlertCompany.alert_id == alert_id, AlertCompany.company_id == company.id)
        .one_or_none()
    )
    if alert_company is None:
        return result

    move = (
        db.query(MarketMove)
        .filter(MarketMove.alert_id == alert_id, MarketMove.company_id == company.id)
        .one_or_none()
    )
    peers = get_sector_peers_for_alert(db, alert, company, held_company_ids)
    result["peers"] = peers

    if move is None or move.measurement_status != "ok" or move.excess_move_pct is None:
        result["is_exposure_only"] = True
        return result

    ok_excess_values = [
        m.excess_move_pct
        for m in db.query(MarketMove).filter_by(alert_id=alert_id).all()
        if m.measurement_status == "ok"
    ]
    breadth_score = compute_breadth_score(ok_excess_values)

    result["is_exposure_only"] = False
    result["excess_move_pct"] = move.excess_move_pct
    result["raw_move_pct"] = move.raw_move_pct
    result["sector_move_pct"] = move.sector_move_pct
    result["volume_multiple"] = move.volume_multiple
    result["intensity"] = _intensity_for_company_move(db, company, move, breadth_score)
    return result
```

- [ ] **Step 4: Register the router**

In `backend/app/main.py`, change the import line:

```python
    alerts, articles, auth, calendar, categories, companies, feed_v2, holdings, translation, watchlist, ws,
```

to:

```python
    alerts, articles, auth, calendar, categories, companies, feed_v2, holdings, stock_deep_dive, translation,
    watchlist, ws,
```

Then add, directly after `app.include_router(feed_v2.router)`:

```python
app.include_router(stock_deep_dive.router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_stock_deep_dive_router.py -v`
Expected: all PASS.

- [ ] **Step 6: Run the full backend suite to confirm no regressions**

Run: `cd backend && python -m pytest -q`
Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/routers/stock_deep_dive.py backend/app/main.py backend/tests/test_stock_deep_dive_router.py
git commit -m "feat: add GET /api/feed-v2/stock/{ticker} -- Level 4 deep-dive, with/without alert context"
```

---

## Task 4: `GET /api/feed-v2/directory` — discovery directory endpoint

**Files:**
- Modify: `backend/app/routers/stock_deep_dive.py`
- Modify: `backend/tests/test_stock_deep_dive_router.py`

**Interfaces:**
- Produces: `GET /api/feed-v2/directory?cap_tier=<optional LARGE|MID|SMALL>&sector=<optional str>` — list endpoint, no news attached (spec Milestone 1).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_stock_deep_dive_router.py`:

```python
from app.market.cap_tier import compute_cap_tiers


def test_directory_returns_all_companies_with_cap_tier_and_sector(db_session, monkeypatch):
    _override_db(db_session)
    db_session.add_all([
        _company("BIG.NS", sector="oil_gas", market_cap=900000.0),
        _company("SMALL.NS", sector="it", market_cap=500.0),
    ])
    db_session.commit()

    client = TestClient(app)
    response = client.get("/api/feed-v2/directory")

    assert response.status_code == 200
    body = response.json()
    tickers = {row["ticker"] for row in body}
    assert tickers == {"BIG.NS", "SMALL.NS"}
    by_ticker = {row["ticker"]: row for row in body}
    assert by_ticker["BIG.NS"]["sector"] == "oil_gas"
    assert by_ticker["BIG.NS"]["cap_tier"] in ("LARGE", "MID", "SMALL")
    app.dependency_overrides.clear()


def test_directory_filters_by_cap_tier(db_session):
    _override_db(db_session)
    db_session.add_all([
        _company("BIG.NS", sector="oil_gas", market_cap=900000.0),
        _company("TINY.NS", sector="it", market_cap=10.0),
    ])
    db_session.commit()
    client = TestClient(app)

    response = client.get("/api/feed-v2/directory?cap_tier=SMALL")

    assert response.status_code == 200
    body = response.json()
    assert all(row["cap_tier"] == "SMALL" for row in body)
    assert "TINY.NS" in {row["ticker"] for row in body}
    assert "BIG.NS" not in {row["ticker"] for row in body}
    app.dependency_overrides.clear()


def test_directory_filters_by_sector(db_session):
    _override_db(db_session)
    db_session.add_all([
        _company("OILCO.NS", sector="oil_gas", market_cap=1000.0),
        _company("ITCO.NS", sector="it", market_cap=1000.0),
    ])
    db_session.commit()
    client = TestClient(app)

    response = client.get("/api/feed-v2/directory?sector=it")

    assert response.status_code == 200
    body = response.json()
    assert {row["ticker"] for row in body} == {"ITCO.NS"}
    app.dependency_overrides.clear()


def test_directory_omits_companies_with_no_market_cap(db_session):
    """cap_tier can't be ranked for a company with no market_cap -- the
    directory omits it rather than showing a fabricated/None cap tier
    (Ground Rules: never fabricate, omit rather than invent)."""
    _override_db(db_session)
    db_session.add(_company("NOCAP.NS", sector="oil_gas", market_cap=None))
    db_session.commit()
    client = TestClient(app)

    response = client.get("/api/feed-v2/directory")

    assert response.status_code == 200
    assert response.json() == []
    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_stock_deep_dive_router.py -v -k directory`
Expected: FAIL — 404 (no matching route).

- [ ] **Step 3: Implement**

Append to `backend/app/routers/stock_deep_dive.py` (add the `compute_cap_tiers` import to the existing `from app.market.cap_tier import compute_cap_tier_for_ticker` line, making it `from app.market.cap_tier import compute_cap_tier_for_ticker, compute_cap_tiers`):

```python
@router.get("/directory")
def get_directory(
    cap_tier: str | None = None,
    sector: str | None = None,
    db: Session = Depends(get_db),
):
    rows = db.query(Company.ticker, Company.market_cap).filter(Company.market_cap.isnot(None)).all()
    tiers = compute_cap_tiers([(t, c) for t, c in rows])

    query = db.query(Company).filter(Company.market_cap.isnot(None))
    if sector is not None:
        query = query.filter(Company.sector == sector)
    companies = query.order_by(Company.ticker.asc()).all()

    results = []
    for company in companies:
        tier = tiers.get(company.ticker)
        if cap_tier is not None and tier != cap_tier:
            continue
        results.append({
            "ticker": company.ticker,
            "name": company.name,
            "sector": company.sector,
            "cap_tier": tier,
        })
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_stock_deep_dive_router.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full backend suite to confirm no regressions**

Run: `cd backend && python -m pytest -q`
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/stock_deep_dive.py backend/tests/test_stock_deep_dive_router.py
git commit -m "feat: add GET /api/feed-v2/directory -- cap-tier/sector browse, no news attached"
```

---

## Task 5: Frontend types + cap-tier color tokens

**Files:**
- Modify: `frontend/tailwind.config.ts`
- Modify: `frontend/src/index.css`
- Modify: `frontend/src/lib/feedV2Api.ts`
- Modify: `frontend/src/lib/feedV2Format.ts`

**Interfaces:**
- Produces: Tailwind tokens `capLarge`/`capMid`/`capSmall`. TS types `CapTier`, `StockDeepDive`, `DirectoryCompany`. Functions `getStockDeepDive(ticker, alertId?, token?)`, `getDirectory(filters?, token?)`, `capTierColorClass(tier: CapTier): string`.

- [ ] **Step 1: Add cap-tier CSS variables**

In `frontend/src/index.css`, add to the `:root` block (after `--color-intensity-low`):

```css
  /* Cap-tier tag colors -- a third distinct hue family from bullish/bearish
     (green/red) and intensity (blue/amber/violet), so a cap-tier pill next
     to a ticker never reads as a direction or intensity signal. */
  --color-cap-large: 129 140 248;
  --color-cap-mid: 45 212 191;
  --color-cap-small: 251 146 60;
```

And to the `.light` block (after `--color-intensity-low`):

```css
  --color-cap-large: 79 70 229;
  --color-cap-mid: 13 148 136;
  --color-cap-small: 194 65 12;
```

- [ ] **Step 2: Add the Tailwind tokens**

In `frontend/tailwind.config.ts`, add after `intensityLow: 'rgb(var(--color-intensity-low) / <alpha-value>)',`:

```ts
        capLarge: 'rgb(var(--color-cap-large) / <alpha-value>)',
        capMid: 'rgb(var(--color-cap-mid) / <alpha-value>)',
        capSmall: 'rgb(var(--color-cap-small) / <alpha-value>)',
```

- [ ] **Step 3: Add frontend types to `feedV2Api.ts`**

Add after the existing `Intensity` interface:

```ts
export type CapTier = 'LARGE' | 'MID' | 'SMALL';

export interface StockDeepDive {
  ticker: string;
  name: string;
  sector: string;
  cap_tier: CapTier | null;
  business_desc: string | null;
  market_cap: number | null;
  pe: number | null;
  in_my_holdings: boolean;
  excess_move_pct: number | null;
  raw_move_pct: number | null;
  sector_move_pct: number | null;
  volume_multiple: number | null;
  intensity: Intensity | null;
  is_exposure_only: boolean | null;
  peers: RippleCompany[];
}

export interface DirectoryCompany {
  ticker: string;
  name: string;
  sector: string;
  cap_tier: CapTier;
}

export interface DirectoryFilters {
  capTier?: CapTier;
  sector?: string;
}
```

Note: `StockDeepDive.peers` reuses the existing `RippleCompany` interface (Phase 6) MINUS its `relationship` field. Since `get_sector_peers_for_alert`'s rows omit `relationship` (see Task 2), extend `feedV2Api.ts`'s existing `RippleCompany` interface to make `relationship` optional rather than introducing a second near-duplicate type:

Change:

```ts
export interface RippleCompany {
  ticker: string;
  name: string;
  relationship: RippleRelationship;
  direction: 'bullish' | 'bearish';
  excess_move_pct: number | null;
  intensity: Intensity | null;
  is_exposure_only: boolean;
  in_my_holdings: boolean;
}
```

to:

```ts
export interface RippleCompany {
  ticker: string;
  name: string;
  relationship?: RippleRelationship;
  direction: 'bullish' | 'bearish';
  excess_move_pct: number | null;
  intensity: Intensity | null;
  is_exposure_only: boolean;
  in_my_holdings: boolean;
}
```

(Making a field optional only widens the type — every existing usage that always provides `relationship` keeps compiling unchanged.)

Then add the two API functions after `getFeedV2Alert`:

```ts
export async function getStockDeepDive(
  ticker: string,
  alertId?: number,
  token: string | null = null,
): Promise<StockDeepDive> {
  const query = alertId !== undefined ? `?alert_id=${alertId}` : '';
  const res = await fetch(`/api/feed-v2/stock/${encodeURIComponent(ticker)}${query}`, {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as StockDeepDive;
}

export async function getDirectory(
  filters: DirectoryFilters = {},
  token: string | null = null,
): Promise<DirectoryCompany[]> {
  const params = new URLSearchParams();
  if (filters.capTier) params.set('cap_tier', filters.capTier);
  if (filters.sector) params.set('sector', filters.sector);
  const query = params.toString() ? `?${params.toString()}` : '';
  const res = await fetch(`/api/feed-v2/directory${query}`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as DirectoryCompany[];
}
```

- [ ] **Step 4: Add `capTierColorClass` to `feedV2Format.ts`**

Add the import `CapTier` to the existing `import type { RippleRelationship, Verdict } from './feedV2Api';` line, making it `import type { CapTier, RippleRelationship, Verdict } from './feedV2Api';`. Then add:

```ts
export function capTierColorClass(tier: CapTier): string {
  if (tier === 'LARGE') return 'bg-capLarge/15 text-capLarge';
  if (tier === 'MID') return 'bg-capMid/15 text-capMid';
  return 'bg-capSmall/15 text-capSmall';
}
```

- [ ] **Step 5: Verify the frontend builds cleanly**

Run: `cd frontend && npm run build`
Expected: succeeds — `tsc --noEmit` passes.

- [ ] **Step 6: Commit**

```bash
git add frontend/tailwind.config.ts frontend/src/index.css frontend/src/lib/feedV2Api.ts frontend/src/lib/feedV2Format.ts
git commit -m "feat: add cap-tier color tokens, StockDeepDive/DirectoryCompany types, getStockDeepDive/getDirectory"
```

---

## Task 6: `BusinessPopup` — the `(i)` quick popup

**Files:**
- Create: `frontend/src/components/feed-v2/BusinessPopup.tsx`
- Create: `frontend/src/components/feed-v2/BusinessPopup.test.tsx`

**Interfaces:**
- Consumes: `capTierColorClass` (Task 5).
- Produces: `<BusinessPopup ticker ={string} sector={string} capTier={CapTier | null} businessDesc={string | null} />`. Pure presentational, same pattern as `IntensityBreakdownPopup` (Phase 5) — the caller wraps it in `AlertDetail`, this component has no modal chrome of its own.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/feed-v2/BusinessPopup.test.tsx`:

```tsx
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import BusinessPopup from './BusinessPopup';

describe('BusinessPopup', () => {
  it('renders ticker, sector, and cap tier', () => {
    render(
      <BusinessPopup
        ticker="RELIANCE.NS"
        sector="oil_gas"
        capTier="LARGE"
        businessDesc="Refines crude oil and runs retail fuel outlets."
      />,
    );
    expect(screen.getByText('RELIANCE.NS')).toBeInTheDocument();
    expect(screen.getByText('oil_gas')).toBeInTheDocument();
    expect(screen.getByText('LARGE')).toBeInTheDocument();
  });

  it('renders the business description when present', () => {
    render(
      <BusinessPopup
        ticker="RELIANCE.NS"
        sector="oil_gas"
        capTier="LARGE"
        businessDesc="Refines crude oil and runs retail fuel outlets."
      />,
    );
    expect(screen.getByText('Refines crude oil and runs retail fuel outlets.')).toBeInTheDocument();
  });

  it('renders a fallback message when business description is unavailable', () => {
    render(<BusinessPopup ticker="RELIANCE.NS" sector="oil_gas" capTier="LARGE" businessDesc={null} />);
    expect(screen.getByText(/not available/i)).toBeInTheDocument();
  });

  it('omits the cap tier tag when it is null', () => {
    render(<BusinessPopup ticker="RELIANCE.NS" sector="oil_gas" capTier={null} businessDesc="d" />);
    expect(screen.queryByText('LARGE')).not.toBeInTheDocument();
    expect(screen.queryByText('MID')).not.toBeInTheDocument();
    expect(screen.queryByText('SMALL')).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/feed-v2/BusinessPopup.test.tsx`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement**

Create `frontend/src/components/feed-v2/BusinessPopup.tsx`:

```tsx
import { capTierColorClass } from '../../lib/feedV2Format';
import type { CapTier } from '../../lib/feedV2Api';

interface BusinessPopupProps {
  ticker: string;
  sector: string;
  capTier: CapTier | null;
  businessDesc: string | null;
}

export default function BusinessPopup({ ticker, sector, capTier, businessDesc }: BusinessPopupProps) {
  return (
    <div className="flex flex-col gap-3">
      <div className="rounded-lg bg-surface p-5">
        <div className="flex items-center gap-2">
          <span className="font-data text-sm text-ink">{ticker}</span>
          <span className="font-sans text-xs uppercase tracking-widest text-muted">{sector}</span>
          {capTier && (
            <span
              className={`rounded-full px-2 py-0.5 font-sans text-[11px] uppercase tracking-widest ${capTierColorClass(capTier)}`}
            >
              {capTier}
            </span>
          )}
        </div>
      </div>
      <div className="rounded-lg bg-surface p-5">
        <p className="font-sans text-sm text-ink">
          {businessDesc ?? 'Business description not available.'}
        </p>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/feed-v2/BusinessPopup.test.tsx`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/feed-v2/BusinessPopup.tsx frontend/src/components/feed-v2/BusinessPopup.test.tsx
git commit -m "feat: add BusinessPopup -- the (i) quick business/sector popup"
```

---

## Task 7: `PeerRow` — the shared canonical ripple/peers row

**Files:**
- Create: `frontend/src/components/feed-v2/PeerRow.tsx`
- Create: `frontend/src/components/feed-v2/PeerRow.test.tsx`

**Interfaces:**
- Consumes: `formatExcess`/`intensityBandColorClass`/`capTierColorClass` (`feedV2Format.ts`), `CapTier`/`Intensity` (`feedV2Api.ts`), `react-router-dom`'s `useNavigate`.
- Produces: `<PeerRow ticker name capTier direction excessMovePct intensity isExposureOnly inMyHoldings alertId onOpenBusinessPopup />`. This is the ONE row format spec §9 describes for "ripple/peers": `[TICKER] [CAP TAG] [•owned] [intensity heat bar + score] [(i)] [›]`. Row tap navigates to `/feed-v2/stock/:ticker` (with `?alertId=` if provided); `(i)` tap calls `onOpenBusinessPopup` instead, stopping propagation on both click and keydown (same isolation discipline as Phase 5's intensity tap target). Consumed by `RippleSection.tsx` (Task 8) and `StockDeepDivePage.tsx` (Task 9).

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/feed-v2/PeerRow.test.tsx`:

```tsx
import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import PeerRow from './PeerRow';

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return { ...actual, useNavigate: () => mockNavigate };
});

function renderRow(overrides = {}) {
  const onOpenBusinessPopup = vi.fn();
  const props = {
    ticker: 'BPCL.NS',
    capTier: 'LARGE' as const,
    direction: 'bullish' as const,
    excessMovePct: 3.0,
    intensity: { score: 70, band: 'Moderate' as const, components: [] },
    isExposureOnly: false,
    inMyHoldings: false,
    alertId: 42,
    onOpenBusinessPopup,
    ...overrides,
  };
  render(
    <MemoryRouter>
      <PeerRow {...props} />
    </MemoryRouter>,
  );
  return { onOpenBusinessPopup };
}

describe('PeerRow', () => {
  beforeEach(() => {
    mockNavigate.mockClear();
  });

  it('renders ticker, cap tag, excess%, and intensity score', () => {
    renderRow();
    expect(screen.getByText('BPCL.NS')).toBeInTheDocument();
    expect(screen.getByText('LARGE')).toBeInTheDocument();
    expect(screen.getByText(/3\.0%/)).toBeInTheDocument();
    expect(screen.getByText('70')).toBeInTheDocument();
  });

  it('renders Exposure with no number/score when is_exposure_only', () => {
    renderRow({ isExposureOnly: true, excessMovePct: null, intensity: null });
    expect(screen.getByText('Exposure')).toBeInTheDocument();
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });

  it('renders an owned dot only when inMyHoldings is true', () => {
    const { container } = render(
      <MemoryRouter>
        <PeerRow
          ticker="BPCL.NS"
          capTier="LARGE"
          direction="bullish"
          excessMovePct={3.0}
          intensity={{ score: 70, band: 'Moderate', components: [] }}
          isExposureOnly={false}
          inMyHoldings
          alertId={42}
          onOpenBusinessPopup={() => {}}
        />
      </MemoryRouter>,
    );
    expect(container.querySelector('[data-testid="peer-row-owned-dot"]')).toBeInTheDocument();
  });

  it('navigates to the stock deep-dive with alertId on row tap', () => {
    renderRow();
    fireEvent.click(screen.getByRole('button', { name: /BPCL\.NS/ }));
    expect(mockNavigate).toHaveBeenCalledWith('/feed-v2/stock/BPCL.NS?alertId=42');
  });

  it('navigates without an alertId query param when none is given', () => {
    renderRow({ alertId: undefined });
    fireEvent.click(screen.getByRole('button', { name: /BPCL\.NS/ }));
    expect(mockNavigate).toHaveBeenCalledWith('/feed-v2/stock/BPCL.NS');
  });

  it('calls onOpenBusinessPopup and does not navigate when (i) is tapped', () => {
    const { onOpenBusinessPopup } = renderRow();
    fireEvent.click(screen.getByLabelText('View business details'));
    expect(onOpenBusinessPopup).toHaveBeenCalledTimes(1);
    expect(mockNavigate).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/feed-v2/PeerRow.test.tsx`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement**

Create `frontend/src/components/feed-v2/PeerRow.tsx`:

```tsx
import { useNavigate } from 'react-router-dom';
import { capTierColorClass, formatExcess, intensityBandColorClass } from '../../lib/feedV2Format';
import type { CapTier, Intensity } from '../../lib/feedV2Api';

interface PeerRowProps {
  ticker: string;
  capTier: CapTier | null;
  direction: 'bullish' | 'bearish';
  excessMovePct: number | null;
  intensity: Intensity | null;
  isExposureOnly: boolean;
  inMyHoldings: boolean;
  alertId?: number;
  onOpenBusinessPopup: () => void;
}

export default function PeerRow({
  ticker,
  capTier,
  direction,
  excessMovePct,
  intensity,
  isExposureOnly,
  inMyHoldings,
  alertId,
  onOpenBusinessPopup,
}: PeerRowProps) {
  const navigate = useNavigate();

  function goToDeepDive() {
    const query = alertId !== undefined ? `?alertId=${alertId}` : '';
    navigate(`/feed-v2/stock/${ticker}${query}`);
  }

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={goToDeepDive}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') goToDeepDive();
      }}
      aria-label={ticker}
      className="flex cursor-pointer items-center gap-3 py-1.5"
    >
      <span className="font-data text-[11px] text-muted">{ticker}</span>
      {capTier && (
        <span
          className={`rounded-full px-2 py-0.5 font-sans text-[10px] uppercase tracking-widest ${capTierColorClass(capTier)}`}
        >
          {capTier}
        </span>
      )}
      {inMyHoldings && (
        <span data-testid="peer-row-owned-dot" className="h-[7px] w-[7px] shrink-0 rounded-full bg-accent" />
      )}
      {isExposureOnly ? (
        <span className="font-sans text-xs text-muted">Exposure</span>
      ) : (
        <>
          <span className={`font-data text-xs ${direction === 'bullish' ? 'text-bullish' : 'text-bearish'}`}>
            {formatExcess(excessMovePct as number).text}
          </span>
          {intensity && (
            <>
              <span className="h-1 w-full max-w-[80px] rounded-sm bg-elevated">
                <span
                  className={`block h-full rounded-sm ${intensityBandColorClass(intensity.band)}`}
                  style={{ width: `${intensity.score}%` }}
                />
              </span>
              <span className="font-data text-[11px] text-muted">{intensity.score}</span>
            </>
          )}
        </>
      )}
      <button
        type="button"
        aria-label="View business details"
        onClick={(e) => {
          e.stopPropagation();
          onOpenBusinessPopup();
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') e.stopPropagation();
        }}
        className="ml-auto flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] text-muted"
      >
        i
      </button>
      <span className="shrink-0 text-muted" aria-hidden="true">
        ›
      </span>
    </div>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/feed-v2/PeerRow.test.tsx`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/feed-v2/PeerRow.tsx frontend/src/components/feed-v2/PeerRow.test.tsx
git commit -m "feat: add PeerRow -- canonical ripple/peers row, tap-to-deep-dive + (i) popup"
```

---

## Task 8: Retrofit `RippleSection` to use `PeerRow`

**Files:**
- Modify: `frontend/src/components/feed-v2/RippleSection.tsx`
- Modify: `frontend/src/components/feed-v2/RippleSection.test.tsx`

**Interfaces:**
- Consumes: `PeerRow` (Task 7), `BusinessPopup` (Task 6), `AlertDetail` (existing, Fragment-sibling pattern established in Phase 5).
- Produces: `RippleSection` gains a required `alertId: number` prop (every row needs it to build its deep-dive link) and a `capTier`/`business_desc`/`sector` per company — meaning `RippleCompany` (Task 5) needs `cap_tier`, `sector`, and `business_desc` added. **This requires a backend change**: `ripple.py`'s `_alert_company_rows` (and therefore `compute_ripple_companies`) must include these three fields per row.

- [ ] **Step 1: Add `cap_tier`/`business_desc` to the ripple row shape (backend)**

This is a small backend addition folded into this task rather than a separate one, since it's purely additive to already-shipped Phase 6 code and only this task's frontend work depends on it.

First, extend the test in `backend/tests/test_ripple.py`'s `test_groups_by_relationship_via_impact_edge` (and add a focused new test) to cover the new fields. Add:

```python
def test_ripple_rows_include_cap_tier_and_business_desc(db_session):
    peak = _company("PEAK.NS")
    beneficiary = Company(
        ticker="BEN.NS", name="Beneficiary Co", sector="oil_gas", index_tier="NIFTY50",
        market_cap=5000.0, business_desc="Makes beneficiary things.",
    )
    db_session.add_all([peak, beneficiary])
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, peak.id))
    db_session.add(_alert_company(alert.id, beneficiary.id))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=peak.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-4.0, sector_move_pct=-0.5, excess_move_pct=-3.5,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=beneficiary.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=2.0, sector_move_pct=0.3, excess_move_pct=1.7,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    result = compute_ripple_companies(db_session, alert, exclude_company_id=peak.id, held_company_ids=set())

    assert result[0]["business_desc"] == "Makes beneficiary things."
    assert result[0]["cap_tier"] in ("LARGE", "MID", "SMALL", None)
```

Run: `cd backend && python -m pytest tests/test_ripple.py -v -k cap_tier_and_business_desc` — expect FAIL (`KeyError`).

In `backend/app/market/ripple.py`, add the import `from app.market.cap_tier import compute_cap_tier_for_ticker` at the top. Then in `_alert_company_rows`, change the `entry` dict construction from:

```python
        entry = {
            "ticker": company.ticker,
            "name": company.name,
            "sector": company.sector,
            "direction": alert_company.direction,
            "excess_move_pct": None,
            "intensity": None,
            "is_exposure_only": exposure_only,
            "in_my_holdings": alert_company.company_id in held_company_ids,
        }
```

to:

```python
        entry = {
            "ticker": company.ticker,
            "name": company.name,
            "sector": company.sector,
            "cap_tier": compute_cap_tier_for_ticker(session, company.ticker),
            "business_desc": company.business_desc,
            "direction": alert_company.direction,
            "excess_move_pct": None,
            "intensity": None,
            "is_exposure_only": exposure_only,
            "in_my_holdings": alert_company.company_id in held_company_ids,
        }
```

Update `compute_ripple_companies`'s regression-guard assertion set (in `test_compute_ripple_companies_still_includes_relationship_after_refactor`, already written in Phase 6/Task 2 above) is now stale — update that test's `assert set(result[0].keys()) == {...}` to include `"cap_tier"` and `"business_desc"`:

```python
    assert set(result[0].keys()) == {
        "ticker", "name", "sector", "relationship", "direction", "excess_move_pct",
        "intensity", "is_exposure_only", "in_my_holdings", "cap_tier", "business_desc",
    }
```

Also update the OTHER Task 2 test that asserts an exact key set (`test_sector_peers_row_shape_matches_ripple_row_shape`) — this one does NOT gain `"sector"`, since `get_sector_peers_for_alert` still strips it (the caller already knows a peer shares the deep-dived company's sector, and `PeerRow`/`StockDeepDivePage` never read `peer.sector` — see this task's own Task 9 note about using the deep-dived company's own info for its peers' `(i)` popup, not each peer's):

```python
    assert set(result[0].keys()) == {
        "ticker", "name", "direction", "excess_move_pct", "intensity",
        "is_exposure_only", "in_my_holdings", "cap_tier", "business_desc",
    }
```

Run: `cd backend && python -m pytest tests/test_ripple.py -v` — all PASS. Run: `cd backend && python -m pytest -q` — full suite PASS (this also affects `test_seed_feed_v2_demo.py`/`test_feed_v2_router.py` only insofar as they check specific keys they already assert on — re-run to confirm no incidental breakage; if any existing test does an exact-key-set assertion on a ripple row elsewhere, update it the same way).

Commit this step:
```bash
git add backend/app/market/ripple.py backend/tests/test_ripple.py
git commit -m "feat: add cap_tier and business_desc to ripple/peer rows for the deep-dive doorway"
```

- [ ] **Step 2: Update `feedV2Api.ts`'s `RippleCompany`**

Add `cap_tier: CapTier | null;` and `business_desc: string | null;` to the `RippleCompany` interface (Task 5's edit), and add `sector: string;` too (needed by `BusinessPopup`). Final shape:

```ts
export interface RippleCompany {
  ticker: string;
  name: string;
  sector: string;
  cap_tier: CapTier | null;
  business_desc: string | null;
  relationship?: RippleRelationship;
  direction: 'bullish' | 'bearish';
  excess_move_pct: number | null;
  intensity: Intensity | null;
  is_exposure_only: boolean;
  in_my_holdings: boolean;
}
```

- [ ] **Step 3: Write the new/updated RippleSection tests**

Read the current `frontend/src/components/feed-v2/RippleSection.test.tsx` in full first — it has no `MemoryRouter` wrapper yet and its `makeCompany` factory is missing the new fields. Replace the ENTIRE file with:

```tsx
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import RippleSection from './RippleSection';
import type { RippleCompany } from '../../lib/feedV2Api';

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return { ...actual, useNavigate: () => mockNavigate };
});

function makeCompany(overrides: Partial<RippleCompany> = {}): RippleCompany {
  return {
    ticker: 'BPCL.NS',
    name: 'Bharat Petroleum',
    sector: 'oil_gas',
    cap_tier: 'LARGE',
    business_desc: 'Refines and markets petroleum products.',
    relationship: 'BENEFICIARY',
    direction: 'bullish',
    excess_move_pct: 3.0,
    intensity: { score: 70, band: 'Moderate', components: [] },
    is_exposure_only: false,
    in_my_holdings: false,
    ...overrides,
  };
}

function renderSection(companies: RippleCompany[], alertId = 42) {
  render(
    <MemoryRouter>
      <RippleSection companies={companies} alertId={alertId} />
    </MemoryRouter>,
  );
}

describe('RippleSection', () => {
  beforeEach(() => {
    mockNavigate.mockClear();
  });

  it('renders nothing when there are no companies', () => {
    const { container } = render(
      <MemoryRouter>
        <RippleSection companies={[]} alertId={42} />
      </MemoryRouter>,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('groups companies by relationship with a count label', () => {
    renderSection([
      makeCompany({ ticker: 'A.NS', relationship: 'BENEFICIARY' }),
      makeCompany({ ticker: 'B.NS', relationship: 'BENEFICIARY' }),
      makeCompany({ ticker: 'C.NS', relationship: 'COMPETITOR' }),
    ]);
    expect(screen.getByText('Beneficiary (2)')).toBeInTheDocument();
    expect(screen.getByText('Competitor (1)')).toBeInTheDocument();
  });

  it('renders ticker, cap tag, excess, and intensity score for a measured company', () => {
    renderSection([makeCompany({ ticker: 'BPCL.NS', cap_tier: 'LARGE', excess_move_pct: 3.0 })]);
    expect(screen.getByText('BPCL.NS')).toBeInTheDocument();
    expect(screen.getByText('LARGE')).toBeInTheDocument();
    expect(screen.getByText(/3\.0%/)).toBeInTheDocument();
  });

  it('renders an Exposure label with no number for an exposure-only company', () => {
    renderSection([
      makeCompany({
        ticker: 'GAIL.NS', is_exposure_only: true, excess_move_pct: null, intensity: null,
      }),
    ]);
    expect(screen.getByText('GAIL.NS')).toBeInTheDocument();
    expect(screen.getByText('Exposure')).toBeInTheDocument();
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });

  it('renders an owned dot only when in_my_holdings is true', () => {
    const { rerender, container } = render(
      <MemoryRouter>
        <RippleSection companies={[makeCompany({ in_my_holdings: false })]} alertId={42} />
      </MemoryRouter>,
    );
    expect(container.querySelector('[data-testid="peer-row-owned-dot"]')).not.toBeInTheDocument();

    rerender(
      <MemoryRouter>
        <RippleSection companies={[makeCompany({ in_my_holdings: true })]} alertId={42} />
      </MemoryRouter>,
    );
    expect(container.querySelector('[data-testid="peer-row-owned-dot"]')).toBeInTheDocument();
  });

  it('omits a relationship group entirely when it has no companies', () => {
    renderSection([makeCompany({ relationship: 'BENEFICIARY' })]);
    expect(screen.queryByText(/Substitute/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Sector wide/)).not.toBeInTheDocument();
  });

  it('navigates to the deep-dive with alertId when a row is tapped', () => {
    renderSection([makeCompany({ ticker: 'BPCL.NS' })], 42);
    fireEvent.click(screen.getByRole('button', { name: /BPCL\.NS/ }));
    expect(mockNavigate).toHaveBeenCalledWith('/feed-v2/stock/BPCL.NS?alertId=42');
  });

  it('opens the business popup and does not navigate when (i) is tapped', () => {
    renderSection([makeCompany({ ticker: 'BPCL.NS' })], 42);
    fireEvent.click(screen.getByLabelText('View business details'));
    expect(mockNavigate).not.toHaveBeenCalled();
    expect(screen.getByText('Refines and markets petroleum products.')).toBeInTheDocument();
  });
});
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/feed-v2/RippleSection.test.tsx`
Expected: FAIL — `RippleSection` doesn't yet accept `alertId`, doesn't use `PeerRow`/`BusinessPopup`.

- [ ] **Step 5: Implement**

Replace `frontend/src/components/feed-v2/RippleSection.tsx`'s content with:

```tsx
import { useState } from 'react';
import { relationshipLabel } from '../../lib/feedV2Format';
import type { RippleCompany, RippleRelationship } from '../../lib/feedV2Api';
import AlertDetail from '../AlertDetail';
import BusinessPopup from './BusinessPopup';
import PeerRow from './PeerRow';

interface RippleSectionProps {
  companies: RippleCompany[];
  alertId: number;
}

const GROUP_ORDER: RippleRelationship[] = [
  'BENEFICIARY',
  'CUSTOMER_INPUT_COST',
  'SUPPLIER',
  'SUBSTITUTE',
  'COMPETITOR',
  'SECTOR_WIDE',
];

function groupBorderColorClass(rows: RippleCompany[]): string {
  const bullishCount = rows.filter((r) => r.direction === 'bullish').length;
  const bearishCount = rows.length - bullishCount;
  return bullishCount >= bearishCount ? 'border-bullish' : 'border-bearish';
}

export default function RippleSection({ companies, alertId }: RippleSectionProps) {
  const [businessPopupTicker, setBusinessPopupTicker] = useState<string | null>(null);

  if (companies.length === 0) return null;

  const groups = GROUP_ORDER.map((relationship) => ({
    relationship,
    rows: companies.filter((c) => c.relationship === relationship),
  })).filter((g) => g.rows.length > 0);

  const popupCompany = companies.find((c) => c.ticker === businessPopupTicker) ?? null;

  return (
    <>
      <div className="rounded-lg bg-surface p-5">
        <div className="flex flex-col gap-4">
          {groups.map((group) => (
            <div
              key={group.relationship}
              className={`rounded-none border-l-2 pl-3 ${groupBorderColorClass(group.rows)}`}
            >
              <div className="font-sans text-[11px] uppercase tracking-widest text-muted">
                {relationshipLabel(group.relationship)} ({group.rows.length})
              </div>
              <div className="mt-2 flex flex-col gap-1">
                {group.rows.map((row) => (
                  <PeerRow
                    key={row.ticker}
                    ticker={row.ticker}
                    capTier={row.cap_tier}
                    direction={row.direction}
                    excessMovePct={row.excess_move_pct}
                    intensity={row.intensity}
                    isExposureOnly={row.is_exposure_only}
                    inMyHoldings={row.in_my_holdings}
                    alertId={alertId}
                    onOpenBusinessPopup={() => setBusinessPopupTicker(row.ticker)}
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
      <AlertDetail open={popupCompany !== null} onClose={() => setBusinessPopupTicker(null)}>
        {popupCompany && (
          <BusinessPopup
            ticker={popupCompany.ticker}
            sector={popupCompany.sector}
            capTier={popupCompany.cap_tier}
            businessDesc={popupCompany.business_desc}
          />
        )}
      </AlertDetail>
    </>
  );
}
```

Note the `<>...</>` Fragment-sibling rendering of `AlertDetail` (established in Phase 5) — `RippleSection` itself already renders as a sibling section inside `Level1SummaryV2`'s own `AlertDetail`, so this popup is a 2nd-level sibling modal, not nested inside any row's own clickable DOM subtree.

- [ ] **Step 6: Update `Level1SummaryV2.tsx`'s call site**

`Level1SummaryV2.tsx` currently renders `<RippleSection companies={alert.ripple} />` (Phase 6, Task 9) — it needs the new `alertId` prop. Read the current file, then change that line to `<RippleSection companies={alert.ripple} alertId={alert.id} />`.

Read `frontend/src/components/feed-v2/Level1SummaryV2.test.tsx`'s ripple-related test (`renders the ripple section when ripple data is present`, added in Phase 6/Task 9) — it doesn't currently wrap in `MemoryRouter`. Since `Level1SummaryV2.test.tsx` didn't need routing before this task, check whether the file already wraps `render(...)` in a `MemoryRouter` anywhere; if not, wrap the whole `describe` block's `render` calls, or just the ripple-specific test, in `<MemoryRouter>` — follow whichever the file's existing pattern for other route-dependent tests (if any) already does, otherwise add a local `MemoryRouter` wrapper only around the ripple test's `render(...)` call, matching `RippleSection.test.tsx`'s own approach from Step 3.

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/feed-v2/RippleSection.test.tsx src/components/feed-v2/Level1SummaryV2.test.tsx`
Expected: all PASS.

- [ ] **Step 8: Run the full frontend suite to confirm no regressions**

Run: `cd frontend && npm test -- --run`
Expected: all tests PASS.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/components/feed-v2/RippleSection.tsx frontend/src/components/feed-v2/RippleSection.test.tsx frontend/src/components/feed-v2/Level1SummaryV2.tsx frontend/src/components/feed-v2/Level1SummaryV2.test.tsx frontend/src/lib/feedV2Api.ts
git commit -m "feat: retrofit RippleSection rows to the canonical PeerRow format (cap tag, (i) popup, tap-to-deep-dive)"
```

---

## Task 9: `StockDeepDivePage` — Level 4

**Files:**
- Create: `frontend/src/pages/StockDeepDivePage.tsx`
- Create: `frontend/src/pages/StockDeepDivePage.test.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: `getStockDeepDive` (Task 5), `IntensityBreakdownPopup` (Phase 5, reused inline — NOT wrapped in a popup here, since the deep-dive page is itself the "complete stopping point"), `PeerRow` (Task 7), `capTierColorClass`/`formatExcess` (`feedV2Format.ts`), `useParams`/`useSearchParams` (`react-router-dom`).
- Produces: `<StockDeepDivePage />`, mounted at route `/feed-v2/stock/:ticker`.

**Layout (task brief Phase 7, verbatim structure):** header (name + cap tag + owned dot on the left; intensity score large and right-aligned with its band label, ONLY when alert context is present) → 3-up metric tile row (`excess`, `raw / sector`, `volume`, only when alert context present) → the breakdown (Phase 5's `IntensityBreakdownPopup`, rendered inline, only when alert context present) → "what they do" (`business_desc`) → market cap + PE facts → sector peers sorted by intensity, each row via `PeerRow`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/pages/StockDeepDivePage.test.tsx`:

```tsx
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import StockDeepDivePage from './StockDeepDivePage';
import * as feedV2Api from '../lib/feedV2Api';
import type { StockDeepDive } from '../lib/feedV2Api';

function makeDeepDive(overrides: Partial<StockDeepDive> = {}): StockDeepDive {
  return {
    ticker: 'RELIANCE.NS',
    name: 'Reliance Industries',
    sector: 'oil_gas',
    cap_tier: 'LARGE',
    business_desc: 'Refines crude oil and runs retail fuel outlets.',
    market_cap: 1500000.0,
    pe: 24.7,
    in_my_holdings: false,
    excess_move_pct: -4.2,
    raw_move_pct: -4.8,
    sector_move_pct: -0.6,
    volume_multiple: 3.1,
    intensity: { score: 82, band: 'High', components: [{ label: 'excess', raw: -4.2, weight: 0.55, contribution: 45.1 }] },
    is_exposure_only: false,
    peers: [],
    ...overrides,
  };
}

function renderPage(ticker = 'RELIANCE.NS', search = '?alertId=42') {
  return render(
    <MemoryRouter initialEntries={[`/feed-v2/stock/${ticker}${search}`]}>
      <Routes>
        <Route path="/feed-v2/stock/:ticker" element={<StockDeepDivePage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('StockDeepDivePage', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders header, metric tiles, and breakdown when alert context is present', async () => {
    vi.spyOn(feedV2Api, 'getStockDeepDive').mockResolvedValue(makeDeepDive());
    renderPage();

    await waitFor(() => expect(screen.getByText('Reliance Industries')).toBeInTheDocument());
    expect(screen.getByText('LARGE')).toBeInTheDocument();
    expect(screen.getByText('82')).toBeInTheDocument();
    expect(screen.getByText('High')).toBeInTheDocument();
    expect(screen.getByText(/4\.2%/)).toBeInTheDocument();
    expect(screen.getByText(/3\.1/)).toBeInTheDocument();
  });

  it('renders business description and market facts', async () => {
    vi.spyOn(feedV2Api, 'getStockDeepDive').mockResolvedValue(makeDeepDive());
    renderPage();

    await waitFor(() =>
      expect(screen.getByText('Refines crude oil and runs retail fuel outlets.')).toBeInTheDocument(),
    );
    expect(screen.getByText(/24\.7/)).toBeInTheDocument();
  });

  it('omits intensity/metric-tile section when no alert context is present', async () => {
    vi.spyOn(feedV2Api, 'getStockDeepDive').mockResolvedValue(
      makeDeepDive({ excess_move_pct: null, intensity: null, is_exposure_only: null }),
    );
    renderPage('RELIANCE.NS', '');

    await waitFor(() => expect(screen.getByText('Reliance Industries')).toBeInTheDocument());
    expect(screen.queryByText('High')).not.toBeInTheDocument();
  });

  it('renders sector peers sorted as returned, via PeerRow', async () => {
    vi.spyOn(feedV2Api, 'getStockDeepDive').mockResolvedValue(
      makeDeepDive({
        peers: [
          {
            ticker: 'ONGC.NS', name: 'ONGC', sector: 'oil_gas', cap_tier: 'LARGE',
            business_desc: null, direction: 'bearish', excess_move_pct: -0.3,
            intensity: { score: 20, band: 'Low', components: [] }, is_exposure_only: false,
            in_my_holdings: false,
          },
        ],
      }),
    );
    renderPage();

    await waitFor(() => expect(screen.getByText('ONGC.NS')).toBeInTheDocument());
  });

  it('renders a not-found message when the ticker does not exist', async () => {
    vi.spyOn(feedV2Api, 'getStockDeepDive').mockRejectedValue(new Error('Stock not found'));
    renderPage('NOPE.NS');

    await waitFor(() => expect(screen.getByText(/not found/i)).toBeInTheDocument());
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/pages/StockDeepDivePage.test.tsx`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement**

Create `frontend/src/pages/StockDeepDivePage.tsx`:

```tsx
import { useEffect, useState } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import IntensityBreakdownPopup from '../components/feed-v2/IntensityBreakdownPopup';
import PeerRow from '../components/feed-v2/PeerRow';
import BusinessPopup from '../components/feed-v2/BusinessPopup';
import AlertDetail from '../components/AlertDetail';
import { capTierColorClass, formatExcess } from '../lib/feedV2Format';
import { getStockDeepDive, type StockDeepDive } from '../lib/feedV2Api';
import { useAuth } from '../lib/auth';

export default function StockDeepDivePage() {
  const { ticker } = useParams<{ ticker: string }>();
  const [searchParams] = useSearchParams();
  const alertIdParam = searchParams.get('alertId');
  const alertId = alertIdParam !== null ? Number(alertIdParam) : undefined;
  const { token } = useAuth();

  const [deepDive, setDeepDive] = useState<StockDeepDive | null | undefined>(undefined);
  const [businessPopupOpen, setBusinessPopupOpen] = useState(false);

  useEffect(() => {
    if (!ticker) return;
    let active = true;
    setDeepDive(undefined);
    getStockDeepDive(ticker, alertId, token)
      .then((data) => {
        if (active) setDeepDive(data);
      })
      .catch(() => {
        if (active) setDeepDive(null);
      });
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticker, alertId, token]);

  if (deepDive === undefined) return null;

  if (deepDive === null) {
    return (
      <main className="mx-auto w-full max-w-3xl px-4 py-8">
        <p className="font-sans text-sm text-muted">Stock not found.</p>
      </main>
    );
  }

  const hasAlertContext = deepDive.excess_move_pct !== null && deepDive.intensity !== null;

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-col gap-3 px-4 py-8">
      <div className="rounded-lg bg-surface p-5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="font-sans text-lg text-ink">{deepDive.name}</span>
            {deepDive.cap_tier && (
              <span
                className={`rounded-full px-2 py-0.5 font-sans text-[11px] uppercase tracking-widest ${capTierColorClass(deepDive.cap_tier)}`}
              >
                {deepDive.cap_tier}
              </span>
            )}
            {deepDive.in_my_holdings && (
              <span className="h-[7px] w-[7px] shrink-0 rounded-full bg-accent" />
            )}
          </div>
          {hasAlertContext && deepDive.intensity && (
            <div className="flex items-baseline gap-2">
              <span className="font-data text-3xl font-medium text-ink">{deepDive.intensity.score}</span>
              <span className="font-sans text-sm text-muted">{deepDive.intensity.band}</span>
            </div>
          )}
        </div>
        <p className="mt-1 font-sans text-xs uppercase tracking-widest text-muted">
          {deepDive.ticker} · {deepDive.sector}
        </p>
      </div>

      {hasAlertContext && (
        <div className="rounded-lg bg-surface p-5">
          <div className="grid grid-cols-3 gap-4">
            <div>
              <div className="font-sans text-[11px] uppercase tracking-widest text-muted">Excess</div>
              <div className={`font-data text-lg ${(deepDive.excess_move_pct ?? 0) >= 0 ? 'text-bullish' : 'text-bearish'}`}>
                {formatExcess(deepDive.excess_move_pct as number).text}
              </div>
            </div>
            <div>
              <div className="font-sans text-[11px] uppercase tracking-widest text-muted">Raw / Sector</div>
              <div className="font-data text-lg text-ink">
                {deepDive.raw_move_pct?.toFixed(1)} / {deepDive.sector_move_pct?.toFixed(1)}
              </div>
            </div>
            <div>
              <div className="font-sans text-[11px] uppercase tracking-widest text-muted">Volume</div>
              <div className="font-data text-lg text-ink">
                {deepDive.volume_multiple !== null ? `${deepDive.volume_multiple.toFixed(1)}×` : '—'}
              </div>
            </div>
          </div>
        </div>
      )}

      {hasAlertContext && deepDive.intensity && <IntensityBreakdownPopup intensity={deepDive.intensity} />}

      <div className="rounded-lg bg-surface p-5">
        <div className="font-sans text-[11px] uppercase tracking-widest text-muted">What they do</div>
        <p className="mt-2 font-sans text-sm text-ink">
          {deepDive.business_desc ?? 'Business description not available.'}
        </p>
        <div className="mt-4 flex gap-6">
          <div>
            <div className="font-sans text-[11px] uppercase tracking-widest text-muted">Market cap</div>
            <div className="font-data text-sm text-ink">
              {deepDive.market_cap !== null ? deepDive.market_cap.toLocaleString() : '—'}
            </div>
          </div>
          <div>
            <div className="font-sans text-[11px] uppercase tracking-widest text-muted">P/E</div>
            <div className="font-data text-sm text-ink">{deepDive.pe !== null ? deepDive.pe.toFixed(1) : '—'}</div>
          </div>
        </div>
      </div>

      {deepDive.peers.length > 0 && (
        <div className="rounded-lg bg-surface p-5">
          <div className="font-sans text-[11px] uppercase tracking-widest text-muted">Sector peers</div>
          <div className="mt-2 flex flex-col gap-1">
            {deepDive.peers.map((peer) => (
              <PeerRow
                key={peer.ticker}
                ticker={peer.ticker}
                capTier={peer.cap_tier}
                direction={peer.direction}
                excessMovePct={peer.excess_move_pct}
                intensity={peer.intensity}
                isExposureOnly={peer.is_exposure_only}
                inMyHoldings={peer.in_my_holdings}
                alertId={alertId}
                onOpenBusinessPopup={() => setBusinessPopupOpen(true)}
              />
            ))}
          </div>
        </div>
      )}

      <AlertDetail open={businessPopupOpen} onClose={() => setBusinessPopupOpen(false)}>
        <BusinessPopup
          ticker={deepDive.ticker}
          sector={deepDive.sector}
          capTier={deepDive.cap_tier}
          businessDesc={deepDive.business_desc}
        />
      </AlertDetail>
    </main>
  );
}
```

Note: the peers-list `(i)` popup here is deliberately simplified to always show the CURRENT company's own business info in this first cut (`onOpenBusinessPopup={() => setBusinessPopupOpen(true)}` for every peer row) rather than each peer's own — a peer's `(i)` tap opening a per-peer popup would need per-peer state (an array of open/closed flags or a "which ticker" selector, same pattern as `RippleSection`'s `businessPopupTicker` in Task 8). **This is a known, deliberate scope-narrowing for this task** — flag it in the STOP report; if the reviewer or user wants per-peer popups here too, follow-up applies the same `businessPopupTicker`-keyed-by-ticker pattern from Task 8's `RippleSection`.

- [ ] **Step 4: Wire the route**

In `frontend/src/App.tsx`, add the import `import StockDeepDivePage from './pages/StockDeepDivePage';` (alphabetically among the existing page imports), then add the route:

```tsx
        <Route path="/feed-v2/stock/:ticker" element={<StockDeepDivePage />} />
```

directly after the existing `<Route path="/feed-v2" element={<FeedV2Page />} />` line.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/pages/StockDeepDivePage.test.tsx`
Expected: all PASS.

- [ ] **Step 6: Run the full frontend suite to confirm no regressions**

Run: `cd frontend && npm test -- --run`
Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/StockDeepDivePage.tsx frontend/src/pages/StockDeepDivePage.test.tsx frontend/src/App.tsx
git commit -m "feat: add StockDeepDivePage -- Level 4, with and without alert context"
```

---

## Task 10: `DirectoryPage` — discovery directory screen

**Files:**
- Create: `frontend/src/pages/DirectoryPage.tsx`
- Create: `frontend/src/pages/DirectoryPage.test.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/feed-v2/FeedV2.tsx`
- Modify: `frontend/src/components/feed-v2/FeedV2.test.tsx`

**Interfaces:**
- Consumes: `getDirectory` (Task 5), `capTierColorClass` (`feedV2Format.ts`), `Link`/`useNavigate` (`react-router-dom`).
- Produces: `<DirectoryPage />`, mounted at `/feed-v2/directory`. A "Browse all stocks" link in `FeedV2.tsx`'s header area.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/pages/DirectoryPage.test.tsx`:

```tsx
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import DirectoryPage from './DirectoryPage';
import * as feedV2Api from '../lib/feedV2Api';
import type { DirectoryCompany } from '../lib/feedV2Api';

function makeCompanies(): DirectoryCompany[] {
  return [
    { ticker: 'RELIANCE.NS', name: 'Reliance Industries', sector: 'oil_gas', cap_tier: 'LARGE' },
    { ticker: 'SOMETEXTILE.NS', name: 'Demo Textiles Ltd', sector: 'textiles', cap_tier: 'SMALL' },
  ];
}

describe('DirectoryPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders companies with ticker, name, sector, and cap tier', async () => {
    vi.spyOn(feedV2Api, 'getDirectory').mockResolvedValue(makeCompanies());
    render(
      <MemoryRouter>
        <DirectoryPage />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText('Reliance Industries')).toBeInTheDocument());
    expect(screen.getByText('LARGE')).toBeInTheDocument();
    expect(screen.getByText('Demo Textiles Ltd')).toBeInTheDocument();
    expect(screen.getByText('SMALL')).toBeInTheDocument();
  });

  it('re-fetches with the selected cap tier filter', async () => {
    const spy = vi.spyOn(feedV2Api, 'getDirectory').mockResolvedValue(makeCompanies());
    render(
      <MemoryRouter>
        <DirectoryPage />
      </MemoryRouter>,
    );
    await waitFor(() => expect(spy).toHaveBeenCalledWith({}, null));

    fireEvent.change(screen.getByLabelText('Cap tier'), { target: { value: 'LARGE' } });

    await waitFor(() => expect(spy).toHaveBeenCalledWith({ capTier: 'LARGE' }, null));
  });

  it('re-fetches with the selected sector filter', async () => {
    const spy = vi.spyOn(feedV2Api, 'getDirectory').mockResolvedValue(makeCompanies());
    render(
      <MemoryRouter>
        <DirectoryPage />
      </MemoryRouter>,
    );
    await waitFor(() => expect(spy).toHaveBeenCalled());

    fireEvent.change(screen.getByLabelText('Sector'), { target: { value: 'oil_gas' } });

    await waitFor(() => expect(spy).toHaveBeenCalledWith({ sector: 'oil_gas' }, null));
  });

  it('links each row to its stock deep-dive with no alertId', async () => {
    vi.spyOn(feedV2Api, 'getDirectory').mockResolvedValue(makeCompanies());
    render(
      <MemoryRouter>
        <DirectoryPage />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText('Reliance Industries')).toBeInTheDocument());
    const link = screen.getByRole('link', { name: /Reliance Industries/ });
    expect(link).toHaveAttribute('href', '/feed-v2/stock/RELIANCE.NS');
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/pages/DirectoryPage.test.tsx`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement**

Create `frontend/src/pages/DirectoryPage.tsx`:

```tsx
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { capTierColorClass } from '../lib/feedV2Format';
import { getDirectory, type CapTier, type DirectoryCompany } from '../lib/feedV2Api';
import { useAuth } from '../lib/auth';

const CAP_TIERS: CapTier[] = ['LARGE', 'MID', 'SMALL'];

export default function DirectoryPage() {
  const { token } = useAuth();
  const [capTier, setCapTier] = useState<CapTier | ''>('');
  const [sector, setSector] = useState('');
  const [companies, setCompanies] = useState<DirectoryCompany[]>([]);

  useEffect(() => {
    let active = true;
    const filters = {
      ...(capTier ? { capTier } : {}),
      ...(sector ? { sector } : {}),
    };
    getDirectory(filters, token)
      .then((data) => {
        if (active) setCompanies(data);
      })
      .catch(() => {
        if (active) setCompanies([]);
      });
    return () => {
      active = false;
    };
  }, [capTier, sector, token]);

  const sectors = Array.from(new Set(companies.map((c) => c.sector))).sort();

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-col gap-3 px-4 py-8">
      <div className="rounded-lg bg-surface p-5">
        <div className="flex gap-4">
          <label className="flex flex-col gap-1 font-sans text-xs text-muted">
            Cap tier
            <select
              aria-label="Cap tier"
              value={capTier}
              onChange={(e) => setCapTier(e.target.value as CapTier | '')}
              className="rounded-md border border-hairline bg-page px-2 py-1 font-sans text-sm text-ink"
            >
              <option value="">All</option>
              {CAP_TIERS.map((tier) => (
                <option key={tier} value={tier}>
                  {tier}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 font-sans text-xs text-muted">
            Sector
            <select
              aria-label="Sector"
              value={sector}
              onChange={(e) => setSector(e.target.value)}
              className="rounded-md border border-hairline bg-page px-2 py-1 font-sans text-sm text-ink"
            >
              <option value="">All</option>
              {sectors.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>

      <div className="rounded-lg bg-surface p-5">
        <div className="flex flex-col divide-y divide-hairline">
          {companies.map((company) => (
            <Link
              key={company.ticker}
              to={`/feed-v2/stock/${company.ticker}`}
              className="flex items-center gap-3 py-2"
            >
              <span className="flex-1 font-sans text-sm text-ink">{company.name}</span>
              <span className="font-data text-[11px] text-muted">{company.ticker}</span>
              <span className="font-sans text-xs uppercase tracking-widest text-muted">{company.sector}</span>
              <span
                className={`rounded-full px-2 py-0.5 font-sans text-[10px] uppercase tracking-widest ${capTierColorClass(company.cap_tier)}`}
              >
                {company.cap_tier}
              </span>
            </Link>
          ))}
        </div>
      </div>
    </main>
  );
}
```

- [ ] **Step 4: Wire the route + a link from `FeedV2.tsx`**

In `frontend/src/App.tsx`, add the import `import DirectoryPage from './pages/DirectoryPage';` and the route `<Route path="/feed-v2/directory" element={<DirectoryPage />} />` directly after the `StockDeepDivePage` route added in Task 9.

Read the current `frontend/src/components/feed-v2/FeedV2.tsx` in full (shown in Phase 6 context above — its top-level return is `<div className="mx-auto w-full max-w-3xl px-4">`). Add a `Link` import and a small header link, changing:

```tsx
  return (
    <div className="mx-auto w-full max-w-3xl px-4">
      <div className="rounded-lg bg-surface p-5">
```

to:

```tsx
  return (
    <div className="mx-auto w-full max-w-3xl px-4">
      <div className="mb-2 flex justify-end">
        <Link to="/feed-v2/directory" className="font-sans text-xs text-muted underline">
          Browse all stocks
        </Link>
      </div>
      <div className="rounded-lg bg-surface p-5">
```

and add `import { Link } from 'react-router-dom';` to its imports.

- [ ] **Step 5: Update `FeedV2.test.tsx`**

Read the current `frontend/src/components/feed-v2/FeedV2.test.tsx` first — check whether it already wraps `render(<FeedV2 />)` in a `MemoryRouter` (it likely does not, if `FeedV2.tsx` previously had no navigation). If it doesn't, wrap every `render(<FeedV2 />)` call in `<MemoryRouter>` (existing tests will now fail without it, since `Link` requires a Router context) and add one new test:

```tsx
it('renders a link to the stock directory', () => {
  // ... existing render setup, wrapped in MemoryRouter
  expect(screen.getByRole('link', { name: 'Browse all stocks' })).toHaveAttribute('href', '/feed-v2/directory');
});
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/pages/DirectoryPage.test.tsx src/components/feed-v2/FeedV2.test.tsx`
Expected: all PASS.

- [ ] **Step 7: Run the full frontend suite to confirm no regressions**

Run: `cd frontend && npm test -- --run`
Expected: all tests PASS.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/pages/DirectoryPage.tsx frontend/src/pages/DirectoryPage.test.tsx frontend/src/App.tsx frontend/src/components/feed-v2/FeedV2.tsx frontend/src/components/feed-v2/FeedV2.test.tsx
git commit -m "feat: add DirectoryPage -- browse/filter by cap tier + sector, no news attached"
```

---

## Task 11: Backend full regression + demo seed spot-check

**Files:**
- No new files — verification task.

- [ ] **Step 1: Run the full backend suite**

Run: `cd backend && python -m pytest -q`
Expected: all tests PASS, zero regressions from Tasks 1-4 and 8's backend changes.

- [ ] **Step 2: Spot-check the new endpoints against the existing demo seed data**

Run the seed script (`cd backend && python seed_feed_v2_demo.py`), start a background server, and curl:
- `GET /api/feed-v2/stock/RELIANCE.NS?alert_id=<reliance alert id>` — confirm `peers` includes the Phase 6 ripple companions that share RELIANCE.NS's `oil_gas` sector (BPCL.NS, IOC.NS, HPCL.NS, GAIL.NS — GAIL.NS as exposure-only), `pe` is either a real float or `null` (never fabricated), `cap_tier` is one of LARGE/MID/SMALL or `null`.
- `GET /api/feed-v2/stock/RELIANCE.NS` (no `alert_id`) — confirm `excess_move_pct`/`intensity`/`peers` are `null`/`null`/`[]`, `business_desc`/`market_cap` still populated.
- `GET /api/feed-v2/directory` — confirm all demo companies appear with a `cap_tier`.
- `GET /api/feed-v2/directory?sector=oil_gas` — confirm only oil_gas companies appear.

Stop the background server by its specific PID afterward.

- [ ] **Step 3: Report any discrepancy found**

If anything above doesn't match, fix it in the relevant Task 1-4/8 file before proceeding, then re-run the full backend suite.

---

## Task 12: Playwright screenshot verification (HARD RULE)

**Files:**
- Modify: `frontend/e2e/feed-v2-screenshots.spec.ts`

**Context:** This phase ships 2 brand-new screens (`StockDeepDivePage`, `DirectoryPage`) plus a visibly changed Level 2 ripple row (cap tag + `(i)` + chevron added). All three need fresh screenshot cases, at 390px and 1920px, dark and light — the plan's own HARD RULE, and Phase 6's own experience (the mobile Level 1 truncation bug found in that phase's Task 10) means the deep-dive page — likely tall on mobile, with header + metric tiles + breakdown + business info + peers — needs the SAME element-scoped-screenshot treatment already fixed for the Level 1 modal, generalized to a plain page (no modal clipping involved here, but still verify: `DirectoryPage`/`StockDeepDivePage` are plain routed pages, not modals, so ordinary `fullPage: true` page screenshots are the correct, sufficient approach for them — only Level 1's `AlertDetail` modal has the `position:fixed` clipping problem).

- [ ] **Step 1: Add new screenshot test cases**

Add to `frontend/e2e/feed-v2-screenshots.spec.ts`, inside the existing `for (const theme of THEMES)` loop, after the `feed-v2 intensity breakdown` test:

```ts
  test(`feed-v2 stock deep-dive with alert context (${theme})`, async ({ page }) => {
    await page.goto('/feed-v2');
    if (theme === 'light') {
      await page.evaluate(() => document.documentElement.classList.add('light'));
    }
    const firstRow = page.locator('[role="button"]').first();
    await firstRow.waitFor({ timeout: 10_000 });
    await firstRow.click();
    await page.waitForTimeout(300);
    const peerRow = page.locator('[role="dialog"] [role="button"][aria-label]').first();
    await peerRow.waitFor({ timeout: 10_000 });
    await peerRow.click();
    await page.waitForTimeout(300);
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
    const firstLink = page.getByRole('link').first();
    await firstLink.waitFor({ timeout: 10_000 });
    await firstLink.click();
    await page.waitForTimeout(300);
    await page.screenshot({
      path: `.superpowers-screenshots/feed-v2-stock-deep-dive-no-alert-${theme}-${test.info().project.name}.png`,
      fullPage: true,
    });
  });
```

- [ ] **Step 2: Seed data and start both servers**

Same process as prior phases: `python seed_feed_v2_demo.py`, start backend + frontend (check port availability, use alternates + temporary config repointing if needed, reverting before any commit).

- [ ] **Step 3: Run the screenshot spec**

Run: `cd frontend && npx playwright test`
Expected: all 24 screenshot tests pass (12 from Phases 4-6 plus 6 new cases × 2 themes × 2 viewports... i.e. the 3 new test names × 2 themes = 6 new cases, × 2 projects (mobile/desktop) = 12 new screenshots, 24 total).

- [ ] **Step 4: Look at every new screenshot — THE ACTUAL VERIFICATION STEP**

Open each of the 12 new files with the Read tool and check against the task brief's Phase 7 layout description and spec §9:
- **Stock deep-dive (with alert context):** name + cap tag + owned dot on the left of the header; intensity score+band large and right-aligned; 3-up metric tile row (excess / raw-sector / volume); the full intensity breakdown (component bars + disclaimer, matching Phase 5's popup exactly); "What they do" business text; market cap + PE; sector peers list with cap tags/bars/scores/(i)/chevron per `PeerRow`.
- **Stock deep-dive (without alert context, from Directory):** header still shows name/cap tag; NO intensity score, NO metric tile row, NO breakdown section (since `hasAlertContext` is false) — business info + market facts still show; peers list may be empty (fine, per Global Constraints).
- **Directory:** filter dropdowns visible and usable-looking; company rows with name/ticker/sector/cap tag, each a real link.
- Both themes legible, no clipped/overlapping text, cap-tag colors visually distinct from bullish/bearish/intensity colors in both themes.
- Ripple section rows (re-check the existing Level 1 screenshots too, since Task 8 changed their appearance): cap tag + `(i)` + chevron now visible per row, still no fabricated number on the GAIL.NS exposure-only row.

Write down every concrete discrepancy found. Fix it in the relevant component. Re-run Step 3 and re-check. Repeat until clean.

- [ ] **Step 5: Stop the background servers**

Kill the specific PIDs — never a broad process-kill.

- [ ] **Step 6: Run both full test suites one more time**

Run: `cd backend && python -m pytest -q` and `cd frontend && npm test -- --run` — confirm zero regressions from any Step 4 fixes.

- [ ] **Step 7: Commit**

Commit the e2e spec addition, and separately any fixes Step 4's review required, describing exactly what was found and corrected.

---

## Task 13: Full-suite regression check

- [ ] **Step 1: Run the entire backend test suite**

Run: `cd backend && python -m pytest -q`
Expected: all tests PASS.

- [ ] **Step 2: Run the entire frontend test suite**

Run: `cd frontend && npm test -- --run`
Expected: all tests PASS.

- [ ] **Step 3: Commit (only if Steps 1-2 required a fix)**

If clean, nothing to commit here.

---

## PHASE 7 STOP — required report

Report:
1. Full-suite pass/fail status, both backend and frontend.
2. All 12 new screenshots' final state — confirm each was actually opened and looked at, list every concrete difference found during Task 12's review and how it was fixed (or "clean on first pass").
3. **Flag for confirmation:** the deliberate scope-narrowing in Task 9 (the deep-dive's OWN peers-list `(i)` popup always shows the current company's own info rather than a per-peer popup) — confirm whether a follow-up to make it per-peer is wanted now or later.
4. Confirm PE ratio never shows a fabricated value: spot-check at least one company where yfinance genuinely has no PE (or force it via a mocked test) and confirm the deep-dive shows `—`, not `0` or `N/A`-as-if-measured.
5. Confirm the Directory screen truly shows no news/intensity anywhere (spec Milestone 1: "no news attached").

This plan ends here. Phase 8 (CAR review, §4.6) is a separate plan, written after this one ships and the report above is reviewed.
