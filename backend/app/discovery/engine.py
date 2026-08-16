"""TASK 3.3 -- discovery rewritten as the four-source model (spec §6.3).

THE BUG THIS FIXES. V4 discovery was anchored on companies NAMED IN THE
ARTICLE, so a crude story surfaced refiners (mentioned) and never surfaced
paints or tyres (not mentioned, and exposed). Recall was being asked of a
language model's memory, which is invisible when it fails and unfixable when
it does.

THE FOUR SOURCES, in the order they run:

  MENTION       companies named in the article.
  MECHANISM     the recall fix. Walk the causal graph from each shock
                variable, and for every exposure tag it reaches, ask the
                exposure index which companies carry that tag above the
                threshold for that distance. No memory involved: if a
                company is tagged, it is found, every time.
  SUPPLY_CHAIN  one hop along sourced customer/supplier edges from the pool.
  PEER_CLOSURE  when an industry already has several members in the pool,
                sweep it for the peers the distance walk rejected.

FOUR SEPARATE FIELDS (invariant 4). A candidate records `discovery_source`
(HOW we found it), `via_tag` (WHICH exposure carried it), `mechanism_id`
(WHICH edge) and `graph_distance` (HOW FAR). It records NO `directness` and
NO tier: directness is a structural property of the causal path and the tier
is the gate's verdict, and neither is discovery's to decide. There is no
field on `Candidate` that fuses any two of them, and a test enforces that by
name.

THIS MODULE HOLDS NO THRESHOLD. Every number comes from
`config/discovery.yaml` through `app.discovery.config`; a test scans this
file for numeric literals.

IT WRITES NOTHING. A candidate is a value, not a record.
"""
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, Sequence

from sqlalchemy import text

from app.discovery.config import DiscoveryConfig, load_discovery_config
from app.discovery.index import query_exposure_index, query_exposure_index_many
from app.graph.traverse import reachable_tags, traverse

MENTION = "MENTION"
MECHANISM = "MECHANISM"
SUPPLY_CHAIN = "SUPPLY_CHAIN"
PEER_CLOSURE = "PEER_CLOSURE"

# Ordered strongest first. When two sources find the same company, the pool
# keeps the earlier one -- being named in the article is a stronger statement
# about why a company is here than being swept in with its peers.
SOURCE_PRECEDENCE = (MENTION, MECHANISM, SUPPLY_CHAIN, PEER_CLOSURE)


@dataclass(frozen=True)
class DiscoveryShock:
    """The economic variable an event moves. Deliberately minimal: discovery
    needs the variable and the sign to find candidates, and nothing else.
    Sizing the move is the sensitivity engine's job (Phase 2)."""
    shock_id: str
    variable: str
    sign: str                       # UP | DOWN
    magnitude_pct: float | None = None


@dataclass(frozen=True)
class DiscoveryEvent:
    """What discovery is given. `mentions` are the entity references the
    article contained -- tickers, ISINs or exact names -- NOT companies some
    stage decided were relevant."""
    event_id: str
    mentions: tuple[str, ...] = ()
    shocks: tuple[DiscoveryShock, ...] = ()


@dataclass(frozen=True)
class Candidate:
    company_id: int
    discovery_source: str
    via_tag: str | None
    mechanism_id: str | None
    graph_distance: int | None
    shock_id: str | None
    share_of_base: float | None
    # Ordering only. It ranks the pool so the bound cuts the least promising
    # names; it is never published, never stored, and never becomes a
    # materiality -- that is computed by the sensitivity engine from the
    # ledger (§5).
    expected_materiality_prior: float = 0.0

    def serialize(self) -> dict:
        return {
            "company_id": self.company_id,
            "discovery_source": self.discovery_source,
            "via_tag": self.via_tag,
            "mechanism_id": self.mechanism_id,
            "graph_distance": self.graph_distance,
            "shock_id": self.shock_id,
            "share_of_base": self.share_of_base,
            "expected_materiality_prior": self.expected_materiality_prior,
        }


@dataclass
class CandidatePool:
    """A bounded, de-duplicated, source-aware set of candidates.

    BOUNDED WHILE FILLING, not only on the way out. A pool that accumulates
    every row the index returns and slices at the end has an unbounded memory
    profile and hides a runaway from every test that inspects only the
    result, so `add` evicts as it goes and `size` never exceeds `max_size`.

    MENTIONS ALWAYS SURVIVE, and this is a deliberate deviation worth
    stating. A mention's prior is infinite, so it outranks every mechanism
    find and the eviction never reaches one: with a pool smaller than the
    mention count, the pool is all mentions. That is the intended trade --
    a company the article NAMES must not be dropped to make room for one the
    ledger inferred, because the reader can see the first kind is missing.
    The consequence, said plainly: an article naming more than
    `max_candidates_per_event` companies crowds out mechanism discovery
    entirely. No such article has been observed, and if one is, the fix is a
    per-source quota in the config, not a silent reordering here.
    """
    max_size: int
    _by_company: dict[int, Candidate] = field(default_factory=dict)
    unresolved_mentions: tuple[str, ...] = ()
    unmodelled_variables: tuple[str, ...] = ()

    @staticmethod
    def _rank_key(candidate: Candidate):
        """The total order the pool is kept in: strongest prior first, then
        source precedence, then company_id. Total, so discovery is
        deterministic."""
        return (-candidate.expected_materiality_prior,
                SOURCE_PRECEDENCE.index(candidate.discovery_source),
                candidate.company_id)

    @property
    def size(self) -> int:
        return len(self._by_company)

    def add(self, candidate: Candidate) -> None:
        existing = self._by_company.get(candidate.company_id)
        if existing is not None:
            if (SOURCE_PRECEDENCE.index(candidate.discovery_source)
                    < SOURCE_PRECEDENCE.index(existing.discovery_source)):
                self._by_company[candidate.company_id] = candidate
            elif (candidate.discovery_source == existing.discovery_source
                  and candidate.expected_materiality_prior
                  > existing.expected_materiality_prior):
                self._by_company[candidate.company_id] = candidate
            return

        self._by_company[candidate.company_id] = candidate
        if len(self._by_company) > self.max_size:
            weakest = max(self._by_company.values(), key=self._rank_key)
            del self._by_company[weakest.company_id]

    def extend(self, candidates: Iterable[Candidate]) -> None:
        for candidate in candidates:
            self.add(candidate)

    @property
    def candidates(self) -> tuple[Candidate, ...]:
        """The pool, ranked. It is already bounded -- `add` evicts."""
        return tuple(sorted(self._by_company.values(), key=self._rank_key))

    def serialize(self) -> list[dict]:
        return [candidate.serialize() for candidate in self.candidates]


# --- source 1: mentions -----------------------------------------------------

def resolve_mentions(session, mentions: Sequence[str], *,
                     as_of: date) -> tuple[list[int], list[str]]:
    """Article mentions to company ids, EXACTLY -- ticker, ISIN or exact
    name. Returns `(company_ids, unresolved)`.

    No fuzzy rung: a candidate resolved by string similarity is a candidate
    about a different company. An unresolved mention is REPORTED, not
    dropped silently and not guessed at.
    """
    resolved: list[int] = []
    unresolved: list[str] = []
    for mention in mentions:
        row = session.execute(text(
            "SELECT id FROM companies "
            "WHERE ticker = :m OR isin = :m OR name = :m "
            "ORDER BY id ASC"), {"m": mention}).fetchall()
        if len(row) == 1:
            resolved.append(int(row[0][0]))
        else:
            # zero matches, or an ambiguity -- either way this is not a
            # company we can name.
            unresolved.append(mention)
    return resolved, unresolved


# --- the prior --------------------------------------------------------------

def _prior(share_of_base: float | None, confidence: float | None,
           graph_distance: int | None) -> float:
    """A RANKING key, computed only from ledger fields that already exist.

    Bigger exposure ranks above smaller; a closer mechanism ranks above a
    remoter one; a better-sourced row ranks above a shakier one. It is not a
    materiality, it is not shown to anyone, and nothing downstream reads it.
    """
    if share_of_base is None:
        return 0.0
    distance = max(1, int(graph_distance or 1))
    return float(share_of_base) * float(confidence or 1.0) / distance


# --- the engine -------------------------------------------------------------

def discover(session, event: DiscoveryEvent, *, as_of: date,
             config: DiscoveryConfig | None = None) -> CandidatePool:
    config = config or load_discovery_config()
    pool = CandidatePool(max_size=config.max_candidates_per_event)

    # 1. MENTION -------------------------------------------------------------
    mentioned, unresolved = resolve_mentions(session, event.mentions, as_of=as_of)
    pool.unresolved_mentions = tuple(unresolved)
    for company_id in mentioned:
        pool.add(Candidate(company_id=company_id, discovery_source=MENTION,
                           via_tag=None, mechanism_id=None,
                           # A mention is not a graph path. Discovery does not
                           # know how far this company is from the shock and
                           # does not invent a number for it.
                           graph_distance=None, shock_id=None,
                           share_of_base=None,
                           expected_materiality_prior=float("inf")))

    # 2. MECHANISM -- the recall fix ----------------------------------------
    unmodelled: list[str] = []
    tag_edges: dict[str, tuple] = {}
    for shock in event.shocks:
        if not config.models(shock.variable):
            unmodelled.append(shock.variable)
            continue
        edges = traverse(session, shock.variable, as_of=as_of,
                         max_depth=config.max_depth)
        for tag, edge in reachable_tags(edges).items():
            threshold = config.threshold_for(edge.graph_distance)
            if threshold is None:
                continue
            tag_edges[tag] = (edge, shock)
            for row in query_exposure_index(session, tag, min_share=threshold,
                                            as_of=as_of):
                pool.add(Candidate(
                    company_id=int(row["company_id"]),
                    discovery_source=MECHANISM, via_tag=tag,
                    mechanism_id=edge.edge_id,
                    graph_distance=edge.graph_distance,
                    shock_id=shock.shock_id,
                    share_of_base=float(row["share_of_base"]),
                    expected_materiality_prior=_prior(
                        row["share_of_base"], row["confidence"],
                        edge.graph_distance)))
    pool.unmodelled_variables = tuple(dict.fromkeys(unmodelled))

    # 3. SUPPLY_CHAIN -- one hop from the pool ------------------------------
    _extend_supply_chain(session, pool)

    # 4. PEER_CLOSURE -- sweep an implicated industry -----------------------
    _extend_peer_closure(session, pool, tag_edges, config=config, as_of=as_of)

    return pool


def _extend_supply_chain(session, pool: CandidatePool) -> None:
    """Sourced counterparty edges (`supply_links`), one hop out.

    Only EXACTLY resolved counterparties are followed: a `supply_links` row
    whose `counterparty_company_id` is NULL means "no exact match", never
    "probably this one".
    """
    seeds = {c.company_id: c for c in pool.candidates}
    if not seeds:
        return
    placeholders = ", ".join(f":c{i}" for i in range(len(seeds)))
    parameters = {f"c{i}": company_id
                  for i, company_id in enumerate(sorted(seeds))}
    rows = session.execute(text(
        "SELECT company_id, counterparty_company_id FROM supply_links "
        f"WHERE counterparty_company_id IN ({placeholders}) "
        "   OR company_id IN (" + placeholders + ") "
        "ORDER BY id ASC"), parameters).mappings().all()

    for row in rows:
        left, right = int(row["company_id"]), row["counterparty_company_id"]
        if right is None:
            continue
        right = int(right)
        for seed_id, other in ((left, right), (right, left)):
            seed = seeds.get(seed_id)
            if seed is None or other in seeds:
                continue
            distance = (None if seed.graph_distance is None
                        else seed.graph_distance + 1)
            pool.add(Candidate(
                company_id=other, discovery_source=SUPPLY_CHAIN,
                via_tag=seed.via_tag, mechanism_id=seed.mechanism_id,
                graph_distance=distance, shock_id=seed.shock_id,
                share_of_base=None,
                expected_materiality_prior=_prior(
                    seed.share_of_base, None, distance)))


def _industry_of(session, company_ids: Sequence[int]) -> dict[int, str | None]:
    if not company_ids:
        return {}
    placeholders = ", ".join(f":c{i}" for i in range(len(company_ids)))
    parameters = {f"c{i}": cid for i, cid in enumerate(company_ids)}
    rows = session.execute(text(
        f"SELECT id, sub_sector, sector FROM companies WHERE id IN ({placeholders})"),
        parameters).mappings().all()
    return {int(row["id"]): (row["sub_sector"] or row["sector"]) for row in rows}


def _extend_peer_closure(session, pool: CandidatePool, tag_edges, *,
                         config: DiscoveryConfig, as_of: date) -> None:
    """A5.2's premise, at discovery time: a mechanism that fires on several
    members of an industry has almost certainly fired on the rest of it, and
    the distance walk's deep-hop bar is the reason they are missing.

    The sweep runs at `peer_closure_threshold`, which sits BELOW the d3 bar
    and ABOVE the shallow ones, and it admits companies ONLY through a tag
    the shock actually reaches -- so a swept name still carries a
    `mechanism_id` and can still be published as SECONDARY_RIPPLE. A name
    with no mechanism could never publish (invariant 7), so adding one would
    be adding noise.
    """
    existing = {c.company_id: c for c in pool.candidates}
    industries = _industry_of(session, sorted(existing))
    members: dict[str, list[int]] = {}
    for company_id, industry in industries.items():
        if industry and existing[company_id].discovery_source == MECHANISM:
            members.setdefault(industry, []).append(company_id)

    implicated = {industry for industry, ids in members.items()
                  if len(ids) >= config.peer_closure_min_members}
    if not implicated or not tag_edges:
        return

    rows = query_exposure_index_many(
        session, sorted(tag_edges), min_share=config.peer_closure_threshold,
        as_of=as_of)
    if not rows:
        return
    candidate_ids = sorted({int(row["company_id"]) for row in rows}
                           - set(existing))
    sweep_industries = _industry_of(session, candidate_ids)

    for row in rows:
        company_id = int(row["company_id"])
        if company_id in existing:
            continue
        if sweep_industries.get(company_id) not in implicated:
            continue
        tag = str(row["exposure_tag"])
        edge, shock = tag_edges[tag]
        pool.add(Candidate(
            company_id=company_id, discovery_source=PEER_CLOSURE,
            via_tag=tag, mechanism_id=edge.edge_id,
            graph_distance=edge.graph_distance, shock_id=shock.shock_id,
            share_of_base=float(row["share_of_base"]),
            expected_materiality_prior=_prior(
                row["share_of_base"], row["confidence"], edge.graph_distance)))
