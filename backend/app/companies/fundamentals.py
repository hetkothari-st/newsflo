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


def ratio_or_none(value: float | None) -> float | None:
    """BSE writes literal 0.00 into ratio slots it has no figure for (see
    fundamentals_payload docstring). Shared by fundamentals_payload and the
    directory serializer so the sentinel rule cannot drift between callers.
    Negative values (loss-making EPS/NPM) are real and kept."""
    return value if value is not None and value != 0 else None


def fundamentals_payload(company: Company) -> dict | None:
    """None when the company has no official classification (the curated
    global rows and NSE-only names). A NULL ratio is OMITTED rather than sent
    as 0 -- a client must not be able to read absent data as a real zero, and
    an empty ratios object invites exactly that.

    An EXACT 0.0 is also omitted: BSE writes literal "0.00" into ratio slots
    it has no figure for (verified live 2026-08-05 -- L&T's consolidated OPM/
    NPM came back 0.00 while its standalone margins were 16.68/12.37; a
    conglomerate with a genuinely 0.00% consolidated margin does not exist).
    Rendering it produced exactly the fake-looking numbers this payload
    exists to prevent. A real near-zero margin (0.004 -> "0.00" after
    rounding) is indistinguishable from the sentinel at BSE's 2-decimal
    precision, so omission is the honest reading either way. Negative values
    (loss-making EPS/NPM) are real and kept.
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

    ratios = {
        k: v for k in _RATIOS
        if (v := ratio_or_none(getattr(company, k))) is not None
    }
    consolidated = {
        k: v for k, a in _CONSOLIDATED
        if (v := ratio_or_none(getattr(company, a))) is not None
    }
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
