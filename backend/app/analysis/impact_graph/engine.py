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
    thresholds = impact_thresholds_for_distance(distance)
    return materiality >= thresholds["materiality"] and confidence >= thresholds["confidence"]


def _register_edge(state: _GraphState, edge: GraphEdge) -> bool:
    """Deterministic edge gate: schema-valid types, real parent, no dupes,
    no cycles (a child that already exists at <= parent distance is a
    back-edge), thresholds for its distance. Returns True when persisted.

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

def _candidate_profile_lines(candidates, cached_by_ticker: dict) -> str:
    """Compact exposure-profile lines (token-opt P8): ticker | name |
    sub_sector | clipped business line -- never the full biography. A
    cached BASE EXPOSURE replaces the generic description entirely: the
    model gets the verified mechanism instead of rediscovering it."""
    lines = []
    for c in candidates:
        cached = cached_by_ticker.get(c.ticker)
        if cached is not None:
            lines.append(f"- {c.ticker} ({c.name}) [KNOWN BASE EXPOSURE, verified: "
                         f"{(cached.mechanism or 'exposure confirmed')[:90]}] "
                         f"-- judge THIS event's specific effect; you may override if this event changes the relationship")
            continue
        seg = f" | {c.sub_sector}" if c.sub_sector else ""
        desc = f" | {c.business_desc[:60]}" if getattr(c, "business_desc", None) else ""
        lines.append(f"- {c.ticker} ({c.name}){seg}{desc}")
    return "\n".join(lines)


def _exposure_cache(session, node_key: str, tickers_to_ids: dict) -> tuple[dict, set]:
    """(positive rows by ticker, negatively-cached tickers) for one
    normalized node -- rows older than the company's own metadata are
    ignored (stale-invalidation, token-opt P10)."""
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
        company = row.company
        meta_as_of = getattr(company, "business_desc_as_of", None)
        if meta_as_of is not None and row.verified_at is not None:
            verified = row.verified_at.date() if hasattr(row.verified_at, "date") else row.verified_at
            if meta_as_of > verified:
                continue  # stale -- company metadata changed since verification
        if row.exposure_exists:
            positive[ticker] = row
        else:
            negative.add(ticker)
    return positive, negative


def _map_companies_for_node(router: StageRouter, session, facts: EventFacts,
                            state: _GraphState, node: _Node) -> None:
    """Stage 3 (distance 1) / stage 5 (ripples): candidate-grounded company
    mapping for one graph node. Deterministic no-call gates run first and
    every skip is logged (token-opt P4)."""
    if node.node_id in state.evaluated_nodes:
        _skip("map_companies", "node_already_evaluated", node=node.node_id)
        return
    state.evaluated_nodes.add(node.node_id)
    if session is None or node.sector is None:
        return  # companies attach where a sector pool exists; economic nodes fan into sector children
    candidates = candidate_companies(session, [node.sector])
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
        # Net-effect discipline: an unresolved net effect never ships as a
        # confident directional call (token-opt P12).
        if company.net_direction in ("mixed", "uncertain"):
            company.confidence = min(company.confidence, 0.55)
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

# Reject reasons that indicate a STRUCTURAL (event-independent) absence of
# exposure -- only these write a negative relationship-cache row. An
# event-specific rejection ("immaterial for this event") must never poison
# a future event's recall (token-opt P10 recall protection).
_STRUCTURAL_REJECT_MARKERS = (
    "no exposure", "no material exposure", "does not operate", "false premise",
    "not exposed", "no business", "does not have", "no such exposure",
)


def _verify_companies(router: StageRouter, session, facts: EventFacts,
                      state: _GraphState, alert_id: int | None = None) -> None:
    """Diff-contract verification (token-opt P17): the verifier returns
    accept[]/reject[]/corrections{} and code applies them. Companies whose
    (node, ticker) relationship is already cache-verified with the same
    direction are auto-accepted deterministically and never re-sent."""
    companies = list(state.companies.values())
    if not companies:
        return

    # Deterministic pre-verification via the relationship cache.
    to_verify = []
    auto_accepted = 0
    for company in companies:
        cached = _cached_positive_for(session, company)
        if cached is not None and (cached.strength or 0) > 0 and company.direction != "neutral":
            company.verified = True
            auto_accepted += 1
        else:
            to_verify.append(company)
    if auto_accepted:
        _skip("verify_companies", "relationship_cache_auto_accept", count=auto_accepted)
    if not to_verify:
        return

    tickers = [c.ticker for c in to_verify]
    listing = "\n".join(
        f"- {c.ticker} ({c.name}) d{c.causal_distance} {c.direction} net={c.net_direction or '-'} "
        f"impact={c.impact_strength:.2f} conf={c.confidence:.2f} mat={c.materiality:.2f} "
        f"parent={c.parent_type}:{c.parent_id} :: {c.mechanism[:140]}"
        for c in to_verify
    )
    suffix = _compact_suffix(facts, extra=f"PROPOSED COMPANIES:\n{listing}")
    try:
        raw = router.call(
            "verify_companies", schema=schema_company_verdicts(tickers),
            static_prefix=prompts.static_prefix(prompts.VERIFY_COMPANIES_PROMPT),
            dynamic_suffix=suffix,
        )
    except StageRouterError as exc:
        logger.warning("impact-graph company verification unavailable, keeping recall set: %s", exc)
        return

    accepted = {t for t in raw.get("accept", []) if t in state.companies}
    for rejection in raw.get("reject", []):
        ticker = rejection.get("ticker")
        company = state.companies.pop(ticker, None)
        if company is None:
            continue
        state.rejected_tickers.add(ticker)
        reason = (rejection.get("reason") or "").lower()
        if session is not None and any(marker in reason for marker in _STRUCTURAL_REJECT_MARKERS):
            _write_exposure_cache(session, company, exposure_exists=False, alert_id=alert_id)
    for correction in raw.get("corrections", []) or []:
        company = state.companies.get(correction.get("ticker"))
        if company is None:
            continue
        direction = correction.get("direction")
        if direction in ("bullish", "bearish", "neutral"):
            company.direction = direction
        distance = correction.get("causal_distance")
        if isinstance(distance, int) and 1 <= distance <= settings.max_causal_depth:
            company.causal_distance = distance
        for field in ("materiality", "confidence"):
            value = correction.get(field)
            if isinstance(value, (int, float)):
                setattr(company, field, max(0.0, min(1.0, float(value))))
    for ticker in accepted:
        state.companies[ticker].verified = True
    # A company with neither verdict is KEPT (omission is not rejection).
    # Positive relationships from verified companies feed the cache.
    if session is not None:
        for company in state.companies.values():
            if company.verified:
                _write_exposure_cache(session, company, exposure_exists=True, alert_id=alert_id)


def _cached_positive_for(session, company: GraphCompany):
    from app.models import Company as CompanyRow, CompanyNodeExposure

    if session is None:
        return None
    row = session.query(CompanyRow).filter_by(ticker=company.ticker).one_or_none()
    if row is None:
        return None
    return (
        session.query(CompanyNodeExposure)
        .filter_by(company_id=row.id, node_key=company.parent_id, exposure_exists=1)
        .one_or_none()
    )


def _write_exposure_cache(session, company: GraphCompany, *, exposure_exists: bool,
                          alert_id: int | None) -> None:
    """Upsert one (company, node) relationship row. BASE exposure only:
    mechanism is the company-level channel, never the event narrative."""
    from app.models import Company as CompanyRow, CompanyNodeExposure, utcnow

    row = session.query(CompanyRow).filter_by(ticker=company.ticker).one_or_none()
    if row is None:
        return
    existing = (
        session.query(CompanyNodeExposure)
        .filter_by(company_id=row.id, node_key=company.parent_id)
        .one_or_none()
    )
    if existing is None:
        session.add(CompanyNodeExposure(
            company_id=row.id, node_key=company.parent_id,
            exposure_exists=1 if exposure_exists else 0,
            strength=company.impact_strength if exposure_exists else None,
            mechanism=company.mechanism[:300] if exposure_exists else None,
            verified_at=utcnow(), source_alert_id=alert_id,
        ))
    else:
        existing.exposure_exists = 1 if exposure_exists else 0
        existing.strength = company.impact_strength if exposure_exists else None
        existing.mechanism = company.mechanism[:300] if exposure_exists else existing.mechanism
        existing.verified_at = utcnow()
        existing.source_alert_id = alert_id


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
    companies.sort(key=lambda c: (c.impact_strength, c.materiality, c.confidence, c.ticker),
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

    state = _GraphState()

    try:
        _build_graph(router, session, facts, state, budget, article_id)
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

    logger.info("impact-graph article=%s: %s nodes, %s edges, %s companies, budget=%s",
                article_id, len(state.nodes), len(state.edges), len(state.companies),
                budget.summary())

    return ImpactGraphResult(
        category=facts.category, event_type=facts.event_type, facts=facts.facts,
        event_label=facts.event, companies=list(state.companies.values()),
        edges=state.edges, gaps=state.gaps, ranking=ranking,
        analysis_provider=router.provider, analysis_quality=router.quality,
    )


def _build_graph(router: StageRouter, session, facts: EventFacts,
                 state: _GraphState, budget: ArticleBudget, article_id: int | None) -> None:
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

    # Stages 4/5/6 -- recursive frontier expansion. RELATED frontier nodes
    # (same parent, same distance) are batched into one call, up to
    # MAX_FRONTIER_BATCH -- never a giant whole-graph request (token-opt
    # P15: the bundling-regression lesson stands; only overlapping-context
    # siblings share a call). Soft budget (75%) gates expansion so the
    # reserve always covers verification + ranking.
    while frontier:
        if budget.expansion_exhausted:
            logger.info("impact-graph expansion soft-stopped at article=%s: %s",
                        article_id, budget.summary())
            break
        node = frontier.popleft()
        if node.node_id in state.expanded:
            _skip("ripple_discovery", "already_expanded", node=node.node_id)
            continue
        if node.distance >= settings.max_causal_depth:
            _skip("ripple_discovery", "max_depth", node=node.node_id)
            continue
        if not _passes(node.distance, node.materiality, node.confidence):
            _skip("ripple_discovery", "below_thresholds", node=node.node_id,
                  materiality=round(node.materiality, 2), confidence=round(node.confidence, 2))
            continue  # dead branch: no LLM call
        if state.expansions >= MAX_EXPANSIONS_PER_ARTICLE:
            _skip("ripple_discovery", "expansion_cap", node=node.node_id)
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
                    and _passes(sibling.distance, sibling.materiality, sibling.confidence)):
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
