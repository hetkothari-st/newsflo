from sqlalchemy import case
from sqlalchemy.orm import Session

from app.analysis.schemas import CompanyMention
from app.companies.integrity import DEMO_TICKERS, is_demo_company
from app.companies.matching import matcher
from app.config import settings
from app.models import Company

# Lowered from 5. Fan-out is an exposure tier, not an analysis tier -- three
# prominent constituents convey "this sector has exposure" as well as five
# do, at 40% less noise.
TOP_N_SECTOR_COMPANIES = 3

# Portable (SQLite + Postgres) ordering expression: rank companies by index
# tier so sector-inference picks the most prominent companies first. Lower
# rank value = higher priority.
_TIER_RANK = case(
    (Company.index_tier == "NIFTY50", 0),
    (Company.index_tier == "NIFTYNEXT50", 1),
    (Company.index_tier == "NIFTYMIDCAP150", 2),
    (Company.index_tier == "NIFTYSMALLCAP250", 3),
    else_=4,
)

# Resolution order for impact_level: a parent must be resolved (and its
# ticker recorded) before any entry that names it via parent_ticker, so
# indirect_l1 entries resolve after every direct entry, and indirect_l2
# entries resolve after every indirect_l1 entry.
_LEVEL_ORDER = {"direct": 0, "indirect_l1": 1, "indirect_l2": 2}


def _to_resolved(
    company: Company, mention: CompanyMention, basis: str,
    impact_level: str = "direct", parent_company_id: int | None = None,
) -> dict:
    return {
        "company_id": company.id,
        "direction": mention.direction,
        "magnitude_low": mention.magnitude_low,
        "magnitude_high": mention.magnitude_high,
        # A sector-inference row's "rationale" is a template built from the
        # sector's own one-line mechanism (app.analysis.cascade.
        # _sector_fanout_mentions), not reasoning about THIS company -- and
        # it reads exactly like analysis, which is how a food-delivery
        # company came to carry a paragraph about crude-driven packaging
        # costs. Persist nothing rather than something that misrepresents
        # itself; the row still renders as a flagged exposure via
        # app.reasoning.ripple_relationship.is_exposure_only.
        "rationale": None if basis == "sector_inference" else mention.rationale,
        "key_points": mention.key_points,
        # Raw LLM value if present, otherwise None -- always overwritten by
        # app.reasoning.confidence.compute_confidence before persistence
        # (see app/pipeline.py::_persist_alert).
        "confidence_score": mention.confidence_score,
        "time_horizon": mention.time_horizon,
        "basis": basis,
        "reasons": mention.reasons,
        "evidence_refs": mention.evidence_refs,
        "risks": mention.risks,
        "assumptions": mention.assumptions,
        "unknowns": mention.unknowns,
        "alternative_hypothesis": mention.alternative_hypothesis,
        "impact_level": impact_level,
        "parent_company_id": parent_company_id,
    }


def _is_tradeable_indian(company: Company) -> bool:
    """Same market/tradeability restriction as this module's own fan-out
    branch (below) -- without it, a direct mention resolving to a
    RESTRICTED/SME/SUSPENDED row, or a curated GLOBAL row, persists as a
    real alert_companies row with basis='direct_mention'. Confirmed live: a
    direct mention of "BP" resolved to a real Company row this way."""
    return company.market == "INDIA" and company.tradeability == "NORMAL"


def _find_direct_company(session: Session, mention: CompanyMention) -> Company | None:
    """Resolve a direct mention via the alias match ladder
    (app.companies.matching.matcher).

    The previous implementation loaded every company into Python and
    substring-matched both directions. At 509 companies that was merely
    slow; at ~4,967 it silently mismatches (many companies share leading
    tokens) so it was replaced. Ambiguity still resolves to None -- the
    "omit rather than mismatch" contract is unchanged.
    """
    if not settings.use_alias_matcher:
        return _find_direct_company_legacy(session, mention)

    result = matcher.resolve(session, ticker=mention.ticker, name=mention.name)
    if result is None:
        return None
    company = session.get(Company, result.company_id)
    if company is None or is_demo_company(company.ticker) or not _is_tradeable_indian(company):
        return None
    return company


def _find_direct_company_legacy(session: Session, mention: CompanyMention) -> Company | None:
    """Resolve a direct mention to a Company, trying ticker first, then name.

    The analysis model sometimes names a real company it is confident about
    without being confident of the exact ticker symbol. Falling straight
    through to sector-wide inference in that case would discard the model's
    specific reasoning and substitute a generic top-N-by-tier sector pick --
    exactly the kind of unrelated-company mismatch this resolver must avoid.
    Name matching only returns a company when there is exactly ONE candidate
    (either an exact case-insensitive match, or a single company whose name
    contains the mention's name or vice versa) -- an ambiguous match returns
    None rather than guessing, consistent with "omit rather than mismatch".
    """
    if mention.ticker:
        company = session.query(Company).filter_by(ticker=mention.ticker).one_or_none()
        if company is not None and not is_demo_company(company.ticker) and _is_tradeable_indian(company):
            return company
    if not mention.name:
        return None
    name_lower = mention.name.strip().lower()
    if not name_lower:
        return None
    all_companies = [
        c for c in session.query(Company).all()
        if not is_demo_company(c.ticker) and _is_tradeable_indian(c)
    ]
    exact = [c for c in all_companies if c.name.strip().lower() == name_lower]
    if len(exact) == 1:
        return exact[0]
    contains = [c for c in all_companies if name_lower in c.name.lower() or c.name.lower() in name_lower]
    if len(contains) == 1:
        return contains[0]
    return None


def resolve_companies(
    session: Session, mentions: list[CompanyMention],
    anchor_sub_sectors: dict[str, set[str]] | None = None,
) -> list[dict]:
    """Resolve every mention to a Company, deduplicated by company_id across
    the WHOLE mentions list.

    Without this, multiple sector-level mentions of the same sector in one
    article (a model deviation actually observed in production: naming 4
    specific companies but marking all of them is_direct=false with the same
    sector) each independently expand to the same top-N sector companies,
    producing severe duplication (one real case: 5 companies x 4 mentions =
    20 rows for a single article). First occurrence wins; later duplicate
    resolutions of an already-resolved company are dropped rather than
    appended again.

    Mentions are processed in impact-level order (direct, then indirect_l1,
    then indirect_l2) regardless of the order the LLM returned them in, so
    an indirect entry's parent_ticker always resolves against an
    already-populated ticker->company_id map -- see _LEVEL_ORDER.

    Dispatches on is_direct (a specific named company vs. a sector-wide
    fan-out mention), not on impact_level -- a sector-wide fan-out mention
    can itself be at any impact_level (see app.analysis.cascade's
    _sector_fanout_mentions, which builds one for the direct stage AND for
    each cascade level), so an indirect one still needs its own
    parent_ticker chain resolved the same way a direct_mention indirect
    entry does.

    anchor_sub_sectors: {sector: {sub_sector, ...}} built from the companies
    the model NAMED for each sector. When present, a sector's fan-out is
    restricted to companies sharing one of those sub-sectors, so a crude-oil
    story reaching "fmcg" pulls staples_food (where the named companies are)
    rather than every prominent fmcg name regardless of what it sells. Falls
    back to the whole sector when a sector has no anchor -- an unanchored
    sector still deserves its exposure tier, just a less targeted one.
    """
    resolved = []
    seen_company_ids: set[int] = set()
    ticker_to_company_id: dict[str, int] = {}

    def _resolve_parent(mention: CompanyMention) -> tuple[int | None, bool]:
        """Returns (parent_company_id, ok). ok is False only when this
        mention IS at an indirect level but its parent_ticker didn't
        resolve (missing, unknown ticker, or a typo) -- the chain is
        broken, so the caller should drop the entry rather than persist an
        orphaned indirect row, consistent with "omit rather than
        mismatch". A direct-level mention always returns (None, True)."""
        if mention.impact_level not in ("indirect_l1", "indirect_l2"):
            return None, True
        parent_company_id = ticker_to_company_id.get(mention.parent_ticker) if mention.parent_ticker else None
        return parent_company_id, parent_company_id is not None

    for mention in sorted(mentions, key=lambda m: _LEVEL_ORDER.get(m.impact_level, 0)):
        if mention.is_direct:
            company = _find_direct_company(session, mention)
            if company is None:
                continue
            if company.id in seen_company_ids:
                continue
            parent_company_id, ok = _resolve_parent(mention)
            if not ok:
                continue
            seen_company_ids.add(company.id)
            resolved.append(_to_resolved(
                company, mention, basis="direct_mention",
                impact_level=mention.impact_level, parent_company_id=parent_company_id,
            ))
            if mention.ticker:
                ticker_to_company_id[mention.ticker] = company.id
        else:
            if not mention.sector:
                continue
            parent_company_id, ok = _resolve_parent(mention)
            if not ok:
                continue
            query = (
                session.query(Company)
                .filter_by(sector=mention.sector)
                .filter(Company.ticker.notin_(DEMO_TICKERS))
                # Dormant shells and non-Indian rows must never surface as
                # affected companies once the universe grows from 509 to
                # ~4,967 (spec §8.4).
                .filter(Company.market == "INDIA")
                .filter(Company.tradeability == "NORMAL")
            )
            anchors = (anchor_sub_sectors or {}).get(mention.sector)
            if anchors:
                query = query.filter(Company.sub_sector.in_(anchors))
            companies = (
                # Rank by real size, not Nifty membership: after the full
                # universe ingest ~4,200 of ~4,967 companies sit in
                # index_tier='OTHER', which collapses the tier ranking into
                # alphabetical order. _TIER_RANK stays as the tiebreak, which
                # is also what keeps the pre-existing fan-out tests (whose
                # companies have no market cap) ordering as before.
                query.order_by(
                    Company.market_cap.desc().nullslast(),
                    _TIER_RANK.asc(),
                    Company.ticker.asc(),
                )
                .limit(TOP_N_SECTOR_COMPANIES)
                .all()
            )
            for company in companies:
                if company.id in seen_company_ids:
                    continue
                seen_company_ids.add(company.id)
                resolved.append(_to_resolved(
                    company, mention, basis="sector_inference",
                    impact_level=mention.impact_level, parent_company_id=parent_company_id,
                ))
                ticker_to_company_id[company.ticker] = company.id
    return resolved
