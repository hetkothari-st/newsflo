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
filter on a unique/indexed column each. The company_name, token_set, and
fuzzy rungs are NOT indexed: they pull every (company_id, name-or-normalized)
row in companies or company_aliases into Python, because neither "same
token set regardless of order" nor edit-distance scoring (nor, for
company_name, comparing a value that only exists normalized in Python) can
be expressed as a single indexed predicate. Measured at ~1ms for 523
aliases (507-company universe); expect roughly 15-30ms at ~15k aliases
(~4,967 companies with dual listings) -- a full table scan of a small,
in-memory-sized table, not one that scales with article or request volume.

company_name (between alias-exact and token_set): a direct exact-match
fallback against Company.name itself, not against company_aliases. Added
because the alias table is a derived side table -- company_aliases.LEGAL
rows are themselves built FROM Company.name (see
app.companies.matching.aliases.build_aliases_for_company), so if that table
is ever empty, stale, or missing a row for a company (a rebuild that hasn't
run yet, a company inserted outside the normal ingest path), a name-only
mention that would have matched a freshly-built alias table instead
silently resolves to nothing -- the resolver never even tries the one
piece of data that's always present, the company's own name. This rung
produces ZERO new match surface versus a correctly-built alias table: it is
exact equality on the same normalized form the LEGAL alias would have used,
not containment and not scoring, so it is not a repeat of the removed
token_subset rung above. It removes a freshness *dependency*, not a
precision guarantee. Do not delete this rung as "redundant with alias" --
it exists for exactly the case where alias is NOT there yet.
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


def _disambiguate_ex(
    session: Session, company_ids: list[int], method: str,
) -> tuple[MatchResult | None, bool]:
    """One candidate wins outright. Several candidates resolve to (None,
    ambiguous=True), unless exactly one of them is normally tradeable -- the
    realistic collision once dormant shells enter the table. The bool is
    the ONLY signal a caller has to tell "we found nothing" apart from "we
    found more than one real company and can't tell which" -- both used to
    collapse to the same None (corrective-v4 Task 7)."""
    unique = list(dict.fromkeys(company_ids))
    if not unique:
        return None, False
    if len(unique) == 1:
        return MatchResult(unique[0], method), False

    tradeable = [
        company_id for company_id, in session.query(Company.id)
        .filter(Company.id.in_(unique), Company.tradeability == "NORMAL").all()
    ]
    if len(tradeable) == 1:
        return MatchResult(tradeable[0], f"{method}+tradeability_tiebreak"), False
    return None, True


def _disambiguate(session: Session, company_ids: list[int], method: str) -> MatchResult | None:
    return _disambiguate_ex(session, company_ids, method)[0]


def resolve_with_ambiguity(
    session: Session, ticker: str | None, name: str | None, isin: str | None = None,
) -> tuple[MatchResult | None, bool]:
    """Same ladder as `resolve()`, plus the one bit `resolve()` throws away:
    whether the winning rung actually found MULTIPLE distinct companies it
    could not tiebreak, rather than finding none at all. `resolve()` is now
    a thin wrapper over this that keeps its old, ambiguity-blind contract
    for the ~60 existing call sites that only ever wanted the match itself.

    Ticker and ISIN lookups are exact-equality on a unique/indexed column,
    so they can never be ambiguous by construction -- only the name-based
    rungs (alias, company_name, token_set, fuzzy) can be."""
    if ticker:
        company = session.query(Company).filter_by(ticker=ticker.strip()).one_or_none()
        if company is not None:
            return MatchResult(company.id, "ticker"), False

    if isin:
        company = session.query(Company).filter_by(isin=isin.strip().upper()).one_or_none()
        if company is not None:
            return MatchResult(company.id, "isin"), False

    normalized = normalize_name(name)
    if not normalized:
        return None, False

    exact = [
        company_id for company_id, in
        session.query(CompanyAlias.company_id).filter_by(normalized=normalized).all()
    ]
    if exact:
        return _disambiguate_ex(session, exact, "alias")

    # Fallback for a stale/empty/missing alias table -- see module docstring.
    # Exact equality on the same normalized form the LEGAL alias would use,
    # so it matches nothing the alias rung wouldn't already have matched had
    # aliases been built.
    company_name_hits = [
        company_id for company_id, company_name in
        session.query(Company.id, Company.name).all()
        if normalize_name(company_name) == normalized
    ]
    if company_name_hits:
        return _disambiguate_ex(session, company_name_hits, "company_name")

    mention_tokens = tokens(name)
    if not mention_tokens:
        return None, False

    candidates = (
        session.query(CompanyAlias.company_id, CompanyAlias.normalized).all()
    )

    token_hits = [
        company_id for company_id, alias_normalized in candidates
        if frozenset(alias_normalized.split(" ")) == mention_tokens
    ]
    if token_hits:
        return _disambiguate_ex(session, token_hits, "token_set")

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
        return None, False
    scored.sort(reverse=True)
    best_score, best_id = scored[0]
    runners = [s for s, cid in scored if cid != best_id]
    if runners and best_score - max(runners) < FUZZY_MIN_MARGIN:
        # Two candidates close enough in score that picking the leader would
        # be a guess dressed up as confidence -- genuinely ambiguous, not
        # simply "no fuzzy match reached the threshold".
        return None, True
    return MatchResult(best_id, "fuzzy", best_score), False


def resolve(
    session: Session, ticker: str | None, name: str | None, isin: str | None = None,
) -> MatchResult | None:
    return resolve_with_ambiguity(session, ticker, name, isin)[0]
