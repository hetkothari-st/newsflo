"""Gate Zero eval schema -- the four tables of migration 0010.

Source of truth for the DDL. ``alembic/versions/0010_eval_gate_zero.py``
re-states the same tables with ``op.create_table`` (migrations must not
import application code -- the repo's rule, see 0008's warning block), and
``tests/test_gate_zero_tooling.py::
test_migration_schema_matches_the_declared_metadata`` pins the two
together so they cannot drift.

WHY A SEPARATE MetaData. ``app.db.Base.metadata`` is what
``app.db.init_db()`` calls ``create_all()`` on, in production and in every
test that builds a schema. Hanging the eval tables off it would silently
add four tables to every running database and every test fixture. These
tables belong to an offline measurement harness, not to the product, so
they carry their own MetaData and are created only by the migration or by
:func:`create_eval_tables`.

TABLES SHIP EMPTY. Nothing in this module (or anywhere in this session's
code) inserts a label, an event or a family. The corpus is human work --
docs/v5/00_MASTER_CONTEXT.md's fabrication guard, applied to the one
dataset that measures the system itself. Generating it would make every
number downstream a measurement of our own imagination.

SQLITE ADAPTATION. 08_PHASE_7's DDL is Postgres (``uuid``,
``timestamptz``). This repo is SQLAlchemy/Alembic over SQLite (and
Postgres in the deployed service), so:

  * ``event_id uuid`` -> ``TEXT`` holding a uuid4 hex string
    (:func:`new_event_id`). Portable across both backends, and the
    importer accepts human-written ids like ``crude_2026_08_01`` too --
    a labeler pasting a spreadsheet must not have to mint uuids.
  * ``timestamptz`` -> ``DateTime(timezone=True)``, matching every other
    timestamp column in app/models.py.
  * ``company_id uuid`` -> ``company_ref TEXT``: labels are produced
    BEFORE entity resolution and must not depend on it. A labeler types a
    ticker; if that ticker is not in the universe, that is itself a
    finding the scorer should surface, not a foreign-key error that
    blocks the label.
"""
from __future__ import annotations

import uuid

import sqlalchemy as sa

# ---------------------------------------------------------------------------
# Closed vocabularies. Every one of these is a CHECK constraint in the DB --
# a typo'd stratum silently creates a stratum, and per-stratum reporting
# (08_PHASE_7: "an aggregate number hides that you are excellent on crude
# and useless on policy") stops meaning anything.
# ---------------------------------------------------------------------------

#: 08_PHASE_7 Task 7.1's stratification table, one slug per row of it.
STRATA = (
    "commodity",
    "policy_regulatory",
    "company_action",
    "macro_data",
    "geopolitical",
    "earnings",
    "null_event",
)

#: The expected tier a labeler assigns to a company for an event. Mirrors
#: the publication tiers the system can emit, plus ABSENT -- the label that
#: makes the null slice measurable at all.
EXPECTED_TIERS = ("PRIMARY", "SECONDARY_RIPPLE", "MACRO_CONTEXT", "ABSENT")

#: Adjudication outcomes. DISPUTED is a first-class outcome, not a failure:
#: "an honest system reports its own ambiguity rate" (08_PHASE_7).
RESOLUTIONS = ("LABELER_A", "LABELER_B", "MERGED", "DISPUTED")

#: Directions a labeler may express. NOT a DB CHECK: `expected_direction`
#: is optional and free-form on ABSENT rows, and a labeler who writes
#: something outside this list should be corrected by the importer with a
#: readable error, not by an opaque IntegrityError. The UI offers exactly
#: these as a <select>; the importer validates against them.
DIRECTIONS = ("bullish", "bearish", "mixed", "uncertain")

EVAL_TABLE_NAMES = ("eval_event", "eval_label", "eval_event_label", "eval_adjudication")

EVAL_METADATA = sa.MetaData()


def _in_clause(column: str, values: tuple[str, ...]) -> str:
    joined = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({joined})"


eval_event = sa.Table(
    "eval_event", EVAL_METADATA,
    sa.Column("event_id", sa.String(), primary_key=True),
    sa.Column("stratum", sa.String(), nullable=False),
    # article id (as a string) or article url -- resolved by
    # app.eval.store.resolve_article. Deliberately not a foreign key: an
    # event may be labeled before its article is ingested, and the scorer
    # reports an unresolvable ref loudly rather than refusing the label.
    sa.Column("article_ref", sa.String(), nullable=False),
    sa.Column("notes", sa.Text(), nullable=True),
    sa.CheckConstraint(_in_clause("stratum", STRATA), name="ck_eval_event_stratum"),
)

eval_label = sa.Table(
    "eval_label", EVAL_METADATA,
    sa.Column("event_id", sa.String(), primary_key=True),
    sa.Column("company_ref", sa.String(), primary_key=True),
    sa.Column("labeler", sa.String(), primary_key=True),
    sa.Column("expected_tier", sa.String(), nullable=False),
    sa.Column("expected_direction", sa.String(), nullable=True),
    sa.Column("expected_mechanism", sa.String(), nullable=True),
    sa.Column("expected_materiality", sa.String(), nullable=True),
    sa.Column("label", sa.String(), nullable=True),
    sa.Column("rationale", sa.Text(), nullable=True),
    sa.Column("labeled_at", sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint(_in_clause("expected_tier", EXPECTED_TIERS),
                       name="ck_eval_label_expected_tier"),
)

eval_event_label = sa.Table(
    # Expected ripple FAMILIES are an event-level, per-labeler statement
    # ("this should reach refiners, paints and aviation"). 7.1's schema is
    # per-company and structurally cannot hold them: a family is not a
    # company, and forcing one into company_ref would make the family
    # indistinguishable from a ticker in every downstream query.
    "eval_event_label", EVAL_METADATA,
    sa.Column("event_id", sa.String(), primary_key=True),
    sa.Column("labeler", sa.String(), primary_key=True),
    sa.Column("ripple_families_json", sa.Text(), nullable=True),  # JSON list[str]
    sa.Column("rationale", sa.Text(), nullable=True),
    sa.Column("labeled_at", sa.DateTime(timezone=True), nullable=True),
)

eval_adjudication = sa.Table(
    "eval_adjudication", EVAL_METADATA,
    sa.Column("event_id", sa.String(), primary_key=True),
    sa.Column("company_ref", sa.String(), primary_key=True),
    sa.Column("resolution", sa.String(), nullable=False),
    sa.Column("resolved_by", sa.String(), nullable=True),
    sa.Column("resolved_note", sa.Text(), nullable=True),
    sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint(_in_clause("resolution", RESOLUTIONS),
                       name="ck_eval_adjudication_resolution"),
)


def new_event_id() -> str:
    """uuid4 hex -- the SQLite-portable stand-in for 7.1's ``uuid`` PK."""
    return uuid.uuid4().hex


def create_eval_tables(engine) -> None:
    """Create the four eval tables on ``engine`` if absent.

    For tests and for a throwaway labeling database. Production schema
    comes from ``alembic upgrade head`` (migration 0010) like every other
    table since 2026-08-13.
    """
    EVAL_METADATA.create_all(engine)
