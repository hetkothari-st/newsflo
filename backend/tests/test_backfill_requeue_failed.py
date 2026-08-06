"""The operator tool that un-strands ANALYSIS_FAILED articles.

ANALYSIS_FAILED is terminal: process_new_articles only reads
status="CATEGORIZED", so nothing ever revisits a failed article. Most of
those failures are transient provider rate limits, and 635 articles -- a
quarter of everything ever ingested -- were stranded that way in
production.
"""
from datetime import timedelta

import backfill_requeue_failed
from app.models import Article, utcnow


def _article(session, url, status, source="wire", age_days=0):
    article = Article(
        source=source, url=url, title="t", content="c", status=status,
        fetched_at=utcnow() - timedelta(days=age_days),
    )
    session.add(article)
    session.commit()
    return article


def test_requeues_failed_articles(db_session):
    failed = _article(db_session, "u1", "ANALYSIS_FAILED")
    result = backfill_requeue_failed.requeue_failed(db_session)

    assert db_session.get(Article, failed.id).status == "CATEGORIZED"
    assert result["requeued"] == 1
    assert result["failed_in_scope"] == 1


def test_leaves_every_other_status_alone(db_session):
    # Requeuing an ANALYZED article would duplicate its alert; requeuing a
    # FILTERED one would undo a deliberate rejection.
    kept = {status: _article(db_session, f"u-{status}", status)
            for status in ["NEW", "FILTERED", "CATEGORIZED", "ANALYZED"]}
    _article(db_session, "u-failed", "ANALYSIS_FAILED")

    result = backfill_requeue_failed.requeue_failed(db_session)

    for status, article in kept.items():
        assert db_session.get(Article, article.id).status == status
    assert result["requeued"] == 1


def test_dry_run_reports_but_writes_nothing(db_session):
    failed = _article(db_session, "u1", "ANALYSIS_FAILED")
    result = backfill_requeue_failed.requeue_failed(db_session, dry_run=True)

    assert result["requeued"] == 1  # reported, not applied
    assert result["dry_run"] is True
    assert db_session.get(Article, failed.id).status == "ANALYSIS_FAILED"


def test_dry_run_leaves_no_pending_state(db_session):
    """Autoflush trap: a query after a dry run must not persist a mutation.
    requeue_failed only ever assigns status inside the non-dry-run branch,
    so there is nothing pending for autoflush to leak.
    """
    failed = _article(db_session, "u1", "ANALYSIS_FAILED")
    backfill_requeue_failed.requeue_failed(db_session, dry_run=True)

    db_session.query(Article).filter_by(id=failed.id).one()  # triggers autoflush

    assert db_session.get(Article, failed.id).status == "ANALYSIS_FAILED"
    assert not db_session.dirty


def test_limit_caps_the_batch_and_reports_the_remainder(db_session):
    for n in range(5):
        _article(db_session, f"u{n}", "ANALYSIS_FAILED")

    result = backfill_requeue_failed.requeue_failed(db_session, limit=2)

    assert result["requeued"] == 2
    assert result["failed_in_scope"] == 5
    assert result["skipped_by_limit"] == 3
    requeued = db_session.query(Article).filter_by(status="CATEGORIZED").count()
    assert requeued == 2


def test_limit_takes_the_newest_first(db_session):
    old = _article(db_session, "old", "ANALYSIS_FAILED", age_days=30)
    new = _article(db_session, "new", "ANALYSIS_FAILED", age_days=1)

    backfill_requeue_failed.requeue_failed(db_session, limit=1)

    assert db_session.get(Article, new.id).status == "CATEGORIZED"
    assert db_session.get(Article, old.id).status == "ANALYSIS_FAILED"


def test_days_window_excludes_older_failures(db_session):
    recent = _article(db_session, "recent", "ANALYSIS_FAILED", age_days=2)
    ancient = _article(db_session, "ancient", "ANALYSIS_FAILED", age_days=40)

    result = backfill_requeue_failed.requeue_failed(db_session, days=7)

    assert db_session.get(Article, recent.id).status == "CATEGORIZED"
    assert db_session.get(Article, ancient.id).status == "ANALYSIS_FAILED"
    assert result["failed_in_scope"] == 1


def test_reports_a_per_source_breakdown(db_session):
    # A single source dominating the failures means a parsing bug, not a
    # quota blip -- that is what makes --dry-run worth running first.
    _article(db_session, "u1", "ANALYSIS_FAILED", source="globenewswire")
    _article(db_session, "u2", "ANALYSIS_FAILED", source="globenewswire")
    _article(db_session, "u3", "ANALYSIS_FAILED", source="reuters")

    result = backfill_requeue_failed.requeue_failed(db_session, dry_run=True)

    assert result["by_source"] == {"globenewswire": 2, "reuters": 1}


def test_no_failures_is_a_clean_no_op(db_session):
    _article(db_session, "u1", "ANALYZED")
    result = backfill_requeue_failed.requeue_failed(db_session)
    assert result == {
        "failed_in_scope": 0, "requeued": 0, "skipped_by_limit": 0,
        "by_source": {}, "dry_run": False,
    }
