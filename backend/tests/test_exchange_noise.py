"""Exchange-announcement noise gate. Same test bias as test_prefilter.py:
the load-bearing assertions are the ones proving real disclosures are NEVER
rejected -- a false positive silently deletes a story from the feed."""
from app.filtering.exchange_noise import (
    ADMIT,
    NOISE,
    exchange_noise_verdict,
    is_exchange_noise,
)

# (source_category, title) pairs that are mechanically produced non-news.
CLEAR_NOISE = [
    ("Declaration of NAV", "ICICI Prudential Nifty 50 ETF"),
    ("Trading Window-XBRL", "AVRO INDIA LIMITED: Closure of Trading Window"),
    ("Closure of Trading Window", "Addictive Learning: Trading Window"),
    ("Copy of Newspaper Publication", "PNC Infratech: newspaper advertisement"),
    ("Record Date Updates", "Nashik Municipal Corporation: Record Date Updates"),
    ("Notice Of Shareholders Meetings-XBRL", "Rico Auto: AGM notice"),
]

# Real disclosures that must ALWAYS admit, whatever else matches.
REAL_DISCLOSURES = [
    ("Awarding of order(s)/contract(s)", "United Drilling Tools: Awarding of order(s)/contract(s)"),
    ("Outcome of Board Meeting", "Ramco Industries: financial results for period ended Jun 30"),
    ("Acquisition", "Leela Palaces: Disclosure under Regulation 30 - Acquisition"),
    ("Credit Rating- Revision", "Premier Polyfilm: Credit Rating Revision"),
    ("Press Release", "Bharti Airtel: Airtel Business and ITI strategic partnership"),
    ("Alteration Of Capital and Fund Raising-XBRL", "Kaya Limited: Issuance of securities"),
]


def test_noise_categories_are_rejected():
    for category, title in CLEAR_NOISE:
        verdict, reason = exchange_noise_verdict(category, title)
        assert verdict == NOISE, f"{category!r} should be noise ({reason})"


def test_real_disclosures_always_admit():
    for category, title in REAL_DISCLOSURES:
        verdict, reason = exchange_noise_verdict(category, title)
        assert verdict == ADMIT, f"{category!r} must admit ({reason})"


def test_signal_category_wins_over_noise_in_compound_category():
    # Signal check runs first: a compound category naming both admits.
    verdict, _ = exchange_noise_verdict("Outcome of Board Meeting / Record Date", "Results and record date")
    assert verdict == ADMIT


def test_unrecognised_category_admits_by_default():
    verdict, _ = exchange_noise_verdict("Some Brand New Category", "Anything")
    assert verdict == ADMIT


def test_title_fallback_when_no_category():
    verdict, _ = exchange_noise_verdict(None, "Declaration of Net Asset Value as on August 07, 2026")
    assert verdict == NOISE
    # Record-date pattern carries the financial-signal veto: a real story
    # mentioning a dividend record date admits.
    verdict, _ = exchange_noise_verdict(
        None, "Record date for dividend announced", "Board declared dividend of Rs 5 after record quarterly results",
    )
    assert verdict == ADMIT


def test_gate_only_applies_to_exchange_providers():
    # A Moneycontrol story about record dates is real news.
    assert not is_exchange_noise("moneycontrol", None, "Record date for RIL bonus issue", mode="enforce")
    assert is_exchange_noise("nse", "Declaration of NAV", "Some ETF", mode="enforce")


def test_shadow_mode_never_rejects():
    assert not is_exchange_noise("nse", "Declaration of NAV", "Some ETF", mode="shadow")
    assert not is_exchange_noise("bse", "Trading Window", "X Ltd", mode="off")
