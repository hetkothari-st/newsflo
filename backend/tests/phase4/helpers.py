"""Shared Phase 4 case construction.

Two ways in, both exercising PRODUCTION code paths rather than re-implementing
them:

  * `upstream_impact` builds channels purely, runs the real
    `apply_modifiers`, the real Monte Carlo, the real signal emitter and the
    real reducer. Nothing touches a database;
  * `seed_case` / `run_horizons` seed a throwaway ledger from a fixture JSON
    and run the real three-horizon engine over it, which is the only way to
    exercise the pass-through / hedge / elasticity CURVES the horizon vector
    is built on.

No production module may import this file -- asserted by
`test_no_fixture_data_reaches_production.py`.
"""
import json
from datetime import date

from sqlalchemy import text

from tests.phase4.conftest import (
    FIXTURE_ANALYSIS_VERSION, FIXTURE_EVENT_ID, FIXTURE_NOW, FIXTURE_TODAY,
    fixture_policy_state, fixture_registry, load_json_fixture, make_company,
    realization_channel, seed_exposure, seed_financials, seed_modifier,
)

UPSTREAM_COMPANY_ID = 9401
UPSTREAM_EBITDA_INR = 5_000_000_000.0


# --- the publication gate ---------------------------------------------------

def clean_primary_draft():
    """An `ImpactDraft` that clears every PRIMARY rule the deployed policy
    states. Tests break exactly one field of it at a time."""
    from app.core.gates import ImpactDraft

    return ImpactDraft(
        entity_status="ACTIVE", entity_ambiguous=False, exposure_stale=False,
        materiality_bucket="HIGH", graph_distance=1, directness="DIRECT",
        evidence_grade="A", weakest_link="COST_EXPOSURE:BOUND",
        sign_consistency=1.0, empirical_status="AGREE", objections=(),
        unbound_claim_ids=(), verifier_status="PASS", adv_20d_inr=None,
        event_status="CONFIRMED", shock_magnitude_confidence=0.9,
        mechanism_id="fixture:mechanism:1", net_effect="POSITIVE",
        delta_ebitda_pct_abs=10.0, uses_sector_proxy=False,
        policy_state_stale=False)


# --- the upstream-on-crude case, built without a database -------------------

def upstream_channels(*, levy_active: bool):
    """One REVENUE_REALIZATION channel on a fixture crude tag, and the
    fixture levy that may or may not still be in force."""
    from app.analysis.policy.registry import PolicyRegistry, modifier_from_mapping
    from tests.phase4.conftest import fixture_modifier

    channel = realization_channel(
        exposure_id="fixture-upstream-realization",
        company_id=UPSTREAM_COMPANY_ID,
        exposure_tag="realization:fixture_crude",
        base_value_inr=10_000_000_000.0, share_of_base=1.0,
        delta_pct=0.06, level_before=100.0, level_after=106.0,
        elasticity=1.0, capture=0.0, source="FILED")

    raw = dict(fixture_modifier("FIXTURE_LEVY_UPSTREAM"))
    if not levy_active:
        # "with the levy repealed (effective_to set)" -- the phase file's own
        # second half of the test.
        raw["effective_to"] = "2225-12-31"
    return channel, PolicyRegistry((modifier_from_mapping(raw),))


def upstream_impact(*, levy_active: bool, policy_state_stale: bool = False,
                    event_context=None):
    """The canonical record for the upstream fixture company."""
    from app.analysis.policy.transforms import apply_modifiers
    from app.analysis.sensitivity.engine import channel_signals
    from app.analysis.sensitivity.monte_carlo import serialize_materiality, simulate
    from app.analysis.sensitivity.config import load_materiality_config
    from app.core.config_loader import load_gate_config, load_sensitivity_policy
    from app.core.reducer import EventContext, ReducerConfig, reduce_company_impact
    from app.core.signals import make_signal

    config = load_materiality_config()
    channel, registry = upstream_channels(levy_active=levy_active)
    modified = apply_modifiers(
        (channel,), as_of_date=FIXTURE_TODAY, policy_state=fixture_policy_state(),
        registry=registry)

    materiality = simulate(
        modified.channels, ebitda_ttm_inr=UPSTREAM_EBITDA_INR,
        event_id=FIXTURE_EVENT_ID, company_id=UPSTREAM_COMPANY_ID,
        analysis_version=FIXTURE_ANALYSIS_VERSION, config=config)

    signals, _ = channel_signals(
        modified.channels, materiality_block=serialize_materiality(materiality, config),
        ebitda_ttm_inr=UPSTREAM_EBITDA_INR, event_id=FIXTURE_EVENT_ID,
        company_id=UPSTREAM_COMPANY_ID, analysis_version=FIXTURE_ANALYSIS_VERSION,
        created_at=FIXTURE_NOW, config=config, exposure_stale=False,
        policy_state_stale=policy_state_stale,
        policy_modifiers=modified.as_payload())

    signals = list(signals) + [
        make_signal(event_id=FIXTURE_EVENT_ID, company_id=UPSTREAM_COMPANY_ID,
                    stage="ENTITY", kind="ENTITY_RESOLUTION",
                    payload={"ticker": "FIXUPS", "isin": None,
                             "resolution": "RESOLVED", "entity_status": "ACTIVE",
                             "_fixture": True},
                    created_by="human:fixture", analysis_version=FIXTURE_ANALYSIS_VERSION,
                    created_at=FIXTURE_NOW),
        make_signal(event_id=FIXTURE_EVENT_ID, company_id=UPSTREAM_COMPANY_ID,
                    stage="DISCOVERY", kind="DISCOVERY",
                    payload={"discovery_source": "MENTION", "directness": "DIRECT",
                             "graph_distance": 1, "_fixture": True},
                    created_by="human:fixture", analysis_version=FIXTURE_ANALYSIS_VERSION,
                    created_at=FIXTURE_NOW),
        make_signal(event_id=FIXTURE_EVENT_ID, company_id=UPSTREAM_COMPANY_ID,
                    stage="CLAIMS", kind="EVIDENCE_BINDING",
                    payload={"claim_id": "fixture-claim-1",
                             "claim_type": "REVENUE_EXPOSURE",
                             "binding_status": "BOUND", "evidence_grade": "A",
                             "evidence_ids": ["fixture-upstream-realization"],
                             "_fixture": True},
                    created_by="human:fixture", analysis_version=FIXTURE_ANALYSIS_VERSION,
                    created_at=FIXTURE_NOW),
    ]

    context = event_context or EventContext(
        event_status="CONFIRMED", shock_magnitude_confidence=0.9,
        exposure_stale=False)
    return reduce_company_impact(signals, ReducerConfig(
        gate_config=load_gate_config(), event_context=context,
        sensitivity_policy=load_sensitivity_policy()))


# --- the ledger-backed horizon cases ----------------------------------------

def seed_case(session, fixture: dict) -> int:
    """Seed one fixture company, its exposures, its parameter rows and its
    EBITDA into a throwaway database. Returns the company id."""
    company = make_company(session, ticker=fixture["company"]["ticker"],
                           name=fixture["company"]["name"],
                           sector=fixture["company"]["sector"])
    seed_financials(session, company_id=company.id,
                    ebitda_inr=float(fixture["company"]["ebitda_ttm_inr"]))

    for raw in fixture["exposures"]:
        seed_exposure(session, exposure_id=raw["exposure_id"],
                      company_id=company.id, exposure_tag=raw["exposure_tag"],
                      exposure_kind=raw["exposure_kind"],
                      base_value_inr=float(raw["base_value_inr"]),
                      share_of_base=float(raw["share_of_base"]),
                      base_kind=raw["base_kind"])
        modifier = raw.get("modifier")
        if modifier:
            seed_modifier(session, modifier_id=modifier["modifier_id"],
                          company_id=company.id, applies_to_tag=raw["exposure_tag"],
                          modifier_kind=modifier["modifier_kind"],
                          parameters=_clean(modifier["parameters"]))
        curve = raw.get("curve")
        if curve:
            session.execute(text(
                "INSERT INTO pass_through_curve (curve_id, company_id, sector_id, "
                "exposure_tag, points, basis, as_of_date, reviewed_by) VALUES "
                "(:curve_id, :company_id, NULL, :exposure_tag, :points, :basis, "
                ":as_of_date, 'human:fixture-reviewer')"), {
                    "curve_id": curve["curve_id"], "company_id": company.id,
                    "exposure_tag": raw["exposure_tag"],
                    "points": json.dumps([
                        {"lag_days": p["lag_days"], "fraction": p["fraction"]}
                        for p in curve["points"]]),
                    "basis": curve["basis"],
                    "as_of_date": FIXTURE_TODAY.isoformat()})
    session.flush()
    return company.id


def _clean(parameters: dict) -> dict:
    """Strip the `_fixture` markers before the JSON reaches a ledger column --
    the marker is a property of the FIXTURE FILE, and the parameter resolver
    must see exactly the shape a real extractor would write."""
    if isinstance(parameters, dict):
        return {k: _clean(v) for k, v in parameters.items() if k != "_fixture"}
    if isinstance(parameters, list):
        return [_clean(v) for v in parameters]
    return parameters


def case_shocks(fixture: dict):
    """One shock per exposure tag, all describing the SAME move."""
    from app.analysis.sensitivity.channels import Shock

    raw = fixture["shock"]
    tags = sorted({e["exposure_tag"] for e in fixture["exposures"]})
    return tuple(
        Shock(shock_id=f"fixture-shock-{index}", exposure_tag=tag,
              delta_pct=float(raw["delta_pct"]), horizon_days=0,
              mechanism_id="fixture:mechanism:1",
              level_before=float(raw["level_before"]),
              level_after=float(raw["level_after"]))
        for index, tag in enumerate(tags))


def run_horizons(session, fixture: dict, *, company_id: int,
                 registry=None, policy_state=None, as_of: date = FIXTURE_TODAY):
    from app.analysis.sensitivity.engine import analyse_company_horizons

    return analyse_company_horizons(
        session, company_id=company_id, shocks=case_shocks(fixture),
        event_id=FIXTURE_EVENT_ID, analysis_version=FIXTURE_ANALYSIS_VERSION,
        created_at=FIXTURE_NOW, as_of=as_of,
        policy_registry=registry if registry is not None else fixture_registry(),
        policy_state=policy_state if policy_state is not None
        else fixture_policy_state())


def impact_from(run, *, company_id: int, ticker: str, event_context=None):
    """Reduce a `HorizonRun`'s signals into the canonical record."""
    from app.core.config_loader import load_gate_config, load_sensitivity_policy
    from app.core.reducer import EventContext, ReducerConfig, reduce_company_impact
    from app.core.signals import make_signal

    signals = list(run.signals) + [
        make_signal(event_id=FIXTURE_EVENT_ID, company_id=company_id,
                    stage="ENTITY", kind="ENTITY_RESOLUTION",
                    payload={"ticker": ticker, "isin": None,
                             "resolution": "RESOLVED", "entity_status": "ACTIVE",
                             "_fixture": True},
                    created_by="human:fixture", analysis_version=FIXTURE_ANALYSIS_VERSION,
                    created_at=FIXTURE_NOW),
        make_signal(event_id=FIXTURE_EVENT_ID, company_id=company_id,
                    stage="DISCOVERY", kind="DISCOVERY",
                    payload={"discovery_source": "MENTION", "directness": "DIRECT",
                             "graph_distance": 1, "_fixture": True},
                    created_by="human:fixture", analysis_version=FIXTURE_ANALYSIS_VERSION,
                    created_at=FIXTURE_NOW),
        make_signal(event_id=FIXTURE_EVENT_ID, company_id=company_id,
                    stage="CLAIMS", kind="EVIDENCE_BINDING",
                    payload={"claim_id": "fixture-claim-1",
                             "claim_type": "REVENUE_EXPOSURE",
                             "binding_status": "BOUND", "evidence_grade": "A",
                             "evidence_ids": ["fixture-evidence-1"],
                             "_fixture": True},
                    created_by="human:fixture", analysis_version=FIXTURE_ANALYSIS_VERSION,
                    created_at=FIXTURE_NOW),
    ]
    context = event_context or EventContext(
        event_status="CONFIRMED", shock_magnitude_confidence=0.9,
        exposure_stale=False)
    return reduce_company_impact(signals, ReducerConfig(
        gate_config=load_gate_config(), event_context=context,
        sensitivity_policy=load_sensitivity_policy()))


def omc_fixture() -> dict:
    from tests.phase4.conftest import OMC_FIXTURE

    return load_json_fixture(OMC_FIXTURE)


def oil_india_fixture() -> dict:
    from tests.phase4.conftest import OIL_INDIA_FIXTURE

    return load_json_fixture(OIL_INDIA_FIXTURE)
