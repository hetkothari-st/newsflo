"""Impact-graph v3 engine + router tests (spec 2026-08-11 §16's list).
Every LLM call is faked at the router layer -- no network anywhere."""
import pytest

from app.analysis.impact_graph.budget import ArticleBudget
from app.analysis.impact_graph.engine import analyze_article_v3
from app.analysis.impact_graph.router import StageRouter, StageRouterError
from app.config import settings
from app.models import Company


class FakeRouter:
    """Duck-types StageRouter.call; replays canned per-stage responses and
    records every call made."""

    def __init__(self, responses: dict, provider="gemini", quality="authoritative"):
        self._responses = responses  # stage -> dict | list[dict] | Exception
        self.calls: list[str] = []
        self.provider = provider
        self.quality = quality
        self.budget = ArticleBudget()

    def call(self, stage, **kwargs):
        self.calls.append(stage)
        response = self._responses.get(stage)
        if isinstance(response, list):
            response = response.pop(0) if response else None
        if response is None:
            if stage == "ripple_discovery":
                return {"children": []}
            if stage == "map_companies":
                return {"companies": []}
            if stage in ("verify_companies",):
                return {"accept": _tickers_from(kwargs), "reject": []}
            if stage == "verify_edges":
                return {"verdicts": []}
            if stage == "rank_companies":
                return {"ranked": []}
            raise StageRouterError(f"no canned response for {stage}")
        if isinstance(response, Exception):
            raise response
        return response


def _tickers_from(kwargs) -> list[str]:
    schema = kwargs.get("schema") or {}
    accept = schema.get("properties", {}).get("accept", {})
    return accept.get("items", {}).get("enum", [])


FACTS = {
    "event": "Strait of Hormuz closes", "event_status": "confirmed",
    "facts": "Hormuz closed; a fifth of global crude transits it.",
    "category": "oil_gas", "event_type": "geopolitics",
}


def _company(db, ticker, name, sector):
    row = Company(ticker=ticker, name=name, sector=sector, index_tier="NIFTY50",
                  market="INDIA", tradeability="NORMAL", market_cap=1e12)
    db.add(row)
    db.commit()
    return row


def _edge(parent_id, child_id, child_type="sector", parent_type="economic_node",
          mat=0.6, conf=0.8, direction="bearish", mech="test mechanism", sector=None):
    edge = {
        "parent_type": parent_type, "parent_id": parent_id,
        "child_type": child_type, "child_id": child_id,
        "direction": direction, "mechanism": mech,
        "impact_strength": 0.6, "confidence": conf, "materiality": mat,
        "time_horizon": "Short-Term",
    }
    if sector:
        edge["child_sector"] = sector
    return edge


def _company_entry(ticker, name, direction="bearish", impact=0.7, conf=0.8, mat=0.6):
    return {
        "ticker": ticker, "name": name, "direction": direction,
        "impact_strength": impact, "confidence": conf, "materiality": mat,
        "time_horizon": "Short-Term", "mechanism": "fuel cost exposure",
        "rationale": "operating costs rise with crude", "key_points": ["k"], "reasons": ["r"],
    }


# 1/2: event -> economic node -> sector -> company, no parent_ticker anywhere
def test_event_to_economic_node_to_sector_to_company(db_session, monkeypatch):
    # This test exercises the DYNAMIC discovery path; the knowledge
    # architecture (archetype priors) has its own tests.
    import app.config as config
    monkeypatch.setattr(config, "IMPACT_KNOWLEDGE_MODE", False)
    _company(db_session, "INDIGO.NS", "InterGlobe Aviation", "railways_transport")
    router = FakeRouter({
        "extract_facts": FACTS,
        "initial_shocks": {
            "shocks": [{"shock_id": "crude_supply_disruption", "label": "Crude supply disruption",
                        "direction": "bearish", "mechanism": "fifth of crude transits Hormuz",
                        "confidence": 0.9, "materiality": 0.9, "impact_strength": 0.9}],
            "direct_nodes": [],
        },
        "ripple_discovery": [
            {"children": [_edge("crude_supply_disruption", "crude_oil_price",
                                child_type="economic_node", mat=0.8, conf=0.85)]},
            {"children": [_edge("crude_oil_price", "railways_transport", child_type="sector",
                                mat=0.7, conf=0.8, mech="ATF costs rise with crude")]},
            {"children": []}, {"children": []},
        ],
        # Exposure-based retrieval (architecture upgrade 2026-08-12) now maps
        # candidates at the ECONOMIC nodes too ("crude" hints at transport
        # sectors), so the shock and crude-price nodes each get a call; the
        # model declines there and selects INDIGO at the sector node.
        "map_companies": [
            {"companies": []}, {"companies": []},
            {"companies": [_company_entry("INDIGO.NS", "InterGlobe Aviation")]},
        ],
        "rank_companies": {"ranked": [{"ticker": "INDIGO.NS", "bucket": "adversely_affected"}]},
    })
    result = analyze_article_v3(router, "Hormuz closes", "body", session=db_session, article_id=1)

    tickers = [c.ticker for c in result.companies]
    assert tickers == ["INDIGO.NS"]
    company = result.companies[0]
    # Distance = event(0) -> shock(1) -> crude price(2) -> transport sector(3)
    assert company.causal_distance == 3
    assert company.parent_type == "sector" and company.parent_id == "railways_transport"
    # The chain exists as typed edges, no company-to-company link required.
    ids = {(e.parent_id, e.child_id) for e in result.edges}
    # Node ids are normalized: crude_oil_price -> crude_price.
    assert ("event", "crude_supply_disruption") in ids
    assert ("crude_supply_disruption", "crude_price") in ids
    assert ("crude_price", "railways_transport") in ids
    assert result.ranking[0]["bucket"] == "adversely_affected"
    assert result.analysis_provider == "gemini"
    assert result.analysis_quality == "authoritative"


# 7: recursion depth is hard-capped
def test_recursion_stops_at_max_causal_depth(db_session, monkeypatch):
    monkeypatch.setattr(settings, "max_causal_depth", 3)
    endless = {
        "extract_facts": FACTS,
        "initial_shocks": {"shocks": [{"shock_id": "n1", "label": "n1", "direction": "bearish",
                                       "mechanism": "m", "confidence": 0.9, "materiality": 0.9,
                                       "impact_strength": 0.9}], "direct_nodes": []},
    }
    router = FakeRouter(endless)
    counter = {"n": 1}

    def ripple(stage, **kwargs):
        if stage != "ripple_discovery":
            return FakeRouter(endless).call(stage, **kwargs)
        router.calls.append(stage)
        counter["n"] += 1
        return {"children": [_edge(f"n{counter['n'] - 1}", f"n{counter['n']}",
                                   child_type="economic_node", mat=0.9, conf=0.95)]}

    original = router.call

    def call(stage, **kwargs):
        if stage == "ripple_discovery":
            return ripple(stage, **kwargs)
        return original(stage, **kwargs)

    router.call = call
    result = analyze_article_v3(router, "t", "c", session=db_session)
    assert max(e.causal_distance for e in result.edges) <= 3


# 8/9: cycles and duplicates rejected
def test_cycle_and_duplicate_prevention(db_session):
    router = FakeRouter({
        "extract_facts": FACTS,
        "initial_shocks": {"shocks": [{"shock_id": "na", "label": "na", "direction": "bearish",
                                       "mechanism": "m", "confidence": 0.9, "materiality": 0.9,
                                       "impact_strength": 0.9}], "direct_nodes": []},
        "ripple_discovery": [
            {"children": [
                _edge("na", "nb", child_type="economic_node", mat=0.8, conf=0.8),
                _edge("na", "nb", child_type="economic_node", mat=0.8, conf=0.8),  # duplicate
                _edge("na", "na", child_type="economic_node", mat=0.8, conf=0.8),  # self-loop
            ]},
            {"children": [_edge("nb", "na", child_type="economic_node", mat=0.9, conf=0.9)]},  # back-edge
            {"children": []},
        ],
    })
    result = analyze_article_v3(router, "t", "c", session=db_session)
    keys = [(e.parent_id, e.child_id) for e in result.edges]
    assert keys.count(("na", "nb")) == 1
    assert ("na", "na") not in keys
    assert ("nb", "na") not in keys  # na exists at distance 1 <= b's distance -> pruned


# 10: distance-aware thresholds prune; dead branch never expands (13)
def test_threshold_pruning_stops_dead_branches(db_session):
    router = FakeRouter({
        "extract_facts": FACTS,
        "initial_shocks": {"shocks": [{"shock_id": "weak", "label": "weak", "direction": "bearish",
                                       "mechanism": "m", "confidence": 0.9, "materiality": 0.9,
                                       "impact_strength": 0.9}], "direct_nodes": []},
        "ripple_discovery": [
            # child fails the distance-2 thresholds (mat .35/conf .60)
            {"children": [_edge("weak", "immaterial", child_type="economic_node",
                                mat=0.10, conf=0.30)]},
        ],
    })
    result = analyze_article_v3(router, "t", "c", session=db_session)
    assert all(e.child_id != "immaterial" for e in result.edges)
    # The pruned child never became a frontier node -> exactly ONE ripple call.
    assert router.calls.count("ripple_discovery") == 1


# 12: no candidates -> no company LLM call
def test_no_candidates_means_no_company_call(db_session):
    router = FakeRouter({
        "extract_facts": FACTS,
        "initial_shocks": {"shocks": [], "direct_nodes": [
            _edge("event", "textiles", child_type="sector", parent_type="event",
                  mat=0.6, conf=0.8),
        ]},
        "ripple_discovery": [{"children": []}],
    })
    result = analyze_article_v3(router, "t", "c", session=db_session)  # empty Company table
    assert "map_companies" not in router.calls
    assert result.companies == []


# grounding: off-candidate ticker dropped
def test_off_candidate_ticker_dropped(db_session):
    _company(db_session, "REAL.NS", "Real Co", "oil_gas")
    router = FakeRouter({
        "extract_facts": FACTS,
        "initial_shocks": {"shocks": [], "direct_nodes": [
            _edge("event", "oil_gas", child_type="sector", parent_type="event", mat=0.7, conf=0.8),
        ]},
        "map_companies": {"companies": [
            _company_entry("REAL.NS", "Real Co"),
            _company_entry("INVENTED.NS", "Invented Co"),
        ]},
        "ripple_discovery": [{"children": []}],
    })
    result = analyze_article_v3(router, "t", "c", session=db_session)
    assert [c.ticker for c in result.companies] == ["REAL.NS"]


# verification: rejection removes; corrections apply
def test_verification_rejects_and_corrects(db_session):
    _company(db_session, "A.NS", "A", "oil_gas")
    _company(db_session, "B.NS", "B", "oil_gas")
    router = FakeRouter({
        "extract_facts": FACTS,
        "initial_shocks": {"shocks": [], "direct_nodes": [
            _edge("event", "oil_gas", child_type="sector", parent_type="event", mat=0.7, conf=0.8),
        ]},
        "map_companies": {"companies": [
            _company_entry("A.NS", "A"), _company_entry("B.NS", "B", direction="bullish"),
        ]},
        "ripple_discovery": [{"children": []}],
        "verify_companies": {
            "accept": ["B.NS"],
            "reject": [{"ticker": "A.NS", "reason": "no real exposure to this shock"}],
            "corrections": [{"ticker": "B.NS", "causal_distance": 2, "direction": "bearish"}],
        },
    })
    result = analyze_article_v3(router, "t", "c", session=db_session)
    assert [c.ticker for c in result.companies] == ["B.NS"]
    assert result.companies[0].causal_distance == 2
    assert result.companies[0].direction == "bearish"
    assert result.companies[0].verified is True


# 11: no forced winner
def test_no_forced_winner(db_session):
    _company(db_session, "L.NS", "Loser", "oil_gas")
    router = FakeRouter({
        "extract_facts": FACTS,
        "initial_shocks": {"shocks": [], "direct_nodes": [
            _edge("event", "oil_gas", child_type="sector", parent_type="event", mat=0.7, conf=0.8),
        ]},
        "map_companies": {"companies": [_company_entry("L.NS", "Loser", direction="bearish")]},
        "ripple_discovery": [{"children": []}],
        "rank_companies": {"ranked": [{"ticker": "L.NS", "bucket": "adversely_affected"}]},
    })
    result = analyze_article_v3(router, "t", "c", session=db_session)
    buckets = {r["bucket"] for r in result.ranking}
    assert "beneficiary" not in buckets  # nothing manufactured


# 18: budget enforcement stops expansion and marks the result
def test_budget_exhaustion_stops_expansion(db_session, monkeypatch):
    monkeypatch.setattr(settings, "gemini_max_output_tokens_per_article", 10)
    router = FakeRouter({
        "extract_facts": FACTS,
        "initial_shocks": {"shocks": [{"shock_id": "s", "label": "s", "direction": "bearish",
                                       "mechanism": "m", "confidence": 0.9, "materiality": 0.9,
                                       "impact_strength": 0.9}], "direct_nodes": []},
        "ripple_discovery": [{"children": [_edge("s", "next", child_type="economic_node",
                                                 mat=0.9, conf=0.9)]}],
    })
    router.budget.record("initial_shocks", output_tokens=50)  # already over
    result = analyze_article_v3(router, "t", "c", session=db_session)
    assert result.analysis_quality == "budget_exhausted"
    assert "ripple_discovery" not in router.calls


# 20: ranking is by impact/materiality/confidence, not generation order
def test_ranking_order_is_deterministic_by_scores(db_session):
    _company(db_session, "SMALL.NS", "Small", "oil_gas")
    _company(db_session, "BIG.NS", "Big", "oil_gas")
    router = FakeRouter({
        "extract_facts": FACTS,
        "initial_shocks": {"shocks": [], "direct_nodes": [
            _edge("event", "oil_gas", child_type="sector", parent_type="event", mat=0.7, conf=0.8),
        ]},
        "map_companies": {"companies": [
            _company_entry("SMALL.NS", "Small", impact=0.3),
            _company_entry("BIG.NS", "Big", impact=0.9),
        ]},
        "ripple_discovery": [{"children": []}],
    })
    result = analyze_article_v3(router, "t", "c", session=db_session)
    assert [r["ticker"] for r in result.ranking] == ["BIG.NS", "SMALL.NS"]


# 14/15/16: the provider ladder (router-level, fake Claude client).
# The old Gemini-ladder rung test (retry -> degraded flash model) is gone
# with the rungs themselves; the Claude policy is asserted end-to-end in
# tests/test_provider_policy.py.
class _FlakyClaude:
    def __init__(self, fail_times, kind="transport"):
        self.fail_times = fail_times
        self.kind = kind
        self.calls = []

    def generate(self, *, model, **kwargs):
        from app.analysis.impact_graph.claude_json import ClaudeJSONError
        self.calls.append(model)
        if len(self.calls) <= self.fail_times:
            raise ClaudeJSONError("boom", status_code=500, kind=self.kind)
        return {"ok": True}


class _GroqOK:
    class chat:
        class completions:
            @staticmethod
            def create(**kwargs):
                from types import SimpleNamespace
                import json as _json
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                    tool_calls=[SimpleNamespace(function=SimpleNamespace(
                        name="emit", arguments=_json.dumps({"ok": True})))]
                ))])


def test_router_groq_fallback_is_loudly_marked(monkeypatch):
    monkeypatch.setattr(settings, "llm_fallback_allowed", True)
    router = StageRouter(claude_api_key="k", claude_client=_FlakyClaude(fail_times=99),
                         groq_client=_GroqOK())
    assert router.quality == "authoritative"  # a Claude router starts authoritative
    result = router.call("initial_shocks", schema={}, static_prefix="s", dynamic_suffix="d")
    assert result == {"ok": True}
    assert router.provider == "groq"
    assert router.quality == "fallback"  # never silently authoritative


def test_groq_by_configuration_route_is_honest_from_construction(monkeypatch):
    class _GroqNoResult:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    from types import SimpleNamespace
                    return SimpleNamespace(choices=[SimpleNamespace(
                        message=SimpleNamespace(tool_calls=[]))])

    monkeypatch.setattr(settings, "llm_fallback_allowed", True)
    router = StageRouter(claude_api_key=None, groq_client=_GroqNoResult())
    # Provider identity is honest from CONSTRUCTION, not just after a
    # failed call: an explicitly-opted-in Groq router is Groq-served and
    # never "authoritative" (corrective-v4 Task 15) -- Groq is never the
    # premium path pretending otherwise.
    assert router.provider == "groq"
    assert router.quality == "fallback"
    with pytest.raises(StageRouterError):
        router.call("initial_shocks", schema={}, static_prefix="s", dynamic_suffix="d")
    assert router.provider == "groq"  # never claims claude
    assert router.quality == "fallback"  # still fallback, never escalated by a failure


# 17: telemetry -- budget accumulates cached/thinking tokens per stage
def test_budget_telemetry_accumulates():
    budget = ArticleBudget(article_id=7)
    budget.record("facts", input_tokens=100, output_tokens=20, cached_tokens=60,
                  thinking_tokens=5, model="gemini-3.1-pro-preview")
    budget.record("ripple", input_tokens=200, output_tokens=50)
    summary = budget.summary()
    assert summary["input_tokens"] == 300
    assert summary["output_tokens"] == 75  # thinking billed as output
    assert summary["cached_tokens"] == 60
    assert summary["per_stage"]["facts"]["calls"] == 1
