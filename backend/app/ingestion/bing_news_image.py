"""Real story photos via Bing News search (no API key): searching the
exact headline returns the story with Bing's cached copy of the article's
own image -- which works even for publishers that block direct scraping
outright (Reuters, Bloomberg, BusinessWire all 401/403 any client, but
their photos are already in Bing's news cache). Verified live against
production headlines.

Guarded against the wrong-image failure mode: the top result's title must
substantially overlap the query headline (token containment) or nothing
is returned -- a wrong photo is worse than no photo.

Same "never raise, degrade to None" contract as fetch_og_image.
"""
import html
import re

import httpx

_TIMEOUT = 8.0
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36"}
# Minimum share of the headline's significant tokens that must appear in
# the matched result's title.
_MIN_TITLE_OVERLAP = 0.6
_STOPWORDS = {"the", "a", "an", "of", "to", "in", "on", "for", "and", "as", "at", "by", "with", "-"}


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if token not in _STOPWORDS and len(token) > 1
    }


def _title_overlap(headline: str, candidate_title: str) -> float:
    headline_tokens = _tokens(headline)
    if not headline_tokens:
        return 0.0
    return len(headline_tokens & _tokens(candidate_title)) / len(headline_tokens)


def fetch_bing_news_image(headline: str) -> str | None:
    """The story's own image for ``headline`` from Bing News, or None."""
    try:
        response = httpx.get(
            "https://www.bing.com/news/search",
            params={"q": headline, "format": "rss"},
            timeout=_TIMEOUT,
            follow_redirects=True,
            headers=_HEADERS,
        )
        response.raise_for_status()
        for item in re.findall(r"<item>(.*?)</item>", response.text, re.S):
            title_match = re.search(r"<title>(.*?)</title>", item, re.S)
            image_match = re.search(r"<News:Image>(.*?)</News:Image>", item, re.S)
            if not title_match or not image_match:
                continue
            candidate_title = html.unescape(title_match.group(1))
            if _title_overlap(headline, candidate_title) < _MIN_TITLE_OVERLAP:
                continue
            image_url = html.unescape(image_match.group(1)).strip()
            if not image_url:
                continue
            # Bing's th endpoint accepts sizing params; request a card-
            # sized crop and force https.
            image_url = image_url.replace("http://", "https://")
            separator = "&" if "?" in image_url else "?"
            return f"{image_url}{separator}w=800&h=450&c=14"
        return None
    except Exception:
        return None
