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
