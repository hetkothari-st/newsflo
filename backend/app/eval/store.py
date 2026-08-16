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
import re
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


_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


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


# Exchange suffixes actually present in the live universe, measured
# 2026-08-17 against backend/newsflo.db: .BO 2418, .NS 2396, .B 2, .KS 1,
# out of 4817 suffixed tickers in 5321 companies. Labelers type the BARE
# symbol (RELIANCE, not RELIANCE.NS), so without stripping these, ~90% of
# the universe can never match a label -- every expectation becomes a false
# negative and every published company a false positive, and the baseline
# reads near zero with real-looking denominators.
#
# .NSE / .BSE are accepted too: they are not in the DB today but are the
# spelling a labeler is most likely to type by hand.
#
# An UNKNOWN dotted suffix is deliberately left INTACT rather than stripped
# by a generic rule -- it then surfaces in BASELINE.md's UNMATCHED section,
# which is a loud, fixable signal, instead of being silently mangled into a
# different company (BRK.A is not BRK).
EXCHANGE_SUFFIXES = ("NS", "BO", "NSE", "BSE", "KS", "B")


def canonical_company_ref(value: str) -> str:
    """Upper-case and strip a known exchange suffix.

    The ONE spelling both sides of the scorer's join are reduced to: the
    labeler's typed ref and the universe's ``companies.ticker``. Applied at
    write time as well, so two labelers typing ``RELIANCE`` and
    ``RELIANCE.NS`` produce one label row, not a spurious disagreement.
    """
    text = (value or "").strip().upper()
    if "." in text:
        head, _, suffix = text.rpartition(".")
        if head and suffix in EXCHANGE_SUFFIXES:
            return head
    return text


def normalize_company_ref(value: str) -> str:
    """Alias of :func:`canonical_company_ref`, kept as the name every call
    site already uses."""
    return canonical_company_ref(value)


def normalize_alias(value: str) -> str:
    """Lower-case, punctuation-to-space, collapsed. Used only to look a
    labeler's typed ref up in ``company_aliases``; deliberately our own
    normalization rather than an import of app.companies (which would pull
    the application, and its provider clients, into the scorer)."""
    return " ".join(_NON_ALNUM_RE.sub(" ", (value or "").lower()).split())


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


def load_company_index(conn: sa.Connection) -> dict[str, Any]:
    """Everything needed to turn a labeler-typed reference into a company.

    Two rungs, in order:

      1. **canonical ticker** -- ``canonical_company_ref(ref)`` against
         ``canonical_company_ref(companies.ticker)``. This is what makes a
         bare ``RELIANCE`` find ``RELIANCE.NS``.
      2. **alias** -- ``company_aliases`` (LEGAL name, BSE_ID, NSE_SYMBOL,
         TRADE_NAME…), so ``RIL`` and ``Reliance Industries`` also resolve.

    Ambiguity is preserved, not resolved: a ref that maps to more than one
    company comes back as ambiguous and is reported rather than guessed at.
    Two listings of the SAME company (RELIANCE.NS and RELIANCE.BO) collapse
    to one canonical ticker and are therefore not ambiguous -- they are one
    company with two lines.
    """
    by_canonical: dict[str, set[str]] = {}
    id_to_canonical: dict[int, str] = {}
    for company_id, ticker in conn.execute(sa.text("SELECT id, ticker FROM companies")):
        canonical = canonical_company_ref(ticker or "")
        if not canonical:
            continue
        by_canonical.setdefault(canonical, set()).add(canonical)
        id_to_canonical[company_id] = canonical

    by_alias: dict[str, set[str]] = {}
    try:
        rows = conn.execute(sa.text(
            "SELECT company_id, alias, normalized FROM company_aliases"))
    except sa.exc.SQLAlchemyError:
        rows = []  # table absent on a minimal DB -- rung 1 still works
    for company_id, alias, normalized in rows:
        canonical = id_to_canonical.get(company_id)
        if not canonical:
            continue
        for key in (normalize_alias(alias), normalize_alias(normalized)):
            if key:
                by_alias.setdefault(key, set()).add(canonical)
    return {"by_canonical": by_canonical, "by_alias": by_alias}


def resolve_ref(index: dict[str, Any], ref: str) -> tuple[str | None, str]:
    """-> (canonical ticker, reason). ``None`` means the reference matched
    no company; the reason is written into BASELINE.md verbatim."""
    canonical = canonical_company_ref(ref)
    if not canonical:
        return None, "blank reference"
    if canonical in index["by_canonical"]:
        return canonical, "ticker"
    matches = index["by_alias"].get(normalize_alias(ref)) or set()
    if len(matches) == 1:
        return next(iter(matches)), "alias"
    if len(matches) > 1:
        return None, f"ambiguous: matches {len(matches)} companies ({', '.join(sorted(matches))})"
    return None, "no company in the universe matches this reference"


def load_family_vocabulary(conn: sa.Connection) -> dict[str, list[str]]:
    """The canonical ripple-family vocabulary, generated from the universe
    itself: ``SELECT DISTINCT sub_sector`` plus ``sector``.

    Shown to the labeler in the labeling form (so they type wording the
    scorer can match) and consulted by the scorer. It is the WHOLE
    vocabulary every time -- never filtered to the event on screen, which
    would leak the answer.
    """
    sub_sectors = sorted({
        row[0] for row in conn.execute(sa.text(
            "SELECT DISTINCT sub_sector FROM companies WHERE sub_sector IS NOT NULL"))
        if (row[0] or "").strip()})
    sectors = sorted({
        row[0] for row in conn.execute(sa.text(
            "SELECT DISTINCT sector FROM companies WHERE sector IS NOT NULL"))
        if (row[0] or "").strip()})
    return {"sub_sectors": sub_sectors, "sectors": sectors}


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
