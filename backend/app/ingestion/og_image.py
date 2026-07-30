from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

_TIMEOUT = 5.0
# Browser-like headers, not a bot UA: verified live that GlobeNewswire and
# SeekingAlpha serve their real story photos (og:image) to a browser UA
# but block/limit "NewsFloBot" -- with the bot UA those articles could
# never get a photo at all. (Reuters/Bloomberg/BusinessWire block plain
# HTTP clients regardless of UA; their cards stay imageless.)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}
_IMAGE_META_PROPS = ("og:image", "twitter:image")


def fetch_og_image(url: str) -> str | None:
    """Fetch the article page and return its Open Graph / Twitter Card image
    URL, or ``None`` on any failure (timeout, non-2xx, no such tag).

    A missing image is not an error -- see the try/except-swallow convention
    in outcomes/price_fetcher.py -- a single article's failed fetch must
    never block the rest of the pipeline.
    """
    try:
        response = httpx.get(url, timeout=_TIMEOUT, follow_redirects=True, headers=_HEADERS)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for prop in _IMAGE_META_PROPS:
            tag = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
            content = tag.get("content") if tag else None
            if content:
                # Some publishers emit a relative og:image path -- resolve it
                # against the (post-redirect) page URL so a usable absolute
                # URL is stored, never a broken relative one. Fall back to
                # the request URL when the response object carries none
                # (stubbed responses in tests).
                base = str(getattr(response, "url", None) or url)
                return urljoin(base, content)
        return None
    except Exception:
        return None
