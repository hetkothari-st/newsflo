"""Impact-graph v3 engine (spec 2026-08-11): facts → initial shocks →
direct companies → recursive ripple expansion → verification → ranking.

Design contract (spec docs 1-4):
- The LLM reasons; code enforces. Every threshold, dedup, cycle check,
  distance assignment and sort happens deterministically here.
- Recursive frontier expansion, one economic hop per call, hard-capped by
  settings.max_causal_depth and pruned by distance-aware thresholds
  (config.impact_thresholds_for_distance).
- Companies are selected ONLY from the candidate DB (ticker enum in the
  structured-output schema + a deterministic post-filter).
- No forced winners: ranking buckets may be empty.
- Per-article budget: once exceeded, expansion stops, verified work is
  kept, and the result is marked budget_exhausted.
"""
import logging
from collections import deque
from dataclasses import dataclass, field

from pydantic import ValidationError

from app.analysis.impact_graph import prompts
from app.analysis.impact_graph.budget import ArticleBudget
from app.analysis.impact_graph.router import StageRouter, StageRouterError
from app.analysis.impact_graph.schemas import (
    CHILD_TYPES, PARENT_TYPES, SCHEMA_EDGE_VERDICTS, SCHEMA_FACTS, SCHEMA_RIPPLE,
    SCHEMA_SHOCKS, EventFacts, GraphCompany, GraphEdge, ImpactGraphResult,
    schema_companies, schema_company_verdicts, schema_ranking,
)
from app.analysis.schemas import CATEGORIES, SECTORS
from app.companies.candidates import candidate_companies, candidate_tickers, format_candidates
from app.config import impact_thresholds_for_distance, settings

logger = logging.getLogger(__name__)

EVENT_NODE_ID = "event"

# Bound how many candidate companies ride one company-mapping prompt --
# same context-minimization rail the old cascade enforced. 40 (was 60):
# the tail of a market-cap-ordered candidate list almost never survives
# verification, and each candidate costs prompt AND ticker-enum tokens.
MAX_CANDIDATES_PER_CALL = 40
# Bound frontier-node expansions per article, independent of depth --
# breadth backstop against a pathological wide graph. 12 (was 24): the
# first live Hormuz run showed a wide event happily fills whatever room
# it is given; 12 expansions still covers every major branch.
MAX_EXPANSIONS_PER_ARTICLE = 12


@dataclass
class _Node:
    node_id: str
    node_type: str  # economic_node | sector | commodity | policy | company
    label: str
    distance: int
    materiality: float
    confidence: float
    sector: str | None = None  # sector slug when node_type == "sector"


@dataclass
class _GraphState:
    nodes: dict = field(default_factory=dict)          # node_id -> _Node
    edges: list = field(default_factory=list)          # list[GraphEdge]
    edge_keys: set = field(default_factory=set)
    expanded: set = field(default_factory=set)         # node_ids already sent to ripple discovery
    companies: dict = field(default_factory=dict)      # ticker -> GraphCompany (best per ticker)
    rejected_tickers: set = field(default_factory=set)
    evaluated_nodes: set = field(default_factory=set)  # node_ids whose companies were mapped
    gaps: list = field(default_factory=list)
    expansions: int = 0


def _facts_suffix(facts: EventFacts, extra: str = "") -> str:
    evidence = "\n".join(facts.article_evidence[:12])
    parts = [f"EVENT: {facts.event} (status: {facts.event_status})", f"FACTS: {facts.facts}"]
    if facts.quantities:
        parts.append("QUANTITIES: " + "; ".join(facts.quantities[:12]))
    if evidence:
        parts.append(f"ARTICLE EVIDENCE:\n{evidence}")
    if extra:
        parts.append(extra)
    return "\n\n".join(parts)


def _passes(distance: int, materiality: float, confidence: float) -> bool:
    thresholds = impact_thresholds_for_distance(distance)
    return materiality >= thresholds["materiality"] and confidence >= thresholds["confidence"]


def _register_edge(state: _GraphState, edge: GraphEdge) -> bool:
    """Deterministic edge gate: schema-valid types, real parent, no dupes,
    no cycles (a child that already exists at <= parent distance is a
    back-edge), thresholds for its distance. Returns True when persisted."""
    if edge.parent_type not in PARENT_TYPES or edge.child_type not in CHILD_TYPES:
        return False
    if edge.parent_id != EVENT_NODE_ID and edge.parent_id not in state.nodes:
        return False
    if edge.child_id == edge.parent_id or edge.child_id == EVENT_NODE_ID:
        return False
    if edge.key in state.edge_keys:
        return False
    existing = state.nodes.get(edge.child_id)
    if existing is not None and existing.distance <= _parent_distance(state, edge):
        # Already reached at least this directly -- re-adding it deeper is
        # either a duplicate or a cycle; both are pruned.
        return False
    edge.clamp()
    edge.causal_distance = _parent_distance(state, edge) + 1
    if not _passes(edge.causal_distance, edge.materiality, edge.confidence):
        return False
    state.edges.append(edge)
    state.edge_keys.add(edge.key)
    return True


def _parent_distance(state: _GraphState, edge: GraphEdge) -> int:
    if edge.parent_id == EVENT_NODE_ID:
        return 0
    return state.nodes[edge.parent_id].distance


def _node_from_edge(edge: GraphEdge, label: str | None, sector: str | None) -> _Node:
    node_sector = sector if sector in SECTORS else None
    if edge.child_type == "sector" and edge.child_id in SECTORS:
        node_sector = edge.child_id
    return _Node(
        node_id=edge.child_id, node_type=edge.child_type,
        label=label or edge.child_id.replace("_", " "), distance=edge.causal_distance,
        materiality=edge.materiality, confidence=edge.confidence, sector=node_sector,
    )


def _graph_outline(state: _GraphState, limit: int = 40) -> str:
    lines = [
        f"- d{e.causal_distance} {e.parent_id} -> {e.child_id} ({e.direction}): {e.mechanism[:110]}"
        for e in state.edges[:limit]
    ]
    return "\n".join(lines) if lines else "(empty)"


# --- company mapping ------------------------------------------------------

def _map_companies_for_node(router: StageRouter, session, facts: EventFacts,
                            state: _GraphState, node: _Node) -> None:
    """Stage 3 (distance 1) / stage 5 (ripples): candidate-grounded company
    mapping for one graph node. Deterministic gates first: no candidates ->
    no LLM call; already-evaluated node -> no call; rejected/duplicate
    candidates filtered before the prompt."""
    if node.node_id in state.evaluated_nodes:
        return
    state.evaluated_nodes.add(node.node_id)
    if session is None or node.sector is None:
        return  # companies attach where a sector pool exists; economic nodes fan into sector children
    candidates = candidate_companies(session, [node.sector])
    candidates = [
        c for c in candidates
        if c.ticker not in state.companies and c.ticker not in state.rejected_tickers
    ][:MAX_CANDIDATES_PER_CALL]
    if not candidates:
        return
    tickers = candidate_tickers(candidates)
    stage_prompt = prompts.DIRECT_COMPANIES_PROMPT if node.distance <= 1 else prompts.RIPPLE_COMPANIES_PROMPT
    parent_edge = next((e for e in state.edges if e.child_id == node.node_id), None)
    parent_desc = (
        f"PARENT NODE: {node.node_id} ({node.node_type}, causal distance {node.distance})\n"
        f"PARENT MECHANISM: {parent_edge.mechanism if parent_edge else facts.event}\n"
        f"PARENT DIRECTION: {parent_edge.direction if parent_edge else 'n/a'}"
    )
    suffix = _facts_suffix(
        facts,
        extra=(
            f"{parent_desc}\n\nCAUSAL PATH SO FAR:\n{_graph_outline(state)}\n\n"
            "CANDIDATE COMPANIES -- choose ONLY from this list; selecting none is a "
            "correct answer when none genuinely qualifies:\n"
            + format_candidates(candidates)
        ),
    )
    compact = _facts_suffix(
        facts,
        extra=f"{parent_desc}\n\nCANDIDATE COMPANIES:\n" + format_candidates(candidates[:25]),
    )
    try:
        raw = router.call(
            "map_companies", schema=schema_companies(tickers),
            static_prefix=prompts.static_prefix(stage_prompt),
            dynamic_suffix=suffix, compact_suffix=compact,
        )
    except StageRouterError as exc:
        state.gaps.append({"sector": node.sector, "impact_level": _legacy_level(node.distance),
                           "parent_ticker": None, "attempts": 4, "last_error": str(exc)[:500]})
        return

    allowed = set(tickers)
    for entry in raw.get("companies", []):
        ticker = entry.get("ticker")
        if ticker not in allowed:
            logger.warning("impact-graph dropped off-candidate ticker %r", ticker)
            continue
        try:
            company = GraphCompany(
                **{**entry, "causal_distance": node.distance,
                   "parent_type": node.node_type, "parent_id": node.node_id},
            ).clamp()
        except ValidationError as exc:
            logger.warning("impact-graph company entry rejected by schema: %s", exc)
            continue
        if not _passes(company.causal_distance, company.materiality, company.confidence):
            state.rejected_tickers.add(ticker)
            continue
        held = state.companies.get(ticker)
        if held is None or company.impact_strength > held.impact_strength:
            state.companies[ticker] = company


def _legacy_level(distance: int) -> str:
    """UI-facing legacy label derived from causal distance. Distances >= 3
    reuse indirect_l2 for now -- the integer causal_distance column carries
    the truth; the frontend gains L3/L4+ labels separately."""
    if distance <= 1:
        return "direct"
    if distance == 2:
        return "indirect_l1"
    return "indirect_l2"


# --- verification ---------------------------------------------------------

def _verify_companies(router: StageRouter, facts: EventFacts, state: _GraphState) -> None:
    companies = list(state.companies.values())
    if not companies:
        return
    tickers = [c.ticker for c in companies]
    listing = "\n".join(
        f"- {c.ticker} ({c.name}) d{c.causal_distance} {c.direction} "
        f"impact={c.impact_strength:.2f} conf={c.confidence:.2f} mat={c.materiality:.2f} "
        f"parent={c.parent_type}:{c.parent_id} :: {c.mechanism[:160]} :: {c.rationale[:200]}"
        for c in companies
    )
    suffix = _facts_suffix(facts, extra=f"GRAPH:\n{_graph_outline(state, 60)}\n\nPROPOSED COMPANIES:\n{listing}")
    try:
        raw = router.call(
            "verify_companies", schema=schema_company_verdicts(tickers),
            static_prefix=prompts.static_prefix(prompts.VERIFY_COMPANIES_PROMPT),
            dynamic_suffix=suffix,
        )
    except StageRouterError as exc:
        logger.warning("impact-graph company verification unavailable, keeping recall set: %s", exc)
        return
    verdicts = {v.get("ticker"): v for v in raw.get("verdicts", [])}
    for ticker, verdict in verdicts.items():
        company = state.companies.get(ticker)
        if company is None:
            continue
        if not verdict.get("belongs", True):
            state.companies.pop(ticker, None)
            state.rejected_tickers.add(ticker)
            continue
        company.verified = True
        corrected = verdict.get("corrected_distance")
        if isinstance(corrected, int) and 1 <= corrected <= settings.max_causal_depth:
            company.causal_distance = corrected
        direction = verdict.get("corrected_direction")
        if direction in ("bullish", "bearish", "neutral"):
            company.direction = direction
    # A company the verifier returned no verdict for is KEPT (omission is
    # not rejection -- same discipline as the old verification stage).


def _verify_edges(router: StageRouter, facts: EventFacts, state: _GraphState) -> None:
    if not state.edges:
        return
    listing = "\n".join(
        f"{i}. {e.parent_type}:{e.parent_id} -> {e.child_type}:{e.child_id} "
        f"(d{e.causal_distance}, {e.direction}): {e.mechanism[:160]}"
        for i, e in enumerate(state.edges)
    )
    suffix = _facts_suffix(facts, extra=f"PROPOSED EDGES:\n{listing}")
    try:
        raw = router.call(
            "verify_edges", schema=SCHEMA_EDGE_VERDICTS,
            static_prefix=prompts.static_prefix(prompts.VERIFY_EDGES_PROMPT),
            dynamic_suffix=suffix,
        )
    except StageRouterError as exc:
        logger.warning("impact-graph edge verification unavailable, edges stay unverified: %s", exc)
        return
    verdicts = {v.get("index"): v for v in raw.get("verdicts", [])}
    for i, edge in enumerate(state.edges):
        verdict = verdicts.get(i)
        if verdict is None:
            edge.verification_status = "unverified"
        elif verdict.get("valid", True):
            edge.verification_status = "verified"
        else:
            edge.verification_status = "pruned"
            missing = verdict.get("missing_intermediate")
            if missing:
                edge.mechanism = f"{edge.mechanism} [PRUNED: missing step: {missing}]"
            elif verdict.get("reason"):
                edge.mechanism = f"{edge.mechanism} [PRUNED: {verdict['reason'][:160]}]"


def _rank(router: StageRouter, facts: EventFacts, state: _GraphState) -> list[dict]:
    companies = list(state.companies.values())
    if not companies:
        return []
    # Deterministic order first (spec doc 1 §9: the model proposes buckets,
    # CODE owns the sort): impact desc, then materiality, then confidence.
    companies.sort(key=lambda c: (c.impact_strength, c.materiality, c.confidence), reverse=True)
    tickers = [c.ticker for c in companies]
    listing = "\n".join(
        f"- {c.ticker} d{c.causal_distance} {c.direction} impact={c.impact_strength:.2f} "
        f"mat={c.materiality:.2f} conf={c.confidence:.2f} :: {c.mechanism[:140]}"
        for c in companies
    )
    try:
        raw = router.call(
            "rank_companies", schema=schema_ranking(tickers),
            static_prefix=prompts.static_prefix(prompts.RANKING_PROMPT),
            dynamic_suffix=_facts_suffix(facts, extra=f"VERIFIED COMPANIES:\n{listing}"),
            thinking="medium",
        )
    except StageRouterError as exc:
        logger.warning("impact-graph ranking unavailable, using deterministic order: %s", exc)
        return [
            {"ticker": c.ticker,
             "bucket": "beneficiary" if c.direction == "bullish"
             else "adversely_affected" if c.direction == "bearish" else "neutral_mixed",
             "rank_reason": None}
            for c in companies
        ]
    buckets = {r.get("ticker"): r for r in raw.get("ranked", []) if r.get("ticker") in set(tickers)}
    ranking = []
    for company in companies:  # deterministic order preserved
        entry = buckets.get(company.ticker) or {}
        bucket = entry.get("bucket")
        if bucket not in ("beneficiary", "adversely_affected", "neutral_mixed"):
            bucket = ("beneficiary" if company.direction == "bullish"
                      else "adversely_affected" if company.direction == "bearish" else "neutral_mixed")
        ranking.append({"ticker": company.ticker, "bucket": bucket,
                        "rank_reason": entry.get("rank_reason")})
    return ranking


# --- main entry -----------------------------------------------------------

def analyze_article_v3(router: StageRouter, title: str, content: str,
                       session=None, article_id: int | None = None) -> ImpactGraphResult:
    """Run the full impact-graph pipeline for one article. `router` decides
    providers/models (protected vs not) and carries the quality mark."""
    budget: ArticleBudget = router.budget or ArticleBudget(article_id=article_id)

    # Stage 1 -- facts. A failure here fails the article (nothing downstream
    # can reason without the event record), same contract as the old cascade.
    raw_facts = router.call(
        "extract_facts", schema=SCHEMA_FACTS,
        static_prefix=prompts.static_prefix(prompts.FACTS_PROMPT),
        dynamic_suffix=f"Title: {title}\n\nArticle:\n{content or '(no content -- reason from the title)'}",
        thinking="low", max_output_tokens=4096,
    )
    if raw_facts.get("category") not in CATEGORIES:
        raw_facts["category"] = "other"
    facts = EventFacts.model_validate(raw_facts)

    state = _GraphState()

    # Stage 2 -- initial shocks + distance-1 nodes (the graph anchor).
    raw_shocks = router.call(
        "initial_shocks", schema=SCHEMA_SHOCKS,
        static_prefix=prompts.static_prefix(prompts.SHOCKS_PROMPT),
        dynamic_suffix=_facts_suffix(facts),
        compact_suffix=_facts_suffix(EventFacts(**{**facts.model_dump(), "article_evidence": []})),
    )
    frontier: deque[_Node] = deque()
    for shock in raw_shocks.get("shocks", []):
        edge = GraphEdge(
            parent_type="event", parent_id=EVENT_NODE_ID, child_type="economic_node",
            child_id=str(shock.get("shock_id") or shock.get("label", "shock")).strip().lower().replace(" ", "_"),
            direction=shock.get("direction", "neutral"), mechanism=shock.get("mechanism", ""),
            causal_distance=1, impact_strength=shock.get("impact_strength", 0.5),
            confidence=shock.get("confidence", 0.0), materiality=shock.get("materiality", 0.5),
            time_horizon=shock.get("time_horizon", "Short-Term"),
        )
        if _register_edge(state, edge):
            node = _node_from_edge(edge, shock.get("label"), None)
            state.nodes[node.node_id] = node
            frontier.append(node)
    for raw_edge in raw_shocks.get("direct_nodes", []):
        try:
            edge = GraphEdge(**{k: v for k, v in raw_edge.items()
                                if k in GraphEdge.model_fields}, causal_distance=1)
        except ValidationError:
            continue
        if _register_edge(state, edge):
            node = _node_from_edge(edge, raw_edge.get("child_label"), raw_edge.get("child_sector"))
            state.nodes[node.node_id] = node
            frontier.append(node)

    # Stage 3 -- direct companies for every distance-1 node with candidates.
    for node in list(frontier):
        if budget.expansion_exhausted:
            break
        _map_companies_for_node(router, session, facts, state, node)

    # Stages 4/5/6 -- recursive frontier expansion, one hop per call.
    # Soft budget (75%) gates expansion so the reserve always covers
    # verification + ranking -- precision must never be what the budget cuts.
    while frontier:
        if budget.expansion_exhausted:
            router.quality = "budget_exhausted"
            logger.warning("impact-graph expansion budget exhausted at article=%s: %s",
                           article_id, budget.summary())
            break
        node = frontier.popleft()
        if node.node_id in state.expanded:
            continue
        if node.distance >= settings.max_causal_depth:
            continue
        if not _passes(node.distance, node.materiality, node.confidence):
            continue  # dead branch: no LLM call (spec test 13)
        if state.expansions >= MAX_EXPANSIONS_PER_ARTICLE:
            break
        state.expanded.add(node.node_id)
        state.expansions += 1

        existing_ids = ", ".join(sorted(state.nodes)) or "(none)"
        suffix = _facts_suffix(
            facts,
            extra=(
                f"FRONTIER NODE (expand exactly one hop from here):\n"
                f"- id: {node.node_id} ({node.node_type}), causal distance {node.distance}\n"
                f"- reached via: {_graph_outline(state)}\n\n"
                f"NODES ALREADY IN THE GRAPH (do not repeat): {existing_ids}\n"
                f"Every child you propose must have parent_id={node.node_id} and will sit at "
                f"causal distance {node.distance + 1}."
            ),
        )
        compact = _facts_suffix(
            facts,
            extra=(f"FRONTIER NODE: {node.node_id} ({node.node_type}), distance {node.distance}. "
                   f"Propose one-hop children; parent_id must be {node.node_id}."),
        )
        try:
            raw = router.call(
                "ripple_discovery", schema=SCHEMA_RIPPLE,
                static_prefix=prompts.static_prefix(prompts.RIPPLE_PROMPT),
                dynamic_suffix=suffix, compact_suffix=compact,
            )
        except StageRouterError as exc:
            state.gaps.append({"sector": node.sector or node.node_id,
                               "impact_level": _legacy_level(node.distance + 1),
                               "parent_ticker": None, "attempts": 4, "last_error": str(exc)[:500]})
            continue

        for raw_edge in raw.get("children", []):
            try:
                edge = GraphEdge(**{k: v for k, v in raw_edge.items() if k in GraphEdge.model_fields})
            except ValidationError:
                continue
            # The model must chain from the frontier node -- a child that
            # claims a different parent is re-anchored only if that parent
            # genuinely exists; otherwise dropped.
            if edge.parent_id != node.node_id and edge.parent_id not in state.nodes \
                    and edge.parent_id != EVENT_NODE_ID:
                continue
            if _register_edge(state, edge):
                child = _node_from_edge(edge, raw_edge.get("child_label"), raw_edge.get("child_sector"))
                state.nodes[child.node_id] = child
                frontier.append(child)
                if not budget.expansion_exhausted:
                    _map_companies_for_node(router, session, facts, state, child)

    # Stage 7/8 -- verification runs out of the reserved budget slice; only
    # a HARD overrun (past 100%) skips it.
    if not budget.exceeded:
        _verify_companies(router, facts, state)
        _verify_edges(router, facts, state)
    ranking = _rank(router, facts, state) if state.companies else []

    logger.info("impact-graph article=%s: %s nodes, %s edges, %s companies, budget=%s",
                article_id, len(state.nodes), len(state.edges), len(state.companies),
                budget.summary())

    return ImpactGraphResult(
        category=facts.category, event_type=facts.event_type, facts=facts.facts,
        event_label=facts.event, companies=list(state.companies.values()),
        edges=state.edges, gaps=state.gaps, ranking=ranking,
        analysis_provider=router.provider, analysis_quality=router.quality,
    )
