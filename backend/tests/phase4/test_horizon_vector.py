"""TASK 4.3 -- three horizons, computed independently, never collapsed.

The fixture is the phase file's OMC worked example rebuilt from fake numbers
(see `fixtures/omc_horizons.json`). What it must reproduce is the SHAPE:

    IMMEDIATE  : POSITIVE  (MEDIUM)  inventory gain
    NEAR_TERM  : NEGATIVE  (HIGH)    marketing margin squeeze, price frozen
    STRUCTURAL : UNCERTAIN (LOW)     depends on revision permission
    net_effect : MIXED,  headline = NEAR_TERM
"""
import json

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


def test_a_record_naming_fewer_than_three_horizons_is_refused_at_the_writer(omc):
    """The write-time check, and the STRUCTURAL half of it: a record that
    names two horizons is missing one, not agreeing about it."""
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


# --- FIX ROUND 1 (I-1): partial vectors are legal and must persist ----------

def test_a_single_horizon_run_persists_rather_than_being_dropped(policy_session):
    """REGRESSION. A caller that runs `analyse_company` at ONE horizon produces
    a computed band on NEAR_TERM and honest `evaluated: false` elsewhere. The
    writer used to refuse it, and `app/pipeline.py` wraps the V5 hook in a bare
    `except`, so the canonical record would have been dropped IN SILENCE."""
    from sqlalchemy import text

    from app.core.impact_writer import persist_company_impact, validate_horizon_vector
    from tests.phase4.helpers import upstream_impact

    impact = upstream_impact(levy_active=True)
    assert impact.sensitivity is not None
    assert impact.direction_by_horizon["NEAR_TERM"]["evaluated"] is True
    assert impact.direction_by_horizon["IMMEDIATE"]["evaluated"] is False
    assert impact.direction_by_horizon["STRUCTURAL"]["evaluated"] is False

    validate_horizon_vector(impact)
    persist_company_impact(policy_session, impact, reducer_run_seq=1)
    assert policy_session.execute(text(
        "SELECT count(*) FROM company_impact")).scalar() == 1


def test_a_horizon_whose_only_channel_decays_to_zero_persists(policy_session):
    """REGRESSION. An inventory revaluation is a one-off: its realisation
    fraction is 0 at 270 days, so the company has NO computable channel at the
    structural horizon and the engine emits no band there. That is the correct
    answer, and the record must persist saying so."""
    from sqlalchemy import text

    from app.core.impact_writer import persist_company_impact
    from tests.phase4.conftest import (
        fixture_policy_state, fixture_registry, make_company, seed_exposure,
        seed_financials, seed_modifier,
    )
    from tests.phase4.helpers import impact_from, run_horizons

    fixture = {
        "shock": {"delta_pct": 0.064, "level_before": 100.0, "level_after": 106.4},
        "exposures": [{"exposure_tag": "realization:fixture_inventory_stock"}]}
    company = make_company(policy_session, ticker="FIXDECAY",
                           name="Fixture Decay Ltd")
    seed_financials(policy_session, company_id=company.id,
                    ebitda_inr=1_000_000_000.0)
    seed_exposure(policy_session, exposure_id="fixture-decay-inventory",
                  company_id=company.id,
                  exposure_tag="realization:fixture_inventory_stock",
                  exposure_kind="INVENTORY", base_value_inr=5_000_000_000.0,
                  share_of_base=1.0)
    seed_modifier(policy_session, modifier_id="fixture-decay-mod",
                  company_id=company.id,
                  applies_to_tag="realization:fixture_inventory_stock",
                  modifier_kind="PASS_THROUGH", parameters={
                      "measurement": "FILED",
                      "inventory_realization_fraction_curve": [
                          {"lag_days": 5, "fraction": 0.5},
                          {"lag_days": 90, "fraction": 0.1},
                          {"lag_days": 270, "fraction": 0.0}]})

    run = run_horizons(policy_session, fixture, company_id=company.id,
                       registry=fixture_registry(),
                       policy_state=fixture_policy_state())
    impact = impact_from(run, company_id=company.id, ticker="FIXDECAY")

    assert impact.direction_by_horizon["IMMEDIATE"]["evaluated"] is True
    assert impact.direction_by_horizon["NEAR_TERM"]["evaluated"] is True
    # zero delta at 270d -> no channel -> no band, honestly recorded
    assert impact.direction_by_horizon["STRUCTURAL"]["evaluated"] is False

    persist_company_impact(policy_session, impact, reducer_run_seq=1)
    stored = policy_session.execute(text(
        "SELECT direction_by_horizon_json FROM company_impact "
        "WHERE company_id = :company_id"), {"company_id": company.id}).scalar()
    assert set(json.loads(stored)) == set(HORIZONS)


def test_a_band_with_no_evaluated_horizon_at_all_is_still_refused():
    """DO NOT OVER-RELAX. A computed band behind which NO horizon was
    evaluated is a number from nowhere, and the writer still refuses it."""
    from app.core.impact_writer import HorizonVectorError, validate_horizon_vector
    from app.core.reducer import UNEVALUATED_HORIZON, CompanyImpact
    from tests.phase4.helpers import upstream_impact

    impact = upstream_impact(levy_active=True)
    hollow = CompanyImpact(**{
        **impact.__dict__,
        "direction_by_horizon": {name: dict(UNEVALUATED_HORIZON)
                                 for name in HORIZONS}})
    with pytest.raises(HorizonVectorError, match="no horizon"):
        validate_horizon_vector(hollow)


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


def test_the_ui_surface_leads_with_the_headline_and_keeps_the_other_two(omc):
    """Task 4.4: "UI leads with headline horizon; other two on expand." The
    renderer is a later phase; the SURFACE it consumes is this one, and it
    can never be handed a record with a horizon missing."""
    from app.analysis.sensitivity.presentation import (
        horizon_lines, impact_lines, modifier_chips,
    )

    _, company_id, run = omc
    impact = impact_from(run, company_id=company_id, ticker="FIXOMC")

    lines = horizon_lines(impact)
    assert len(lines) == 3
    assert [line[2:].split(":")[0] for line in lines] == [
        "IMMEDIATE", "NEAR TERM", "STRUCTURAL"]
    assert lines[1].startswith("> "), "the headline horizon is not marked"
    assert lines[0].startswith("  ") and lines[2].startswith("  ")

    chips = modifier_chips(impact)
    assert {chip["modifier_id"] for chip in chips} == {"FIXTURE_OMC_FREEZE"}
    assert {chip["status"] for chip in chips} == {"APPLIED", "UNKNOWN_STATE"}
    for chip in chips:
        assert chip["horizons"]
        assert chip["label"]

    body = "\n".join(impact_lines(impact))
    assert "STRUCTURAL" in body and "IMMEDIATE" in body
    assert "FIXTURE_OMC_FREEZE" in body


def test_the_inventory_channel_refuses_to_run_with_no_parameters_at_all():
    """The Phase 2 no-defaults guard, extended to the channel type Phase 4
    added. `tests/phase2/test_channel_math.py` names INVENTORY as covered
    here rather than in its own frozen corpus."""
    from app.analysis.sensitivity.channels import compute_channel
    from app.analysis.sensitivity.params import InsufficientParameterData
    from tests.phase4.conftest import make_exposure, make_shock

    exposure = make_exposure(
        exposure_kind="INVENTORY",
        exposure_tag="realization:fixture_inventory_stock")
    shock = make_shock(exposure_tag="realization:fixture_inventory_stock")
    with pytest.raises(InsufficientParameterData):
        compute_channel(exposure, shock, {}, horizon_days=5)


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
