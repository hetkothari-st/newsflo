"""Architecture-upgrade tests (spec 2026-08-12 §29): discover broadly first
-> audit for missing branches -> then prune. Every LLM call is faked at the
router layer -- no network anywhere."""
import pytest

from app.analysis.impact_graph.budget import ArticleBudget
from app.analysis.impact_graph.engine import (
    EVENT_NODE_ID, _final_materiality_prune, _GraphState, _Node, analyze_article_v3,
)
from app.analysis.impact_graph.exposure import sectors_for_node
from app.analysis.impact_graph.router import StageRouterError
from app.analysis.impact_graph.schemas import (
    SCHEMA_COMPLETENESS, SCHEMA_SHOCKS, GraphCompany, GraphEdge,
)
from app.config import IMPACT_TRIAGE_TIERS
from app.models import Company


class FakeRouter:
    def __init__(self, responses: dict, provider="gemini", quality="authoritative"):
        self._responses = responses
        self.calls: list[str] = []
        self.prompts: dict[str, list] = {}
        self.provider = provider
        self.quality = quality
        self.budget = ArticleBudget()

    def call(self, stage, **kwargs):
        self.calls.append(stage)
        self.prompts.setdefault(stage, []).append(kwargs)
        response = self._responses.get(stage)
        if isinstance(response, list):
            response = response.pop(0) if response else None
        if response is None:
            if stage == "ripple_discovery":
                return {"children": []}
            if stage == "map_companies":
                return {"companies": []}
            if stage == "completeness_audit":
                return {"missing_branches": [], "channel_audit": []}
            if stage == "verify_companies":
                schema = kwargs.get("schema") or {}
                accept = schema.get("properties", {}).get("accept", {})
                return {"accept": accept.get("items", {}).get("enum", []), "reject": []}
            if stage == "verify_edges":
                return {"verdicts": []}
            raise StageRouterError(f"no canned response for {stage}")
        if isinstance(response, Exception):
            raise response
        return response


def _company(db, ticker, name, sector):
    row = Company(ticker=ticker, name=name, sector=sector, index_tier="NIFTY50",
                  market="INDIA", tradeability="NORMAL", market_cap=1e12)
    db.add(row)
    db.commit()
    return row


def _edge(parent_id, child_id, child_type="economic_node", parent_type="economic_node",
          mat=0.6, conf=0.8, direction="bearish", mech="test mechanism", sector=None,
          impact=0.6, effect=None):
    edge = {
        "parent_type": parent_type, "parent_id": parent_id,
        "child_type": child_type, "child_id": child_id,
        "direction": direction, "mechanism": mech,
        "impact_strength": impact, "confidence": conf, "materiality": mat,
        "time_horizon": "Short-Term",
    }
    if sector:
        edge["child_sector"] = sector
    if effect:
        edge["economic_effect"] = effect
    return edge


def _company_entry(ticker, name, direction="bearish", impact=0.7, conf=0.8, mat=0.6, **extra):
    return {
        "ticker": ticker, "name": name, "direction": direction,
        "impact_strength": impact, "confidence": conf, "materiality": mat,
        "time_horizon": "Short-Term", "mechanism": "exposure mechanism",
        "rationale": "rationale", **extra,
    }


UNEMPLOYMENT_FACTS = {
    "event": "Unemployment rises", "event_status": "confirmed",
    "facts": "Rural unemployment 4.3% -> 4.8%; urban 6.6% -> 6.7%.",
    "fact_items": [{"fact_id": "F1", "text": "Rural unemployment rose from 4.3% to 4.8%"},
                   {"fact_id": "F2", "text": "Urban unemployment rose from 6.6% to 6.7%"}],
    "category": "other", "event_type": "macro_data",
}


# --- A: multi-channel discovery scaffolding --------------------------------

def test_unemployment_discovery_carries_multiple_channels(db_session):
    """The shocks schema FORCES a channel audit and the prompt carries the
    ontology; the engine must accept and register multiple independent
    channels (not just the first FMCG idea) at discovery time."""
    channels = ["household_income_pressure", "consumer_demand", "credit_quality",
                "housing_demand", "discretionary_spending", "wage_dynamics",
                "government_response"]
    router = FakeRouter({
        "extract_facts": UNEMPLOYMENT_FACTS,
        "initial_shocks": {
            "shocks": [
                {"shock_id": c, "label": c.replace("_", " "), "direction": "bearish",
                 "mechanism": f"unemployment moves {c}", "confidence": 0.7,
                 "materiality": 0.5, "impact_strength": 0.5}
                for c in channels
            ],
            "direct_nodes": [],
            "channel_audit": [{"channel": "demand", "verdict": "material"}],
        },
    })
    result = analyze_article_v3(router, "Unemployment rises", "body",
                                session=db_session, article_id=1)
    edge_children = {e.child_id for e in result.edges}
    # All seven channels survive discovery (macro_data => broad tier).
    for channel in channels:
        assert any(channel.rstrip("s") in child or child in channel for child in edge_children), channel
    # Schema + prompt scaffolding is actually in force.
    assert "channel_audit" in SCHEMA_SHOCKS["required"]
    shocks_prompt = router.prompts["initial_shocks"][0]["static_prefix"]
    assert "ECONOMIC CHANNEL ONTOLOGY" in shocks_prompt
    assert "Do NOT prune merely because" in shocks_prompt


# --- B: crude shock channels ----------------------------------------------

def test_crude_shock_exposure_pools_cover_major_channels(db_session):
    """Exposure ontology must route crude-price economic nodes to the fuel,
    transport, chemicals and auto universes without requiring a sector node."""
    hinted = sectors_for_node("crude_oil_price_rise")
    for sector in ("oil_gas", "chemicals", "railways_transport", "auto"):
        assert sector in hinted
    assert sectors_for_node("aviation_fuel_cost_increase")  # transport reachable
    assert "banking" in sectors_for_node("interest_rate_expectations_shift")
    assert "fmcg" in sectors_for_node("inflation_expectations_rise")


def test_economic_node_without_sector_maps_companies(db_session):
    """The old dead-end (node.sector is None -> return) is gone: an economic
    node with exposure hints retrieves a real candidate pool."""
    _company(db_session, "ONGC.NS", "ONGC", "oil_gas")
    router = FakeRouter({
        "extract_facts": {**UNEMPLOYMENT_FACTS, "event_type": "crude_oil"},
        "initial_shocks": {
            "shocks": [{"shock_id": "crude_price_rise", "label": "Crude price rise",
                        "direction": "bullish", "mechanism": "supply cut", "confidence": 0.9,
                        "materiality": 0.8, "impact_strength": 0.8}],
            "direct_nodes": [], "channel_audit": [],
        },
        "map_companies": {"companies": [_company_entry("ONGC.NS", "ONGC",
                                                       direction="bullish")]},
    })
    result = analyze_article_v3(router, "Crude rises", "body",
                                session=db_session, article_id=2)
    assert [c.ticker for c in result.companies] == ["ONGC.NS"]
    # Normalizer canonicalizes crude_price_rise -> crude_price_up.
    assert result.companies[0].parent_id == "crude_price_up"
    assert result.companies[0].parent_type == "economic_node"


# --- C: infrastructure-policy shock ----------------------------------------

def test_infra_policy_exposure_hints(db_session):
    hinted = sectors_for_node("government_infrastructure_capex_increase")
    for sector in ("infra", "metals", "construction_realestate", "banking"):
        assert sector in hinted


# --- D: mixed company effects survive --------------------------------------

def test_mixed_net_direction_survives_at_distance_two(db_session):
    """Regression for the architecture bug: mixed/uncertain used to have
    confidence clamped to 0.55 BEFORE the d2 gate (conf >= 0.60), so every
    mixed company at distance >= 2 silently died. Mixed must now survive on
    materiality alone, with display confidence capped after gating."""
    state = _GraphState()
    state.nodes["fmcg"] = _Node(node_id="fmcg", node_type="sector", label="FMCG",
                                distance=2, materiality=0.7, confidence=0.8, sector="fmcg")
    state.edges.append(GraphEdge(
        parent_type="event", parent_id=EVENT_NODE_ID, child_type="sector", child_id="fmcg",
        direction="bearish", mechanism="m", causal_distance=2,
        impact_strength=0.6, confidence=0.8, materiality=0.7,
    ))
    state.edge_keys = {e.key for e in state.edges}
    state.companies["HINDUNILVR.NS"] = GraphCompany(
        ticker="HINDUNILVR.NS", name="HUL", direction="neutral", net_direction="mixed",
        impact_strength=0.6, confidence=0.9, materiality=0.6, causal_distance=2,
        parent_type="sector", parent_id="fmcg",
        positive_channels=["input cost relief"], negative_channels=["volume pressure"],
    ).clamp()
    _final_materiality_prune(state)
    assert "HINDUNILVR.NS" in state.companies
    survivor = state.companies["HINDUNILVR.NS"]
    assert survivor.net_direction == "mixed"
    assert survivor.economic_effect == "mixed"
    assert survivor.confidence <= 0.55  # display discipline applied AFTER gating


def test_uncertain_survives_and_low_materiality_mixed_still_prunes(db_session):
    state = _GraphState()
    state.companies["A.NS"] = GraphCompany(
        ticker="A.NS", name="A", direction="neutral", net_direction="uncertain",
        impact_strength=0.5, confidence=0.9, materiality=0.5, causal_distance=3,
        parent_type="event", parent_id=EVENT_NODE_ID,
    ).clamp()
    state.companies["B.NS"] = GraphCompany(
        ticker="B.NS", name="B", direction="neutral", net_direction="mixed",
        impact_strength=0.5, confidence=0.9, materiality=0.2, causal_distance=3,
        parent_type="event", parent_id=EVENT_NODE_ID,
    ).clamp()
    _final_materiality_prune(state)
    assert "A.NS" in state.companies       # mat 0.5 >= d3 0.45, conf gate waived
    assert "B.NS" not in state.companies   # materiality gate still real


# --- E: no invented company-to-company relationships ------------------------

def test_company_edge_requires_existing_parent(db_session):
    """A company-parent edge whose parent company is not in the graph is
    structurally rejected -- relationships cannot be conjured."""
    from app.analysis.impact_graph.engine import _register_edge

    state = _GraphState()
    ghost = GraphEdge(parent_type="company", parent_id="GHOST.NS", child_type="company",
                      child_id="REAL.NS", direction="bearish", mechanism="supplier",
                      impact_strength=0.6, confidence=0.9, materiality=0.7)
    assert _register_edge(state, ghost) is False
    assert state.edges == []


# --- F: completeness audit finds missing branch, re-enters frontier ---------

def test_completeness_audit_missing_branch_reenters_frontier(db_session):
    """An intentionally incomplete graph (crude event, no monetary-policy
    branch): the completeness auditor proposes it; the engine registers it,
    expands it one hop, and maps companies for the new nodes."""
    _company(db_session, "HDFCBANK.NS", "HDFC Bank", "banking")
    router = FakeRouter({
        "extract_facts": {**UNEMPLOYMENT_FACTS, "event_type": "crude_oil"},
        "initial_shocks": {
            "shocks": [{"shock_id": "crude_price_rise", "label": "Crude price rise",
                        "direction": "bearish", "mechanism": "supply", "confidence": 0.9,
                        "materiality": 0.8, "impact_strength": 0.8}],
            "direct_nodes": [], "channel_audit": [],
        },
        "completeness_audit": [
            {"missing_branches": [
                {**_edge("crude_price_rise", "inflation_expectations", mat=0.6, conf=0.8),
                 "reason_missing": "monetary channel omitted"},
            ], "channel_audit": []},
            {"missing_branches": [], "channel_audit": []},
        ],
        "ripple_discovery": [
            {"children": []},  # crude_price_rise expansion finds nothing
            {"children": [_edge("inflation_expectations", "banking", child_type="sector",
                                mat=0.6, conf=0.8, mech="rate expectations shift NIMs")]},
            {"children": []},
        ],
        "map_companies": {"companies": []},
    })
    result = analyze_article_v3(router, "Crude rises", "body",
                                session=db_session, article_id=3)
    ids = {(e.parent_id, e.child_id) for e in result.edges}
    # Normalizer: crude_price_rise -> crude_price_up, plural singularized.
    assert ("crude_price_up", "inflation_expectation") in ids
    # The missing branch was EXPANDED (one hop) -- banking arrived through it.
    assert any(parent.startswith("inflation_expectation") and child == "banking"
               for parent, child in ids)
    assert result.metrics["completeness_branches_found"] >= 1
    assert result.metrics["completeness_rounds_run"] >= 1
    # Completeness prompt discipline.
    audit_prefix = router.prompts["completeness_audit"][0]["static_prefix"]
    assert "MAY BE INCOMPLETE" in audit_prefix
    assert "Actively search" in audit_prefix


# --- duplicate nodes / cycles ----------------------------------------------

def test_duplicate_and_cycle_edges_counted_and_blocked(db_session):
    from app.analysis.impact_graph.engine import _register_edge

    state = _GraphState()
    first = GraphEdge(parent_type="event", parent_id=EVENT_NODE_ID,
                      child_type="economic_node", child_id="crude_price_rise",
                      direction="bearish", mechanism="m",
                      impact_strength=0.7, confidence=0.9, materiality=0.7)
    assert _register_edge(state, first) is True
    state.nodes["crude_price_rise"] = _Node("crude_price_rise", "economic_node",
                                            "Crude", 1, 0.7, 0.9)
    # Synonym normalizes onto the same id -> duplicate blocked.
    synonym = GraphEdge(parent_type="event", parent_id=EVENT_NODE_ID,
                        child_type="economic_node", child_id="higher crude prices",
                        direction="bearish", mechanism="m",
                        impact_strength=0.7, confidence=0.9, materiality=0.7)
    assert _register_edge(state, synonym) is False
    # A back-edge to an ancestor is a cycle -> blocked.
    cycle = GraphEdge(parent_type="economic_node", parent_id="crude_price_rise",
                      child_type="economic_node", child_id="crude_price_rise",
                      direction="bearish", mechanism="m",
                      impact_strength=0.7, confidence=0.9, materiality=0.7)
    assert _register_edge(state, cycle) is False
    assert state.metrics["duplicate_nodes_removed"] >= 1
    assert len(state.edges) == 1


# --- discovery floor vs final gate -----------------------------------------

def test_uncertain_materiality_survives_discovery_then_final_prune_decides(db_session):
    """The architecture's core: an edge with uncertain (low) materiality but
    plausible mechanism REGISTERS at discovery, and only the final prune
    (post-completeness) applies the strict distance thresholds."""
    from app.analysis.impact_graph.engine import _register_edge

    state = _GraphState()
    weak = GraphEdge(parent_type="event", parent_id=EVENT_NODE_ID,
                     child_type="economic_node", child_id="weak_channel",
                     direction="bearish", mechanism="plausible but uncertain",
                     impact_strength=0.4, confidence=0.6, materiality=0.2)
    # Old architecture: d1 gate (mat 0.30) kills it at discovery. New: floor
    # (0.15) admits it.
    assert _register_edge(state, weak) is True
    state.nodes["weak_channel"] = _Node("weak_channel", "economic_node", "Weak",
                                        1, 0.2, 0.6)
    _final_materiality_prune(state)
    # Final prune then applies the strict d1 thresholds and removes it.
    assert all(e.child_id != "weak_channel" for e in state.edges)
    assert state.metrics["edges_pruned_final"] == 1


# --- schema / backward compatibility ----------------------------------------

def test_economic_effect_derivation_and_direction_compat():
    bullish = GraphEdge(parent_type="event", parent_id=EVENT_NODE_ID,
                        child_type="sector", child_id="oil_gas",
                        direction="bullish", mechanism="m").clamp()
    assert bullish.economic_effect == "positive"
    mixed = GraphEdge(parent_type="event", parent_id=EVENT_NODE_ID,
                      child_type="sector", child_id="fmcg",
                      economic_effect="mixed", mechanism="m").clamp()
    assert mixed.direction == "neutral"          # legacy view derived
    assert mixed.economic_effect == "mixed"      # truth preserved
    company = GraphCompany(ticker="X.NS", name="X", direction="bearish").clamp()
    assert company.economic_effect == "negative"
    uncertain = GraphCompany(ticker="Y.NS", name="Y", direction="neutral",
                             net_direction="uncertain").clamp()
    assert uncertain.economic_effect == "uncertain"


def test_v3_entries_carry_economic_effect(db_session):
    from app.analysis.impact_graph.schemas import ImpactGraphResult
    from app.pipeline import _v3_edges, _v3_entries

    _company(db_session, "HUL.NS", "HUL", "fmcg")
    result = ImpactGraphResult(
        category="fmcg",
        companies=[GraphCompany(ticker="HUL.NS", name="HUL", direction="neutral",
                                net_direction="mixed", impact_strength=0.5,
                                confidence=0.5, materiality=0.5, causal_distance=2,
                                parent_type="sector", parent_id="fmcg").clamp()],
        edges=[GraphEdge(parent_type="event", parent_id=EVENT_NODE_ID,
                         child_type="sector", child_id="fmcg", economic_effect="negative",
                         mechanism="m", causal_distance=1).clamp()],
    )
    entries = _v3_entries(db_session, result)
    assert entries[0]["economic_effect"] == "mixed"
    # Legacy direction column still gets a non-null legacy value.
    assert entries[0]["direction"] in ("bullish", "bearish")
    edges = _v3_edges(result)
    assert edges[0]["economic_effect"] == "negative"
    assert edges[0]["direction"] in ("bullish", "bearish")  # legacy chart contract


def test_completeness_rounds_configured_per_tier():
    assert IMPACT_TRIAGE_TIERS["broad"]["completeness_rounds"] >= 1
    assert IMPACT_TRIAGE_TIERS["narrow"]["completeness_rounds"] == 0
    assert "missing_branches" in SCHEMA_COMPLETENESS["properties"]
    assert "reason_missing" in (
        SCHEMA_COMPLETENESS["properties"]["missing_branches"]["items"]["required"]
    )
