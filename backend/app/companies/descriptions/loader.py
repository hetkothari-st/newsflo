"""Stage 3: the only module here that touches the DB.

Resolution is ARTICLE -> COMPANY and is required to be unambiguous. Every
identifier an article asserts is looked up independently; if they do not
all land on the same company row, the article is discarded. That covers the
cases that would otherwise produce a wrong description:

  - a demerger article carrying both the parent's and the spinoff's codes
  - a stale infobox whose BSE code was reassigned to another scrip
  - a group article ("Tata Group") listing several subsidiaries' tickers

In all three the honest answer is no description, and that is what gets
written -- which is to say, nothing.
"""
from datetime import date

from sqlalchemy.orm import Session

from app.companies.descriptions import extract
from app.models import Company, Listing

SOURCE_NAME = "wikipedia"


def resolve_company(session: Session, refs: extract.ArticleRefs) -> Company | None:
    """The single company every identifier in ``refs`` agrees on, or None.

    None covers three distinct situations that the caller does not need to
    tell apart: no identifiers, identifiers we do not recognise, and
    identifiers that disagree. All three mean "do not write a description".
    """
    if not refs:
        return None

    matched: set[int] = set()

    if refs.bse_codes:
        rows = (
            session.query(Listing.company_id)
            .filter(Listing.exchange == "BSE")
            .filter(Listing.scrip_code.in_(sorted(refs.bse_codes)))
            .all()
        )
        matched.update(r[0] for r in rows)

    if refs.nse_symbols:
        rows = (
            session.query(Listing.company_id)
            .filter(Listing.exchange == "NSE")
            .filter(Listing.symbol.in_(sorted(refs.nse_symbols)))
            .all()
        )
        matched.update(r[0] for r in rows)

    if refs.isins:
        rows = (
            session.query(Company.id)
            .filter(Company.isin.in_(sorted(refs.isins)))
            .all()
        )
        matched.update(r[0] for r in rows)

    if len(matched) != 1:
        return None
    return session.get(Company, matched.pop())


def apply_pages(session: Session, pages: list[dict], as_of: date) -> dict:
    """Write a sourced description for every page that resolves to exactly
    one company. Returns a counts dict for the runbook to print.

    Idempotent: rerunning with the same snapshot rewrites the same values.
    A page that stops resolving (its infobox lost the ticker) does NOT clear
    the description already stored -- never clobber good data with nothing.
    """
    stats = {
        "pages": len(pages),
        "disambiguation": 0,
        "no_refs": 0,
        "unresolved": 0,
        "no_text": 0,
        "written": 0,
        "unchanged": 0,
    }
    # One article per company. Wikipedia has redirects and near-duplicate
    # articles; without this the last one processed would silently win.
    claimed: dict[int, str] = {}

    for page in pages:
        wikitext = page.get("wikitext") or ""
        title = page.get("title") or ""

        if extract.is_disambiguation(wikitext):
            stats["disambiguation"] += 1
            continue

        refs = extract.parse_refs(wikitext)
        if not refs:
            stats["no_refs"] += 1
            continue

        company = resolve_company(session, refs)
        if company is None:
            stats["unresolved"] += 1
            continue

        text = extract.summarize(page.get("extract") or "")
        if text is None:
            stats["no_text"] += 1
            continue

        if company.id in claimed:
            # Two articles both proving the same company. Neither is
            # trustworthy enough to pick between, so keep the first and
            # count the collision rather than overwrite.
            stats["unresolved"] += 1
            continue
        claimed[company.id] = title

        url = extract.source_url(title)
        if company.business_desc == text and company.business_desc_source_url == url:
            company.business_desc_as_of = as_of
            stats["unchanged"] += 1
            continue

        company.business_desc = text
        company.business_desc_source_url = url
        company.business_desc_as_of = as_of
        stats["written"] += 1

    session.commit()
    return stats
