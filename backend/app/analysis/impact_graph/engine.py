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
    CHILD_TYPES, COUNTERFACTUAL_VERDICTS, PARENT_TYPES, SCHEMA_EDGE_VERDICTS, SCHEMA_FACTS,
    SCHEMA_RIPPLE, SCHEMA_SHOCKS, EventFacts, GraphCompany, GraphEdge, ImpactGraphResult,
    direction_to_effect, effect_to_direction,
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
# Related-frontier batching (token-opt P15): same-parent, same-distance
# siblings share ONE ripple call. Small on purpose -- indiscriminate
# bundling measurably hurt recall in the old cascade.
MAX_FRONTIER_BATCH = 3


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
    company_calls: int = 0
    # P9 canonical exposure dedup: (exposure_archetype, dimension, effect)
    # keys already evaluated this article -- an economically equivalent
    # node never re-buys the same company-level evaluation.
    evaluated_exposures: set = field(default_factory=set)
    # Observability (spec §30) -- graph-quality counters, logged and shipped
    # on ImpactGraphResult.metrics.
    metrics: dict = field(default_factory=lambda: {
        "nodes_discovered": 0, "edges_discovered": 0,
        "edges_rejected_discovery": 0, "edges_pruned_final": 0,
        "nodes_pruned_final": 0, "duplicate_nodes_removed": 0,
        "companies_considered": 0, "companies_retained": 0,
        "companies_pruned_final": 0, "completeness_rounds_run": 0,
        "completeness_branches_found": 0, "verification_failures": 0,
    })


def _facts_suffix(facts: EventFacts, extra: str = "") -> str:
    """Full fact context -- used ONLY by the graph-anchoring stage
    (initial_shocks), which genuinely needs the complete event record."""
    evidence = "\n".join(facts.article_evidence[:12])
    parts = [f"EVENT: {facts.event} (status: {facts.event_status})", f"FACTS: {facts.facts}"]
    if facts.quantities:
        parts.append("QUANTITIES: " + "; ".join(facts.quantities[:12]))
    if evidence:
        parts.append(f"ARTICLE EVIDENCE:\n{evidence}")
    if extra:
        parts.append(extra)
    return "\n\n".join(parts)


def _compact_suffix(facts: EventFacts, extra: str = "") -> str:
    """Sliced downstream context (token-opt P5/P6): event line + numbered
    canonical facts. Never the prose block, never article evidence, never
    the whole graph -- callers append only THIS call's frontier/ancestors/
    candidates via `extra`."""
    parts = [
        f"EVENT: {facts.event} (status: {facts.event_status})",
        f"FACTS:\n{facts.compact_lines()}",
    ]
    if extra:
        parts.append(extra)
    return "\n\n".join(parts)


def _ancestor_path(state: "_GraphState", node: "_Node") -> str:
    """The RELEVANT ancestor chain for one frontier node (token-opt P5) --
    replaces the whole-graph outline that used to ride every downstream
    call. One line per hop, mechanisms clipped."""
    lines = []
    current = node.node_id
    seen = set()
    while current != EVENT_NODE_ID and current not in seen:
        seen.add(current)
        edge = next((e for e in state.edges if e.child_id == current), None)
        if edge is None:
            break
        lines.append(f"d{edge.causal_distance} {edge.parent_id} -> {edge.child_id} "
                     f"({edge.direction}): {edge.mechanism[:90]}")
        current = edge.parent_id
    return "\n".join(reversed(lines)) if lines else "(direct from event)"


def _skip(stage: str, reason: str, **context) -> None:
    """No-call gate telemetry (token-opt P4): every avoided LLM call is a
    logged decision, never a silent absence."""
    logger.info("impact-graph call_skipped stage=%s reason=%s %s", stage, reason,
                " ".join(f"{k}={v}" for k, v in context.items()))


def _passes(distance: int, materiality: float, confidence: float) -> bool:
    """FINAL-prune gate: the distance-scaled thresholds. Applied after the
    completeness audit, never during discovery (architecture upgrade
    2026-08-12: discover broadly first, prune later)."""
    thresholds = impact_thresholds_for_distance(distance)
    return materiality >= thresholds["materiality"] and confidence >= thresholds["confidence"]


def _passes_discovery(materiality: float, confidence: float) -> bool:
    """Discovery-time floor: reject only the clearly nonsensical. Uncertain
    materiality is explicitly NOT a discovery-time rejection reason."""
    from app.config import IMPACT_DISCOVERY_MIN_CONFIDENCE, IMPACT_DISCOVERY_MIN_MATERIALITY

    return (materiality >= IMPACT_DISCOVERY_MIN_MATERIALITY
            and confidence >= IMPACT_DISCOVERY_MIN_CONFIDENCE)


def _register_edge(state: _GraphState, edge: GraphEdge) -> bool:
    """Deterministic edge gate at DISCOVERY time: schema-valid types, real
    parent, no dupes, no cycles (a child that already exists at <= parent
    distance is a back-edge), and the loose discovery floor. The strict
    distance-scaled thresholds run later in _final_materiality_prune, after
    the completeness audit had its chance to re-open branches.

    Node ids are NORMALIZED first (token-opt P7): "higher crude prices"
    and "crude price rises" collapse to one canonical id, so a synonym
    can never open a duplicate branch that would burn its own calls."""
    from app.analysis.impact_graph.normalize import normalize_node_id

    # Tickers and sector slugs are already canonical vocabularies -- the
    # economics normalizer only runs on free-form node ids (a singularizer
    # that turns railways_transport into railway_transport would orphan the
    # sector from its candidate pool).
    if edge.child_type not in ("company", "sector"):
        edge.child_id = normalize_node_id(edge.child_id)
    if edge.parent_id != EVENT_NODE_ID and edge.parent_type not in ("company", "sector"):
        edge.parent_id = normalize_node_id(edge.parent_id)
    if edge.parent_type not in PARENT_TYPES or edge.child_type not in CHILD_TYPES:
        return False
    if edge.parent_id != EVENT_NODE_ID and edge.parent_id not in state.nodes:
        return False
    if edge.child_id == edge.parent_id or edge.child_id == EVENT_NODE_ID:
        return False
    if edge.key in state.edge_keys:
        state.metrics["duplicate_nodes_removed"] += 1
        return False
    existing = state.nodes.get(edge.child_id)
    if existing is not None and existing.distance <= _parent_distance(state, edge):
        # Already reached at least this directly -- re-adding it deeper is
        # either a duplicate or a cycle; both are pruned.
        state.metrics["duplicate_nodes_removed"] += 1
        return False
    edge.clamp()
    edge.causal_distance = _parent_distance(state, edge) + 1
    if not _passes_discovery(edge.materiality, edge.confidence):
        state.metrics["edges_rejected_discovery"] += 1
        return False
    state.edges.append(edge)
    state.edge_keys.add(edge.key)
    state.metrics["edges_discovered"] += 1
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

def _subject_companies(session, facts: EventFacts) -> list:
    """Companies the article ITSELF names, resolved deterministically via
    the alias matcher (2026-08-12 fix): candidate lists are top-N by market
    cap per sector, so a small-cap article subject (ideaForge, measured
    live) could be structurally absent from its own story's candidates.
    Subjects are prepended to candidate lists and never count against the
    per-call cap. Free -- no LLM involvement."""
    return _subject_companies_ex(session, facts)[0]


def _subject_companies_ex(session, facts: EventFacts) -> tuple[list, set[str]]:
    """`_subject_companies` plus the set of named entities the alias matcher
    found genuinely AMBIGUOUS -- multiple real, tradeable companies with no
    tiebreak -- rather than simply absent (corrective-v4 Task 7). Either way
    the entity omits from `subjects` ("omit rather than mismatch" holds),
    but the two failure modes are not the same fact and postmortems
    shouldn't have to guess which one happened. app.pipeline._gate_candidates
    consumes the ambiguous set to tell REJECT_ENTITY_AMBIGUOUS apart from
    REJECT_UNKNOWN_COMPANY."""
    from app.companies.matching.matcher import resolve_with_ambiguity
    from app.models import Company as CompanyRow

    if session is None:
        return [], set()
    subjects, seen, ambiguous_entities = [], set(), set()
    for entity in (facts.named_entities or [])[:12]:
        try:
            match, ambiguous = resolve_with_ambiguity(session, None, entity)
        except Exception:  # noqa: BLE001 -- matcher trouble never blocks analysis
            continue
        if ambiguous:
            ambiguous_entities.add(entity)
        if match is None or match.company_id in seen:
            continue
        row = session.get(CompanyRow, match.company_id)
        if row is not None and row.market == "INDIA" and row.tradeability == "NORMAL":
            seen.add(match.company_id)
            subjects.append(row)
    return subjects, ambiguous_entities


# Provenance values a candidate-profile line may honestly call "verified"
# (corrective-v4 Task 6): only an independently-sourced relationship, never
# the system's own MODEL_VERIFIED prior or a NULL-provenance legacy row --
# see app.analysis.impact_graph.evidence._PROVENANCED_EXPOSURE_TYPES, same
# vocabulary.
_PROVENANCED_EXPOSURE_TYPES = ("SUPPLY_LINK", "MANUAL", "CURATED")


def _candidate_profile_lines(candidates, cached_by_ticker: dict) -> str:
    """Compact exposure-profile lines (token-opt P8): ticker | name |
    sub_sector | clipped business line -- never the full biography. A
    cached exposure row replaces the generic description entirely: the
    model gets the prior mechanism instead of rediscovering it. The label
    must not overclaim (Task 6, self-certification fix): a MODEL_VERIFIED
    or NULL-provenance row is the model's OWN earlier acceptance, not an
    independent check, so it reads as an unconfirmed prior the model may
    freely override -- only a provenanced row (SUPPLY_LINK/MANUAL/CURATED)
    may say "verified"."""
    lines = []
    for c in candidates:
        cached = cached_by_ticker.get(c.ticker)
        if cached is not None:
            mechanism = (cached.mechanism or "exposure confirmed")[:90]
            if getattr(cached, "provenance_type", None) in _PROVENANCED_EXPOSURE_TYPES:
                label = f"[VERIFIED EXPOSURE (provenanced): {mechanism}]"
            else:
                label = f"[PRIOR EXPOSURE (model-derived, unconfirmed): {mechanism}]"
            lines.append(f"- {c.ticker} ({c.name}) {label} "
                         f"-- judge THIS event's specific effect; you may override if this event changes the relationship")
            continue
        seg = f" | {c.sub_sector}" if c.sub_sector else ""
        desc = f" | {c.business_desc[:60]}" if getattr(c, "business_desc", None) else ""
        lines.append(f"- {c.ticker} ({c.name}){seg}{desc}")
    return "\n".join(lines)


def _exposure_cache(session, node_key: str, tickers_to_ids: dict) -> tuple[dict, set]:
    """(positive rows by ticker, negatively-cached tickers) for one
    normalized node -- stale rows are ignored. Freshness is delegated to
    exposure_row_is_fresh (the ONE staleness rule every reader must apply,
    spec §8; this reader used to reimplement it inline, an audited
    defect -- corrective-v4 Task 6)."""
    from app.analysis.impact_graph.exposure import exposure_row_is_fresh
    from app.models import CompanyNodeExposure

    if session is None or not tickers_to_ids:
        return {}, set()
    rows = (
        session.query(CompanyNodeExposure)
        .filter(CompanyNodeExposure.node_key == node_key,
                CompanyNodeExposure.company_id.in_(list(tickers_to_ids.values())))
        .all()
    )
    ids_to_tickers = {v: k for k, v in tickers_to_ids.items()}
    positive, negative = {}, set()
    for row in rows:
        ticker = ids_to_tickers.get(row.company_id)
        if ticker is None:
            continue
        if not exposure_row_is_fresh(row, row.company):
            continue  # stale -- company metadata changed since verification, or past review_after
        if row.exposure_exists:
            positive[ticker] = row
        else:
            negative.add(ticker)
    return positive, negative


def _candidate_pool(session, facts: EventFacts, state: _GraphState, node: _Node) -> list:
    """Exposure-based candidate pool (spec §9): sector nodes keep their
    sector pool; economic/commodity/policy nodes retrieve through the
    exposure ontology (node vocabulary -> exposed sectors) PLUS any company
    whose exposure to this exact node key was verified on an earlier event
    (relationship cache as retrieval index). Sector membership is no longer
    the only road to candidacy."""
    from app.analysis.impact_graph.exposure import cached_exposed_companies, sectors_for_node

    if node.sector is not None:
        candidates = candidate_companies(session, [node.sector])
        subject_sector = node.sector
    else:
        hinted = sectors_for_node(node.node_id, node.label)
        candidates = candidate_companies(session, hinted) if hinted else []
        subject_sector = None
        # Cache-verified exposures ride the pool regardless of sector.
        for cached in cached_exposed_companies(session, node.node_id):
            if all(c.ticker != cached.ticker for c in candidates):
                candidates.insert(0, cached)
    # Article-subject seeding: companies the article names always ride the
    # list for their own sector, cap or no cap.
    for subject in _subject_companies(session, facts):
        if (subject_sector is None or subject.sector == subject_sector) \
                and all(c.ticker != subject.ticker for c in candidates):
            candidates.insert(0, subject)
    return candidates


def _map_companies_for_node(router: StageRouter, session, facts: EventFacts,
                            state: _GraphState, node: _Node) -> None:
    """Stage 3 (distance 1) / stage 5 (ripples): candidate-grounded company
    mapping for one graph node. Deterministic no-call gates run first and
    every skip is logged (token-opt P4)."""
    from app.config import IMPACT_MAX_COMPANY_MAP_CALLS

    if node.node_id in state.evaluated_nodes:
        _skip("map_companies", "node_already_evaluated", node=node.node_id)
        return
    state.evaluated_nodes.add(node.node_id)
    if session is None:
        return
    if state.company_calls >= IMPACT_MAX_COMPANY_MAP_CALLS:
        _skip("map_companies", "company_call_cap", node=node.node_id,
              cap=IMPACT_MAX_COMPANY_MAP_CALLS)
        return
    candidates = _candidate_pool(session, facts, state, node)
    candidates = [
        c for c in candidates
        if c.ticker not in state.companies and c.ticker not in state.rejected_tickers
    ]
    tickers_to_ids = {c.ticker: c.id for c in candidates}
    cached_positive, cached_negative = _exposure_cache(session, node.node_id, tickers_to_ids)
    if cached_negative:
        _skip("map_companies", "negative_relationship_cache", node=node.node_id,
              skipped=len(cached_negative))
        candidates = [c for c in candidates if c.ticker not in cached_negative]
    candidates = candidates[:MAX_CANDIDATES_PER_CALL]
    if not candidates:
        _skip("map_companies", "no_candidates", node=node.node_id, sector=node.sector)
        return
    tickers = candidate_tickers(candidates)
    stage_prompt = prompts.DIRECT_COMPANIES_PROMPT if node.distance <= 1 else prompts.RIPPLE_COMPANIES_PROMPT
    parent_edge = next((e for e in state.edges if e.child_id == node.node_id), None)
    parent_desc = (
        f"PARENT NODE: {node.node_id} ({node.node_type}, causal distance {node.distance})\n"
        f"PARENT MECHANISM: {parent_edge.mechanism if parent_edge else facts.event}\n"
        f"PARENT DIRECTION: {parent_edge.direction if parent_edge else 'n/a'}\n"
        f"CAUSAL PATH TO THIS NODE:\n{_ancestor_path(state, node)}"
    )
    suffix = _compact_suffix(
        facts,
        extra=(
            f"{parent_desc}\n\n"
            "For every company weigh COMPETING channels (positive_channels / "
            "negative_channels) and report the NET direction -- mixed and "
            "uncertain are valid; a relative beneficiary (better off than "
            "peers) is not automatically an absolute winner. For diversified "
            "companies judge the RELEVANT segment, not the whole conglomerate.\n\n"
            "CANDIDATE COMPANIES -- choose ONLY from this list; selecting none is a "
            "correct answer when none genuinely qualifies:\n"
            + _candidate_profile_lines(candidates, cached_positive)
        ),
    )
    compact = _compact_suffix(
        facts,
        extra=f"{parent_desc}\n\nCANDIDATE COMPANIES:\n"
              + _candidate_profile_lines(candidates[:20], cached_positive),
    )
    state.company_calls += 1
    # Semantic cache seed (cost-opt P12): node + candidates + facts. The
    # raw suffix also carries relationship-cache annotations that change
    # after every verify pass -- they must not invalidate the cache for a
    # semantically identical call (measured leak: Rs ~4/retry).
    cache_seed = "|".join([
        node.node_id, ",".join(sorted(tickers)), facts.compact_lines(limit=8),
    ])
    try:
        entries = _judge_candidates(
            router, state, stage_prompt=stage_prompt, suffix=suffix, compact=compact,
            tickers=tickers,
            context={"parent_node": node.node_id, "candidate_count": len(candidates)},
            cache_seed=cache_seed,
        )
    except StageRouterError as exc:
        state.gaps.append({"sector": node.sector, "impact_level": _legacy_level(node.distance),
                           "parent_ticker": None, "attempts": 4, "last_error": str(exc)[:500]})
        return
    _register_company_entries(state, entries, node)


def _legacy_level(distance: int) -> str:
    """UI-facing legacy label derived from causal distance. Distances >= 3
    reuse indirect_l2 for now -- the integer causal_distance column carries
    the truth; the frontend gains L3/L4+ labels separately."""
    if distance <= 1:
        return "direct"
    if distance == 2:
        return "indirect_l1"
    return "indirect_l2"


# --- knowledge-architecture mapping (cost-opt spec 2026-08-12) ------------

def _priority_tiers(session, candidates, dimension: str):
    """P8 deterministic candidate prioritization: exposure-registry level on
    the mechanism's dimension x data quality. Returns candidates ordered
    Tier A (HIGH+), then B (MEDIUM/UNKNOWN -- the safety band), then C
    (LOW/NONE). A ROUTING order only -- Tier C is trimmed by the per-call
    cap, never permanently discarded (escalation may still reach it)."""
    from app.analysis.impact_graph.knowledge import exposure_levels_for, level_rank

    levels = exposure_levels_for(session, [c.id for c in candidates])
    scored = []
    for company in candidates:
        rank = level_rank(levels.get((company.id, dimension)))
        quality = 1 if getattr(company, "business_desc", None) else 0
        scored.append((rank, quality, company))
    scored.sort(key=lambda t: (-t[0], -t[1], t[2].ticker))
    tier_a = [c for r, _, c in scored if r >= 3]
    tier_b = [c for r, _, c in scored if r in (1, 2)]
    tier_c = [c for r, _, c in scored if r == 0]
    return tier_a, tier_b, tier_c


def _escalation_tickers(entries: list[dict], candidate_count: int,
                        prior_effect: str | None) -> list[str]:
    """P10 escalation triggers: which returned entries deserve a HIGH-
    thinking re-judgement. Empty list = the medium result stands."""
    flagged = []
    big_call = candidate_count > 30 or len(entries) > 8
    for entry in entries:
        ticker = entry.get("ticker")
        if not ticker:
            continue
        confidence = float(entry.get("confidence") or 0)
        materiality = float(entry.get("materiality") or 0)
        net = entry.get("net_direction") or ""
        conflicts_prior = (
            prior_effect in ("positive", "negative")
            and entry.get("direction") in ("bullish", "bearish")
            and entry["direction"] != ("bullish" if prior_effect == "positive" else "bearish")
        )
        near_threshold = abs(materiality - impact_thresholds_for_distance(
            int(entry.get("causal_distance") or 2))["materiality"]) <= 0.05
        if (confidence < 0.6 or net in ("mixed", "uncertain") or conflicts_prior
                or near_threshold or big_call):
            flagged.append(ticker)
    return flagged[:12]


def _judge_candidates(router: StageRouter, state: _GraphState, *, stage_prompt: str,
                      suffix: str, compact: str | None, tickers: list[str],
                      context: dict, cache_seed: str, prior_effect: str | None = None,
                      candidate_lines: str = "") -> list[dict]:
    """One mapping call, MEDIUM-first with selective HIGH escalation (spec
    P10). Returns the raw entry dicts; the caller validates/registers.
    Escalation re-judges only the flagged subset -- never the whole call --
    and its (high-thinking) result replaces those entries."""
    from app.config import IMPACT_MAPPING_ESCALATION, IMPACT_MAPPING_THINKING

    raw = router.call(
        "map_companies", schema=schema_companies(tickers),
        static_prefix=prompts.static_prefix(stage_prompt),
        dynamic_suffix=suffix, compact_suffix=compact,
        thinking=IMPACT_MAPPING_THINKING, context=context, cache_seed=cache_seed,
    )
    entries = [e for e in raw.get("companies", []) if e.get("ticker") in set(tickers)]
    if not IMPACT_MAPPING_ESCALATION or router.budget is None or router.budget.exceeded:
        return entries
    flagged = _escalation_tickers(entries, len(tickers), prior_effect)
    if not flagged:
        return entries
    _skip("map_companies", "escalating_to_high", count=len(flagged))
    try:
        escalated = router.call(
            "map_companies_escalation", schema=schema_companies(flagged),
            static_prefix=prompts.static_prefix(prompts.ESCALATION_PROMPT),
            dynamic_suffix=(f"{suffix}\n\nRE-JUDGE ONLY THESE FLAGGED CANDIDATES "
                            f"(low confidence / competing channels / near threshold / "
                            f"prior conflict): {', '.join(flagged)}"),
            thinking="high",
            context={**context, "candidate_count": len(flagged)},
            cache_seed=f"{cache_seed}|escalation",
        )
    except StageRouterError:
        return entries  # medium result stands; escalation is best-effort
    replacements = {e.get("ticker"): e for e in escalated.get("companies", [])
                    if e.get("ticker") in set(flagged)}
    merged = [replacements.get(e.get("ticker"), e) for e in entries]
    # A flagged candidate the escalation DROPPED stays dropped -- high
    # thinking judged it out; also admit escalation-only additions.
    merged = [e for e in merged if e.get("ticker") not in set(flagged)
              or e.get("ticker") in replacements]
    return merged


def _register_company_entries(state: _GraphState, entries: list[dict], node: _Node,
                              mechanism_id: str | None = None) -> None:
    """Shared validation/registration for mapping results (discovery floor
    only -- final prune stays the single strict gate)."""
    for entry in entries:
        ticker = entry.get("ticker")
        try:
            company = GraphCompany(
                **{**{k: v for k, v in entry.items() if k in GraphCompany.model_fields},
                   "causal_distance": node.distance,
                   "parent_type": node.node_type, "parent_id": node.node_id,
                   "discovery_source": f"archetype:{mechanism_id}" if mechanism_id else ""},
            ).clamp()
        except ValidationError as exc:
            logger.warning("impact-graph company entry rejected by schema: %s", exc)
            continue
        state.metrics["companies_considered"] += 1
        if not _passes_discovery(company.materiality or 0.0, company.confidence):
            state.rejected_tickers.add(ticker)
            continue
        held = state.companies.get(ticker)
        if held is None or company.impact_strength > held.impact_strength:
            state.companies[ticker] = company


def _archetype_mapping(router: StageRouter, session, facts: EventFacts,
                       state: _GraphState, budget: ArticleBudget,
                       article_id: int | None, archetype_id: str, direction: str) -> None:
    """P5/P7 knowledge-driven mapping: the matched event archetype's
    mechanism slice replaces open-ended rediscovery. Each mechanism becomes
    a graph node hung off its trigger shock, retrieves its archetype's
    candidate universe deterministically, priority-tiers it, and runs ONE
    small mapping call whose prompt carries the mechanism PRIOR -- Gemini
    judges applicability to THIS event and may override the prior."""
    from app.analysis.impact_graph.knowledge import (
        MECHANISM_DIMENSIONS, companies_for_archetype, oriented_mechanisms,
    )
    from app.analysis.impact_graph.normalize import normalize_node_id
    from app.config import IMPACT_MAX_COMPANY_MAP_CALLS, IMPACT_TIER_CAP

    mechanisms = oriented_mechanisms(archetype_id, direction)
    mechanisms.sort(key=lambda m: -m["confidence_baseline"])
    logger.info("impact-graph archetype=%s direction=%s mechanisms=%s article=%s",
                archetype_id, direction, len(mechanisms), article_id)
    state.metrics["event_archetype"] = archetype_id

    def _trigger_node(parent_variable: str) -> _Node | None:
        target = set(normalize_node_id(parent_variable).split("_"))
        best, best_overlap = None, 0.0
        for candidate_node in state.nodes.values():
            if candidate_node.node_type != "economic_node":
                continue
            tokens = set(candidate_node.node_id.replace("shock_", "").split("_"))
            overlap = len(target & tokens) / max(1, len(target | tokens))
            if overlap > best_overlap:
                best, best_overlap = candidate_node, overlap
        return best if best_overlap >= 0.4 else None

    from app.config import IMPACT_MIN_MECHANISM_CONFIDENCE

    for mech in mechanisms:
        if budget.expansion_exhausted:
            _skip("archetype_mapping", "budget_soft_stop", article=article_id)
            break
        if state.company_calls >= IMPACT_MAX_COMPANY_MAP_CALLS:
            _skip("archetype_mapping", "company_call_cap", mechanism=mech["mechanism_id"])
            break
        # Prior-confidence floor (eligibility directive): weak second-order
        # priors are not force-mapped on every archetype event -- the
        # dynamic path and completeness audit can still surface them when
        # THIS event genuinely activates them.
        if mech["confidence_baseline"] < IMPACT_MIN_MECHANISM_CONFIDENCE:
            _skip("archetype_mapping", "below_prior_confidence_floor",
                  mechanism=mech["mechanism_id"],
                  baseline=mech["confidence_baseline"])
            continue
        dimension = MECHANISM_DIMENSIONS.get(mech["mechanism_id"], "general")
        dedup_key = (mech["child_exposure"], dimension, mech["oriented_effect"])
        if dedup_key in state.evaluated_exposures:
            _skip("archetype_mapping", "canonical_exposure_dedup",
                  mechanism=mech["mechanism_id"], key="|".join(dedup_key))
            continue
        state.evaluated_exposures.add(dedup_key)

        parent = _trigger_node(mech["parent_variable"])
        if parent is None:
            # Shock stage did not surface the trigger variable -- honor the
            # model's event-specific judgment; do not force the template.
            _skip("archetype_mapping", "trigger_shock_absent",
                  mechanism=mech["mechanism_id"], variable=mech["parent_variable"])
            continue
        # The archetype slice IS this trigger's ripple set -- generic ripple
        # discovery must not re-buy the same universe (cost-opt P9/P16).
        state.expanded.add(parent.node_id)

        node_id = normalize_node_id(mech["mechanism_id"])
        edge = GraphEdge(
            parent_type="economic_node", parent_id=parent.node_id,
            child_type="economic_node", child_id=node_id,
            economic_effect=mech["oriented_effect"], mechanism=mech["mechanism"],
            impact_strength=mech["confidence_baseline"] * 0.8,
            confidence=mech["confidence_baseline"], materiality=0.6,
            time_horizon=mech["time_horizon"],
        )
        if _register_edge(state, edge):
            node = _node_from_edge(edge, mech["mechanism_id"].replace("_", " "), None)
            state.nodes[node.node_id] = node
        else:
            node = state.nodes.get(edge.child_id)
            if node is None:
                continue
        state.evaluated_nodes.add(node.node_id)

        # ELIGIBILITY gate (directive §2/§3/§16): archetype membership is
        # only candidacy; the company's VERIFIED exposure on the mechanism's
        # required dimension must clear the mechanism's threshold. UNKNOWN
        # is not eligible (a verified node relationship is the one escape).
        from app.analysis.impact_graph.knowledge import eligible_candidates

        eligible, pool_size = eligible_candidates(session, mech, node_id)
        candidates = [c for c in eligible
                      if c.ticker not in state.companies
                      and c.ticker not in state.rejected_tickers]
        if pool_size and len(eligible) < pool_size:
            _skip("archetype_mapping", "eligibility_gate_trimmed",
                  mechanism=mech["mechanism_id"], eligible=len(eligible), pool=pool_size)
        if not candidates:
            _skip("archetype_mapping", "no_eligible_candidates",
                  mechanism=mech["mechanism_id"], pool=pool_size)
            continue
        tier_a, tier_b, tier_c = _priority_tiers(session, candidates, dimension)
        high_impact = mech["confidence_baseline"] >= 0.75
        chosen = (tier_a + tier_b) if high_impact else (tier_a + tier_b[:10])
        chosen = (chosen + tier_c)[:IMPACT_TIER_CAP]
        if len(chosen) < len(candidates):
            _skip("archetype_mapping", "tier_trimmed", mechanism=mech["mechanism_id"],
                  offered=len(chosen), pool=len(candidates))

        tickers = [c.ticker for c in chosen]
        prior_line = (
            f"MECHANISM PRIOR (from the verified registry -- judge whether it applies to "
            f"THIS event; override freely if the event's facts differ):\n"
            f"- id: {mech['mechanism_id']}\n"
            f"- expected effect on this exposure class: {mech['oriented_effect']}\n"
            f"- mechanism: {mech['mechanism']}\n"
            f"- typical horizon: {mech['time_horizon']}"
        )
        candidate_lines = _candidate_profile_lines(chosen, {})
        suffix = _compact_suffix(
            facts,
            extra=(f"PARENT NODE: {parent.node_id} (causal distance {parent.distance})\n\n"
                   f"{prior_line}\n\n"
                   "CANDIDATE COMPANIES -- choose ONLY from this list; selecting none is "
                   "correct when the mechanism does not genuinely apply:\n" + candidate_lines),
        )
        cache_seed = "|".join([
            str(article_id), mech["mechanism_id"], mech["oriented_effect"],
            ",".join(sorted(tickers)), facts.compact_lines(limit=8),
        ])
        state.company_calls += 1
        try:
            entries = _judge_candidates(
                router, state, stage_prompt=prompts.MECHANISM_MAPPING_PROMPT,
                suffix=suffix, compact=None, tickers=tickers,
                context={"parent_node": node.node_id, "mechanism_id": mech["mechanism_id"],
                         "candidate_count": len(tickers)},
                cache_seed=cache_seed, prior_effect=mech["oriented_effect"],
            )
        except StageRouterError as exc:
            state.gaps.append({"sector": mech["child_exposure"], "impact_level": _legacy_level(node.distance),
                               "parent_ticker": None, "attempts": 4, "last_error": str(exc)[:500]})
            continue
        _register_company_entries(state, entries, node, mechanism_id=mech["mechanism_id"])


# --- final materiality pruning (spec §15) ---------------------------------

def _final_materiality_prune(state: _GraphState) -> None:
    """The ONE place the strict distance-scaled thresholds apply -- runs
    after completeness expansion, before LLM verification (so verification
    tokens are never spent on branches code can prune deterministically).

    Order: edges below threshold go; nodes no longer reachable from the
    event go; companies below threshold or orphaned by node pruning go.
    Mixed/uncertain net effects are gated on MATERIALITY ONLY -- an honest
    "we cannot call the direction" must survive to the product (spec §11);
    its display confidence is then capped so it never reads as a confident
    directional call (net-effect discipline, token-opt P12)."""
    kept_edges = []
    for edge in state.edges:
        if _passes(edge.causal_distance, edge.materiality, edge.confidence):
            kept_edges.append(edge)
        else:
            state.metrics["edges_pruned_final"] += 1

    # Reachability over surviving edges: a branch whose trunk was pruned is
    # gone entirely, not left dangling.
    children_of: dict[str, list] = {}
    for edge in kept_edges:
        children_of.setdefault(edge.parent_id, []).append(edge)
    reachable: set[str] = set()
    queue = deque([EVENT_NODE_ID])
    while queue:
        current = queue.popleft()
        for edge in children_of.get(current, []):
            if edge.child_id not in reachable:
                reachable.add(edge.child_id)
                queue.append(edge.child_id)
    kept_edges = [e for e in kept_edges
                  if e.parent_id == EVENT_NODE_ID or e.parent_id in reachable]
    state.edges = kept_edges
    state.edge_keys = {e.key for e in kept_edges}
    for node_id in set(state.nodes) - reachable:
        state.nodes.pop(node_id, None)
        state.metrics["nodes_pruned_final"] += 1

    for ticker in list(state.companies):
        company = state.companies[ticker]
        thresholds = impact_thresholds_for_distance(company.causal_distance)
        mixed = company.net_direction in ("mixed", "uncertain")
        ok_materiality = (company.materiality or 0.0) >= thresholds["materiality"]
        ok_confidence = mixed or company.confidence >= thresholds["confidence"]
        parent_alive = company.parent_id == EVENT_NODE_ID or company.parent_id in state.nodes
        # Neutral is not a garbage category (eligibility directive §11): a
        # neutral company without articulated competing channels is a weak
        # association, not an offsetting analysis -- prune it. A genuine
        # offset carries both channel lists.
        neutral_garbage = (
            company.economic_effect == "no_material_impact"
            and not (company.positive_channels and company.negative_channels)
            and not company.offsetting_channels
        )
        if not (ok_materiality and ok_confidence and parent_alive) or neutral_garbage:
            state.companies.pop(ticker)
            state.rejected_tickers.add(ticker)
            state.metrics["companies_pruned_final"] += 1
            continue
        if mixed:
            company.confidence = min(company.confidence, 0.55)
    state.metrics["companies_retained"] = len(state.companies)


# --- verification ---------------------------------------------------------

# Reject reasons that indicate a STRUCTURAL (event-independent) absence of
# exposure -- only these write a negative relationship-cache row. An
# event-specific rejection ("immaterial for this event") must never poison
# a future event's recall (token-opt P10 recall protection).
_STRUCTURAL_REJECT_MARKERS = (
    "no exposure", "no material exposure", "does not operate", "false premise",
    "not exposed", "no business", "does not have", "no such exposure",
)


def _apply_company_correction(company: GraphCompany, correction: dict) -> None:
    """Apply one verifier correction, keeping `direction` and
    `economic_effect` consistent. A direction flip re-derives the effect;
    a correction to "neutral" leaves mixed/uncertain effects alone, since
    those already render as neutral direction -- flattening them would
    destroy the mixed-channel truth (spec §42)."""
    direction = correction.get("direction")
    if direction in ("bullish", "bearish", "neutral"):
        company.direction = direction
        if effect_to_direction(company.economic_effect or "") != direction:
            company.economic_effect = direction_to_effect(direction)
        # net_direction shares direction vocabulary plus mixed/uncertain;
        # mixed/uncertain render as neutral, so only a real inconsistency
        # (e.g. net "bullish" under a "bearish" correction) is rewritten.
        net = company.net_direction
        net_as_direction = net if net in ("bullish", "bearish") else "neutral"
        if net and net_as_direction != direction:
            company.net_direction = direction
    distance = correction.get("causal_distance")
    if isinstance(distance, int) and 1 <= distance <= settings.max_causal_depth:
        company.causal_distance = distance
    for field in ("materiality", "confidence"):
        value = correction.get(field)
        if isinstance(value, (int, float)):
            setattr(company, field, max(0.0, min(1.0, float(value))))


def _verify_companies(router: StageRouter, session, facts: EventFacts,
                      state: _GraphState, alert_id: int | None = None) -> None:
    """Diff-contract verification (token-opt P17): the verifier returns
    accept[]/reject[]/corrections{} and code applies them.

    Every candidate faces THIS event's verification, always (corrective-v4
    Task 6: the exposure self-certification loop is closed). There used to
    be a deterministic pre-verification step here: a company whose
    relationship cache already carried a positive row skipped the verifier
    outright and was auto-accepted. That is exactly a self-certification
    loop -- _write_exposure_cache below writes the row the NEXT event's
    auto-accept would read back, so one LLM acceptance could keep
    certifying itself forever without ever facing a current-event check
    again. The cache still seeds candidacy (_candidate_pool /
    _exposure_cache) and still annotates the prompt as a PRIOR the model
    may override -- it may never again substitute for verification."""
    companies = list(state.companies.values())
    if not companies:
        return

    to_verify = companies
    tickers = [c.ticker for c in to_verify]

    def _company_path(company: GraphCompany) -> str:
        """Full causal path for path-verification (spec §17): event -> ... ->
        parent node -> company, one clipped line."""
        parent = state.nodes.get(company.parent_id)
        if parent is None:
            return "(direct from event)"
        return _ancestor_path(state, parent) + f"\n  d{company.causal_distance} {company.parent_id} -> {company.ticker}"

    listing = "\n".join(
        f"- {c.ticker} ({c.name}) d{c.causal_distance} {c.direction} net={c.net_direction or '-'} "
        f"impact={c.impact_strength:.2f} conf={c.confidence:.2f} mat={(c.materiality or 0.0):.2f} "
        f"parent={c.parent_type}:{c.parent_id} :: {c.mechanism[:140]}\n"
        f"  path: {_company_path(c)}"
        for c in to_verify
    )
    suffix = _compact_suffix(facts, extra=f"PROPOSED COMPANIES:\n{listing}")
    try:
        raw = router.call(
            "verify_companies", schema=schema_company_verdicts(tickers),
            static_prefix=prompts.static_prefix(prompts.VERIFY_COMPANIES_PROMPT),
            dynamic_suffix=suffix,
            context={"candidate_count": len(to_verify)},
        )
    except StageRouterError as exc:
        logger.warning("impact-graph company verification unavailable, keeping recall set: %s", exc)
        # The verifier never ran: record it so the publication gate can
        # fail closed (REJECT_VALIDATOR_UNAVAILABLE) instead of treating
        # "unverified because the validator was down" as ordinary output.
        state.metrics["verification_unavailable"] = 1
        return

    accepted = {t for t in raw.get("accept", []) if t in state.companies}
    for rejection in raw.get("reject", []):
        ticker = rejection.get("ticker")
        company = state.companies.pop(ticker, None)
        if company is None:
            continue
        state.rejected_tickers.add(ticker)
        state.metrics["verification_failures"] += 1
        reason = (rejection.get("reason") or "").lower()
        if session is not None and any(marker in reason for marker in _STRUCTURAL_REJECT_MARKERS):
            _write_exposure_cache(session, company, exposure_exists=False, alert_id=alert_id)
    for correction in raw.get("corrections", []) or []:
        company = state.companies.get(correction.get("ticker"))
        if company is None:
            continue
        _apply_company_correction(company, correction)
    for ticker in accepted:
        state.companies[ticker].verified = True
    # Counterfactual verdicts (Task 9): a ticker -> verdict map, validated
    # against both the enum and state.companies (an unknown ticker or a
    # garbage verdict is dropped, never trusted) -- applied to every company
    # STILL IN state.companies, not only the accepted ones, so an explicit
    # verdict the model gave for some other reason is never silently thrown
    # away. An ACCEPTED company the model omitted from this map is not "no
    # answer" in the same sense as a company the verifier never reached at
    # all -- the verifier ran and looked at the whole set, so silence on one
    # accepted ticker is graded UNCERTAIN (displayable as a deep dive, never
    # primary -- spec §25/§31) rather than left "" (which the gate reads as
    # REJECT_VALIDATOR_UNAVAILABLE, the "verifier never ran" state). A
    # company with no accept, no reject, AND no counterfactual entry -- pure
    # silence on every question -- keeps "" and fails exactly that closed.
    counterfactual_map = raw.get("counterfactual", {}) or {}
    for ticker, company in state.companies.items():
        verdict = counterfactual_map.get(ticker)
        if verdict in COUNTERFACTUAL_VERDICTS:
            company.counterfactual = verdict
        elif ticker in accepted:
            company.counterfactual = "UNCERTAIN"
    # A company with neither an accept nor a reject verdict stays in
    # state.companies (still visible for the run's bookkeeping) but its
    # `verified` flag was reset to False before this call and is never set
    # True here -- silence is not acceptance, so REJECT_UNVERIFIED (or, if
    # the counterfactual question was equally unanswered, the earlier
    # REJECT_VALIDATOR_UNAVAILABLE) applies at the gate exactly as if the
    # verifier had explicitly said no.
    # Positive relationships from verified companies feed the cache.
    if session is not None:
        for company in state.companies.values():
            if company.verified:
                _write_exposure_cache(session, company, exposure_exists=True, alert_id=alert_id)


def _write_exposure_cache(session, company: GraphCompany, *, exposure_exists: bool,
                          alert_id: int | None) -> None:
    """Upsert one (company, node) relationship row. BASE exposure only:
    mechanism is the company-level channel, never the event narrative.

    provenance_type is MODEL_VERIFIED (corrective-v4 Task 6, spec §8/§9),
    never VERIFIED_RELATIONSHIP: this row records the CURRENT VERIFIER'S
    acceptance of this candidate for THIS event -- not an independently
    sourced fact. app.analysis.impact_graph.evidence.classify_evidence
    reads provenance_type back and refuses to grant Tier C for
    MODEL_VERIFIED, precisely so this write can never certify a future
    candidate's evidence on its own; it only seeds candidacy and an
    unconfirmed prompt prior. review_after gives the prior a 90-day
    expiry -- exposure_row_is_fresh treats a row past it as stale, so
    acceptance re-earns its place instead of compounding forever."""
    from datetime import timedelta

    from app.models import Company as CompanyRow, CompanyNodeExposure, utcnow

    row = session.query(CompanyRow).filter_by(ticker=company.ticker).one_or_none()
    if row is None:
        return
    existing = (
        session.query(CompanyNodeExposure)
        .filter_by(company_id=row.id, node_key=company.parent_id)
        .one_or_none()
    )
    now = utcnow()
    review_after = now + timedelta(days=90)
    if existing is None:
        session.add(CompanyNodeExposure(
            company_id=row.id, node_key=company.parent_id,
            exposure_exists=1 if exposure_exists else 0,
            strength=company.impact_strength if exposure_exists else None,
            mechanism=company.mechanism[:300] if exposure_exists else None,
            verified_at=now, source_alert_id=alert_id,
            provenance_type="MODEL_VERIFIED",
            review_after=review_after,
            verification_version=prompts.IMPACT_PROMPT_VERSION,
        ))
    else:
        existing.exposure_exists = 1 if exposure_exists else 0
        existing.strength = company.impact_strength if exposure_exists else None
        existing.mechanism = company.mechanism[:300] if exposure_exists else existing.mechanism
        existing.verified_at = now
        existing.source_alert_id = alert_id
        existing.provenance_type = "MODEL_VERIFIED"
        existing.review_after = review_after
        existing.verification_version = prompts.IMPACT_PROMPT_VERSION


def _verify_edges(router: StageRouter, facts: EventFacts, state: _GraphState) -> None:
    if not state.edges:
        return
    listing = "\n".join(
        f"{i}. {e.parent_type}:{e.parent_id} -> {e.child_type}:{e.child_id} "
        f"(d{e.causal_distance}, {e.direction}): {e.mechanism[:160]}"
        for i, e in enumerate(state.edges)
    )
    suffix = _compact_suffix(facts, extra=f"PROPOSED EDGES:\n{listing}")
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
            state.metrics["verification_failures"] += 1
            missing = verdict.get("missing_intermediate")
            if missing:
                edge.mechanism = f"{edge.mechanism} [PRUNED: missing step: {missing}]"
            elif verdict.get("reason"):
                edge.mechanism = f"{edge.mechanism} [PRUNED: {verdict['reason'][:160]}]"


def _rank(state: _GraphState) -> list[dict]:
    """Fully deterministic ranking (token-opt P20): Gemini already supplied
    the analytical inputs (impact/materiality/confidence/net_direction);
    bucketing and sorting are arithmetic, so no Pro call happens here at
    all. Net-effect discipline decides the bucket: a mixed/uncertain net
    (including a merely RELATIVE beneficiary) lands in neutral_mixed, never
    in the winners column."""
    companies = list(state.companies.values())
    if not companies:
        return []
    companies.sort(key=lambda c: (c.impact_strength, c.materiality or 0.0, c.confidence, c.ticker),
                   reverse=True)
    ranking = []
    for company in companies:
        net = company.net_direction or company.direction
        if net in ("mixed", "uncertain", "neutral"):
            bucket = "neutral_mixed"
        elif net == "bullish":
            bucket = "beneficiary"
        else:
            bucket = "adversely_affected"
        if company.relative_beneficiary and net not in ("bullish",):
            bucket = "neutral_mixed"
        ranking.append({"ticker": company.ticker, "bucket": bucket, "rank_reason": None})
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

    # Event-size triage (cost-target work 2026-08-11): DETERMINISTIC and
    # free -- the facts stage already classified event_type. Broad macro
    # types keep the deep graph the quality spec demands; everything else
    # (most pulse items) runs a small graph under tight token ceilings.
    from app.config import IMPACT_BROAD_EVENT_TYPES, IMPACT_TRIAGE_TIERS

    tier = "broad" if facts.event_type in IMPACT_BROAD_EVENT_TYPES else "narrow"
    tier_caps = IMPACT_TRIAGE_TIERS[tier]
    budget.max_input_override = tier_caps["max_input_tokens"]
    budget.max_output_override = tier_caps["max_output_tokens"]
    logger.info("impact-graph triage article=%s tier=%s event_type=%s caps=%s",
                article_id, tier, facts.event_type, tier_caps)

    state = _GraphState()

    try:
        if tier == "narrow" and settings.impact_narrow_single_call:
            _narrow_single_call(router, session, facts, state, budget, article_id)
        else:
            _build_graph(router, session, facts, state, budget, article_id,
                         max_depth=tier_caps["max_depth"] or settings.max_causal_depth,
                         max_expansions=tier_caps["max_expansions"] or MAX_EXPANSIONS_PER_ARTICLE,
                         completeness_rounds=tier_caps.get("completeness_rounds", 0))
    except Exception as exc:  # noqa: BLE001 -- never-fail contract (2026-08-11)
        # A crash AFTER real work exists must not throw that work away: if
        # any companies or edges were produced, ship them marked degraded
        # instead of failing the whole alert. Only a crash with NOTHING to
        # show propagates -- the retry path then replays completed stages
        # free via the stage cache.
        if not state.companies and not state.edges:
            raise
        logger.exception("impact-graph crashed mid-run for article=%s; shipping partial graph", article_id)
        router.quality = "degraded" if router.quality == "authoritative" else router.quality

    ranking = _rank(state) if state.companies else []
    state.metrics["companies_retained"] = len(state.companies)

    logger.info("impact-graph article=%s: %s nodes, %s edges, %s companies, budget=%s metrics=%s",
                article_id, len(state.nodes), len(state.edges), len(state.companies),
                budget.summary(), state.metrics)

    return ImpactGraphResult(
        category=facts.category, event_type=facts.event_type,
        event_cause=facts.event_cause, facts=facts.facts,
        event_label=facts.event, named_entities=list(facts.named_entities or []),
        companies=list(state.companies.values()),
        edges=state.edges, gaps=state.gaps, ranking=ranking,
        analysis_provider=router.provider, analysis_quality=router.quality,
        metrics=dict(state.metrics),
    )


def _narrow_single_call(router: StageRouter, session, facts: EventFacts,
                        state: _GraphState, budget: ArticleBudget,
                        article_id: int | None) -> None:
    """Narrow-tier consolidated path (2026-08-11): ONE graph call (shocks +
    depth<=2 edges + channel audit) and ONE batched companies call replace
    the staged loop -- validated manually via the v2.1 anti-omission
    prompt. Every deterministic rail stays identical: _register_edge
    normalization/dedup/thresholds, candidate grounding with ticker enums,
    net-effect discipline, deterministic ranking. Verification escalates
    RISK-BASED: an independent verify call fires only when the result
    carries high-impact / low-confidence / many companies; otherwise the
    in-call self-check stands (and no exposure-cache rows are written --
    the cache only ever learns from independently verified results)."""
    from app.analysis.impact_graph.schemas import SCHEMA_NARROW_GRAPH, schema_companies_batched

    raw = router.call(
        "narrow_graph", schema=SCHEMA_NARROW_GRAPH,
        static_prefix=prompts.static_prefix(prompts.NARROW_GRAPH_PROMPT),
        dynamic_suffix=_facts_suffix(facts),
        compact_suffix=_compact_suffix(facts),
        max_output_tokens=4096,
    )
    for shock in raw.get("shocks", []):
        edge = GraphEdge(
            parent_type="event", parent_id=EVENT_NODE_ID, child_type="economic_node",
            child_id=str(shock.get("shock_id") or shock.get("label", "shock")),
            direction=shock.get("direction", "neutral"), mechanism=shock.get("mechanism", ""),
            impact_strength=shock.get("impact_strength", 0.5),
            confidence=shock.get("confidence", 0.0), materiality=shock.get("materiality", 0.5),
            time_horizon=shock.get("time_horizon", "Short-Term"),
        )
        if _register_edge(state, edge):
            node = _node_from_edge(edge, shock.get("label"), None)
            state.nodes[node.node_id] = node
    # Two passes so an edge whose parent arrives later in the list still
    # registers -- the graph is at most depth 2 here.
    pending_edges = list(raw.get("edges", []))
    for _ in range(2):
        remaining = []
        for raw_edge in pending_edges:
            try:
                edge = GraphEdge(**{k: v for k, v in raw_edge.items() if k in GraphEdge.model_fields})
            except ValidationError:
                continue
            if _register_edge(state, edge):
                node = _node_from_edge(edge, raw_edge.get("child_label"), raw_edge.get("child_sector"))
                state.nodes[node.node_id] = node
            else:
                remaining.append(raw_edge)
        pending_edges = remaining
        if not pending_edges:
            break

    # Batched company mapping: one call covering every sector node.
    sector_nodes = [n for n in state.nodes.values() if n.sector is not None]
    subjects = _subject_companies(session, facts) if session is not None else []
    if session is None or (not sector_nodes and not subjects):
        _skip("narrow_companies", "no_sector_nodes_no_subjects", article=article_id)
        return
    node_blocks, union_tickers, node_by_id = [], [], {}
    placed_subjects = set()
    for node in sector_nodes:
        state.evaluated_nodes.add(node.node_id)
        candidates = candidate_companies(session, [node.sector])
        for subject in subjects:
            if subject.sector == node.sector and all(c.ticker != subject.ticker for c in candidates):
                candidates.insert(0, subject)
                placed_subjects.add(subject.ticker)
        candidates = [c for c in candidates if c.ticker not in state.rejected_tickers]
        tickers_to_ids = {c.ticker: c.id for c in candidates}
        cached_positive, cached_negative = _exposure_cache(session, node.node_id, tickers_to_ids)
        if cached_negative:
            _skip("narrow_companies", "negative_relationship_cache", node=node.node_id,
                  skipped=len(cached_negative))
            candidates = [c for c in candidates if c.ticker not in cached_negative]
        candidates = candidates[:MAX_CANDIDATES_PER_CALL]
        if not candidates:
            continue
        node_by_id[node.node_id] = node
        union_tickers.extend(c.ticker for c in candidates if c.ticker not in union_tickers)
        parent_edge = next((e for e in state.edges if e.child_id == node.node_id), None)
        node_blocks.append(
            f"NODE {node.node_id} (distance {node.distance}, "
            f"{parent_edge.direction if parent_edge else 'n/a'}): "
            f"{parent_edge.mechanism if parent_edge else facts.event}\n"
            + _candidate_profile_lines(candidates, cached_positive)
        )
    # Subjects whose sector has no node of its own still must be
    # selectable -- the article is ABOUT them (the ideaForge case: a
    # small-cap infra-classified drone maker whose story built it/defense
    # nodes). They ride a dedicated block; the model maps them to the most
    # causally relevant node via parent_id.
    stray_subjects = [s for s in subjects if s.ticker not in placed_subjects
                      and s.ticker not in state.rejected_tickers]
    if stray_subjects:
        # A single-stock story often builds a shocks-only graph (no sector
        # nodes -- measured live: ideaForge's downgrade). The article's own
        # subjects must still be evaluable: the distance-1 shock nodes
        # become valid parents.
        if not node_by_id:
            for node in state.nodes.values():
                if node.distance == 1:
                    node_by_id[node.node_id] = node
        if node_by_id:
            union_tickers.extend(s.ticker for s in stray_subjects if s.ticker not in union_tickers)
            shock_lines = "\n".join(
                f"NODE {n.node_id} (distance {n.distance}): {n.label}" for n in node_by_id.values()
            )
            node_blocks.append(
                f"{shock_lines}\n\n" if not sector_nodes else ""
            )
            node_blocks.append(
                "ARTICLE SUBJECT COMPANIES (named by the article itself -- evaluate "
                "each against the most causally relevant node above). For a "
                "company-specific event (downgrade, earnings, order win, management "
                "change), the subject company is normally MATERIALLY AFFECTED by its "
                "own event -- include it with the event's direction and forward-looking "
                "mechanism unless the effect is genuinely neutral:\n"
                + _candidate_profile_lines(stray_subjects, {})
            )
    if not node_blocks:
        _skip("narrow_companies", "no_candidates", article=article_id)
        return

    raw_companies = router.call(
        "narrow_companies",
        schema=schema_companies_batched(union_tickers, list(node_by_id)),
        static_prefix=prompts.static_prefix(prompts.NARROW_COMPANIES_PROMPT),
        dynamic_suffix=_compact_suffix(facts, extra="\n\n".join(node_blocks)),
        compact_suffix=_compact_suffix(facts, extra="\n\n".join(node_blocks[:2])),
    )
    allowed = set(union_tickers)
    for entry in raw_companies.get("companies", []):
        ticker = entry.get("ticker")
        node = node_by_id.get(entry.get("parent_id") or "")
        if ticker not in allowed or node is None:
            logger.warning("narrow single-call dropped entry ticker=%r parent=%r",
                           ticker, entry.get("parent_id"))
            continue
        try:
            company = GraphCompany(
                **{**entry, "causal_distance": node.distance,
                   "parent_type": node.node_type, "parent_id": node.node_id},
            ).clamp()
        except ValidationError as exc:
            logger.warning("narrow single-call company rejected by schema: %s", exc)
            continue
        state.metrics["companies_considered"] += 1
        # DISCOVERY floor only here; the strict distance thresholds -- and
        # mixed/uncertain survival handling -- run in the final prune below.
        if not _passes_discovery(company.materiality or 0.0, company.confidence):
            state.rejected_tickers.add(ticker)
            continue
        company.verified = True  # in-call self-check; independent verify below when risky
        held = state.companies.get(ticker)
        if held is None or company.impact_strength > held.impact_strength:
            state.companies[ticker] = company

    # FINAL materiality pruning (spec §15): strict thresholds once, after
    # all discovery. Mixed/uncertain gate on materiality only.
    state.metrics["nodes_discovered"] = len(state.nodes)
    _final_materiality_prune(state)

    # Deterministic subject fallback (2026-08-12): a single-stock story
    # whose mapping call returned nothing must not ship an invisible
    # zero-company alert -- the article NAMING the company is a fact, not a
    # model opinion. The subject persists with modest scores; the
    # measurement layer then overwrites direction with the REAL market
    # move (its established job), so nothing here fabricates a call.
    if not state.companies and subjects:
        top_shock = next((e for e in state.edges if e.parent_id == EVENT_NODE_ID), None)
        for subject in subjects[:3]:
            state.companies[subject.ticker] = GraphCompany(
                ticker=subject.ticker, name=subject.name,
                direction=top_shock.direction if top_shock and top_shock.direction != "neutral" else "bearish",
                impact_strength=0.4, confidence=0.6, materiality=0.45,
                causal_distance=1, time_horizon="Short-Term",
                parent_type="event", parent_id=EVENT_NODE_ID,
                mechanism=(top_shock.mechanism if top_shock else facts.event)[:200],
                rationale="Named subject of this article; direction reflects the measured market reaction.",
                net_direction="uncertain", verified=False,
            )
        _skip("narrow_companies", "subject_fallback_persisted", count=len(state.companies))

    # Risk-based escalation (token-opt spec P18): independent verification
    # when the result is large, high-impact, or shaky. Strict mode (spec
    # §5, INV-005) never trusts the in-call self-check: verification is
    # mandatory for every result, and its absence is recorded so the
    # publication gate fails closed instead of silently displaying.
    companies = list(state.companies.values())
    risky = (
        len(companies) > 8
        or any(c.impact_strength >= 0.7 for c in companies)
        or any(c.confidence < 0.6 for c in companies)
        or any(c.causal_distance >= 3 for c in companies)
    )
    if settings.impact_engine_v4_strict:
        risky = True
    if companies and risky:
        for company in companies:
            company.verified = False
        if budget.exceeded:
            # Symmetric with the broad path's hard-overrun branch below
            # (spec §5, INV-005/016): a risky result that needed
            # independent verification but ran out of budget for it is
            # exactly as unverified as a verifier outage. Both signals are
            # recorded -- the metric for the "why", router.quality for the
            # ImpactGraphResult.analysis_quality the gate actually reads --
            # so REJECT_VALIDATOR_UNAVAILABLE fires the same way it would if
            # the verifier call itself had raised.
            state.metrics["verification_unavailable"] = 1
            router.quality = "budget_exhausted"
            logger.warning(
                "impact-graph narrow-path hard budget overrun skipped verification "
                "at article=%s: %s", article_id, budget.summary())
        else:
            _verify_companies(router, session, facts, state, alert_id=article_id)


def _build_graph(router: StageRouter, session, facts: EventFacts,
                 state: _GraphState, budget: ArticleBudget, article_id: int | None,
                 max_depth: int | None = None, max_expansions: int | None = None,
                 completeness_rounds: int = 0) -> None:
    max_depth = max_depth or settings.max_causal_depth
    max_expansions = max_expansions or MAX_EXPANSIONS_PER_ARTICLE
    # Stage 2 -- initial shocks + distance-1 nodes (the graph anchor). The
    # schema now forces a channel_audit: every ontology channel classified,
    # so first-order coverage is systematic, not the model's first ideas.
    raw_shocks = router.call(
        "initial_shocks", schema=SCHEMA_SHOCKS,
        static_prefix=prompts.static_prefix(prompts.SHOCKS_PROMPT),
        dynamic_suffix=_facts_suffix(facts),
        compact_suffix=_facts_suffix(EventFacts(**{**facts.model_dump(), "article_evidence": []})),
    )
    frontier: list[_Node] = []
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

    # Knowledge architecture (cost-opt spec P5/P6): a matched event
    # archetype maps its mechanism slice FIRST -- deterministic candidate
    # universes + mechanism priors, small medium-thinking calls. Trigger
    # shocks covered by the archetype are marked expanded so generic ripple
    # discovery does not re-buy the same universe. No match, or the flag
    # off -> the dynamic path below runs exactly as before.
    from app.config import IMPACT_KNOWLEDGE_MODE

    if IMPACT_KNOWLEDGE_MODE and session is not None:
        from app.analysis.impact_graph.knowledge import match_event_archetype

        match = match_event_archetype(facts)
        if match is not None:
            _archetype_mapping(router, session, facts, state, budget, article_id,
                               match[0], match[1])

    # Stage 3 -- direct companies for every distance-1 node with candidates.
    for node in list(frontier):
        if budget.expansion_exhausted:
            break
        _map_companies_for_node(router, session, facts, state, node)

    # Stages 4/5/6 -- recursive frontier expansion.
    _expand_frontier(router, session, facts, state, budget, article_id,
                     frontier, max_depth, max_expansions)

    # Completeness audit + missing-branch expansion (spec §13/§14): assume
    # the graph is incomplete, actively search for omitted branches, feed
    # what is found back into the SAME expansion machinery. Rounds are
    # config-bounded and stop early when an audit finds nothing new.
    for _ in range(max(0, completeness_rounds)):
        if budget.expansion_exhausted:
            _skip("completeness_audit", "budget_soft_stop", article=article_id)
            break
        state.metrics["completeness_rounds_run"] += 1
        new_nodes = _completeness_audit(router, session, facts, state, article_id)
        if not new_nodes:
            break
        for node in new_nodes:
            if budget.expansion_exhausted:
                break
            _map_companies_for_node(router, session, facts, state, node)
        _expand_frontier(router, session, facts, state, budget, article_id,
                         list(new_nodes), max_depth, max_expansions)

    # FINAL materiality pruning (spec §15) -- the strict distance-scaled
    # thresholds run exactly once, here, after completeness. Deterministic,
    # zero-cost, and BEFORE LLM verification so verification tokens are not
    # spent on prunable branches.
    state.metrics["nodes_discovered"] = len(state.nodes)
    _final_materiality_prune(state)

    # Stage 7/8 -- verification runs out of the reserved budget slice; only
    # a HARD overrun (past 100%) skips it, and ONLY that skip marks the
    # analysis budget_exhausted (an unverified recall set is genuinely a
    # lower-quality artifact; a soft-stopped-but-verified graph is not).
    if not budget.exceeded:
        _verify_companies(router, session, facts, state, alert_id=article_id)
        _verify_edges(router, facts, state)
    else:
        router.quality = "budget_exhausted"
        logger.warning("impact-graph hard budget overrun skipped verification at article=%s: %s",
                       article_id, budget.summary())


def _expand_frontier(router: StageRouter, session, facts: EventFacts,
                     state: _GraphState, budget: ArticleBudget, article_id: int | None,
                     frontier: list, max_depth: int, max_expansions: int) -> None:
    """Recursive one-hop expansion of a frontier. PRIORITY-ordered: the
    strongest (materiality x confidence) node expands first, so expansion
    caps trim the weakest tail, never an arbitrary FIFO tail. RELATED
    frontier nodes (same parent, same distance) are batched into one call,
    up to MAX_FRONTIER_BATCH -- never a giant whole-graph request
    (token-opt P15: the bundling-regression lesson stands). Soft budget
    (75%) gates expansion so the reserve always covers verification.
    Expansion eligibility uses the DISCOVERY floor -- strict thresholds
    only apply at final pruning."""
    while frontier:
        if budget.expansion_exhausted:
            logger.info("impact-graph expansion soft-stopped at article=%s: %s",
                        article_id, budget.summary())
            break
        frontier.sort(key=lambda n: (n.materiality * n.confidence, -n.distance))
        node = frontier.pop()
        if node.node_id in state.expanded:
            _skip("ripple_discovery", "already_expanded", node=node.node_id)
            continue
        if node.distance >= max_depth:
            _skip("ripple_discovery", "max_depth", node=node.node_id, cap=max_depth)
            continue
        if not _passes_discovery(node.materiality, node.confidence):
            _skip("ripple_discovery", "below_discovery_floor", node=node.node_id,
                  materiality=round(node.materiality, 2), confidence=round(node.confidence, 2))
            continue  # dead branch: no LLM call
        # Controlled depth (breadth-without-depth directive 2026-08-12):
        # only MAJOR branches deepen past distance 2 -- a node at d>=3 must
        # already clear its FINAL distance thresholds to earn an expansion
        # call. Depth is not the objective; materiality > causal depth.
        if node.distance >= 3 and not _passes(node.distance, node.materiality, node.confidence):
            _skip("ripple_discovery", "not_major_enough_to_deepen", node=node.node_id,
                  distance=node.distance, materiality=round(node.materiality, 2))
            continue
        if state.expansions >= max_expansions:
            _skip("ripple_discovery", "expansion_cap", node=node.node_id, cap=max_expansions)
            break

        # Gather same-parent siblings for one batched call.
        batch = [node]
        parent_of = {e.child_id: e.parent_id for e in state.edges}
        for sibling in list(frontier):
            if len(batch) >= MAX_FRONTIER_BATCH:
                break
            if (sibling.distance == node.distance
                    and parent_of.get(sibling.node_id) == parent_of.get(node.node_id)
                    and sibling.node_id not in state.expanded
                    and _passes_discovery(sibling.materiality, sibling.confidence)):
                frontier.remove(sibling)
                batch.append(sibling)
        for member in batch:
            state.expanded.add(member.node_id)
        state.expansions += 1

        batch_ids = [m.node_id for m in batch]
        node_lines = "\n".join(
            f"- id: {m.node_id} ({m.node_type}), causal distance {m.distance}\n"
            f"  path: {_ancestor_path(state, m)}"
            for m in batch
        )
        existing_ids = ", ".join(sorted(state.nodes))
        suffix = _compact_suffix(
            facts,
            extra=(
                f"FRONTIER NODES (expand each exactly one hop):\n{node_lines}\n\n"
                f"Node ids already in the graph (do not repeat): {existing_ids}\n"
                f"Every child's parent_id must be one of: {', '.join(batch_ids)}; "
                f"each child sits at its parent's distance + 1."
            ),
        )
        compact = _compact_suffix(
            facts,
            extra=(f"FRONTIER NODES: {', '.join(batch_ids)} (distance {node.distance}). "
                   f"Propose one-hop children; parent_id must be one of the frontier ids."),
        )
        try:
            raw = router.call(
                "ripple_discovery", schema=SCHEMA_RIPPLE,
                static_prefix=prompts.static_prefix(prompts.RIPPLE_PROMPT),
                dynamic_suffix=suffix, compact_suffix=compact,
                context={"parent_node": ",".join(batch_ids)},
            )
        except StageRouterError as exc:
            state.gaps.append({"sector": node.sector or node.node_id,
                               "impact_level": _legacy_level(node.distance + 1),
                               "parent_ticker": None, "attempts": 4, "last_error": str(exc)[:500]})
            continue

        from app.analysis.impact_graph.normalize import normalize_node_id

        for raw_edge in raw.get("children", []):
            try:
                edge = GraphEdge(**{k: v for k, v in raw_edge.items() if k in GraphEdge.model_fields})
            except ValidationError:
                continue
            # Normalize BEFORE the membership check -- the model may name
            # the parent with a synonym of the canonical node id.
            if edge.parent_id != EVENT_NODE_ID and edge.parent_type not in ("company", "sector"):
                edge.parent_id = normalize_node_id(edge.parent_id)
            # The model must chain from a batched frontier node -- a child
            # claiming a different parent is kept only if that parent
            # genuinely exists in the graph; otherwise dropped.
            if edge.parent_id not in batch_ids and edge.parent_id not in state.nodes \
                    and edge.parent_id != EVENT_NODE_ID:
                continue
            if _register_edge(state, edge):
                child = _node_from_edge(edge, raw_edge.get("child_label"), raw_edge.get("child_sector"))
                state.nodes[child.node_id] = child
                frontier.append(child)
                if not budget.expansion_exhausted:
                    _map_companies_for_node(router, session, facts, state, child)


# Channel -> node-vocabulary hints for the deterministic coverage matrix
# (cost-opt spec P13). A channel counts as COVERED when any graph node's id
# or label carries one of its tokens -- code decides coverage; Gemini is
# asked only about the channels code could not find.
_CHANNEL_NODE_HINTS: dict[str, list[str]] = {
    "demand": ["demand", "consumption", "spending", "purchas"],
    "supply": ["supply", "production", "output", "capacity"],
    "price": ["price", "pricing", "realization", "tariff"],
    "input_costs": ["cost", "input", "feedstock", "raw_material"],
    "margins": ["margin", "spread", "profitab"],
    "financing": ["financ", "funding", "borrow", "capital"],
    "credit_quality": ["credit", "asset_quality", "npa", "default"],
    "interest_rates": ["rate", "repo", "yield", "monetary"],
    "currency_fx": ["currency", "rupee", "fx", "exchange", "dollar"],
    "imports": ["import"],
    "exports": ["export"],
    "trade_flows": ["trade", "shipping", "freight", "route"],
    "substitution": ["substitut", "alternative", "switch", "relative"],
    "competition": ["competit", "market_share"],
    "capex": ["capex", "investment", "expansion"],
    "inventory": ["inventory", "stock", "working_capital"],
    "employment": ["employment", "unemploy", "job", "wage", "income"],
    "regulation": ["regulat", "policy", "compliance"],
    "fiscal_policy": ["fiscal", "budget", "subsid", "government_spending"],
    "monetary_policy": ["monetary", "rbi", "central_bank", "inflation"],
    "consumer_behavior": ["consumer", "household", "discretionary", "sentiment"],
    "government_response": ["government", "intervention", "response"],
}


def _coverage_matrix(state: _GraphState) -> tuple[list[str], list[str]]:
    """(covered, missing) channels, decided deterministically from the
    graph's node vocabulary -- zero LLM cost."""
    haystack = " ".join(
        f"{node_id} {node.label}".lower().replace(" ", "_")
        for node_id, node in state.nodes.items()
    )
    covered, missing = [], []
    for channel, hints in _CHANNEL_NODE_HINTS.items():
        (covered if any(h in haystack for h in hints) else missing).append(channel)
    return covered, missing


def _completeness_audit(router: StageRouter, session, facts: EventFacts,
                        state: _GraphState, article_id: int | None) -> list:
    """One audit round (spec §13): an ACTIVE search for missing branches.
    Deterministic-first (cost-opt P13): code builds the coverage matrix and
    Gemini is asked ONLY about the channels code found missing -- never the
    whole ontology against the whole graph. All channels covered = no call
    at all. Accepted branches become real nodes and are returned so the
    caller can re-enter them into the frontier."""
    from app.analysis.impact_graph.normalize import normalize_node_id
    from app.analysis.impact_graph.schemas import SCHEMA_COMPLETENESS

    covered, missing = _coverage_matrix(state)
    if not missing:
        _skip("completeness_audit", "coverage_matrix_complete", article=article_id)
        return []
    company_line = ", ".join(sorted(state.companies)) or "(none yet)"
    suffix = _compact_suffix(
        facts,
        extra=(
            f"CURRENT GRAPH:\n{_graph_outline(state, limit=60)}\n\n"
            f"COMPANIES ALREADY MAPPED: {company_line}\n\n"
            f"CHANNELS ALREADY COVERED (deterministic audit -- do NOT re-propose): "
            f"{', '.join(covered)}\n"
            f"INVESTIGATE ONLY THESE MISSING CHANNELS (propose a branch only where "
            f"one is genuinely, materially relevant to THIS event): {', '.join(missing)}\n\n"
            f"Existing node ids (propose only branches NOT already represented): "
            f"{', '.join(sorted(state.nodes))}"
        ),
    )
    try:
        raw = router.call(
            "completeness_audit", schema=SCHEMA_COMPLETENESS,
            static_prefix=prompts.static_prefix(prompts.COMPLETENESS_PROMPT),
            dynamic_suffix=suffix,
        )
    except StageRouterError as exc:
        logger.warning("impact-graph completeness audit unavailable for article=%s: %s",
                       article_id, exc)
        return []

    new_nodes = []
    for raw_branch in raw.get("missing_branches", []):
        try:
            edge = GraphEdge(**{k: v for k, v in raw_branch.items()
                                if k in GraphEdge.model_fields})
        except ValidationError:
            continue
        if edge.parent_id != EVENT_NODE_ID and edge.parent_type not in ("company", "sector"):
            edge.parent_id = normalize_node_id(edge.parent_id)
        if edge.parent_id != EVENT_NODE_ID and edge.parent_id not in state.nodes:
            continue  # a missing branch must hang off the real graph
        if _register_edge(state, edge):
            node = _node_from_edge(edge, raw_branch.get("child_label"),
                                   raw_branch.get("child_sector"))
            state.nodes[node.node_id] = node
            new_nodes.append(node)
            state.metrics["completeness_branches_found"] += 1
    logger.info("impact-graph completeness_audit article=%s found=%s",
                article_id, len(new_nodes))
    return new_nodes
