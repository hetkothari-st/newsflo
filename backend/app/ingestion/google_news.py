"""Resolves a Google News RSS wrapper URL (news.google.com/rss/articles/
<opaque-id>) to the real publisher article URL, via Google's own
batchexecute endpoint -- the same mechanism the googlenewsdecoder library
uses. Needed because most Finnhub items link to the Google News wrapper,
whose own og:image is Google's logo, never the story photo (see
app.ingestion.image_filter.resolve_article_image).

Same "never raise, degrade to None" contract as fetch_og_image: a
resolution failure means "leave the article as it was", never a crashed
pipeline. Two HTTP calls per resolution -- only invoked when an article
needs an image re-fetch, not on every ingest.
"""
import json
from urllib.parse import quote, urlparse

import httpx
from bs4 import BeautifulSoup

_TIMEOUT = 5.0
_USER_AGENT = "Mozilla/5.0 (compatible; NewsFloBot/1.0)"
_BATCHEXECUTE_URL = "https://news.google.com/_/DotsSplashUi/data/batchexecute"


def is_google_news_url(url: str) -> bool:
    return urlparse(url).netloc.endswith("news.google.com")


def _article_id(url: str) -> str | None:
    path_parts = [p for p in urlparse(url).path.split("/") if p]
    for marker in ("articles", "read"):
        if marker in path_parts:
            index = path_parts.index(marker)
            if index + 1 < len(path_parts):
                return path_parts[index + 1]
    return None


def resolve_google_news_url(url: str) -> str | None:
    """The real publisher URL behind a Google News wrapper link, or None
    when ``url`` isn't a Google News link or the resolution fails."""
    if not is_google_news_url(url):
        return None
    article_id = _article_id(url)
    if article_id is None:
        return None
    try:
        page = httpx.get(
            f"https://news.google.com/articles/{article_id}",
            timeout=_TIMEOUT, follow_redirects=True, headers={"User-Agent": _USER_AGENT},
        )
        page.raise_for_status()
        soup = BeautifulSoup(page.text, "html.parser")
        data_element = soup.select_one("c-wiz > div[jscontroller]")
        if data_element is None:
            return None
        signature = data_element.get("data-n-a-sg")
        timestamp = data_element.get("data-n-a-ts")
        if not signature or not timestamp:
            return None

        inner = (
            '["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,null,null,'
            'null,null,null,0,1],"X","X",1,[1,1,1],1,1,null,0,0,null,0],'
            f'"{article_id}",{timestamp},"{signature}"]'
        )
        body = "f.req=" + quote(json.dumps([[["Fbv4je", inner, "null", "generic"]]]))
        response = httpx.post(
            _BATCHEXECUTE_URL, content=body, timeout=_TIMEOUT,
            headers={
                "User-Agent": _USER_AGENT,
                "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            },
        )
        response.raise_for_status()
        # Response: anti-JSON prefix line(s), then a JSON array whose
        # ["wrb.fr","Fbv4je","<json-string>"] envelope wraps another JSON
        # array with the decoded URL at index 1.
        for line in response.text.splitlines():
            line = line.strip()
            if not line.startswith("[["):
                continue
            envelope = json.loads(line)
            payload = json.loads(envelope[0][2])
            decoded = payload[1]
            if isinstance(decoded, str) and decoded.startswith("http"):
                return decoded
        return None
    except Exception:
        return None
