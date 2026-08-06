"""Sourced-description backfill.

The tests that matter here are the rejection ones. Anyone can make a
scraper store text; the requirement is that it refuses to store text it
cannot attribute to the right company.
"""
from datetime import date

import json

from app.companies.descriptions import extract, fetchers, loader, snapshot, sourced_description
from app.models import Company, Listing

AS_OF = date(2026, 8, 5)

# Real infobox shapes, copied from live articles on 2026-08-05.
TCS_WIKITEXT = (
    "{{Infobox company\n"
    "| name = Tata Consultancy Services\n"
    "| traded_as = {{Unbulleted list|{{BSE|532540}}|{{NSE|TCS}}"
    "|[[BSE SENSEX]] constituent|[[NIFTY 50|NSE NIFTY 50]] constituent}}\n"
    "| ISIN = {{ISIN|sl=n|pl=y|INE467B01029}}\n"
    "}}\n"
)
RELIANCE_WIKITEXT = (
    "| traded_as = {{Unbulleted list|{{BSE|500325}}|{{NSE|RELIANCE}}|{{LSE|RIGD}}}}\n"
)


def _company(session, ticker, isin, name, *, nse=None, bse=None):
    company = Company(
        ticker=ticker, name=name, sector="it", index_tier="OTHER", isin=isin,
    )
    session.add(company)
    session.flush()
    if nse:
        session.add(Listing(company_id=company.id, exchange="NSE", symbol=nse,
                            source="NSE", as_of=AS_OF))
    if bse:
        session.add(Listing(company_id=company.id, exchange="BSE", symbol=ticker.split(".")[0],
                            scrip_code=bse, source="BSE", as_of=AS_OF))
    session.flush()
    return company


# --- extract: identifiers -------------------------------------------------

def test_parses_bse_nse_and_isin_from_the_infobox():
    refs = extract.parse_refs(TCS_WIKITEXT)
    assert refs.bse_codes == {"532540"}
    assert refs.nse_symbols == {"TCS"}
    assert refs.isins == {"INE467B01029"}


def test_a_foreign_exchange_template_is_not_read_as_nse():
    refs = extract.parse_refs(RELIANCE_WIKITEXT)
    assert refs.nse_symbols == {"RELIANCE"}
    assert "RIGD" not in refs.nse_symbols


def test_an_index_wikilink_is_not_read_as_a_scrip_code():
    # [[BSE SENSEX]] and {{BSE SENSEX}} both lack the pipe a code needs.
    refs = extract.parse_refs("[[BSE SENSEX]] {{BSE SENSEX}} constituent")
    assert refs.bse_codes == set()
    assert not refs


def test_a_cited_bse_url_is_not_read_as_a_scrip_code():
    """Article bodies cite bseindia.com for other companies' filings. A
    citation is not a claim about who the article is about."""
    body = (
        "Acquired a stake in a rival.<ref>{{cite web|url="
        "https://www.bseindia.com/stock-share-price/foo-ltd/foo/543210/}}</ref>"
    )
    assert extract.parse_refs(body).bse_codes == set()


def test_empty_wikitext_yields_no_refs():
    assert not extract.parse_refs("")
    assert not extract.parse_refs(None)


# --- extract: description text --------------------------------------------

def test_summarize_keeps_whole_sentences_within_the_budget():
    text = (
        "Alkem Laboratories Limited is an Indian multinational pharmaceutical "
        "company headquartered in Mumbai. Specialising in generics, Alkem "
        "manufactures and sells branded formulations. It was founded in 1973."
    )
    out = extract.summarize(text)
    assert out.startswith("Alkem Laboratories Limited is an Indian")
    assert out.endswith(".")
    assert len(out) <= 400


def test_summarize_rejects_a_stub_too_short_to_be_a_description():
    assert extract.summarize("Foo Ltd is a company.") is None


def test_summarize_rejects_empty_and_whitespace():
    assert extract.summarize("") is None
    assert extract.summarize("   \n  ") is None


def test_summarize_rejects_a_disambiguation_lead():
    assert extract.summarize("Foo may refer to several Indian companies listed below.") is None


def test_summarize_truncates_a_single_runaway_sentence_rather_than_dropping_it():
    text = "Foo Limited is " + ("a very large diversified conglomerate " * 40) + "company."
    out = extract.summarize(text)
    assert out is not None
    assert len(out) <= 601
    assert out.endswith("…")


def test_disambiguation_pages_are_detected():
    assert extract.is_disambiguation("Foo may refer to:\n{{Disambiguation}}") is True
    assert extract.is_disambiguation(TCS_WIKITEXT) is False


def test_source_url_is_a_real_article_url():
    assert extract.source_url("Tata Consultancy Services") == (
        "https://en.wikipedia.org/wiki/Tata_Consultancy_Services"
    )


# --- snapshot -------------------------------------------------------------

def test_title_filename_round_trips_through_illegal_path_characters():
    for title in ["Tata Consultancy Services", "AC/DC Ltd", "Foo: The Bar", "R&D Co?"]:
        assert snapshot.filename_to_title(snapshot.title_to_filename(title)) == title


def test_fetched_titles_is_the_resume_set(tmp_path):
    root = str(tmp_path)
    assert snapshot.fetched_titles(root, AS_OF) == set()
    path = snapshot.page_path(root, AS_OF, "Tata Consultancy Services")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")
    assert snapshot.fetched_titles(root, AS_OF) == {"Tata Consultancy Services"}


# --- loader: resolution ---------------------------------------------------

def test_resolves_an_article_to_its_company_by_exchange_code(db_session):
    company = _company(db_session, "TCS.NS", "INE467B01029", "Tata Consultancy Services",
                       nse="TCS", bse="532540")
    resolved = loader.resolve_company(db_session, extract.parse_refs(TCS_WIKITEXT))
    assert resolved is not None and resolved.id == company.id


def test_an_article_whose_codes_disagree_resolves_to_nothing(db_session):
    """A group/demerger article carrying two companies' tickers. Neither is
    the subject, so neither gets the description."""
    _company(db_session, "AAA.NS", "INE111A01011", "Alpha", nse="AAA", bse="500001")
    _company(db_session, "BBB.NS", "INE222B01012", "Beta", nse="BBB", bse="500002")
    wikitext = "| traded_as = {{BSE|500001}}<br />{{NSE|BBB}}"
    assert loader.resolve_company(db_session, extract.parse_refs(wikitext)) is None


def test_an_unknown_code_resolves_to_nothing(db_session):
    _company(db_session, "AAA.NS", "INE111A01011", "Alpha", nse="AAA", bse="500001")
    assert loader.resolve_company(db_session, extract.parse_refs("{{BSE|999999}}")) is None


def test_no_identifiers_resolves_to_nothing(db_session):
    assert loader.resolve_company(db_session, extract.parse_refs("plain prose")) is None


# --- loader: writes -------------------------------------------------------

def _page(title, wikitext, extract_text):
    return {"title": title, "wikitext": wikitext, "extract": extract_text}


LEAD = (
    "Tata Consultancy Services Limited is an Indian multinational technology "
    "company specializing in information technology services and consulting."
)


def test_writes_description_with_its_source_url_and_date(db_session):
    company = _company(db_session, "TCS.NS", "INE467B01029", "Tata Consultancy Services",
                       nse="TCS", bse="532540")
    stats = loader.apply_pages(
        db_session, [_page("Tata Consultancy Services", TCS_WIKITEXT, LEAD)], AS_OF,
    )
    assert stats["written"] == 1
    db_session.refresh(company)
    assert company.business_desc.startswith("Tata Consultancy Services Limited is an Indian")
    assert company.business_desc_source_url == (
        "https://en.wikipedia.org/wiki/Tata_Consultancy_Services"
    )
    assert company.business_desc_as_of == AS_OF


def test_an_unresolvable_page_writes_nothing(db_session):
    company = _company(db_session, "AAA.NS", "INE111A01011", "Alpha", nse="AAA", bse="500001")
    stats = loader.apply_pages(db_session, [_page("Beta", "{{BSE|999999}}", LEAD)], AS_OF)
    assert stats["written"] == 0 and stats["unresolved"] == 1
    db_session.refresh(company)
    assert company.business_desc is None


def test_a_resolvable_page_with_no_usable_text_writes_nothing(db_session):
    company = _company(db_session, "TCS.NS", "INE467B01029", "TCS", nse="TCS", bse="532540")
    stats = loader.apply_pages(
        db_session, [_page("Tata Consultancy Services", TCS_WIKITEXT, "A stub.")], AS_OF,
    )
    assert stats["written"] == 0 and stats["no_text"] == 1
    db_session.refresh(company)
    assert company.business_desc is None
    assert company.business_desc_source_url is None


def test_rerunning_the_same_snapshot_is_idempotent(db_session):
    _company(db_session, "TCS.NS", "INE467B01029", "TCS", nse="TCS", bse="532540")
    pages = [_page("Tata Consultancy Services", TCS_WIKITEXT, LEAD)]
    assert loader.apply_pages(db_session, pages, AS_OF)["written"] == 1
    second = loader.apply_pages(db_session, pages, AS_OF)
    assert second["written"] == 0 and second["unchanged"] == 1


def test_a_page_that_stops_resolving_does_not_clear_a_stored_description(db_session):
    """Never clobber good data with nothing -- an infobox edit that drops the
    ticker must not blank a description we already sourced."""
    company = _company(db_session, "TCS.NS", "INE467B01029", "TCS", nse="TCS", bse="532540")
    loader.apply_pages(db_session, [_page("Tata Consultancy Services", TCS_WIKITEXT, LEAD)], AS_OF)
    loader.apply_pages(db_session, [_page("Tata Consultancy Services", "no infobox", LEAD)], AS_OF)
    db_session.refresh(company)
    assert company.business_desc is not None
    assert company.business_desc_source_url is not None


def test_two_articles_claiming_one_company_do_not_fight(db_session):
    _company(db_session, "TCS.NS", "INE467B01029", "TCS", nse="TCS", bse="532540")
    other_lead = "Tata Consultancy Services is a different article about the same company entirely."
    stats = loader.apply_pages(
        db_session,
        [
            _page("Tata Consultancy Services", TCS_WIKITEXT, LEAD),
            _page("TCS (company)", TCS_WIKITEXT, other_lead),
        ],
        AS_OF,
    )
    assert stats["written"] == 1


def test_a_disambiguation_page_is_skipped_before_resolution(db_session):
    _company(db_session, "TCS.NS", "INE467B01029", "TCS", nse="TCS", bse="532540")
    stats = loader.apply_pages(
        db_session, [_page("TCS", TCS_WIKITEXT + "{{Disambiguation}}", LEAD)], AS_OF,
    )
    assert stats["disambiguation"] == 1 and stats["written"] == 0


# --- search candidate stage -----------------------------------------------

def _search_opener(calls, results):
    def opener(url, timeout=60):
        calls.append(url)
        return json.dumps(
            {"query": {"search": [{"title": t} for t in results]}}
        ).encode("utf-8")
    return opener


def test_search_returns_candidate_titles(monkeypatch, tmp_path):
    monkeypatch.setattr(fetchers, "SEARCH_THROTTLE_SECONDS", 0)
    calls = []
    titles = fetchers.search_for_companies(
        str(tmp_path), AS_OF, [("SUNPHARMA.NS", "Sun Pharmaceutical Industries Ltd.")],
        opener=_search_opener(calls, ["Sun Pharmaceutical"]),
    )
    assert titles == ["Sun Pharmaceutical"]
    assert len(calls) == 1


def test_search_resumes_without_requerying(monkeypatch, tmp_path):
    monkeypatch.setattr(fetchers, "SEARCH_THROTTLE_SECONDS", 0)
    root, companies = str(tmp_path), [("SUNPHARMA.NS", "Sun Pharmaceutical")]
    calls = []
    opener = _search_opener(calls, ["Sun Pharmaceutical"])
    fetchers.search_for_companies(root, AS_OF, companies, opener=opener)
    again = fetchers.search_for_companies(root, AS_OF, companies, opener=opener)
    assert again == ["Sun Pharmaceutical"]
    assert len(calls) == 1, "second pass must read the cached result, not re-query"


def test_a_company_wikipedia_has_never_heard_of_is_not_retried(monkeypatch, tmp_path):
    """An empty result still gets a file. Without it the expensive pass
    would re-ask about every unknown microcap on every rerun."""
    monkeypatch.setattr(fetchers, "SEARCH_THROTTLE_SECONDS", 0)
    root, companies = str(tmp_path), [("NOBODY.NS", "Nobody Ltd")]
    calls = []
    opener = _search_opener(calls, [])
    assert fetchers.search_for_companies(root, AS_OF, companies, opener=opener) == []
    assert fetchers.search_for_companies(root, AS_OF, companies, opener=opener) == []
    assert len(calls) == 1


def test_a_failed_search_is_retried_on_the_next_run(monkeypatch, tmp_path):
    monkeypatch.setattr(fetchers, "SEARCH_THROTTLE_SECONDS", 0)
    calls = []

    def failing(url, timeout=60):
        calls.append(url)
        raise OSError("network down")

    root, companies = str(tmp_path), [("AAA.NS", "Alpha")]
    assert fetchers.search_for_companies(root, AS_OF, companies, opener=failing) == []
    assert fetchers.search_for_companies(root, AS_OF, companies, opener=failing) == []
    assert len(calls) == 2, "a failure must not be cached as 'no such company'"


def test_a_search_hit_still_has_to_prove_itself(db_session):
    """The whole point of the search stage: it widens the candidate pool
    without widening what is trusted. A plausible article that does not
    carry the company's code is still discarded."""
    company = _company(db_session, "AAA.NS", "INE111A01011", "Alpha Industries", nse="AAA")
    plausible = "'''Alpha Industries''' is an American aerospace clothing manufacturer."
    stats = loader.apply_pages(db_session, [_page("Alpha Industries", plausible, LEAD)], AS_OF)
    assert stats["written"] == 0 and stats["no_refs"] == 1
    db_session.refresh(company)
    assert company.business_desc is None


# --- serving gate ---------------------------------------------------------

def test_a_legacy_unsourced_description_is_withheld(db_session):
    company = _company(db_session, "AAA.NS", "INE111A01011", "Alpha", nse="AAA")
    company.business_desc = "An LLM made this up."
    assert sourced_description(company) == (None, None)


def test_a_sourced_description_is_served_with_its_attribution(db_session):
    company = _company(db_session, "AAA.NS", "INE111A01011", "Alpha", nse="AAA")
    company.business_desc = "Alpha Limited is an Indian company."
    company.business_desc_source_url = "https://en.wikipedia.org/wiki/Alpha"
    assert sourced_description(company) == (
        "Alpha Limited is an Indian company.", "https://en.wikipedia.org/wiki/Alpha",
    )
