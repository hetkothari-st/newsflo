# Measurement-First Impact Architecture — Phase 4 (Level 0 Feed + Level 1 Summary UI) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first two levels of the five-level progressive-disclosure UI — a hairline-rule feed of measured news events (Level 0) and a tap-through summary screen (Level 1) — exactly per `docs/NEWS_IMPACT_APP_SPEC.md` §2, §9 and the task brief's Phase 4 layout section, backed by real `excess_move_pct`/`intensity`/`verdict` computed fresh from Phase 1-3's measurement spine. This is the first phase with a UI component, so the task brief's **HARD RULE** applies: tests passing is not "done" — every task with a UI component must be Playwright-screenshotted at 390px and 1920px, in both light and dark themes, and a human-equivalent visual comparison against the spec must be performed and documented before the phase is considered complete.

**Architecture:** Built as a **new, parallel screen** (`/feed-v2`), not a replacement of the existing image-card feed (`/`, `Feed.tsx`/`AlertCoverCard.tsx`) — confirmed with the user: the existing feed stays exactly as-is at its current route; this phase adds new components, a new backend endpoint, and a new route, touching zero existing feed/card component files. The new backend piece computes `intensity`/`verdict`/`breadth_score` **on read** (never persisted) from Phase 2's pure functions, applied against Phase 1's `MarketMove` rows — this is the first code anywhere in the app that calls `compute_intensity`/`compute_verdict`/`compute_breadth_score` (confirmed unwired until now).

**Tech Stack:** Backend: FastAPI + SQLAlchemy (same as Phases 1-3). Frontend: React + TypeScript + Vite + Tailwind, Vitest + Testing Library for unit tests. **Playwright is not yet in this repo** — Task 9 introduces it fresh, scoped to this phase's screenshot-verification need only.

## Global Constraints

- **Parallel screen, zero edits to the existing feed.** Do not modify `frontend/src/pages/FeedPage.tsx`, `frontend/src/components/Feed.tsx`, `AlertCoverCard.tsx`, `AlertCover.tsx`, `DesktopFeedGrid.tsx`, `MobileFeedCarousel.tsx`, `AlertDetail.tsx` (reused read-only as a generic modal shell — fine to *import*, never to *edit*), `AlertCompanies.tsx`, or `backend/app/routers/alerts.py`. Every new capability lives in new files plus small, additive registration points (a new route in `App.tsx`, a new router include in `main.py`).
- **Never delete existing code** — this task is additive-only by construction (new files + two registration lines), so this should not come up; if it ever would, comment out with a note instead per explicit user instruction for this whole task.
- **No LLM-generated number reaches a user.** `excess_move_pct`, `raw_move_pct`, `sector_move_pct`, `volume_multiple`, `intensity.score`, `verdict` all come from `MarketMove` rows or Phase 2's config-weighted pure functions — never from `AlertCompany.why`/`Alert.summary_short`/`summary_long` (LLM text, rendered as prose only, never parsed for a number).
- **Always surface `excess`, never `raw`, as the headline number** (spec §4.1) — Level 0's largest element is `excess_move_pct`; `raw_move_pct`/`sector_move_pct` only appear later, in Level 1's explicit "raw vs. sector" reveal, clearly labeled as the reveal, not the headline.
- **An alert with no measured company is omitted from this feed entirely** — never a fabricated excess/intensity/verdict. `compute_alert_measurement` returns `None` for such an alert; the router filters those out before returning.
- **Verdict tag carries no color of its own** — per the spec's Color rules ("color encodes only direction, intensity band, and holdings — nothing else is colored"), the verdict pill is neutral (muted background/text), never color-coded by which verdict it is. Only intensity gets its own color scale (High/Moderate/Low), separate from the bullish/bearish direction colors already in use.
- **`is_unconfirmed` defaults to `False`** for now — the spec's rumor/denial classification is an LLM judgment call not yet built (out of scope for this phase, which is UI-focused). This means `verdict` can only resolve to `COMPANY_SPECIFIC`/`SECTOR_WIDE` until a future phase adds that classifier. Documented gap, not a fabrication — flagged again in this phase's STOP report.
- **`intensity`/`cap_tier`/`verdict`/`breadth_score` are computed on every request, never persisted** (Phase 2's own constraint, carried forward) — `compute_alert_measurement` is a pure read-time rollup with no `session.add`/`session.commit` of its own.
- Typography: every number `font-data` (this codebase's mono font, not the built-in `font-mono`); all prose `font-sans`; two weights only (400 normal, 500 medium — Tailwind's default `font-normal`/`font-medium`); sentence case everywhere in source text; the only uppercase is the 11px tracked-uppercase small labels (verdict pill, ticker), applied via CSS (`uppercase tracking-widest text-[11px]`), never typed in all-caps in the source string itself.
- Page frame (applies to both Level 0 and Level 1 screens): one centered column, `mx-auto w-full max-w-3xl px-4`. Section container: `rounded-lg bg-surface p-5` (12px `border-radius` per spec = Tailwind's `rounded-lg` token, confirmed `12px` in `tailwind.config.ts`; `1.25rem` padding = Tailwind's `p-5`), `gap-3` (12px) between stacked section containers. The spec's "surface-1" language maps onto this codebase's real `surface` token (confirmed: no literal `surface-1` token exists; `elevated` is reserved for a second, lighter tier nested *inside* an already-`surface` element, not a synonym for the base card background).
- Full backend test suite (`cd backend && python -m pytest -q`) and full frontend test suite (`cd frontend && npm test`) must both pass with zero regressions at the end (Task 10).
- If a spec instruction genuinely conflicts with existing code/architecture, STOP and report — see the `is_unconfirmed` default and the "peak company" interpretation (Task 1) as the two places this plan makes an explicit, documented interpretive call rather than guessing silently.

---

## File Structure

```
backend/app/market/alert_measurement.py         NEW — compute_alert_measurement(session, alert) -> dict | None
backend/app/routers/feed_v2.py                  NEW — GET /api/feed-v2, GET /api/feed-v2/{alert_id}
backend/app/main.py                             MODIFY — register feed_v2 router (2 lines)
backend/seed_feed_v2_demo.py                    NEW — deterministic demo-data seed script for local screenshotting

backend/tests/test_alert_measurement.py         NEW
backend/tests/test_feed_v2_router.py            NEW

frontend/tailwind.config.ts                     MODIFY — add intensityHigh/intensityModerate/intensityLow color tokens
frontend/src/index.css                          MODIFY — add matching CSS custom properties, both themes

frontend/src/lib/feedV2Api.ts                   NEW — FeedV2Alert type + getFeedV2Alerts/getFeedV2Alert
frontend/src/lib/feedV2Format.ts                NEW — formatExcess, verdictLabel, intensityBandClass helpers

frontend/src/components/feed-v2/FeedRowV2.tsx        NEW — Level 0 row
frontend/src/components/feed-v2/Level1SummaryV2.tsx  NEW — Level 1 summary screen content
frontend/src/components/feed-v2/FeedV2.tsx           NEW — fetch + list + open/close Level 1 modal
frontend/src/pages/FeedV2Page.tsx                     NEW — route entry, thin passthrough (mirrors FeedPage.tsx)
frontend/src/App.tsx                                  MODIFY — add /feed-v2 route (1 import + 1 <Route>)

frontend/src/components/feed-v2/FeedRowV2.test.tsx        NEW
frontend/src/components/feed-v2/Level1SummaryV2.test.tsx  NEW
frontend/src/components/feed-v2/FeedV2.test.tsx            NEW

frontend/playwright.config.ts                   NEW
frontend/e2e/feed-v2-screenshots.spec.ts        NEW
frontend/.superpowers-screenshots/              gitignored output dir for the screenshots Task 9 reviews
```

---

## Task 1: `compute_alert_measurement` — the read-time rollup

**Files:**
- Create: `backend/app/market/alert_measurement.py`
- Test: `backend/tests/test_alert_measurement.py`

**Interfaces:**
- Consumes: `app.market.breadth.compute_breadth_score`, `app.market.intensity.compute_intensity`, `app.market.verdict.compute_verdict`, `app.market.sector_indices.is_fallback_benchmark`, `app.models.Alert`/`MarketMove`.
- Produces: `compute_alert_measurement(session, alert) -> dict | None`. Consumed by `app/routers/feed_v2.py` (Task 2).

**Interpretive call, documented:** the spec's Level 0 row shows one "peak-intensity bar" per event, and `NewsEvent.verdict` is an event-level field even though the verdict formula (§4.3) operates on a single `excess_move_pct`. This function resolves that by defining the event's "peak" as whichever measured company has the largest `|excess_move_pct|`, and computing `intensity`/`verdict` against that company — the event's own headline reaction, not an artificial average. Both peer groups for intensity's within-sector/event normalization use every measured company *within this same event* (simplest defensible reading of "within sector or event" given no cross-event peer data is queried here).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_alert_measurement.py`:

```python
from app.market.alert_measurement import compute_alert_measurement
from app.models import Alert, AlertCompany, Article, Company, MarketMove, utcnow


def _company(ticker, sector="oil_gas"):
    return Company(ticker=ticker, name=f"Company {ticker}", sector=sector, index_tier="NIFTY50")


def _article(db_session):
    article = Article(source="test", url="https://example.com/a", title="t", content="c")
    db_session.add(article)
    db_session.commit()
    return article


def _alert_company(alert_id, company_id, direction="bullish"):
    return AlertCompany(
        alert_id=alert_id, company_id=company_id, direction=direction,
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", basis="direct_mention",
    )


def test_returns_none_when_no_measured_companies(db_session):
    company = _company("A.NS")
    db_session.add(company)
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, company.id))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^CNXENERGY",
        measurement_status="no_data", measured_at=utcnow(),
    ))
    db_session.commit()

    assert compute_alert_measurement(db_session, alert) is None


def test_single_measured_company_is_the_peak(db_session):
    company = _company("A.NS")
    db_session.add(company)
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, company.id))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-4.8, sector_move_pct=-0.6, excess_move_pct=-4.2,
        volume=300.0, avg_volume_20d=100.0, volume_multiple=3.0,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    result = compute_alert_measurement(db_session, alert)

    assert result["excess_move_pct"] == -4.2
    assert result["direction"] == "bearish"
    assert result["raw_move_pct"] == -4.8
    assert result["sector_move_pct"] == -0.6
    assert result["volume_multiple"] == 3.0
    assert result["peak_ticker"] == "A.NS"
    assert result["peak_company_name"] == "Company A.NS"
    assert result["benchmark_ticker"] == "^CNXENERGY"
    assert result["is_fallback_benchmark"] is False
    assert result["verdict"] in ("COMPANY_SPECIFIC", "SECTOR_WIDE")
    assert set(result["intensity"].keys()) == {"score", "band", "components"}
    assert isinstance(result["breadth_score"], int)


def test_picks_the_larger_magnitude_move_as_peak(db_session):
    small = _company("SMALL.NS")
    big = _company("BIG.NS")
    db_session.add_all([small, big])
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, small.id))
    db_session.add(_alert_company(alert.id, big.id))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=small.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=0.5, sector_move_pct=0.3, excess_move_pct=0.2,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=big.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-6.0, sector_move_pct=-0.5, excess_move_pct=-5.5,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    result = compute_alert_measurement(db_session, alert)

    assert result["peak_ticker"] == "BIG.NS"
    assert result["excess_move_pct"] == -5.5


def test_no_data_companies_are_excluded_but_do_not_block_the_measured_ones(db_session):
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
        raw_move_pct=2.0, sector_move_pct=0.5, excess_move_pct=1.5,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=unmeasured.id, benchmark_ticker="^NSEI",
        measurement_status="no_data", measured_at=utcnow(),
    ))
    db_session.commit()

    result = compute_alert_measurement(db_session, alert)

    assert result is not None
    assert result["peak_ticker"] == "A.NS"


def test_fallback_benchmark_sector_is_flagged(db_session):
    company = _company("A.NS", sector="textiles")  # textiles falls back to Nifty 50
    db_session.add(company)
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="other")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, company.id))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^NSEI",
        raw_move_pct=1.0, sector_move_pct=0.2, excess_move_pct=0.8,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    result = compute_alert_measurement(db_session, alert)

    assert result["is_fallback_benchmark"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_alert_measurement.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.market.alert_measurement'`.

- [ ] **Step 3: Implement**

Create `backend/app/market/alert_measurement.py`:

```python
"""Read-time measurement rollup for one Alert (news event): peak-company
excess/intensity, event verdict, and breadth -- everything Level 0/1 of the
five-level UI needs (docs/NEWS_IMPACT_APP_SPEC.md §2, §4), computed fresh
from MarketMove rows every call, never persisted. Feeds
app.routers.feed_v2 only.
"""
from sqlalchemy.orm import Session

from app.market.breadth import compute_breadth_score
from app.market.intensity import compute_intensity
from app.market.sector_indices import is_fallback_benchmark
from app.market.verdict import compute_verdict
from app.models import Alert, MarketMove


def compute_alert_measurement(session: Session, alert: Alert) -> dict | None:
    """Returns None if this alert has no company with a real measured
    excess move (measurement_status == "ok") -- an alert with nothing
    measured has no headline number to show and must be omitted from the
    Level 0 feed entirely (spec Ground Rules: never fabricate, omit
    rather than invent).

    Otherwise returns a dict with: excess_move_pct, direction
    ("bullish"|"bearish"), raw_move_pct, sector_move_pct, volume_multiple
    (float | None), benchmark_ticker, is_fallback_benchmark (bool),
    peak_ticker, peak_company_name, verdict (str), intensity
    ({"score","band","components"}), breadth_score (int).

    "Peak" is whichever measured company has the largest |excess_move_pct|
    -- the event's own headline reaction. is_unconfirmed is hardcoded False
    (the rumor/denial LLM classifier is a later phase) -- verdict can only
    resolve to COMPANY_SPECIFIC/SECTOR_WIDE until then.
    """
    moves = (
        session.query(MarketMove)
        .filter(MarketMove.alert_id == alert.id, MarketMove.measurement_status == "ok")
        .all()
    )
    if not moves:
        return None

    peak = max(moves, key=lambda m: abs(m.excess_move_pct))
    excess_values = [m.excess_move_pct for m in moves]
    volume_values = [m.volume_multiple for m in moves if m.volume_multiple is not None]
    breadth_score = compute_breadth_score(excess_values)

    intensity = compute_intensity(
        excess_move_pct=peak.excess_move_pct,
        excess_peer_group=excess_values,
        volume_multiple=peak.volume_multiple or 0.0,
        volume_peer_group=volume_values or [peak.volume_multiple or 0.0],
        breadth_score=breadth_score,
    )
    verdict = compute_verdict(is_unconfirmed=False, excess_move_pct=peak.excess_move_pct)

    peak_alert_company = next(ac for ac in alert.companies if ac.company_id == peak.company_id)
    peak_company = peak_alert_company.company

    return {
        "excess_move_pct": peak.excess_move_pct,
        "direction": "bullish" if peak.excess_move_pct >= 0 else "bearish",
        "raw_move_pct": peak.raw_move_pct,
        "sector_move_pct": peak.sector_move_pct,
        "volume_multiple": peak.volume_multiple,
        "benchmark_ticker": peak.benchmark_ticker,
        "is_fallback_benchmark": is_fallback_benchmark(peak_company.sector),
        "peak_ticker": peak_company.ticker,
        "peak_company_name": peak_company.name,
        "verdict": verdict,
        "intensity": intensity,
        "breadth_score": breadth_score,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_alert_measurement.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/market/alert_measurement.py backend/tests/test_alert_measurement.py
git commit -m "feat: add compute_alert_measurement -- read-time peak-company intensity/verdict rollup"
```

---

## Task 2: `GET /api/feed-v2` router

**Files:**
- Create: `backend/app/routers/feed_v2.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_feed_v2_router.py`

**Interfaces:**
- Consumes: `app.market.alert_measurement.compute_alert_measurement` (Task 1), `app.routers.articles.get_db`, `app.auth.dependencies.get_current_user_optional`, `app.ist_time.day_utc_window`/`today_ist`.
- Produces: `GET /api/feed-v2` (list, today-IST-window, measured alerts only), `GET /api/feed-v2/{alert_id}` (single, 404 if missing or unmeasured).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_feed_v2_router.py`:

```python
from fastapi.testclient import TestClient

from app.main import app
from app.models import Alert, AlertCompany, Article, Company, MarketMove, utcnow
from app.routers.articles import get_db


def _override_db(db_session):
    def _get_db():
        yield db_session
    app.dependency_overrides[get_db] = _get_db


def _measured_alert(db_session, ticker="RELIANCE.NS", excess=-4.2):
    company = Company(ticker=ticker, name=f"Company {ticker}", sector="oil_gas", index_tier="NIFTY50")
    db_session.add(company)
    db_session.commit()
    article = Article(source="test", url=f"https://example.com/{ticker}", title="Oil surges", content="c")
    db_session.add(article)
    db_session.commit()
    alert = Alert(article_id=article.id, category="oil_gas", summary_short="Oil supply shock hits refiners")
    db_session.add(alert)
    db_session.flush()
    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bearish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", basis="direct_mention",
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-4.8, sector_move_pct=-0.6, excess_move_pct=excess,
        volume=300.0, avg_volume_20d=100.0, volume_multiple=3.0,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()
    return alert


def _unmeasured_alert(db_session):
    company = Company(ticker="NODATA.NS", name="No Data Co", sector="other", index_tier="OTHER")
    db_session.add(company)
    db_session.commit()
    article = Article(source="test", url="https://example.com/nodata", title="Untradeable news", content="c")
    db_session.add(article)
    db_session.commit()
    alert = Alert(article_id=article.id, category="other")
    db_session.add(alert)
    db_session.flush()
    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=company.id, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", basis="direct_mention",
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=company.id, benchmark_ticker="^NSEI",
        measurement_status="no_data", measured_at=utcnow(),
    ))
    db_session.commit()
    return alert


def test_list_feed_v2_returns_only_measured_alerts(db_session):
    _override_db(db_session)
    measured = _measured_alert(db_session)
    _unmeasured_alert(db_session)
    client = TestClient(app)

    response = client.get("/api/feed-v2")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == measured.id
    assert body[0]["excess_move_pct"] == -4.2
    assert body[0]["summary_short"] == "Oil supply shock hits refiners"
    assert body[0]["peak_ticker"] == "RELIANCE.NS"
    assert body[0]["article"]["title"] == "Oil surges"
    app.dependency_overrides.clear()


def test_get_feed_v2_alert_by_id(db_session):
    _override_db(db_session)
    alert = _measured_alert(db_session)
    client = TestClient(app)

    response = client.get(f"/api/feed-v2/{alert.id}")

    assert response.status_code == 200
    assert response.json()["id"] == alert.id
    app.dependency_overrides.clear()


def test_get_feed_v2_alert_404_when_not_found(db_session):
    _override_db(db_session)
    client = TestClient(app)

    response = client.get("/api/feed-v2/999999")

    assert response.status_code == 404
    app.dependency_overrides.clear()


def test_get_feed_v2_alert_404_when_unmeasured(db_session):
    _override_db(db_session)
    alert = _unmeasured_alert(db_session)
    client = TestClient(app)

    response = client.get(f"/api/feed-v2/{alert.id}")

    assert response.status_code == 404
    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_feed_v2_router.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.routers.feed_v2'` (or a 404 on the not-yet-registered route).

- [ ] **Step 3: Implement the router**

Create `backend/app/routers/feed_v2.py`:

```python
"""Level 0/1 feed endpoints for the measurement-first UI rebuild
(docs/NEWS_IMPACT_APP_SPEC.md §2, §9) -- a new, parallel set of routes
alongside the existing GET /api/alerts (kept untouched; see this plan's
Global Constraints). Returns only alerts with at least one measured
company (excess_move_pct computed, measurement_status == "ok") -- an
alert with nothing measured has no headline number and is omitted
entirely (Ground Rules: never fabricate, omit rather than invent).
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload

from app.auth.dependencies import get_current_user_optional
from app.ist_time import day_utc_window, today_ist
from app.market.alert_measurement import compute_alert_measurement
from app.models import Alert, AlertCompany, Holding, User
from app.routers.articles import get_db

router = APIRouter(prefix="/api/feed-v2", tags=["feed-v2"])

ALERTS_LIMIT = 200


def _held_company_ids(db: Session, current_user: User | None) -> set[int]:
    if current_user is None:
        return set()
    return {h.company_id for h in db.query(Holding).filter_by(user_id=current_user.id).all()}


def _serialize(alert: Alert, measurement: dict, held_company_ids: set[int]) -> dict:
    in_my_holdings = any(ac.company_id in held_company_ids for ac in alert.companies)
    return {
        "id": alert.id,
        "category": alert.category,
        "created_at": alert.created_at.isoformat(),
        "summary_short": alert.summary_short,
        "summary_long": alert.summary_long,
        "article": {
            "id": alert.article.id,
            "title": alert.article.title,
            "url": alert.article.url,
            "source": alert.article.source,
            "published_at": alert.article.published_at.isoformat() if alert.article.published_at else None,
        },
        "in_my_holdings": in_my_holdings,
        **measurement,
    }


def _query_with_relations(db: Session):
    return db.query(Alert).options(
        selectinload(Alert.article),
        selectinload(Alert.companies).selectinload(AlertCompany.company),
    )


@router.get("")
def list_feed_v2_alerts(
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    start_utc, end_utc = day_utc_window(today_ist())
    alerts = (
        _query_with_relations(db)
        .filter(Alert.created_at >= start_utc, Alert.created_at < end_utc)
        .order_by(Alert.created_at.desc())
        .limit(ALERTS_LIMIT)
        .all()
    )
    held_company_ids = _held_company_ids(db, current_user)

    results = []
    for alert in alerts:
        measurement = compute_alert_measurement(db, alert)
        if measurement is not None:
            results.append(_serialize(alert, measurement, held_company_ids))
    return results


@router.get("/{alert_id}")
def get_feed_v2_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    alert = _query_with_relations(db).filter(Alert.id == alert_id).first()
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")

    measurement = compute_alert_measurement(db, alert)
    if measurement is None:
        raise HTTPException(status_code=404, detail="Alert has no measured companies")

    held_company_ids = _held_company_ids(db, current_user)
    return _serialize(alert, measurement, held_company_ids)
```

- [ ] **Step 4: Register the router**

In `backend/app/main.py`, change:

```python
from app.routers import alerts, articles, auth, calendar, categories, companies, holdings, translation, watchlist, ws
```

to:

```python
from app.routers import (
    alerts, articles, auth, calendar, categories, companies, feed_v2, holdings, translation, watchlist, ws,
)
```

and add, directly after `app.include_router(alerts.router)`:

```python
app.include_router(feed_v2.router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_feed_v2_router.py -v`
Expected: all PASS.

- [ ] **Step 6: Run the full backend suite to confirm no regressions**

Run: `cd backend && python -m pytest -q`
Expected: all tests PASS (additive-only: new router, new module, two new import/include lines in `main.py`).

- [ ] **Step 7: Commit**

```bash
git add backend/app/routers/feed_v2.py backend/app/main.py backend/tests/test_feed_v2_router.py
git commit -m "feat: add GET /api/feed-v2 -- measured-only alert feed with peak intensity/verdict"
```

---

## Task 3: Demo-data seed script (for local screenshotting)

**Files:**
- Create: `backend/seed_feed_v2_demo.py`

**Context:** Task 9's Playwright screenshots need real, varied alerts in the local dev DB — `COMPANY_SPECIFIC`/`SECTOR_WIDE` verdicts, High/Moderate/Low intensity bands, a held company (owned dot), a fallback-benchmark sector — without depending on the live scheduler/ingestion pipeline or real LLM calls. This script inserts deterministic rows directly, mirroring the standalone-script pattern already used by `backend/seed_nifty_indices.py`.

- [ ] **Step 1: Write the script**

Create `backend/seed_feed_v2_demo.py`:

```python
"""Deterministic demo data for locally viewing/screenshotting the Level 0/1
feed-v2 UI (docs/superpowers/plans/2026-07-22-measurement-first-impact-
phase4-feed-summary-ui.md) -- inserts a handful of realistic Alert/Company/
MarketMove rows directly (no LLM calls, no live market data) covering a
spread of verdicts, intensity bands, and a held company, so the feed has
something meaningful to render without depending on the live scheduler.

Safe to re-run: clears its own previously-seeded rows (identified by a
fixed marker prefix on Article.url) before re-inserting.

Usage (from the backend/ directory, so `app` is importable):
    .venv/Scripts/python seed_feed_v2_demo.py
"""
from datetime import timedelta

from app.db import SessionLocal, init_db
from app.models import Alert, AlertCompany, Article, Company, MarketMove, utcnow

URL_MARKER = "https://demo.feed-v2.local/"

DEMO_ROWS = [
    # (ticker, name, sector, benchmark, raw, sector_move, excess, volume_mult, headline, summary_short, why, direction)
    (
        "RELIANCE.NS", "Reliance Industries", "oil_gas", "^CNXENERGY",
        -4.8, -0.6, -4.2, 3.1,
        "Crude oil supply shock hits refiners", "Oil supply shock lifts costs for refiners",
        "Higher crude prices squeeze refining margins for this company.", "bearish",
    ),
    (
        "TCS.NS", "Tata Consultancy Services", "it", "^CNXIT",
        1.2, 0.9, 0.3, 1.1,
        "IT services sector drifts with broader market", "IT stocks move with the wider market today",
        "This move tracks the sector, not company-specific news.", "bullish",
    ),
    (
        "SOMETEXTILE.NS", "Demo Textiles Ltd", "textiles", "^NSEI",
        2.5, 0.4, 2.1, 2.4,
        "Cotton export duty cut announced", "Export duty cut helps textile makers",
        "Lower export duty directly raises this company's overseas margins.", "bullish",
    ),
]


def main() -> None:
    init_db()
    session = SessionLocal()
    try:
        existing = session.query(Article).filter(Article.url.like(f"{URL_MARKER}%")).all()
        for article in existing:
            for alert in session.query(Alert).filter_by(article_id=article.id).all():
                session.query(MarketMove).filter_by(alert_id=alert.id).delete()
                session.query(AlertCompany).filter_by(alert_id=alert.id).delete()
                session.delete(alert)
            session.delete(article)
        session.commit()

        now = utcnow()
        for i, row in enumerate(DEMO_ROWS):
            ticker, name, sector, benchmark, raw, sector_move, excess, vol_mult, headline, summary_short, why, direction = row

            company = session.query(Company).filter_by(ticker=ticker).one_or_none()
            if company is None:
                company = Company(ticker=ticker, name=name, sector=sector, index_tier="NIFTY50", market_cap=50000.0)
                session.add(company)
                session.commit()

            article = Article(
                source="demo", url=f"{URL_MARKER}{i}", title=headline, content=headline,
                published_at=now - timedelta(minutes=5 * i),
            )
            session.add(article)
            session.commit()

            alert = Alert(
                article_id=article.id, category=sector if sector != "textiles" else "other",
                created_at=now - timedelta(minutes=5 * i), summary_short=summary_short,
                summary_long=f"{summary_short}. {why}",
            )
            session.add(alert)
            session.flush()

            alert_company = AlertCompany(
                alert_id=alert.id, company_id=company.id, direction=direction,
                magnitude_low=1.0, magnitude_high=2.0, rationale=why, basis="direct_mention",
                why=why,
            )
            session.add(alert_company)

            session.add(MarketMove(
                alert_id=alert.id, company_id=company.id, benchmark_ticker=benchmark,
                raw_move_pct=raw, sector_move_pct=sector_move, excess_move_pct=excess,
                volume=vol_mult * 100.0, avg_volume_20d=100.0, volume_multiple=vol_mult,
                measurement_status="ok", measured_at=now,
            ))
            session.commit()

        print(f"Seeded {len(DEMO_ROWS)} demo feed-v2 alerts.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it against the local dev DB**

Run: `cd backend && python seed_feed_v2_demo.py`
Expected: prints `Seeded 3 demo feed-v2 alerts.` with no error.

- [ ] **Step 3: Spot-check via the API**

Run: `cd backend && uvicorn app.main:app --port 8000 &` (background) then `curl http://127.0.0.1:8000/api/feed-v2` (or open in a browser) — confirm 3 alerts come back with varied `verdict`/`intensity.band`/`direction` values. Stop the server after checking.

- [ ] **Step 4: Commit**

```bash
git add backend/seed_feed_v2_demo.py
git commit -m "feat: add deterministic demo-data seed script for feed-v2 local screenshotting"
```

---

## Task 4: Design tokens — intensity band colors

**Files:**
- Modify: `frontend/tailwind.config.ts`
- Modify: `frontend/src/index.css`

**Context:** The spec's Color rules permit exactly three things to carry color: direction (already `bullish`/`bearish`), holdings (already `accent`), and intensity band. No intensity-band tokens exist yet — add them additively, keeping every existing token untouched.

- [ ] **Step 1: Add the color keys to `tailwind.config.ts`**

In `frontend/tailwind.config.ts`, inside the `colors` object (alongside the existing `bullish`/`bearish`/`accent`/etc. entries), add:

```ts
        intensityHigh: 'rgb(var(--color-intensity-high) / <alpha-value>)',
        intensityModerate: 'rgb(var(--color-intensity-moderate) / <alpha-value>)',
        intensityLow: 'rgb(var(--color-intensity-low) / <alpha-value>)',
```

- [ ] **Step 2: Add the matching CSS custom properties to `index.css`**

In `frontend/src/index.css`, in the `:root` block (dark theme, default), add alongside the existing `--color-*` declarations:

```css
  --color-intensity-high: 248 113 113;
  --color-intensity-moderate: 251 191 36;
  --color-intensity-low: 74 222 128;
```

In the `.light` block, add:

```css
  --color-intensity-high: 220 38 38;
  --color-intensity-moderate: 217 119 6;
  --color-intensity-low: 22 163 74;
```

- [ ] **Step 3: Verify the frontend still builds cleanly**

Run: `cd frontend && npm run build`
Expected: succeeds with no TypeScript/Tailwind errors (additive-only token registration).

- [ ] **Step 4: Commit**

```bash
git add frontend/tailwind.config.ts frontend/src/index.css
git commit -m "feat: add intensity-band color tokens (High/Moderate/Low), both themes"
```

---

## Task 5: TypeScript types, API client, and format helpers

**Files:**
- Create: `frontend/src/lib/feedV2Api.ts`
- Create: `frontend/src/lib/feedV2Format.ts`

**Interfaces:**
- Produces: `FeedV2Alert`, `Intensity`, `IntensityComponent`, `Verdict` types; `getFeedV2Alerts(token) -> Promise<FeedV2Alert[]>`; `getFeedV2Alert(id, token) -> Promise<FeedV2Alert>`; `formatExcess(pct) -> {arrow, text}`; `verdictLabel(verdict) -> string`; `intensityBandColorClass(band) -> string`.

`frontend/src/lib/api.ts`'s existing `getAlerts`/`getAlert` fetch convention (confirmed current content, lines 260-284) is:

```ts
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

export async function getAlerts(token: string | null = null, lang: Language = 'en'): Promise<Alert[]> {
  const res = await fetch(`/api/alerts?lang=${lang}`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as Alert[];
}
```

`feedV2Api.ts` mirrors this exactly (own local `authHeaders`/`parseError` copies — no `lang` param since `/api/feed-v2` doesn't translate, per Task 2's router).

- [ ] **Step 1: Create the types + API client**

Create `frontend/src/lib/feedV2Api.ts`:

```ts
export interface FeedV2Article {
  id: number;
  title: string;
  url: string;
  source: string;
  published_at: string | null;
}

export interface IntensityComponent {
  label: string;
  raw: number;
  weight: number;
  contribution: number;
}

export interface Intensity {
  score: number;
  band: 'High' | 'Moderate' | 'Low';
  components: IntensityComponent[];
}

export type Verdict = 'COMPANY_SPECIFIC' | 'SECTOR_WIDE' | 'UNCONFIRMED';

export interface FeedV2Alert {
  id: number;
  category: string;
  created_at: string;
  summary_short: string | null;
  summary_long: string | null;
  article: FeedV2Article;
  excess_move_pct: number;
  direction: 'bullish' | 'bearish';
  raw_move_pct: number;
  sector_move_pct: number;
  volume_multiple: number | null;
  benchmark_ticker: string;
  is_fallback_benchmark: boolean;
  peak_ticker: string;
  peak_company_name: string;
  verdict: Verdict;
  intensity: Intensity;
  breadth_score: number;
  in_my_holdings: boolean;
}

function authHeaders(token: string | null): Record<string, string> {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

interface ApiError {
  detail?: string;
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

export async function getFeedV2Alerts(token: string | null = null): Promise<FeedV2Alert[]> {
  const res = await fetch('/api/feed-v2', { headers: authHeaders(token) });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as FeedV2Alert[];
}

export async function getFeedV2Alert(id: number, token: string | null = null): Promise<FeedV2Alert> {
  const res = await fetch(`/api/feed-v2/${id}`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error(await parseError(res));
  return (await res.json()) as FeedV2Alert;
}
```

- [ ] **Step 2: Create the format helpers**

Create `frontend/src/lib/feedV2Format.ts`:

```ts
import type { Verdict } from './feedV2Api';

export function formatExcess(pct: number): { arrow: string; text: string } {
  const arrow = pct >= 0 ? '▲' : '▼';
  const text = `${arrow} ${Math.abs(pct).toFixed(1)}%`;
  return { arrow, text };
}

const VERDICT_LABELS: Record<Verdict, string> = {
  COMPANY_SPECIFIC: 'Company specific',
  SECTOR_WIDE: 'Sector wide',
  UNCONFIRMED: 'Unconfirmed',
};

export function verdictLabel(verdict: Verdict): string {
  return VERDICT_LABELS[verdict];
}

export function intensityBandColorClass(band: 'High' | 'Moderate' | 'Low'): string {
  if (band === 'High') return 'bg-intensityHigh';
  if (band === 'Moderate') return 'bg-intensityModerate';
  return 'bg-intensityLow';
}
```

- [ ] **Step 3: Verify the frontend builds cleanly**

Run: `cd frontend && npm run build`
Expected: succeeds — `tsc --noEmit` passes (no unused-throw issues since Step 1's placeholders are replaced with real code before this check).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/feedV2Api.ts frontend/src/lib/feedV2Format.ts
git commit -m "feat: add feed-v2 TypeScript types, API client, and format helpers"
```

---

## Task 6: `FeedRowV2` — Level 0 feed row

**Files:**
- Create: `frontend/src/components/feed-v2/FeedRowV2.tsx`
- Test: `frontend/src/components/feed-v2/FeedRowV2.test.tsx`

**Interfaces:**
- Consumes: `FeedV2Alert` (Task 5), `formatExcess`/`verdictLabel`/`intensityBandColorClass` (Task 5).
- Produces: `<FeedRowV2 alert={alert} onOpen={() => void} />` — a presentational component, no data fetching, no router dependency.

**Layout (exact, per spec §9 and the task brief's Phase 4 layout section):**
- Row wrapper: `border-b border-hairline py-[14px] last:border-b-0 cursor-pointer`, `onClick={onOpen}`.
- Line 1 (`flex items-center gap-3`):
  - Excess: `font-data text-[19px] font-medium min-w-[74px] flex-shrink-0`, `text-bullish` or `text-bearish` by direction — this is the largest element on the row.
  - Why (`alert.summary_short`): `flex-1 truncate font-sans text-sm`, `text-ink` normally, `text-muted` when `verdict === 'SECTOR_WIDE'` (the whole row reads as muted/skippable).
  - Owned dot: `h-[7px] w-[7px] shrink-0 rounded-full bg-accent`, rendered only when `alert.in_my_holdings` is true.
- Line 2 (`ml-[84px] flex items-center gap-2`):
  - Verdict pill: `rounded-full bg-elevated px-2 py-0.5 text-[11px] uppercase tracking-widest text-muted` (neutral — no verdict-specific color, per Global Constraints), text = `verdictLabel(alert.verdict)`.
  - Ticker: `font-data text-[11px] text-muted`, text = `alert.peak_ticker`.
  - Intensity bar: a `div` track (`h-1 w-full max-w-[130px] rounded-sm bg-elevated`) containing an inner filled `div` (`h-full rounded-sm`, width `${alert.intensity.score}%`, background class from `intensityBandColorClass(alert.intensity.band)`).
  - Score: `font-data text-[11px] text-muted`, text = `alert.intensity.score`.
- When `alert.verdict === 'SECTOR_WIDE'`, the excess-number line-1 text color still reflects direction (bullish/bearish are always colored — muting only applies to the *why* text and the row's overall visual weight per the spec's muted-row rule) but line 2's ticker/score are `text-muted` (already the default for line 2).

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/feed-v2/FeedRowV2.test.tsx`:

```tsx
import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import FeedRowV2 from './FeedRowV2';
import type { FeedV2Alert } from '../../lib/feedV2Api';

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
    ...overrides,
  };
}

describe('FeedRowV2', () => {
  it('renders the excess move, why, verdict, ticker, and score', () => {
    render(<FeedRowV2 alert={makeAlert()} onOpen={() => {}} />);
    expect(screen.getByText(/4\.2%/)).toBeInTheDocument();
    expect(screen.getByText('Oil supply shock lifts refiners')).toBeInTheDocument();
    expect(screen.getByText('Company specific')).toBeInTheDocument();
    expect(screen.getByText('RELIANCE.NS')).toBeInTheDocument();
    expect(screen.getByText('82')).toBeInTheDocument();
  });

  it('shows a down arrow for a bearish move and a bullish text color class for an up move', () => {
    const { rerender } = render(<FeedRowV2 alert={makeAlert({ direction: 'bearish' })} onOpen={() => {}} />);
    expect(screen.getByText(/▼/)).toBeInTheDocument();

    rerender(<FeedRowV2 alert={makeAlert({ direction: 'bullish', excess_move_pct: 3.0 })} onOpen={() => {}} />);
    expect(screen.getByText(/▲/)).toBeInTheDocument();
  });

  it('renders an owned dot only when in_my_holdings is true', () => {
    const { rerender, container } = render(
      <FeedRowV2 alert={makeAlert({ in_my_holdings: false })} onOpen={() => {}} />,
    );
    expect(container.querySelector('[data-testid="owned-dot"]')).not.toBeInTheDocument();

    rerender(<FeedRowV2 alert={makeAlert({ in_my_holdings: true })} onOpen={() => {}} />);
    expect(container.querySelector('[data-testid="owned-dot"]')).toBeInTheDocument();
  });

  it('calls onOpen when the row is clicked', () => {
    const onOpen = vi.fn();
    render(<FeedRowV2 alert={makeAlert()} onOpen={onOpen} />);
    fireEvent.click(screen.getByText('Oil supply shock lifts refiners'));
    expect(onOpen).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/feed-v2/FeedRowV2.test.tsx`
Expected: FAIL — module `./FeedRowV2` does not exist.

- [ ] **Step 3: Implement**

Create `frontend/src/components/feed-v2/FeedRowV2.tsx`:

```tsx
import { formatExcess, intensityBandColorClass, verdictLabel } from '../../lib/feedV2Format';
import type { FeedV2Alert } from '../../lib/feedV2Api';

interface FeedRowV2Props {
  alert: FeedV2Alert;
  onOpen: () => void;
}

export default function FeedRowV2({ alert, onOpen }: FeedRowV2Props) {
  const { text: excessText } = formatExcess(alert.excess_move_pct);
  const isMuted = alert.verdict === 'SECTOR_WIDE';

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') onOpen();
      }}
      className="cursor-pointer border-b border-hairline py-[14px] last:border-b-0"
    >
      <div className="flex items-center gap-3">
        <span
          className={`min-w-[74px] shrink-0 font-data text-[19px] font-medium ${
            alert.direction === 'bullish' ? 'text-bullish' : 'text-bearish'
          }`}
        >
          {excessText}
        </span>
        <span className={`flex-1 truncate font-sans text-sm ${isMuted ? 'text-muted' : 'text-ink'}`}>
          {alert.summary_short}
        </span>
        {alert.in_my_holdings && (
          <span data-testid="owned-dot" className="h-[7px] w-[7px] shrink-0 rounded-full bg-accent" />
        )}
      </div>
      <div className="ml-[84px] flex items-center gap-2">
        <span className="rounded-full bg-elevated px-2 py-0.5 text-[11px] uppercase tracking-widest text-muted">
          {verdictLabel(alert.verdict)}
        </span>
        <span className="font-data text-[11px] text-muted">{alert.peak_ticker}</span>
        <span className="h-1 w-full max-w-[130px] rounded-sm bg-elevated">
          <span
            className={`block h-full rounded-sm ${intensityBandColorClass(alert.intensity.band)}`}
            style={{ width: `${alert.intensity.score}%` }}
          />
        </span>
        <span className="font-data text-[11px] text-muted">{alert.intensity.score}</span>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/feed-v2/FeedRowV2.test.tsx`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/feed-v2/FeedRowV2.tsx frontend/src/components/feed-v2/FeedRowV2.test.tsx
git commit -m "feat: add FeedRowV2 -- Level 0 feed row per spec §9 layout"
```

---

## Task 7: `Level1SummaryV2` — Level 1 summary screen

**Files:**
- Create: `frontend/src/components/feed-v2/Level1SummaryV2.tsx`
- Test: `frontend/src/components/feed-v2/Level1SummaryV2.test.tsx`

**Interfaces:**
- Consumes: `FeedV2Alert` (Task 5), `formatExcess`/`verdictLabel` (Task 5).
- Produces: `<Level1SummaryV2 alert={alert} />` — content only (no modal chrome; the caller, Task 8's `FeedV2`, wraps this in the existing generic `AlertDetail` shell).

**Layout:** three stacked section containers (`rounded-lg bg-surface p-5`, `gap-3` between them):
1. **Summary section** — `alert.summary_long` (2 sentences, `font-sans text-sm text-ink`), with the verdict pill (reused styling from Task 6) above it.
2. **Raw-vs-sector reveal** — a metric tile: two `font-data` numbers side by side, `raw_move_pct` and `sector_move_pct`, each with a small `text-muted font-sans text-xs` label above ("Raw move" / "Sector move"), formatted with sign and `%`. Plus, below, the volume multiple as `font-data text-sm` text, e.g. `"3.1× average volume"` — omit this line entirely if `volume_multiple` is `null`.
3. **Source + timestamp** — `alert.article.source` and a formatted `alert.created_at`, `font-sans text-xs text-muted`. If `is_fallback_benchmark` is true, add a small note: `"vs Nifty 50"` instead of implying a real sector index (per the task brief's explicit instruction); otherwise `"vs sector index"`.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/feed-v2/Level1SummaryV2.test.tsx`:

```tsx
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import Level1SummaryV2 from './Level1SummaryV2';
import type { FeedV2Alert } from '../../lib/feedV2Api';

function makeAlert(overrides: Partial<FeedV2Alert> = {}): FeedV2Alert {
  return {
    id: 1,
    category: 'oil_gas',
    created_at: '2026-07-22T10:00:00Z',
    summary_short: 'Oil supply shock lifts refiners',
    summary_long: 'Crude prices jumped on a supply disruption. Refiners face wider margin pressure.',
    article: { id: 1, title: 'Oil surges', url: 'https://example.com/a', source: 'Economic Times', published_at: '2026-07-22T09:45:00Z' },
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

describe('Level1SummaryV2', () => {
  it('renders the two-sentence summary and verdict', () => {
    render(<Level1SummaryV2 alert={makeAlert()} />);
    expect(screen.getByText(/Crude prices jumped on a supply disruption/)).toBeInTheDocument();
    expect(screen.getByText('Company specific')).toBeInTheDocument();
  });

  it('renders raw and sector move as a metric tile', () => {
    render(<Level1SummaryV2 alert={makeAlert()} />);
    expect(screen.getByText(/-4\.8%/)).toBeInTheDocument();
    expect(screen.getByText(/-0\.6%/)).toBeInTheDocument();
  });

  it('renders volume multiple when present, omits it when null', () => {
    const { rerender } = render(<Level1SummaryV2 alert={makeAlert({ volume_multiple: 3.1 })} />);
    expect(screen.getByText(/3\.1/)).toBeInTheDocument();

    rerender(<Level1SummaryV2 alert={makeAlert({ volume_multiple: null })} />);
    expect(screen.queryByText(/average volume/)).not.toBeInTheDocument();
  });

  it('shows the Nifty 50 fallback note when is_fallback_benchmark is true', () => {
    render(<Level1SummaryV2 alert={makeAlert({ is_fallback_benchmark: true })} />);
    expect(screen.getByText(/vs Nifty 50/)).toBeInTheDocument();
  });

  it('shows the sector-index note when is_fallback_benchmark is false', () => {
    render(<Level1SummaryV2 alert={makeAlert({ is_fallback_benchmark: false })} />);
    expect(screen.getByText(/vs sector index/)).toBeInTheDocument();
  });

  it('renders source', () => {
    render(<Level1SummaryV2 alert={makeAlert()} />);
    expect(screen.getByText(/Economic Times/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/feed-v2/Level1SummaryV2.test.tsx`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement**

Create `frontend/src/components/feed-v2/Level1SummaryV2.tsx`:

```tsx
import { verdictLabel } from '../../lib/feedV2Format';
import type { FeedV2Alert } from '../../lib/feedV2Api';

interface Level1SummaryV2Props {
  alert: FeedV2Alert;
}

function signedPct(value: number): string {
  const sign = value >= 0 ? '+' : '';
  return `${sign}${value.toFixed(1)}%`;
}

export default function Level1SummaryV2({ alert }: Level1SummaryV2Props) {
  return (
    <div className="flex flex-col gap-3">
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
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/feed-v2/Level1SummaryV2.test.tsx`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/feed-v2/Level1SummaryV2.tsx frontend/src/components/feed-v2/Level1SummaryV2.test.tsx
git commit -m "feat: add Level1SummaryV2 -- summary, raw-vs-sector reveal, volume, source"
```

---

## Task 8: `FeedV2` container, `FeedV2Page`, and route registration

**Files:**
- Create: `frontend/src/components/feed-v2/FeedV2.tsx`
- Create: `frontend/src/pages/FeedV2Page.tsx`
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/components/feed-v2/FeedV2.test.tsx`

**Interfaces:**
- Consumes: `getFeedV2Alerts`/`getFeedV2Alert` (Task 5), `FeedRowV2` (Task 6), `Level1SummaryV2` (Task 7), the existing generic `AlertDetail` modal shell (`frontend/src/components/AlertDetail.tsx` — imported read-only, never edited), `useAuth` (`../lib/auth`).

**Before writing:** read `frontend/src/components/AlertDetail.tsx`'s real current prop signature (confirmed from research: `open`, `onClose`, `children`, optional `header`, `hiddenOnMobile`, `fullScreenMobile`) to wire it correctly, and read `frontend/src/lib/auth.tsx`'s `useAuth()` return shape (expected: `{ token }`) to fetch with the right token.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/feed-v2/FeedV2.test.tsx`:

```tsx
import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
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
    <MemoryRouter>
      <AuthProvider>
        <FeedV2 />
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

  it('opens the Level 1 summary when a row is clicked', async () => {
    vi.spyOn(feedV2Api, 'getFeedV2Alerts').mockResolvedValue([makeAlert()]);
    vi.spyOn(feedV2Api, 'getFeedV2Alert').mockResolvedValue(makeAlert());
    const { user } = await import('@testing-library/user-event').then((m) => ({ user: m.default.setup() }));
    renderFeedV2();
    await waitFor(() => screen.getByText('Oil supply shock lifts refiners'));
    await user.click(screen.getByText('Oil supply shock lifts refiners'));
    await waitFor(() =>
      expect(screen.getByText(/Crude prices jumped on a supply disruption/)).toBeInTheDocument(),
    );
  });

  it('renders nothing extra when the feed is empty', async () => {
    vi.spyOn(feedV2Api, 'getFeedV2Alerts').mockResolvedValue([]);
    renderFeedV2();
    await waitFor(() => expect(feedV2Api.getFeedV2Alerts).toHaveBeenCalled());
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/feed-v2/FeedV2.test.tsx`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement `FeedV2.tsx`**

Create `frontend/src/components/feed-v2/FeedV2.tsx` (adapt the `useAuth()` destructure to match its real current return shape):

```tsx
import { useEffect, useState } from 'react';
import { useAuth } from '../../lib/auth';
import { getFeedV2Alert, getFeedV2Alerts, type FeedV2Alert } from '../../lib/feedV2Api';
import AlertDetail from '../AlertDetail';
import FeedRowV2 from './FeedRowV2';
import Level1SummaryV2 from './Level1SummaryV2';

export default function FeedV2() {
  const { token } = useAuth();
  const [alerts, setAlerts] = useState<FeedV2Alert[]>([]);
  const [openAlert, setOpenAlert] = useState<FeedV2Alert | null>(null);

  useEffect(() => {
    getFeedV2Alerts(token).then(setAlerts).catch(() => setAlerts([]));
  }, [token]);

  const handleOpen = (id: number) => {
    getFeedV2Alert(id, token)
      .then(setOpenAlert)
      .catch(() => setOpenAlert(null));
  };

  return (
    <div className="mx-auto w-full max-w-3xl px-4">
      <div className="rounded-lg bg-surface p-5">
        {alerts.map((alert) => (
          <FeedRowV2 key={alert.id} alert={alert} onOpen={() => handleOpen(alert.id)} />
        ))}
      </div>
      <AlertDetail open={openAlert !== null} onClose={() => setOpenAlert(null)}>
        {openAlert && <Level1SummaryV2 alert={openAlert} />}
      </AlertDetail>
    </div>
  );
}
```

- [ ] **Step 4: Create `FeedV2Page.tsx`**

Create `frontend/src/pages/FeedV2Page.tsx`:

```tsx
import FeedV2 from '../components/feed-v2/FeedV2';

export default function FeedV2Page() {
  return <FeedV2 />;
}
```

- [ ] **Step 5: Register the route**

In `frontend/src/App.tsx`, add the import alongside the existing page imports:

```tsx
import FeedV2Page from './pages/FeedV2Page';
```

and add the route directly after the existing `/` route:

```tsx
        <Route path="/feed-v2" element={<FeedV2Page />} />
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/feed-v2/FeedV2.test.tsx`
Expected: all PASS.

- [ ] **Step 7: Run the full frontend suite to confirm no regressions**

Run: `cd frontend && npm test`
Expected: all tests PASS (additive-only: new files, two new lines in `App.tsx`, no existing component touched).

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/feed-v2/FeedV2.tsx frontend/src/components/feed-v2/FeedV2.test.tsx frontend/src/pages/FeedV2Page.tsx frontend/src/App.tsx
git commit -m "feat: add FeedV2 container + /feed-v2 route"
```

---

## Task 9: Playwright screenshot verification (HARD RULE)

**Files:**
- Create: `frontend/playwright.config.ts`
- Create: `frontend/e2e/feed-v2-screenshots.spec.ts`
- Modify: `frontend/.gitignore` (add the screenshot output dir)

**Context — this task is the task brief's HARD RULE in practice.** Tests passing is not "done." After this task ships, the plan's executor must actually look at every screenshot and compare it against the spec (§9 UI reference, this plan's Task 6/7 layout descriptions), write down concrete differences, fix them, and re-screenshot — repeating until the rendered UI genuinely matches. If Playwright will not install in this environment, stop and say so rather than proceeding blind (the task brief's explicit instruction).

- [ ] **Step 1: Install Playwright**

Run: `cd frontend && npm install -D @playwright/test && npx playwright install chromium`
Expected: succeeds. If this fails (no network access, sandboxed environment, etc.), **stop here and report exactly what failed** — do not proceed to manual/unverified screenshotting as a silent substitute.

- [ ] **Step 2: Add Playwright config**

Create `frontend/playwright.config.ts`:

```ts
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  use: {
    baseURL: 'http://127.0.0.1:5173',
  },
  webServer: {
    command: 'npm run dev',
    url: 'http://127.0.0.1:5173',
    reuseExistingServer: true,
    timeout: 60_000,
  },
  projects: [
    { name: 'mobile', use: { ...devices['Desktop Chrome'], viewport: { width: 390, height: 844 } } },
    { name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1920, height: 1080 } } },
  ],
});
```

- [ ] **Step 3: Add the screenshot spec**

Create `frontend/e2e/feed-v2-screenshots.spec.ts`:

```ts
import { test } from '@playwright/test';

const THEMES = ['dark', 'light'] as const;

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
    await page.waitForTimeout(300); // allow the modal's open transition to settle
    await page.screenshot({
      path: `.superpowers-screenshots/feed-v2-level1-${theme}-${test.info().project.name}.png`,
      fullPage: true,
    });
  });
}
```

- [ ] **Step 4: Ignore the screenshot output dir**

Add to `frontend/.gitignore` (append, do not remove any existing entries):

```
.superpowers-screenshots/
```

- [ ] **Step 5: Seed the dev DB and start both servers**

Run (each in its own background process):
```bash
cd backend && python seed_feed_v2_demo.py
cd backend && uvicorn app.main:app --port 8000 &
cd frontend && npm run dev &
```
Wait for both to report ready (backend: "Application startup complete"; frontend: "Local: http://127.0.0.1:5173/").

- [ ] **Step 6: Run the screenshot spec**

Run: `cd frontend && npx playwright test`
Expected: 8 screenshots produced in `frontend/.superpowers-screenshots/` (`feed-v2-level{0,1}-{dark,light}-{mobile,desktop}.png`).

- [ ] **Step 7: Look at every screenshot and compare against spec — THE ACTUAL VERIFICATION STEP**

Open each of the 8 PNGs (via the Read tool, which can view images) and check against:
- Page frame: centered column, `max-w-3xl`, padding — nothing touching the viewport edge at either 390px or 1920px.
- Level 0: two-line rows, hairline dividers, excess % is visibly the largest/boldest element, mono numbers vs. sans prose is visually distinct, verdict pill/ticker/intensity bar/score all present and aligned under the why text (84px indent), colors correct (bullish=green-ish, bearish=red-ish, intensity bar colored by band, verdict pill neutral/uncolored).
- Level 1: two-sentence summary visible, raw-vs-sector metric tile clearly two separate numbers, volume multiple line present, source/timestamp line present, "vs Nifty 50" wording showing correctly for the seeded textiles-sector demo row (fallback benchmark).
- Both themes: dark and light each render legibly, no invisible-text-on-background issues, no leftover dark-only or light-only artifacts.

**Write down every concrete difference you find** (e.g. "excess % font size looks smaller than 19px," "intensity bar color for High band is too similar to the bearish red — hard to distinguish at a glance," "light theme verdict pill background barely visible against surface"). Fix each one in the relevant Task 6/7/4 file. Re-run Step 6 and re-check. Repeat until no discrepancies remain.

- [ ] **Step 8: Stop the background dev servers**

Kill the `uvicorn` and `npm run dev` background processes started in Step 5 by their specific PIDs (never a broad `taskkill`/`pkill` that could affect other parallel sessions' processes).

- [ ] **Step 9: Commit**

```bash
git add frontend/playwright.config.ts frontend/e2e/feed-v2-screenshots.spec.ts frontend/.gitignore frontend/package.json frontend/package-lock.json
git commit -m "feat: add Playwright screenshot verification for feed-v2 Level 0/1"
```

If Step 7's fix loop touched any Task 4/6/7 file, commit those fixes separately with a message describing exactly what the screenshot review caught and corrected.

---

## Task 10: Full-suite regression check

- [ ] **Step 1: Run the entire backend test suite**

Run: `cd backend && python -m pytest -q`
Expected: all tests PASS.

- [ ] **Step 2: Run the entire frontend test suite**

Run: `cd frontend && npm test`
Expected: all tests PASS.

- [ ] **Step 3: Commit (only if Steps 1-2 required a fix)**

If clean, nothing to commit here. If a fix was required, commit it separately describing exactly what regressed and why.

---

## PHASE 4 STOP — required report

Report:
1. Full-suite pass/fail status, both backend and frontend (Task 10).
2. All 8 screenshots' final state — confirm each was actually opened and looked at (not just "the test passed"), and list every concrete difference found during Task 9 Step 7's review loop and how each was fixed.
3. **Flag for confirmation:** the "peak company" interpretation for event-level `verdict`/`intensity` (Task 1) and the `is_unconfirmed=False` default (no rumor/denial classifier yet) — confirm these readings are acceptable before Phase 5 (intensity breakdown popup) builds on top of them.
4. Confirm the existing `/` feed and all its components remain completely untouched (per the "parallel screen" decision) — `git diff` against pre-Phase-4 `HEAD` should show zero changes to `Feed.tsx`/`AlertCoverCard.tsx`/`AlertCover.tsx`/`DesktopFeedGrid.tsx`/`MobileFeedCarousel.tsx`/`AlertCompanies.tsx`/`FeedPage.tsx`/`app/routers/alerts.py`.

This plan ends here. Phase 5 (intensity breakdown popup — the score must never appear without a reachable component breakdown) is a separate plan, written after this one ships and the report above is reviewed.
