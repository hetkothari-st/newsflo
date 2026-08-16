"""TASK 1.2 -- company master and entity resolution (spec §4.4).

WHY THIS IS SEPARATE FROM `app.companies.matching.matcher`

The existing match ladder resolves an ARTICLE MENTION -- a journalist's
shorthand, where a fuzzy rung and a tradeability tiebreak buy recall that is
worth its risk. This resolver attaches a FILING to a company in the ledger,
where the same trade is wrong: a ledger row is permanent, is reused by every
later event, and a mis-attached filing silently poisons everything computed
from it.

So this resolver is strict and FAILS CLOSED:

  * ISIN first, always. Ticker and name are lookup aliases only (§4.4).
  * exact rungs only -- no fuzzy match, no similarity score, no tiebreak.
    Two candidates is ENTITY_AMBIGUOUS, never "the more tradeable one".
  * a bare symbol that two exchanges list for two different companies is
    ENTITY_AMBIGUOUS (the "Castrol India vs plc" case, §4.4).
  * `as_of` is REQUIRED. Validity cannot be skipped by forgetting to pass a
    date: a claim on an entity outside its window, or after a merger's
    effective date, is ENTITY_WRONG.

ATTACHMENT (`attach_exposure_to_listco`) is a PURE function over explicit
evidence, so the rules are testable without a database and cannot silently
read something they were not given.
"""
from dataclasses import dataclass
from datetime import date
from typing import Sequence

from sqlalchemy.orm import Session

from app.companies.matching.normalize import normalize_name
from app.models import (
    Company, CompanyAlias, CompanyAliasWindow, CompanyEntityMeta,
    EntityCorporateAction, Listing,
)

RESOLVED = "RESOLVED"
ENTITY_AMBIGUOUS = "ENTITY_AMBIGUOUS"
ENTITY_WRONG = "ENTITY_WRONG"
ENTITY_NOT_FOUND = "ENTITY_NOT_FOUND"

# Corporate actions after whose effective date the entity no longer exists as
# the thing a claim would be about.
_TERMINAL_ACTIONS = ("MERGER", "DELISTING")
# Entity statuses that are not "a live listed company".
_TERMINAL_STATUSES = ("MERGED", "DELISTED")

TIER_SECONDARY_RIPPLE = "SECONDARY_RIPPLE"
HOLDCO_DISCOUNT = "HOLDCO_DISCOUNT"


@dataclass(frozen=True)
class EntityResolution:
    status: str
    company_id: int | None = None
    isin: str | None = None
    method: str = ""
    detail: str = ""


# --- resolution ------------------------------------------------------------

def _validity(session: Session, company: Company, as_of: date,
              method: str) -> EntityResolution:
    """The one place a resolved company is checked against the claim date."""
    action = (session.query(EntityCorporateAction)
              .filter(EntityCorporateAction.company_id == company.id,
                      EntityCorporateAction.action_type.in_(_TERMINAL_ACTIONS),
                      EntityCorporateAction.effective_date <= as_of)
              .order_by(EntityCorporateAction.effective_date.asc())
              .first())
    if action is not None:
        return EntityResolution(
            ENTITY_WRONG, None, company.isin, method,
            f"{action.action_type} effective {action.effective_date.isoformat()}"
            + (f" -> {action.successor_isin}" if action.successor_isin else ""))

    meta = session.get(CompanyEntityMeta, company.id)
    if meta is not None:
        if meta.status in _TERMINAL_STATUSES:
            return EntityResolution(ENTITY_WRONG, None, company.isin, method,
                                    f"entity status {meta.status}")
        if meta.valid_from is not None and as_of < meta.valid_from:
            return EntityResolution(
                ENTITY_WRONG, None, company.isin, method,
                f"claim date precedes valid_from {meta.valid_from.isoformat()}")
        if meta.valid_to is not None and as_of > meta.valid_to:
            return EntityResolution(
                ENTITY_WRONG, None, company.isin, method,
                f"claim date follows valid_to {meta.valid_to.isoformat()}")

    return EntityResolution(RESOLVED, company.id, company.isin, method)


def _by_symbol(session: Session, symbol: str,
               exchange: str | None) -> tuple[list[int], str]:
    """Exchange listings first (a bare symbol can collide across exchanges),
    then the repo's suffixed `companies.ticker`."""
    query = session.query(Listing.company_id).filter(Listing.symbol == symbol)
    if exchange:
        query = query.filter(Listing.exchange == exchange)
    ids = sorted({company_id for company_id, in query.all()})
    if ids:
        return ids, "listing_symbol"

    ids = sorted({company_id for company_id, in
                  session.query(Company.id).filter(Company.ticker == symbol).all()})
    return ids, "ticker"


def _by_name(session: Session, name: str, as_of: date) -> tuple[list[int], str]:
    """EXACT rungs only: the alias index, the company's own name, and the
    validity-windowed alias table (a FORMER name resolves only inside its
    window)."""
    normalized = normalize_name(name)
    if not normalized:
        return [], "name"

    ids = sorted({company_id for company_id, in
                  session.query(CompanyAlias.company_id)
                  .filter(CompanyAlias.normalized == normalized).all()})
    if ids:
        return ids, "alias"

    ids = sorted({company.id for company in session.query(Company).all()
                  if normalize_name(company.name) == normalized})
    if ids:
        return ids, "company_name"

    windowed = [alias for alias in session.query(CompanyAliasWindow)
                .filter(CompanyAliasWindow.normalized == normalized).all()
                if (alias.valid_from is None or as_of >= alias.valid_from)
                and (alias.valid_to is None or as_of <= alias.valid_to)]
    return sorted({alias.company_id for alias in windowed}), "alias_window"


def resolve_entity(session: Session, *, as_of: date, isin: str | None = None,
                   ticker: str | None = None, name: str | None = None,
                   exchange: str | None = None) -> EntityResolution:
    """Resolve a filing (or a claim) to ONE listed company, or refuse.

    `as_of` is keyword-REQUIRED: validity is not an optional check.
    """
    if isin:
        company = (session.query(Company)
                   .filter(Company.isin == isin.strip().upper()).one_or_none())
        if company is None:
            return EntityResolution(ENTITY_NOT_FOUND, None, isin, "isin",
                                    "no company carries this ISIN")
        return _validity(session, company, as_of, "isin")

    candidates: list[int] = []
    method = ""
    if ticker:
        candidates, method = _by_symbol(session, ticker.strip(), exchange)
    if not candidates and name:
        candidates, method = _by_name(session, name, as_of)

    if not candidates:
        return EntityResolution(ENTITY_NOT_FOUND, None, None, method or "none",
                                "no exact match; the ledger never fuzzy-matches")
    if len(candidates) > 1:
        return EntityResolution(
            ENTITY_AMBIGUOUS, None, None, method,
            f"{len(candidates)} companies match: {candidates}")

    company = session.get(Company, candidates[0])
    return _validity(session, company, as_of, method)


# --- attachment ------------------------------------------------------------

@dataclass(frozen=True)
class ExposureOrigin:
    """WHERE the exposure physically sits -- which is not always the entity a
    reader can buy."""
    entity_name: str
    isin: str | None
    listed: bool
    parent_isin: str | None
    ownership_fraction: float | None = None
    segment_name: str | None = None
    exposure_tag: str | None = None


@dataclass(frozen=True)
class ListCo:
    """The listed company an exposure might attach to."""
    company_id: int
    isin: str
    listed: bool = True


@dataclass(frozen=True)
class SegmentEvidence:
    """A consolidated segment note line. `source_url` is mandatory: evidence
    without a document is not evidence."""
    segment_name: str
    fiscal_year: int
    source_url: str
    revenue_share: float | None = None
    ebitda_share: float | None = None


@dataclass(frozen=True)
class AttachResult:
    attached: bool
    company_id: int | None
    reason: str
    tier_cap: str | None = None
    modifiers: tuple[str, ...] = ()
    ownership_fraction: float | None = None
    materiality_base: str | None = None
    evidence_url: str | None = None


def attach_exposure_to_listco(exposure: ExposureOrigin, company: ListCo, *,
                              consolidated_segments: Sequence[SegmentEvidence] = (),
                              ) -> AttachResult:
    """Exposure in an unlisted subsidiary attaches to the listed parent ONLY
    IF consolidated segment data evidences it. Materiality is then computed
    against consolidated EBITDA with ownership_fraction applied.

    A holdco whose operating exposure sits in a listed subsidiary is capped
    at SECONDARY_RIPPLE with a HOLDCO_DISCOUNT modifier.

    PURE: every input is passed in, nothing is looked up, no default is
    invented. In particular a missing `ownership_fraction` BLOCKS the
    attachment -- it never becomes 1.0.
    """
    if not company.listed:
        return AttachResult(False, None, "TARGET_NOT_LISTED")

    same_entity = (exposure.isin is not None and company.isin is not None
                   and exposure.isin == company.isin)
    if same_entity:
        # The company's own exposure. Nothing to discount, nothing to cap.
        return AttachResult(True, company.company_id, "SELF",
                            ownership_fraction=exposure.ownership_fraction,
                            materiality_base="CONSOLIDATED_EBITDA")

    if exposure.parent_isin != company.isin:
        return AttachResult(False, None, "NOT_IN_OWNERSHIP_CHAIN")

    matching = [segment for segment in consolidated_segments
                if exposure.segment_name is not None
                and segment.segment_name.strip().casefold()
                == exposure.segment_name.strip().casefold()
                and segment.source_url]
    if not matching:
        # §4.4: without consolidated segment data showing the exposure, the
        # claim does not transmit to the parent at all.
        return AttachResult(False, None, "NO_CONSOLIDATED_SEGMENT_EVIDENCE")

    if exposure.ownership_fraction is None:
        return AttachResult(False, None, "OWNERSHIP_FRACTION_UNKNOWN")

    if exposure.listed:
        # The operating exposure sits in a LISTED subsidiary: a reader who
        # wants it can buy the subsidiary. The holdco carries it only as a
        # ripple, discounted -- and the discount itself is Phase 4 policy
        # data that does not exist yet, so only the modifier NAME is
        # recorded. No coefficient is invented here.
        return AttachResult(
            True, company.company_id, "HOLDCO_ROUTE",
            tier_cap=TIER_SECONDARY_RIPPLE, modifiers=(HOLDCO_DISCOUNT,),
            ownership_fraction=exposure.ownership_fraction,
            materiality_base="CONSOLIDATED_EBITDA",
            evidence_url=matching[0].source_url)

    return AttachResult(
        True, company.company_id, "CONSOLIDATED_SUBSIDIARY",
        ownership_fraction=exposure.ownership_fraction,
        materiality_base="CONSOLIDATED_EBITDA",
        evidence_url=matching[0].source_url)
