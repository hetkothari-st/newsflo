from datetime import date

from app.companies.fundamentals import fundamentals_payload
from app.models import Company


def _co(**kw):
    base = dict(ticker="X.NS", name="X", sector="oil_gas", index_tier="OTHER")
    base.update(kw)
    return Company(**base)


def test_full_payload():
    p = fundamentals_payload(_co(
        official_sector="Energy", official_industry="Oil, Gas & Consumable Fuels",
        official_igroup="Petroleum Products", official_isubgroup="Refineries & Marketing",
        eps=28.98, pe=44.95, financials_source="BSE", financials_as_of=date(2026, 8, 4),
    ))
    assert p["classification"]["sub_group"] == "Refineries & Marketing"
    assert p["ratios"]["eps"] == 28.98
    assert p["financials_source"] == "BSE"
    assert p["financials_as_of"] == "2026-08-04"


def test_classification_and_financial_provenance_are_kept_separate():
    """[Minor] financials_source/financials_as_of must not clobber the
    classification's own source/as_of -- the two halves of the payload can
    legitimately be sourced on different dates (classification is a monthly
    detail pass, ratios refresh on their own cadence), and a client must be
    able to tell which date applies to which half."""
    p = fundamentals_payload(_co(
        official_sector="Energy", classification_source="BSE",
        classification_as_of=date(2026, 7, 1),
        eps=28.98, financials_source="BSE", financials_as_of=date(2026, 8, 4),
    ))
    assert p["source"] == "BSE"
    assert p["as_of"] == "2026-07-01"
    assert p["financials_source"] == "BSE"
    assert p["financials_as_of"] == "2026-08-04"


def test_null_ratios_are_omitted_not_zeroed():
    p = fundamentals_payload(_co(
        official_sector="Energy", eps=28.98, roe=None,
        financials_source="BSE", financials_as_of=date(2026, 8, 4),
    ))
    assert "roe" not in p["ratios"]
    assert p["ratios"]["eps"] == 28.98


def test_classification_without_ratios_omits_the_ratios_key():
    p = fundamentals_payload(_co(official_sector="Energy"))
    assert p["classification"]["sector"] == "Energy"
    assert "ratios" not in p
    assert "consolidated" not in p


def test_no_classification_yields_none():
    assert fundamentals_payload(_co()) is None


def test_exact_zero_is_treated_as_bses_not_published_sentinel():
    """Reverses an earlier decision that kept published 0.00 values. BSE
    writes literal "0.00" into slots it has no figure for -- verified live
    2026-08-05: L&T's consolidated OPM/NPM came back 0.00 next to standalone
    margins of 16.68/12.37, and rendering them produced exactly the
    fake-looking numbers this payload exists to prevent. At BSE's 2-decimal
    precision a genuine break-even 0.00 is indistinguishable from the
    sentinel, so omission is the honest reading either way."""
    p = fundamentals_payload(_co(
        official_sector="Energy", npm=0.0, con_opm=0.0, con_npm=0.0,
        eps=28.98, con_eps=142.64,
        financials_source="BSE", financials_as_of=date(2026, 8, 4),
    ))
    assert "npm" not in p["ratios"]
    assert p["ratios"]["eps"] == 28.98
    assert p["consolidated"] == {"eps": 142.64}


def test_negative_ratios_are_real_and_kept():
    """Loss-making companies exist; a negative EPS or margin is a fact, not
    a sentinel, and dropping it would hide exactly the companies where the
    number matters most."""
    p = fundamentals_payload(_co(
        official_sector="Energy", eps=-4.31, npm=-2.05,
        financials_source="BSE", financials_as_of=date(2026, 8, 4),
    ))
    assert p["ratios"]["eps"] == -4.31
    assert p["ratios"]["npm"] == -2.05
