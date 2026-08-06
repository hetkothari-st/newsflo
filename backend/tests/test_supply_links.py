"""Supply links from rating rationales.

Spec: docs/superpowers/specs/2026-08-06-supply-links-rating-rationales-
design.md. The load-bearing tests are the refusals: no evidence quote ->
no row; no exact name match -> NULL counterparty_company_id; no stored
links -> byte-identical prompt; LLM returns nothing -> zero ripple rows.
"""
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from app import config
from app.companies.supply_links import fetchers, snapshot
from app.models import Company, SupplyLink

FIXTURES = Path(__file__).parent / "fixtures" / "ratings"

AS_OF = date(2026, 8, 6)


def _company(session, ticker, name, sector="other"):
    company = Company(ticker=ticker, name=name, sector=sector, index_tier="OTHER")
    session.add(company)
    session.flush()
    return company


def test_supply_link_table_exists(db_session):
    company = _company(db_session, "RELIANCE.NS", "Reliance Industries")
    db_session.add(SupplyLink(
        company_id=company.id, relation="CUSTOMER",
        counterparty_name="Indian Oil Corporation", counterparty_company_id=None,
        evidence="derives a material share of revenue from Indian Oil Corporation",
        source_url="https://www.bseindia.com/xml-data/corpfiling/AttachLive/x.pdf",
        source_agency="CRISIL", as_of=AS_OF,
        extracted_at=datetime.now(timezone.utc),
    ))
    db_session.commit()
    got = db_session.query(SupplyLink).one()
    assert got.relation == "CUSTOMER"
    assert got.counterparty_company_id is None


def test_supply_caps_live_in_config():
    assert config.SUPPLY_LINK_MAX_PER_RELATION == 3
    assert config.SUPPLY_PROMPT_MAX_LINES == 8
    assert config.SUPPLY_PROMPT_MAX_CHARS == 700


# --- Task 3: announcements index + rationale document fetchers -----------
#
# Reality correction (Task 1's fixtures README, 2026-08-06): the rating
# agency name lives in HEADLINE, not NEWSSUB -- NEWSSUB is always generic
# LODR boilerplate ("<Company> - <code> - Announcement under Regulation 30
# (LODR)-Credit Rating"). parse_announcements must check HEADLINE first,
# falling back to NEWSSUB (belt and braces -- some filers do restate the
# agency there too). Row 4 below has the agency ONLY in NEWSSUB and must
# still match.


def test_parse_announcements_keeps_only_agency_rows_with_attachments():
    rows = [
        {"SCRIP_CD": "500325", "SLONGNAME": "Reliance", "NEWS_DT": "2026-08-01T10:00:00",
         "NEWSSUB": "Reliance - 500325 - Announcement under Regulation 30 (LODR)-Credit Rating",
         "HEADLINE": "CRISIL Ratings reaffirms AAA", "ATTACHMENTNAME": "abc.pdf"},
        {"SCRIP_CD": "500002", "SLONGNAME": "ABB", "NEWS_DT": "2026-08-01T10:00:00",
         "NEWSSUB": "ABB - 500002 - Announcement under Regulation 30 (LODR)-Board Meeting",
         "HEADLINE": "Intimation of board meeting", "ATTACHMENTNAME": "def.pdf"},
        {"SCRIP_CD": "500003", "SLONGNAME": "NoAttach", "NEWS_DT": "2026-08-01T10:00:00",
         "NEWSSUB": "ICRA assigns rating", "HEADLINE": "as per enclosed letter.",
         "ATTACHMENTNAME": ""},
        {"SCRIP_CD": "500004", "SLONGNAME": "NewsSubOnly", "NEWS_DT": "2026-08-01T10:00:00",
         "NEWSSUB": "NewsSubOnly - 500004 - ICRA assigns rating AA to facility",
         "HEADLINE": "as per enclosed letter.", "ATTACHMENTNAME": "ghi.pdf"},
    ]
    parsed = fetchers.parse_announcements(rows)
    assert len(parsed) == 2
    assert parsed[0]["scrip_code"] == "500325"
    assert parsed[0]["agency"] == "CRISIL"
    assert parsed[0]["attachment_url"].endswith("/AttachLive/abc.pdf")
    # NEWSSUB-only match (row 4) still counts -- belt and braces.
    assert parsed[1]["scrip_code"] == "500004"
    assert parsed[1]["agency"] == "ICRA"


def test_parse_announcements_handles_the_real_fixture_page():
    rows = json.loads((FIXTURES / "announcements_page.json").read_text(encoding="utf-8"))["Table"]
    parsed = fetchers.parse_announcements(rows)
    # The fixture was chosen because it contains at least one agency row
    # (in HEADLINE -- see fixtures/ratings/README.md).
    assert parsed, "fixture page must yield at least one rating rationale"
    assert all(p["attachment_url"] for p in parsed)


def test_fetch_announcements_splits_wide_ranges_into_windows(tmp_path):
    # BSE silently caps the date-range span at ~30 days (fixtures README);
    # a wider request must be paged as several <=28-day windows rather than
    # sent as one shot.
    requested = []

    def opener(url, timeout=60):
        requested.append(url)
        return json.dumps({"Table": [], "Table1": [{"ROWCNT": 0}]}).encode("utf-8")

    root = str(tmp_path)
    day = date(2026, 8, 6)
    rows = fetchers.fetch_announcements(
        root, day, date(2026, 6, 1), date(2026, 8, 6), opener=opener,
    )
    assert rows == []
    # 67-day span (inclusive) split into <=28-day windows -> 3 windows.
    assert len(requested) == 3
    for url in requested:
        assert "strPrevDate=" in url and "strToDate=" in url
    assert snapshot.index_path(root, day).exists()


def test_fetch_announcements_raises_on_status_false(tmp_path):
    # HTTP 200 with Status:false is BSE's "date range rejected" shape --
    # must never be silently read as "zero rows this period".
    def opener(url, timeout=60):
        return json.dumps(
            {"Status": False, "Message": "Date range exceeded threshold."}
        ).encode("utf-8")

    with pytest.raises(ValueError):
        fetchers.fetch_announcements(
            str(tmp_path), date(2026, 8, 6),
            date(2026, 6, 1), date(2026, 8, 6), opener=opener,
        )


def test_fetch_documents_resumes_and_respects_budget(tmp_path):
    targets = [
        {"scrip_code": "500325", "attachment_url": f"https://x/AttachLive/{i}.pdf"}
        for i in range(5)
    ]
    calls = []

    def opener(url, timeout=60):
        calls.append(url)
        return b"%PDF-1.4 fake"

    r1 = fetchers.fetch_documents(str(tmp_path), targets[:2], opener=opener,
                                  sleep=lambda _s: None, throttle_seconds=0)
    assert r1["fetched"] == 2
    r2 = fetchers.fetch_documents(str(tmp_path), targets, opener=opener,
                                  sleep=lambda _s: None, throttle_seconds=0)
    assert r2["skipped"] == 2 and r2["fetched"] == 3
    assert len(calls) == 5, "already-fetched docs must not be re-fetched"


def test_fetch_documents_stops_cleanly_on_budget(tmp_path):
    ticks = iter(range(100))
    targets = [{"scrip_code": "1", "attachment_url": f"https://x/AttachLive/{i}.pdf"}
               for i in range(10)]
    result = fetchers.fetch_documents(
        str(tmp_path), targets, opener=lambda u, timeout=60: b"%PDF",
        sleep=lambda _s: None, throttle_seconds=0,
        time_budget_seconds=3, clock=lambda: next(ticks),
    )
    assert result["exhausted"] is True
    assert 0 < result["fetched"] < 10


def test_fetch_documents_writes_url_and_meta_sidecars(tmp_path):
    root = str(tmp_path)
    targets = [{
        "scrip_code": "544317",
        "company_name": "Transrail Lighting Ltd",
        "agency": "IND-RA",
        "news_date": "2026-08-04T17:47:01.793",
        "attachment_url": "https://x/AttachLive/a.pdf",
    }]
    fetchers.fetch_documents(
        root, targets, opener=lambda u, timeout=60: b"%PDF-1.4 fake",
        sleep=lambda _s: None, throttle_seconds=0,
    )
    pdf_path = snapshot.doc_path(root, "544317", targets[0]["attachment_url"])
    assert pdf_path.exists()
    url_sidecar = pdf_path.with_suffix(".url")
    meta_sidecar = pdf_path.with_name(pdf_path.stem + ".meta.json")
    assert url_sidecar.read_text(encoding="utf-8").strip() == targets[0]["attachment_url"]
    meta = json.loads(meta_sidecar.read_text(encoding="utf-8"))
    assert meta == {
        "scrip_code": "544317",
        "company_name": "Transrail Lighting Ltd",
        "agency": "IND-RA",
        "news_date": "2026-08-04T17:47:01.793",
    }
    assert targets[0]["attachment_url"] in snapshot.fetched_doc_urls(root)


def test_pending_docs_and_mark_extracted(tmp_path):
    root = str(tmp_path)
    path = snapshot.doc_path(root, "500325", "https://x/AttachLive/a.pdf")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF")
    assert path in snapshot.pending_docs(root)
    snapshot.mark_extracted(path)
    assert path not in snapshot.pending_docs(root)
