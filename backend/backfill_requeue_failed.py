"""Flip ANALYSIS_FAILED articles back to CATEGORIZED so the pipeline gets
another pass at them.

WHY THIS EXISTS: process_new_articles only ever picks up status
"CATEGORIZED". When analyze_article fails twice it writes ANALYSIS_FAILED,
and nothing in the system ever reads that status again -- it is terminal.
Most of those failures are not permanent: they are provider rate
limits/quota exhaustion during a burst, and the same article would analyze
fine an hour later. Measured in production: 635 articles, a quarter of
everything ever ingested, permanently stranded this way.

WHY IT IS AN OPERATOR TOOL AND NOT AUTOMATIC: an article that fails for a
genuine, permanent reason -- an empty body, content the model refuses,
something malformed -- would be requeued, fail, be requeued again, forever,
burning the same quota that stranded it in the first place. Requeuing has
to be a decision someone makes after looking at counts, so it lives here
rather than inside the pipeline.

    python backfill_requeue_failed.py --dry-run
    python backfill_requeue_failed.py --days 7 --limit 100
    python backfill_requeue_failed.py

--days filters on fetched_at (not published_at, which is nullable and often
absent on wire items), and requeues the MOST RECENT failures first, since a
transient-quota backlog is overwhelmingly recent and recent articles are the
ones still worth showing.
"""
import argparse
from collections import Counter
from datetime import timedelta

from sqlalchemy.orm import Session

from app.models import Article, utcnow

FAILED_STATUS = "ANALYSIS_FAILED"
REQUEUE_STATUS = "CATEGORIZED"


def requeue_failed(
    session: Session, limit: int | None = None, days: int | None = None, dry_run: bool = False,
) -> dict:
    """Move ANALYSIS_FAILED articles back to CATEGORIZED.

    Returns a report: how many failed articles exist in scope, how many were
    requeued, and a per-source breakdown -- the breakdown is the point of
    --dry-run, because a single source dominating the failures means a
    parsing bug, not a quota blip, and those articles should not be requeued
    until it is fixed.

    dry_run never assigns to ``article.status`` at all (rather than assigning
    and relying on a rollback), so there is nothing pending for autoflush to
    leak into the caller's transaction -- same discipline as
    backfill_reclassify.reclassify.
    """
    query = session.query(Article).filter(Article.status == FAILED_STATUS)
    if days is not None:
        query = query.filter(Article.fetched_at >= utcnow() - timedelta(days=days))

    # Newest first: a rate-limit backlog is recent, and if --limit cuts the
    # set short the recent articles are the ones still worth publishing.
    query = query.order_by(Article.fetched_at.desc(), Article.id.desc())

    in_scope = query.count()
    if limit is not None:
        query = query.limit(limit)

    articles = query.all()
    by_source = Counter(article.source for article in articles)

    if not dry_run:
        for article in articles:
            article.status = REQUEUE_STATUS
        session.commit()

    return {
        "failed_in_scope": in_scope,
        "requeued": len(articles),
        "skipped_by_limit": in_scope - len(articles),
        "by_source": dict(by_source),
        "dry_run": dry_run,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=None, help="requeue at most N articles (newest first)")
    parser.add_argument("--days", type=int, default=None, help="only articles fetched within the last N days")
    parser.add_argument("--dry-run", action="store_true", help="report what would be requeued, write nothing")
    args = parser.parse_args()

    from app.db import SessionLocal

    session = SessionLocal()
    try:
        result = requeue_failed(session, limit=args.limit, days=args.days, dry_run=args.dry_run)
        print("DRY RUN -- reporting only, writing nothing" if args.dry_run else "APPLIED")
        print(f"  {FAILED_STATUS} in scope : {result['failed_in_scope']}")
        print(f"  requeued to {REQUEUE_STATUS}: {result['requeued']}")
        print(f"  skipped by --limit      : {result['skipped_by_limit']}")
        for source, count in sorted(result["by_source"].items(), key=lambda kv: -kv[1]):
            print(f"    {source:40s} {count}")
        print("DRY RUN complete -- nothing was written" if args.dry_run else "done")
    finally:
        session.close()


if __name__ == "__main__":
    main()
