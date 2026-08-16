"""TASK 4.3 -- three horizons, computed independently, never collapsed.

The fixture is the phase file's OMC worked example rebuilt from fake numbers
(see `fixtures/omc_horizons.json`). What it must reproduce is the SHAPE:

    IMMEDIATE  : POSITIVE  (MEDIUM)  inventory gain
    NEAR_TERM  : NEGATIVE  (HIGH)    marketing margin squeeze, price frozen
    STRUCTURAL : UNCERTAIN (LOW)     depends on revision permission
    net_effect : MIXED,  headline = NEAR_TERM
"""
import pytest

from tests.phase4.conftest import fixture_policy_state, fixture_registry
from tests.phase4.helpers import impact_from, omc_fixture, run_horizons, seed_case

HORIZONS = ("IMMEDIATE", "NEAR_TERM", "STRUCTURAL")


@pytest.fixture()
def omc(policy_session):
    fixture = omc_fixture()
    company_id = seed_case(policy_session, fixture)
    run = run_horizons(
        policy_session, fixture, company_id=company_id,
        registry=fixture_registry("FIXTURE_OMC_FREEZE"),
        policy_state=fixture_policy_state("fixture_retail_revision_active"))
    return fixture, company_id, run


def test_the_three_horizons_are_evaluated_at_the_configured_windows(omc):
    from app.analysis.sensitivity.horizons import load_horizon_config

    _, _, run = omc
    config = load_horizon_config()
    assert tuple(config.order) == HORIZONS
    for name in HORIZONS:
        assert run.by_horizon[name].channels
        for channel in run.by_horizon[name].channels:
            assert channel.horizon == name
            assert channel.horizon_days == config.days[name]


def test_each_horizon_is_computed_independently_from_its_own_curves(omc):
    """The hand-computed point estimates. Every one of them is the SAME
    closed form evaluated at a different point on the same curves -- which is
    why Phase 1 stored pass-through as a curve rather than a scalar."""
    fixture, _, run = omc
    for name in HORIZONS:
        total = sum(c.delta_ebitda_inr for c in run.by_horizon[name].channels)
        assert total == pytest.approx(
            float(fixture["expected"][name]["delta_inr"]), rel=1e-9), name


def test_the_omc_fixture_reproduces_the_worked_example(omc):
    _, company_id, run = omc
    impact = impact_from(run, company_id=company_id, ticker="FIXOMC")
    horizons = impact.direction_by_horizon

    assert horizons["IMMEDIATE"]["direction"] == "POSITIVE"
    assert horizons["IMMEDIATE"]["materiality"] == "MEDIUM"
    assert horizons["NEAR_TERM"]["direction"] == "NEGATIVE"
    assert horizons["NEAR_TERM"]["materiality"] == "HIGH"
    assert horizons["STRUCTURAL"]["direction"] == "UNCERTAIN"
    assert horizons["STRUCTURAL"]["materiality"] == "LOW"


def test_net_effect_is_mixed_and_the_headline_is_near_term(omc):
    _, company_id, run = omc
    impact = impact_from(run, company_id=company_id, ticker="FIXOMC")
    assert impact.net_effect == "MIXED"
    assert impact.headline_horizon == "NEAR_TERM"


def test_the_headline_is_the_largest_magnitude_weighted_by_materiality(omc):
    """`headline_horizon` = argmax |delta_ebitda_pct_p50| x materiality weight,
    tie-broken toward NEAR_TERM -- not "the worst one" and not "the first
    one"."""
    from app.analysis.sensitivity.horizons import load_horizon_config

    _, company_id, run = omc
    impact = impact_from(run, company_id=company_id, ticker="FIXOMC")
    config = load_horizon_config()

    scores = {
        name: abs(float(entry["delta_ebitda_pct_p50"]))
        * config.materiality_weight[str(entry["materiality"])]
        for name, entry in impact.direction_by_horizon.items()
        if entry.get("evaluated")}
    assert impact.headline_horizon == max(scores, key=lambda n: scores[n])


def test_the_headline_tie_breaks_toward_near_term():
    from app.analysis.sensitivity.horizons import select_headline

    scored = {"IMMEDIATE": 4.0, "NEAR_TERM": 4.0, "STRUCTURAL": 4.0}
    assert select_headline(scored) == "NEAR_TERM"
    assert select_headline({"IMMEDIATE": 9.0, "NEAR_TERM": 4.0}) == "IMMEDIATE"


def test_all_three_horizons_are_persisted_and_returned(omc, policy_session):
    """"Never discard the non-headline horizons" -- discarding them is
    precisely how V4 produced three contradictory Oil India representations."""
    import json

    from sqlalchemy import text

    from app.core.impact_writer import persist_company_impact
    from app.core.reducer import serialize_company_impact

    _, company_id, run = omc
    impact = impact_from(run, company_id=company_id, ticker="FIXOMC")
    persist_company_impact(policy_session, impact, reducer_run_seq=1)

    stored, headline = policy_session.execute(text(
        "SELECT direction_by_horizon_json, headline_horizon FROM company_impact "
        "WHERE company_id = :company_id"), {"company_id": company_id}).one()
    persisted = json.loads(stored)
    assert set(persisted) == set(HORIZONS)
    assert headline == "NEAR_TERM"
    assert persisted["IMMEDIATE"]["direction"] == "POSITIVE"
    assert persisted["STRUCTURAL"]["direction"] == "UNCERTAIN"

    payload = serialize_company_impact(impact)
    assert set(payload["fundamental"]["direction_by_horizon"]) == set(HORIZONS)
    assert payload["fundamental"]["headline_horizon"] == "NEAR_TERM"


def test_single_horizon_collapse_is_structurally_impossible(omc):
    """Every canonical record carries all three keys, whether or not a horizon
    was evaluated -- a horizon nobody computed is `evaluated: false`, never
    an absent key that a reader would mistake for agreement."""
    from app.core.reducer import serialize_company_impact
    from tests.phase4.helpers import upstream_impact

    _, company_id, run = omc
    for impact in (impact_from(run, company_id=company_id, ticker="FIXOMC"),
                   upstream_impact(levy_active=True)):
        assert set(impact.direction_by_horizon) == set(HORIZONS)
        assert set(serialize_company_impact(impact)
                   ["fundamental"]["direction_by_horizon"]) == set(HORIZONS)


def test_a_sensitivity_fed_record_must_evaluate_all_three_horizons(omc):
    """The write-time check. A record carrying a computed band for one horizon
    only is refused by the writer rather than persisted as a truth."""
    from app.core.impact_writer import HorizonVectorError, validate_horizon_vector
    from app.core.reducer import CompanyImpact

    _, company_id, run = omc
    impact = impact_from(run, company_id=company_id, ticker="FIXOMC")
    validate_horizon_vector(impact)         # the honest record passes

    collapsed = CompanyImpact(**{
        **impact.__dict__,
        "direction_by_horizon": {
            "NEAR_TERM": impact.direction_by_horizon["NEAR_TERM"]}})
    with pytest.raises(HorizonVectorError):
        validate_horizon_vector(collapsed)


def test_the_unknown_regime_is_what_makes_the_structural_horizon_uncertain(omc):
    """The fixture retail-revision state has a 120-day freshness window, so it
    is KNOWN at 5 and 90 days and UNKNOWN at 270. That is why the structural
    horizon widens and caps at C rather than inheriting the freeze."""
    _, _, run = omc
    immediate = run.by_horizon["IMMEDIATE"]
    structural = run.by_horizon["STRUCTURAL"]

    assert "FIXTURE_OMC_FREEZE" in immediate.policy_modifiers_applied
    assert "FIXTURE_OMC_FREEZE" not in structural.policy_modifiers_applied
    assert "FIXTURE_OMC_FREEZE" in structural.policy_modifiers_unknown_state
    caps = {c.grade_cap for c in structural.channels
            if c.channel_id == "realization:fixture_marketing_margin"}
    assert caps == {"C"}


def test_the_inventory_channel_dominates_the_immediate_horizon(omc):
    """Task 4.3's new channel type, and the specific mechanism the OMC
    contradiction was missing."""
    _, _, run = omc
    immediate = run.by_horizon["IMMEDIATE"]
    by_id = {c.channel_id: c for c in immediate.channels}
    inventory = by_id["realization:fixture_inventory_stock"]
    assert inventory.channel_type == "INVENTORY_REVALUATION"
    assert inventory.delta_ebitda_inr == pytest.approx(32_000_000.0)
    assert abs(inventory.delta_ebitda_inr) == max(
        abs(c.delta_ebitda_inr) for c in immediate.channels)


def test_an_inventory_exposure_with_no_realisation_fraction_is_uncomputable(
        policy_session):
    """No parameter, no channel -- Phase 2's rule, unchanged by the new type."""
    from app.analysis.sensitivity.channels import Shock
    from app.analysis.sensitivity.engine import analyse_company
    from tests.phase4.conftest import (
        FIXTURE_ANALYSIS_VERSION, FIXTURE_EVENT_ID, FIXTURE_NOW, FIXTURE_TODAY,
        make_company, seed_exposure, seed_financials,
    )

    company = make_company(policy_session, ticker="FIXBARE", name="Fixture Bare Ltd")
    seed_financials(policy_session, company_id=company.id, ebitda_inr=1_000_000_000.0)
    seed_exposure(policy_session, exposure_id="fixture-bare-inventory",
                  company_id=company.id,
                  exposure_tag="realization:fixture_inventory_stock",
                  exposure_kind="INVENTORY", base_value_inr=1_000_000_000.0,
                  share_of_base=1.0)

    run = analyse_company(
        policy_session, company_id=company.id,
        shocks=(Shock(shock_id="s", exposure_tag="realization:fixture_inventory_stock",
                      delta_pct=0.1, horizon_days=5),),
        event_id=FIXTURE_EVENT_ID, analysis_version=FIXTURE_ANALYSIS_VERSION,
        created_at=FIXTURE_NOW, as_of=FIXTURE_TODAY)
    assert run.channels == ()
    assert run.signals == ()
    assert run.uncomputable_channels


def test_the_horizon_config_is_policy_not_data():
    """`config/horizons.yaml` states windows and weights. It carries no
    company, no coefficient and no financial figure."""
    from pathlib import Path

    import yaml

    raw = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / "config" / "horizons.yaml"
         ).read_text(encoding="utf-8"))
    assert set(raw) == {"version", "horizons", "headline", "materiality_weight"}
    assert set(raw["horizons"]) == set(HORIZONS)
    assert raw["headline"]["tie_break"] == "NEAR_TERM"
