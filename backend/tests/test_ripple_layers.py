from app.models import Alert, AlertCompany, Article, Company, ImpactEdge, MarketMove, utcnow
from app.market.ripple_layers import compute_ripple_layers


def _alert_with_companies(db_session, companies, event_type=None):
    """Build one Alert with one AlertCompany per dict in `companies`. Each
    dict must have at least `ticker` and `sector`; any other Company or
    AlertCompany field (e.g. `basis`, `impact_level`, `direction`) may be
    overridden. `event_type` is optional and only needed to exercise the
    static archetype template tier (`template_layers_for` returns None for
    `event_type=None`, so the template tier is otherwise unreachable).
    Returns the flushed Alert. Reused by test_generated_ripple_layers.py --
    kept minimal on purpose, unlike `_alert_with_layers` which also wires up
    MarketMove/ImpactEdge for the layer-ordering tests above."""
    article = Article(source="test", url=f"https://example.com/{id(companies)}", title="News", content="c")
    db_session.add(article)
    db_session.commit()
    alert = Alert(article_id=article.id, category="test", event_type=event_type)
    db_session.add(alert)
    db_session.flush()
    for spec in companies:
        company = Company(
            ticker=spec["ticker"],
            name=spec.get("name", spec["ticker"]),
            sector=spec["sector"],
            index_tier=spec.get("index_tier", "OTHER"),
            market_cap=spec.get("market_cap", 10000.0),
        )
        db_session.add(company)
        db_session.commit()
        db_session.add(AlertCompany(
            alert_id=alert.id, company_id=company.id,
            direction=spec.get("direction", "bullish"),
            magnitude_low=spec.get("magnitude_low", 1.0),
            magnitude_high=spec.get("magnitude_high", 2.0),
            rationale=spec.get("rationale", "r"),
            basis=spec.get("basis", "direct_mention"),
            impact_level=spec.get("impact_level", "direct"),
        ))
    db_session.commit()
    db_session.flush()
    db_session.refresh(alert)
    return alert


def _alert_with_layers(db_session):
    """One direct bearish company + one indirect bullish supplier + one
    indirect exposure-only (no measured move) supplier."""
    direct = Company(ticker="DIRECT.NS", name="Direct Co", sector="oil_gas", index_tier="NIFTY50", market_cap=900000.0)
    winner = Company(ticker="WINNER.NS", name="Winner Co", sector="oil_gas", index_tier="OTHER", market_cap=20000.0)
    exposure = Company(ticker="EXPO.NS", name="Exposure Co", sector="oil_gas", index_tier="OTHER", market_cap=10000.0)
    db_session.add_all([direct, winner, exposure])
    db_session.commit()
    article = Article(source="test", url="https://example.com/layers", title="Oil news", content="c")
    db_session.add(article)
    db_session.commit()
    alert = Alert(article_id=article.id, category="oil_gas")
    db_session.add(alert)
    db_session.flush()
    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=direct.id, direction="bearish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="r", basis="direct_mention",
        impact_level="direct", why="Crude spike raises input costs.",
    ))
    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=winner.id, direction="bullish",
        magnitude_low=0.5, magnitude_high=1.5, rationale="r", basis="direct_mention",
        impact_level="indirect_l1", parent_company_id=direct.id,
    ))
    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=exposure.id, direction="bullish",
        magnitude_low=0.5, magnitude_high=1.5, rationale="r", basis="direct_mention",
        impact_level="indirect_l1", parent_company_id=direct.id,
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=direct.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=-4.8, sector_move_pct=-0.6, excess_move_pct=-4.2,
        volume=300.0, avg_volume_20d=100.0, volume_multiple=3.0,
        delivery_pct=38.0, avg_traded_value=900_000_000.0,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=winner.id, benchmark_ticker="^CNXENERGY",
        raw_move_pct=2.0, sector_move_pct=0.0, excess_move_pct=2.0,
        volume=100.0, avg_volume_20d=100.0, volume_multiple=1.0,
        avg_traded_value=10_000_000.0,
        measurement_status="ok", measured_at=utcnow(),
    ))
    db_session.add(MarketMove(
        alert_id=alert.id, company_id=exposure.id, benchmark_ticker="^CNXENERGY",
        measurement_status="no_data", measured_at=utcnow(),
    ))
    db_session.add(ImpactEdge(
        alert_id=alert.id, from_company_id=direct.id, from_node_kind="company",
        from_label="DIRECT.NS", to_company_id=winner.id, to_node_kind="company",
        to_label="WINNER.NS", relation="supplier", direction="bullish",
        note="They supply the refining chain.", source="llm_only",
    ))
    db_session.add(ImpactEdge(
        alert_id=alert.id, from_company_id=direct.id, from_node_kind="company",
        from_label="DIRECT.NS", to_company_id=exposure.id, to_node_kind="company",
        to_label="EXPO.NS", relation="supplier", direction="bullish",
        note="They supply the refining chain.", source="llm_only",
    ))
    db_session.commit()
    return alert


def test_direct_layer_comes_first_and_contains_the_direct_company(db_session):
    alert = _alert_with_layers(db_session)
    layers = compute_ripple_layers(db_session, alert, held_company_ids=set())
    assert layers[0]["relationship"] == "DIRECT"
    assert [r["ticker"] for r in layers[0]["rows"]] == ["DIRECT.NS"]
    # Single bearish row -> lose icon, "Directly affected" title.
    assert layers[0]["icon"] == "lose"
    assert layers[0]["title"] == "Directly affected"


def test_supplier_layer_groups_indirect_companies_with_edge_note(db_session):
    alert = _alert_with_layers(db_session)
    layers = compute_ripple_layers(db_session, alert, held_company_ids=set())
    supplier = next(l for l in layers if l["relationship"] == "SUPPLIER")
    assert supplier["icon"] == "win"
    assert supplier["title"] == "Winners — suppliers upstream"
    assert supplier["note"] == "They supply the refining chain."
    assert {r["ticker"] for r in supplier["rows"]} == {"WINNER.NS", "EXPO.NS"}


def test_exposure_only_rows_carry_no_fabricated_numbers_and_sort_last(db_session):
    alert = _alert_with_layers(db_session)
    layers = compute_ripple_layers(db_session, alert, held_company_ids=set())
    supplier = next(l for l in layers if l["relationship"] == "SUPPLIER")
    assert supplier["rows"][-1]["ticker"] == "EXPO.NS"
    expo = supplier["rows"][-1]
    assert expo["is_exposure_only"] is True
    assert expo["excess_move_pct"] is None
    assert expo["intensity"] is None


def test_rows_carry_liquidity_and_delivery_risk_cues(db_session):
    alert = _alert_with_layers(db_session)
    layers = compute_ripple_layers(db_session, alert, held_company_ids=set())
    direct_row = layers[0]["rows"][0]
    assert direct_row["liquidity_tier"] == "HIGH"
    assert direct_row["delivery_pct"] == 38.0
    supplier = next(l for l in layers if l["relationship"] == "SUPPLIER")
    winner_row = next(r for r in supplier["rows"] if r["ticker"] == "WINNER.NS")
    assert winner_row["liquidity_tier"] == "LOW"


def test_multi_sector_direct_bucket_splits_into_per_sector_sections(db_session):
    # A broad event (war, macro shock) marks its whole fan-out "direct" --
    # without the split, the card back collapsed into one flat blob
    # (confirmed live on geopolitics alerts). No event_type -> no archetype
    # template -> the per-sector fallback must still produce sections.
    oil = Company(ticker="OIL.NS", name="Oil Co", sector="oil_gas", index_tier="NIFTY50", market_cap=900000.0)
    defense = Company(ticker="DEF.NS", name="Defense Co", sector="defense", index_tier="NIFTY50", market_cap=500000.0)
    port = Company(ticker="PORT.NS", name="Port Co", sector="railways_transport", index_tier="NIFTY50", market_cap=400000.0)
    db_session.add_all([oil, defense, port])
    db_session.commit()
    article = Article(source="test", url="https://example.com/broad", title="War news", content="c")
    db_session.add(article)
    db_session.commit()
    alert = Alert(article_id=article.id, category="geopolitics", event_type=None)
    db_session.add(alert)
    db_session.flush()
    for company, direction in ((oil, "bullish"), (defense, "bullish"), (port, "bearish")):
        db_session.add(AlertCompany(
            alert_id=alert.id, company_id=company.id, direction=direction,
            magnitude_low=1.0, magnitude_high=2.0, rationale="r", basis="direct_mention",
            impact_level="direct",
        ))
        db_session.add(MarketMove(
            alert_id=alert.id, company_id=company.id, benchmark_ticker="^NSEI",
            raw_move_pct=1.0, sector_move_pct=0.0,
            excess_move_pct=1.0 if direction == "bullish" else -1.0,
            volume=100.0, avg_volume_20d=100.0, volume_multiple=1.0,
            measurement_status="ok", measured_at=utcnow(),
        ))
    db_session.commit()
    db_session.refresh(alert)

    layers = compute_ripple_layers(db_session, alert, held_company_ids=set())
    titles = [l["title"] for l in layers]
    assert len(layers) == 3
    assert "Winners — oil & gas" in titles
    assert "Winners — defense" in titles
    assert "Losers — transport & logistics" in titles


def test_every_company_appears_exactly_once_across_layers(db_session):
    alert = _alert_with_layers(db_session)
    layers = compute_ripple_layers(db_session, alert, held_company_ids=set())
    tickers = [r["ticker"] for layer in layers for r in layer["rows"]]
    assert sorted(tickers) == ["DIRECT.NS", "EXPO.NS", "WINNER.NS"]


def test_sector_inference_row_goes_to_sector_wide_not_direct(db_session):
    # Build one alert with a direct_mention row and a sector_inference row,
    # both at impact_level="direct" -- exactly the shape _sector_fanout_mentions
    # produces for a primary sector.
    alert = _alert_with_companies(db_session, [
        {"ticker": "HPCL.NS", "sector": "oil_gas", "basis": "direct_mention",
         "impact_level": "direct", "direction": "bullish"},
        {"ticker": "ETERNAL.NS", "sector": "fmcg", "basis": "sector_inference",
         "impact_level": "direct", "direction": "bullish"},
    ])

    layers = compute_ripple_layers(db_session, alert, held_company_ids=set())

    by_ticker = {
        row["ticker"]: layer
        for layer in layers for row in layer["rows"]
    }
    assert by_ticker["HPCL.NS"]["relationship"] == "DIRECT"
    assert by_ticker["ETERNAL.NS"]["relationship"] == "SECTOR_WIDE"


def test_every_company_still_appears_exactly_once(db_session):
    alert = _alert_with_companies(db_session, [
        {"ticker": "HPCL.NS", "sector": "oil_gas", "basis": "direct_mention",
         "impact_level": "direct", "direction": "bullish"},
        {"ticker": "ETERNAL.NS", "sector": "fmcg", "basis": "sector_inference",
         "impact_level": "direct", "direction": "bullish"},
    ])

    layers = compute_ripple_layers(db_session, alert, held_company_ids=set())

    tickers = [row["ticker"] for layer in layers for row in layer["rows"]]
    assert sorted(tickers) == ["ETERNAL.NS", "HPCL.NS"]
