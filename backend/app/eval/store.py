"""Read/write helpers over the Gate Zero eval tables.

Shared by the labeling UI, the importer and the scorer so the three cannot
disagree about what a label is. Everything here takes a SQLAlchemy
``Connection`` and returns plain dicts -- no ORM, no session lifecycle, no
import of ``app.models``. That keeps the scorer's import graph free of the
application (and therefore free of any provider SDK), which
``test_scorer_imports_no_llm_or_network_module`` enforces.

Upserts are written as UPDATE-then-INSERT rather than a dialect-specific
``ON CONFLICT``: the local DB is SQLite, the deployed one is Postgres, and
this tooling must run identically against both.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

import sqlalchemy as sa

from app.eval.schema import (
    EXPECTED_TIERS,
    RESOLUTIONS,
    STRATA,
    eval_adjudication,
    eval_event,
    eval_event_label,
    eval_label,
)


class EvalValidationError(ValueError):
    """A value outside a closed vocabulary. Raised before any write."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# parsing helpers
# ---------------------------------------------------------------------------

def parse_list(value: str | Sequence[str] | None) -> list[str]:
    """Split a human-typed list on commas, semicolons or newlines.

    Labelers type ``AAA, BBB`` in a form and ``AAA;BBB`` in a spreadsheet
    cell; both mean the same thing. Order is preserved and duplicates are
    collapsed (first occurrence wins) so a double-typed ticker is not two
    labels.
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        items = [str(v).strip() for v in value]
    else:
        text = str(value).replace(";", ",").replace("\n", ",")
        items = [part.strip() for part in text.split(",")]
    out: list[str] = []
    for item in items:
        if item and item not in out:
            out.append(item)
    return out


def parse_direction_map(value: str | None) -> dict[str, str]:
    """``"AAA:bearish, BBB:bullish"`` -> ``{"AAA": "bearish", ...}``.

    Entries without a colon are ignored rather than guessed at -- a
    direction we cannot read is a direction we do not have, and the
    wrong-direction metric must never score against an invented one.
    """
    out: dict[str, str] = {}
    for chunk in parse_list(value):
        if ":" not in chunk:
            continue
        company, _, direction = chunk.partition(":")
        company, direction = company.strip(), direction.strip().lower()
        if company and direction:
            out[company.upper()] = direction
    return out


def normalize_company_ref(value: str) -> str:
    """Tickers are compared case-insensitively everywhere; store them
    upper-cased so ``infy`` and ``INFY`` are one label, not two."""
    return (value or "").strip().upper()


# ---------------------------------------------------------------------------
# writes (all idempotent on the primary key)
# ---------------------------------------------------------------------------

def _upsert(conn: sa.Connection, table: sa.Table, keys: dict[str, Any],
            values: dict[str, Any]) -> None:
    where = sa.and_(*[table.c[k] == v for k, v in keys.items()])
    if values:
        result = conn.execute(sa.update(table).where(where).values(**values))
        if result.rowcount:
            return
    else:
        existing = conn.execute(sa.select(sa.literal(1)).where(where).select_from(table)).first()
        if existing:
            return
    conn.execute(sa.insert(table).values(**keys, **values))


def upsert_event(conn: sa.Connection, *, event_id: str, stratum: str,
                 article_ref: str, notes: str | None = None) -> None:
    if stratum not in STRATA:
        raise EvalValidationError(
            f"unknown stratum {stratum!r}; expected one of {', '.join(STRATA)}")
    _upsert(conn, eval_event, {"event_id": event_id},
            {"stratum": stratum, "article_ref": article_ref, "notes": notes})


def upsert_label(conn: sa.Connection, *, event_id: str, company_ref: str, labeler: str,
                 expected_tier: str, expected_direction: str | None = None,
                 expected_mechanism: str | None = None,
                 expected_materiality: str | None = None, label: str | None = None,
                 rationale: str | None = None,
                 labeled_at: datetime | None = None) -> None:
    if expected_tier not in EXPECTED_TIERS:
        raise EvalValidationError(
            f"unknown expected_tier {expected_tier!r}; expected one of "
            f"{', '.join(EXPECTED_TIERS)}")
    _upsert(conn, eval_label,
            {"event_id": event_id, "company_ref": normalize_company_ref(company_ref),
             "labeler": labeler},
            {"expected_tier": expected_tier, "expected_direction": expected_direction,
             "expected_mechanism": expected_mechanism,
             "expected_materiality": expected_materiality, "label": label,
             "rationale": rationale, "labeled_at": labeled_at or utcnow()})


def upsert_event_label(conn: sa.Connection, *, event_id: str, labeler: str,
                       ripple_families: Iterable[str] | None = None,
                       rationale: str | None = None,
                       labeled_at: datetime | None = None) -> None:
    families = list(ripple_families or [])
    _upsert(conn, eval_event_label, {"event_id": event_id, "labeler": labeler},
            {"ripple_families_json": json.dumps(families), "rationale": rationale,
             "labeled_at": labeled_at or utcnow()})


def upsert_adjudication(conn: sa.Connection, *, event_id: str, company_ref: str,
                        resolution: str, resolved_by: str | None = None,
                        resolved_note: str | None = None,
                        resolved_at: datetime | None = None) -> None:
    if resolution not in RESOLUTIONS:
        raise EvalValidationError(
            f"unknown resolution {resolution!r}; expected one of {', '.join(RESOLUTIONS)}")
    _upsert(conn, eval_adjudication,
            {"event_id": event_id, "company_ref": normalize_company_ref(company_ref)},
            {"resolution": resolution, "resolved_by": resolved_by,
             "resolved_note": resolved_note, "resolved_at": resolved_at or utcnow()})


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------

def resolve_article(conn: sa.Connection, article_ref: str) -> dict[str, Any] | None:
    """Resolve an ``article_ref`` to the stored article.

    Accepts an article id (digits) or a url. Returns None when nothing
    matches -- callers must report that, never substitute a placeholder
    article.
    """
    ref = (article_ref or "").strip()
    if not ref:
        return None
    sql = ("SELECT id, source, url, title, content, full_content, published_at, status "
           "FROM articles WHERE ")
    if ref.isdigit():
        row = conn.execute(sa.text(sql + "id = :v"), {"v": int(ref)}).mappings().first()
    else:
        row = conn.execute(sa.text(sql + "url = :v"), {"v": ref}).mappings().first()
    return dict(row) if row else None


def get_event(conn: sa.Connection, event_id: str) -> dict[str, Any] | None:
    row = conn.execute(sa.select(eval_event).where(
        eval_event.c.event_id == event_id)).mappings().first()
    return dict(row) if row else None


def all_events(conn: sa.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(sa.select(eval_event).order_by(eval_event.c.event_id)).mappings()
    return [dict(r) for r in rows]


def labels_for_event(conn: sa.Connection, event_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(sa.select(eval_label).where(
        eval_label.c.event_id == event_id).order_by(
        eval_label.c.company_ref, eval_label.c.labeler)).mappings()
    return [dict(r) for r in rows]


def event_labels_for_event(conn: sa.Connection, event_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(sa.select(eval_event_label).where(
        eval_event_label.c.event_id == event_id).order_by(
        eval_event_label.c.labeler)).mappings()
    out = []
    for row in rows:
        item = dict(row)
        item["ripple_families"] = json.loads(item.get("ripple_families_json") or "[]")
        out.append(item)
    return out


def adjudications_for_event(conn: sa.Connection, event_id: str) -> dict[str, dict[str, Any]]:
    rows = conn.execute(sa.select(eval_adjudication).where(
        eval_adjudication.c.event_id == event_id)).mappings()
    return {r["company_ref"]: dict(r) for r in rows}


def labelers_for_event(conn: sa.Connection, event_id: str) -> list[str]:
    """Everyone who has recorded ANYTHING for this event -- a per-company
    label or an event-level families row. A labeler who genuinely expects
    no company (a correct null-event label) still counts as having
    labeled it, which is exactly the case the null slice measures."""
    per_company = conn.execute(sa.select(eval_label.c.labeler.distinct()).where(
        eval_label.c.event_id == event_id)).scalars().all()
    event_level = conn.execute(sa.select(eval_event_label.c.labeler.distinct()).where(
        eval_event_label.c.event_id == event_id)).scalars().all()
    return sorted(set(per_company) | set(event_level))


def event_progress(conn: sa.Connection) -> list[dict[str, Any]]:
    """One row per event: who has labeled it and how far adjudication got.
    Drives the labeling UI's index page."""
    out = []
    for event in all_events(conn):
        labelers = labelers_for_event(conn, event["event_id"])
        adjudications = adjudications_for_event(conn, event["event_id"])
        resolutions = [a["resolution"] for a in adjudications.values()]
        out.append({
            **event,
            "labelers": labelers,
            "labeler_count": len(labelers),
            "adjudicated": len(adjudications),
            "disputed": sum(1 for r in resolutions if r == "DISPUTED"),
        })
    return out


def next_unlabeled_event(conn: sa.Connection, labeler: str) -> str | None:
    """The first event (by id) this labeler has not touched.

    Deliberately independent of what the OTHER labeler has done: the two
    passes are independent by protocol, and skipping events someone else
    already labeled would collapse the corpus to one labeler per event.
    """
    labeled = set(conn.execute(sa.select(eval_label.c.event_id).where(
        eval_label.c.labeler == labeler)).scalars().all())
    labeled |= set(conn.execute(sa.select(eval_event_label.c.event_id).where(
        eval_event_label.c.labeler == labeler)).scalars().all())
    for event in all_events(conn):
        if event["event_id"] not in labeled:
            return event["event_id"]
    return None
