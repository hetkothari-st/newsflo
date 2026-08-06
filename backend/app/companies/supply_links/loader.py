"""Stage 4: the only module here that touches the DB.

Two writes per company per document, both provenance-guarded:

1. `supply_links` rows (+ the `supply_chain_*_json` caches derived from
   them) -- gated on document recency. A company's stored links all come
   from ONE document at a time (the newest one seen); an older document's
   links are never merged in on top of a newer document's, and an older
   document with nothing to say is never allowed to wipe a newer
   document's rows. Only a document at least as new as what's stored may
   replace them -- including replacing them with nothing, which is how a
   relationship correctly ages out when a fresher rationale drops it.

2. `business_desc` -- gated on provenance, not just recency, mirroring
   app.companies.descriptions.loader's honesty rule. A rating rationale's
   one-line summary may only overwrite a description that is unsourced,
   or itself sourced from a rating rationale (an "AttachLive" BSE
   attachment URL) that's the same document or older. It must never
   overwrite Wikipedia -- Wikipedia's URL never contains "AttachLive" and
   never equals the incoming rationale URL, so that comparison alone
   keeps this module from ever touching a Wikipedia-sourced description.
"""
import json

from sqlalchemy.orm import Session

from app.companies.matching import matcher
from app.models import Company, SupplyLink


def _existing_newest_as_of(session: Session, company_id: int):
    rows = (
        session.query(SupplyLink.as_of)
        .filter(SupplyLink.company_id == company_id)
        .all()
    )
    if not rows:
        return None
    return max(as_of for as_of, in rows)


def _should_write_description(company: Company, source_url: str, as_of) -> bool:
    existing_url = company.business_desc_source_url
    if existing_url is not None and "AttachLive" not in existing_url and existing_url != source_url:
        # Sourced from something else (Wikipedia, or any non-rating URL) --
        # never overwrite.
        return False
    existing_as_of = company.business_desc_as_of
    if existing_as_of is not None and as_of < existing_as_of:
        return False
    return True


def apply_extraction(
    session: Session, company: Company, profile: dict, *,
    source_url: str, source_agency: str, as_of,
) -> dict:
    counts = {"links_written": 0, "links_kept_older": 0, "desc_written": 0, "desc_kept": 0}

    entries = [
        (relation, name, evidence)
        for relation, key in (("SUPPLIER", "suppliers"), ("CUSTOMER", "customers"))
        for name, evidence in profile.get(key, [])
    ]

    newest_existing = _existing_newest_as_of(session, company.id)
    is_newer_or_equal = newest_existing is None or as_of >= newest_existing

    if is_newer_or_equal:
        session.query(SupplyLink).filter(SupplyLink.company_id == company.id).delete()
        for relation, name, evidence in entries:
            match = matcher.resolve(session, ticker=None, name=name)
            session.add(SupplyLink(
                company_id=company.id, relation=relation,
                counterparty_name=name,
                counterparty_company_id=match.company_id if match else None,
                evidence=evidence, source_url=source_url,
                source_agency=source_agency, as_of=as_of,
            ))
        counts["links_written"] = len(entries)
    else:
        # Older document. If it has nothing new to report, the existing
        # (newer) rows stand untouched -- an old rationale never clobbers
        # a fresher one's silence. If it DOES carry links, they lose to
        # the newer document's rows already in place: a newer rating
        # review supersedes whatever an older one said.
        counts["links_kept_older"] = len(entries) if entries else 1

    session.flush()

    summary = profile.get("business_summary")
    if summary is not None and _should_write_description(company, source_url, as_of):
        company.business_desc = summary
        company.business_desc_source_url = source_url
        company.business_desc_as_of = as_of
        counts["desc_written"] = 1
    elif summary is not None:
        counts["desc_kept"] = 1

    refresh_json_caches(session, company)
    session.commit()
    return counts


def refresh_json_caches(session: Session, company: Company) -> None:
    def names(relation: str) -> list[str]:
        rows = (
            session.query(SupplyLink.counterparty_name)
            .filter(SupplyLink.company_id == company.id, SupplyLink.relation == relation)
            .order_by(SupplyLink.counterparty_name)
            .all()
        )
        return [name for name, in rows]

    company.supply_chain_suppliers_json = json.dumps(names("SUPPLIER"))
    company.supply_chain_customers_json = json.dumps(names("CUSTOMER"))
