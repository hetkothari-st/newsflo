"""Filters generic publisher artwork out of article image URLs so the
card front only ever shows a real news photo, never a wire-service or
newspaper logo banner (the og:image fallback many publishers serve for
wire stories).

Two independent, deterministic signals -- either one marks the image
generic:

1. Filename heuristic: the URL's basename (not the whole path -- some
   publishers keep real photos under a /logo/ directory) contains a
   telltale token ("logo", "placeholder", "default", ...).
2. Repetition: the same image_url attached to several DIFFERENT articles
   is publisher boilerplate, not a photo of any one story -- observed
   directly in production data (a market-site logo on 6 articles, a
   newspaper's default banner on 5), while genuine photos are unique per
   story. Threshold lives in app.config.

No image is ever downloaded or inspected -- URL string + count only.
"""
from urllib.parse import urlparse

from sqlalchemy import func
from sqlalchemy.orm import Session

from app import config
from app.models import Article

# Tokens that mark a basename as publisher artwork rather than a story
# photo. Checked against the FILENAME only -- path directories like
# livemint's /logo/ folder hold real photos and must not match.
_GENERIC_BASENAME_TOKENS = (
    "logo", "placeholder", "default", "favicon", "og-image", "og_image",
    "brand", "watermark", "fallback",
)


def is_generic_image_filename(image_url: str) -> bool:
    basename = urlparse(image_url).path.rsplit("/", 1)[-1].lower()
    return any(token in basename for token in _GENERIC_BASENAME_TOKENS)


def repeated_image_urls(session: Session, image_urls: list[str]) -> set[str]:
    """The subset of ``image_urls`` attached to at least
    config.GENERIC_IMAGE_REPEAT_THRESHOLD articles -- publisher
    boilerplate by the repetition signal. One grouped query for the whole
    batch (the feed list serializes up to 200 alerts per request)."""
    unique = [u for u in set(image_urls) if u]
    if not unique:
        return set()
    rows = (
        session.query(Article.image_url, func.count(Article.id))
        .filter(Article.image_url.in_(unique))
        .group_by(Article.image_url)
        .having(func.count(Article.id) >= config.GENERIC_IMAGE_REPEAT_THRESHOLD)
        .all()
    )
    return {url for url, _count in rows}


def resolve_article_image(
    article_url: str,
    provided_image_url: str | None,
    fetch=None,
    resolve_wrapper=None,
    provided_is_generic: bool = False,
) -> str | None:
    """Ingest-time image resolution: prefer a real story photo over
    publisher artwork. A provided image with a clean filename is kept
    as-is (no extra HTTP). When the feed API handed us a generic image
    (wire-service logo -- Finnhub does this for Reuters stories) or none
    at all, fetch the article page's own og:image, which is usually the
    genuine photo; keep it only when IT isn't generic too. Falls back to
    whatever existed -- the serve-time filter (displayable_image_url)
    still decides what reaches a card.

    Google News wrapper links are resolved to the real publisher URL
    first -- the wrapper page's own og:image is Google's logo, never the
    story photo. When resolution fails, NO og fetch happens for that
    article (fetching would only harvest Google's logo).

    ``provided_is_generic`` lets callers flag a provided image the
    REPETITION signal already condemned (wire-service boilerplate with a
    clean filename, e.g. GlobeNewswire's default banner) -- the filename
    heuristic alone cannot see that, and without the flag such an image
    early-returns untouched and never gets a real-photo re-fetch.
    """
    if fetch is None:
        from app.ingestion.og_image import fetch_og_image  # late import: circular-free
        fetch = fetch_og_image
    if resolve_wrapper is None:
        from app.ingestion.google_news import is_google_news_url, resolve_google_news_url

        def resolve_wrapper(url):
            if not is_google_news_url(url):
                return url
            return resolve_google_news_url(url)  # None on failure -> skip og fetch

    if (
        provided_image_url
        and not provided_is_generic
        and not is_generic_image_filename(provided_image_url)
    ):
        return provided_image_url
    target_url = resolve_wrapper(article_url)
    if target_url is None:
        return provided_image_url
    fetched = fetch(target_url)
    if fetched and not is_generic_image_filename(fetched):
        return fetched
    return provided_image_url or fetched


def displayable_image_url(image_url: str | None, repeated: set[str]) -> str | None:
    """The image_url fit to show on a card, or None when it's generic
    publisher artwork (omit rather than show a wrong image -- same
    discipline as every other field)."""
    if image_url is None:
        return None
    if image_url in repeated:
        return None
    if is_generic_image_filename(image_url):
        return None
    return image_url
