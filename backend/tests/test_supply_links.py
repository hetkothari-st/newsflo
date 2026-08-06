"""Supply links from rating rationales.

Spec: docs/superpowers/specs/2026-08-06-supply-links-rating-rationales-
design.md. The load-bearing tests are the refusals: no evidence quote ->
no row; no exact name match -> NULL counterparty_company_id; no stored
links -> byte-identical prompt; LLM returns nothing -> zero ripple rows.
"""
import json
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.analysis.cascade as cascade_module
import app.pipeline as pipeline_module
from app import config
from app.analysis.cascade import _identify_companies, _identify_companies_per_sector
from app.analysis.schemas import AnalysisOutput, CompanyMention, SectorFinding
from app.companies.supply_links import extract, fetchers, loader, prompting, snapshot
from app.models import Alert, AlertCompany, Article, Company, CompanyAlias, ImpactEdge, SupplyLink

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
    assert config.SUPPLY_PROMPT_MAX_CHARS == 500
    assert config.SUPPLY_PROMPT_MAX_EXTRAS == 5


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


def test_fetch_announcements_pagination_hard_cap_prevents_infinite_loop(tmp_path):
    # A real class of upstream pagination bug: BSE repeats the last full
    # page for every pageno instead of ever returning a short page. With
    # no ROWCNT to use as a cheaper stop, the pager must hit _MAX_PAGES and
    # raise rather than loop forever.
    calls = {"n": 0}

    def opener(url, timeout=60):
        calls["n"] += 1
        if calls["n"] > 45:
            # Test-side guard: if the fix regresses, fail fast and loud
            # instead of hanging the test run.
            raise AssertionError("loop ran away")
        return json.dumps({"Table": [{"NEWSID": "x"}] * 50}).encode("utf-8")

    with pytest.raises(ValueError):
        fetchers.fetch_announcements(
            str(tmp_path), date(2026, 8, 6),
            date(2026, 8, 1), date(2026, 8, 6), opener=opener,
        )


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


# --- Task 4: extraction -- PDF text, LLM-as-reader, evidence gate --------


def test_evidence_gate_is_whitespace_normalized():
    text = "The company  derives ~60% of\nrevenue from Indian Railways."
    assert extract._evidence_in_text("derives ~60% of revenue from Indian Railways", text)
    assert not extract._evidence_in_text("supplies steel to Tata Motors", text)


def test_entries_without_provable_evidence_are_discarded(monkeypatch):
    text = "Alpha Ltd manufactures castings. It derives most revenue from Indian Railways."
    payload = {
        "business_summary": "Alpha Ltd manufactures castings for rail applications.",
        "suppliers": [],
        "customers": [
            {"name": "Indian Railways", "evidence": "derives most revenue from Indian Railways"},
            {"name": "Tata Motors", "evidence": "supplies castings to Tata Motors"},  # not in text
        ],
    }
    monkeypatch.setattr(extract, "_call_supply_tool", lambda client, name, text: payload)
    result = extract.extract_profile(object(), "Alpha Ltd", text)
    assert [n for n, _e in result["customers"]] == ["Indian Railways"]


def test_caps_are_enforced_after_gating(monkeypatch):
    text = " ".join(f"sells to Customer{i}." for i in range(6))
    payload = {
        "business_summary": None,
        "suppliers": [],
        "customers": [{"name": f"Customer{i}", "evidence": f"sells to Customer{i}."} for i in range(6)],
    }
    monkeypatch.setattr(extract, "_call_supply_tool", lambda client, name, text: payload)
    result = extract.extract_profile(object(), "X", text)
    assert len(result["customers"]) == 3  # config.SUPPLY_LINK_MAX_PER_RELATION


def test_advice_language_summary_is_dropped_but_links_survive(monkeypatch):
    text = "Beta Ltd refines sugar. It sells mainly to Nestle India."
    payload = {
        "business_summary": "Beta Ltd is a strong buy with excellent prospects.",
        "suppliers": [],
        "customers": [{"name": "Nestle India", "evidence": "sells mainly to Nestle India"}],
    }
    monkeypatch.setattr(extract, "_call_supply_tool", lambda client, name, text: payload)
    result = extract.extract_profile(object(), "Beta Ltd", text)
    assert result["business_summary"] is None
    assert result["customers"]


def test_pdf_text_reads_the_real_fixture():
    text = extract.pdf_text(FIXTURES / "rationale_sample.pdf")
    assert text and len(text) > 200


def test_client_failure_degrades_to_none(monkeypatch):
    def boom(client, name, text):
        raise RuntimeError("rate limited to death")
    monkeypatch.setattr(extract, "_call_supply_tool", boom)
    assert extract.extract_profile(object(), "X", "some text") is None


# --- Task 5: loader -- supply_links rows, caches, description fill -------


def _profile(customers=(), suppliers=(), summary=None):
    return {"business_summary": summary, "suppliers": list(suppliers), "customers": list(customers)}


def test_links_are_written_with_provenance_and_caches_refreshed(db_session):
    company = _company(db_session, "ALPHA.NS", "Alpha Ltd")
    counters = loader.apply_extraction(
        db_session, company,
        _profile(customers=[("Indian Railways", "derives most revenue from Indian Railways")],
                 summary="Alpha Ltd manufactures castings."),
        source_url="https://x/AttachLive/a.pdf", source_agency="CRISIL", as_of=AS_OF,
    )
    assert counters["links_written"] == 1
    link = db_session.query(SupplyLink).one()
    assert link.source_agency == "CRISIL" and link.evidence.startswith("derives")
    db_session.refresh(company)
    assert json.loads(company.supply_chain_customers_json) == ["Indian Railways"]
    assert company.business_desc == "Alpha Ltd manufactures castings."
    assert company.business_desc_source_url == "https://x/AttachLive/a.pdf"
    assert company.business_desc_as_of == AS_OF


def test_counterparty_resolves_via_the_exact_ladder_only(db_session):
    company = _company(db_session, "ALPHA.NS", "Alpha Ltd")
    target = _company(db_session, "IRFC.NS", "Indian Railway Finance Corporation")
    db_session.add(CompanyAlias(company_id=target.id, alias="Indian Railway Finance Corporation",
                                alias_type="LEGAL", normalized="indian railway finance corporation"))
    db_session.flush()
    loader.apply_extraction(
        db_session, company,
        _profile(customers=[("Indian Railway Finance Corporation", "q1"),
                            ("Some Unlisted Trading House", "q2")]),
        source_url="u", source_agency="ICRA", as_of=AS_OF,
    )
    links = {l.counterparty_name: l for l in db_session.query(SupplyLink).all()}
    assert links["Indian Railway Finance Corporation"].counterparty_company_id == target.id
    assert links["Some Unlisted Trading House"].counterparty_company_id is None


def test_newer_document_replaces_older_links(db_session):
    company = _company(db_session, "ALPHA.NS", "Alpha Ltd")
    loader.apply_extraction(db_session, company, _profile(customers=[("Old Buyer", "q")]),
                            source_url="u1", source_agency="CRISIL", as_of=date(2025, 1, 1))
    loader.apply_extraction(db_session, company, _profile(customers=[("New Buyer", "q")]),
                            source_url="u2", source_agency="CRISIL", as_of=AS_OF)
    names = [l.counterparty_name for l in db_session.query(SupplyLink).all()]
    assert names == ["New Buyer"]


def test_older_empty_extraction_never_clobbers_newer_links(db_session):
    company = _company(db_session, "ALPHA.NS", "Alpha Ltd")
    loader.apply_extraction(db_session, company, _profile(customers=[("Buyer", "q")]),
                            source_url="u1", source_agency="CRISIL", as_of=AS_OF)
    result = loader.apply_extraction(db_session, company, _profile(),
                                     source_url="u2", source_agency="ICRA", as_of=date(2025, 1, 1))
    assert result["links_kept_older"] == 1 or db_session.query(SupplyLink).count() == 1


def test_newer_empty_extraction_replaces_aged_out_links(db_session):
    company = _company(db_session, "ALPHA.NS", "Alpha Ltd")
    loader.apply_extraction(db_session, company, _profile(customers=[("Buyer", "q")]),
                            source_url="u1", source_agency="CRISIL", as_of=date(2025, 1, 1))
    loader.apply_extraction(db_session, company, _profile(),
                            source_url="u2", source_agency="CRISIL", as_of=AS_OF)
    assert db_session.query(SupplyLink).count() == 0
    db_session.refresh(company)
    assert company.supply_chain_customers_json == "[]"


def test_wikipedia_description_is_never_overwritten(db_session):
    company = _company(db_session, "ALPHA.NS", "Alpha Ltd")
    company.business_desc = "Wikipedia text."
    company.business_desc_source_url = "https://en.wikipedia.org/wiki/Alpha"
    db_session.flush()
    result = loader.apply_extraction(db_session, company, _profile(summary="Rating summary."),
                                     source_url="u", source_agency="CARE", as_of=AS_OF)
    assert result["desc_kept"] == 1
    db_session.refresh(company)
    assert company.business_desc == "Wikipedia text."


def test_rating_description_updates_an_older_rating_description(db_session):
    company = _company(db_session, "ALPHA.NS", "Alpha Ltd")
    loader.apply_extraction(db_session, company, _profile(summary="Old summary."),
                            source_url="https://x/AttachLive/old.pdf", source_agency="CRISIL",
                            as_of=date(2025, 1, 1))
    loader.apply_extraction(db_session, company, _profile(summary="New summary."),
                            source_url="https://x/AttachLive/new.pdf", source_agency="CRISIL",
                            as_of=AS_OF)
    db_session.refresh(company)
    assert company.business_desc == "New summary."
    assert company.business_desc_as_of == AS_OF


def test_self_referential_counterparty_is_skipped_not_stored(db_session):
    """Group-company disclosure / extraction slip: the rationale names the
    rated company's own legal name as its own customer or supplier. That
    must resolve to the company itself via the alias table and then be
    dropped entirely -- not stored with counterparty_company_id == the
    company's own id, and not stored with a NULL match either, since the
    self-name would still pollute the JSON caches and later render as
    nonsense in the cascade prompt block ("ALPHA.NS customers: Alpha
    Ltd"). A legitimate second counterparty in the same extraction must
    still land normally."""
    company = _company(db_session, "ALPHA.NS", "Alpha Ltd")
    beta = _company(db_session, "BETA.NS", "Beta Ltd")
    db_session.add(CompanyAlias(company_id=company.id, alias="Alpha Ltd",
                                alias_type="LEGAL", normalized="alpha ltd"))
    db_session.flush()
    result = loader.apply_extraction(
        db_session, company,
        _profile(customers=[("Alpha Ltd", "q1"), ("Beta Ltd", "q2")]),
        source_url="u", source_agency="CRISIL", as_of=AS_OF,
    )
    assert result["links_written"] == 1
    links = db_session.query(SupplyLink).all()
    assert [l.counterparty_name for l in links] == ["Beta Ltd"]
    assert links[0].counterparty_company_id == beta.id
    db_session.refresh(company)
    assert json.loads(company.supply_chain_customers_json) == ["Beta Ltd"]


# --- Task 6: prompt grounding + the no-auto-attribution guarantee ---------


def test_no_links_means_empty_block_and_no_candidates(db_session):
    _company(db_session, "AAA.NS", "Alpha")
    block, extras = prompting.known_relationships_block(db_session, ["AAA.NS"])
    assert block == "" and extras == []


def test_block_lists_links_with_agency_and_date(db_session):
    company = _company(db_session, "AAA.NS", "Alpha")
    buyer = _company(db_session, "BBB.NS", "Beta")
    db_session.add(SupplyLink(
        company_id=company.id, relation="CUSTOMER", counterparty_name="Beta",
        counterparty_company_id=buyer.id, evidence="q", source_url="u",
        source_agency="CRISIL", as_of=AS_OF,
        extracted_at=datetime.now(timezone.utc),
    ))
    db_session.flush()
    block, extras = prompting.known_relationships_block(db_session, ["AAA.NS"])
    assert "AAA.NS customers: Beta (BBB.NS)" in block
    assert "[CRISIL 2026-08-06]" in block
    assert "ONLY if THIS news plausibly transmits" in block
    assert extras == ["BBB.NS"]


def test_block_respects_line_and_char_caps(db_session):
    company = _company(db_session, "AAA.NS", "Alpha")
    for i in range(20):
        db_session.add(SupplyLink(
            company_id=company.id, relation="CUSTOMER",
            counterparty_name=f"Counterparty Number {i} With A Long Name",
            counterparty_company_id=None, evidence="q", source_url="u",
            source_agency="CRISIL", as_of=AS_OF,
            extracted_at=datetime.now(timezone.utc),
        ))
    db_session.flush()
    block, _extras = prompting.known_relationships_block(db_session, ["AAA.NS"])
    from app import config
    assert len(block) <= config.SUPPLY_PROMPT_MAX_CHARS + 200  # + fixed instruction text
    assert block.count("\n- ") <= config.SUPPLY_PROMPT_MAX_LINES


def test_supply_links_NEVER_create_alert_companies_without_llm_output(db_session, monkeypatch):
    """USER-LOCKED CONSTRAINT (spec 1): links ground the prompt and do
    nothing else. An event company with stored links plus an LLM that
    returns zero companies must produce zero AlertCompany rows and zero
    ImpactEdges -- the ETERNAL.NS-class fan-out failure must be
    structurally impossible."""
    company = _company(db_session, "ALPHA.NS", "Alpha Ltd")
    buyer = _company(db_session, "BETA.NS", "Beta Ltd")
    db_session.add(SupplyLink(
        company_id=company.id, relation="CUSTOMER", counterparty_name="Beta Ltd",
        counterparty_company_id=buyer.id, evidence="q", source_url="u",
        source_agency="CRISIL", as_of=AS_OF,
        extracted_at=datetime.now(timezone.utc),
    ))
    db_session.commit()

    article = Article(
        source="test", url="https://example.com/supply-links-t5",
        title="Alpha Ltd files an update", content="c",
    )
    db_session.add(article)
    db_session.commit()

    # The company-identification LLM stage returns zero companies -- reuses
    # test_pipeline.py's stub pattern of replacing analyze_article wholesale
    # (that is the only seam every persist-path test in this codebase mocks
    # at), so the stored SupplyLink row above is the ONLY thing that could
    # possibly inject a company into this alert.
    fake_output = AnalysisOutput(category="other", companies=[])
    monkeypatch.setattr(
        pipeline_module, "analyze_article",
        lambda client, title, content, session=None: fake_output,
    )

    created = pipeline_module.process_new_articles(db_session, claude_client=object())

    assert created == 1
    alert = db_session.query(Alert).one()
    assert db_session.query(AlertCompany).filter_by(alert_id=alert.id).count() == 0
    assert db_session.query(ImpactEdge).filter_by(alert_id=alert.id).count() == 0


# --- Task 6 review fixes (2026-08-06): L1-only grounding, filtered      --
# --- extras, cascade wiring tests, real-path constraint supplement      --


class _CapturingClient:
    """Captures the assembled request (messages + tool schema) and returns
    an empty-but-valid record_sector_companies response, so
    _identify_companies runs its real prompt-assembly path end to end --
    same pattern as tests/test_prompt_budget.py's _CapturingClient, kept
    local here rather than imported since it is intentionally tiny and this
    file already has its own fixtures/helpers."""

    def __init__(self):
        self.messages = None
        self.tools = None

    class _Completions:
        def __init__(self, outer):
            self._outer = outer

        def create(self, **kwargs):
            self._outer.messages = kwargs["messages"]
            self._outer.tools = kwargs["tools"]
            message = SimpleNamespace(tool_calls=[SimpleNamespace(
                function=SimpleNamespace(
                    name="record_sector_companies",
                    arguments=json.dumps({"sector_companies": []}),
                ),
            )])
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    @property
    def chat(self):
        return SimpleNamespace(completions=self._Completions(self))


def _direct_mention(ticker, name, sector):
    """A parent_pool entry shaped like the CONFIRMED direct company a real
    L1 cascade call would chain from -- impact_level defaults to "direct",
    which is exactly the condition cascade._identify_companies now gates
    supply-links grounding on."""
    return CompanyMention(
        name=name, ticker=ticker, is_direct=True, sector=sector,
        direction="bullish", magnitude_low=1.0, magnitude_high=2.0,
        rationale="r", time_horizon="Short-Term", impact_level="direct",
    )


def test_grounding_only_fires_at_the_l1_stage_not_l2(db_session):
    """Review finding 1a: grounding the L2 stage too (parent_pool = the L1
    stage's OWN output, impact_level="indirect_l1") measured over
    COMPANY_PROMPT_TOKEN_BUDGET in production. event_tickers must come from
    ONLY a parent_pool whose mentions are all impact_level="direct" -- L2's
    parent_pool never qualifies."""
    company = _company(db_session, "ALPHA.NS", "Alpha Ltd", sector="oil_gas")
    buyer = _company(db_session, "BETA.NS", "Beta Ltd", sector="oil_gas")
    db_session.add(SupplyLink(
        company_id=company.id, relation="CUSTOMER", counterparty_name="Beta Ltd",
        counterparty_company_id=buyer.id, evidence="q", source_url="u",
        source_agency="CRISIL", as_of=AS_OF, extracted_at=datetime.now(timezone.utc),
    ))
    db_session.commit()

    # L1 call: parent_pool IS the direct-company pool -- grounding fires.
    l1_client = _CapturingClient()
    _identify_companies(
        l1_client, facts="f",
        sectors=[SectorFinding(sector="oil_gas", direction="bullish", mechanism="m")],
        impact_level="indirect_l1", parent_pool=[_direct_mention("ALPHA.NS", "Alpha Ltd", "oil_gas")],
        session=db_session,
    )
    assert "KNOWN RELATIONSHIPS" in l1_client.messages[1]["content"]

    # L2 call: parent_pool is the L1 stage's OWN output (impact_level=
    # "indirect_l1", NOT "direct") -- grounding must NOT fire even though
    # the same ALPHA.NS ticker (with the same stored links) is the parent.
    l2_parent = CompanyMention(
        name="Alpha Ltd", ticker="ALPHA.NS", is_direct=False, sector="oil_gas",
        direction="bullish", magnitude_low=1.0, magnitude_high=2.0, rationale="r",
        time_horizon="Short-Term", impact_level="indirect_l1",
    )
    l2_client = _CapturingClient()
    _identify_companies(
        l2_client, facts="f",
        sectors=[SectorFinding(sector="oil_gas", direction="bullish", mechanism="m")],
        impact_level="indirect_l2", parent_pool=[l2_parent], session=db_session,
    )
    assert "KNOWN RELATIONSHIPS" not in l2_client.messages[1]["content"]


def test_extras_appear_in_candidate_list_and_the_tool_schema_ticker_enum(db_session):
    """Review finding 3(b): a resolved counterparty must reach BOTH the
    CANDIDATE COMPANIES prose block AND the tool schema's ticker enum
    (build_company_tool's valid_tickers) -- appearing in only one would let
    the model either never see it, or see it but have the provider reject
    the tool call for naming a ticker outside the enum."""
    company = _company(db_session, "ALPHA.NS", "Alpha Ltd", sector="oil_gas")
    buyer = _company(db_session, "BETA.NS", "Beta Ltd", sector="oil_gas")
    db_session.add(SupplyLink(
        company_id=company.id, relation="CUSTOMER", counterparty_name="Beta Ltd",
        counterparty_company_id=buyer.id, evidence="q", source_url="u",
        source_agency="CRISIL", as_of=AS_OF, extracted_at=datetime.now(timezone.utc),
    ))
    db_session.commit()

    client = _CapturingClient()
    _identify_companies(
        client, facts="f",
        sectors=[SectorFinding(sector="oil_gas", direction="bullish", mechanism="m")],
        impact_level="indirect_l1", parent_pool=[_direct_mention("ALPHA.NS", "Alpha Ltd", "oil_gas")],
        session=db_session,
    )
    prompt = client.messages[1]["content"]
    assert "CANDIDATE COMPANIES" in prompt and "BETA.NS" in prompt

    ticker_schema = (
        client.tools[0]["function"]["parameters"]["properties"]["sector_companies"]
        ["items"]["properties"]["companies"]["items"]["properties"]["ticker"]
    )
    assert "BETA.NS" in ticker_schema["enum"]


def test_extras_are_excluded_when_ineligible_as_ordinary_candidates(db_session):
    """Review finding 2: a resolved counterparty must pass the SAME
    eligibility guards app.companies.candidates.candidate_companies applies
    to every other candidate (DEMO_TICKERS excluded, market == "INDIA",
    tradeability == "NORMAL") before it is promoted into the candidate
    list / ticker enum -- prompting.known_relationships_block itself has no
    way to know a ticker's tradeability, so this guard lives in cascade.py
    where the extras Company rows are actually queried. An SME-tier
    counterparty must never reach the enum, even though it is still named
    (with its sourced relationship) in the KNOWN RELATIONSHIPS text -- the
    text is historical context, the candidate list is what the model may
    actually select."""
    company = _company(db_session, "ALPHA.NS", "Alpha Ltd", sector="oil_gas")
    sme_buyer = Company(
        ticker="SMEBUYER.NS", name="SME Buyer Ltd", sector="oil_gas", index_tier="OTHER",
        market="INDIA", tradeability="SME",
    )
    db_session.add(sme_buyer)
    db_session.flush()
    db_session.add(SupplyLink(
        company_id=company.id, relation="CUSTOMER", counterparty_name="SME Buyer Ltd",
        counterparty_company_id=sme_buyer.id, evidence="q", source_url="u",
        source_agency="CRISIL", as_of=AS_OF, extracted_at=datetime.now(timezone.utc),
    ))
    db_session.commit()

    client = _CapturingClient()
    _identify_companies(
        client, facts="f",
        sectors=[SectorFinding(sector="oil_gas", direction="bullish", mechanism="m")],
        impact_level="indirect_l1", parent_pool=[_direct_mention("ALPHA.NS", "Alpha Ltd", "oil_gas")],
        session=db_session,
    )
    prompt = client.messages[1]["content"]
    # Still named in the KNOWN RELATIONSHIPS text (sourced, historical fact).
    assert "SME Buyer Ltd" in prompt and "SMEBUYER.NS" in prompt

    # But never promoted to a selectable candidate or ticker-enum entry.
    if "CANDIDATE COMPANIES" in prompt:
        candidate_section = prompt.split("CANDIDATE COMPANIES", 1)[1]
        assert "SMEBUYER.NS" not in candidate_section
    ticker_schema = (
        client.tools[0]["function"]["parameters"]["properties"]["sector_companies"]
        ["items"]["properties"]["companies"]["items"]["properties"]["ticker"]
    )
    assert "SMEBUYER.NS" not in ticker_schema.get("enum", [])


def test_extras_still_respect_the_global_max_candidates_per_prompt_cap(db_session, monkeypatch):
    """Review finding 3(c) / spec 8.T4 clause 4: extras are appended BEFORE
    MAX_CANDIDATES_PER_PROMPT is applied, so the cap still binds even when
    sector candidates + resolved counterparties together exceed it. Patches
    the cap down to a small number so the test doesn't need to seed
    hundreds of rows to exercise it."""
    monkeypatch.setattr(cascade_module, "MAX_CANDIDATES_PER_PROMPT", 3)

    company = _company(db_session, "ALPHA.NS", "Alpha Ltd", sector="oil_gas")
    _company(db_session, "CAND1.NS", "Candidate One", sector="oil_gas")
    _company(db_session, "CAND2.NS", "Candidate Two", sector="oil_gas")
    for i in range(3):
        buyer = _company(db_session, f"EXTRA{i}.NS", f"Extra {i}", sector="oil_gas")
        db_session.add(SupplyLink(
            company_id=company.id, relation="CUSTOMER", counterparty_name=f"Extra {i}",
            counterparty_company_id=buyer.id, evidence="q", source_url="u",
            source_agency="CRISIL", as_of=AS_OF, extracted_at=datetime.now(timezone.utc),
        ))
    db_session.commit()

    client = _CapturingClient()
    _identify_companies(
        client, facts="f",
        sectors=[SectorFinding(sector="oil_gas", direction="bullish", mechanism="m")],
        impact_level="indirect_l1", parent_pool=[_direct_mention("ALPHA.NS", "Alpha Ltd", "oil_gas")],
        session=db_session,
    )
    ticker_schema = (
        client.tools[0]["function"]["parameters"]["properties"]["sector_companies"]
        ["items"]["properties"]["companies"]["items"]["properties"]["ticker"]
    )
    # 2 ordinary sector candidates + 3 extras = 5 total, uncapped -- must be
    # sliced down to the patched cap of 3.
    assert len(ticker_schema["enum"]) == 3


def test_supply_links_never_create_companies_via_the_real_grounded_identify_companies_call(db_session, monkeypatch):
    """Supplement to test_supply_links_NEVER_create_alert_companies_
    without_llm_output above: that test stubs analyze_article WHOLESALE,
    so it never actually executes cascade._identify_companies (where
    supply-links grounding is wired) at all -- it only proves the
    constraint at the persist layer. This one runs the REAL
    _identify_companies_per_sector call -- grounding code included, using
    _CapturingClient rather than a hand-typed empty result -- against the
    event company's genuinely stored SupplyLink rows, confirms the block
    actually reached the prompt (so this is proven to exercise the wired
    path, not a no-op), confirms the real call returns zero companies, and
    then re-runs the same persist-path assertion as the test above on that
    real (empty) result."""
    company = _company(db_session, "ALPHA.NS", "Alpha Ltd", sector="oil_gas")
    buyer = _company(db_session, "BETA.NS", "Beta Ltd", sector="oil_gas")
    db_session.add(SupplyLink(
        company_id=company.id, relation="CUSTOMER", counterparty_name="Beta Ltd",
        counterparty_company_id=buyer.id, evidence="q", source_url="u",
        source_agency="CRISIL", as_of=AS_OF, extracted_at=datetime.now(timezone.utc),
    ))
    db_session.commit()

    client = _CapturingClient()
    mentions, gaps = _identify_companies_per_sector(
        client, facts="f",
        sectors=[SectorFinding(sector="oil_gas", direction="bearish", mechanism="m")],
        impact_level="indirect_l1", parent_pool=[_direct_mention("ALPHA.NS", "Alpha Ltd", "oil_gas")],
        session=db_session,
    )
    assert "KNOWN RELATIONSHIPS" in client.messages[1]["content"]  # real grounding fired
    assert mentions == [] and gaps == []

    article = Article(
        source="test", url="https://example.com/supply-links-t5-real", title="t", content="c",
    )
    db_session.add(article)
    db_session.commit()

    fake_output = AnalysisOutput(category="other", companies=mentions)
    monkeypatch.setattr(
        pipeline_module, "analyze_article",
        lambda client, title, content, session=None: fake_output,
    )
    created = pipeline_module.process_new_articles(db_session, claude_client=object())

    assert created == 1
    alert = db_session.query(Alert).one()
    assert db_session.query(AlertCompany).filter_by(alert_id=alert.id).count() == 0
    assert db_session.query(ImpactEdge).filter_by(alert_id=alert.id).count() == 0
