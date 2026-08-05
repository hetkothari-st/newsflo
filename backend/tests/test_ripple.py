from datetime import date

from app.market.ripple import compute_ripple_companies, get_sector_peers_for_alert
from app.models import Alert, AlertCompany, Article, Company, ImpactEdge, MarketMove, utcnow


def test_ripple_rows_include_cap_tier_and_fundamentals(db_session):
    peak = _company("PEAK.NS")
    beneficiary = Company(
        ticker="BEN.NS", name="Beneficiary Co", sector="oil_gas", index_tier="NIFTY50",
        market_cap=5000.0, business_desc="Makes beneficiary things.",
        official_sector="Energy", eps=28.98,
        financials_source="BSE", financials_as_of=date(2026, 8, 4),
    )
    db_session.add_all([peak, beneficiary])
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, peak.id))
    db_session.add(_alert_company(alert.id, beneficiary.id, impact_level="indirect_l1"))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=peak.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-4.0, sector_move_pct=-0.5, excess_move_pct=-3.5,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=beneficiary.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=2.0, sector_move_pct=0.3, excess_move_pct=1.7,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    result = compute_ripple_companies(db_session, alert, exclude_company_id=peak.id, held_company_ids=set())

    # business_desc was LLM-invented and is never served now, regardless of
    # what's stored on the row; the sourced fundamentals payload replaces it.
    assert result[0]["business_desc"] is None
    assert result[0]["fundamentals"]["classification"]["sector"] == "Energy"
    assert result[0]["fundamentals"]["ratios"]["eps"] == 28.98
    assert result[0]["cap_tier"] in ("LARGE", "MID", "SMALL", None)


def test_ripple_row_cap_tier_reports_a_real_tier_when_fresh(db_session):
    """Proves the resolve_cap_tier wire (Task 19): a fresh, ranked market
    cap must produce a definite tier on the ripple row, not just "something
    in this tuple or None". test_ripple_rows_include_cap_tier_and_business_
    desc's tolerant assertion would stay green even if this wire were
    ripped out and cap_tier hardcoded to None -- this test would not."""
    peak = _company("PEAK.NS")
    beneficiary = Company(
        ticker="BEN2.NS", name="Beneficiary Co 2", sector="oil_gas", index_tier="NIFTY50",
        market_cap=5000.0, market_cap_source="BSE", market_cap_as_of=date.today(),
    )
    db_session.add_all([peak, beneficiary])
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, peak.id))
    db_session.add(_alert_company(alert.id, beneficiary.id, impact_level="indirect_l1"))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=peak.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-4.0, sector_move_pct=-0.5, excess_move_pct=-3.5,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=beneficiary.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=2.0, sector_move_pct=0.3, excess_move_pct=1.7,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    result = compute_ripple_companies(db_session, alert, exclude_company_id=peak.id, held_company_ids=set())

    # Peak has no market_cap of its own, so beneficiary is the only ranked
    # company in the pool -- rank 1 -> LARGE.
    assert result[0]["cap_tier"] == "LARGE"


def test_ripple_row_cap_tier_withheld_when_market_cap_as_of_missing(db_session):
    """Same setup, but the company's market_cap has no market_cap_as_of --
    resolve_cap_tier's staleness rule (a missing as_of is stale) must
    withhold the tier here too, proving ripple.py runs the real staleness
    gate rather than the old compute_cap_tier_for_ticker, which never
    checked staleness at all."""
    peak = _company("PEAK.NS")
    beneficiary = Company(
        ticker="BEN3.NS", name="Beneficiary Co 3", sector="oil_gas", index_tier="NIFTY50",
        market_cap=5000.0,  # no market_cap_as_of
    )
    db_session.add_all([peak, beneficiary])
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, peak.id))
    db_session.add(_alert_company(alert.id, beneficiary.id, impact_level="indirect_l1"))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=peak.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-4.0, sector_move_pct=-0.5, excess_move_pct=-3.5,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=beneficiary.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=2.0, sector_move_pct=0.3, excess_move_pct=1.7,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    result = compute_ripple_companies(db_session, alert, exclude_company_id=peak.id, held_company_ids=set())

    assert result[0]["cap_tier"] is None


def _company(ticker, sector="oil_gas"):
    return Company(ticker=ticker, name=f"Company {ticker}", sector=sector, index_tier="NIFTY50")


def _article(db_session):
    article = Article(source="test", url=f"https://example.com/{id(object())}", title="t", content="c")
    db_session.add(article)
    db_session.commit()
    return article


def _alert_company(alert_id, company_id, direction="bullish", impact_level="direct"):
    return AlertCompany(
        alert_id=alert_id, company_id=company_id, direction=direction,
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", basis="direct_mention",
        impact_level=impact_level,
    )


def _edge(alert_id, from_id, to_id, relation, direction="bullish"):
    return ImpactEdge(
        alert_id=alert_id, from_company_id=from_id, from_node_kind="company", from_label="X",
        to_company_id=to_id, to_node_kind="company", to_label="Y",
        relation=relation, direction=direction, note="n", source="llm_only",
    )


def test_excludes_the_peak_company(db_session):
    peak = _company("PEAK.NS")
    other = _company("OTHER.NS")
    db_session.add_all([peak, other])
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, peak.id))
    db_session.add(_alert_company(alert.id, other.id, impact_level="indirect_l1"))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=peak.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-4.0, sector_move_pct=-0.5, excess_move_pct=-3.5,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=other.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=1.0, sector_move_pct=0.2, excess_move_pct=0.8,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    result = compute_ripple_companies(db_session, alert, exclude_company_id=peak.id, held_company_ids=set())

    tickers = {r["ticker"] for r in result}
    assert tickers == {"OTHER.NS"}


def test_groups_by_relationship_via_impact_edge(db_session):
    peak = _company("PEAK.NS")
    beneficiary = _company("BEN.NS")
    db_session.add_all([peak, beneficiary])
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, peak.id))
    db_session.add(_alert_company(alert.id, beneficiary.id, impact_level="indirect_l1"))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=peak.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-4.0, sector_move_pct=-0.5, excess_move_pct=-3.5,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=beneficiary.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=2.0, sector_move_pct=0.3, excess_move_pct=1.7,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(_edge(alert.id, peak.id, beneficiary.id, relation="commodity", direction="bullish"))
    db_session.commit()

    result = compute_ripple_companies(db_session, alert, exclude_company_id=peak.id, held_company_ids=set())

    assert result[0]["relationship"] == "BENEFICIARY"


def test_company_with_no_edge_defaults_to_sector_wide(db_session):
    peak = _company("PEAK.NS")
    unlinked = _company("UNLINKED.NS")
    db_session.add_all([peak, unlinked])
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, peak.id))
    db_session.add(_alert_company(alert.id, unlinked.id, impact_level="indirect_l1"))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=peak.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-4.0, sector_move_pct=-0.5, excess_move_pct=-3.5,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=unlinked.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=1.0, sector_move_pct=0.2, excess_move_pct=0.8,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    result = compute_ripple_companies(db_session, alert, exclude_company_id=peak.id, held_company_ids=set())

    assert result[0]["relationship"] == "SECTOR_WIDE"


def test_unmeasured_company_is_exposure_only_with_no_number(db_session):
    peak = _company("PEAK.NS")
    unmeasured = _company("NODATA.NS")
    db_session.add_all([peak, unmeasured])
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, peak.id))
    db_session.add(_alert_company(alert.id, unmeasured.id, impact_level="indirect_l1"))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=peak.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-4.0, sector_move_pct=-0.5, excess_move_pct=-3.5,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=unmeasured.id, benchmark_ticker="^CNXENERGY",
        measurement_status="no_data", measured_at=utcnow(),
    ))
    db_session.commit()

    result = compute_ripple_companies(db_session, alert, exclude_company_id=peak.id, held_company_ids=set())

    assert result[0]["is_exposure_only"] is True
    assert result[0]["excess_move_pct"] is None
    assert result[0]["intensity"] is None


def test_company_with_no_market_move_row_at_all_is_exposure_only(db_session):
    peak = _company("PEAK.NS")
    never_measured = _company("NEVER.NS")
    db_session.add_all([peak, never_measured])
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, peak.id))
    db_session.add(_alert_company(alert.id, never_measured.id, impact_level="indirect_l1"))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=peak.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-4.0, sector_move_pct=-0.5, excess_move_pct=-3.5,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    result = compute_ripple_companies(db_session, alert, exclude_company_id=peak.id, held_company_ids=set())

    assert result[0]["is_exposure_only"] is True


def test_sorted_by_intensity_descending_exposure_only_sorts_last(db_session):
    peak = _company("PEAK.NS")
    small = _company("SMALL.NS")
    big = _company("BIG.NS")
    unmeasured = _company("UNMEASURED.NS")
    db_session.add_all([peak, small, big, unmeasured])
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, peak.id))
    for c in (small, big, unmeasured):
        db_session.add(_alert_company(alert.id, c.id, impact_level="indirect_l1"))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=peak.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-4.0, sector_move_pct=-0.5, excess_move_pct=-3.5,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=small.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=0.5, sector_move_pct=0.3, excess_move_pct=0.2,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=big.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=3.0, sector_move_pct=0.3, excess_move_pct=2.7,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=unmeasured.id, benchmark_ticker="^CNXENERGY",
        measurement_status="no_data", measured_at=utcnow(),
    ))
    db_session.commit()

    result = compute_ripple_companies(db_session, alert, exclude_company_id=peak.id, held_company_ids=set())

    tickers_in_order = [r["ticker"] for r in result]
    assert tickers_in_order[-1] == "UNMEASURED.NS"
    assert tickers_in_order.index("BIG.NS") < tickers_in_order.index("SMALL.NS")


def test_in_my_holdings_reflects_held_company_ids(db_session):
    peak = _company("PEAK.NS")
    held = _company("HELD.NS")
    db_session.add_all([peak, held])
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, peak.id))
    db_session.add(_alert_company(alert.id, held.id, impact_level="indirect_l1"))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=peak.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-4.0, sector_move_pct=-0.5, excess_move_pct=-3.5,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=held.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=1.0, sector_move_pct=0.2, excess_move_pct=0.8,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    result = compute_ripple_companies(
        db_session, alert, exclude_company_id=peak.id, held_company_ids={held.id},
    )

    assert result[0]["in_my_holdings"] is True


def test_sector_peers_excludes_self_and_other_sectors(db_session):
    target = _company("TARGET.NS", sector="oil_gas")
    same_sector = _company("PEER.NS", sector="oil_gas")
    other_sector = _company("OTHER.NS", sector="it")
    db_session.add_all([target, same_sector, other_sector])
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    for c in (target, same_sector, other_sector):
        db_session.add(_alert_company(alert.id, c.id))
    for c, excess in ((target, -3.0), (same_sector, 1.5), (other_sector, 2.0)):
        db_session.add(MarketMove(
            alert_id=alert.id, company_id=c.id, benchmark_ticker="^CNXENERGY",
            raw_move_pct=excess, sector_move_pct=0.0, excess_move_pct=excess,
            measurement_status="ok", measured_at=utcnow(),
        ))
    db_session.commit()

    result = get_sector_peers_for_alert(db_session, alert, target, held_company_ids=set())

    tickers = {r["ticker"] for r in result}
    assert tickers == {"PEER.NS"}


def test_sector_peers_row_shape_matches_ripple_row_shape(db_session):
    target = _company("TARGET.NS", sector="oil_gas")
    peer = _company("PEER.NS", sector="oil_gas")
    db_session.add_all([target, peer])
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, target.id))
    db_session.add(_alert_company(alert.id, peer.id))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=target.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-3.0, sector_move_pct=0.0, excess_move_pct=-3.0,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=peer.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=1.5, sector_move_pct=0.0, excess_move_pct=1.5,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    result = get_sector_peers_for_alert(db_session, alert, target, held_company_ids=set())

    assert set(result[0].keys()) == {
        "ticker", "name", "sector", "direction", "excess_move_pct", "intensity",
        "is_exposure_only", "in_my_holdings", "cap_tier", "business_desc", "fundamentals", "why", "logo_url",
    }


def test_sector_peers_sorted_by_intensity_exposure_only_last(db_session):
    target = _company("TARGET.NS", sector="oil_gas")
    small = _company("SMALL.NS", sector="oil_gas")
    big = _company("BIG.NS", sector="oil_gas")
    unmeasured = _company("UNMEASURED.NS", sector="oil_gas")
    db_session.add_all([target, small, big, unmeasured])
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    for c in (target, small, big, unmeasured):
        db_session.add(_alert_company(alert.id, c.id))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=target.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-3.0, sector_move_pct=0.0, excess_move_pct=-3.0,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=small.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=0.2, sector_move_pct=0.0, excess_move_pct=0.2,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=big.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=2.7, sector_move_pct=0.0, excess_move_pct=2.7,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=unmeasured.id, benchmark_ticker="^CNXENERGY",
        measurement_status="no_data", measured_at=utcnow(),
    ))
    db_session.commit()

    result = get_sector_peers_for_alert(db_session, alert, target, held_company_ids=set())

    tickers_in_order = [r["ticker"] for r in result]
    assert tickers_in_order[-1] == "UNMEASURED.NS"
    assert tickers_in_order.index("BIG.NS") < tickers_in_order.index("SMALL.NS")


def test_compute_ripple_companies_still_includes_relationship_after_refactor(db_session):
    """Regression guard for the Task 2 refactor: compute_ripple_companies'
    PUBLIC return shape (with 'relationship') must be byte-for-byte
    unchanged even though its internals now delegate to the shared
    _alert_company_rows helper."""
    peak = _company("PEAK.NS")
    beneficiary = _company("BEN.NS")
    db_session.add_all([peak, beneficiary])
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, peak.id))
    db_session.add(_alert_company(alert.id, beneficiary.id, impact_level="indirect_l1"))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=peak.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-4.0, sector_move_pct=-0.5, excess_move_pct=-3.5,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=beneficiary.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=2.0, sector_move_pct=0.3, excess_move_pct=1.7,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(_edge(alert.id, peak.id, beneficiary.id, relation="commodity", direction="bullish"))
    db_session.commit()

    result = compute_ripple_companies(db_session, alert, exclude_company_id=peak.id, held_company_ids=set())

    assert set(result[0].keys()) == {
        "ticker", "name", "sector", "relationship", "direction", "excess_move_pct",
        "intensity", "is_exposure_only", "in_my_holdings", "cap_tier", "business_desc", "fundamentals", "why", "logo_url",
    }
    assert result[0]["relationship"] == "BENEFICIARY"


def test_excludes_direct_non_peak_companies_from_ripple(db_session):
    """Ripple (Level 2) must only show genuine spillover (indirect_l1/l2)
    -- a company the article directly names is shown by
    compute_impact_companies (Level 1's Affected tab) instead. Before this
    fix, every non-peak AlertCompany appeared in ripple regardless of
    impact_level, duplicating Affected's content verbatim (confirmed live
    in production: a user reported the two tabs "literally show the same
    companies")."""
    peak = _company("PEAK.NS")
    other_direct = _company("DIRECT.NS")
    spillover = _company("SPILLOVER.NS")
    db_session.add_all([peak, other_direct, spillover])
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, peak.id))
    db_session.add(_alert_company(alert.id, other_direct.id, impact_level="direct"))
    db_session.add(_alert_company(alert.id, spillover.id, impact_level="indirect_l1"))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=peak.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-4.0, sector_move_pct=-0.5, excess_move_pct=-3.5,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=other_direct.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=1.0, sector_move_pct=0.2, excess_move_pct=0.8,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=spillover.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=1.2, sector_move_pct=0.2, excess_move_pct=1.0,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    result = compute_ripple_companies(db_session, alert, exclude_company_id=peak.id, held_company_ids=set())

    tickers = {r["ticker"] for r in result}
    assert tickers == {"SPILLOVER.NS"}


def test_includes_both_indirect_levels(db_session):
    """indirect_l2 (a second cascade hop) must qualify for ripple too --
    only impact_level == "direct" is excluded, not every level besides
    indirect_l1 specifically."""
    peak = _company("PEAK.NS")
    l1 = _company("L1.NS")
    l2 = _company("L2.NS")
    db_session.add_all([peak, l1, l2])
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, peak.id))
    db_session.add(_alert_company(alert.id, l1.id, impact_level="indirect_l1"))
    db_session.add(_alert_company(alert.id, l2.id, impact_level="indirect_l2"))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=peak.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-4.0, sector_move_pct=-0.5, excess_move_pct=-3.5,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=l1.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=1.0, sector_move_pct=0.2, excess_move_pct=0.8,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=l2.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=0.6, sector_move_pct=0.1, excess_move_pct=0.5,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    result = compute_ripple_companies(db_session, alert, exclude_company_id=peak.id, held_company_ids=set())

    tickers = {r["ticker"] for r in result}
    assert tickers == {"L1.NS", "L2.NS"}


def test_ripple_rows_include_why_when_present(db_session):
    peak = _company("PEAK.NS")
    spillover = _company("SPILLOVER.NS")
    db_session.add_all([peak, spillover])
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, peak.id))
    ripple_ac = _alert_company(alert.id, spillover.id, impact_level="indirect_l1")
    ripple_ac.why = "Higher input costs squeeze this supplier's own margins."
    db_session.add(ripple_ac)
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=peak.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-4.0, sector_move_pct=-0.5, excess_move_pct=-3.5,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=spillover.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=1.0, sector_move_pct=0.2, excess_move_pct=0.8,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    result = compute_ripple_companies(db_session, alert, exclude_company_id=peak.id, held_company_ids=set())

    assert result[0]["why"] == "Higher input costs squeeze this supplier's own margins."


def test_ripple_rows_why_is_none_when_not_populated(db_session):
    peak = _company("PEAK.NS")
    spillover = _company("SPILLOVER.NS")
    db_session.add_all([peak, spillover])
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, peak.id))
    db_session.add(_alert_company(alert.id, spillover.id, impact_level="indirect_l1"))  # why left unset
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=peak.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-4.0, sector_move_pct=-0.5, excess_move_pct=-3.5,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=spillover.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=1.0, sector_move_pct=0.2, excess_move_pct=0.8,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    result = compute_ripple_companies(db_session, alert, exclude_company_id=peak.id, held_company_ids=set())

    assert result[0]["why"] is None


def test_ripple_rows_include_logo_url(db_session, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "brandfetch_client_id", "test-client-id")

    peak = _company("PEAK.NS")
    spillover = Company(
        ticker="SPILLOVER.NS", name="Spillover Co", sector="oil_gas", index_tier="NIFTY50",
        isin="INE999Z99999",
    )
    db_session.add_all([peak, spillover])
    db_session.commit()
    article = _article(db_session)
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(_alert_company(alert.id, peak.id))
    db_session.add(_alert_company(alert.id, spillover.id, impact_level="indirect_l1"))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=peak.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-4.0, sector_move_pct=-0.5, excess_move_pct=-3.5,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=spillover.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=1.0, sector_move_pct=0.2, excess_move_pct=0.8,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.commit()

    result = compute_ripple_companies(db_session, alert, exclude_company_id=peak.id, held_company_ids=set())

    assert result[0]["logo_url"] == "https://cdn.brandfetch.io/isin/INE999Z99999?c=test-client-id"
