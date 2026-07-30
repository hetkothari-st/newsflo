"""Backfill: fetch og:image for already-analyzed articles that are missing
an image OR are stuck with generic publisher artwork (a wire-service logo
or newspaper default banner -- what Finnhub hands over for Reuters wire
stories, and what the serve-time filter now nulls out). Re-fetching the
article's own page usually yields the genuine story photo.

Not part of the test suite and not imported by the app. Safe to re-run --
commits after each article so an interrupted run keeps whatever progress
it made.

Usage (from the backend/ directory, so `app` is importable):
    .venv/Scripts/python backfill_images.py [--days N]

--days N limits the run to articles fetched in the last N days -- the
feed only surfaces today's alerts, so a scoped run fixes what users
actually see in minutes instead of re-crawling the whole archive.
"""
import argparse
import time
from datetime import timedelta

from sqlalchemy import func

from app.db import SessionLocal, init_db
from app.ingestion.image_filter import is_generic_image_filename, resolve_article_image
from app.models import Article, utcnow
from app import config

# Be polite to the source sites -- this can hit dozens of distinct hosts in
# one run, all fired from the same process back to back.
DELAY_BETWEEN_FETCHES_SECONDS = 0.5


def _repeated_urls(session) -> set[str]:
    rows = (
        session.query(Article.image_url, func.count(Article.id))
        .filter(Article.image_url.isnot(None))
        .group_by(Article.image_url)
        .having(func.count(Article.id) >= config.GENERIC_IMAGE_REPEAT_THRESHOLD)
        .all()
    )
    return {url for url, _count in rows}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=None, help="only articles fetched in the last N days")
    args = parser.parse_args()

    init_db()
    session = SessionLocal()
    try:
        repeated = _repeated_urls(session)
        query = session.query(Article).filter(Article.status == "ANALYZED")
        if args.days is not None:
            query = query.filter(Article.fetched_at >= utcnow() - timedelta(days=args.days))
        analyzed = query.all()
        pending = [
            a for a in analyzed
            if a.image_url is None
            or a.image_url in repeated
            or is_generic_image_filename(a.image_url)
        ]
        print(f"{len(pending)} analyzed article(s) missing an image or stuck with publisher artwork.")

        found = 0
        for i, article in enumerate(pending, start=1):
            # resolve_article_image handles the whole chain: Google News
            # wrapper resolution -> publisher og:image -> generic checks.
            # provided_is_generic carries the repetition verdict -- a
            # boilerplate image with a clean filename must still trigger
            # the real-photo re-fetch.
            resolved = resolve_article_image(
                article.url, article.image_url,
                provided_is_generic=article.image_url in repeated,
            )
            # ASCII-safe printing -- Windows consoles choke on unicode titles.
            title = article.title[:60].encode("ascii", "replace").decode()
            if resolved is not None and resolved != article.image_url:
                article.image_url = resolved
                session.commit()
                found += 1
                print(f"[{i}/{len(pending)}] found: {title}")
            else:
                # Keep whatever was there -- the serve-time filter decides
                # what reaches a card; never overwrite with a worse image.
                print(f"[{i}/{len(pending)}] no better image: {title}")
            time.sleep(DELAY_BETWEEN_FETCHES_SECONDS)

        print(f"Done. {found}/{len(pending)} articles now carry a real story photo.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
