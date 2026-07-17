import httpx
import trafilatura

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
