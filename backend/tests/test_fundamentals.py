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
    assert p["as_of"] == "2026-08-04"


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


def test_real_zero_ratio_is_included_not_dropped():
    """BSE sends "0.00" for some margins -- a real published 0.0 is a value
    and must survive, unlike an omitted-because-None ratio. `if value` would
    wrongly treat 0.0 as falsy and drop it; the filter must check `is not
    None`."""
    p = fundamentals_payload(_co(
        official_sector="Energy", npm=0.0, eps=28.98,
        financials_source="BSE", financials_as_of=date(2026, 8, 4),
    ))
    assert p["ratios"]["npm"] == 0.0
    assert "npm" in p["ratios"]
