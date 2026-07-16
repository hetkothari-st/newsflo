from app.analysis.schemas import CompanyMention
from app.companies.resolution import resolve_companies
from app.models import Company


def _make_company(session, ticker, name, sector, market_cap, index_tier="NIFTY50"):
    company = Company(ticker=ticker, name=name, sector=sector, index_tier=index_tier, market_cap=market_cap)
    session.add(company)
    session.commit()
    return company


def test_resolve_direct_mention(db_session):
    company = _make_company(db_session, "RELIANCE.NS", "Reliance Industries", "oil_gas", 1_800_000.0, index_tier="NIFTY50")
    mention = CompanyMention(
        name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
        direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin",
        key_points=["Crude prices ease", "Refining margins widen"],
        confidence_score=85, time_horizon="Short-Term",
    )

    resolved = resolve_companies(db_session, [mention])

    assert len(resolved) == 1
    assert resolved[0]["company_id"] == company.id
    assert resolved[0]["basis"] == "direct_mention"
    assert resolved[0]["key_points"] == ["Crude prices ease", "Refining margins widen"]


def test_resolve_sector_inference_picks_top_5_by_index_tier(db_session):
    # 3 top-tier companies plus 5 lower-tier companies: more than 5 total in
    # the sector, so the resolver must prefer the higher-tier companies.
    nifty50_tickers = [f"OILN50_{i}.NS" for i in range(3)]
    other_tickers = [f"OILOTHER_{i}.NS" for i in range(5)]
    for ticker in nifty50_tickers:
        _make_company(db_session, ticker, ticker, "oil_gas", market_cap=None, index_tier="NIFTY50")
    for ticker in other_tickers:
        _make_company(db_session, ticker, ticker, "oil_gas", market_cap=None, index_tier="OTHER")

    mention = CompanyMention(
        name="oil sector", ticker=None, is_direct=False, sector="oil_gas",
        direction="bullish", magnitude_low=1.0, magnitude_high=2.0, rationale="crude spike",
        confidence_score=55, time_horizon="Medium-Term",
    )

    resolved = resolve_companies(db_session, [mention])

    assert len(resolved) == 5
    assert all(r["basis"] == "sector_inference" for r in resolved)

    resolved_tickers = {
        db_session.get(Company, r["company_id"]).ticker for r in resolved
    }
    # All 3 NIFTY50 companies must be included in preference to OTHER tier.
    assert set(nifty50_tickers).issubset(resolved_tickers)
    assert len(resolved_tickers & set(other_tickers)) == 2


def test_resolve_direct_mention_with_unknown_ticker_is_skipped(db_session):
    mention = CompanyMention(
        name="Unknown Corp", ticker="UNKNOWN.NS", is_direct=True, sector=None,
        direction="bullish", magnitude_low=1.0, magnitude_high=2.0, rationale="n/a",
        confidence_score=50, time_horizon="Short-Term",
    )

    resolved = resolve_companies(db_session, [mention])

    assert resolved == []


def test_resolve_direct_mention_falls_back_to_name_when_ticker_missing(db_session):
    # The model is confident of the company but not the exact ticker -- the
    # resolver must still use the specific name rather than discarding the
    # mention or falling back to unrelated sector-wide picks.
    company = _make_company(db_session, "SBIN.NS", "State Bank of India", "banking", None)
    mention = CompanyMention(
        name="State Bank of India", ticker=None, is_direct=True, sector="banking",
        direction="bearish", magnitude_low=-2.0, magnitude_high=-1.0, rationale="higher funding costs",
        confidence_score=75, time_horizon="Medium-Term",
    )

    resolved = resolve_companies(db_session, [mention])

    assert len(resolved) == 1
    assert resolved[0]["company_id"] == company.id
    assert resolved[0]["basis"] == "direct_mention"


def test_resolve_direct_mention_name_fallback_skips_ambiguous_matches(db_session):
    # Two companies both contain "Bank" -- an ambiguous substring match must
    # be skipped entirely (omit rather than mismatch), not guessed at.
    _make_company(db_session, "HDFCBANK.NS", "HDFC Bank", "banking", None)
    _make_company(db_session, "ICICIBANK.NS", "ICICI Bank", "banking", None)
    mention = CompanyMention(
        name="Bank", ticker=None, is_direct=True, sector="banking",
        direction="bullish", magnitude_low=1.0, magnitude_high=2.0, rationale="vague",
        confidence_score=40, time_horizon="Short-Term",
    )

    resolved = resolve_companies(db_session, [mention])

    assert resolved == []


def test_resolve_direct_mention_name_fallback_is_case_insensitive(db_session):
    company = _make_company(db_session, "TCS.NS", "Tata Consultancy Services", "it", None)
    mention = CompanyMention(
        name="tata consultancy services", ticker=None, is_direct=True, sector="it",
        direction="bullish", magnitude_low=1.0, magnitude_high=2.0, rationale="strong order book",
        confidence_score=80, time_horizon="Short-Term",
    )

    resolved = resolve_companies(db_session, [mention])

    assert len(resolved) == 1
    assert resolved[0]["company_id"] == company.id


def test_resolve_dedupes_repeated_sector_inference_across_mentions(db_session):
    # Observed in production: the model named 4 specific companies in one
    # article but marked all 4 is_direct=false with the same sector -- each
    # independently expanding to the same top-5 sector companies produced 20
    # duplicate rows for a single article. Same sector mentioned twice must
    # resolve the sector's companies only once.
    for i in range(3):
        _make_company(db_session, f"OIL_{i}.NS", f"Oil Co {i}", "oil_gas", None, index_tier="NIFTY50")
    mentions = [
        CompanyMention(
            name="Indian Oil Corporation", ticker="IOC.NS", is_direct=False, sector="oil_gas",
            direction="bullish", magnitude_low=1.0, magnitude_high=2.0, rationale="easing crude prices",
            confidence_score=60, time_horizon="Medium-Term",
        ),
        CompanyMention(
            name="Bharat Petroleum", ticker="BPCL.NS", is_direct=False, sector="oil_gas",
            direction="bullish", magnitude_low=1.0, magnitude_high=2.0, rationale="easing crude prices",
            confidence_score=60, time_horizon="Medium-Term",
        ),
    ]

    resolved = resolve_companies(db_session, mentions)

    assert len(resolved) == 3
    assert len({r["company_id"] for r in resolved}) == 3


def test_tier_rank_prefers_niftynext50_over_midcap150(db_session):
    next50 = _make_company(db_session, "NEXT50CO.NS", "Next50 Co", "oil_gas", None, index_tier="NIFTYNEXT50")
    midcap = _make_company(db_session, "MIDCO.NS", "Mid Co", "oil_gas", None, index_tier="NIFTYMIDCAP150")

    mention = CompanyMention(
        name="oil sector", ticker=None, is_direct=False, sector="oil_gas",
        direction="bullish", magnitude_low=1.0, magnitude_high=2.0, rationale="crude spike",
        confidence_score=55, time_horizon="Medium-Term",
    )
    resolved = resolve_companies(db_session, [mention])
    resolved_ids = [r["company_id"] for r in resolved]

    assert resolved_ids.index(next50.id) < resolved_ids.index(midcap.id)


def test_resolve_dedupes_direct_mention_already_covered_by_sector_inference(db_session):
    # A company resolved via an earlier sector-wide expansion must not be
    # appended again if a later direct mention in the same article names it.
    company = _make_company(db_session, "OIL_0.NS", "Oil Co 0", "oil_gas", None, index_tier="NIFTY50")
    mentions = [
        CompanyMention(
            name="oil sector", ticker=None, is_direct=False, sector="oil_gas",
            direction="bullish", magnitude_low=1.0, magnitude_high=2.0, rationale="crude spike",
            confidence_score=55, time_horizon="Medium-Term",
        ),
        CompanyMention(
            name="Oil Co 0", ticker="OIL_0.NS", is_direct=True, sector="oil_gas",
            direction="bullish", magnitude_low=1.0, magnitude_high=2.0, rationale="named directly",
            confidence_score=85, time_horizon="Short-Term",
        ),
    ]

    resolved = resolve_companies(db_session, mentions)

    assert len([r for r in resolved if r["company_id"] == company.id]) == 1


def test_resolve_carries_evidence_discipline_fields_through(db_session):
    company = _make_company(db_session, "RELIANCE.NS", "Reliance Industries", "oil_gas", 1.0)
    mention = CompanyMention(
        name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
        direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin",
        time_horizon="Short-Term",
        reasons=["Refining margins widen."],
        evidence_refs=["RULE_CRUDE_OIL_UP"],
        risks=["Margin reversal."],
        assumptions=["Crude stays elevated."],
        unknowns=["Duration of the spike."],
        alternative_hypothesis="Already priced in.",
    )

    resolved = resolve_companies(db_session, [mention])

    assert resolved[0]["reasons"] == ["Refining margins widen."]
    assert resolved[0]["evidence_refs"] == ["RULE_CRUDE_OIL_UP"]
    assert resolved[0]["risks"] == ["Margin reversal."]
    assert resolved[0]["assumptions"] == ["Crude stays elevated."]
    assert resolved[0]["unknowns"] == ["Duration of the spike."]
    assert resolved[0]["alternative_hypothesis"] == "Already priced in."


def test_direct_mention_defaults_to_impact_level_direct_with_no_parent(db_session):
    _make_company(db_session, "RELIANCE.NS", "Reliance Industries", "oil_gas", 1.0)
    mention = CompanyMention(
        name="Reliance Industries", ticker="RELIANCE.NS", is_direct=True, sector=None,
        direction="bullish", magnitude_low=2.0, magnitude_high=4.0, rationale="refiner margin",
        time_horizon="Short-Term",
    )

    resolved = resolve_companies(db_session, [mention])

    assert resolved[0]["impact_level"] == "direct"
    assert resolved[0]["parent_company_id"] is None


def test_resolve_indirect_l1_links_to_its_direct_parent(db_session):
    direct = _make_company(db_session, "NVDA.NS", "Nvidia", "it", 1.0)
    supplier = _make_company(db_session, "TSM.NS", "TSMC", "it", 1.0)
    mentions = [
        CompanyMention(
            name="Nvidia", ticker="NVDA.NS", is_direct=True, sector=None,
            direction="bearish", magnitude_low=2.0, magnitude_high=4.0, rationale="export ban",
            time_horizon="Short-Term", impact_level="direct",
        ),
        CompanyMention(
            name="TSMC", ticker="TSM.NS", is_direct=True, sector=None,
            direction="bearish", magnitude_low=1.0, magnitude_high=2.0,
            rationale="TSMC fabs Nvidia's chips; lower Nvidia orders reduce TSMC's foundry revenue.",
            time_horizon="Medium-Term", impact_level="indirect_l1", parent_ticker="NVDA.NS",
        ),
    ]

    resolved = resolve_companies(db_session, mentions)

    direct_entry = next(r for r in resolved if r["company_id"] == direct.id)
    indirect_entry = next(r for r in resolved if r["company_id"] == supplier.id)
    assert direct_entry["impact_level"] == "direct"
    assert indirect_entry["impact_level"] == "indirect_l1"
    assert indirect_entry["parent_company_id"] == direct.id


def test_resolve_indirect_l2_chains_through_indirect_l1(db_session):
    direct = _make_company(db_session, "NVDA.NS", "Nvidia", "it", 1.0)
    l1 = _make_company(db_session, "TSM.NS", "TSMC", "it", 1.0)
    l2 = _make_company(db_session, "ASML.NS", "ASML", "it", 1.0)
    mentions = [
        CompanyMention(
            name="Nvidia", ticker="NVDA.NS", is_direct=True, sector=None,
            direction="bearish", magnitude_low=2.0, magnitude_high=4.0, rationale="export ban",
            time_horizon="Short-Term", impact_level="direct",
        ),
        CompanyMention(
            name="TSMC", ticker="TSM.NS", is_direct=True, sector=None,
            direction="bearish", magnitude_low=1.0, magnitude_high=2.0, rationale="fabs Nvidia chips",
            time_horizon="Medium-Term", impact_level="indirect_l1", parent_ticker="NVDA.NS",
        ),
        CompanyMention(
            name="ASML", ticker="ASML.NS", is_direct=True, sector=None,
            direction="bearish", magnitude_low=0.5, magnitude_high=1.0,
            rationale="ASML supplies lithography tools to TSMC",
            time_horizon="Long-Term", impact_level="indirect_l2", parent_ticker="TSM.NS",
        ),
    ]

    resolved = resolve_companies(db_session, mentions)

    l2_entry = next(r for r in resolved if r["company_id"] == l2.id)
    assert l2_entry["impact_level"] == "indirect_l2"
    assert l2_entry["parent_company_id"] == l1.id


def test_resolve_drops_indirect_entry_whose_parent_ticker_never_resolved(db_session):
    _make_company(db_session, "TSM.NS", "TSMC", "it", 1.0)
    mention = CompanyMention(
        name="TSMC", ticker="TSM.NS", is_direct=True, sector=None,
        direction="bearish", magnitude_low=1.0, magnitude_high=2.0, rationale="orphaned indirect entry",
        time_horizon="Medium-Term", impact_level="indirect_l1", parent_ticker="NOTHING_NAMED.NS",
    )

    resolved = resolve_companies(db_session, [mention])

    assert resolved == []
