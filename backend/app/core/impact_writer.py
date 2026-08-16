"""TASK 0.3 -- the reducer persistence module. THE ONLY WRITER of
`company_impact`.

Deliberately IMPURE (it is the DB boundary) and deliberately the only place
in the codebase that opens a `reducer_session`. Everything else in the
process -- the API, the scheduler, a one-off script, a stale worker from an
older container -- is refused by the database itself.

HOW THE GUARD WORKS (SQLite substitution for the phase file's Postgres
roles, ruled binding by the controller):

    with reducer_session(session):        # CREATE TEMP TABLE _newsflo_…
        upsert_impact_row(session, row)   # allowed on THIS connection only
    # temp table dropped -> the very next statement is refused again

`app/models.py`'s triggers check for that temp table on every INSERT and
UPDATE. The Postgres port replaces this with real role privileges; the DDL
is recorded in migration 0011's docstring.

Idempotency and staleness: writes go through
`INSERT … ON CONFLICT (event_id, company_id, analysis_version) DO UPDATE …
WHERE company_impact.reducer_run_seq < excluded.reducer_run_seq`, so a
slow worker whose result arrives late cannot overwrite a newer one.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

import json
import logging

from sqlalchemy import text

from app.core.reducer import CompanyImpact, REDUCER_VERSION

logger = logging.getLogger(__name__)

REDUCER_SESSION_TABLE = "_newsflo_reducer_session"

# Every column the writer sets. Kept explicit (not derived from the model)
# so a new column cannot silently start being written by accident.
_IMPACT_COLUMNS = (
    "event_id", "company_id", "ticker", "isin", "analysis_version",
    "reducer_version", "reducer_run_seq", "gate_config_version",
    "net_effect", "headline_horizon", "direction_by_horizon_json",
    "sign_consistency", "materiality_bucket", "mechanism_id",
    "channels_json", "policy_modifiers_json", "evidence_grade",
    "weakest_link", "claim_bindings_json", "empirical_status",
    "objections_json", "directness", "graph_distance", "discovery_source",
    "publication_tier", "needs_reanalysis", "rejection_reason",
    "gate_trace_json", "decision_trace_id", "created_at",
)

_KEY_COLUMNS = ("event_id", "company_id", "analysis_version")
# Never rewritten by an upsert: the identity columns, and the moment the
# canonical row first appeared (an upsert is a new REDUCTION of the same
# event, not a new row).
_IMMUTABLE_ON_UPDATE = _KEY_COLUMNS + ("created_at",)


class ReducerPrivilegeError(RuntimeError):
    """A process that can write `company_impact` when it must not."""


def event_id_for_article(article_id: int) -> str:
    """V5 `event_id` in this repo's terms.

    There is no `event` table here: an "event" is one analysis run of one
    article (an Alert). The identity pair the controller ruled is
    `article_id` + `analysis_version`, where `analysis_version` is
    `app.pipeline._v3_cache_key(article)` -- the content key that already
    encodes prompt, schema, knowledge-registry and gate-policy versions plus
    the article's content hash.
    """
    return f"article:{article_id}"


@contextmanager
def reducer_session(session):
    """Grant THIS connection the reducer capability, for the duration of the
    block. Nothing else in the codebase may call this."""
    session.execute(text(
        f"CREATE TEMP TABLE IF NOT EXISTS {REDUCER_SESSION_TABLE} (granted INTEGER)"))
    try:
        yield session
    finally:
        # Dropped in a finally so an exception cannot leave a connection
        # holding write privileges it should not have.
        session.execute(text(f"DROP TABLE IF EXISTS temp.{REDUCER_SESSION_TABLE}"))


def assert_cannot_write_company_impact(session) -> None:
    """Task 0.3's startup assertion, called from `app.main`. The API process
    must NOT be able to write the canonical table; if it can, something has
    granted it the reducer capability and the single-writer guarantee is
    already gone."""
    granted = session.execute(text(
        "SELECT count(*) FROM pragma_table_list "
        "WHERE schema = 'temp' AND name = :name"
        if session.bind is not None and session.bind.dialect.name == "sqlite"
        else "SELECT 0"), {"name": REDUCER_SESSION_TABLE}).scalar()
    if granted:
        raise ReducerPrivilegeError(
            "this process holds the reducer write capability "
            f"({REDUCER_SESSION_TABLE} exists on its connection) -- only "
            "app.core.impact_writer may hold it")


def _row_from_impact(impact: CompanyImpact, reducer_run_seq: int) -> dict:
    return {
        "event_id": impact.event_id,
        "company_id": impact.company_id,
        "ticker": impact.ticker,
        "isin": impact.isin,
        "analysis_version": impact.analysis_version,
        "reducer_version": impact.reducer_version,
        "reducer_run_seq": int(reducer_run_seq),
        "gate_config_version": impact.gate_config_version,
        "net_effect": impact.net_effect,
        "headline_horizon": impact.headline_horizon,
        "direction_by_horizon_json": json.dumps(
            {k: dict(v) for k, v in impact.direction_by_horizon.items()},
            sort_keys=True),
        "sign_consistency": impact.sign_consistency,
        "materiality_bucket": impact.materiality_bucket,
        "mechanism_id": impact.mechanism_id,
        "channels_json": json.dumps([dict(c) for c in impact.channels], sort_keys=True),
        "policy_modifiers_json": json.dumps(list(impact.policy_modifiers_applied)),
        "evidence_grade": impact.evidence_grade,
        "weakest_link": impact.weakest_link,
        "claim_bindings_json": json.dumps(
            [dict(b) for b in impact.claim_bindings], sort_keys=True),
        "empirical_status": impact.empirical_status,
        "objections_json": json.dumps(
            [dict(o) for o in impact.objections], sort_keys=True),
        "directness": impact.directness,
        "graph_distance": impact.graph_distance,
        "discovery_source": impact.discovery_source,
        "publication_tier": impact.publication_tier,
        "needs_reanalysis": 1 if impact.needs_reanalysis else 0,
        "rejection_reason": impact.rejection_reason,
        "gate_trace_json": json.dumps([dict(r) for r in impact.gate_trace],
                                      sort_keys=True),
        "decision_trace_id": impact.decision_trace_id,
        # The writer is the impure boundary, so reading a clock here is
        # fine -- the REDUCER never does, which is what keeps its output
        # byte-identical across runs.
        "created_at": datetime.now(timezone.utc),
    }


def upsert_impact_row(session, row: Mapping[str, Any]) -> None:
    """The monotonic-sequence upsert from the phase file, verbatim in
    intent: a lower `reducer_run_seq` never overwrites a higher one."""
    columns = [c for c in _IMPACT_COLUMNS if c in row]
    updates = ", ".join(f"{c} = excluded.{c}" for c in columns
                        if c not in _IMMUTABLE_ON_UPDATE)
    statement = (
        f"INSERT INTO company_impact ({', '.join(columns)}) "
        f"VALUES ({', '.join(':' + c for c in columns)}) "
        f"ON CONFLICT (event_id, company_id, analysis_version) DO UPDATE SET "
        f"{updates} "
        "WHERE company_impact.reducer_run_seq < excluded.reducer_run_seq")
    session.execute(text(statement), dict(row))


def persist_company_impact(session, impact: CompanyImpact,
                           *, reducer_run_seq: int) -> None:
    """Write one canonical record. Opens (and closes) the reducer session."""
    with reducer_session(session):
        upsert_impact_row(session, _row_from_impact(impact, reducer_run_seq))
    # COMMITTED OUTSIDE THE BLOCK, deliberately (fix round 2, C1). A
    # Session.commit() releases the connection back to the pool, and a
    # SQLite TEMP table lives on the CONNECTION -- committing while the
    # capability token still existed handed the next borrower of that
    # connection the right to write company_impact (empirically reproduced
    # on a QueuePool engine: the very next Session wrote a row). Worse, with
    # more than one pooled connection the `finally` DROP could land on a
    # DIFFERENT connection -- a silent no-op leaving the original privileged
    # for the process lifetime. Dropping first, inside the same transaction
    # and before any commit, makes both impossible. The triggers fire at
    # INSERT time, not at commit time, so the write above is unaffected.
    # Pinned by tests/phase0/test_writer_pool_isolation.py.
    session.commit()


def append_signals(session, signals: Iterable) -> int:
    """Append signals to the append-only table. Content-addressed ids make
    this idempotent: replaying the same analysis inserts nothing new."""
    written = 0
    for signal in signals:
        result = session.execute(text(
            "INSERT OR IGNORE INTO signal (signal_id, event_id, company_id, "
            "stage, kind, payload_json, created_by, analysis_version, created_at) "
            "VALUES (:signal_id, :event_id, :company_id, :stage, :kind, "
            ":payload_json, :created_by, :analysis_version, :created_at)"), {
                "signal_id": signal.signal_id, "event_id": signal.event_id,
                "company_id": signal.company_id, "stage": signal.stage,
                "kind": str(signal.kind),
                "payload_json": json.dumps(dict(signal.payload), sort_keys=True),
                "created_by": signal.created_by,
                "analysis_version": signal.analysis_version,
                "created_at": signal.created_at,
            })
        written += result.rowcount or 0
    return written


def record_company_impacts(session, *, article, entries, alert,
                           entity_status_by_company=None,
                           isin_by_company=None) -> int:
    """THE POST-ANALYSIS HOOK (controller adaptation).

    Converts the V4 entry dicts the existing pipeline just built into
    signals, reduces each company independently, and persists the canonical
    records. It writes ONLY to `signal` and `company_impact`; the
    `alert_companies` serving path is untouched.

    The caller wraps this so a failure here can never break the existing
    persist path -- see app/pipeline.py.
    """
    from app.core.config_loader import load_gate_config, load_sensitivity_policy
    from app.core.reducer import EventContext, ReducerConfig, reduce_company_impact
    from app.core.signal_adapters import signals_from_entry

    # `analysis_version` is the article's own content key -- the identity
    # the controller ruled (see event_id_for_article).
    from app.pipeline import _v3_cache_key

    analysis_version = _v3_cache_key(article)
    event_id = event_id_for_article(article.id)
    created_at = alert.created_at or article.published_at

    config = ReducerConfig(
        gate_config=load_gate_config(),
        event_context=EventContext(
            # A real field, not a guess: the ingestion layer marks an alert
            # unconfirmed when the source is a rumour. §7.4: rumours never
            # publish primary.
            event_status="RUMOUR" if getattr(alert, "is_unconfirmed", None) else "CONFIRMED",
            # No shock-sizing engine exists yet (Phase 2). Unknown stays
            # unknown; the gate decides what that means.
            shock_magnitude_confidence=None,
            # This hook runs on the V4 path, which has no exposure TAGS to
            # ask about, so it cannot compute a company's staleness here.
            # Phase 2's sensitivity engine can, and does: it puts the real
            # flag on every CHANNEL payload it emits, and the reducer
            # hard-blocks on that (see `reduce_company_impact`). Until the
            # canonical path runs the engine, this stays False and the
            # abstention comes from having no channel at all.
            exposure_stale=False),
        # PHASE 2: the sign-consistency thresholds, so a computed band
        # arriving on this path is judged by the deployed policy rather than
        # refused. V4 signals carry no band and are unaffected.
        sensitivity_policy=load_sensitivity_policy())

    entity_status_by_company = entity_status_by_company or {}
    isin_by_company = isin_by_company or {}

    written = 0
    for entry in entries:
        company_id = entry.get("company_id")
        if company_id is None:
            # A candidate whose ticker never resolved has no canonical
            # record to write (and no company row to point at). The V4
            # decision record already retains it for audit.
            continue
        signals = signals_from_entry(
            entry, event_id=event_id, analysis_version=analysis_version,
            created_at=created_at,
            entity_status=entity_status_by_company.get(company_id, "UNKNOWN"),
            isin=isin_by_company.get(company_id))
        append_signals(session, signals)
        impact = reduce_company_impact(signals, config)
        # alert.id is monotonic per analysis run, which is exactly the
        # ordering the stale-worker guard needs.
        with reducer_session(session):
            upsert_impact_row(session, _row_from_impact(impact, alert.id))
        written += 1
    # Outside every guard block, for the reason spelled out in
    # persist_company_impact: a commit inside one would release a connection
    # to the pool still carrying the capability token.
    session.commit()
    logger.info("[v5] wrote %s company_impact rows for %s (reducer %s)",
                written, event_id, REDUCER_VERSION)
    return written
