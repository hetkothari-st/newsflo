"""The ledger -> channels -> signals orchestration, and the one impure
module in this package (it reads the database; it writes nothing).

    exposures = non-stale company_exposure rows for the shock's tags
    for each: resolve the §5.1 parameters   -> channel, or UNCOMPUTABLE
    channels + EBITDA_ttm -> Monte Carlo    -> MaterialityResult
    each channel                            -> one CHANNEL signal

NO EXPOSURE ROW, NO CHANNEL -- Phase 1's structural statement, unchanged.
NO PARAMETER, NO CHANNEL -- Phase 2's addition. Neither is a judgement call
at runtime; both are the absence of a row.

STALENESS (controller addendum). `app/ledger/channels.ledger_exposures`
already filters stale rows out defensively, so a stale row cannot back a
channel. That silence is not enough on its own: a company whose ONLY
exposure is stale would then look like a company with no exposure, and the
gate would reject it as NO_MATERIAL_IMPACT rather than as EXPOSURE_STALE.
So this module also ASKS -- `company_exposure_is_stale` over the same tags --
and reports the answer twice: on `SensitivityRun.exposure_stale`, which the
caller threads into `EventContext`, and on every CHANNEL payload, so the
reducer hard-blocks even if a caller forgets. Two lines of defence, both
tested.

CLOCK-FREE. `as_of` is the caller's; staleness and every ledger read are
evaluated against it, so a run is reproducible.

V5 PHASE 4 adds two things to this module and changes nothing else.

  * POLICY MODIFIERS run between channel computation and the Monte Carlo --
    the position Task 4.2 requires ("after channel computation and before
    net-effect resolution"). With no registry configured the transform is the
    identity, which is what every Phase 2 test exercises;
  * `analyse_company_horizons` runs the SAME per-company analysis three
    times, once per horizon, sampling every curve at that horizon's day count.
    The three runs are independent by construction: they share no state, and
    each emits its own CHANNEL signals carrying its own horizon label.
"""
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Mapping, Sequence

import logging

from sqlalchemy import text

from app.analysis.policy.registry import PolicyRegistry, registry_from_db
from app.analysis.policy.state import PolicyStateStore, state_store_from_db
from app.analysis.policy.transforms import ModifiedChannels, apply_modifiers
from app.analysis.sensitivity.channels import (
    CHANNEL_FOR_KIND, ChannelResult, ExposureView, OWNERSHIP_SELF_CONSOLIDATED,
    OWNERSHIP_SUPPLIED, REQUIRED_PARAMS, Shock, UncomputableChannel,
    compute_channel, NEAR_TERM,
)
from app.analysis.sensitivity.config import MaterialityConfig, load_materiality_config
from app.analysis.sensitivity.horizons import (
    HORIZON_ORDER, HorizonConfig, load_horizon_config,
)
from app.analysis.sensitivity.monte_carlo import (
    ENGINE_VERSION, MaterialityResult, serialize_materiality, simulate,
)
from app.analysis.sensitivity.params import (
    InsufficientParameterData, ParameterNameError, REASON_MISSING_OWNERSHIP,
    REASON_MISSING_ROW, REASON_NO_FORMULA, resolve_param,
)
from app.core.signals import Signal, make_signal
from app.ledger.channels import ledger_exposures
from app.ledger.staleness import company_exposure_is_stale

logger = logging.getLogger(__name__)

STAGE = "SENSITIVITY"
CREATED_BY = f"sensitivity:{ENGINE_VERSION}"

# The signal bus's channel materiality vocabulary has no NO_MATERIAL_IMPACT;
# it spells that NONE.
_BUCKET_TO_SIGNAL = {"HIGH": "HIGH", "MEDIUM": "MEDIUM", "LOW": "LOW",
                     "NO_MATERIAL_IMPACT": "NONE"}


@dataclass(frozen=True)
class SensitivityRun:
    company_id: int
    channels: tuple[ChannelResult, ...]
    materiality: MaterialityResult | None
    uncomputable_channels: tuple[UncomputableChannel, ...]
    zero_delta_channels: tuple[str, ...]
    exposure_stale: bool
    signals: tuple[Signal, ...]
    # --- V5 PHASE 4 -------------------------------------------------------
    horizon: str = NEAR_TERM
    policy_modifiers_applied: tuple[str, ...] = ()
    policy_modifiers_unknown_state: tuple[str, ...] = ()
    policy_modifiers_unresolved: tuple[str, ...] = ()
    policy_state_stale: bool = False
    stale_policy_state_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class HorizonRun:
    """One company, one event, THREE independent analyses.

    `signals` is every horizon's CHANNEL signals together, which is what the
    reducer folds into `direction_by_horizon`. `by_horizon` keeps each run
    whole so a caller can ask what happened at one horizon without
    reconstructing it from signals.
    """
    company_id: int
    by_horizon: Mapping[str, SensitivityRun]
    signals: tuple[Signal, ...]

    @property
    def exposure_stale(self) -> bool:
        return any(run.exposure_stale for run in self.by_horizon.values())

    @property
    def policy_state_stale(self) -> bool:
        return any(run.policy_state_stale for run in self.by_horizon.values())


def ebitda_ttm(session, company_id: int) -> float | None:
    """The most recently sourced EBITDA for this company, or None. NEVER a
    substitute: with no EBITDA there is no denominator and nothing is
    published."""
    value = session.execute(text(
        "SELECT ebitda_inr FROM company_financials "
        "WHERE company_id = :company_id AND ebitda_inr IS NOT NULL "
        "ORDER BY as_of_date DESC, fiscal_period DESC LIMIT 1"),
        {"company_id": int(company_id)}).scalar()
    return None if value is None else float(value)


def _resolve_params(session, *, company_id: int, tag: str, channel_type: str,
                    horizon_days: int, as_of: date, config: MaterialityConfig):
    resolved = {}
    for name in REQUIRED_PARAMS[channel_type]:
        try:
            resolved[name] = resolve_param(
                session, company_id=company_id, tag=tag, param_name=name,
                horizon_days=horizon_days, as_of=as_of, config=config).dist
        except ParameterNameError:                     # pragma: no cover
            raise
    return resolved


def channel_signals(channels: Sequence[ChannelResult], *,
                    materiality_block: Mapping[str, Any],
                    ebitda_ttm_inr: float, event_id: str, company_id: int,
                    analysis_version: str, created_at: datetime,
                    config: MaterialityConfig, exposure_stale: bool = False,
                    policy_state_stale: bool = False,
                    policy_modifiers: Sequence[Mapping[str, Any]] = (),
                    created_by: str = CREATED_BY) -> tuple[tuple[Signal, ...],
                                                           tuple[str, ...]]:
    """`(signals, zero_delta_channel_ids)` for one company at one horizon.

    Extracted from `analyse_company` in Phase 4 so the three-horizon runner
    and the pure-fixture tests emit signals through the SAME code the ledger
    path uses -- a payload built twice is a payload that will disagree with
    itself eventually.
    """
    signals: list[Signal] = []
    zero_delta: list[str] = []
    for channel in sorted(channels, key=lambda c: c.channel_id):
        channel_pct = channel.delta_ebitda_inr / float(ebitda_ttm_inr) * 100.0
        if channel.delta_ebitda_inr == 0.0:
            # A channel whose point estimate is exactly zero is not a
            # directional claim, so it is recorded and not published.
            zero_delta.append(channel.channel_id)
            continue
        signals.append(make_signal(
            event_id=event_id, company_id=int(company_id), stage=STAGE,
            kind="CHANNEL", payload={
                "channel_id": channel.channel_id,
                "mechanism_id": channel.mechanism_id,
                "horizon": channel.horizon,
                "direction": "NEGATIVE" if channel.delta_ebitda_inr < 0 else "POSITIVE",
                "materiality": _BUCKET_TO_SIGNAL[config.bucket_for(channel_pct)],
                "evidence_ids": list(channel.evidence_ids),
                "channel_type": channel.channel_type,
                "exposure_id": channel.exposure_id,
                "param_sources": dict(channel.param_sources),
                "delta_ebitda_pct_p50": round(channel_pct, 6),
                "exposure_stale": bool(exposure_stale),
                # V5 PHASE 4. The modifiers considered for this company, and
                # whether the regime state behind them is stale. Both travel
                # on EVERY channel so the reducer sees them even when a
                # caller forgets to thread the event context.
                "policy_modifiers": [dict(entry) for entry in policy_modifiers],
                "policy_state_stale": bool(policy_state_stale),
                "sensitivity": materiality_block,
            }, created_by=created_by, analysis_version=analysis_version,
            created_at=created_at))
    return tuple(signals), tuple(zero_delta)


def analyse_company(session, *, company_id: int, shocks: Sequence[Shock],
                    event_id: str, analysis_version: str, created_at: datetime,
                    as_of: date, horizon: str = NEAR_TERM,
                    horizon_days: int | None = None,
                    ebitda_ttm_inr: float | None = None,
                    segment_ownership_fractions: Mapping[str, float] | None = None,
                    config: MaterialityConfig | None = None,
                    policy_registry: PolicyRegistry | None = None,
                    policy_state: PolicyStateStore | None = None,
                    region_mix: Mapping[str, float] | None = None,
                    created_by: str = CREATED_BY) -> SensitivityRun:
    """Size one company against one event's shocks. Emits nothing when it
    cannot compute -- abstention is the default, not the exception.

    OWNERSHIP (fix round 1, I1). `segment_ownership_fractions` is
    exposure_id -> fraction, and there are exactly two ways to be sized:

      * the caller passes NO mapping. It thereby asserts that every exposure
        being sized is the company's own consolidated line, and each channel
        records `ownership_basis = SELF_CONSOLIDATED`. That is the normal
        case, it is a structural fact (a company owns all of its own P&L
        line), and it is now an explicit assertion in the record instead of a
        dictionary default;
      * the caller passes a mapping, in which case the mapping must be
        COMPLETE. An exposure it does not mention is not a company owning
        100% of the line -- it is an ownership fraction nobody supplied, so
        the channel is uncomputable with reason MISSING_OWNERSHIP.

    There is no persisted path from Phase 1's `attach_exposure_to_listco` to
    here (`company_exposure` has no ownership column), which is exactly why
    the silent default was dangerous. Recorded in DATA_GAPS.md §6.
    """
    config = config or load_materiality_config()
    # V5 PHASE 4: the registry and the state store come from the DATABASE
    # unless a caller supplies them, and both are EMPTY in production. An
    # empty registry is an identity transform -- "no modifier is registered",
    # never "no modifier applies".
    registry = (policy_registry if policy_registry is not None
                else registry_from_db(session))
    states = (policy_state if policy_state is not None
              else state_store_from_db(session))
    ownership = dict(segment_ownership_fractions or {})
    ownership_supplied = segment_ownership_fractions is not None
    tags = sorted({str(shock.exposure_tag) for shock in shocks})

    stale = company_exposure_is_stale(session, int(company_id), as_of=as_of,
                                      exposure_tags=tags) if tags else False

    rows = ledger_exposures(session, company_id=int(company_id), as_of=as_of,
                            exposure_tags=tags) if tags else []
    by_tag: dict[str, list[dict]] = {}
    for row in rows:
        by_tag.setdefault(str(row["exposure_tag"]), []).append(row)

    channels: list[ChannelResult] = []
    uncomputable: list[UncomputableChannel] = []
    zero_delta: list[str] = []

    for shock in sorted(shocks, key=lambda s: (s.exposure_tag, s.shock_id)):
        for row in by_tag.get(str(shock.exposure_tag), []):
            tag = str(row["exposure_tag"])
            kind = str(row["exposure_kind"])
            channel_type = CHANNEL_FOR_KIND.get(kind)
            if channel_type is None:
                # A real exposure with no §5.1 formula. Recorded, not sized.
                uncomputable.append(UncomputableChannel(tag, REASON_NO_FORMULA))
                continue

            exposure_id = str(row["exposure_id"])
            if ownership_supplied and exposure_id not in ownership:
                uncomputable.append(
                    UncomputableChannel(tag, REASON_MISSING_OWNERSHIP))
                continue

            exposure = ExposureView(
                exposure_id=exposure_id, company_id=int(company_id),
                exposure_kind=kind, exposure_tag=tag,
                base_value_inr=float(row["base_value_inr"]),
                share_of_base=float(row["share_of_base"]),
                segment_ownership_fraction=(float(ownership[exposure_id])
                                            if ownership_supplied else 1.0),
                evidence_ids=(exposure_id,),
                ownership_basis=(OWNERSHIP_SUPPLIED if ownership_supplied
                                 else OWNERSHIP_SELF_CONSOLIDATED))
            days = int(horizon_days if horizon_days is not None
                       else shock.horizon_days)
            try:
                params = _resolve_params(
                    session, company_id=int(company_id),
                    tag=exposure.exposure_tag, channel_type=channel_type,
                    horizon_days=days, as_of=as_of, config=config)
                channel = compute_channel(exposure, shock, params,
                                          days, horizon=horizon,
                                          config=config)
            except InsufficientParameterData as exc:
                uncomputable.append(UncomputableChannel(
                    tag, getattr(exc, "reason", REASON_MISSING_ROW),
                    getattr(exc, "param", None)))
                continue
            channels.append(ChannelResult(
                **{**channel.__dict__, "exposure_stale": stale}))

    uncomputable = list(dict.fromkeys(uncomputable))
    base = ebitda_ttm_inr if ebitda_ttm_inr is not None else ebitda_ttm(
        session, int(company_id))

    # --- V5 PHASE 4: modifiers, between the channels and the net effect ----
    modified: ModifiedChannels = apply_modifiers(
        tuple(channels), as_of_date=as_of, policy_state=states,
        registry=registry, region_mix=region_mix, config=config)
    channels = list(modified.channels)
    policy_state_stale = bool(modified.stale_state_keys)

    if not channels or not base:
        _log_abstention(company_id=int(company_id), event_id=event_id,
                        uncomputable=uncomputable, tags=tags,
                        no_ebitda=not base, stale=bool(stale))
        return SensitivityRun(
            company_id=int(company_id), channels=tuple(channels), materiality=None,
            uncomputable_channels=tuple(uncomputable),
            zero_delta_channels=(), exposure_stale=bool(stale), signals=(),
            horizon=horizon,
            policy_modifiers_applied=modified.applied,
            policy_modifiers_unknown_state=modified.unknown_state,
            policy_modifiers_unresolved=modified.unresolved,
            policy_state_stale=policy_state_stale,
            stale_policy_state_keys=modified.stale_state_keys)

    if uncomputable:
        _log_abstention(company_id=int(company_id), event_id=event_id,
                        uncomputable=uncomputable, tags=tags, no_ebitda=False,
                        stale=bool(stale), partial=True)

    materiality = simulate(
        channels, ebitda_ttm_inr=base, event_id=event_id, company_id=company_id,
        analysis_version=analysis_version,
        uncomputable_channels=tuple(uncomputable), config=config)
    block = serialize_materiality(materiality, config)

    signals, zero_delta_ids = channel_signals(
        channels, materiality_block=block, ebitda_ttm_inr=float(base),
        event_id=event_id, company_id=int(company_id),
        analysis_version=analysis_version, created_at=created_at, config=config,
        exposure_stale=bool(stale), policy_state_stale=policy_state_stale,
        policy_modifiers=modified.as_payload(), created_by=created_by)
    zero_delta = list(zero_delta_ids)

    return SensitivityRun(
        company_id=int(company_id), channels=tuple(channels),
        materiality=materiality,
        uncomputable_channels=tuple(uncomputable),
        zero_delta_channels=tuple(zero_delta), exposure_stale=bool(stale),
        signals=tuple(signals), horizon=horizon,
        policy_modifiers_applied=modified.applied,
        policy_modifiers_unknown_state=modified.unknown_state,
        policy_modifiers_unresolved=modified.unresolved,
        policy_state_stale=policy_state_stale,
        stale_policy_state_keys=modified.stale_state_keys)


def analyse_company_horizons(
        session, *, company_id: int, shocks: Sequence[Shock], event_id: str,
        analysis_version: str, created_at: datetime, as_of: date,
        ebitda_ttm_inr: float | None = None,
        segment_ownership_fractions: Mapping[str, float] | None = None,
        config: MaterialityConfig | None = None,
        horizon_config: HorizonConfig | None = None,
        policy_registry: PolicyRegistry | None = None,
        policy_state: PolicyStateStore | None = None,
        region_mix: Mapping[str, float] | None = None,
        created_by: str = CREATED_BY) -> HorizonRun:
    """TASK 4.3 -- the horizon vector.

    Three INDEPENDENT analyses, one per horizon, each sampling every
    pass-through / hedge / elasticity curve at its own day count, and each
    resolving policy state against its own horizon (a regime reading with a
    90-day freshness window is not evidence about day 270).

    All three are returned. None is ever discarded, and none is ever inferred
    from another -- which is the whole content of §8.
    """
    horizon_config = horizon_config or load_horizon_config()
    runs: dict[str, SensitivityRun] = {}
    signals: list[Signal] = []
    for horizon in HORIZON_ORDER:
        run = analyse_company(
            session, company_id=company_id, shocks=shocks, event_id=event_id,
            analysis_version=analysis_version, created_at=created_at, as_of=as_of,
            horizon=horizon, horizon_days=horizon_config.days[horizon],
            ebitda_ttm_inr=ebitda_ttm_inr,
            segment_ownership_fractions=segment_ownership_fractions,
            config=config, policy_registry=policy_registry,
            policy_state=policy_state, region_mix=region_mix,
            created_by=created_by)
        runs[horizon] = run
        signals.extend(run.signals)
    return HorizonRun(company_id=int(company_id), by_horizon=runs,
                      signals=tuple(signals))


def _log_abstention(*, company_id: int, event_id: str,
                    uncomputable: Sequence[UncomputableChannel],
                    tags: Sequence[str], no_ebitda: bool, stale: bool,
                    partial: bool = False) -> None:
    """A structured line per company (fix round 1, I3).

    A company that silently sizes nothing looks exactly like a company nobody
    considered. This is the difference, and it is the first thing an operator
    will grep when coverage looks wrong.
    """
    reasons = ";".join(sorted(
        f"{u.channel_id}={u.reason}" + (f"({u.param})" if u.param else "")
        for u in uncomputable)) or "NO_EXPOSURE_ROW"
    logger.warning(
        "[v5-sensitivity] %s company_id=%s event_id=%s tags=%s "
        "uncomputable=%s no_ebitda=%s exposure_stale=%s",
        "PARTIAL" if partial else "ABSTAINED", company_id, event_id,
        ",".join(tags) or "-", reasons, no_ebitda, stale)
