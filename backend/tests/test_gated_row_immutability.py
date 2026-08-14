"""Blueprint §26 -- gated rows are immutable against inconsistency, at the
DATABASE level, not merely by application convention.

The real run exposed a stale pre-V4 worker mutating a gated row AFTER the
publication gate had authorized it: the row came out of the gate with a
positive `economic_effect`, and something outside the V4 code path wrote a
`bearish` direction over it. Application-side guards (app/pipeline.py's
gate_state skip) only protect the binaries that carry them -- a stale
container, a one-off script, an old worker class all still hold a write
handle to the same file.

These tests pin the backstop that fires inside ANY binary touching the DB:
SQLite BEFORE INSERT / BEFORE UPDATE triggers on `alert_companies` that
RAISE(ABORT) when a GATED row would be left in a state the gate could
never have produced. Legacy (ungated, gate_state IS NULL) rows keep their
byte-identical pre-gate behaviour -- they have no gate semantics to
protect and must stay writable.

The triggers are installed BOTH by migration 0008 (production DBs) and by
a `after_create` DDL hook in app/models.py (create_all-built DBs, which is
what this module's `db_session` fixture uses) -- see
tests/test_migrations.py for the migration half of the same guarantee.

Also pinned here: the §26 idempotency key -- a partial unique index on
alerts(article_id, content_key) so two processes persisting the identical
analysis of the identical article collide on INSERT instead of both
landing.
"""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError

from app.models import Alert, AlertCompany, Article, Company

# RAISE(ABORT, ...) surfaces as SQLITE_CONSTRAINT_TRIGGER -> sqlite3
# IntegrityError; guard against OperationalError too so the assertion is
# about "the write was refused", not about a driver's error taxonomy.
_REFUSED = (IntegrityError, OperationalError)


def _seed(db_session, *, gate_state, economic_effect="positive", direction="bullish"):
    """One consistent alert_companies row. Consistent on purpose: the INSERT
    trigger would refuse a contradictory one, and every test here is about
    what happens to a row that was legitimately persisted."""
    article = Article(
        source="test", url=f"https://example.test/{gate_state}-{economic_effect}",
        title="Crude spikes", content="body", status="ANALYZED",
    )
    db_session.add(article)
    db_session.flush()

    alert = Alert(article_id=article.id, category="commodity")
    db_session.add(alert)

    company = Company(
        ticker=f"OIL{abs(hash((gate_state, economic_effect))) % 9999}.NS",
        name="Oil India", sector="oil_gas", index_tier="NIFTY500",
    )
    db_session.add(company)
    db_session.flush()

    ac = AlertCompany(
        alert_id=alert.id, company_id=company.id,
        direction=direction, magnitude_low=1.0, magnitude_high=3.0,
        rationale="Upstream realization rises with crude.",
        confidence_score=70, time_horizon="Short-Term",
        basis="direct_mention", confidence="llm_estimate",
        impact_level="direct",
        economic_effect=economic_effect,
        gate_state=gate_state,
        display_tier="primary" if gate_state else None,
    )
    db_session.add(ac)
    db_session.commit()
    return ac


def test_trigger_blocks_direction_contradiction_on_gated_row(db_session):
    """§4: `economic_effect` is the ONE authoritative field and `direction`
    is derived from it. A gated positive-effect row can never be left
    bearish -- exactly the live OIL.NS contradiction."""
    ac = _seed(db_session, gate_state="DISPLAY_ELIGIBLE", economic_effect="positive")

    with pytest.raises(_REFUSED):
        db_session.execute(
            text("UPDATE alert_companies SET direction = 'bearish' WHERE id = :id"),
            {"id": ac.id})
        db_session.commit()
    db_session.rollback()

    still = db_session.execute(
        text("SELECT direction FROM alert_companies WHERE id = :id"),
        {"id": ac.id}).scalar()
    assert still == "bullish"


def test_trigger_blocks_negative_effect_turned_bullish(db_session):
    """The mirror case -- a gated negative-effect row can never be left
    bullish either."""
    ac = _seed(db_session, gate_state="DISPLAY_ELIGIBLE",
               economic_effect="negative", direction="bearish")

    with pytest.raises(_REFUSED):
        db_session.execute(
            text("UPDATE alert_companies SET direction = 'bullish' WHERE id = :id"),
            {"id": ac.id})
        db_session.commit()
    db_session.rollback()

    still = db_session.execute(
        text("SELECT direction FROM alert_companies WHERE id = :id"),
        {"id": ac.id}).scalar()
    assert still == "bearish"


def test_trigger_blocks_rationale_nulling_on_gated_row(db_session):
    """The stale worker's other signature move: clearing the rationale of a
    row whose direction it had just flipped. A gated row that HAD a
    rationale must never lose it -- the gate published it with that
    reasoning attached."""
    ac = _seed(db_session, gate_state="DISPLAY_ELIGIBLE")

    with pytest.raises(_REFUSED):
        db_session.execute(
            text("UPDATE alert_companies SET rationale = NULL WHERE id = :id"),
            {"id": ac.id})
        db_session.commit()
    db_session.rollback()

    still = db_session.execute(
        text("SELECT rationale FROM alert_companies WHERE id = :id"),
        {"id": ac.id}).scalar()
    assert still is not None


def test_trigger_blocks_contradictory_gated_insert(db_session):
    """Same shape on INSERT: a contradictory gated row must never LAND, not
    only never be updated into existence."""
    article = Article(source="t", url="https://example.test/insert",
                      title="t", content="c", status="ANALYZED")
    db_session.add(article)
    db_session.flush()
    alert = Alert(article_id=article.id, category="commodity")
    company = Company(ticker="BADINS.NS", name="Bad Insert", sector="oil_gas",
                      index_tier="OTHER")
    db_session.add_all([alert, company])
    db_session.flush()

    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=company.id,
        direction="bearish",  # contradicts economic_effect below
        magnitude_low=1.0, magnitude_high=2.0, rationale="r",
        confidence_score=50, time_horizon="Short-Term",
        basis="direct_mention", confidence="llm_estimate", impact_level="direct",
        economic_effect="positive", gate_state="DISPLAY_ELIGIBLE",
        display_tier="primary",
    ))
    with pytest.raises(_REFUSED):
        db_session.flush()
    db_session.rollback()


def test_ungated_legacy_row_updates_still_allowed(db_session):
    """A legacy row (gate_state IS NULL) has no gate semantics to protect.
    Both writes the trigger refuses on a gated row must still succeed here
    -- the backstop must not retroactively freeze the pre-V4 corpus."""
    ac = _seed(db_session, gate_state=None, economic_effect="positive")

    db_session.execute(
        text("UPDATE alert_companies SET direction = 'bearish', rationale = NULL "
             "WHERE id = :id"),
        {"id": ac.id})
    db_session.commit()

    row = db_session.execute(
        text("SELECT direction, rationale FROM alert_companies WHERE id = :id"),
        {"id": ac.id}).fetchone()
    assert row == ("bearish", None)


def test_consistent_update_on_gated_row_still_allowed(db_session):
    """The backstop is narrow: it refuses only the inconsistent end state.
    A gated row's ordinary fields stay writable."""
    ac = _seed(db_session, gate_state="DISPLAY_ELIGIBLE")

    db_session.execute(
        text("UPDATE alert_companies SET confidence_score = 88, "
             "rationale = 'refreshed reasoning' WHERE id = :id"),
        {"id": ac.id})
    db_session.commit()

    row = db_session.execute(
        text("SELECT confidence_score, rationale, direction "
             "FROM alert_companies WHERE id = :id"), {"id": ac.id}).fetchone()
    assert row == (88, "refreshed reasoning", "bullish")


# ---------------------------------------------------------------------------
# §26 idempotency: concurrent identical article processing
# ---------------------------------------------------------------------------


def test_duplicate_content_key_insert_rejected(db_session):
    """Two processes persisting the identical analysis of the identical
    article must collide at the DB, not both land. The second INSERT is
    caught by the caller and treated as idempotent success."""
    article = Article(source="t", url="https://example.test/idem",
                      title="t", content="c", status="ANALYZED")
    db_session.add(article)
    db_session.flush()

    db_session.add(Alert(article_id=article.id, category="commodity",
                         content_key="sha-abc123"))
    db_session.commit()

    db_session.add(Alert(article_id=article.id, category="commodity",
                         content_key="sha-abc123"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    assert db_session.execute(
        text("SELECT COUNT(*) FROM alerts WHERE article_id = :a"),
        {"a": article.id}).scalar() == 1


def test_null_content_key_alerts_are_not_constrained(db_session):
    """The index is PARTIAL (`WHERE content_key IS NOT NULL`) on purpose:
    the entire legacy corpus has no content key, and re-analysis of one
    article legitimately produces multiple alerts. Only rows that actually
    claim an identity are deduped."""
    article = Article(source="t", url="https://example.test/nullkey",
                      title="t", content="c", status="ANALYZED")
    db_session.add(article)
    db_session.flush()

    db_session.add_all([
        Alert(article_id=article.id, category="commodity"),
        Alert(article_id=article.id, category="commodity"),
    ])
    db_session.commit()

    assert db_session.execute(
        text("SELECT COUNT(*) FROM alerts WHERE article_id = :a"),
        {"a": article.id}).scalar() == 2


def test_different_content_keys_on_same_article_coexist(db_session):
    """Two genuinely different analyses of one article (different key) are
    not duplicates and must both persist."""
    article = Article(source="t", url="https://example.test/twokeys",
                      title="t", content="c", status="ANALYZED")
    db_session.add(article)
    db_session.flush()

    db_session.add_all([
        Alert(article_id=article.id, category="commodity", content_key="k1"),
        Alert(article_id=article.id, category="commodity", content_key="k2"),
    ])
    db_session.commit()

    assert db_session.execute(
        text("SELECT COUNT(*) FROM alerts WHERE article_id = :a"),
        {"a": article.id}).scalar() == 2


# ---------------------------------------------------------------------------
# §21/§22 columns the gate and the graph now persist
# ---------------------------------------------------------------------------


def test_blueprint_columns_are_writable_and_nullable(db_session):
    """T4-T8 consume these; they must exist on a create_all-built DB and
    default to NULL on rows that do not set them (the whole legacy
    corpus)."""
    ac = _seed(db_session, gate_state="DISPLAY_ELIGIBLE")
    assert ac.causal_directness is None
    assert ac.discovery_source is None
    assert ac.evidence_source is None
    assert ac.edge_relation is None
    assert ac.confidence_band is None

    ac.causal_directness = "DIRECT"
    ac.discovery_source = "ARTICLE_MENTION"
    ac.evidence_source = "PRIMARY"
    ac.edge_relation = "REVENUE_REALIZATION"
    ac.confidence_band = "HIGH"
    db_session.commit()

    row = db_session.execute(
        text("SELECT causal_directness, discovery_source, evidence_source, "
             "edge_relation, confidence_band FROM alert_companies WHERE id = :id"),
        {"id": ac.id}).fetchone()
    assert row == ("DIRECT", "ARTICLE_MENTION", "PRIMARY",
                   "REVENUE_REALIZATION", "HIGH")


def test_decision_record_carries_causal_directness(db_session):
    """The audit trail must record the directness the gate evaluated, not
    leave a postmortem to re-derive it from causal_distance (§11: DIRECT/
    INDIRECT is NOT derivable from d1/d2 alone)."""
    from app.models import CompanyDecisionRecord

    article = Article(source="t", url="https://example.test/dr",
                      title="t", content="c", status="ANALYZED")
    db_session.add(article)
    db_session.flush()
    alert = Alert(article_id=article.id, category="commodity")
    db_session.add(alert)
    db_session.flush()

    record = CompanyDecisionRecord(
        alert_id=alert.id, ticker="OIL.NS",
        final_state="DISPLAY_ELIGIBLE", display_tier="primary",
        causal_directness="DIRECT",
    )
    db_session.add(record)
    db_session.commit()

    assert db_session.execute(
        text("SELECT causal_directness FROM company_decision_records WHERE id = :id"),
        {"id": record.id}).scalar() == "DIRECT"
