"""The match ladder (spec §8.3). Replaces
app.companies.resolution._find_direct_company.

Every rung is an EXACT comparison on a normalized form and every rung
resolves ambiguity to None -- preserving the resolver's "omit rather than
mismatch" contract while removing the substring matching that silently
mismatched companies. The one tiebreak allowed: when exactly one candidate
is normally tradeable and the rest are SME or suspended shells, the
tradeable one wins.

Deliberately NOT in this ladder: any token-subset rung ("mention's tokens
are all present in some alias's tokens"). It was tried and reverted -- at
the real 507-company universe, 488 of 718 distinct alias tokens belong to
exactly one company and aren't themselves an exact alias, so a subset rung
resolves with false confidence on bare/short mentions like "Air India" (->
Tenneco Clean Air India), "cards" (-> SBI Cards), "authority" (-> SAIL).
The hazard scales with universe size, not down. Ambiguous cases being
protected by 2+ colliding aliases (as "Apollo"/"Bharat" are in the small
test fixture) is a lucky accident of a small universe, not a property that
holds at scale. Abbreviated mentions belong in curated.py as reviewed
TRADE_NAME aliases (e.g. "SBI Cards"), not resolved by loosening the
ladder.

The ticker, isin, and alias-exact rungs are indexed queries -- an equality
filter on a unique/indexed column each. The token_set and fuzzy rungs are
NOT indexed: they pull every (company_id, normalized) row in
company_aliases into Python, because neither "same token set regardless of
order" nor edit-distance scoring can be expressed as a single indexed
predicate. Measured at ~1ms for 523 aliases (507-company universe); expect
roughly 15-30ms at ~15k aliases (~4,967 companies with dual listings) -- a
full table scan of a small, in-memory-sized table, not one that scales
with article or request volume.
"""
from dataclasses import dataclass
from difflib import SequenceMatcher

from sqlalchemy.orm import Session

from app.companies.matching.normalize import normalize_name, tokens
from app.models import Company, CompanyAlias

FUZZY_MIN_SCORE = 0.90
FUZZY_MIN_MARGIN = 0.05


@dataclass(frozen=True)
class MatchResult:
    company_id: int
    method: str
    score: float = 1.0


def _disambiguate(session: Session, company_ids: list[int], method: str) -> MatchResult | None:
    """One candidate wins outright. Several candidates resolve to None,
    unless exactly one of them is normally tradeable -- the realistic
    collision once dormant shells enter the table."""
    unique = list(dict.fromkeys(company_ids))
    if not unique:
        return None
    if len(unique) == 1:
        return MatchResult(unique[0], method)

    tradeable = [
        company_id for company_id, in session.query(Company.id)
        .filter(Company.id.in_(unique), Company.tradeability == "NORMAL").all()
    ]
    if len(tradeable) == 1:
        return MatchResult(tradeable[0], f"{method}+tradeability_tiebreak")
    return None


def resolve(
    session: Session, ticker: str | None, name: str | None, isin: str | None = None,
) -> MatchResult | None:
    if ticker:
        company = session.query(Company).filter_by(ticker=ticker.strip()).one_or_none()
        if company is not None:
            return MatchResult(company.id, "ticker")

    if isin:
        company = session.query(Company).filter_by(isin=isin.strip().upper()).one_or_none()
        if company is not None:
            return MatchResult(company.id, "isin")

    normalized = normalize_name(name)
    if not normalized:
        return None

    exact = [
        company_id for company_id, in
        session.query(CompanyAlias.company_id).filter_by(normalized=normalized).all()
    ]
    if exact:
        return _disambiguate(session, exact, "alias")

    mention_tokens = tokens(name)
    if not mention_tokens:
        return None

    candidates = (
        session.query(CompanyAlias.company_id, CompanyAlias.normalized).all()
    )

    token_hits = [
        company_id for company_id, alias_normalized in candidates
        if frozenset(alias_normalized.split(" ")) == mention_tokens
    ]
    if token_hits:
        return _disambiguate(session, token_hits, "token_set")

    scored: list[tuple[float, int]] = []
    for company_id, alias_normalized in candidates:
        # Only score aliases that share at least one token -- without this
        # gate every unrelated name gets a similarity score and the margin
        # test becomes meaningless.
        if not (frozenset(alias_normalized.split(" ")) & mention_tokens):
            continue
        score = SequenceMatcher(None, normalized, alias_normalized).ratio()
        if score >= FUZZY_MIN_SCORE:
            scored.append((score, company_id))

    if not scored:
        return None
    scored.sort(reverse=True)
    best_score, best_id = scored[0]
    runners = [s for s, cid in scored if cid != best_id]
    if runners and best_score - max(runners) < FUZZY_MIN_MARGIN:
        return None
    return MatchResult(best_id, "fuzzy", best_score)
