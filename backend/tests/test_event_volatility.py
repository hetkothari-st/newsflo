"""Subsystem D: per-(stock, category) reaction ranges from measured moves.

Spec: docs/superpowers/specs/2026-08-05-event-volatility-ranges-design.md.
The tests that matter most are the withholding ones -- below threshold,
wrong level, missing category must all yield nothing rather than a number.
"""
from datetime import date
from itertools import count

import pytest

from app import config
from app.market import event_volatility as ev
from app.models import Company, EventVolatilityRange, MarketMove

AS_OF = date(2026, 8, 5)


@pytest.fixture
def make_company(db_session):
    """No such fixture exists in conftest.py -- local factory following the
    Company-construction pattern used elsewhere (e.g. test_market_move_wiring.py)."""
    def _make(ticker, sector="other", name=None, index_tier="OTHER",
              market="INDIA", tradeability="NORMAL"):
        company = Company(
            ticker=ticker, name=name or ticker, sector=sector, index_tier=index_tier,
            market=market, tradeability=tradeability,
        )
        db_session.add(company)
        db_session.flush()
        return company
    return _make


def test_event_volatility_range_table_exists(db_session):
    row = EventVolatilityRange(
        level="COMPANY", company_id=1, sector=None, category="pharma",
        n_events=3, min_excess_move_pct=-1.8, median_excess_move_pct=0.6,
        max_excess_move_pct=2.4, as_of=AS_OF, source="market_moves",
    )
    db_session.add(row)
    db_session.commit()
    got = db_session.query(EventVolatilityRange).one()
    assert got.level == "COMPANY"
    assert got.source == "market_moves"


def test_market_move_carries_its_alert_category(db_session):
    """Copied at measurement time -- alerts get recategorized later, and a
    live join would silently re-shuffle historical ranges (same hazard
    calibration_samples.category already documents). Round-trip a real
    value through the table rather than just checking the column exists."""
    move = MarketMove(
        alert_id=1, company_id=1, benchmark_ticker="^CNXPHARMA",
        excess_move_pct=1.5, category="pharma", measurement_status="ok",
    )
    db_session.add(move)
    db_session.flush()
    db_session.expire(move)
    got = db_session.query(MarketMove).one()
    assert got.category == "pharma"


def test_thresholds_live_in_config_not_code():
    assert config.EVENT_VOL_COMPANY_MIN_EVENTS == 3
    assert config.EVENT_VOL_SECTOR_MIN_EVENTS == 5


_fact_alert_id_seq = count(1)


def _fact(company_id=1, sector="pharma", category="pharma", move=1.0, alert_id=None):
    """alert_id defaults to a fresh value per call -- most tests build one
    fact per (implicit) event, so the default keeps them reading the same
    as before this parameter existed. Pass alert_id explicitly to model
    several measurements sharing one event (one alert resolving multiple
    same-sector companies)."""
    if alert_id is None:
        alert_id = next(_fact_alert_id_seq)
    return ev.MoveFact(company_id=company_id, sector=sector, category=category,
                       excess_move_pct=move, alert_id=alert_id)


# --- compute_ranges: grouping and thresholds --------------------------------

def test_company_row_needs_three_events():
    facts = [_fact(move=m) for m in (-1.8, 0.6, 2.4)]
    rows = ev.compute_ranges(facts)
    company = [r for r in rows if r["level"] == "COMPANY"]
    assert len(company) == 1
    assert company[0] == {
        "level": "COMPANY", "company_id": 1, "sector": None,
        "category": "pharma", "n_events": 3,
        "min_excess_move_pct": -1.8, "median_excess_move_pct": 0.6,
        "max_excess_move_pct": 2.4,
    }


def test_two_events_earn_no_company_row():
    assert not [r for r in ev.compute_ranges([_fact(), _fact(move=2.0)])
                if r["level"] == "COMPANY"]


def test_sector_pool_needs_five_events_and_includes_company_row_earners():
    """The sector row describes the sector, not 'the leftovers' -- company
    1's three measurements count toward the pharma pool too. Each fact
    below is a DISTINCT event (alert_id 1-5) -- n_events counts events, not
    measurement rows, so this must stay five events to earn the row."""
    facts = [_fact(company_id=1, alert_id=1, move=-1.8),
             _fact(company_id=1, alert_id=2, move=0.6),
             _fact(company_id=1, alert_id=3, move=2.4)]
    facts += [_fact(company_id=2, alert_id=4, move=-4.0),
              _fact(company_id=2, alert_id=5, move=5.0)]
    rows = ev.compute_ranges(facts)
    sector = [r for r in rows if r["level"] == "SECTOR"]
    assert len(sector) == 1
    assert sector[0]["n_events"] == 5
    assert sector[0]["company_id"] is None
    assert sector[0]["sector"] == "pharma"
    assert sector[0]["min_excess_move_pct"] == -4.0
    assert sector[0]["max_excess_move_pct"] == 5.0
    assert sector[0]["median_excess_move_pct"] == 0.6


def test_one_shared_alert_across_five_companies_earns_no_sector_row():
    """n_events counts DISTINCT alerts, not measurements: one broad alert
    that resolves 5 same-sector companies is a single day's cross-sectional
    spread, not 5 independent observations of how this category behaves --
    it must not alone clear EVENT_VOL_SECTOR_MIN_EVENTS."""
    facts = [_fact(company_id=i, alert_id=1, move=float(i)) for i in range(1, 6)]
    assert not [r for r in ev.compute_ranges(facts) if r["level"] == "SECTOR"]


def test_mixed_alerts_n_events_counts_distinct_alerts_not_measurements():
    """6 measurements from 5 distinct alerts (alert 1 resolves both company
    1 and company 2) must report n_events=5, not 6."""
    facts = [
        _fact(company_id=1, alert_id=1, move=1.0),
        _fact(company_id=2, alert_id=1, move=2.0),
        _fact(company_id=3, alert_id=2, move=3.0),
        _fact(company_id=4, alert_id=3, move=4.0),
        _fact(company_id=5, alert_id=4, move=5.0),
        _fact(company_id=6, alert_id=5, move=6.0),
    ]
    sector = [r for r in ev.compute_ranges(facts) if r["level"] == "SECTOR"]
    assert len(sector) == 1
    assert sector[0]["n_events"] == 5


def test_four_sector_events_earn_no_sector_row():
    facts = [_fact(company_id=i, move=float(i)) for i in range(1, 5)]
    assert not [r for r in ev.compute_ranges(facts) if r["level"] == "SECTOR"]


def test_other_sector_pools_nothing_but_company_rows_survive():
    """'other' is an absence of classification, not a peer group."""
    facts = [_fact(company_id=1, sector="other", move=m)
             for m in (1.0, 2.0, 3.0, 4.0, 5.0)]
    rows = ev.compute_ranges(facts)
    assert [r["level"] for r in rows] == ["COMPANY"]


def test_none_sector_pools_nothing():
    facts = [_fact(company_id=i, sector=None, move=float(i))
             for i in range(1, 7)]
    assert not [r for r in ev.compute_ranges(facts) if r["level"] == "SECTOR"]


def test_categories_never_mix():
    facts = [_fact(category="pharma", move=m) for m in (1.0, 2.0)]
    facts += [_fact(category="banking", move=m) for m in (3.0, 4.0)]
    assert ev.compute_ranges(facts) == []


def test_signs_are_preserved_not_folded():
    """A category that only ever hurts this stock must show a negative
    range -- the sign structure IS the information."""
    rows = ev.compute_ranges([_fact(move=m) for m in (-4.0, -2.5, -1.0)])
    assert rows[0]["min_excess_move_pct"] == -4.0
    assert rows[0]["max_excess_move_pct"] == -1.0


def test_even_count_median_is_the_midpoint_average():
    facts = [_fact(company_id=i, move=m)
             for i, m in enumerate([1.0, 2.0, 3.0, 10.0], start=1)]
    facts += [_fact(company_id=5, move=4.0)]
    sector = [r for r in ev.compute_ranges(facts) if r["level"] == "SECTOR"][0]
    assert sector["median_excess_move_pct"] == 3.0  # median of 1,2,3,4,10


# --- collect_move_facts: what counts as usable -------------------------------

_alert_id_seq = count(1)


def _move(db_session, company, category="pharma", excess=1.0, status="ok"):
    # market_moves has a UNIQUE(alert_id, company_id) constraint (one row per
    # resolved company per alert) -- each call needs its own alert_id, distinct
    # per row is what the brief's alert_id=1 elided since it wasn't testing
    # that constraint. No real Alert row is required: SQLite here has no
    # foreign_keys pragma enabled, so the FK itself isn't enforced.
    move = MarketMove(
        alert_id=next(_alert_id_seq), company_id=company.id, benchmark_ticker="^CNXPHARMA",
        excess_move_pct=excess, category=category, measurement_status=status,
    )
    db_session.add(move)
    db_session.flush()
    return move


def test_collect_facts_excludes_unusable_rows(db_session, make_company):
    company = make_company("CIPLA.NS", sector="pharma")
    _move(db_session, company, excess=1.5)
    _move(db_session, company, status="no_data", excess=None)
    _move(db_session, company, excess=None)          # ok but unmeasured
    _move(db_session, company, category=None)        # pre-backfill row
    facts = ev.collect_move_facts(db_session)
    assert [f.excess_move_pct for f in facts] == [1.5]
    assert facts[0].sector == "pharma"


def test_collect_facts_excludes_global_market_companies(db_session, make_company):
    """A curated GLOBAL company (app.companies.global_seed) can still carry
    a measured market_move, but every other consumer of these pools --
    deep dive, card back -- is India-only. Same restriction as
    app.companies.resolution._is_tradeable_indian's fan-out branch."""
    company = make_company("BP", sector="oil_gas", market="GLOBAL")
    _move(db_session, company, category="oil_gas", excess=2.0)
    facts = ev.collect_move_facts(db_session)
    assert facts == []


def test_collect_facts_excludes_non_normal_tradeability_companies(db_session, make_company):
    """RESTRICTED/SME/SUSPENDED rows must not feed pools, same restriction
    as the resolver's fan-out branch."""
    company = make_company("SMESHELL.NS", sector="pharma", tradeability="SME")
    _move(db_session, company, category="pharma", excess=2.0)
    facts = ev.collect_move_facts(db_session)
    assert facts == []


# --- apply_ranges ------------------------------------------------------------

def test_apply_ranges_full_rebuild_replaces_previous_rows(db_session):
    ev.apply_ranges(db_session, [{
        "level": "COMPANY", "company_id": 1, "sector": None,
        "category": "pharma", "n_events": 3,
        "min_excess_move_pct": -1.0, "median_excess_move_pct": 0.0,
        "max_excess_move_pct": 1.0,
    }], as_of=AS_OF)
    result = ev.apply_ranges(db_session, [{
        "level": "SECTOR", "company_id": None, "sector": "pharma",
        "category": "pharma", "n_events": 6,
        "min_excess_move_pct": -2.0, "median_excess_move_pct": 0.5,
        "max_excess_move_pct": 3.0,
    }], as_of=AS_OF)
    assert result == {"deleted": 1, "inserted": 1}
    rows = db_session.query(EventVolatilityRange).all()
    assert len(rows) == 1 and rows[0].level == "SECTOR"
    assert rows[0].as_of == AS_OF and rows[0].source == "market_moves"


def test_empty_input_never_clobbers_existing_rows(db_session):
    """A dev DB with no measured moves, or a bug upstream, must not blank
    production's ranges."""
    ev.apply_ranges(db_session, [{
        "level": "COMPANY", "company_id": 1, "sector": None,
        "category": "pharma", "n_events": 3,
        "min_excess_move_pct": -1.0, "median_excess_move_pct": 0.0,
        "max_excess_move_pct": 1.0,
    }], as_of=AS_OF)
    result = ev.apply_ranges(db_session, [], as_of=AS_OF)
    assert result == {"deleted": 0, "inserted": 0}
    assert db_session.query(EventVolatilityRange).count() == 1


# --- range_payload / volatility_range_payload / ranges_for_category ---------

def _stored(db_session, level, category="pharma", company_id=None,
            sector=None, n=3):
    row = EventVolatilityRange(
        level=level, company_id=company_id, sector=sector, category=category,
        n_events=n, min_excess_move_pct=-1.8, median_excess_move_pct=0.6,
        max_excess_move_pct=2.4, as_of=AS_OF, source="market_moves",
    )
    db_session.add(row)
    db_session.flush()
    return row


def test_payload_prefers_the_company_row(db_session, make_company):
    company = make_company("CIPLA.NS", sector="pharma")
    _stored(db_session, "COMPANY", company_id=company.id, n=9)
    _stored(db_session, "SECTOR", sector="pharma", n=40)
    payload = ev.volatility_range_payload(db_session, company, "pharma")
    assert payload == {
        "level": "COMPANY", "n_events": 9,
        "min_excess_move_pct": -1.8, "median_excess_move_pct": 0.6,
        "max_excess_move_pct": 2.4, "as_of": "2026-08-05",
    }


def test_payload_falls_back_to_the_sector_pool(db_session, make_company):
    company = make_company("CIPLA.NS", sector="pharma")
    _stored(db_session, "SECTOR", sector="pharma", n=12)
    payload = ev.volatility_range_payload(db_session, company, "pharma")
    assert payload["level"] == "SECTOR" and payload["n_events"] == 12


def test_payload_is_none_below_every_rung(db_session, make_company):
    company = make_company("CIPLA.NS", sector="pharma")
    assert ev.volatility_range_payload(db_session, company, "pharma") is None


def test_payload_is_none_for_a_different_category(db_session, make_company):
    company = make_company("CIPLA.NS", sector="pharma")
    _stored(db_session, "COMPANY", company_id=company.id, category="banking")
    assert ev.volatility_range_payload(db_session, company, "pharma") is None


def test_payload_is_none_without_a_category(db_session, make_company):
    """Directory browsing has no event context -- a range is meaningless
    without an event type."""
    company = make_company("CIPLA.NS", sector="pharma")
    _stored(db_session, "COMPANY", company_id=company.id)
    assert ev.volatility_range_payload(db_session, company, None) is None


def test_bulk_lookup_returns_both_maps(db_session, make_company):
    company = make_company("CIPLA.NS", sector="pharma")
    _stored(db_session, "COMPANY", company_id=company.id)
    _stored(db_session, "SECTOR", sector="pharma", n=8)
    by_company, by_sector = ev.ranges_for_category(db_session, "pharma")
    assert company.id in by_company
    assert by_sector["pharma"].n_events == 8
