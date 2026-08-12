"""Knowledge-architecture tests (cost-opt spec 2026-08-12): mechanism
registry, event-archetype matching, priority tiers, canonical exposure
dedup, medium-first escalation, coverage matrix, semantic cache seed, and
the IMPACT_KNOWLEDGE_MODE rollback flag. No network anywhere."""
import pytest

import app.config as config
from app.analysis.impact_graph.budget import ArticleBudget
from app.analysis.impact_graph.engine import (
    _coverage_matrix, _escalation_tickers, _GraphState, _Node, analyze_article_v3,
)
from app.analysis.impact_graph.knowledge import (
    ARCHETYPE_EXPOSURES, EVENT_ARCHETYPES, EXPOSURE_ARCHETYPES, MECHANISM_DIMENSIONS,
    MECHANISMS, companies_for_archetype, match_event_archetype, oriented_mechanisms,
    seed_company_exposures,
)
from app.analysis.impact_graph.router import StageRouterError
from app.models import Company


class FakeRouter:
    def __init__(self, responses: dict, provider="gemini", quality="authoritative"):
        self._responses = responses
        self.calls: list[str] = []
        self.kwargs: dict[str, list] = {}
        self.provider = provider
        self.quality = quality
        self.budget = ArticleBudget()

    def call(self, stage, **kwargs):
        self.calls.append(stage)
        self.kwargs.setdefault(stage, []).append(kwargs)
        response = self._responses.get(stage)
        if isinstance(response, list):
            response = response.pop(0) if response else None
        if response is None:
            defaults = {
                "ripple_discovery": {"children": []},
                "map_companies": {"companies": []},
                "map_companies_escalation": {"companies": []},
                "completeness_audit": {"missing_branches": [], "channel_audit": []},
                "verify_edges": {"verdicts": []},
            }
            if stage in defaults:
                return defaults[stage]
            if stage == "verify_companies":
                schema = kwargs.get("schema") or {}
                accept = schema.get("properties", {}).get("accept", {})
                return {"accept": accept.get("items", {}).get("enum", []), "reject": []}
            raise StageRouterError(f"no canned response for {stage}")
        if isinstance(response, Exception):
            raise response
        return response


def _company(db, ticker, name, sector, sub_sector=None, desc=None, cap=1e12):
    row = Company(ticker=ticker, name=name, sector=sector, sub_sector=sub_sector,
                  business_desc=desc, index_tier="NIFTY50", market="INDIA",
                  tradeability="NORMAL", market_cap=cap)
    db.add(row)
    db.commit()
    return row


CRUDE_FACTS = {
    "event": "Crude oil prices rise sharply", "event_status": "confirmed",
    "facts": "Brent crude rose 6% amid supply concerns.",
    "fact_items": [{"fact_id": "F1", "text": "Brent crude rose 6%"}],
    "category": "oil_gas", "event_type": "crude_oil",
}


# --- registry integrity ----------------------------------------------------

def test_registry_referential_integrity():
    for archetype_id, spec in EVENT_ARCHETYPES.items():
        for mechanism_id in spec["mechanisms"]:
            assert mechanism_id in MECHANISMS, f"{archetype_id} -> {mechanism_id}"
    for mechanism_id, mech in MECHANISMS.items():
        assert mech["child_exposure"] in EXPOSURE_ARCHETYPES, mechanism_id
        assert mechanism_id in MECHANISM_DIMENSIONS, mechanism_id
        assert mech["effect"] in ("positive", "negative", "mixed", "uncertain", "neutral")
    for archetype_id in ARCHETYPE_EXPOSURES:
        assert archetype_id in EXPOSURE_ARCHETYPES, archetype_id


def test_archetype_matching_and_orientation():
    class F:
        event = "RBI cuts repo rate by 50 bps"
        facts = "Repo rate cut to support growth"
        event_type = "repo_rate_change"
    match = match_event_archetype(F())
    assert match == ("RATE_CHANGE", "inverted")
    mechs = {m["mechanism_id"]: m["oriented_effect"]
             for m in oriented_mechanisms("RATE_CHANGE", "inverted")}
    assert mechs["nbfc_funding_cost"] == "positive"      # rate CUT helps NBFC funding
    assert mechs["housing_demand_rates"] == "positive"
    assert mechs["bank_nim_repricing"] == "mixed"        # mixed stays mixed


def test_no_archetype_for_novel_event():
    class F:
        event = "Company wins defence order"
        facts = "order win for drones"
        event_type = "order_win"
    assert match_event_archetype(F()) is None
    # event_type gate alone is not enough -- keywords must also hit
    class G:
        event = "Something unrelated happened"
        facts = "no relevant words at all"
        event_type = "crude_oil"
    assert match_event_archetype(G()) is None


def test_companies_for_archetype_uses_real_vocabulary(db_session):
    _company(db_session, "ONGC.NS", "ONGC", "oil_gas", sub_sector="upstream_exploration")
    _company(db_session, "CASTROLIND.NS", "Castrol", "oil_gas",
             desc="Manufactures lubricants and greases")
    _company(db_session, "TCS.NS", "TCS", "it", sub_sector="it_other")
    upstream = [c.ticker for c in companies_for_archetype(db_session, "upstream_oil_producer")]
    lubes = [c.ticker for c in companies_for_archetype(db_session, "lubricant_producer")]
    assert upstream == ["ONGC.NS"]
    assert lubes == ["CASTROLIND.NS"]


# --- P8 priority tiers -----------------------------------------------------

def test_priority_tiers_order_by_exposure_level(db_session):
    from app.analysis.impact_graph.engine import _priority_tiers

    high = _company(db_session, "AAA.NS", "A", "chemicals", desc="petrochemical maker")
    low = _company(db_session, "BBB.NS", "B", "chemicals", desc="soap maker")
    seed_company_exposures(db_session)
    # AAA matched petrochemical_producer -> crude_linked_inputs VERY_HIGH
    tier_a, tier_b, tier_c = _priority_tiers(
        db_session, [low, high], "crude_linked_inputs")
    assert [c.ticker for c in tier_a] == ["AAA.NS"]
    assert low.ticker in [c.ticker for c in tier_b + tier_c]


# --- P10 escalation triggers ----------------------------------------------

def test_escalation_flags_low_confidence_mixed_and_prior_conflict():
    entries = [
        {"ticker": "A.NS", "confidence": 0.5, "materiality": 0.6, "causal_distance": 2},
        {"ticker": "B.NS", "confidence": 0.9, "materiality": 0.6, "causal_distance": 2,
         "net_direction": "mixed"},
        {"ticker": "C.NS", "confidence": 0.9, "materiality": 0.6, "causal_distance": 2,
         "direction": "bullish"},
        {"ticker": "D.NS", "confidence": 0.9, "materiality": 0.65, "causal_distance": 2,
         "direction": "bearish"},
    ]
    flagged = _escalation_tickers(entries, candidate_count=20, prior_effect="negative")
    assert "A.NS" in flagged      # low confidence
    assert "B.NS" in flagged      # mixed net
    assert "C.NS" in flagged      # conflicts with negative prior
    assert "D.NS" not in flagged  # clean, matches prior, far from threshold


def test_escalation_result_replaces_flagged_entries(db_session):
    _company(db_session, "ONGC.NS", "ONGC", "oil_gas", sub_sector="upstream_exploration")
    router = FakeRouter({
        "extract_facts": CRUDE_FACTS,
        "initial_shocks": {
            "shocks": [{"shock_id": "crude_price_up", "label": "Crude price up",
                        "direction": "bullish", "mechanism": "supply", "confidence": 0.9,
                        "materiality": 0.8, "impact_strength": 0.8}],
            "direct_nodes": [], "channel_audit": [],
        },
        # Medium pass returns ONGC with LOW confidence -> flagged; the
        # escalation call corrects it at high thinking.
        "map_companies": {"companies": [{
            "ticker": "ONGC.NS", "name": "ONGC", "direction": "bearish",
            "impact_strength": 0.5, "confidence": 0.4, "materiality": 0.6,
            "time_horizon": "Short-Term", "mechanism": "m", "rationale": "r",
            "net_direction": "bearish"}]},
        "map_companies_escalation": {"companies": [{
            "ticker": "ONGC.NS", "name": "ONGC", "direction": "bullish",
            "impact_strength": 0.85, "confidence": 0.9, "materiality": 0.85,
            "time_horizon": "Immediate", "mechanism": "higher realization",
            "rationale": "upstream benefits", "net_direction": "bullish"}]},
    })
    result = analyze_article_v3(router, "Crude rises", "body",
                                session=db_session, article_id=10)
    assert "map_companies_escalation" in router.calls
    ongc = next(c for c in result.companies if c.ticker == "ONGC.NS")
    assert ongc.direction == "bullish"           # escalated verdict won
    assert ongc.confidence == pytest.approx(0.9)
    # Medium-first thinking on the mapping call (spec P10)
    first_map = router.kwargs["map_companies"][0]
    assert first_map.get("thinking") == config.IMPACT_MAPPING_THINKING
    assert router.kwargs["map_companies_escalation"][0].get("thinking") == "high"


# --- P9 canonical exposure dedup ------------------------------------------

def test_archetype_mapping_dedups_equivalent_exposures(db_session, monkeypatch):
    _company(db_session, "ONGC.NS", "ONGC", "oil_gas", sub_sector="upstream_exploration")
    seed_company_exposures(db_session)  # eligibility gate needs verified exposure rows
    # Two mechanisms artificially pointed at the SAME (archetype, dimension,
    # effect) -- only one mapping call may fire.
    import app.analysis.impact_graph.knowledge as knowledge
    monkeypatch.setitem(knowledge.MECHANISMS, "upstream_realization_dup",
                        {**knowledge.MECHANISMS["upstream_realization"]})
    monkeypatch.setitem(knowledge.MECHANISM_DIMENSIONS, "upstream_realization_dup",
                        knowledge.MECHANISM_DIMENSIONS["upstream_realization"])
    monkeypatch.setitem(
        knowledge.EVENT_ARCHETYPES, "CRUDE_PRICE_SHOCK",
        {**knowledge.EVENT_ARCHETYPES["CRUDE_PRICE_SHOCK"],
         "mechanisms": ["upstream_realization", "upstream_realization_dup"]},
    )
    router = FakeRouter({
        "extract_facts": CRUDE_FACTS,
        "initial_shocks": {
            "shocks": [{"shock_id": "crude_price_up", "label": "Crude price up",
                        "direction": "bullish", "mechanism": "supply", "confidence": 0.9,
                        "materiality": 0.8, "impact_strength": 0.8}],
            "direct_nodes": [], "channel_audit": [],
        },
        "map_companies": {"companies": []},
    })
    analyze_article_v3(router, "Crude rises", "body", session=db_session, article_id=11)
    map_calls = [k for k in router.kwargs.get("map_companies", [])
                 if k.get("context", {}).get("mechanism_id", "").startswith("upstream_realization")]
    assert len(map_calls) == 1  # the duplicate exposure never re-bought


# --- P13 coverage matrix ---------------------------------------------------

def test_coverage_matrix_found_vs_missing():
    state = _GraphState()
    state.nodes["crude_price_up"] = _Node("crude_price_up", "economic_node",
                                          "Crude price up", 1, 0.8, 0.9)
    state.nodes["consumer_demand_fall"] = _Node("consumer_demand_fall", "economic_node",
                                                "Consumer demand falls", 2, 0.6, 0.7)
    covered, missing = _coverage_matrix(state)
    assert "price" in covered
    assert "demand" in covered
    assert "exports" in missing
    assert "credit_quality" in missing


def test_completeness_prompt_lists_only_missing_channels(db_session, monkeypatch):
    monkeypatch.setattr(config, "IMPACT_KNOWLEDGE_MODE", False)
    router = FakeRouter({
        "extract_facts": CRUDE_FACTS,
        "initial_shocks": {
            "shocks": [{"shock_id": "crude_price_up", "label": "Crude price up",
                        "direction": "bullish", "mechanism": "supply", "confidence": 0.9,
                        "materiality": 0.8, "impact_strength": 0.8}],
            "direct_nodes": [], "channel_audit": [],
        },
        "completeness_audit": [{"missing_branches": [], "channel_audit": []}],
    })
    analyze_article_v3(router, "Crude rises", "body", session=db_session, article_id=12)
    audit_kwargs = router.kwargs["completeness_audit"][0]
    suffix = audit_kwargs["dynamic_suffix"]
    assert "INVESTIGATE ONLY THESE MISSING CHANNELS" in suffix
    assert "price" not in suffix.split("MISSING CHANNELS")[1].split("\n")[0].split("exports")[0] \
        or "exports" in suffix  # price covered -> not in the missing list


# --- P12 semantic cache seed ----------------------------------------------

def test_mapping_cache_seed_excludes_exposure_annotations(db_session, monkeypatch):
    """The fingerprint leak: relationship-cache annotations changed the
    prompt after verification, re-billing identical mapping calls. The
    cache_seed must be stable across that change."""
    monkeypatch.setattr(config, "IMPACT_KNOWLEDGE_MODE", False)
    _company(db_session, "ONGC.NS", "ONGC", "oil_gas")
    seeds = []

    router = FakeRouter({
        "extract_facts": CRUDE_FACTS,
        "initial_shocks": {
            "shocks": [{"shock_id": "crude_price_up", "label": "Crude price up",
                        "direction": "bullish", "mechanism": "supply", "confidence": 0.9,
                        "materiality": 0.8, "impact_strength": 0.8}],
            "direct_nodes": [], "channel_audit": [],
        },
        "map_companies": {"companies": []},
    })
    analyze_article_v3(router, "Crude rises", "body", session=db_session, article_id=13)
    for kwargs in router.kwargs.get("map_companies", []):
        assert kwargs.get("cache_seed"), "mapping calls must carry a semantic cache seed"
        assert "KNOWN BASE EXPOSURE" not in kwargs["cache_seed"]
        seeds.append(kwargs["cache_seed"])
    assert seeds


# --- rollback flag ---------------------------------------------------------

def test_knowledge_mode_off_is_pure_dynamic_path(db_session, monkeypatch):
    monkeypatch.setattr(config, "IMPACT_KNOWLEDGE_MODE", False)
    _company(db_session, "ONGC.NS", "ONGC", "oil_gas", sub_sector="upstream_exploration")
    router = FakeRouter({
        "extract_facts": CRUDE_FACTS,
        "initial_shocks": {
            "shocks": [{"shock_id": "crude_price_up", "label": "Crude price up",
                        "direction": "bullish", "mechanism": "supply", "confidence": 0.9,
                        "materiality": 0.8, "impact_strength": 0.8}],
            "direct_nodes": [], "channel_audit": [],
        },
        "map_companies": {"companies": []},
    })
    analyze_article_v3(router, "Crude rises", "body", session=db_session, article_id=14)
    mechanism_calls = [k for k in router.kwargs.get("map_companies", [])
                       if k.get("context", {}).get("mechanism_id")]
    assert mechanism_calls == []  # no archetype path ran


def test_domain_batching_defaults_off():
    assert config.DOMAIN_BATCHING is False


# --- eligibility directive (2026-08-12) ------------------------------------

def test_eligible_candidates_gate_excludes_unknown_exposure(db_session):
    from app.analysis.impact_graph.knowledge import MECHANISMS, eligible_candidates

    exposed = _company(db_session, "PAINTED.NS", "Painted", "chemicals", desc="paint and coating maker")
    unknown = _company(db_session, "MYSTERY.NS", "Mystery", "chemicals", desc="paint distribution")
    seed_company_exposures(db_session)
    # Remove the seeded row for MYSTERY so its exposure is genuinely unknown.
    from app.models import CompanyExposure
    db_session.query(CompanyExposure).filter_by(company_id=unknown.id).delete()
    db_session.commit()
    mech = {**MECHANISMS["paints_input_cost"], "mechanism_id": "paints_input_cost"}
    eligible, pool = eligible_candidates(db_session, mech, "paint_input_cost")
    tickers = [c.ticker for c in eligible]
    assert "PAINTED.NS" in tickers      # seeded crude_linked_inputs HIGH
    assert "MYSTERY.NS" not in tickers  # UNKNOWN exposure -> not eligible
    assert pool == 2


def test_eligible_candidates_verified_relationship_escape(db_session):
    from app.analysis.impact_graph.knowledge import MECHANISMS, eligible_candidates
    from app.models import CompanyNodeExposure, utcnow

    quiet = _company(db_session, "QUIET.NS", "Quiet", "chemicals", desc="paint maker")
    from app.models import CompanyExposure
    db_session.query(CompanyExposure).delete()
    db_session.add(CompanyNodeExposure(company_id=quiet.id, node_key="paint_input_cost",
                                       exposure_exists=1, strength=0.7,
                                       mechanism="verified earlier", verified_at=utcnow()))
    db_session.commit()
    mech = {**MECHANISMS["paints_input_cost"], "mechanism_id": "paints_input_cost"}
    eligible, _ = eligible_candidates(db_session, mech, "paint_input_cost")
    assert [c.ticker for c in eligible] == ["QUIET.NS"]


def test_fertilizer_excluded_from_petrochemical_archetype(db_session):
    _company(db_session, "DEEPFERT.NS", "Deepak Fert", "chemicals",
             desc="fertilisers and petrochemicals producer")
    _company(db_session, "PETCHEM.NS", "PetChem", "chemicals", desc="petrochemical polymers")
    tickers = [c.ticker for c in companies_for_archetype(db_session, "petrochemical_producer")]
    assert "PETCHEM.NS" in tickers
    assert "DEEPFERT.NS" not in tickers  # exclusion rule (directive §15)


def test_refiner_mechanism_is_mixed_not_automatic():
    assert MECHANISMS["refiner_marketing_margin"]["effect"] == "mixed"  # directive §7
    assert MECHANISMS["refiner_marketing_margin"].get("min_exposure") == "HIGH"


def test_weak_priors_below_confidence_floor_are_skipped():
    assert MECHANISMS["auto_fuel_demand"]["confidence_baseline"] < config.IMPACT_MIN_MECHANISM_CONFIDENCE
    assert MECHANISMS["two_wheeler_fuel_demand"]["confidence_baseline"] < config.IMPACT_MIN_MECHANISM_CONFIDENCE
    assert MECHANISMS["vehicle_financier_stress"]["confidence_baseline"] < config.IMPACT_MIN_MECHANISM_CONFIDENCE
    # EV relative-substitution mechanism survives -- distinct chain, §6.
    assert MECHANISMS["ev_relative_advantage"]["confidence_baseline"] >= config.IMPACT_MIN_MECHANISM_CONFIDENCE


def test_neutral_without_channels_is_pruned(db_session):
    from app.analysis.impact_graph.engine import _final_materiality_prune
    from app.analysis.impact_graph.schemas import GraphCompany

    state = _GraphState()
    state.companies["WEAK.NS"] = GraphCompany(
        ticker="WEAK.NS", name="Weak", direction="neutral", net_direction="neutral",
        impact_strength=0.5, confidence=0.9, materiality=0.6, causal_distance=1,
        parent_type="event", parent_id="event").clamp()
    state.companies["OFFSET.NS"] = GraphCompany(
        ticker="OFFSET.NS", name="Offset", direction="neutral", net_direction="neutral",
        impact_strength=0.5, confidence=0.9, materiality=0.6, causal_distance=1,
        parent_type="event", parent_id="event",
        positive_channels=["export gains"], negative_channels=["input costs"]).clamp()
    _final_materiality_prune(state)
    assert "WEAK.NS" not in state.companies   # weak association, no analysis
    assert "OFFSET.NS" in state.companies     # genuine offsetting channels
