"""TASK 0.2/0.3 tests -- one truth per company per event.

docs/v5/01_PHASE_0_canonical_truth.md TESTS/test_single_truth.py:
  * for a fixture event, exactly one CompanyImpact row exists per
    (event_id, company_id, analysis_version)
  * no field combination within a CompanyImpact implies opposite directions
"""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.db import Base
from tests.phase0 import fixtures


@pytest.fixture()
def impact_db(tmp_path):
    from app import models  # noqa: F401

    engine = create_engine(f"sqlite:///{tmp_path / 'truth.db'}",
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_exactly_one_row_per_event_company_analysis_version(impact_db):
    from app.core.impact_writer import persist_company_impact
    from app.core.reducer import reduce_company_impact

    config = fixtures.reducer_config()
    for company_id in (fixtures.PRIMARY_COMPANY_ID, fixtures.REMOTE_COMPANY_ID):
        impact = reduce_company_impact(fixtures.signals(company_id), config)
        # Three runs of the same analysis (a retry, a replay, a stale worker
        # catching up) must converge on ONE row.
        for run_seq in (1, 2, 3):
            persist_company_impact(impact_db, impact, reducer_run_seq=run_seq)

    rows = impact_db.execute(text(
        "SELECT event_id, company_id, analysis_version, count(*) "
        "FROM company_impact GROUP BY 1, 2, 3")).all()
    assert len(rows) == 2
    assert all(row[3] == 1 for row in rows), (
        f"duplicate canonical rows: {rows}")


def test_direction_is_consistent_with_the_aggregate_channel_sign():
    """No field combination inside one CompanyImpact may imply opposite
    directions -- the defect this whole phase exists to make impossible
    (the Oil India three-way contradiction)."""
    from app.core.reducer import reduce_company_impact

    config = fixtures.reducer_config()
    for company_id in (fixtures.PRIMARY_COMPANY_ID, fixtures.REMOTE_COMPANY_ID):
        impact = reduce_company_impact(fixtures.signals(company_id), config)
        material = [c for c in impact.channels if c["material"]]
        positives = [c for c in material if c["direction"] == "POSITIVE"]
        negatives = [c for c in material if c["direction"] == "NEGATIVE"]

        if positives and negatives:
            assert impact.net_effect == "MIXED"
        elif positives:
            assert impact.net_effect == "POSITIVE"
        elif negatives:
            assert impact.net_effect == "NEGATIVE"
        else:
            assert impact.net_effect == "NO_MATERIAL_IMPACT"

        # ...and the horizon vector agrees with the headline.
        headline = impact.direction_by_horizon[impact.headline_horizon]
        assert headline["direction"] == impact.net_effect


def test_mixed_is_never_collapsed_into_a_direction():
    """Master context invariant 9."""
    from app.core.reducer import reduce_company_impact

    impact = reduce_company_impact(
        fixtures.signals(fixtures.REMOTE_COMPANY_ID), fixtures.reducer_config())
    assert impact.net_effect == "MIXED"
    assert impact.sign_consistency < 0.60
    assert impact.publication_tier in ("SECONDARY_RIPPLE", "REJECTED")
    if impact.publication_tier == "SECONDARY_RIPPLE":
        assert impact.direction_by_horizon["NEAR_TERM"]["direction"] == "MIXED"


def test_a_rejected_impact_always_carries_a_reason_and_vice_versa():
    from app.core.reducer import reduce_company_impact

    config = fixtures.reducer_config()
    for company_id in (fixtures.PRIMARY_COMPANY_ID, fixtures.REMOTE_COMPANY_ID):
        impact = reduce_company_impact(fixtures.signals(company_id), config)
        assert (impact.publication_tier == "REJECTED") == \
               (impact.rejection_reason is not None)


def test_the_fixture_primary_company_reaches_primary():
    """The fixture corpus must contain at least one PRIMARY company, or the
    'firewall deletion rate on PRIMARY prose == 0' DoD is vacuous."""
    from app.core.reducer import reduce_company_impact

    impact = reduce_company_impact(
        fixtures.signals(fixtures.PRIMARY_COMPANY_ID), fixtures.reducer_config())
    assert impact.publication_tier == "PRIMARY", impact.gate_trace
