"""The ledger -> signal join. NO EXPOSURE ROW, NO CHANNEL.

This is the structural statement of Phase 1, and the thing the empty-ledger
test proves: a transmission channel may exist for a company only if a
reviewed, sourced, non-stale row in `company_exposure` says that company is
exposed to that tag. However confident the caller is, an empty ledger yields
an empty tuple, the reducer sees no channels, materiality resolves to
NO_MATERIAL_IMPACT and the publication gate rejects. The system says nothing
rather than guessing.

WHAT PHASE 1 DOES NOT OWN. Direction and materiality are the sensitivity
engine's answers (Phase 2, spec §5). They are passed IN, per tag, by the
caller. Phase 1 never computes, defaults or infers them: a tag with no
supplied sensitivity produces no channel, exactly like a tag with no
exposure row.

This module reads the ledger and builds `Signal`s. It writes nothing.
"""
from datetime import date, datetime
from typing import Mapping, Sequence

from sqlalchemy import text

from app.core.signals import Signal, make_signal

# The stage name these signals carry, so the signal bus records WHERE the
# channel came from.
STAGE = "exposure_ledger"
LEDGER_VERSION = "ledger-v5.1.0"


def ledger_exposures(session, *, company_id: int, as_of: date,
                     exposure_tags: Sequence[str] | None = None) -> list[dict]:
    """Every non-stale exposure row for a company, oldest tag first.

    Staleness is evaluated from the dates rather than the stored flag, so the
    answer does not depend on whether the nightly job has run."""
    sql = ("SELECT * FROM company_exposure "
           "WHERE company_id = :company_id "
           "  AND julianday(:as_of) - julianday(as_of_date) <= freshness_days")
    parameters: dict = {"company_id": int(company_id), "as_of": as_of.isoformat()}
    if exposure_tags is not None:
        tags = tuple(exposure_tags)
        if not tags:
            return []
        placeholders = ", ".join(f":tag{i}" for i in range(len(tags)))
        sql += f" AND exposure_tag IN ({placeholders})"
        parameters.update({f"tag{i}": tag for i, tag in enumerate(tags)})
    sql += " ORDER BY exposure_tag ASC, exposure_id ASC"
    return [dict(row) for row in session.execute(text(sql), parameters).mappings().all()]


def channel_signals_from_ledger(
        session, *, company_id: int, event_id: str, analysis_version: str,
        created_at: datetime, as_of: date,
        sensitivity: Mapping[str, tuple[str, str]],
        mechanism_id_by_tag: Mapping[str, str] | None = None,
        created_by: str = f"ledger:{LEDGER_VERSION}") -> tuple[Signal, ...]:
    """One CHANNEL signal per (exposure row x supplied sensitivity).

    `sensitivity` maps exposure_tag -> (direction, materiality), both from
    the sensitivity engine. A tag present in `sensitivity` but absent from
    the ledger yields NOTHING: the ledger is what authorises a channel.
    """
    mechanism_id_by_tag = mechanism_id_by_tag or {}
    exposures = ledger_exposures(session, company_id=company_id, as_of=as_of,
                                 exposure_tags=tuple(sensitivity) or None)
    signals: list[Signal] = []
    for exposure in exposures:
        tag = str(exposure["exposure_tag"])
        supplied = sensitivity.get(tag)
        if not supplied:
            # An exposure we cannot yet size is an exposure, not a claim.
            continue
        direction, materiality = supplied
        signals.append(make_signal(
            event_id=event_id, company_id=int(company_id), stage=STAGE,
            kind="CHANNEL",
            payload={
                "channel_id": tag,
                "mechanism_id": mechanism_id_by_tag.get(tag),
                "horizon": "NEAR_TERM",
                "direction": direction,
                "materiality": materiality,
                # The exposure row that authorises this channel, so the
                # canonical record traces back to a filing page.
                "evidence_ids": [str(exposure["exposure_id"])],
            },
            created_by=created_by, analysis_version=analysis_version,
            created_at=created_at))
    return tuple(signals)
