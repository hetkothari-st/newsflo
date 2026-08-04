"""One shape for the company-fundamentals payload, used by all four
serializers so it cannot drift between them.

Replaces the LLM-written business_desc: what a company does is expressed as
BSE's official classification plus the ratios BSE publishes, each traceable to
a source and an as-of date. See docs/superpowers/specs/2026-08-04-sourced-
company-fundamentals-design.md.
"""
from app.models import Company

_RATIOS = ("eps", "ceps", "pe", "pb", "opm", "npm", "roe")
_CONSOLIDATED = (
    ("eps", "con_eps"), ("ceps", "con_ceps"), ("pe", "con_pe"), ("pb", "con_pb"),
    ("opm", "con_opm"), ("npm", "con_npm"), ("roe", "con_roe"),
)


def fundamentals_payload(company: Company) -> dict | None:
    """None when the company has no official classification (the curated
    global rows and NSE-only names). A NULL ratio is OMITTED rather than sent
    as 0 -- a client must not be able to read absent data as a real zero, and
    an empty ratios object invites exactly that.
    """
    if not company.official_sector:
        return None

    payload: dict = {
        "classification": {
            "sector": company.official_sector,
            "industry": company.official_industry,
            "group": company.official_igroup,
            "sub_group": company.official_isubgroup,
        },
        "source": company.classification_source,
        "as_of": company.classification_as_of.isoformat() if company.classification_as_of else None,
    }

    ratios = {k: getattr(company, k) for k in _RATIOS if getattr(company, k) is not None}
    consolidated = {k: getattr(company, a) for k, a in _CONSOLIDATED if getattr(company, a) is not None}
    if ratios:
        payload["ratios"] = ratios
    if consolidated:
        payload["consolidated"] = consolidated
    # Own key, not a clobber of `source`/`as_of` above: those two describe
    # WHEN the classification was sourced, financials_source/financials_as_of
    # describe WHEN the ratios were sourced, and the two dates can legitimately
    # differ (classification is a monthly detail pass, ratios refresh on their
    # own cadence). Overwriting `source`/`as_of` here made it impossible for a
    # client to tell which half of the payload a given date applied to.
    if company.financials_source:
        payload["financials_source"] = company.financials_source
        payload["financials_as_of"] = (
            company.financials_as_of.isoformat() if company.financials_as_of else None
        )
    return payload
