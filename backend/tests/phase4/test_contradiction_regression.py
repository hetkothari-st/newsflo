"""Phase file TESTS/test_contradiction_regression.py.

    "the Oil India fixture from the V4 incident yields exactly one canonical
     fundamental truth with no field-level contradiction"

The V4 incident was one company, one event and THREE representations that
disagreed. The fix is not "be more careful": it is that a horizon is a first
class dimension, that all three are persisted, and that the ONE canonical row
states a per-horizon direction plus a net effect that cannot contradict it.

`fixtures/oil_india_incident.json` rebuilds the incident's SHAPE from fake
numbers: an inventory gain that dominates the immediate horizon, a cost
pass-through that collapses at the near-term horizon, and a realisation
upside a levy has already taken most of.
"""
import json

import pytest
from sqlalchemy import text

from tests.phase4.conftest import fixture_policy_state, fixture_registry
from tests.phase4.helpers import (
    impact_from, oil_india_fixture, run_horizons, seed_case,
)

HORIZONS = ("IMMEDIATE", "NEAR_TERM", "STRUCTURAL")
DIRECTIONS = {"POSITIVE": 1, "NEGATIVE": -1}


@pytest.fixture()
def incident(policy_session):
    fixture = oil_india_fixture()
    company_id = seed_case(policy_session, fixture)
    run = run_horizons(
        policy_session, fixture, company_id=company_id,
        registry=fixture_registry("FIXTURE_LEVY_UPSTREAM"),
        policy_state=fixture_policy_state())
    return fixture, company_id, run


def test_the_incident_shape_is_reproduced(incident):
    """Three horizons, three different answers -- the input that used to
    produce three contradictory records."""
    fixture, _, run = incident
    for name in HORIZONS:
        total = sum(c.delta_ebitda_inr for c in run.by_horizon[name].channels)
        assert total == pytest.approx(
            float(fixture["expected"][name]["delta_inr"]), rel=1e-9), name


def test_exactly_one_canonical_row_survives_three_reductions(incident, policy_session):
    from app.core.impact_writer import persist_company_impact

    _, company_id, run = incident
    impact = impact_from(run, company_id=company_id, ticker="FIXOIL")
    for run_seq in (1, 2, 3):
        persist_company_impact(policy_session, impact, reducer_run_seq=run_seq)

    rows = policy_session.execute(text(
        "SELECT event_id, company_id, analysis_version, count(*) "
        "FROM company_impact GROUP BY 1, 2, 3")).all()
    assert len(rows) == 1
    assert rows[0][3] == 1


def test_no_field_combination_implies_opposite_directions(incident):
    """The property the incident violated, stated as an assertion over the
    WHOLE record rather than over one field at a time."""
    _, company_id, run = incident
    impact = impact_from(run, company_id=company_id, ticker="FIXOIL")

    # 1. every horizon's direction agrees with its own computed band.
    for name, entry in impact.direction_by_horizon.items():
        if not entry.get("evaluated"):
            continue
        p50 = float(entry["delta_ebitda_pct_p50"])
        if entry["direction"] in DIRECTIONS:
            assert DIRECTIONS[entry["direction"]] * p50 > 0, name

    # 2. the headline horizon is one of the evaluated ones, and it is the one
    #    the record leads with.
    headline = impact.direction_by_horizon[impact.headline_horizon]
    assert headline["evaluated"] is True

    # 3. the net effect never asserts a direction opposite to any horizon's.
    signs = {DIRECTIONS[e["direction"]] for e in impact.direction_by_horizon.values()
             if e.get("evaluated") and e["direction"] in DIRECTIONS}
    if impact.net_effect in DIRECTIONS:
        assert signs <= {DIRECTIONS[impact.net_effect]}
    else:
        assert len(signs) > 1 or impact.net_effect in (
            "MIXED", "UNCERTAIN", "NO_MATERIAL_IMPACT")

    # 4. horizons that disagree are published as MIXED, never averaged into
    #    one of them (master context invariant 9).
    if len(signs) > 1:
        assert impact.net_effect == "MIXED"


def test_the_persisted_record_says_the_same_thing_as_the_object(incident,
                                                                policy_session):
    """A contradiction between the in-memory record and the row is the same
    defect one layer down."""
    from app.core.impact_writer import persist_company_impact

    _, company_id, run = incident
    impact = impact_from(run, company_id=company_id, ticker="FIXOIL")
    persist_company_impact(policy_session, impact, reducer_run_seq=1)

    row = policy_session.execute(text(
        "SELECT net_effect, headline_horizon, direction_by_horizon_json, "
        "materiality_bucket FROM company_impact WHERE company_id = :company_id"),
        {"company_id": company_id}).one()
    assert row[0] == impact.net_effect
    assert row[1] == impact.headline_horizon
    assert json.loads(row[2]) == {k: dict(v) for k, v in
                                  impact.direction_by_horizon.items()}
    assert row[3] == impact.materiality_bucket


def test_the_levy_is_recorded_on_the_one_row_rather_than_inferred(incident):
    _, company_id, run = incident
    impact = impact_from(run, company_id=company_id, ticker="FIXOIL")
    assert "FIXTURE_LEVY_UPSTREAM" in impact.policy_modifiers_applied


def test_the_record_is_byte_identical_however_the_signals_are_ordered(incident):
    """Order independence is what makes "exactly one truth" meaningful: two
    workers reducing the same signals in different orders must not produce
    two different rows."""
    import random

    from app.core.reducer import serialize_company_impact

    _, company_id, run = incident
    first = impact_from(run, company_id=company_id, ticker="FIXOIL")

    shuffled = list(run.signals)
    random.Random(4).shuffle(shuffled)
    from app.analysis.sensitivity.engine import HorizonRun

    reordered = impact_from(
        HorizonRun(company_id=run.company_id, by_horizon=run.by_horizon,
                   signals=tuple(shuffled)),
        company_id=company_id, ticker="FIXOIL")
    assert serialize_company_impact(first) == serialize_company_impact(reordered)
