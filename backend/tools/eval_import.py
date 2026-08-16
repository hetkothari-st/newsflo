"""Offline importer for the Gate Zero labeled corpus (CSV or JSON).

Labeling in the browser (tools/eval_ui.py) is the primary path; this is
the other one -- two people labeling 50 events in a spreadsheet, then
loading the result. Both write the same tables through the same helpers
(app.eval.store), so neither can produce a shape the other cannot read.

USAGE

    python tools/eval_import.py --events events.csv --labels labels.csv \
                               --event-labels families.csv [--db URL]
    python tools/eval_import.py --bundle corpus.json [--db URL]

``--db`` defaults to $DATABASE_URL, then to sqlite:///./newsflo.db (the
same default as app/config.py). Each of --events/--labels/--event-labels
accepts a .csv or a .json file; --bundle takes one .json holding all three
under the keys "events", "labels", "event_labels".

FILE FORMATS  (unknown columns are ignored, so a spreadsheet may carry
working columns like `_fixture` or `comments` without failing the import)

events        event_id     optional -- a uuid4 hex is minted when blank
              stratum      REQUIRED -- commodity | policy_regulatory |
                           company_action | macro_data | geopolitical |
                           earnings | null_event
              article_ref  REQUIRED -- the articles.id, or the article url
              notes        optional

labels        event_id          REQUIRED
              company_ref       REQUIRED -- ticker as the labeler typed it
              labeler           REQUIRED -- labeler identity, stored as-is
              expected_tier     REQUIRED -- PRIMARY | SECONDARY_RIPPLE |
                                MACRO_CONTEXT | ABSENT
              expected_direction    optional -- bullish|bearish|mixed|uncertain
              expected_mechanism    optional
              expected_materiality  optional
              rationale             optional
              label                 optional -- free-text labeler note
              ripple_families       optional convenience column: the
                                    EVENT-level families for this
                                    (event_id, labeler). Repeating it on
                                    several rows of the same pair is fine
                                    only if the values agree; contradictory
                                    repeats abort the import rather than
                                    letting the last row silently win.

event_labels  event_id        REQUIRED
              labeler         REQUIRED
              ripple_families optional -- ";"- or ","-separated family names
              rationale       optional

REFUSALS. An unknown stratum, an unknown expected_tier, an unknown
direction, a missing required column, or a label pointing at an event that
is not being imported and does not already exist -- each aborts the WHOLE
import inside one transaction. A half-loaded corpus is worse than none:
the scorer would report metrics over a subset and no one would know.

IDEMPOTENT. Every write is an upsert on the natural primary key, so
re-importing a corrected spreadsheet updates in place instead of
duplicating.

This importer NEVER writes to a production table and never invents a row:
it loads exactly what the file says, or nothing.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import sqlalchemy as sa  # noqa: E402

from app.eval.schema import (  # noqa: E402
    DIRECTIONS,
    EXPECTED_TIERS,
    STRATA,
    new_event_id,
)
from app.eval import store  # noqa: E402


class EvalImportError(Exception):
    """A file the importer refuses. Carries the offending row's location."""


def _fail(source: Any, index: int | None, message: str) -> None:
    where = f"{source}" + (f" row {index}" if index is not None else "")
    raise EvalImportError(f"{where}: {message}")


def _load_rows(path: str | Path, key: str) -> list[dict[str, Any]]:
    """Read a .csv or a .json list of objects into plain dicts."""
    path = Path(path)
    if not path.exists():
        raise EvalImportError(f"{path}: file not found")
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            payload = payload.get(key, [])
        if not isinstance(payload, list):
            raise EvalImportError(f"{path}: expected a JSON list of {key} objects")
        return [dict(item) for item in payload]
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _get(row: dict[str, Any], name: str) -> str:
    value = row.get(name)
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ";".join(str(v) for v in value)
    return str(value).strip()


def _require(row: dict[str, Any], name: str, source: Any, index: int) -> str:
    value = _get(row, name)
    if not value:
        _fail(source, index, f"missing required column {name!r}")
    return value


def _validated_events(rows: Iterable[dict[str, Any]], source: Any) -> list[dict[str, Any]]:
    out = []
    for index, row in enumerate(rows, start=1):
        stratum = _require(row, "stratum", source, index)
        if stratum not in STRATA:
            _fail(source, index,
                  f"unknown stratum {stratum!r}; expected one of {', '.join(STRATA)}")
        article_ref = _require(row, "article_ref", source, index)
        event_id = _get(row, "event_id") or new_event_id()
        out.append({"event_id": event_id, "stratum": stratum,
                    "article_ref": article_ref, "notes": _get(row, "notes") or None})
    return out


def _validated_labels(rows: Iterable[dict[str, Any]], source: Any) -> tuple[
        list[dict[str, Any]], list[dict[str, Any]]]:
    """Returns (label rows, event-level rows implied by a families column)."""
    labels: list[dict[str, Any]] = []
    implied: dict[tuple[str, str], list[str]] = {}
    for index, row in enumerate(rows, start=1):
        event_id = _require(row, "event_id", source, index)
        company_ref = store.normalize_company_ref(
            _require(row, "company_ref", source, index))
        labeler = _require(row, "labeler", source, index)
        tier = _require(row, "expected_tier", source, index).upper()
        if tier not in EXPECTED_TIERS:
            _fail(source, index, f"unknown expected_tier {tier!r}; expected one of "
                                 f"{', '.join(EXPECTED_TIERS)}")
        direction = _get(row, "expected_direction").lower() or None
        if direction and direction not in DIRECTIONS:
            _fail(source, index, f"unknown expected_direction {direction!r}; expected one "
                                 f"of {', '.join(DIRECTIONS)} (or blank)")
        labels.append({
            "event_id": event_id, "company_ref": company_ref, "labeler": labeler,
            "expected_tier": tier, "expected_direction": direction,
            "expected_mechanism": _get(row, "expected_mechanism") or None,
            "expected_materiality": _get(row, "expected_materiality") or None,
            "label": _get(row, "label") or None,
            "rationale": _get(row, "rationale") or None,
        })
        if "ripple_families" in row:
            families = store.parse_list(_get(row, "ripple_families"))
            key = (event_id, labeler)
            if key in implied and implied[key] != families:
                _fail(source, index,
                      f"contradictory ripple_families for event {event_id!r} / labeler "
                      f"{labeler!r}: {implied[key]} then {families}. Families are an "
                      f"event-level statement -- repeat them identically or move them to "
                      f"an --event-labels file.")
            implied[key] = families
    implied_rows = [{"event_id": e, "labeler": l, "ripple_families": f,
                     "rationale": None} for (e, l), f in implied.items()]
    return labels, implied_rows


def _validated_event_labels(rows: Iterable[dict[str, Any]],
                            source: Any) -> list[dict[str, Any]]:
    out = []
    for index, row in enumerate(rows, start=1):
        event_id = _require(row, "event_id", source, index)
        labeler = _require(row, "labeler", source, index)
        out.append({
            "event_id": event_id, "labeler": labeler,
            "ripple_families": store.parse_list(_get(row, "ripple_families")),
            "rationale": _get(row, "rationale") or None,
        })
    return out


def run_import(engine, *, events=None, labels=None, event_labels=None,
               bundle=None) -> dict[str, int]:
    """Validate everything, then write everything, in ONE transaction.

    Raises :class:`EvalImportError` before any write when a row is
    invalid, so a rejected file leaves the database exactly as it was.
    """
    event_rows: list[dict[str, Any]] = []
    label_rows: list[dict[str, Any]] = []
    event_label_rows: list[dict[str, Any]] = []

    if bundle is not None:
        payload = json.loads(Path(bundle).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise EvalImportError(f"{bundle}: a bundle must be a JSON object with "
                                  f"'events' / 'labels' / 'event_labels' keys")
        event_rows += _validated_events(payload.get("events", []), f"{bundle}#events")
        bundle_labels, implied = _validated_labels(payload.get("labels", []),
                                                   f"{bundle}#labels")
        label_rows += bundle_labels
        event_label_rows += implied
        event_label_rows += _validated_event_labels(payload.get("event_labels", []),
                                                    f"{bundle}#event_labels")
    if events is not None:
        event_rows += _validated_events(_load_rows(events, "events"), events)
    if labels is not None:
        file_labels, implied = _validated_labels(_load_rows(labels, "labels"), labels)
        label_rows += file_labels
        event_label_rows += implied
    if event_labels is not None:
        event_label_rows += _validated_event_labels(
            _load_rows(event_labels, "event_labels"), event_labels)

    if not (event_rows or label_rows or event_label_rows):
        raise EvalImportError("nothing to import -- no --events, --labels, "
                              "--event-labels or --bundle produced any row")

    with engine.begin() as conn:
        known_events = set(conn.execute(sa.text("SELECT event_id FROM eval_event")).scalars())
        known_events |= {row["event_id"] for row in event_rows}
        for row in label_rows + event_label_rows:
            if row["event_id"] not in known_events:
                raise EvalImportError(
                    f"label references unknown event {row['event_id']!r} -- import its "
                    f"events file first, or in the same run")

        for row in event_rows:
            store.upsert_event(conn, **row)
        for row in label_rows:
            store.upsert_label(conn, **row)
        for row in event_label_rows:
            store.upsert_event_label(conn, **row)

    return {"events": len(event_rows), "labels": len(label_rows),
            "event_labels": len(event_label_rows)}


def _default_db_url() -> str:
    return os.environ.get("DATABASE_URL", "sqlite:///./newsflo.db")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Import a Gate Zero labeled corpus from CSV/JSON.")
    parser.add_argument("--db", default=None,
                        help="SQLAlchemy URL (default: $DATABASE_URL, else sqlite:///./newsflo.db)")
    parser.add_argument("--events", default=None, help="events file (.csv or .json)")
    parser.add_argument("--labels", default=None, help="labels file (.csv or .json)")
    parser.add_argument("--event-labels", default=None,
                        help="event-level ripple families file (.csv or .json)")
    parser.add_argument("--bundle", default=None,
                        help="one .json with events/labels/event_labels keys")
    args = parser.parse_args(argv)

    if not any((args.events, args.labels, args.event_labels, args.bundle)):
        parser.error("give at least one of --events / --labels / --event-labels / --bundle")

    url = args.db or _default_db_url()
    engine = sa.create_engine(url)
    try:
        counts = run_import(engine, events=args.events, labels=args.labels,
                            event_labels=args.event_labels, bundle=args.bundle)
    except EvalImportError as exc:
        print(f"IMPORT REFUSED: {exc}", file=sys.stderr)
        print("Nothing was written -- fix the file and re-run.", file=sys.stderr)
        return 2
    print(f"imported into {url}: {counts['events']} event(s), {counts['labels']} label(s), "
          f"{counts['event_labels']} event-level label(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
