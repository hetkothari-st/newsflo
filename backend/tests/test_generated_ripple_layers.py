import json
from types import SimpleNamespace

from app.analysis.refinement import generate_ripple_layers
from app.market.ripple_layers import compute_ripple_layers
from app.models import Alert, AlertCompany, AlertRippleLayer, Article, Company, MarketMove, utcnow
from tests.test_ripple_layers import _alert_with_companies


class _FakeToolClient:
    """Minimal chat.completions.create fake returning one canned tool call."""

    def __init__(self, tool_name: str, payload: dict):
        function = SimpleNamespace(name=tool_name, arguments=json.dumps(payload))
        message = SimpleNamespace(tool_calls=[SimpleNamespace(function=function)])
        response = SimpleNamespace(choices=[SimpleNamespace(message=message)])
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: response))


_COMPANIES = [
    {"ticker": "A.NS", "name": "A", "sector": "oil_gas", "sub_sector": None, "direction": "bearish", "why": None},
    {"ticker": "B.NS", "name": "B", "sector": "auto", "sub_sector": None, "direction": "bullish", "why": None},
]


def test_generator_validates_relationship_tickers_and_dedup():
    payload = {"layers": [
        {"title": "Losers — battery makers", "relationship": "EXPOSED", "note": "n1", "tickers": ["A.NS", "GHOST.NS"]},
        {"title": "Winners — recyclers", "relationship": "NOT_A_TYPE", "note": "n2", "tickers": ["B.NS"]},
        {"title": "Winners — assemblers", "relationship": "USER", "note": "n3", "tickers": ["B.NS", "A.NS"]},
    ]}
    layers = generate_ripple_layers(_FakeToolClient("record_ripple_layers", payload), "t", "c", _COMPANIES)
    # Unknown ticker dropped; bad relationship layer dropped entirely; a
    # ticker claimed twice keeps only its first section.
    assert [(l["title"], l["tickers"]) for l in layers] == [
        ("Losers — battery makers", ["A.NS"]),
        ("Winners — assemblers", ["B.NS"]),
    ]


def test_generator_returns_empty_without_companies_or_on_failure():
    assert generate_ripple_layers(_FakeToolClient("record_ripple_layers", {"layers": []}), "t", "c", []) == []
    class _Boom:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    raise ConnectionError("down")
    assert generate_ripple_layers(_Boom(), "t", "c", _COMPANIES) == []


def _seed_alert_with_two_companies(db_session, event_type=None):
    a = Company(ticker="A.NS", name="Company A", sector="oil_gas", index_tier="NIFTY50", market_cap=900000.0)
    b = Company(ticker="B.NS", name="Company B", sector="auto", index_tier="NIFTY50", market_cap=500000.0)
    db_session.add_all([a, b])
    db_session.commit()
    article = Article(source="test", url="https://example.com/gen", title="Story", content="c")
    db_session.add(article)
    db_session.commit()
    alert = Alert(article_id=article.id, category="other", event_type=event_type)
    db_session.add(alert)
    db_session.flush()
    for company, direction in ((a, "bearish"), (b, "bullish")):
        db_session.add(AlertCompany(
            alert_id=alert.id, company_id=company.id, direction=direction,
            magnitude_low=1.0, magnitude_high=2.0, rationale="r", basis="direct_mention",
        ))
        db_session.add(MarketMove(
            alert_id=alert.id, company_id=company.id, benchmark_ticker="^NSEI",
            raw_move_pct=1.0, sector_move_pct=0.0, excess_move_pct=1.0 if direction == "bullish" else -1.0,
            volume=100.0, avg_volume_20d=100.0, volume_multiple=1.0,
            measurement_status="ok", measured_at=utcnow(),
        ))
    db_session.commit()
    db_session.refresh(alert)
    return alert


def test_read_time_prefers_generated_sections_and_buckets_the_rest(db_session):
    alert = _seed_alert_with_two_companies(db_session)
    db_session.add(AlertRippleLayer(
        alert_id=alert.id, position=0, title="Losers — story-specific section",
        relationship="EXPOSED", note="why this group moves together",
        tickers_json=json.dumps(["A.NS"]),
    ))
    db_session.commit()

    layers = compute_ripple_layers(db_session, alert, held_company_ids=set())
    assert layers[0]["title"] == "Losers — story-specific section"
    assert layers[0]["relationship"] == "EXPOSED"
    assert layers[0]["note"] == "why this group moves together"
    assert [r["ticker"] for r in layers[0]["rows"]] == ["A.NS"]
    # The unclaimed company still renders, in a generic fallback bucket.
    remaining = [r["ticker"] for layer in layers[1:] for r in layer["rows"]]
    assert remaining == ["B.NS"]


def test_read_time_without_generated_rows_keeps_template_or_buckets(db_session):
    alert = _seed_alert_with_two_companies(db_session)
    layers = compute_ripple_layers(db_session, alert, held_company_ids=set())
    tickers = [r["ticker"] for layer in layers for r in layer["rows"]]
    assert sorted(tickers) == ["A.NS", "B.NS"]


def test_template_layer_cannot_claim_a_sector_inference_row(db_session):
    # event_type="repo_rate_change" activates the MACRO_POLICY template,
    # whose "banks vs NBFCs" layer matches on sector alone -- so a banking
    # fan-out row would be claimed into a DIRECT-family layer.
    alert = _alert_with_companies(db_session, [
        {"ticker": "HDFCBANK.NS", "sector": "banking", "basis": "direct_mention",
         "impact_level": "direct", "direction": "bullish"},
        {"ticker": "AXISBANK.NS", "sector": "banking", "basis": "sector_inference",
         "impact_level": "direct", "direction": "bullish"},
    ], event_type="repo_rate_change")

    layers = compute_ripple_layers(db_session, alert, held_company_ids=set())

    by_ticker = {row["ticker"]: layer for layer in layers for row in layer["rows"]}
    assert by_ticker["AXISBANK.NS"]["relationship"] == "SECTOR_WIDE"
    # The analyzed row still gets its template layer -- this must not
    # disable the template tier, only exclude fan-out from it.
    assert by_ticker["HDFCBANK.NS"]["relationship"] != "SECTOR_WIDE"

    tickers = [row["ticker"] for layer in layers for row in layer["rows"]]
    assert sorted(tickers) == ["AXISBANK.NS", "HDFCBANK.NS"]


def test_generated_layer_can_claim_an_analyzed_indirect_row_with_no_impact_edge(db_session):
    # Regression test: an analyzed (basis="direct_mention") indirect_l1 row
    # with no ImpactEdge at all gets engine_relation="" ->
    # relation_to_ripple_relationship("") -> "SECTOR_WIDE" as its bucket_key
    # -- purely because that function's fallback for an unrecognized/empty
    # relation IS SECTOR_WIDE, not because this row is fan-out. It must
    # still be claimable by a generated (tier-1) layer; the old
    # `bucket_keys[i] != "SECTOR_WIDE"` proxy incorrectly excluded it.
    alert = _alert_with_companies(db_session, [
        {"ticker": "TSM.NS", "sector": "it", "basis": "direct_mention",
         "impact_level": "indirect_l1", "direction": "bullish"},
    ])
    db_session.add(AlertRippleLayer(
        alert_id=alert.id, position=0, title="Winners — foundry partners",
        relationship="SUPPLIER", note="n",
        tickers_json=json.dumps(["TSM.NS"]),
    ))
    db_session.commit()

    layers = compute_ripple_layers(db_session, alert, held_company_ids=set())

    assert layers[0]["title"] == "Winners — foundry partners"
    assert [r["ticker"] for r in layers[0]["rows"]] == ["TSM.NS"]


def test_generated_layer_cannot_claim_a_sector_inference_row(db_session):
    alert = _alert_with_companies(db_session, [
        {"ticker": "HPCL.NS", "sector": "oil_gas", "basis": "direct_mention",
         "impact_level": "direct", "direction": "bullish"},
        {"ticker": "ETERNAL.NS", "sector": "fmcg", "basis": "sector_inference",
         "impact_level": "direct", "direction": "bullish"},
    ])
    # A generated layer that (wrongly) tries to claim the fan-out row.
    db_session.add(AlertRippleLayer(
        alert_id=alert.id, position=0, title="Losers — consumer names",
        relationship="EXPOSED", note="n",
        tickers_json=json.dumps(["HPCL.NS", "ETERNAL.NS"]),
    ))
    db_session.commit()

    layers = compute_ripple_layers(db_session, alert, held_company_ids=set())

    by_ticker = {row["ticker"]: layer for layer in layers for row in layer["rows"]}
    assert by_ticker["HPCL.NS"]["title"] == "Losers — consumer names"
    assert by_ticker["ETERNAL.NS"]["relationship"] == "SECTOR_WIDE"
