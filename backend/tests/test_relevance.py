from types import SimpleNamespace

from app.filtering.relevance import classify_relevance, filter_new_articles
from app.models import Article


def _fake_client(response_text: str):
    def create(**kwargs):
        message = SimpleNamespace(content=response_text)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def _raising_client():
    def create(**kwargs):
        raise RuntimeError("api error")
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def test_classify_relevance_true_on_yes():
    assert classify_relevance(_fake_client("YES"), "RBI hikes repo rate", "") is True


def test_classify_relevance_false_on_no():
    assert classify_relevance(_fake_client("NO"), "Cat stuck in tree", "") is False


def test_classify_relevance_tolerates_case_and_whitespace():
    assert classify_relevance(_fake_client("  yes  "), "t", "c") is True
    assert classify_relevance(_fake_client("No."), "t", "c") is False


def test_classify_relevance_fails_open_on_client_exception():
    # Load-bearing: dropping a real story silently is worse than one
    # wasted downstream analysis call on a false positive.
    assert classify_relevance(_raising_client(), "t", "c") is True


def test_classify_relevance_fails_open_on_garbled_response():
    assert classify_relevance(_fake_client(""), "t", "c") is False
    assert classify_relevance(_fake_client("maybe"), "t", "c") is False


def test_filter_new_articles_categorizes_relevant_and_filters_irrelevant(db_session, monkeypatch):
    relevant = Article(source="test", url="https://example.com/1", title="RBI hikes repo rate", content="")
    irrelevant = Article(source="test", url="https://example.com/2", title="Cat stuck in tree", content="")
    db_session.add_all([relevant, irrelevant])
    db_session.commit()

    def fake_classify(client, title, content):
        return title == "RBI hikes repo rate"
    monkeypatch.setattr("app.filtering.relevance.classify_relevance", fake_classify)

    filter_new_articles(db_session, client=object())

    db_session.refresh(relevant)
    db_session.refresh(irrelevant)
    assert relevant.status == "CATEGORIZED"
    assert relevant.category is None
    assert irrelevant.status == "FILTERED"


def test_filter_new_articles_uses_full_content_when_available(db_session, monkeypatch):
    article = Article(
        source="test", url="https://example.com/1", title="t",
        content="short summary", full_content="the real full article text",
    )
    db_session.add(article)
    db_session.commit()

    captured = {}
    def fake_classify(client, title, content):
        captured["content"] = content
        return True
    monkeypatch.setattr("app.filtering.relevance.classify_relevance", fake_classify)

    filter_new_articles(db_session, client=object())

    assert captured["content"] == "the real full article text"


def test_filter_new_articles_only_touches_new_articles(db_session, monkeypatch):
    already_analyzed = Article(
        source="test", url="https://example.com/1", title="t", content="c", status="ANALYZED",
    )
    db_session.add(already_analyzed)
    db_session.commit()

    call_count = {"n": 0}
    def counting_classify(client, title, content):
        call_count["n"] += 1
        return True
    monkeypatch.setattr("app.filtering.relevance.classify_relevance", counting_classify)

    filter_new_articles(db_session, client=object())

    assert call_count["n"] == 0
