"""One-off backfill: fetch og:image for every already-analyzed article that
predates the image_url column (or whose earlier fetch failed/returned none).

Not part of the test suite and not imported by the app. Safe to re-run --
only targets articles still missing an image, and commits after each one so
an interrupted run keeps whatever progress it made.

Usage (from the backend/ directory, so `app` is importable):
    .venv/Scripts/python backfill_images.py
"""
import time

from app.db import SessionLocal, init_db
from app.ingestion.og_image import fetch_og_image
from app.models import Article

# Be polite to the source sites -- this can hit dozens of distinct hosts in
# one run, all fired from the same process back to back.
DELAY_BETWEEN_FETCHES_SECONDS = 0.5


def main() -> None:
    init_db()
    session = SessionLocal()
    try:
        pending = (
            session.query(Article)
            .filter(Article.status == "ANALYZED")
            .filter(Article.image_url.is_(None))
            .all()
        )
        print(f"{len(pending)} analyzed article(s) missing an image.")

        found = 0
        for i, article in enumerate(pending, start=1):
            image_url = fetch_og_image(article.url)
            if image_url is not None:
                article.image_url = image_url
                session.commit()
                found += 1
                print(f"[{i}/{len(pending)}] found: {article.title[:60]}")
            else:
                print(f"[{i}/{len(pending)}] no image: {article.title[:60]}")
            time.sleep(DELAY_BETWEEN_FETCHES_SECONDS)

        print(f"Done. {found}/{len(pending)} articles backfilled with an image.")
    finally:
        session.close()


if __name__ == "__main__":
    main()
