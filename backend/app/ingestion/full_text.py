import httpx
import trafilatura
from sqlalchemy.orm import Session

from app.models import Article, utcnow

_TIMEOUT = 10.0
_USER_AGENT = "Mozilla/5.0 (compatible; NewsFloBot/1.0)"


def fetch_full_text(url: str) -> str | None:
    """Fetch the article's own page and extract its main body text, or
    None on any failure (timeout, non-2xx, paywall, JS-rendered page
    trafilatura can't parse, no extractable content). Never raises -- same
    "degrade to None" contract as app.ingestion.og_image.fetch_og_image.
    10s timeout (double fetch_og_image's 5s) since this reads the full
    page body, not just <head> meta tags.
    """
    try:
        response = httpx.get(
            url, timeout=_TIMEOUT, follow_redirects=True, headers={"User-Agent": _USER_AGENT},
        )
        response.raise_for_status()
        return trafilatura.extract(response.text)
    except Exception:
        return None


def fetch_pending_full_text(session: Session) -> None:
    """For every NEW article that hasn't had a full-text fetch attempted
    yet, try once to fetch and extract its body text. Always marks the
    attempt timestamp regardless of success, so a permanently-unreachable
    URL (dead link, hard paywall) is never retried -- it just proceeds
    with summary-only text for the rest of the pipeline. Commits after
    each article (not batched) so a mid-run crash doesn't lose already-
    fetched articles.
    """
    articles = (
        session.query(Article)
        .filter_by(status="NEW")
        .filter(Article.full_content_fetch_attempted_at.is_(None))
        .all()
    )
    for article in articles:
        article.full_content = fetch_full_text(article.url)
        article.full_content_fetch_attempted_at = utcnow()
        session.commit()
