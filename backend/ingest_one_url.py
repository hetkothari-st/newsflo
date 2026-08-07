"""One-off: ingest a single news URL through the REAL pipeline.

Creates one Article row (status NEW) from the given URL -- title and
body extracted from the page itself via the same trafilatura path the
live pipeline uses -- then runs the standard filter -> analyze ->
resolve -> alert -> measure pipeline over it. Nothing is faked: the
LLM analysis, company resolution, market measurement and confidence
scoring are exactly what the scheduler would have produced had an
ingestion source surfaced this URL.

Usage:
    python ingest_one_url.py <url> [--source "ET BFSI"]

Idempotent by URL: refuses to insert a duplicate Article row.
"""
import argparse
import re
import sys
from datetime import timezone

import httpx
import trafilatura

from app.analysis.claude_client import build_client
from app.config import settings
from app.db import SessionLocal
from app.ingestion.full_text import _TIMEOUT, _USER_AGENT
from app.models import Article, utcnow
from app.pipeline import process_new_articles


def fetch_page(url: str) -> tuple[str, str]:
    """(title, body) extracted from the article page. Raises on failure --
    a one-off script should fail loudly, not degrade."""
    response = httpx.get(
        url, timeout=_TIMEOUT, follow_redirects=True, headers={"User-Agent": _USER_AGENT},
    )
    response.raise_for_status()
    body = trafilatura.extract(response.text)
    if not body:
        raise SystemExit("trafilatura could not extract article body")
    title_match = re.search(r"<title[^>]*>(.*?)</title>", response.text, re.DOTALL | re.IGNORECASE)
    title = (title_match.group(1) if title_match else "").strip()
    # Publisher suffixes ("... - ET BFSI") stay -- the dedup key is the
    # normalized full title, same as live ingestion sees it.
    if not title:
        raise SystemExit("no <title> on the page")
    return title, body


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--source", default=None, help="source label; defaults to the domain")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        article = session.query(Article).filter_by(url=args.url).one_or_none()
        if article is not None and article.status == "ANALYZED":
            print(f"Already analyzed (article id={article.id}); nothing to do.")
            return
        if article is not None:
            # Retry path: an earlier run inserted the row but the pipeline
            # failed mid-way (e.g. provider rate limit). Reset a hard-failed
            # status so the pipeline picks it up again.
            if article.status == "ANALYSIS_FAILED":
                article.status = "CATEGORIZED"
                session.commit()
            print(f"Resuming article id={article.id} (status {article.status})")
        else:
            title, body = fetch_page(args.url)
            source = args.source or httpx.URL(args.url).host
            article = Article(
                source=source,
                url=args.url,
                title=title,
                content=body,
                full_content=body,
                full_content_fetch_attempted_at=utcnow(),
                published_at=utcnow().astimezone(timezone.utc),
                image_url=None,
                status="NEW",
            )
            session.add(article)
            session.commit()
            print(f"Article id={article.id} inserted: {title[:90]}")

        client = build_client(settings.groq_api_keys, settings.gemini_api_key or None)
        created = process_new_articles(session, client, throttle_seconds=2.5)
        print(f"Pipeline done: {created} alert(s) created.")

        session.refresh(article)
        print(f"Article status: {article.status}")
        if article.status == "ANALYZED":
            from app.models import Alert

            alert = session.query(Alert).filter_by(article_id=article.id).one_or_none()
            if alert:
                print(f"Alert id={alert.id}, category={alert.category}, companies={len(alert.companies)}")
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
