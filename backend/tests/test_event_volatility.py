"""Subsystem D: per-(stock, category) reaction ranges from measured moves.

Spec: docs/superpowers/specs/2026-08-05-event-volatility-ranges-design.md.
The tests that matter most are the withholding ones -- below threshold,
wrong level, missing category must all yield nothing rather than a number.
"""
from datetime import date

from app import config
from app.models import EventVolatilityRange, MarketMove

AS_OF = date(2026, 8, 5)


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
    calibration_samples.category already documents)."""
    assert hasattr(MarketMove, "category")


def test_thresholds_live_in_config_not_code():
    assert config.EVENT_VOL_COMPANY_MIN_EVENTS == 3
    assert config.EVENT_VOL_SECTOR_MIN_EVENTS == 5
