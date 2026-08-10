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
from app.models import Company, CompanyProfile, Listing

SOURCE_NAME = "wikipedia"

# "Recent years" = this far back from the snapshot day. Five is the
# dossier's own framing ("what has it been doing the last five years").
PROFILE_LOOKBACK_YEARS = 5


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


def apply_profile(session: Session, company: Company, full_page: dict, as_of: date) -> str:
    """Stage B write for ONE company whose article `full_page` describes.
    The title is ALREADY proven to belong to this company by Stage A's
    resolution -- this function never re-derives the match. Deterministic
    extraction only (section split -> recent-year paragraph filter ->
    whole-sentence bounding); no LLM, no invented text.

    Never clobbers: a page that stops yielding a section this run leaves
    the previously stored text in place. Returns one of
    'written' | 'unchanged' | 'empty' for the runbook's counts.
    """
    section_map = extract.sections(full_page.get("extract") or "")
    cutoff = as_of.year - PROFILE_LOOKBACK_YEARS
    max_year = as_of.year + 1  # forward-dated "in fiscal 2027" phrasing

    history_section = extract.find_section(section_map, extract._HISTORY_HEADINGS)
    history = extract.bounded_text(
        extract.recent_paragraphs(history_section or "", cutoff, max_year),
        extract.HISTORY_MAX_CHARS,
        extract.HISTORY_HARD_CHARS,
    )
    if history is None and history_section:
        # No recent-dated paragraphs, but the article HAS a history --
        # fall back to its most recent material regardless of age
        # (bounded_text is tail-anchored, so the newest content wins).
        # Still sourced and attributed; the UI titles the section
        # age-neutrally ("The story so far"), so older text never
        # masquerades as the last five years.
        history = extract.bounded_text(
            extract.all_paragraphs(history_section),
            extract.HISTORY_MAX_CHARS,
            extract.HISTORY_HARD_CHARS,
        )
    developments_section = extract.find_section(section_map, extract._DEVELOPMENTS_HEADINGS)
    developments = extract.bounded_text(
        extract.recent_paragraphs(developments_section or "", cutoff, max_year),
        extract.DEVELOPMENTS_MAX_CHARS,
        extract.DEVELOPMENTS_HARD_CHARS,
    )

    profile = (
        session.query(CompanyProfile).filter(CompanyProfile.company_id == company.id).one_or_none()
    )
    if history is None and developments is None:
        # Nothing qualified. No half-empty marker row; an existing row's
        # text stays (never clobber good data with nothing).
        return "empty"

    title = full_page.get("title") or ""
    url = extract.source_url(title)
    if profile is None:
        profile = CompanyProfile(
            company_id=company.id, source_url=url, source_title=title,
            source_revision_id=full_page.get("revid"), as_of=as_of,
        )
        session.add(profile)
    changed = False
    if history is not None and history != profile.history_text:
        profile.history_text = history
        changed = True
    if developments is not None and developments != profile.developments_text:
        profile.developments_text = developments
        changed = True
    profile.source_url = url
    profile.source_title = title
    profile.source_revision_id = full_page.get("revid")
    profile.as_of = as_of
    session.commit()
    return "written" if changed else "unchanged"
