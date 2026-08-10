"""BSE corporate announcements provider (AnnSubCategoryGetData JSON API).

Reuses the browser headers the universe/supply-links fetchers already use
against api.bseindia.com (app/companies/universe/fetchers.py) -- BSE
rejects non-browser User-Agents and requires a Referer.

Two BSE quirks inherited from the supply-links investigation
(app/companies/supply_links/fetchers.py, probed 2026-08-06):
* rejected queries return HTTP 200 with {"Status": false, "Message": ...},
  never a 4xx -- must be checked explicitly or an error reads as "no news";
* rows carry no article URL. The stable announcement id (NEWSID) both
  synthesizes a canonical detail-page URL and serves as
  provider_article_id.

The announcement category for the exchange-noise gate is parsed from
NEWSSUB, whose fixed LODR shape is
"<Company> - <scrip> - Announcement under Regulation 30 (LODR)-<Category>".
"""
import re
from datetime import datetime, timedelta, timezone

import httpx

from app.ingestion.providers.base import Checkpoint, NormalizedArticle

ANNOUNCEMENTS_URL = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
ANNOUNCEMENT_PAGE_URL = "https://www.bseindia.com/corporates/anndet_new.aspx?newsid={newsid}"
FETCH_TIMEOUT_SECONDS = 20

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.bseindia.com/",
}

# "... - Announcement under Regulation 30 (LODR)-Newspaper Publication"
_NEWSSUB_CATEGORY_RE = re.compile(r"\(LODR\)\s*-\s*(?P<category>.+?)\s*$")

# NEWS_DT is IST wall-clock without an offset ("2026-08-10T13:06:50.813").
IST = timezone(timedelta(hours=5, minutes=30))


def _parse_news_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    aware = parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=IST)
    return aware.astimezone(timezone.utc)


class BseAnnouncementsProvider:
    slug = "bse"
    display_name = "BSE Announcements"
    default_poll_interval_minutes = 5
    max_items_per_poll = 200

    def is_configured(self) -> bool:
        return True  # public endpoint, no key

    def fetch(self, checkpoint: Checkpoint) -> list[dict]:
        today = datetime.now(IST).strftime("%Y%m%d")
        response = httpx.get(
            ANNOUNCEMENTS_URL,
            params={
                "pageno": 1,
                "strCat": "-1",
                "subcategory": "-1",
                "strPrevDate": today,
                "strToDate": today,
                "strScrip": "",
                "strSearch": "P",
                "strType": "C",
            },
            headers=BROWSER_HEADERS,
            timeout=FETCH_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and payload.get("Status") is False:
            raise ValueError(f"BSE rejected the announcements query: {payload.get('Message', 'no message')!r}")
        rows = payload.get("Table") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise ValueError(f"BSE returned no Table list: {payload!r:.200}")
        return [row for row in rows if isinstance(row, dict)]

    def normalize(self, raw_item: dict) -> NormalizedArticle | None:
        newsid = raw_item.get("NEWSID")
        if not newsid:
            return None
        newssub = (raw_item.get("NEWSSUB") or "").strip()
        headline = (raw_item.get("HEADLINE") or "").strip()
        more = (raw_item.get("MORE") or "").strip()
        category_match = _NEWSSUB_CATEGORY_RE.search(newssub)
        source_category = category_match.group("category").strip() if category_match else None
        return NormalizedArticle(
            source="bse",
            url=ANNOUNCEMENT_PAGE_URL.format(newsid=newsid),
            title=newssub or headline[:200],
            content=headline or more,
            published_at=_parse_news_dt(raw_item.get("NEWS_DT") or raw_item.get("DT_TM")),
            provider_article_id=str(newsid),
            source_category=source_category,
            raw=raw_item,
        )

    def next_checkpoint(self, raw_items: list[dict], previous: Checkpoint) -> Checkpoint:
        return previous  # today-window poll + NEWSID idempotency, no cursor
