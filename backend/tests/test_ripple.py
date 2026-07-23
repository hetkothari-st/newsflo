from app.market.ripple import compute_ripple_companies, get_sector_peers_for_alert
from app.models import Alert, AlertCompany, Article, Company, ImpactEdge, MarketMove, utcnow


def _company(ticker, sector="oil_gas"):
    return Company(ticker=ticker, name=f"Company {ticker}", sector=sector, index_tier="NIFTY50")


def _article(db_session):
    article = Article(source="test", url=f"https://example.com/{id(object())}", title="t", content="c")
    db_session.add(article)
    db_session.commit()
    return article


def _alert_company(alert_id, company_id, direction="bullish"):
    return AlertCompany(
        alert_id=alert_id, company_id=company_id, direction=direction,
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", basis="direct_mention",
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
    db_session.add(_alert_company(alert.id, other.id))
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
    db_session.add(_alert_company(alert.id, beneficiary.id))
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
    db_session.add(_alert_company(alert.id, unlinked.id))
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
    db_session.add(_alert_company(alert.id, unmeasured.id))
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
    db_session.add(_alert_company(alert.id, never_measured.id))
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
    for c in (peak, small, big, unmeasured):
        db_session.add(_alert_company(alert.id, c.id))
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
    db_session.add(_alert_company(alert.id, held.id))
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
        "ticker", "name", "direction", "excess_move_pct", "intensity",
        "is_exposure_only", "in_my_holdings",
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
    db_session.add(_alert_company(alert.id, beneficiary.id))
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
        "intensity", "is_exposure_only", "in_my_holdings",
    }
    assert result[0]["relationship"] == "BENEFICIARY"
