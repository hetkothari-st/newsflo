"""V5 PHASE 6 / spec §12.3 -- REBUTTALS.

    An objection is `sustained` unless a rebuttal signal exists that cites a
    specific record field or evidence id. Rebuttals are produced by the
    sensitivity/evidence stages, not by the falsifier itself, and not by
    free-form argument. Default is that the objection stands.

This module is where those stages answer. It lives OUTSIDE
`app/analysis/falsifier/` on purpose: the adversary must not be able to
answer itself, and the cleanest way to guarantee that is for the answering
code to be somewhere the adversary does not reach (ast-asserted by
`tests/phase6/test_falsifier.py`). The reducer independently discards any
rebuttal whose stage is the stage that raised the objection, so the rule
holds even if a future caller wires this badly.

EVERY RULE BELOW CITES A DATUM THE STAGE ALREADY HOLDS. Not one of them
computes, infers or supplies anything:

  OFFSET_IGNORED          <- SENSITIVITY holds the channel list, so it can
                             name the offsetting channel_id (or find none).
  REGIME_MODIFIER_MISSING <- SENSITIVITY holds the policy modifiers that
                             were APPLIED, so it can name the modifier_id.
  EXPOSURE_NOT_IN_LISTCO  <- SENSITIVITY holds the ledger exposure_id behind
                             each channel, and a ledger row is a reviewed
                             claim about the LISTED entity.
  EVIDENCE_STALE          <- EVIDENCE holds the claim bindings, so it can
                             name a BOUND claim's evidence id.

An objection type with no rule here is never rebutted automatically, and
that is the correct default rather than a gap: ENTITY_WRONG,
MECHANISM_INVALID, MAGNITUDE_IMMATERIAL, HORIZON_MISMATCH, ALREADY_PRICED,
BASE_RATE_VIOLATION and SECOND_ORDER_OVERREACH all stand until somebody can
point at the record field that answers them.

PURE. No I/O, no clock (the caller supplies `created_at`), no LLM.
"""
from typing import Any, Callable, Mapping, Sequence

# stage -> the stage name written on the emitted signal. The reducer compares
# this against the OBJECTION's stage, which is what makes self-rebuttal
# structurally impossible rather than merely discouraged.
STAGE_SENSITIVITY = "SENSITIVITY"
STAGE_EVIDENCE = "EVIDENCE"

OPPOSITE = {"POSITIVE": "NEGATIVE", "NEGATIVE": "POSITIVE"}


def _channels(record: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
    return (record.get("fundamental") or {}).get("channels") or ()


def _claim_bindings(record: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
    return (record.get("evidence") or {}).get("claim_bindings") or ()


def _net_effect(record: Mapping[str, Any]) -> str | None:
    value = (record.get("fundamental") or {}).get("net_effect")
    return str(value) if value else None


def _rebut_offset_ignored(record: Mapping[str, Any]) -> tuple[str, str] | None:
    """A material channel pointing the OTHER WAY is the offset the objection
    says was ignored. Deterministic pick: the first by channel_id, so a
    replay cites the same channel."""
    directions = {str(c.get("direction")) for c in _channels(record)
                  if c.get("material")}
    if not directions & set(OPPOSITE):
        return None
    # Both signs present => an offset exists and can be named.
    if len(directions & set(OPPOSITE)) < 2:
        return None
    opposing = sorted(
        (str(c.get("channel_id")) for c in _channels(record)
         if c.get("material") and str(c.get("direction")) == "POSITIVE"))
    if not opposing:                                    # pragma: no cover
        return None
    return STAGE_SENSITIVITY, f"fundamental.channels[{opposing[0]}].direction"


def _rebut_regime_modifier_missing(record: Mapping[str, Any]) -> tuple[str, str] | None:
    """A policy modifier that was APPLIED is the regime the objection says is
    missing from the model."""
    applied = sorted(str(m) for m in
                     (record.get("fundamental") or {}).get("policy_modifiers_applied") or ())
    if not applied:
        return None
    return STAGE_SENSITIVITY, f"fundamental.policy_modifiers_applied[{applied[0]}]"


def _rebut_exposure_not_in_listco(record: Mapping[str, Any]) -> tuple[str, str] | None:
    """A ledger `exposure_id` behind a material channel is a REVIEWED claim
    about the listed entity's own filing. A channel with no exposure row
    cannot rebut anything -- which is most channels today, and that is the
    honest answer while the ledger is empty."""
    sourced = sorted(str(c["exposure_id"]) for c in _channels(record)
                     if c.get("material") and c.get("exposure_id"))
    if not sourced:
        return None
    return STAGE_SENSITIVITY, f"fundamental.channels.exposure_id[{sourced[0]}]"


def _rebut_evidence_stale(record: Mapping[str, Any]) -> tuple[str, str] | None:
    """A BOUND claim's evidence id. SECTOR_PROXY and UNBOUND bindings cannot
    rebut a staleness objection: the first is not about this company and the
    second is not evidence at all."""
    bound = sorted(
        str(evidence_id)
        for binding in _claim_bindings(record)
        if str(binding.get("binding_status")) == "BOUND"
        for evidence_id in (binding.get("evidence_ids") or ()))
    if not bound:
        return None
    return STAGE_EVIDENCE, bound[0]


# objection type -> (rule, whether the citation is an EVIDENCE id)
_RULES: Mapping[str, tuple[Callable[[Mapping[str, Any]], Any], bool]] = {
    "OFFSET_IGNORED": (_rebut_offset_ignored, False),
    "REGIME_MODIFIER_MISSING": (_rebut_regime_modifier_missing, False),
    "EXPOSURE_NOT_IN_LISTCO": (_rebut_exposure_not_in_listco, False),
    "EVIDENCE_STALE": (_rebut_evidence_stale, True),
}


def rebuttals_for(objections: Sequence[Mapping[str, Any]],
                  record: Mapping[str, Any], *, event_id: str,
                  company_id: int | None, analysis_version: str,
                  created_at) -> tuple:
    """The REBUTTAL signals this record can honestly support.

    Returns `()` when it can support none, which is the common case and the
    correct one: nothing here manufactures a citation to clear an objection.
    """
    from app.core.signals import make_signal

    out = []
    for objection in sorted(objections, key=lambda o: str(o.get("objection_id"))):
        rule = _RULES.get(str(objection.get("type")))
        if rule is None:
            continue
        finder, cites_evidence = rule
        found = finder(record)
        if found is None:
            continue
        stage, citation = found
        objection_id = str(objection["objection_id"])
        payload = {
            "rebuttal_id": f"rebuttal:{stage.lower()}:{objection_id}",
            "objection_id": objection_id,
            "cites_evidence_id": citation if cites_evidence else None,
            "cites_record_field": None if cites_evidence else citation,
        }
        out.append(make_signal(
            event_id=event_id, company_id=company_id, stage=stage,
            kind="REBUTTAL", payload=payload,
            created_by=f"{stage.lower()}:rebuttal",
            analysis_version=analysis_version, created_at=created_at))
    return tuple(out)
