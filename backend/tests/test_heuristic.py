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
