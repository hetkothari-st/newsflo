"""Shared Phase 5 case construction.

Two things live here:

  * `SyntheticHistory` -- the `ReturnHistory` protocol satisfied by
    arithmetic. Real price history for the listed universe over 8+ years does
    not exist in this repo and acquiring it is the owner's act (DATA_GAPS §9).
    Everything about the ESTIMATOR that can be tested without it is tested on
    returns a test wrote;
  * `impact_with` -- one canonical record through the REAL reducer and the
    REAL deployed gate, so a tier assertion is an assertion about the shipped
    policy rather than about a mock.

No production module may import this file -- asserted by
`test_no_fixture_data_reaches_production.py`.
"""
from datetime import date

from tests.phase5.conftest import (
    FIXTURE_ANALYSIS_VERSION, FIXTURE_BENCHMARK, FIXTURE_COMPANY_ID,
    FIXTURE_EVENT_ID, FIXTURE_NOW, FIXTURE_TICKER, load_fixture,
)


# --- the ReturnHistory protocol, satisfied by arithmetic --------------------

class SyntheticHistory:
    """Observations keyed by trading-day offset from the event day.

    The estimator asks for offsets, not calendar ranges, because only the
    supplier knows the exchange calendar. A missing offset is MISSING -- this
    class never invents one, and never returns a zero for it.
    """

    def __init__(self, company: dict, benchmark: dict, *,
                 benchmark_id: str = FIXTURE_BENCHMARK,
                 company_id: int = FIXTURE_COMPANY_ID):
        self._company = dict(company)          # {offset: DailyObservation}
        self._benchmark = dict(benchmark)
        self._benchmark_id = benchmark_id
        self._company_id = company_id

    def window(self, company_id, event_day, from_offset, to_offset):
        if company_id != self._company_id:
            return ()
        return tuple(self._company[o] for o in range(from_offset, to_offset + 1)
                     if o in self._company)

    def benchmark_window(self, benchmark_id, event_day, from_offset, to_offset):
        if benchmark_id != self._benchmark_id:
            return ()
        return tuple(self._benchmark[o] for o in range(from_offset, to_offset + 1)
                     if o in self._benchmark)

    def benchmark_for(self, company_id):
        return self._benchmark_id if company_id == self._company_id else None


def hand_computed_history(*, thin: bool = False, corporate_action_offset=None,
                          circuit_offset=None, not_listed: bool = False,
                          estimation_gap_offset=None,
                          stale_print_offsets=()):
    """The hand-computed fixture as a `SyntheticHistory`.

    Estimation window: offsets -250..-31, benchmark cycling through
    {-0.4%, -0.2%, 0, +0.2%, +0.4%} and company = 0.1% + 1.5 x benchmark
    EXACTLY, so OLS recovers alpha=0.001 and beta=1.5 on the nose.
    Event window: the six observations in the fixture, then a quiet tail.

    THE STALE-PRINT SHAPE (review round 1, I-2). A day that did not trade
    carries the previous close forward, so a real feed reports it as
    `traded=False` with a perfectly well-formed `return_pct = 0.0` -- NOT as a
    missing return. That is the shape that would sum as a genuine zero
    abnormal return if the estimator only checked for None, so it is the shape
    the fixtures must be able to produce:

      * `thin=True` makes every other ESTIMATION day a stale print;
      * `stale_print_offsets=(2,)` makes an EVENT-window day one.
    """
    from app.analysis.empirical.event_study import DailyObservation

    fixture = load_fixture("car_hand_computed.json")
    alpha = fixture["estimation"]["alpha"]
    beta = fixture["estimation"]["beta"]
    cycle = fixture["estimation"]["benchmark_cycle"]

    company: dict[int, object] = {}
    benchmark: dict[int, object] = {}

    def day_of(offset: int) -> date:
        return date(2226, 3, 3)          # calendar day is not what indexes here

    for index, offset in enumerate(range(-250, -30)):
        b = cycle[index % len(cycle)]
        r = alpha + beta * b
        traded = True
        if thin and index % 2 == 0:
            # Every other session is a STALE PRINT: no trade, and the feed
            # reports a well-formed 0.0 return rather than a missing one. Only
            # the `traded` flag distinguishes it from a genuine flat day, which
            # is exactly what the estimator has to honour.
            traded = False
        benchmark[offset] = DailyObservation(day=day_of(offset), offset=offset,
                                             return_pct=b)
        company[offset] = DailyObservation(
            day=day_of(offset), offset=offset,
            return_pct=(0.0 if not traded else r), traded=traded,
            corporate_action=("SPLIT" if offset == estimation_gap_offset else None))
        if offset == estimation_gap_offset:
            company[offset] = DailyObservation(
                day=day_of(offset), offset=offset, return_pct=None, traded=True,
                corporate_action="SPLIT")
        if not_listed:
            company[offset] = DailyObservation(
                day=day_of(offset), offset=offset, return_pct=None, traded=False)

    for entry in fixture["event_window"]["observations"]:
        offset = int(entry["offset"])
        benchmark[offset] = DailyObservation(day=day_of(offset), offset=offset,
                                             return_pct=entry["benchmark"])
        stale = offset in tuple(stale_print_offsets)
        company[offset] = DailyObservation(
            day=day_of(offset), offset=offset,
            return_pct=(None if offset == corporate_action_offset
                        else 0.0 if stale else entry["company"]),
            traded=not stale,
            circuit=("UPPER" if offset == circuit_offset else None),
            corporate_action=("SPLIT" if offset == corporate_action_offset else None))

    for offset in range(6, 21):
        b = cycle[offset % len(cycle)]
        benchmark[offset] = DailyObservation(day=day_of(offset), offset=offset,
                                             return_pct=b)
        company[offset] = DailyObservation(day=day_of(offset), offset=offset,
                                           return_pct=alpha + beta * b)
    return SyntheticHistory(company, benchmark)


def levels_from_moves(moves, *, start: date = date(2218, 1, 1),
                      level: float = 100.0):
    """[(day, level)] whose consecutive simple returns are `moves`."""
    from datetime import timedelta

    series = [(start, level)]
    for index, move in enumerate(moves, 1):
        level = level * (1.0 + move)
        series.append((start + timedelta(days=index), level))
    return tuple(series)


def tiny_policy(**overrides):
    """The DEPLOYED empirical policy with named fields replaced.

    A test that shortens the minimum series span says so out loud here rather
    than carrying its own copy of every threshold the product ships.
    """
    import dataclasses

    from app.analysis.empirical.config import load_empirical_config

    return dataclasses.replace(load_empirical_config(), **overrides)


# --- the publication gate ---------------------------------------------------

def clean_primary_draft(**overrides):
    """An `ImpactDraft` that clears every PRIMARY rule the DEPLOYED policy
    states. Tests break exactly one field of it at a time."""
    from app.core.gates import ImpactDraft

    fields = dict(
        entity_status="ACTIVE", entity_ambiguous=False, exposure_stale=False,
        materiality_bucket="HIGH", graph_distance=1, directness="DIRECT",
        evidence_grade="A", weakest_link="COST_EXPOSURE:BOUND",
        sign_consistency=1.0, empirical_status="AGREE", objections=(),
        unbound_claim_ids=(), verifier_status="PASS", adv_20d_inr=None,
        event_status="CONFIRMED", shock_magnitude_confidence=0.9,
        mechanism_id="fixture:mechanism:1", net_effect="POSITIVE",
        delta_ebitda_pct_abs=10.0, uses_sector_proxy=False,
        policy_state_stale=False)
    fields.update(overrides)
    return ImpactDraft(**fields)


# --- the canonical record ---------------------------------------------------

def base_signals(*, direction: str = "POSITIVE", materiality: str = "HIGH",
                 company_id: int = FIXTURE_COMPANY_ID):
    """Entity + discovery + one channel + evidence + a passing verifier.

    No computed band: Phase 5 is not testing the sensitivity engine, it is
    testing what the EMPIRICAL status does to a record that would otherwise
    publish PRIMARY.
    """
    from app.core.signals import make_signal

    def emit(stage, kind, payload, created_by="human:fixture"):
        return make_signal(
            event_id=FIXTURE_EVENT_ID, company_id=company_id, stage=stage,
            kind=kind, payload={**payload, "_fixture": True},
            created_by=created_by, analysis_version=FIXTURE_ANALYSIS_VERSION,
            created_at=FIXTURE_NOW)

    return [
        emit("ENTITY", "ENTITY_RESOLUTION",
             {"ticker": FIXTURE_TICKER, "isin": None, "resolution": "RESOLVED",
              "entity_status": "ACTIVE"}),
        emit("DISCOVERY", "DISCOVERY",
             {"discovery_source": "MECHANISM", "directness": "DIRECT",
              "graph_distance": 1}),
        emit("SENSITIVITY", "CHANNEL",
             {"channel_id": "fixture_channel", "mechanism_id": "fixture:mechanism:1",
              "horizon": "NEAR_TERM", "direction": direction,
              "materiality": materiality, "evidence_ids": ["fixture-ev-1"]}),
        emit("CLAIMS", "EVIDENCE_BINDING",
             {"claim_id": "fixture-claim-1", "claim_type": "REVENUE_EXPOSURE",
              "binding_status": "BOUND", "evidence_grade": "A",
              "evidence_ids": ["fixture-ev-1"]}),
        emit("VERIFIER", "OBJECTION",
             {"objection_id": "fixture:verification", "type": "NOT_INDEPENDENTLY_VERIFIED",
              "severity": "MAJOR", "sustained": False}),
    ]


def reduce_with(signals):
    """The REAL reducer over the DEPLOYED gate policy."""
    from app.core.config_loader import load_reducer_config
    from app.core.reducer import EventContext, reduce_company_impact
    import dataclasses

    config = load_reducer_config()
    config = dataclasses.replace(config, event_context=EventContext(
        event_status="CONFIRMED", shock_magnitude_confidence=0.9))
    return reduce_company_impact(signals, config)


def impact_with_empirical(assessment=None, *, direction: str = "POSITIVE",
                          extra_signals=()):
    """The canonical record for the fixture company, with the empirical
    signals a real assessment would emit."""
    from app.analysis.empirical.check import signals_from_assessment

    signals = base_signals(direction=direction)
    if assessment is not None:
        signals.extend(signals_from_assessment(
            assessment, event_id=FIXTURE_EVENT_ID, company_id=FIXTURE_COMPANY_ID,
            analysis_version=FIXTURE_ANALYSIS_VERSION, created_at=FIXTURE_NOW))
    else:
        from app.core.signals import make_signal
        signals.append(make_signal(
            event_id=FIXTURE_EVENT_ID, company_id=FIXTURE_COMPANY_ID,
            stage="EMPIRICAL", kind="EMPIRICAL_CHECK",
            payload={"status": "NO_DATA", "n_events": None, "_fixture": True},
            created_by="empirical:not_available",
            analysis_version=FIXTURE_ANALYSIS_VERSION, created_at=FIXTURE_NOW))
    signals.extend(extra_signals)
    return reduce_with(signals)


def transmission_row(*, n_events: int = 34, median_car: float = -0.014,
                     p_value: float = 0.02, sign_consistency: float = 0.79,
                     iqr_lo: float = -0.032, iqr_hi: float = 0.001,
                     horizon: str = "5d", shock_sign: str = "UP",
                     variable: str = "fixture_variable"):
    """A `transmission_empirical` row of invented statistics."""
    from app.analysis.empirical.event_study import TransmissionRow

    return TransmissionRow(
        company_id=FIXTURE_COMPANY_ID, shock_variable=variable,
        shock_sign=shock_sign, horizon=horizon, n_events=n_events,
        median_car=median_car, iqr_lo=iqr_lo, iqr_hi=iqr_hi, p_value=p_value,
        sign_consistency=sign_consistency)
