from app.filtering.heuristic import classify_category, filter_new_articles
from app.models import Article


def test_classify_category_matches_oil_keyword():
    assert classify_category("US strikes Iran oil export sites", "") == "oil_energy"


def test_classify_category_returns_none_for_irrelevant_text():
    assert classify_category("Local bakery wins award", "") is None


def test_classify_category_no_match_substring_war_in_award():
    # Prefix-match boundary still prevents "war" matching inside "award"
    assert classify_category("Local bakery wins award", "") is None


def test_classify_category_matches_plural_sanctions():
    # Plural form "sanctions" should match keyword "sanction"
    assert classify_category("Government imposes new sanctions on firms", "") == "geopolitics"


def test_classify_category_matches_plural_tariffs():
    # Plural form "tariffs" should match keyword "tariff"
    assert classify_category("Officials announce fresh tariffs on imports", "") == "geopolitics"


def test_classify_category_no_false_positive_warning():
    # "war" keyword must not match inside "warning" (kept keyword-neutral so the
    # new market_news keywords, e.g. "profit", don't confound this boundary check)
    assert classify_category("Security team issues a warning about phishing", "") is None


def test_classify_category_matches_market_news_profit_warning():
    # A profit warning is genuine market-moving news -- should now be caught by
    # the broader market_news category rather than silently filtered out.
    assert classify_category("Company issues profit warning", "") == "market_news"


def test_classify_category_no_false_positive_warehouse():
    # "war" keyword must not match inside "warehouse"
    assert classify_category("New warehouse opens in Pune", "") is None


def test_classify_category_no_false_positive_ward():
    # "war" keyword must not match inside "ward"
    assert classify_category("Ward elections held", "") is None


def test_classify_category_matches_market_news_dividend():
    assert classify_category("Bharti Airtel fixes record date for its highest-ever dividend", "") == "market_news"


def test_classify_category_matches_market_news_shares_crash():
    assert classify_category("Dr Reddy's shares crash 9% in 2 days", "") == "market_news"


def test_filter_new_articles_updates_status(db_session):
    relevant = Article(source="test", url="https://example.com/1", title="RBI hikes repo rate", content="")
    irrelevant = Article(source="test", url="https://example.com/2", title="Cat stuck in tree", content="")
    db_session.add_all([relevant, irrelevant])
    db_session.commit()

    filter_new_articles(db_session)

    db_session.refresh(relevant)
    db_session.refresh(irrelevant)
    assert relevant.status == "CATEGORIZED"
    assert relevant.category == "banking"
    assert irrelevant.status == "FILTERED"
