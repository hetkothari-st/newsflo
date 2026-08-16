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
"""
from dataclasses import dataclass
from datetime import date, datetime
from typing import Mapping, Sequence

from sqlalchemy import text

from app.analysis.sensitivity.channels import (
    CHANNEL_FOR_KIND, ChannelResult, ExposureView, REQUIRED_PARAMS, Shock,
    compute_channel, NEAR_TERM,
)
from app.analysis.sensitivity.config import MaterialityConfig, load_materiality_config
from app.analysis.sensitivity.monte_carlo import (
    ENGINE_VERSION, MaterialityResult, serialize_materiality, simulate,
)
from app.analysis.sensitivity.params import (
    InsufficientParameterData, ParameterNameError, resolve_param,
)
from app.core.signals import Signal, make_signal
from app.ledger.channels import ledger_exposures
from app.ledger.staleness import company_exposure_is_stale

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
    uncomputable_channels: tuple[str, ...]
    zero_delta_channels: tuple[str, ...]
    exposure_stale: bool
    signals: tuple[Signal, ...]


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


def analyse_company(session, *, company_id: int, shocks: Sequence[Shock],
                    event_id: str, analysis_version: str, created_at: datetime,
                    as_of: date, horizon: str = NEAR_TERM,
                    ebitda_ttm_inr: float | None = None,
                    segment_ownership_fractions: Mapping[str, float] | None = None,
                    config: MaterialityConfig | None = None,
                    created_by: str = CREATED_BY) -> SensitivityRun:
    """Size one company against one event's shocks. Emits nothing when it
    cannot compute -- abstention is the default, not the exception."""
    config = config or load_materiality_config()
    ownership = dict(segment_ownership_fractions or {})
    tags = sorted({str(shock.exposure_tag) for shock in shocks})

    stale = company_exposure_is_stale(session, int(company_id), as_of=as_of,
                                      exposure_tags=tags) if tags else False

    rows = ledger_exposures(session, company_id=int(company_id), as_of=as_of,
                            exposure_tags=tags) if tags else []
    by_tag: dict[str, list[dict]] = {}
    for row in rows:
        by_tag.setdefault(str(row["exposure_tag"]), []).append(row)

    channels: list[ChannelResult] = []
    uncomputable: list[str] = []
    zero_delta: list[str] = []

    for shock in sorted(shocks, key=lambda s: (s.exposure_tag, s.shock_id)):
        for row in by_tag.get(str(shock.exposure_tag), []):
            kind = str(row["exposure_kind"])
            channel_type = CHANNEL_FOR_KIND.get(kind)
            if channel_type is None:
                # A real exposure with no §5.1 formula. Recorded, not sized.
                uncomputable.append(str(row["exposure_tag"]))
                continue

            exposure_id = str(row["exposure_id"])
            exposure = ExposureView(
                exposure_id=exposure_id, company_id=int(company_id),
                exposure_kind=kind, exposure_tag=str(row["exposure_tag"]),
                base_value_inr=float(row["base_value_inr"]),
                share_of_base=float(row["share_of_base"]),
                # A company's OWN exposure row: it owns all of its own P&L
                # line. An exposure attached from another entity arrives with
                # its fraction supplied by Phase 1's attachment rules, which
                # refuse to attach at all when the fraction is unknown.
                segment_ownership_fraction=float(ownership.get(exposure_id, 1.0)),
                evidence_ids=(exposure_id,))
            try:
                params = _resolve_params(
                    session, company_id=int(company_id),
                    tag=exposure.exposure_tag, channel_type=channel_type,
                    horizon_days=shock.horizon_days, as_of=as_of, config=config)
                channel = compute_channel(exposure, shock, params,
                                          shock.horizon_days, horizon=horizon,
                                          config=config)
            except InsufficientParameterData:
                uncomputable.append(str(row["exposure_tag"]))
                continue
            channels.append(ChannelResult(
                **{**channel.__dict__, "exposure_stale": stale}))

    base = ebitda_ttm_inr if ebitda_ttm_inr is not None else ebitda_ttm(
        session, int(company_id))

    if not channels or not base:
        return SensitivityRun(
            company_id=int(company_id), channels=tuple(channels), materiality=None,
            uncomputable_channels=tuple(dict.fromkeys(uncomputable)),
            zero_delta_channels=(), exposure_stale=bool(stale), signals=())

    materiality = simulate(
        channels, ebitda_ttm_inr=base, event_id=event_id, company_id=company_id,
        analysis_version=analysis_version,
        uncomputable_channels=tuple(dict.fromkeys(uncomputable)), config=config)
    block = serialize_materiality(materiality, config)

    signals: list[Signal] = []
    for channel in channels:
        channel_pct = channel.delta_ebitda_inr / float(base) * 100.0
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
                "exposure_stale": bool(stale),
                "sensitivity": block,
            }, created_by=created_by, analysis_version=analysis_version,
            created_at=created_at))

    return SensitivityRun(
        company_id=int(company_id), channels=tuple(channels),
        materiality=materiality,
        uncomputable_channels=tuple(dict.fromkeys(uncomputable)),
        zero_delta_channels=tuple(zero_delta), exposure_stale=bool(stale),
        signals=tuple(signals))
