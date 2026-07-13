import httpx
from bs4 import BeautifulSoup

_TIMEOUT = 5.0
_USER_AGENT = "Mozilla/5.0 (compatible; NewsFloBot/1.0)"
_IMAGE_META_PROPS = ("og:image", "twitter:image")


def fetch_og_image(url: str) -> str | None:
    """Fetch the article page and return its Open Graph / Twitter Card image
    URL, or ``None`` on any failure (timeout, non-2xx, no such tag).

    A missing image is not an error -- see the try/except-swallow convention
    in outcomes/price_fetcher.py -- a single article's failed fetch must
    never block the rest of the pipeline.
    """
    try:
        response = httpx.get(
            url, timeout=_TIMEOUT, follow_redirects=True, headers={"User-Agent": _USER_AGENT},
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for prop in _IMAGE_META_PROPS:
            tag = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
            content = tag.get("content") if tag else None
            if content:
                return content
        return None
    except Exception:
        return None
