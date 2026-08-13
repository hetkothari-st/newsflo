"""Token-optimization layer tests (spec 2026-08-11 P25): no-call gates,
relationship caches, normalization, net-effect discipline, deterministic
ranking, frontier batching, cache-friendly prompt shape."""
import httpx

from app.analysis.impact_graph.engine import analyze_article_v3
from app.analysis.impact_graph.gemini_json import GeminiJSONClient
from app.analysis.impact_graph.normalize import normalize_node_id
from app.models import Company as CompanyRow
from app.models import CompanyNodeExposure, utcnow

from tests.test_impact_graph import FACTS, FakeRouter, _company, _company_entry, _edge


def _direct_sector_setup(extra=None):
    responses = {
        "extract_facts": FACTS,
        "initial_shocks": {"shocks": [], "direct_nodes": [
            _edge("event", "oil_gas", child_type="sector", parent_type="event", mat=0.7, conf=0.8),
        ]},
        "ripple_discovery": [{"children": []}],
    }
    if extra:
        responses.update(extra)
    return responses


def test_node_normalizer_collapses_synonyms():
    assert (normalize_node_id("Crude Oil Price Rises")
            == normalize_node_id("higher crude prices")
            == normalize_node_id("oil price increase")
            == "crude_price_up")
    assert (normalize_node_id("borrowing cost down")
            == normalize_node_id("funding cost decrease")
            == "financing_cost_down")
    assert normalize_node_id("aviation fuel") == normalize_node_id("ATF")


def test_negative_relationship_cache_skips_candidate(db_session):
    row = _company(db_session, "NOEXP.NS", "No Exposure Co", "oil_gas")
    _company(db_session, "REAL.NS", "Real Co", "oil_gas")
    db_session.add(CompanyNodeExposure(company_id=row.id, node_key="oil_gas",
                                       exposure_exists=0, verified_at=utcnow()))
    db_session.commit()
    captured = {}

    class Router(FakeRouter):
        def call(self, stage, **kwargs):
            if stage == "map_companies":
                schema = kwargs["schema"]
                captured["enum"] = schema["properties"]["companies"]["items"]["properties"]["ticker"]["enum"]
            return super().call(stage, **kwargs)

    router = Router(_direct_sector_setup(
        {"map_companies": {"companies": [_company_entry("REAL.NS", "Real Co")]}}))
    analyze_article_v3(router, "t", "c", session=db_session)
    assert "NOEXP.NS" not in captured["enum"] and "REAL.NS" in captured["enum"]


def test_relationship_cache_seeds_candidacy_but_still_verifies(db_session):
    """A positive relationship-cache row still rides the candidate pool
    (retrieval index, spec §9) and still annotates the prompt with the
    prior mechanism -- but corrective-v4 Task 6 removed the auto-accept
    bypass this test used to pin: the cache can no longer substitute for
    THIS event's verification. The candidate still reaches the verifier,
    and its verdict decides."""
    row = _company(db_session, "CACHED.NS", "Cached Co", "oil_gas")
    db_session.add(CompanyNodeExposure(company_id=row.id, node_key="oil_gas",
                                       exposure_exists=1, strength=0.7,
                                       mechanism="crude input exposure", verified_at=utcnow()))
    db_session.commit()
    router = FakeRouter(_direct_sector_setup(
        {"map_companies": {"companies": [_company_entry("CACHED.NS", "Cached Co")]}}))
    result = analyze_article_v3(router, "t", "c", session=db_session)
    assert result.companies[0].verified is True
    assert "verify_companies" in router.calls  # no bypass: always verified


def test_verification_accept_writes_positive_cache(db_session):
    _company(db_session, "WRITE.NS", "Write Co", "oil_gas")
    router = FakeRouter(_direct_sector_setup({
        "map_companies": {"companies": [_company_entry("WRITE.NS", "Write Co")]},
        "verify_companies": {"accept": ["WRITE.NS"], "reject": []},
    }))
    analyze_article_v3(router, "t", "c", session=db_session)
    company_id = db_session.query(CompanyRow).filter_by(ticker="WRITE.NS").one().id
    cached = db_session.query(CompanyNodeExposure).filter_by(company_id=company_id).one()
    assert cached.exposure_exists == 1 and cached.node_key == "oil_gas"


def test_structural_reject_writes_negative_cache(db_session):
    _company(db_session, "FAKE.NS", "Fake Co", "oil_gas")
    router = FakeRouter(_direct_sector_setup({
        "map_companies": {"companies": [_company_entry("FAKE.NS", "Fake Co")]},
        "verify_companies": {"accept": [], "reject": [
            {"ticker": "FAKE.NS", "reason": "company has no exposure to crude at all"},
        ]},
    }))
    result = analyze_article_v3(router, "t", "c", session=db_session)
    assert result.companies == []
    company_id = db_session.query(CompanyRow).filter_by(ticker="FAKE.NS").one().id
    cached = db_session.query(CompanyNodeExposure).filter_by(company_id=company_id).one()
    assert cached.exposure_exists == 0


def test_event_specific_reject_does_not_poison_cache(db_session):
    _company(db_session, "EVT.NS", "Event Co", "oil_gas")
    router = FakeRouter(_direct_sector_setup({
        "map_companies": {"companies": [_company_entry("EVT.NS", "Event Co")]},
        "verify_companies": {"accept": [], "reject": [
            {"ticker": "EVT.NS", "reason": "immaterial for this specific event"},
        ]},
    }))
    analyze_article_v3(router, "t", "c", session=db_session)
    company_id = db_session.query(CompanyRow).filter_by(ticker="EVT.NS").one().id
    assert db_session.query(CompanyNodeExposure).filter_by(company_id=company_id).count() == 0


def test_mixed_net_direction_lands_neutral_and_confidence_capped(db_session):
    _company(db_session, "MIX.NS", "Mixed Co", "auto")
    entry = _company_entry("MIX.NS", "Mixed Co", direction="bullish", conf=0.9)
    entry.update({"net_direction": "mixed",
                  "positive_channels": ["downtrading to two-wheelers"],
                  "negative_channels": ["household income pressure", "financing stress"]})
    router = FakeRouter({
        "extract_facts": FACTS,
        "initial_shocks": {"shocks": [], "direct_nodes": [
            _edge("event", "auto", child_type="sector", parent_type="event", mat=0.7, conf=0.8),
        ]},
        "map_companies": {"companies": [entry]},
        "ripple_discovery": [{"children": []}],
    })
    result = analyze_article_v3(router, "t", "c", session=db_session)
    company = result.companies[0]
    assert company.confidence <= 0.55  # unresolved net effect never ships confident
    assert result.ranking[0]["bucket"] == "neutral_mixed"  # never a manufactured winner


def test_ranking_is_deterministic_no_llm_call(db_session):
    _company(db_session, "R1.NS", "R1", "oil_gas")
    router = FakeRouter(_direct_sector_setup(
        {"map_companies": {"companies": [_company_entry("R1.NS", "R1")]}}))
    result = analyze_article_v3(router, "t", "c", session=db_session)
    assert "rank_companies" not in router.calls
    assert result.ranking[0]["ticker"] == "R1.NS"


def test_same_parent_frontier_nodes_batch_into_one_call(db_session):
    router = FakeRouter({
        "extract_facts": FACTS,
        "initial_shocks": {"shocks": [
            {"shock_id": f"shock_{i}", "label": f"shock {i}", "direction": "bearish",
             "mechanism": "m", "confidence": 0.9, "materiality": 0.9, "impact_strength": 0.9}
            for i in range(3)
        ], "direct_nodes": []},
        "ripple_discovery": [{"children": []}],
    })
    analyze_article_v3(router, "t", "c", session=db_session)
    assert router.calls.count("ripple_discovery") == 1  # 3 siblings, one batched call


def test_static_prefix_rides_contents_head_for_implicit_cache(monkeypatch):
    captured = {}

    class _Response:
        status_code = 200

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "{}"}]}}],
                    "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1}}

    def fake_post(url, json=None, timeout=None):
        captured["body"] = json
        return _Response()

    monkeypatch.setattr(httpx, "post", fake_post)
    GeminiJSONClient("k").generate(model="m", schema={}, static_prefix="STATIC-RULES",
                                   dynamic_suffix="dynamic", thinking="low")
    parts = captured["body"]["contents"][0]["parts"]
    assert parts[0]["text"] == "STATIC-RULES"  # cacheable head, byte-stable
    assert "systemInstruction" not in captured["body"]


def test_triage_narrow_event_gets_small_graph_and_tight_budget(db_session, monkeypatch):
    """Deterministic triage (cost-target 2026-08-11): a non-macro
    event_type runs depth-capped with tier token ceilings; a broad type
    keeps the full graph. Zero extra LLM calls either way. Staged-narrow
    path pinned (single-call mode covered by its own tests)."""
    from app.config import IMPACT_TRIAGE_TIERS, settings as _settings
    monkeypatch.setattr(_settings, "impact_narrow_single_call", False)
    narrow_facts = dict(FACTS, event_type="earnings")
    counter = {"n": 0}

    class Router(FakeRouter):
        def call(self, stage, **kwargs):
            if stage == "ripple_discovery":
                counter["n"] += 1
                return {"children": [_edge(f"m{counter['n']}", f"m{counter['n']+1}",
                                           child_type="economic_node", mat=0.9, conf=0.95)]}                     if counter["n"] == 1 else {"children": []}
            return super().call(stage, **kwargs)

    router = Router({
        "extract_facts": narrow_facts,
        "initial_shocks": {"shocks": [{"shock_id": "m1", "label": "m1", "direction": "bearish",
                                       "mechanism": "m", "confidence": 0.9, "materiality": 0.9,
                                       "impact_strength": 0.9}], "direct_nodes": []},
    })
    result = analyze_article_v3(router, "t", "c", session=db_session)
    # narrow tier: max_depth 2 -> nothing past distance 2
    assert max((e.causal_distance for e in result.edges), default=0) <= IMPACT_TRIAGE_TIERS["narrow"]["max_depth"]
    # tier ceilings applied to the budget
    assert router.budget.max_output_override == IMPACT_TRIAGE_TIERS["narrow"]["max_output_tokens"]


def test_triage_broad_event_keeps_full_budget(db_session):
    router = FakeRouter({
        "extract_facts": FACTS,  # geopolitics -> broad
        "initial_shocks": {"shocks": [], "direct_nodes": []},
    })
    analyze_article_v3(router, "t", "c", session=db_session)
    assert router.budget.max_output_override is None


def test_narrow_single_call_uses_two_llm_calls(db_session):
    """Narrow tier + single-call mode: facts + narrow_graph +
    narrow_companies -- never the staged loop."""
    _company(db_session, "NARROW.NS", "Narrow Co", "fmcg")
    router = FakeRouter({
        "extract_facts": dict(FACTS, event_type="earnings"),
        "narrow_graph": {
            "shocks": [{"shock_id": "demand_hit", "label": "Demand hit", "direction": "bearish",
                        "mechanism": "m", "confidence": 0.85, "materiality": 0.7,
                        "impact_strength": 0.6}],
            "edges": [_edge("demand_hit", "fmcg", child_type="sector", mat=0.6, conf=0.8)],
            "channel_audit": [{"channel": "demand", "verdict": "kept"}],
        },
        "narrow_companies": {"companies": [
            dict(_company_entry("NARROW.NS", "Narrow Co", impact=0.5, conf=0.8),
                 parent_id="fmcg", net_direction="bearish"),
        ]},
    })
    result = analyze_article_v3(router, "t", "c", session=db_session)
    assert router.calls == ["extract_facts", "narrow_graph", "narrow_companies"]
    assert [c.ticker for c in result.companies] == ["NARROW.NS"]
    company = result.companies[0]
    assert company.causal_distance == 2  # sits AT the sector node's distance
    assert company.verified is True      # low-risk: self-check stands
    assert result.ranking[0]["bucket"] == "adversely_affected"


def test_narrow_single_call_escalates_risky_results_to_verification(db_session):
    _company(db_session, "BIGIMP.NS", "Big Impact Co", "fmcg")
    router = FakeRouter({
        "extract_facts": dict(FACTS, event_type="earnings"),
        "narrow_graph": {
            "shocks": [{"shock_id": "demand_hit", "label": "d", "direction": "bearish",
                        "mechanism": "m", "confidence": 0.85, "materiality": 0.7,
                        "impact_strength": 0.6}],
            "edges": [_edge("demand_hit", "fmcg", child_type="sector", mat=0.6, conf=0.8)],
        },
        "narrow_companies": {"companies": [
            dict(_company_entry("BIGIMP.NS", "Big Impact Co", impact=0.9, conf=0.8),
                 parent_id="fmcg", net_direction="bearish"),  # impact >= 0.7 -> risky
        ]},
        "verify_companies": {"accept": ["BIGIMP.NS"], "reject": []},
    })
    result = analyze_article_v3(router, "t", "c", session=db_session)
    assert "verify_companies" in router.calls
    assert result.companies[0].verified is True


def test_broad_events_never_use_single_call_mode(db_session):
    router = FakeRouter({
        "extract_facts": FACTS,  # geopolitics -> broad tier
        "initial_shocks": {"shocks": [], "direct_nodes": []},
    })
    analyze_article_v3(router, "t", "c", session=db_session)
    assert "narrow_graph" not in router.calls
    assert "initial_shocks" in router.calls


def test_narrow_single_call_stays_candidate_grounded(db_session):
    _company(db_session, "GROUND.NS", "Grounded Co", "fmcg")
    router = FakeRouter({
        "extract_facts": dict(FACTS, event_type="earnings"),
        "narrow_graph": {
            "shocks": [{"shock_id": "demand_hit", "label": "d", "direction": "bearish",
                        "mechanism": "m", "confidence": 0.85, "materiality": 0.7,
                        "impact_strength": 0.6}],
            "edges": [_edge("demand_hit", "fmcg", child_type="sector", mat=0.6, conf=0.8)],
        },
        "narrow_companies": {"companies": [
            dict(_company_entry("INVENTED.NS", "Invented Co"), parent_id="fmcg",
                 net_direction="bearish"),
            dict(_company_entry("GROUND.NS", "Grounded Co"), parent_id="fmcg",
                 net_direction="bearish"),
        ]},
    })
    result = analyze_article_v3(router, "t", "c", session=db_session)
    assert [c.ticker for c in result.companies] == ["GROUND.NS"]
