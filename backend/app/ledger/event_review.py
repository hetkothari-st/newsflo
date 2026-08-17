"""TASK 6.3 -- the review console's DATA LAYER.

Everything the per-event view shows, read out of the V5 tables and returned
as plain dicts. Kept out of the page module for the same reason Phase 1 kept
`review.py` out of the console and Phase 3 kept `edge_review.py` out of
`edge_review_pages.py`: the pages are presentation, this is the query set.

WHAT THIS MODULE MAY DO: read `company_impact`, `signal`, `evidence_records`,
`articles`, `alerts`, and write ONE thing -- a human's label in the Gate Zero
eval corpus (`eval_label`, and `eval_event` when the labeler names a
stratum). That is the console's only write path.

WHAT IT MAY NOT DO, and structurally cannot: write a canonical record. The
reducer is the only writer (invariant 1) and nothing here opens a
`reducer_session`, so the database refuses this connection anyway --
`tests/phase6/test_review_console.py` proves both halves.

THE REJECTED SET IS FIRST-CLASS. `event_detail` returns it as its own key,
with the reason and the failed gate rules, because invariant 12 says
rejected candidates are retained with a reason and visible in the review
console -- and because rejection visibility is the clearest signal to a
professional user that the system has judgement rather than enthusiasm
(§15).
"""
from typing import Any, Mapping, Sequence

import json

import sqlalchemy as sa

from app.output.section_config import load_section_taxonomy
from app.output.sections import (
    build_sections, render_zero_primary, serialize_sections, zero_primary_state,
)

#: TASK 6.3's one-click label vocabulary, verbatim. Stored in
#: `eval_label.label` (Session 0's schema is NOT modified by this phase) --
#: a free-text column whose contents this tuple closes.
REVIEW_LABELS = (
    "CORRECT", "WRONG_COMPANY", "WRONG_DIRECTION", "WRONG_MECHANISM",
    "WRONG_MATERIALITY", "WRONG_TIER", "WRONG_SECTION", "INSUFFICIENT_EVIDENCE",
    "DISPUTED",
)

DISPLAY_TIERS = ("PRIMARY", "SECONDARY_RIPPLE", "MACRO_CONTEXT")
TIER_REJECTED = "REJECTED"


class EventReviewError(ValueError):
    """A label the console refuses to write."""


class _ImpactRow:
    """One `company_impact` row, wearing the attribute names the pure section
    engine reads. Deliberately a thin adapter rather than a second record
    type: the engine must see the same six fields whether they came from the
    reducer in memory or from the table."""

    __slots__ = ("row", "sensitivity")

    def __init__(self, row: Mapping[str, Any],
                 sensitivity: Mapping[str, Any] | None = None):
        self.row = row
        self.sensitivity = sensitivity

    def __getattr__(self, name: str) -> Any:
        try:
            return self.row[name]
        except KeyError as exc:                          # pragma: no cover
            raise AttributeError(name) from exc


def _loads(value: Any, fallback):
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, ValueError):                      # pragma: no cover
        return fallback


def article_id_for_event(event_id: str) -> int | None:
    """`article:6001` -> 6001. A V5 "event" is one analysis run of one
    article (`app.core.impact_writer.event_id_for_article`); an event id in
    any other shape has no article and says so."""
    prefix, separator, tail = str(event_id).partition(":")
    if prefix != "article" or not separator or not tail.isdigit():
        return None
    return int(tail)


def article_for_event(conn: sa.Connection, event_id: str) -> dict | None:
    article_id = article_id_for_event(event_id)
    if article_id is None:
        return None
    row = conn.execute(sa.text(
        "SELECT id, source, url, title, published_at FROM articles WHERE id = :id"),
        {"id": article_id}).mappings().first()
    return dict(row) if row else None


def impacts_for_event(conn: sa.Connection, event_id: str) -> list[dict]:
    rows = conn.execute(sa.text(
        "SELECT * FROM company_impact WHERE event_id = :event_id "
        "ORDER BY ticker, company_id"), {"event_id": event_id}).mappings()
    return [dict(row) for row in rows]


def signals_for_event(conn: sa.Connection, event_id: str) -> list[dict]:
    rows = conn.execute(sa.text(
        "SELECT signal_id, company_id, stage, kind, payload_json, created_by, "
        "created_at FROM signal WHERE event_id = :event_id "
        "ORDER BY company_id, kind, signal_id"),
        {"event_id": event_id}).mappings()
    out = []
    for row in rows:
        item = dict(row)
        item["payload"] = _loads(item.pop("payload_json"), {})
        out.append(item)
    return out


def evidence_for_event(conn: sa.Connection, event_id: str,
                       evidence_ids: Sequence[str]) -> dict[str, dict | None]:
    """Resolve the evidence ids a record cites to the STORED artefacts.

    An id with no artefact resolves to `None` and is reported as such. A
    broken evidence chain is exactly what this console exists to show; a
    console that silently dropped the unresolvable ones would make the chain
    look complete.
    """
    article_id = article_id_for_event(event_id)
    wanted = [str(value) for value in evidence_ids if str(value).strip()]
    resolved: dict[str, dict | None] = {value: None for value in wanted}
    numeric = [int(value) for value in wanted if value.lstrip("-").isdigit()]
    if article_id is None or not numeric:
        return resolved

    rows = conn.execute(sa.text(
        "SELECT e.id, e.company_id, e.source_type, e.source_name, e.source_url, "
        "e.source_date, e.evidence_class, e.evidence_tier, e.fact_text, "
        "e.quoted_text FROM evidence_records e JOIN alerts a ON a.id = e.event_id "
        "WHERE a.article_id = :article_id"), {"article_id": article_id}).mappings()
    by_id = {str(row["id"]): dict(row) for row in rows}
    for value in wanted:
        resolved[value] = by_id.get(value)
    return resolved


def _cited_evidence_ids(record: Mapping[str, Any]) -> list[str]:
    ids: list[str] = []
    for binding in _loads(record.get("claim_bindings_json"), []):
        ids.extend(str(value) for value in (binding.get("evidence_ids") or ()))
    for channel in _loads(record.get("channels_json"), []):
        ids.extend(str(value) for value in (channel.get("evidence_ids") or ()))
    return sorted(set(ids))


def _sensitivity_by_company(signals: Sequence[Mapping[str, Any]],
                            headline_by_company: Mapping[int, str]
                            ) -> dict[int, dict]:
    """The computed band, read off the CHANNEL signals.

    `company_impact` has no band column -- the record's `sensitivity` block
    is carried on the signals that produced it, and the signal log is
    append-only, so this is the auditable source rather than a convenient
    one.
    """
    out: dict[int, dict] = {}
    for signal in signals:
        if signal["kind"] != "CHANNEL":
            continue
        block = (signal["payload"] or {}).get("sensitivity")
        if not block:
            continue
        company_id = signal["company_id"]
        horizon = str((signal["payload"] or {}).get("horizon") or "NEAR_TERM")
        if horizon != headline_by_company.get(company_id):
            continue
        out.setdefault(company_id, dict(block))
    return out


def event_detail(conn: sa.Connection, event_id: str) -> dict:
    """Everything Task 6.3 requires on one event, in one dict."""
    taxonomy = load_section_taxonomy()
    records = impacts_for_event(conn, event_id)
    signals = signals_for_event(conn, event_id)
    headline_by_company = {r["company_id"]: r["headline_horizon"] for r in records}
    bands = _sensitivity_by_company(signals, headline_by_company)

    adapters = [_ImpactRow(record, bands.get(record["company_id"]))
                for record in records]
    sections = build_sections(adapters, taxonomy)
    state = zero_primary_state(adapters, sections)

    evidence_ids = sorted({value for record in records
                           for value in _cited_evidence_ids(record)})
    evidence = evidence_for_event(conn, event_id, evidence_ids)

    rebuttals = [s for s in signals if s["kind"] == "REBUTTAL"]
    objection_signals = [s for s in signals if s["kind"] == "OBJECTION"]
    empirical_signals = [s for s in signals if s["kind"] == "EMPIRICAL_CHECK"]

    by_tier: dict[str, list[dict]] = {tier: [] for tier in DISPLAY_TIERS}
    rejected: list[dict] = []
    for record, adapter in zip(records, adapters):
        view = _company_view(record, adapter, evidence, rebuttals)
        if record["publication_tier"] in by_tier:
            by_tier[record["publication_tier"]].append(view)
        else:
            rejected.append(view)

    return {
        "event_id": event_id,
        "article": article_for_event(conn, event_id),
        "shocks": _shocks(empirical_signals),
        "sections": serialize_sections(sections),
        "zero_primary": state,
        "zero_primary_text": (render_zero_primary(state, taxonomy)
                              if state["zero_primary"] else None),
        "by_tier": by_tier,
        "rejected": rejected,
        "evidence": evidence,
        "objection_signals": objection_signals,
        "counts": {
            "companies": len(records),
            "rejected": len(rejected),
            **{tier: len(rows) for tier, rows in by_tier.items()},
        },
    }


def _shocks(empirical_signals: Sequence[Mapping[str, Any]]) -> list[dict]:
    """The event's shock variables, as the EMPIRICAL stage recorded them.

    This repo has no `event` table and no shock table (DATA_GAPS §10): an
    event is one analysis run of one article, and the only place a shock
    variable is written down is the empirical cross-check's payload. When
    that stage has not run, the list is EMPTY and the page says so rather
    than inventing a shock.
    """
    seen: dict[tuple, dict] = {}
    for signal in empirical_signals:
        payload = signal["payload"] or {}
        variable = payload.get("shock_variable")
        if not variable:
            continue
        key = (str(variable), str(payload.get("shock_sign") or ""))
        seen.setdefault(key, {"shock_variable": key[0], "shock_sign": key[1],
                              "horizon": payload.get("horizon"),
                              "status": payload.get("status")})
    return [seen[key] for key in sorted(seen)]


def _company_view(record: Mapping[str, Any], adapter: _ImpactRow,
                  evidence: Mapping[str, Any],
                  rebuttals: Sequence[Mapping[str, Any]]) -> dict:
    objections = _loads(record.get("objections_json"), [])
    rebuttal_by_id = {str((s["payload"] or {}).get("rebuttal_id")): s
                      for s in rebuttals
                      if s["company_id"] == record["company_id"]}
    for objection in objections:
        objection["rebuttals"] = [
            {"rebuttal_id": rebuttal_id,
             "stage": (rebuttal_by_id[rebuttal_id]["stage"]
                       if rebuttal_id in rebuttal_by_id else None),
             "cites_record_field": ((rebuttal_by_id[rebuttal_id]["payload"] or {})
                                    .get("cites_record_field")
                                    if rebuttal_id in rebuttal_by_id else None),
             "cites_evidence_id": ((rebuttal_by_id[rebuttal_id]["payload"] or {})
                                   .get("cites_evidence_id")
                                   if rebuttal_id in rebuttal_by_id else None)}
            for rebuttal_id in (objection.get("rebutted_by") or ())]

    cited = _cited_evidence_ids(record)
    gate_trace = _loads(record.get("gate_trace_json"), [])
    return {
        "company_id": record["company_id"],
        "ticker": record["ticker"],
        "publication_tier": record["publication_tier"],
        "net_effect": record["net_effect"],
        "headline_horizon": record["headline_horizon"],
        "materiality_bucket": record["materiality_bucket"],
        "mechanism_id": record["mechanism_id"],
        "evidence_grade": record["evidence_grade"],
        "weakest_link": record["weakest_link"],
        "empirical_status": record["empirical_status"],
        "rejection_reason": record["rejection_reason"],
        "needs_reanalysis": record["needs_reanalysis"],
        "decision_trace_id": record["decision_trace_id"],
        # Four SEPARATE fields, four SEPARATE keys (invariant 4).
        "directness": record["directness"],
        "graph_distance": record["graph_distance"],
        "discovery_source": record["discovery_source"],
        # the causal path, the band, the modifiers, the objections
        "channels": _loads(record.get("channels_json"), []),
        "direction_by_horizon": _loads(record.get("direction_by_horizon_json"), {}),
        "claim_bindings": _loads(record.get("claim_bindings_json"), []),
        "policy_modifiers": _loads(record.get("policy_modifiers_json"), []),
        "sensitivity": adapter.sensitivity,
        "objections": objections,
        "evidence": [{"evidence_id": value, "record": evidence.get(value)}
                     for value in cited],
        "failed_gate_rules": [rule for rule in gate_trace if not rule.get("passed")],
        "gate_trace": gate_trace,
    }


def event_index(conn: sa.Connection, limit: int = 200) -> list[dict]:
    """Every V5 event with a canonical record, newest first, with the counts
    a reviewer picks from."""
    rows = conn.execute(sa.text(
        "SELECT event_id, publication_tier, count(*) AS n, max(created_at) AS last "
        "FROM company_impact GROUP BY event_id, publication_tier")).mappings()
    events: dict[str, dict] = {}
    for row in rows:
        entry = events.setdefault(row["event_id"], {
            "event_id": row["event_id"], "last": row["last"],
            "PRIMARY": 0, "SECONDARY_RIPPLE": 0, "MACRO_CONTEXT": 0,
            "REJECTED": 0, "title": None, "labels": 0})
        entry[row["publication_tier"]] = entry.get(row["publication_tier"], 0) + row["n"]
        entry["last"] = max(entry["last"], row["last"]) if entry["last"] else row["last"]

    for event in events.values():
        article = article_for_event(conn, event["event_id"])
        if article:
            event["title"] = article["title"]
            event["url"] = article["url"]
    try:
        counted = conn.execute(sa.text(
            "SELECT event_id, count(*) AS n FROM eval_label GROUP BY event_id")
        ).mappings()
        for row in counted:
            if row["event_id"] in events:
                events[row["event_id"]]["labels"] = row["n"]
    except sa.exc.SQLAlchemyError:                        # pragma: no cover
        pass          # the eval corpus is an offline harness; it may be absent
    return sorted(events.values(), key=lambda e: str(e["event_id"]))[:limit]


# ---------------------------------------------------------------------------
# the ONE write path
# ---------------------------------------------------------------------------

def record_label(conn: sa.Connection, *, event_id: str, company_ref: str,
                 labeler: str, label: str, expected_tier: str,
                 expected_direction: str | None = None,
                 expected_mechanism: str | None = None,
                 expected_materiality: str | None = None,
                 rationale: str | None = None, stratum: str | None = None,
                 article_ref: str | None = None) -> None:
    """Write one reviewer's judgement into the Gate Zero eval corpus.

    SESSION 0's SCHEMA IS NOT MODIFIED. The phase file's nine-value
    vocabulary lands in `eval_label.label` (which already exists as a free
    text column) and this module closes it; `expected_tier` is the corpus's
    own NOT NULL column and the form asks for it, because "this is wrong"
    without "and this is what it should have been" is not a label a scorer
    can use.

    `labeler` is mandatory and is written verbatim: a label nobody signed is
    not evidence about anything.
    """
    from app.eval.store import EvalValidationError, upsert_event, upsert_label

    if label not in REVIEW_LABELS:
        raise EventReviewError(
            f"{label!r} is not a review label; expected one of "
            f"{', '.join(REVIEW_LABELS)}")
    if not (labeler or "").strip():
        raise EventReviewError("a label needs a labeler -- who is signing it?")
    if not (company_ref or "").strip():
        raise EventReviewError("a label needs a company")

    try:
        if stratum:
            upsert_event(conn, event_id=event_id, stratum=stratum,
                         article_ref=article_ref or event_id)
        upsert_label(conn, event_id=event_id, company_ref=company_ref.strip(),
                     labeler=labeler.strip(), expected_tier=expected_tier,
                     expected_direction=expected_direction or None,
                     expected_mechanism=expected_mechanism or None,
                     expected_materiality=expected_materiality or None,
                     label=label, rationale=rationale or None)
    except EvalValidationError as error:
        raise EventReviewError(str(error)) from error
