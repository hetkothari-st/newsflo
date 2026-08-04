from app.analysis.schemas import CompanyMention
from app.companies.matching import aliases
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


def test_resolve_sector_inference_picks_top_3_by_index_tier(db_session):
    # TOP_N_SECTOR_COMPANIES lowered from 5 to 3 (Task 11): 2 top-tier
    # companies plus 5 lower-tier companies -- more than 3 total in the
    # sector, so the resolver must still prefer the higher-tier companies
    # before falling back to fill the remaining slot from OTHER tier.
    nifty50_tickers = [f"OILN50_{i}.NS" for i in range(2)]
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

    assert len(resolved) == 3
    assert all(r["basis"] == "sector_inference" for r in resolved)

    resolved_tickers = {
        db_session.get(Company, r["company_id"]).ticker for r in resolved
    }
    # Both NIFTY50 companies must be included in preference to OTHER tier.
    assert set(nifty50_tickers).issubset(resolved_tickers)
    assert len(resolved_tickers & set(other_tickers)) == 1


def test_resolve_sector_inference_at_indirect_l1_chains_to_the_stated_parent(db_session):
    # app.analysis.cascade's _sector_fanout_mentions builds a sector-wide
    # fan-out mention for cascade levels too, not just the direct stage --
    # it must chain to a resolvable parent exactly like a direct_mention
    # indirect entry does.
    parent = _make_company(db_session, "HDFCBANK.NS", "HDFC Bank", "banking", 1_000_000.0)
    for i in range(3):
        _make_company(db_session, f"AUTO_{i}.NS", f"Auto Co {i}", "auto", None)
    direct_mention = CompanyMention(
        name="HDFC Bank", ticker="HDFCBANK.NS", is_direct=True, sector="banking",
        direction="bearish", magnitude_low=-2.0, magnitude_high=-1.0, rationale="rate exposure",
        confidence_score=70, time_horizon="Short-Term", impact_level="direct",
    )
    sector_wide_l1 = CompanyMention(
        name="auto sector", ticker=None, is_direct=False, sector="auto",
        direction="bearish", magnitude_low=1.0, magnitude_high=3.0, rationale="input cost pass-through",
        confidence_score=50, time_horizon="Short-Term",
        impact_level="indirect_l1", parent_ticker="HDFCBANK.NS",
    )

    resolved = resolve_companies(db_session, [direct_mention, sector_wide_l1])

    sector_rows = [r for r in resolved if r["basis"] == "sector_inference"]
    assert len(sector_rows) == 3
    assert all(r["impact_level"] == "indirect_l1" for r in sector_rows)
    assert all(r["parent_company_id"] == parent.id for r in sector_rows)


def test_resolve_sector_inference_at_indirect_l2_chains_through_l1(db_session):
    parent = _make_company(db_session, "HDFCBANK.NS", "HDFC Bank", "banking", 1_000_000.0)
    l1_company = _make_company(db_session, "MARUTI.NS", "Maruti Suzuki", "auto", 500_000.0)
    _make_company(db_session, "COMP_A.NS", "Component Co A", "metals", None)

    mentions = [
        CompanyMention(
            name="HDFC Bank", ticker="HDFCBANK.NS", is_direct=True, sector="banking",
            direction="bearish", magnitude_low=-2.0, magnitude_high=-1.0, rationale="rate exposure",
            confidence_score=70, time_horizon="Short-Term", impact_level="direct",
        ),
        CompanyMention(
            name="Maruti Suzuki", ticker="MARUTI.NS", is_direct=True, sector="auto",
            direction="bearish", magnitude_low=-1.0, magnitude_high=-1.0, rationale="demand hit",
            confidence_score=60, time_horizon="Short-Term",
            impact_level="indirect_l1", parent_ticker="HDFCBANK.NS",
        ),
        CompanyMention(
            name="metals sector", ticker=None, is_direct=False, sector="metals",
            direction="bearish", magnitude_low=1.0, magnitude_high=2.0, rationale="input cost",
            confidence_score=45, time_horizon="Short-Term",
            impact_level="indirect_l2", parent_ticker="MARUTI.NS",
        ),
    ]

    resolved = resolve_companies(db_session, mentions)

    sector_row = next(r for r in resolved if r["basis"] == "sector_inference")
    assert sector_row["impact_level"] == "indirect_l2"
    assert sector_row["parent_company_id"] == l1_company.id
    # Sanity: the chain's own companies still resolved correctly too.
    assert {r["company_id"] for r in resolved} == {parent.id, l1_company.id, sector_row["company_id"]}


def test_resolve_sector_inference_at_indirect_level_dropped_when_parent_unresolved(db_session):
    # The stated parent_ticker was never itself resolved in this same
    # mentions list (e.g. its own LLM call failed) -- the chain is broken,
    # so this entry must be dropped entirely, not persisted with no parent.
    for i in range(3):
        _make_company(db_session, f"AUTO_{i}.NS", f"Auto Co {i}", "auto", None)
    sector_wide_l1 = CompanyMention(
        name="auto sector", ticker=None, is_direct=False, sector="auto",
        direction="bearish", magnitude_low=1.0, magnitude_high=3.0, rationale="input cost pass-through",
        confidence_score=50, time_horizon="Short-Term",
        impact_level="indirect_l1", parent_ticker="NEVER_RESOLVED.NS",
    )

    resolved = resolve_companies(db_session, [sector_wide_l1])

    assert resolved == []


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


def test_sector_inference_entry_has_no_rationale(db_session):
    db_session.add(Company(ticker="ITC.NS", name="ITC Ltd.", sector="fmcg", index_tier="NIFTY50"))
    db_session.commit()

    resolved = resolve_companies(db_session, [CompanyMention(
        name="fmcg sector", is_direct=False, sector="fmcg",
        direction="bullish", magnitude_low=1.0, magnitude_high=3.0,
        rationale="Sector-wide exposure via fmcg: some template text",
        time_horizon="Short-Term",
    )])

    assert len(resolved) == 1
    assert resolved[0]["basis"] == "sector_inference"
    assert resolved[0]["rationale"] is None


def test_direct_mention_keeps_its_rationale(db_session):
    db_session.add(Company(ticker="HPCL.NS", name="Hindustan Petroleum Corporation", sector="oil_gas", index_tier="NIFTY50"))
    db_session.commit()

    resolved = resolve_companies(db_session, [CompanyMention(
        name="Hindustan Petroleum Corporation", ticker="HPCL.NS", is_direct=True,
        direction="bullish", magnitude_low=1.0, magnitude_high=3.0,
        rationale="Real, article-specific reasoning.", time_horizon="Short-Term",
    )])

    assert resolved[0]["rationale"] == "Real, article-specific reasoning."


def test_fanout_prefers_companies_sharing_a_named_company_sub_sector(db_session):
    db_session.add_all([
        Company(ticker="ITC.NS", name="ITC Ltd.", sector="fmcg",
                sub_sector="staples_food", index_tier="NIFTY50"),
        Company(ticker="ETERNAL.NS", name="Eternal Ltd.", sector="fmcg",
                sub_sector="retail", index_tier="NIFTY50"),
        Company(ticker="NESTLEIND.NS", name="Nestle India Ltd.", sector="fmcg",
                sub_sector="staples_food", index_tier="NIFTY50"),
    ])
    db_session.commit()

    resolved = resolve_companies(
        db_session,
        [CompanyMention(
            name="fmcg sector", is_direct=False, sector="fmcg",
            direction="bullish", magnitude_low=1.0, magnitude_high=3.0,
            rationale="r", time_horizon="Short-Term",
        )],
        anchor_sub_sectors={"fmcg": {"staples_food"}},
    )

    tickers = {r["company_id"] for r in resolved}
    names = {
        db_session.query(Company).get(cid).ticker for cid in tickers
    }
    assert names == {"ITC.NS", "NESTLEIND.NS"}


def test_fanout_without_an_anchor_falls_back_to_the_whole_sector(db_session):
    db_session.add_all([
        Company(ticker="ITC.NS", name="ITC Ltd.", sector="fmcg",
                sub_sector="staples_food", index_tier="NIFTY50"),
        Company(ticker="ETERNAL.NS", name="Eternal Ltd.", sector="fmcg",
                sub_sector="retail", index_tier="NIFTY50"),
    ])
    db_session.commit()

    resolved = resolve_companies(db_session, [CompanyMention(
        name="fmcg sector", is_direct=False, sector="fmcg",
        direction="bullish", magnitude_low=1.0, magnitude_high=3.0,
        rationale="r", time_horizon="Short-Term",
    )])

    assert len(resolved) == 2


def test_top_n_sector_companies_is_three():
    from app.companies.resolution import TOP_N_SECTOR_COMPANIES
    assert TOP_N_SECTOR_COMPANIES == 3


def _sector_mention(sector):
    # CompanyMention.name is a required str field (not Optional) -- a
    # sector-wide fan-out mention doesn't use it for resolution (dispatch is
    # on is_direct/sector, see resolve_companies), but it must still be a
    # valid string to pass schema validation, consistent with how every
    # other sector mention in this file is constructed (e.g. name="oil
    # sector" above).
    return CompanyMention(
        name=f"{sector} sector", ticker=None, is_direct=False, sector=sector,
        direction="bullish", magnitude_low=1.0, magnitude_high=2.0,
        rationale="r", key_points=[], confidence_score=50, time_horizon="Short-Term",
    )


def _name_mention(name):
    return CompanyMention(
        name=name, ticker=None, is_direct=True, sector=None,
        direction="bullish", magnitude_low=1.0, magnitude_high=2.0,
        rationale="r", key_points=[], confidence_score=50, time_horizon="Short-Term",
    )


def test_matcher_resolves_a_name_without_a_ticker(db_session):
    _make_company(db_session, "APOLLOTYRE.NS", "Apollo Tyres Limited", "auto", None)
    aliases.rebuild_aliases(db_session)

    resolved = resolve_companies(db_session, [_name_mention("Apollo Tyres Ltd")])
    assert len(resolved) == 1


def test_ambiguous_name_resolves_to_nothing(db_session):
    _make_company(db_session, "APOLLOTYRE.NS", "Apollo Tyres Limited", "auto", None)
    _make_company(db_session, "APOLLOHOSP.NS", "Apollo Hospitals Enterprise Limited", "pharma", None)
    aliases.rebuild_aliases(db_session)

    assert resolve_companies(db_session, [_name_mention("Apollo")]) == []


def test_sector_fanout_ranks_by_market_cap(db_session):
    # BIG is in the lowest index tier but is far larger. Under the old
    # _TIER_RANK-first ordering SMALL won; market cap now leads.
    _make_company(db_session, "BIG.NS", "Big Oil Limited", "oil_gas", 900000.0, index_tier="OTHER")
    _make_company(db_session, "SMALL.NS", "Small Oil Limited", "oil_gas", 100.0, index_tier="NIFTY50")

    resolved = resolve_companies(db_session, [_sector_mention("oil_gas")])
    assert db_session.get(Company, resolved[0]["company_id"]).ticker == "BIG.NS"


def test_sector_fanout_still_falls_back_to_index_tier_without_caps(db_session):
    # Guards the concurrent work in f39fd55: when no company has a market
    # cap, nullslast() leaves every row tied and _TIER_RANK must still
    # decide the order.
    _make_company(db_session, "LOW.NS", "Low Tier Oil Limited", "oil_gas", None, index_tier="OTHER")
    _make_company(db_session, "HIGH.NS", "High Tier Oil Limited", "oil_gas", None, index_tier="NIFTY50")

    resolved = resolve_companies(db_session, [_sector_mention("oil_gas")])
    assert db_session.get(Company, resolved[0]["company_id"]).ticker == "HIGH.NS"


def test_sector_fanout_excludes_non_tradeable_companies(db_session):
    shell = _make_company(db_session, "SHELL.BO", "Dormant Shell Limited", "oil_gas", 5000000.0, index_tier="OTHER")
    shell.tradeability = "SUSPENDED"
    db_session.commit()
    _make_company(db_session, "REAL.NS", "Real Oil Limited", "oil_gas", 100.0, index_tier="OTHER")

    resolved = resolve_companies(db_session, [_sector_mention("oil_gas")])
    tickers = {db_session.get(Company, r["company_id"]).ticker for r in resolved}
    assert tickers == {"REAL.NS"}


def test_sector_fanout_excludes_global_companies(db_session):
    xom = _make_company(db_session, "XOM", "Exxon Mobil", "oil_gas", 9000000.0, index_tier="GLOBAL_LARGE_CAP")
    xom.market = "GLOBAL"
    db_session.commit()
    _make_company(db_session, "REAL.NS", "Real Oil Limited", "oil_gas", 100.0, index_tier="OTHER")

    resolved = resolve_companies(db_session, [_sector_mention("oil_gas")])
    tickers = {db_session.get(Company, r["company_id"]).ticker for r in resolved}
    assert tickers == {"REAL.NS"}
