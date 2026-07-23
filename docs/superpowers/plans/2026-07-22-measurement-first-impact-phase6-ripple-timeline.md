# Measurement-First Impact Architecture — Phase 6 (Level 2 Ripple + Level 3 Timeline) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Level 2 (ripple — "who else does it touch?") and Level 3 (timeline — "blip or slow burn?") per `docs/NEWS_IMPACT_APP_SPEC.md` §2, §3.1 and the task brief's Phase 6 layout section. Level 0/1 (Phases 4-5) only ever showed the event's single "peak" company; this phase surfaces every OTHER company tied to the alert, grouped by relationship type, plus the LLM-generated per-horizon timeline effects that Phase 3 already persists (`TimelineEffect` rows) but has never been read by any API endpoint until now.

**Architecture:** Two new backend data-assembly functions (`compute_ripple_companies`, `get_timeline_entries`), wired into the existing `GET /api/feed-v2/{alert_id}` detail endpoint only (the list endpoint stays unchanged — Level 0 doesn't need this). Two new frontend components (`RippleSection`, `TimelineSection`), appended to the existing `Level1SummaryV2` content (this phase's own interpretive call — see Global Constraints). This phase has UI components, so the task brief's HARD RULE applies again: Playwright screenshots, actually looked at, before this phase is done.

**Tech Stack:** Same as Phases 4-5 — FastAPI + SQLAlchemy backend, React + TypeScript + Vite + Tailwind frontend, Vitest + Testing Library, Playwright (already installed, this phase extends the existing `e2e/feed-v2-screenshots.spec.ts`).

## Global Constraints

- **Never fabricate a number for an unmeasured ripple company.** A company with `measurement_status != "ok"` (including no `MarketMove` row at all) renders as a flagged EXPOSURE — ticker + relationship group only, no excess%, no intensity bar, no score. This is the single most safety-critical rule in this phase (spec §3, Ground Rules, and Phase 3's own `is_exposure_only` helper this phase finally puts to use).
- **The peak company (already shown at Level 0/1) is excluded from the ripple list** — Level 2 answers "who ELSE does it touch," not a repeat of the headline. `compute_ripple_companies` takes an explicit `exclude_company_id` parameter for this.
- **Two interpretive calls this plan makes explicitly (flagged again in the STOP report, not assumed silently):**
  1. **Ripple/timeline are additional sections within the SAME Level 1 detail view** (appended below the existing summary/metric-tile/source sections in `Level1SummaryV2`), not separate tap-through screens. The spec calls each level "a complete stopping point," which a scrollable single view still satisfies; the task brief gives no explicit navigation instruction for Levels 2/3, and this keeps the existing `AlertDetail` modal/routing model unchanged.
  2. **A ripple group's `border-left` accent color follows the MAJORITY direction among its rows** (bullish if bullish-count ≥ bearish-count, else bearish) — the spec says a group's border takes "its direction color" but a relationship group can genuinely contain both bullish and bearish companies (e.g. a `COMPETITOR` group), so a single color needs a tie-break rule.
- **Breadth stays event-scoped.** `compute_ripple_companies`' intensity calculations reuse breadth computed from THIS alert's own companies (unchanged from Phase 4) — only the excess/volume peer groups are sector-wide-across-today (Phase 4's own fix, reused via a shared helper this phase extracts).
- **Timeline only shows horizons with real content.** `TimelineEffect` rows only exist for horizons the LLM refinement layer (Phase 3) found genuine, distinct content for — `get_timeline_entries` orders what exists, it never invents a missing horizon.
- **Never delete existing code.** This phase modifies `alert_measurement.py` (extracting a shared helper — a real, intentional refactor of already-shipped code from this same ongoing build) and `feed_v2.py`/`Level1SummaryV2.tsx` (additive extensions) — the existing behavior of all three must be provably unchanged for every case that doesn't involve the new fields.
- **No LLM-generated number reaches a user.** Every ripple/timeline number comes from `MarketMove`/`compute_intensity`/`compute_breadth_score` (Phase 1-2) or is the LLM's own prose text (`TimelineEffect.description`, rendered as-is, never parsed for a number) — consistent with every prior phase.
- Full backend and frontend test suites must both pass with zero regressions at the end.

---

## File Structure

```
backend/app/market/alert_measurement.py       MODIFY — extract _intensity_for_company_move, add peak_company_id
backend/app/market/ripple.py                  NEW — compute_ripple_companies
backend/app/market/timeline_entries.py        NEW — get_timeline_entries
backend/app/routers/feed_v2.py                MODIFY — detail endpoint gains ripple + timeline
backend/seed_feed_v2_demo.py                  MODIFY — add ripple companions + ImpactEdge rows + TimelineEffect rows

backend/tests/test_alert_measurement.py       MODIFY — cover the peak_company_id addition
backend/tests/test_ripple.py                  NEW
backend/tests/test_timeline_entries.py        NEW
backend/tests/test_feed_v2_router.py          MODIFY — detail endpoint now includes ripple/timeline

frontend/src/lib/feedV2Api.ts                 MODIFY — RippleCompany, TimelineEntry, RippleRelationship, TimelineHorizon types; FeedV2Alert gains optional ripple/timeline
frontend/src/lib/feedV2Format.ts              MODIFY — relationshipLabel

frontend/src/components/feed-v2/RippleSection.tsx        NEW
frontend/src/components/feed-v2/RippleSection.test.tsx   NEW
frontend/src/components/feed-v2/TimelineSection.tsx       NEW
frontend/src/components/feed-v2/TimelineSection.test.tsx  NEW
frontend/src/components/feed-v2/Level1SummaryV2.tsx       MODIFY — render the two new sections when present
frontend/src/components/feed-v2/Level1SummaryV2.test.tsx MODIFY — new tests for the two sections' presence

frontend/e2e/feed-v2-screenshots.spec.ts      MODIFY — Level 1 screenshots now include ripple/timeline content
```

---

## Task 1: Extract shared intensity helper, add `peak_company_id`

**Files:**
- Modify: `backend/app/market/alert_measurement.py`
- Modify: `backend/tests/test_alert_measurement.py`

**Interfaces:**
- Produces: `_intensity_for_company_move(session, company, move, breadth_score) -> dict` (module-private, shared helper). `compute_alert_measurement`'s returned dict gains a new key: `peak_company_id: int`. Every existing key is unchanged.

- [ ] **Step 1: Add a test for the new `peak_company_id` field**

Append to `backend/tests/test_alert_measurement.py` (reuse the file's existing `_company`/`_article`/`_alert_company` helpers):

```python
def test_result_includes_peak_company_id(db_session):
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
        raw_move_pct=2.0, sector_move_pct=0.5, excess_move_pct=1.5,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    result = compute_alert_measurement(db_session, alert)

    assert result["peak_company_id"] == company.id
```

- [ ] **Step 2: Run tests to verify the new test fails**

Run: `cd backend && python -m pytest tests/test_alert_measurement.py -v -k peak_company_id`
Expected: FAIL — `KeyError: 'peak_company_id'`.

- [ ] **Step 3: Refactor**

Replace `backend/app/market/alert_measurement.py`'s content with:

```python
"""Read-time measurement rollup for one Alert (news event): peak-company
excess/intensity, event verdict, and breadth -- everything Level 0/1 of the
five-level UI needs (docs/NEWS_IMPACT_APP_SPEC.md §2, §4), computed fresh
from MarketMove rows every call, never persisted. Feeds
app.routers.feed_v2 only.
"""
from sqlalchemy.orm import Session

from app.ist_time import day_utc_window, today_ist
from app.market.breadth import compute_breadth_score
from app.market.intensity import compute_intensity
from app.market.sector_indices import is_fallback_benchmark
from app.market.verdict import compute_verdict
from app.models import Alert, Company, MarketMove


def _sector_peer_moves(session: Session, sector: str) -> list[MarketMove]:
    """Every measured (status='ok') MarketMove today for companies in the
    given sector, across ALL of today's alerts -- not just one event. This
    is the real comparison population for intensity's within-sector
    normalization (spec §4.2): a single-company event's own excess move is
    trivially the max of a group containing only itself, so a peer group
    must reach beyond one event to be a meaningful comparison, or every
    single-company alert scores 100/High regardless of real magnitude.
    """
    start_utc, end_utc = day_utc_window(today_ist())
    return (
        session.query(MarketMove)
        .join(Company, MarketMove.company_id == Company.id)
        .join(Alert, MarketMove.alert_id == Alert.id)
        .filter(
            Company.sector == sector,
            MarketMove.measurement_status == "ok",
            Alert.created_at >= start_utc,
            Alert.created_at < end_utc,
        )
        .all()
    )


def _intensity_for_company_move(session: Session, company: Company, move: MarketMove, breadth_score: int) -> dict:
    """Compute intensity for one (company, move) pair, normalized against
    every measured company in the same sector across today's alerts (see
    _sector_peer_moves). Shared by compute_alert_measurement (for the
    event's peak company) and app.market.ripple.compute_ripple_companies
    (for every other measured company in the event's ripple) -- the exact
    same normalization discipline applies to both, so this is the one
    place that logic lives.
    """
    sector_moves = _sector_peer_moves(session, company.sector)
    excess_peer_group = [m.excess_move_pct for m in sector_moves] or [move.excess_move_pct]
    sector_volume_values = [m.volume_multiple for m in sector_moves if m.volume_multiple is not None]
    volume_peer_group = sector_volume_values or [move.volume_multiple or 0.0]
    return compute_intensity(
        excess_move_pct=move.excess_move_pct,
        excess_peer_group=excess_peer_group,
        volume_multiple=move.volume_multiple or 0.0,
        volume_peer_group=volume_peer_group,
        breadth_score=breadth_score,
    )


def compute_alert_measurement(session: Session, alert: Alert) -> dict | None:
    """Returns None if this alert has no company with a real measured
    excess move (measurement_status == "ok") -- an alert with nothing
    measured has no headline number to show and must be omitted from the
    Level 0 feed entirely (spec Ground Rules: never fabricate, omit
    rather than invent).

    Otherwise returns a dict with: excess_move_pct, direction
    ("bullish"|"bearish"), raw_move_pct, sector_move_pct, volume_multiple
    (float | None), benchmark_ticker, is_fallback_benchmark (bool),
    peak_ticker, peak_company_id, peak_company_name, verdict (str),
    intensity ({"score","band","components"}), breadth_score (int).

    "Peak" is whichever measured company has the largest |excess_move_pct|
    -- the event's own headline reaction. breadth_score is event-scoped
    (spec §4.4: how widely THIS event rippled). is_unconfirmed is
    hardcoded False (the rumor/denial LLM classifier is a later phase) --
    verdict can only resolve to COMPANY_SPECIFIC/SECTOR_WIDE until then.
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
    breadth_score = compute_breadth_score(excess_values)

    peak_alert_company = next(ac for ac in alert.companies if ac.company_id == peak.company_id)
    peak_company = peak_alert_company.company

    intensity = _intensity_for_company_move(session, peak_company, peak, breadth_score)
    verdict = compute_verdict(is_unconfirmed=False, excess_move_pct=peak.excess_move_pct)

    return {
        "excess_move_pct": peak.excess_move_pct,
        "direction": "bullish" if peak.excess_move_pct >= 0 else "bearish",
        "raw_move_pct": peak.raw_move_pct,
        "sector_move_pct": peak.sector_move_pct,
        "volume_multiple": peak.volume_multiple,
        "benchmark_ticker": peak.benchmark_ticker,
        "is_fallback_benchmark": is_fallback_benchmark(peak_company.sector),
        "peak_ticker": peak_company.ticker,
        "peak_company_id": peak_company.id,
        "peak_company_name": peak_company.name,
        "verdict": verdict,
        "intensity": intensity,
        "breadth_score": breadth_score,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_alert_measurement.py -v`
Expected: all PASS (the 6 existing tests from Phases 4-5 plus the new one) — the refactor must not change any existing test's outcome.

- [ ] **Step 5: Commit**

```bash
git add backend/app/market/alert_measurement.py backend/tests/test_alert_measurement.py
git commit -m "refactor: extract _intensity_for_company_move, add peak_company_id to compute_alert_measurement"
```

---

## Task 2: `compute_ripple_companies` — Level 2 data

**Files:**
- Create: `backend/app/market/ripple.py`
- Test: `backend/tests/test_ripple.py`

**Interfaces:**
- Consumes: `app.market.alert_measurement._intensity_for_company_move` (Task 1), `app.market.breadth.compute_breadth_score`, `app.reasoning.ripple_relationship.is_exposure_only`/`relation_to_ripple_relationship`, `app.models.Alert`/`ImpactEdge`/`MarketMove`.
- Produces: `compute_ripple_companies(session, alert, exclude_company_id, held_company_ids) -> list[dict]`. Consumed by `app/routers/feed_v2.py` (Task 3).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_ripple.py`:

```python
from app.market.ripple import compute_ripple_companies
from app.models import Alert, AlertCompany, Article, Company, ImpactEdge, MarketMove, utcnow


def _company(ticker, sector="oil_gas"):
    return Company(ticker=ticker, name=f"Company {ticker}", sector=sector, index_tier="NIFTY50")


def _article(db_session):
    article = Article(source="test", url=f"https://example.com/{id(object())}", title="t", content="c")
    db_session.add(article)
    db_session.commit()
    return article


def _alert_company(alert_id, company_id, direction="bullish"):
    return AlertCompany(
        alert_id=alert_id, company_id=company_id, direction=direction,
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", basis="direct_mention",
    )


def _edge(alert_id, from_id, to_id, relation, direction="bullish"):
    return ImpactEdge(
        alert_id=alert_id, from_company_id=from_id, from_node_kind="company", from_label="X",
        to_company_id=to_id, to_node_kind="company", to_label="Y",
        relation=relation, direction=direction, note="n", source="llm_only",
    )


def test_excludes_the_peak_company(db_session):
    peak = _company("PEAK.NS")
    other = _company("OTHER.NS")
    db_session.add_all([peak, other])
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, peak.id))
    db_session.add(_alert_company(alert.id, other.id))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=peak.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-4.0, sector_move_pct=-0.5, excess_move_pct=-3.5,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=other.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=1.0, sector_move_pct=0.2, excess_move_pct=0.8,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    result = compute_ripple_companies(db_session, alert, exclude_company_id=peak.id, held_company_ids=set())

    tickers = {r["ticker"] for r in result}
    assert tickers == {"OTHER.NS"}


def test_groups_by_relationship_via_impact_edge(db_session):
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

    assert result[0]["relationship"] == "BENEFICIARY"


def test_company_with_no_edge_defaults_to_sector_wide(db_session):
    peak = _company("PEAK.NS")
    unlinked = _company("UNLINKED.NS")
    db_session.add_all([peak, unlinked])
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, peak.id))
    db_session.add(_alert_company(alert.id, unlinked.id))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=peak.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-4.0, sector_move_pct=-0.5, excess_move_pct=-3.5,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=unlinked.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=1.0, sector_move_pct=0.2, excess_move_pct=0.8,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    result = compute_ripple_companies(db_session, alert, exclude_company_id=peak.id, held_company_ids=set())

    assert result[0]["relationship"] == "SECTOR_WIDE"


def test_unmeasured_company_is_exposure_only_with_no_number(db_session):
    peak = _company("PEAK.NS")
    unmeasured = _company("NODATA.NS")
    db_session.add_all([peak, unmeasured])
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, peak.id))
    db_session.add(_alert_company(alert.id, unmeasured.id))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=peak.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-4.0, sector_move_pct=-0.5, excess_move_pct=-3.5,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=unmeasured.id, benchmark_ticker="^CNXENERGY",
        measurement_status="no_data", measured_at=utcnow(),
    ))
    db_session.commit()

    result = compute_ripple_companies(db_session, alert, exclude_company_id=peak.id, held_company_ids=set())

    assert result[0]["is_exposure_only"] is True
    assert result[0]["excess_move_pct"] is None
    assert result[0]["intensity"] is None


def test_company_with_no_market_move_row_at_all_is_exposure_only(db_session):
    peak = _company("PEAK.NS")
    never_measured = _company("NEVER.NS")
    db_session.add_all([peak, never_measured])
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, peak.id))
    db_session.add(_alert_company(alert.id, never_measured.id))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=peak.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-4.0, sector_move_pct=-0.5, excess_move_pct=-3.5,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    result = compute_ripple_companies(db_session, alert, exclude_company_id=peak.id, held_company_ids=set())

    assert result[0]["is_exposure_only"] is True


def test_sorted_by_intensity_descending_exposure_only_sorts_last(db_session):
    peak = _company("PEAK.NS")
    small = _company("SMALL.NS")
    big = _company("BIG.NS")
    unmeasured = _company("UNMEASURED.NS")
    db_session.add_all([peak, small, big, unmeasured])
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    for c in (peak, small, big, unmeasured):
        db_session.add(_alert_company(alert.id, c.id))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=peak.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-4.0, sector_move_pct=-0.5, excess_move_pct=-3.5,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=small.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=0.5, sector_move_pct=0.3, excess_move_pct=0.2,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=big.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=3.0, sector_move_pct=0.3, excess_move_pct=2.7,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=unmeasured.id, benchmark_ticker="^CNXENERGY",
        measurement_status="no_data", measured_at=utcnow(),
    ))
    db_session.commit()

    result = compute_ripple_companies(db_session, alert, exclude_company_id=peak.id, held_company_ids=set())

    tickers_in_order = [r["ticker"] for r in result]
    assert tickers_in_order[-1] == "UNMEASURED.NS"
    assert tickers_in_order.index("BIG.NS") < tickers_in_order.index("SMALL.NS")


def test_in_my_holdings_reflects_held_company_ids(db_session):
    peak = _company("PEAK.NS")
    held = _company("HELD.NS")
    db_session.add_all([peak, held])
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, peak.id))
    db_session.add(_alert_company(alert.id, held.id))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=peak.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-4.0, sector_move_pct=-0.5, excess_move_pct=-3.5,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=held.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=1.0, sector_move_pct=0.2, excess_move_pct=0.8,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    result = compute_ripple_companies(
        db_session, alert, exclude_company_id=peak.id, held_company_ids={held.id},
    )

    assert result[0]["in_my_holdings"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_ripple.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.market.ripple'`.

- [ ] **Step 3: Implement**

Create `backend/app/market/ripple.py`:

```python
"""Level 2 ripple data: every OTHER measured/exposed company tied to an
alert (excluding the event's own peak, already shown at Level 0/1), grouped
by relationship type (docs/NEWS_IMPACT_APP_SPEC.md §2 Level 2, §3.1
RippleLink). A company with no real measured move renders as a flagged
EXPOSURE, never a fabricated impact number (spec: "ripple companies that
have not moved... show it as a flagged relationship with no number and no
score -- never a fabricated magnitude").
"""
from sqlalchemy.orm import Session

from app.market.alert_measurement import _intensity_for_company_move
from app.market.breadth import compute_breadth_score
from app.models import Alert, ImpactEdge, MarketMove
from app.reasoning.ripple_relationship import is_exposure_only, relation_to_ripple_relationship


def compute_ripple_companies(
    session: Session, alert: Alert, exclude_company_id: int, held_company_ids: set[int],
) -> list[dict]:
    """Returns one entry per AlertCompany on this alert OTHER than
    exclude_company_id (the event's peak, already shown at Level 0/1),
    each: {ticker, name, relationship, direction, excess_move_pct
    (float|None), intensity (dict|None), is_exposure_only (bool),
    in_my_holdings (bool)}. excess_move_pct/intensity are None whenever
    is_exposure_only is True -- never a fabricated number for an
    unmeasured company. Sorted by intensity score descending;
    exposure-only entries (no score) sort last.
    """
    moves_by_company_id = {
        m.company_id: m for m in session.query(MarketMove).filter_by(alert_id=alert.id).all()
    }
    ok_excess_values = [m.excess_move_pct for m in moves_by_company_id.values() if m.measurement_status == "ok"]
    breadth_score = compute_breadth_score(ok_excess_values)

    edges = session.query(ImpactEdge).filter_by(alert_id=alert.id).all()
    relation_by_company_id: dict[int, str] = {}
    for edge in edges:
        for company_id in (edge.to_company_id, edge.from_company_id):
            if company_id is not None and company_id not in relation_by_company_id:
                relation_by_company_id[company_id] = edge.relation

    results = []
    for alert_company in alert.companies:
        if alert_company.company_id == exclude_company_id:
            continue
        company = alert_company.company
        move = moves_by_company_id.get(alert_company.company_id)
        status = move.measurement_status if move else None
        exposure_only = is_exposure_only(status)
        relationship = relation_to_ripple_relationship(relation_by_company_id.get(alert_company.company_id, ""))

        entry = {
            "ticker": company.ticker,
            "name": company.name,
            "relationship": relationship,
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_ripple.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/market/ripple.py backend/tests/test_ripple.py
git commit -m "feat: add compute_ripple_companies -- Level 2 ripple grouped by relationship, exposure-only when unmeasured"
```

---

## Task 3: `get_timeline_entries` — Level 3 data

**Files:**
- Create: `backend/app/market/timeline_entries.py`
- Test: `backend/tests/test_timeline_entries.py`

**Interfaces:**
- Consumes: `app.models.Alert`/`TimelineEffect`.
- Produces: `get_timeline_entries(session, alert) -> list[dict]`, each `{"horizon", "description"}`, ordered `TODAY < DAYS < WEEKS < MONTHS < QUARTERS`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_timeline_entries.py`:

```python
from app.market.timeline_entries import get_timeline_entries
from app.models import Alert, Article, TimelineEffect


def _article(db_session):
    article = Article(source="test", url="https://example.com/timeline", title="t", content="c")
    db_session.add(article)
    db_session.commit()
    return article


def test_returns_entries_in_horizon_order_regardless_of_insertion_order(db_session):
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(TimelineEffect(alert_id=alert.id, horizon="QUARTERS", description="Long-term effect."))
    db_session.add(TimelineEffect(alert_id=alert.id, horizon="TODAY", description="Immediate effect."))
    db_session.add(TimelineEffect(alert_id=alert.id, horizon="WEEKS", description="Weeks-long effect."))
    db_session.commit()

    result = get_timeline_entries(db_session, alert)

    assert [e["horizon"] for e in result] == ["TODAY", "WEEKS", "QUARTERS"]
    assert result[0]["description"] == "Immediate effect."


def test_returns_empty_list_when_no_timeline_effects_exist(db_session):
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.commit()

    assert get_timeline_entries(db_session, alert) == []


def test_only_returns_entries_for_this_alert(db_session):
    article1 = _article(db_session)
    alert1 = Alert(article_id=article1.id, category="oil_gas")
    db_session.add(alert1)
    db_session.flush()
    db_session.add(TimelineEffect(alert_id=alert1.id, horizon="TODAY", description="Alert 1 effect."))

    article2 = Article(source="test", url="https://example.com/timeline2", title="t2", content="c2")
    db_session.add(article2)
    db_session.commit()
    alert2 = Alert(article_id=article2.id, category="oil_gas")
    db_session.add(alert2)
    db_session.flush()
    db_session.add(TimelineEffect(alert_id=alert2.id, horizon="TODAY", description="Alert 2 effect."))
    db_session.commit()

    result = get_timeline_entries(db_session, alert1)

    assert len(result) == 1
    assert result[0]["description"] == "Alert 1 effect."
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_timeline_entries.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.market.timeline_entries'`.

- [ ] **Step 3: Implement**

Create `backend/app/market/timeline_entries.py`:

```python
"""Level 3 timeline data: every TimelineEffect row for an alert, in a
fixed horizon order (docs/NEWS_IMPACT_APP_SPEC.md §2 Level 3, §3.1). Only
horizons the LLM refinement layer found genuine content for exist as rows
at all (see app.analysis.refinement.generate_timeline_effects) -- nothing
here decides whether a horizon "has content", it only orders what already
exists.
"""
from sqlalchemy.orm import Session

from app.models import Alert, TimelineEffect

HORIZON_ORDER = ["TODAY", "DAYS", "WEEKS", "MONTHS", "QUARTERS"]


def get_timeline_entries(session: Session, alert: Alert) -> list[dict]:
    rows = session.query(TimelineEffect).filter_by(alert_id=alert.id).all()
    rows.sort(key=lambda r: HORIZON_ORDER.index(r.horizon) if r.horizon in HORIZON_ORDER else len(HORIZON_ORDER))
    return [{"horizon": r.horizon, "description": r.description} for r in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_timeline_entries.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/market/timeline_entries.py backend/tests/test_timeline_entries.py
git commit -m "feat: add get_timeline_entries -- Level 3 timeline, ordered by horizon"
```

---

## Task 4: Wire ripple + timeline into the detail endpoint

**Files:**
- Modify: `backend/app/routers/feed_v2.py`
- Modify: `backend/tests/test_feed_v2_router.py`

**Interfaces:**
- Consumes: `compute_ripple_companies` (Task 2), `get_timeline_entries` (Task 3).
- Produces: `GET /api/feed-v2/{alert_id}` response gains `ripple: list[dict]` and `timeline: list[dict]` keys. `GET /api/feed-v2` (list) is UNCHANGED — no new keys.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_feed_v2_router.py` (reuse the file's existing `_override_db`/`_measured_alert` helpers):

```python
def test_get_feed_v2_alert_includes_ripple_and_timeline(db_session):
    _override_db(db_session)
    alert = _measured_alert(db_session)  # single-company alert -- peak only, no ripple companions
    client = TestClient(app)

    response = client.get(f"/api/feed-v2/{alert.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["ripple"] == []
    assert body["timeline"] == []
    app.dependency_overrides.clear()


def test_list_feed_v2_does_not_include_ripple_or_timeline(db_session):
    _override_db(db_session)
    _measured_alert(db_session)
    client = TestClient(app)

    response = client.get("/api/feed-v2")

    assert response.status_code == 200
    body = response.json()
    assert "ripple" not in body[0]
    assert "timeline" not in body[0]
    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_feed_v2_router.py -v -k "ripple_and_timeline or does_not_include"`
Expected: FAIL — `KeyError: 'ripple'` (the detail test) — the second test may already pass trivially since the field doesn't exist yet, confirm it does once the feature ships that it's STILL true for the list endpoint.

- [ ] **Step 3: Implement**

In `backend/app/routers/feed_v2.py`, change the import line:

```python
from app.market.alert_measurement import compute_alert_measurement
```

to:

```python
from app.market.alert_measurement import compute_alert_measurement
from app.market.ripple import compute_ripple_companies
from app.market.timeline_entries import get_timeline_entries
```

Then change `get_feed_v2_alert` (leave `list_feed_v2_alerts` completely untouched) from:

```python
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

to:

```python
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
    result = _serialize(alert, measurement, held_company_ids)
    result["ripple"] = compute_ripple_companies(
        db, alert, exclude_company_id=measurement["peak_company_id"], held_company_ids=held_company_ids,
    )
    result["timeline"] = get_timeline_entries(db, alert)
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_feed_v2_router.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full backend suite to confirm no regressions**

Run: `cd backend && python -m pytest -q`
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/routers/feed_v2.py backend/tests/test_feed_v2_router.py
git commit -m "feat: wire ripple + timeline into GET /api/feed-v2/{alert_id}"
```

---

## Task 5: Extend the demo seed script with ripple companions + timeline

**Files:**
- Modify: `backend/seed_feed_v2_demo.py`

**Context:** Task 9's Playwright screenshots need real ripple/timeline content to show. This adds, for the RELIANCE.NS demo alert only (index 0 of `DEMO_ROWS`): four ripple companion companies (one per relationship-mapping family — `commodity`→BENEFICIARY, `input_cost`→CUSTOMER_INPUT_COST, `competitor`→COMPETITOR, `supplier`→SUPPLIER with no `MarketMove` at all, proving the exposure-only path), plus three `TimelineEffect` rows (skipping `DAYS`/`MONTHS`, proving "only horizons with content render").

- [ ] **Step 1: Add the ripple/timeline demo data structures**

In `backend/seed_feed_v2_demo.py`, add after the existing `DEMO_ROWS` list:

```python
# Ripple companions + timeline, attached to DEMO_ROWS[0] (RELIANCE.NS) only --
# one company per relationship-mapping family (see app.reasoning.
# ripple_relationship._RELATION_TO_RIPPLE_RELATIONSHIP), plus one with NO
# MarketMove row at all to demonstrate the exposure-only path.
RIPPLE_COMPANIONS = [
    # (ticker, name, sector, relation, direction, excess, has_market_move)
    ("BPCL.NS", "Bharat Petroleum Corporation", "oil_gas", "commodity", "bullish", 3.0, True),
    ("IOC.NS", "Indian Oil Corporation", "oil_gas", "input_cost", "bearish", -1.5, True),
    ("HPCL.NS", "Hindustan Petroleum Corporation", "oil_gas", "competitor", "bearish", -0.8, True),
    ("GAIL.NS", "GAIL India", "oil_gas", "supplier", "bearish", None, False),
]

TIMELINE_ENTRIES = [
    ("TODAY", "Markets react immediately to the supply disruption."),
    ("WEEKS", "Refining margins stay pressured while crude prices remain elevated."),
    ("QUARTERS", "Refiners may pass costs to consumers if the disruption persists."),
]
```

- [ ] **Step 2: Extend the cleanup loop to also remove ripple companion rows**

The existing cleanup loop deletes `MarketMove`/`AlertCompany` rows by `alert_id` before deleting the `Alert` itself — ripple companions attach to the SAME `alert_id` as `DEMO_ROWS[0]`, so the existing cleanup already covers them (no change needed there). Add `ImpactEdge` and `TimelineEffect` to the existing per-alert cleanup so re-running the script doesn't leave duplicates. Change:

```python
        for article in existing:
            for alert in session.query(Alert).filter_by(article_id=article.id).all():
                session.query(MarketMove).filter_by(alert_id=alert.id).delete()
                session.query(AlertCompany).filter_by(alert_id=alert.id).delete()
                session.delete(alert)
            session.delete(article)
```

to:

```python
        for article in existing:
            for alert in session.query(Alert).filter_by(article_id=article.id).all():
                session.query(MarketMove).filter_by(alert_id=alert.id).delete()
                session.query(AlertCompany).filter_by(alert_id=alert.id).delete()
                session.query(ImpactEdge).filter_by(alert_id=alert.id).delete()
                session.query(TimelineEffect).filter_by(alert_id=alert.id).delete()
                session.delete(alert)
            session.delete(article)
```

And update the import line from:

```python
from app.models import Alert, AlertCompany, Article, Company, MarketMove, utcnow
```

to:

```python
from app.models import Alert, AlertCompany, Article, Company, ImpactEdge, MarketMove, TimelineEffect, utcnow
```

- [ ] **Step 3: Insert the ripple companions + timeline after the main loop, attached to `DEMO_ROWS[0]`'s alert**

The existing `main()` loop creates each `DEMO_ROWS` entry's `alert` inside the `for i, row in enumerate(DEMO_ROWS):` loop. Capture the first alert's id, then after that loop ends, add:

```python
        first_alert_id = None
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
            if i == 0:
                first_alert_id = alert.id

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

        # Ripple companions + timeline, attached to DEMO_ROWS[0] (RELIANCE.NS) only.
        peak_company = session.query(Company).filter_by(ticker=DEMO_ROWS[0][0]).one()
        for ticker, name, sector, relation, direction, excess, has_market_move in RIPPLE_COMPANIONS:
            company = session.query(Company).filter_by(ticker=ticker).one_or_none()
            if company is None:
                company = Company(ticker=ticker, name=name, sector=sector, index_tier="OTHER", market_cap=20000.0)
                session.add(company)
                session.commit()

            session.add(AlertCompany(
                alert_id=first_alert_id, company_id=company.id, direction=direction,
                magnitude_low=0.5, magnitude_high=1.5, rationale=f"Ripple effect via {relation}.",
                basis="direct_mention",
            ))

            if has_market_move:
                session.add(MarketMove(
                    alert_id=first_alert_id, company_id=company.id, benchmark_ticker="^CNXENERGY",
                    raw_move_pct=excess, sector_move_pct=0.0, excess_move_pct=excess,
                    volume=100.0, avg_volume_20d=100.0, volume_multiple=1.0,
                    measurement_status="ok", measured_at=now,
                ))
            else:
                session.add(MarketMove(
                    alert_id=first_alert_id, company_id=company.id, benchmark_ticker="^CNXENERGY",
                    measurement_status="no_data", measured_at=now,
                ))

            session.add(ImpactEdge(
                alert_id=first_alert_id, from_company_id=peak_company.id, from_node_kind="company",
                from_label=peak_company.ticker, to_company_id=company.id, to_node_kind="company",
                to_label=company.ticker, relation=relation, direction=direction,
                note=f"Demo ripple edge ({relation}).", source="llm_only",
            ))
            session.commit()

        for horizon, description in TIMELINE_ENTRIES:
            session.add(TimelineEffect(alert_id=first_alert_id, horizon=horizon, description=description))
        session.commit()

        print(f"Seeded {len(DEMO_ROWS)} demo feed-v2 alerts, {len(RIPPLE_COMPANIONS)} ripple companions, {len(TIMELINE_ENTRIES)} timeline entries.")
```

Replace the entire body of `main()`'s `try:` block (from `existing = session.query(...)` through the old `print(...)` line) with the updated cleanup loop (Step 2) followed by this new loop+companions+timeline code, keeping the production guard (`if not settings.database_url...`) and `init_db()`/`session = SessionLocal()` at the top and the `finally: session.close()` at the bottom exactly as they are today.

- [ ] **Step 4: Run it against the local dev DB**

Run: `cd backend && python seed_feed_v2_demo.py`
Expected: prints `Seeded 4 demo feed-v2 alerts, 4 ripple companions, 3 timeline entries.` with no error.

- [ ] **Step 5: Spot-check via the API**

Start a background `uvicorn` (check port availability first, per the established pattern from prior phases), then:
`curl http://127.0.0.1:8000/api/feed-v2/<RELIANCE alert id>` and confirm the response's `ripple` array has 4 entries (one per relationship family, one with `is_exposure_only: true` and `excess_move_pct: null`) and `timeline` has 3 entries in `TODAY, WEEKS, QUARTERS` order. Stop the background server by its specific PID afterward.

- [ ] **Step 6: Commit**

```bash
git add backend/seed_feed_v2_demo.py
git commit -m "feat: extend demo seed script with ripple companions and timeline entries"
```

---

## Task 6: Frontend types + `relationshipLabel`

**Files:**
- Modify: `frontend/src/lib/feedV2Api.ts`
- Modify: `frontend/src/lib/feedV2Format.ts`

**Interfaces:**
- Produces: `RippleRelationship`, `RippleCompany`, `TimelineHorizon`, `TimelineEntry` types; `FeedV2Alert` gains optional `ripple?: RippleCompany[]` and `timeline?: TimelineEntry[]`; `relationshipLabel(relationship: RippleRelationship) -> string`.

- [ ] **Step 1: Add the new types to `feedV2Api.ts`**

In `frontend/src/lib/feedV2Api.ts`, add after the existing `Verdict` type declaration:

```ts
export type RippleRelationship =
  | 'BENEFICIARY'
  | 'CUSTOMER_INPUT_COST'
  | 'SUPPLIER'
  | 'SUBSTITUTE'
  | 'COMPETITOR'
  | 'SECTOR_WIDE';

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

export type TimelineHorizon = 'TODAY' | 'DAYS' | 'WEEKS' | 'MONTHS' | 'QUARTERS';

export interface TimelineEntry {
  horizon: TimelineHorizon;
  description: string;
}
```

Then add two new optional fields to the existing `FeedV2Alert` interface, directly after `in_my_holdings: boolean;`:

```ts
  ripple?: RippleCompany[];
  timeline?: TimelineEntry[];
```

- [ ] **Step 2: Add `relationshipLabel` to `feedV2Format.ts`**

In `frontend/src/lib/feedV2Format.ts`, add:

```ts
import type { RippleRelationship } from './feedV2Api';
```

to the top import (combine with the existing `Verdict` import from the same module: `import type { RippleRelationship, Verdict } from './feedV2Api';`), then add after `verdictLabel`:

```ts
const RELATIONSHIP_LABELS: Record<RippleRelationship, string> = {
  BENEFICIARY: 'Beneficiary',
  CUSTOMER_INPUT_COST: 'Customer / input cost',
  SUPPLIER: 'Supplier',
  SUBSTITUTE: 'Substitute',
  COMPETITOR: 'Competitor',
  SECTOR_WIDE: 'Sector wide',
};

export function relationshipLabel(relationship: RippleRelationship): string {
  return RELATIONSHIP_LABELS[relationship];
}
```

- [ ] **Step 3: Verify the frontend builds cleanly**

Run: `cd frontend && npm run build`
Expected: succeeds — `tsc --noEmit` passes (the new optional fields don't break any existing `FeedV2Alert` literal in tests, since they're optional).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/feedV2Api.ts frontend/src/lib/feedV2Format.ts
git commit -m "feat: add RippleCompany/TimelineEntry types and relationshipLabel helper"
```

---

## Task 7: `RippleSection` — Level 2 component

**Files:**
- Create: `frontend/src/components/feed-v2/RippleSection.tsx`
- Test: `frontend/src/components/feed-v2/RippleSection.test.tsx`

**Interfaces:**
- Consumes: `RippleCompany`/`RippleRelationship` (Task 6), `formatExcess`/`intensityBandColorClass`/`relationshipLabel` (Task 6).
- Produces: `<RippleSection companies={RippleCompany[]} />`.

**Layout (per spec §9 and the task brief's Phase 6 layout section):** group by `relationship`, in a fixed order (`BENEFICIARY, CUSTOMER_INPUT_COST, SUPPLIER, SUBSTITUTE, COMPETITOR, SECTOR_WIDE` — only groups with ≥1 company render); each group: `border-left: 2px` accent in the MAJORITY direction color (bullish if bullish-count ≥ bearish-count, else bearish — this plan's documented tie-break), `border-radius: 0`, an 11px uppercase-tracked label with the count; then rows (already pre-sorted by the backend) as `[TICKER] [excess%] [intensity bar] [owned dot]` — an exposure-only row shows `[TICKER] [Exposure] [owned dot]` instead (no number, no bar, per compliance).

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/feed-v2/RippleSection.test.tsx`:

```tsx
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import RippleSection from './RippleSection';
import type { RippleCompany } from '../../lib/feedV2Api';

function makeCompany(overrides: Partial<RippleCompany> = {}): RippleCompany {
  return {
    ticker: 'BPCL.NS',
    name: 'Bharat Petroleum',
    relationship: 'BENEFICIARY',
    direction: 'bullish',
    excess_move_pct: 3.0,
    intensity: { score: 70, band: 'Moderate', components: [] },
    is_exposure_only: false,
    in_my_holdings: false,
    ...overrides,
  };
}

describe('RippleSection', () => {
  it('renders nothing when there are no companies', () => {
    const { container } = render(<RippleSection companies={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('groups companies by relationship with a count label', () => {
    render(
      <RippleSection
        companies={[
          makeCompany({ ticker: 'A.NS', relationship: 'BENEFICIARY' }),
          makeCompany({ ticker: 'B.NS', relationship: 'BENEFICIARY' }),
          makeCompany({ ticker: 'C.NS', relationship: 'COMPETITOR' }),
        ]}
      />,
    );
    expect(screen.getByText('Beneficiary (2)')).toBeInTheDocument();
    expect(screen.getByText('Competitor (1)')).toBeInTheDocument();
  });

  it('renders ticker, excess, and intensity bar for a measured company', () => {
    render(<RippleSection companies={[makeCompany({ ticker: 'BPCL.NS', excess_move_pct: 3.0 })]} />);
    expect(screen.getByText('BPCL.NS')).toBeInTheDocument();
    expect(screen.getByText(/3\.0%/)).toBeInTheDocument();
  });

  it('renders an Exposure label with no number for an exposure-only company', () => {
    render(
      <RippleSection
        companies={[
          makeCompany({
            ticker: 'GAIL.NS', is_exposure_only: true, excess_move_pct: null, intensity: null,
          }),
        ]}
      />,
    );
    expect(screen.getByText('GAIL.NS')).toBeInTheDocument();
    expect(screen.getByText('Exposure')).toBeInTheDocument();
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });

  it('renders an owned dot only when in_my_holdings is true', () => {
    const { rerender, container } = render(
      <RippleSection companies={[makeCompany({ in_my_holdings: false })]} />,
    );
    expect(container.querySelector('[data-testid="ripple-owned-dot"]')).not.toBeInTheDocument();

    rerender(<RippleSection companies={[makeCompany({ in_my_holdings: true })]} />);
    expect(container.querySelector('[data-testid="ripple-owned-dot"]')).toBeInTheDocument();
  });

  it('omits a relationship group entirely when it has no companies', () => {
    render(<RippleSection companies={[makeCompany({ relationship: 'BENEFICIARY' })]} />);
    expect(screen.queryByText(/Substitute/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Sector wide/)).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/feed-v2/RippleSection.test.tsx`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement**

Create `frontend/src/components/feed-v2/RippleSection.tsx`:

```tsx
import { formatExcess, intensityBandColorClass, relationshipLabel } from '../../lib/feedV2Format';
import type { RippleCompany, RippleRelationship } from '../../lib/feedV2Api';

interface RippleSectionProps {
  companies: RippleCompany[];
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

export default function RippleSection({ companies }: RippleSectionProps) {
  if (companies.length === 0) return null;

  const groups = GROUP_ORDER.map((relationship) => ({
    relationship,
    rows: companies.filter((c) => c.relationship === relationship),
  })).filter((g) => g.rows.length > 0);

  return (
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
            <div className="mt-2 flex flex-col gap-2">
              {group.rows.map((row) => (
                <div key={row.ticker} className="flex items-center gap-3">
                  <span className="font-data text-[11px] text-muted">{row.ticker}</span>
                  {row.is_exposure_only ? (
                    <span className="font-sans text-xs text-muted">Exposure</span>
                  ) : (
                    <>
                      <span
                        className={`font-data text-xs ${
                          row.direction === 'bullish' ? 'text-bullish' : 'text-bearish'
                        }`}
                      >
                        {formatExcess(row.excess_move_pct as number).text}
                      </span>
                      {row.intensity && (
                        <span className="h-1 w-full max-w-[80px] rounded-sm bg-elevated">
                          <span
                            className={`block h-full rounded-sm ${intensityBandColorClass(row.intensity.band)}`}
                            style={{ width: `${row.intensity.score}%` }}
                          />
                        </span>
                      )}
                    </>
                  )}
                  {row.in_my_holdings && (
                    <span
                      data-testid="ripple-owned-dot"
                      className="h-[7px] w-[7px] shrink-0 rounded-full bg-accent"
                    />
                  )}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/feed-v2/RippleSection.test.tsx`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/feed-v2/RippleSection.tsx frontend/src/components/feed-v2/RippleSection.test.tsx
git commit -m "feat: add RippleSection -- Level 2 ripple grouped by relationship type"
```

---

## Task 8: `TimelineSection` — Level 3 component

**Files:**
- Create: `frontend/src/components/feed-v2/TimelineSection.tsx`
- Test: `frontend/src/components/feed-v2/TimelineSection.test.tsx`

**Interfaces:**
- Consumes: `TimelineEntry` (Task 6).
- Produces: `<TimelineSection entries={TimelineEntry[]} />`.

**Layout:** vertical rail (a `border-l` line), one dot per entry, horizon label (11px tracked uppercase) above a 13px description. Only entries present render (guaranteed by the backend already only returning horizons with content).

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/feed-v2/TimelineSection.test.tsx`:

```tsx
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import TimelineSection from './TimelineSection';
import type { TimelineEntry } from '../../lib/feedV2Api';

describe('TimelineSection', () => {
  it('renders nothing when there are no entries', () => {
    const { container } = render(<TimelineSection entries={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders one row per entry with horizon label and description', () => {
    const entries: TimelineEntry[] = [
      { horizon: 'TODAY', description: 'Markets react immediately.' },
      { horizon: 'WEEKS', description: 'Effects persist for weeks.' },
    ];
    render(<TimelineSection entries={entries} />);
    expect(screen.getByText('Today')).toBeInTheDocument();
    expect(screen.getByText('Markets react immediately.')).toBeInTheDocument();
    expect(screen.getByText('Next few weeks')).toBeInTheDocument();
    expect(screen.getByText('Effects persist for weeks.')).toBeInTheDocument();
  });

  it('only renders horizons that are present, in the order given', () => {
    const entries: TimelineEntry[] = [
      { horizon: 'TODAY', description: 'Today effect.' },
      { horizon: 'QUARTERS', description: 'Quarters effect.' },
    ];
    render(<TimelineSection entries={entries} />);
    expect(screen.queryByText('Next few days')).not.toBeInTheDocument();
    expect(screen.queryByText('Next few months')).not.toBeInTheDocument();
    expect(screen.getByText('Next few quarters')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/feed-v2/TimelineSection.test.tsx`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement**

Create `frontend/src/components/feed-v2/TimelineSection.tsx`:

```tsx
import type { TimelineEntry } from '../../lib/feedV2Api';

interface TimelineSectionProps {
  entries: TimelineEntry[];
}

const HORIZON_LABELS: Record<string, string> = {
  TODAY: 'Today',
  DAYS: 'Next few days',
  WEEKS: 'Next few weeks',
  MONTHS: 'Next few months',
  QUARTERS: 'Next few quarters',
};

export default function TimelineSection({ entries }: TimelineSectionProps) {
  if (entries.length === 0) return null;

  return (
    <div className="rounded-lg bg-surface p-5">
      <div className="flex flex-col gap-4 border-l-2 border-hairline pl-4">
        {entries.map((entry) => (
          <div key={entry.horizon} className="relative">
            <span className="absolute -left-[21px] top-1 h-2 w-2 rounded-full bg-accent" />
            <div className="font-sans text-[11px] uppercase tracking-widest text-muted">
              {HORIZON_LABELS[entry.horizon] ?? entry.horizon}
            </div>
            <p className="mt-1 font-sans text-[13px] text-ink">{entry.description}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/feed-v2/TimelineSection.test.tsx`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/feed-v2/TimelineSection.tsx frontend/src/components/feed-v2/TimelineSection.test.tsx
git commit -m "feat: add TimelineSection -- Level 3 vertical rail, only horizons with content"
```

---

## Task 9: Wire both sections into `Level1SummaryV2`

**Files:**
- Modify: `frontend/src/components/feed-v2/Level1SummaryV2.tsx`
- Modify: `frontend/src/components/feed-v2/Level1SummaryV2.test.tsx`

**Interfaces:**
- Consumes: `RippleSection` (Task 7), `TimelineSection` (Task 8).

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/components/feed-v2/Level1SummaryV2.test.tsx` (reuse the existing `makeAlert` factory):

```tsx
it('renders the ripple section when ripple data is present', () => {
  render(
    <Level1SummaryV2
      alert={makeAlert({
        ripple: [
          {
            ticker: 'BPCL.NS', name: 'Bharat Petroleum', relationship: 'BENEFICIARY',
            direction: 'bullish', excess_move_pct: 3.0,
            intensity: { score: 70, band: 'Moderate', components: [] },
            is_exposure_only: false, in_my_holdings: false,
          },
        ],
      })}
    />,
  );
  expect(screen.getByText('BPCL.NS')).toBeInTheDocument();
});

it('renders the timeline section when timeline data is present', () => {
  render(
    <Level1SummaryV2
      alert={makeAlert({
        timeline: [{ horizon: 'TODAY', description: 'Markets react immediately.' }],
      })}
    />,
  );
  expect(screen.getByText('Markets react immediately.')).toBeInTheDocument();
});

it('renders neither section when ripple/timeline are absent (list-fetch shape)', () => {
  render(<Level1SummaryV2 alert={makeAlert({ ripple: undefined, timeline: undefined })} />);
  expect(screen.queryByText('Exposure')).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/feed-v2/Level1SummaryV2.test.tsx`
Expected: FAIL — `ripple`/`timeline` content never renders (props aren't consumed yet).

- [ ] **Step 3: Implement**

In `frontend/src/components/feed-v2/Level1SummaryV2.tsx`, add the imports:

```tsx
import RippleSection from './RippleSection';
import TimelineSection from './TimelineSection';
```

Then add, directly before the closing `</div>` of the component's returned top-level `<div className="flex flex-col gap-3">`:

```tsx
      {alert.ripple && <RippleSection companies={alert.ripple} />}
      {alert.timeline && <TimelineSection entries={alert.timeline} />}
```

(`RippleSection`/`TimelineSection` each already return `null` for an empty array, so this guard only needs to handle the `undefined` case — a genuinely empty array is still truthy in JavaScript and safely delegates to each component's own empty-check.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/components/feed-v2/Level1SummaryV2.test.tsx`
Expected: all PASS (Phase 4/5's original tests plus these 3 new ones).

- [ ] **Step 5: Run the full frontend suite to confirm no regressions**

Run: `cd frontend && npm test`
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/feed-v2/Level1SummaryV2.tsx frontend/src/components/feed-v2/Level1SummaryV2.test.tsx
git commit -m "feat: render RippleSection and TimelineSection in Level1SummaryV2 when present"
```

---

## Task 10: Playwright screenshot verification (HARD RULE, extending Phase 4/5's spec)

**Files:**
- Modify: `frontend/e2e/feed-v2-screenshots.spec.ts`

**Context:** Playwright is already installed and configured. This task doesn't add new test CASES — the existing `Level 1` screenshot case already opens the detail modal, which will now naturally include the ripple/timeline sections once the demo data (Task 5) provides them for the RELIANCE.NS alert. This task's job is to make sure the EXISTING Level 1 screenshots are re-captured with the new content and actually reviewed — the HARD RULE applies to new UI content appearing in an existing screenshot just as much as to a brand-new screenshot case.

- [ ] **Step 1: Confirm the existing Level 1 case opens the RELIANCE.NS alert**

Read `frontend/e2e/feed-v2-screenshots.spec.ts`'s `Level 1` test case — confirm it clicks the first row (`page.locator('[role="button"]').first()`), which per the demo seed data (Task 5) is RELIANCE.NS (index 0, most recent `created_at`) — the alert with ripple companions and timeline entries attached. No code change needed if this is already true; if the existing case targets a different alert, adjust the locator to target RELIANCE.NS specifically (e.g. by finding the row containing its ticker) and note this change.

- [ ] **Step 2: Seed data and start both servers**

Run (mirroring the established process from Phases 4/5):
```bash
cd backend && python seed_feed_v2_demo.py
cd backend && uvicorn app.main:app --port 8000 &
cd frontend && npm run dev &
```
Check port availability first (prior phases repeatedly hit other parallel sessions occupying 8000/5173) — use alternate ports + temporary config repointing if needed, reverting to committed values before any commit, exactly as in Phases 4/5.

- [ ] **Step 3: Run the screenshot spec**

Run: `cd frontend && npx playwright test`
Expected: all existing screenshots regenerate successfully (12 from Phases 4-5), with the 4 `feed-v2-level1-*` files now showing the ripple/timeline sections since the demo data now populates them.

- [ ] **Step 4: Look at the 4 `feed-v2-level1-*` screenshots — THE ACTUAL VERIFICATION STEP**

Open each with the Read tool and check:
- The existing summary/metric-tile/source sections are unchanged in position/appearance from Phase 5.
- Below them: a ripple section with visible group headers (e.g. "Beneficiary (1)", "Customer / input cost (1)", "Competitor (1)", "Supplier (1)") each with a colored left border, and one row per company showing ticker + excess%/bar (or "Exposure" for GAIL.NS with no bar/number).
- Below that: a timeline section with 3 entries (Today/Next few weeks/Next few quarters), each with a dot, a label, and the description text, and NO entries for "Next few days"/"Next few months" (proving the "only horizons with content" rule).
- Both themes legible, no clipped/overlapping text, group border colors visually distinguishable from the page background in both themes.

Write down every concrete discrepancy found. Fix it in `RippleSection.tsx`/`TimelineSection.tsx`/`Level1SummaryV2.tsx`/`index.css` as appropriate. Re-run Step 3 and re-check. Repeat until clean.

- [ ] **Step 5: Stop the background servers**

Kill the specific PIDs — never a broad process-kill.

- [ ] **Step 6: Run both full test suites one more time**

Run: `cd backend && python -m pytest -q` and `cd frontend && npm test` — confirm zero regressions from any Step 4 fixes.

- [ ] **Step 7: Commit**

If Step 1 required a locator change, commit that. If Step 4's review found and fixed anything, commit that separately, describing exactly what the screenshot review caught and corrected. If nothing needed changing, no commit is needed for this task beyond what's already landed.

---

## Task 11: Full-suite regression check

- [ ] **Step 1: Run the entire backend test suite**

Run: `cd backend && python -m pytest -q`
Expected: all tests PASS.

- [ ] **Step 2: Run the entire frontend test suite**

Run: `cd frontend && npm test`
Expected: all tests PASS.

- [ ] **Step 3: Commit (only if Steps 1-2 required a fix)**

If clean, nothing to commit here.

---

## PHASE 6 STOP — required report

Report:
1. Full-suite pass/fail status, both backend and frontend.
2. All 4 re-captured Level 1 screenshots' final state — confirm each was actually opened and looked at, and list every concrete difference found during Task 10's review and how it was fixed (or "clean on first pass").
3. **Flag for confirmation:** both interpretive calls from Global Constraints — (a) ripple/timeline as additional sections within the same Level 1 view rather than separate tap-through screens, (b) a ripple group's border color following majority direction. Confirm these readings are acceptable before Phase 7 (Level 4 deep-dive) builds its own navigation/discovery patterns on top.
4. Confirm the exposure-only path never renders a number: re-check the GAIL.NS row in the reviewed screenshots specifically.

This plan ends here. Phase 7 (Level 4 stock deep-dive + discovery directory) is a separate plan, written after this one ships and the report above is reviewed.
