import pytest

from app.companies.matching import aliases, matcher
from app.models import Company


@pytest.fixture()
def universe(db_session):
    rows = [
        ("RELIANCE.NS", "Reliance Industries Limited", "oil_gas", "INE002A01018", "NORMAL"),
        ("APOLLOTYRE.NS", "Apollo Tyres Limited", "auto", "INE438A01022", "NORMAL"),
        ("APOLLOHOSP.NS", "Apollo Hospitals Enterprise Limited", "pharma", "INE437A01024", "NORMAL"),
        ("BHARATGEAR.NS", "Bharat Gears Limited", "auto", "INE561A01011", "NORMAL"),
        ("BHARATSEAT.NS", "Bharat Seats Limited", "auto", "INE785A01026", "NORMAL"),
        ("SBIN.NS", "State Bank of India", "banking", "INE062A01020", "NORMAL"),
        ("SBICARD.NS", "SBI Cards and Payment Services Limited", "banking", "INE018E01016", "NORMAL"),
        ("SHELL.BO", "Reliance Industries Limited", "other", "INE999Z01099", "SUSPENDED"),
        ("TENNIND.NS", "Tenneco Clean Air India Limited", "auto", "INE999T01011", "NORMAL"),
    ]
    for ticker, name, sector, isin, tradeability in rows:
        db_session.add(Company(
            ticker=ticker, name=name, sector=sector, index_tier="OTHER",
            isin=isin, tradeability=tradeability,
        ))
    db_session.commit()
    aliases.rebuild_aliases(db_session)
    return db_session


def _company_id(session, ticker):
    return session.query(Company).filter_by(ticker=ticker).one().id


def test_exact_ticker_wins(universe):
    result = matcher.resolve(universe, ticker="APOLLOTYRE.NS", name=None)
    assert result.company_id == _company_id(universe, "APOLLOTYRE.NS")
    assert result.method == "ticker"


def test_isin_match(universe):
    result = matcher.resolve(universe, ticker=None, name=None, isin="INE437A01024")
    assert result.company_id == _company_id(universe, "APOLLOHOSP.NS")
    assert result.method == "isin"


def test_alias_exact_match(universe):
    result = matcher.resolve(universe, ticker=None, name="Apollo Tyres Ltd")
    assert result.company_id == _company_id(universe, "APOLLOTYRE.NS")
    assert result.method == "alias"


def test_token_set_match_ignores_word_order(universe):
    result = matcher.resolve(universe, ticker=None, name="Tyres Apollo Limited")
    assert result.company_id == _company_id(universe, "APOLLOTYRE.NS")
    assert result.method == "token_set"


def test_apollo_alone_is_ambiguous_and_returns_none(universe):
    assert matcher.resolve(universe, ticker=None, name="Apollo") is None


def test_bharat_collision_does_not_mismatch(universe):
    result = matcher.resolve(universe, ticker=None, name="Bharat Gears")
    assert result.company_id == _company_id(universe, "BHARATGEAR.NS")


def test_bare_bharat_returns_none(universe):
    assert matcher.resolve(universe, ticker=None, name="Bharat") is None


def test_sbi_does_not_match_sbi_cards(universe):
    result = matcher.resolve(universe, ticker=None, name="SBI Cards")
    assert result.company_id == _company_id(universe, "SBICARD.NS")


def test_unknown_name_returns_none(universe):
    assert matcher.resolve(universe, ticker=None, name="Totally Fictional Corp") is None


def test_unknown_ticker_falls_through_to_name(universe):
    result = matcher.resolve(universe, ticker="WRONG.NS", name="Apollo Tyres Limited")
    assert result.company_id == _company_id(universe, "APOLLOTYRE.NS")


def test_normal_company_beats_suspended_shell_on_identical_name(universe):
    result = matcher.resolve(universe, ticker=None, name="Reliance Industries Limited")
    assert result.company_id == _company_id(universe, "RELIANCE.NS")
    assert result.method.endswith("tradeability_tiebreak")


def test_empty_input_returns_none(universe):
    assert matcher.resolve(universe, ticker=None, name=None) is None
    assert matcher.resolve(universe, ticker="", name="  ") is None


# --- Regression lock: no token-subset rung. ---
#
# A token-subset rung ("every mention token appears in some alias's token
# set") was added and reverted during review. At the real 507-company
# universe, 488 of 718 distinct alias tokens belong to exactly ONE company
# and are not themselves an exact alias -- so a subset rung resolves with
# false confidence on bare/short mentions, and the hazard gets worse (not
# better) as the universe grows toward ~4,967. "Air India" matching
# Tenneco's "Tenneco Clean Air India" and a bare "cards" matching SBI Cards
# are two of the reviewer's real examples. These tests exist so nobody
# re-adds subset matching without confronting this failure mode again.

def test_air_india_mention_does_not_match_single_subset_company(universe):
    # "Air India" is a token-subset of ONLY "Tenneco Clean Air India" in
    # this fixture -- exactly the unprotected case (no colliding alias to
    # force the ambiguity rule to kick in). A subset rung would return a
    # confident wrong match here; the ladder without it must return None.
    assert matcher.resolve(universe, ticker=None, name="Air India") is None


def test_bare_cards_mention_does_not_match_sbi_cards(universe):
    # A bare, generic word that happens to be one token of a curated trade
    # name ("SBI Cards") must not resolve on its own.
    assert matcher.resolve(universe, ticker=None, name="cards") is None
