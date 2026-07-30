"""Backfill: fetch og:image for already-analyzed articles that are missing
an image OR are stuck with generic publisher artwork (a wire-service logo
or newspaper default banner -- what Finnhub hands over for Reuters wire
stories, and what the serve-time filter now nulls out). Re-fetching the
article's own page usually yields the genuine story photo.

Not part of the test suite and not imported by the app. Safe to re-run --
commits after each article so an interrupted run keeps whatever progress
it made.

Usage (from the backend/ directory, so `app` is importable):
    .venv/Scripts/python backfill_images.py
"""
import time

from sqlalchemy import func

from app.db import SessionLocal, init_db
from app.ingestion.image_filter import is_generic_image_filename
from app.ingestion.og_image import fetch_og_image
from app.models import Article
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
    init_db()
    session = SessionLocal()
    try:
        repeated = _repeated_urls(session)
        analyzed = session.query(Article).filter(Article.status == "ANALYZED").all()
        pending = [
            a for a in analyzed
            if a.image_url is None
            or a.image_url in repeated
            or is_generic_image_filename(a.image_url)
        ]
        print(f"{len(pending)} analyzed article(s) missing an image or stuck with publisher artwork.")

        found = 0
        for i, article in enumerate(pending, start=1):
            image_url = fetch_og_image(article.url)
            usable = (
                image_url is not None
                and image_url != article.image_url
                and not is_generic_image_filename(image_url)
            )
            if usable:
                article.image_url = image_url
                session.commit()
                found += 1
                print(f"[{i}/{len(pending)}] found: {article.title[:60]}")
            else:
                # Keep whatever was there -- the serve-time filter decides
                # what reaches a card; never overwrite with a worse image.
                print(f"[{i}/{len(pending)}] no better image: {article.title[:60]}")
            time.sleep(DELAY_BETWEEN_FETCHES_SECONDS)

        print(f"Done. {found}/{len(pending)} articles now carry a real story photo.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
