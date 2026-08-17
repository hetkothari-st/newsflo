"""Builders for Phase 6 tests.

Two of them:

  * `impact(...)` builds a `CompanyImpact` DIRECTLY. The section engine is a
    pure function of the canonical record, so a test of it should hand it
    canonical records rather than run four upstream stages to manufacture
    one -- and a builder that names every field makes the input of each
    section test readable in one screen.
  * `signal(...)` builds one `Signal` with the frozen fixture identity, for
    the falsifier and reducer tests.

Every number that appears here or in `fixtures/` is invented and marked
`_fixture`. Nothing in this file is a claim about any company.
"""
from typing import Any, Mapping, Sequence

from app.core.reducer import CompanyImpact, HORIZONS, REDUCER_VERSION
from app.core.signals import make_signal
from tests.phase6.conftest import (
    FIXTURE_ANALYSIS_VERSION, FIXTURE_EVENT_ID, FIXTURE_NOW,
)

UNEVALUATED = {"direction": None, "materiality": None, "sign_consistency": None,
               "delta_ebitda_pct_p50": None, "evaluated": False}


def band(p50: float, *, spread: float = 1.0) -> dict:
    """A computed materiality block, in the shape the sensitivity engine
    emits. `_fixture` is carried so a row built from it is identifiable in
    the database itself."""
    return {
        "_fixture": True,
        "bucket": "MEDIUM",
        "sign_consistency": 0.9,
        "delta_ebitda_pct": {"p10": p50 - spread, "p50": p50, "p90": p50 + spread},
        "driver_ranking": [],
    }


def impact(*, company_id: int, ticker: str, publication_tier: str,
           net_effect: str, mechanism_id: str | None,
           headline_horizon: str = "NEAR_TERM",
           delta_ebitda_pct_p50: float | None = None,
           materiality_bucket: str = "MEDIUM",
           evidence_grade: str | None = "B",
           directness: str | None = "DIRECT",
           graph_distance: int | None = 1,
           discovery_source: str | None = "MECHANISM",
           rejection_reason: str | None = None,
           channels: Sequence[Mapping[str, Any]] = (),
           claim_bindings: Sequence[Mapping[str, Any]] = (),
           objections: Sequence[Mapping[str, Any]] = (),
           empirical_status: str | None = None,
           event_id: str = FIXTURE_EVENT_ID) -> CompanyImpact:
    """One canonical record, every field named."""
    evaluated = {
        "direction": net_effect, "materiality": materiality_bucket,
        "sign_consistency": 0.9, "delta_ebitda_pct_p50": delta_ebitda_pct_p50,
        "evaluated": True}
    return CompanyImpact(
        event_id=event_id, company_id=company_id, ticker=ticker, isin=None,
        analysis_version=FIXTURE_ANALYSIS_VERSION,
        reducer_version=REDUCER_VERSION, gate_config_version="fixture-gates",
        direction_by_horizon={
            horizon: (evaluated if horizon == headline_horizon else dict(UNEVALUATED))
            for horizon in HORIZONS},
        headline_horizon=headline_horizon, net_effect=net_effect,
        sign_consistency=0.9, channels=tuple(dict(c) for c in channels),
        policy_modifiers_applied=(), policy_modifiers_unmatched=(),
        policy_modifiers_detail=(), materiality_bucket=materiality_bucket,
        mechanism_id=mechanism_id, evidence_grade=evidence_grade,
        weakest_link=None, claim_bindings=tuple(dict(b) for b in claim_bindings),
        empirical_status=empirical_status,
        objections=tuple(dict(o) for o in objections),
        directness=directness, graph_distance=graph_distance,
        discovery_source=discovery_source, publication_tier=publication_tier,
        needs_reanalysis=False, rejection_reason=rejection_reason,
        gate_trace=(), decision_trace_id="fixture-trace",
        sensitivity=(band(delta_ebitda_pct_p50)
                     if delta_ebitda_pct_p50 is not None else None))


def impacts_from(fixture: Mapping[str, Any]) -> tuple[CompanyImpact, ...]:
    """Every company in a sections fixture, as canonical records."""
    return tuple(
        impact(company_id=int(row["company_id"]), ticker=str(row["ticker"]),
               publication_tier=str(row["publication_tier"]),
               net_effect=str(row["net_effect"]),
               mechanism_id=row["mechanism_id"],
               headline_horizon=str(row["horizon_bucket"]),
               delta_ebitda_pct_p50=row.get("delta_ebitda_pct_p50"),
               rejection_reason=row.get("rejection_reason"))
        for row in fixture["companies"])


def signal(kind: str, payload: Mapping[str, Any], *, stage: str,
           company_id: int = 6001, created_by: str = "fixture:stage",
           event_id: str = FIXTURE_EVENT_ID,
           analysis_version: str = FIXTURE_ANALYSIS_VERSION,
           created_at=FIXTURE_NOW):
    return make_signal(
        event_id=event_id, company_id=company_id, stage=stage, kind=kind,
        payload=dict(payload), created_by=created_by,
        analysis_version=analysis_version, created_at=created_at)
