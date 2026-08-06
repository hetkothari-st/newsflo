import json
from types import SimpleNamespace

import httpx
import pytest
from openai import RateLimitError

from app.filtering.relevance import (
    RelevanceRateLimited, classify_relevance, filter_new_articles, is_rate_limit_error,
)
from app.models import Article


class _FakeToolCall:
    def __init__(self, name: str, arguments: dict):
        self.function = SimpleNamespace(name=name, arguments=json.dumps(arguments))


def _fake_client(relevant: bool):
    def create(**kwargs):
        message = SimpleNamespace(tool_calls=[_FakeToolCall("record_relevance", {"relevant": relevant})])
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def _no_tool_call_client():
    def create(**kwargs):
        message = SimpleNamespace(tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def _malformed_client():
    def create(**kwargs):
        message = SimpleNamespace(tool_calls=[_FakeToolCall("record_relevance", {})])
        # Force malformed JSON regardless of the dict above.
        message.tool_calls[0].function.arguments = '{"relevant": tru'
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def _raising_client():
    def create(**kwargs):
        raise RuntimeError("api error")
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def test_classify_relevance_true_on_relevant():
    assert classify_relevance(_fake_client(True), "RBI hikes repo rate", "") is True


def test_classify_relevance_false_on_irrelevant():
    assert classify_relevance(_fake_client(False), "Cat stuck in tree", "") is False


def test_classify_relevance_fails_open_on_client_exception():
    # Load-bearing: dropping a real story silently is worse than one
    # wasted downstream analysis call on a false positive.
    assert classify_relevance(_raising_client(), "t", "c") is True


def test_classify_relevance_fails_open_when_no_tool_call_returned():
    assert classify_relevance(_no_tool_call_client(), "t", "c") is True


def test_classify_relevance_fails_open_on_malformed_arguments():
    assert classify_relevance(_malformed_client(), "t", "c") is True


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


# --- rate limit: leave the article NEW, do not admit it ---
#
# Admitting on a rate limit is what produced 31 ANALYSIS_FAILED articles in
# a single measured day: the article proceeds to full analysis, which is ~7
# more calls against the quota that just ran out, so those fail too and the
# article lands in a status nothing revisits. Leaving it NEW costs nothing
# and the next scheduler tick retries it.

def _rate_limit_error() -> RateLimitError:
    request = httpx.Request("POST", "https://example.test/v1/chat/completions")
    response = httpx.Response(status_code=429, request=request)
    return RateLimitError("rate limited", response=response, body=None)


def _rate_limited_client():
    def create(**kwargs):
        raise _rate_limit_error()
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def test_is_rate_limit_error_recognises_openai_rate_limit():
    assert is_rate_limit_error(_rate_limit_error()) is True


def test_is_rate_limit_error_recognises_flat_provider_errors_by_message():
    # AnthropicAPIError/GeminiAPIError are flat types covering every
    # provider-level failure, so the message is the only signal available.
    class GeminiAPIError(Exception):
        pass
    assert is_rate_limit_error(GeminiAPIError("429 RESOURCE_EXHAUSTED: quota exceeded")) is True
    assert is_rate_limit_error(GeminiAPIError("500 internal error")) is False


def test_is_rate_limit_error_is_false_for_ordinary_errors():
    assert is_rate_limit_error(RuntimeError("api error")) is False
    assert is_rate_limit_error(ValueError("malformed json")) is False


def test_classify_relevance_raises_on_rate_limit_instead_of_admitting():
    with pytest.raises(RelevanceRateLimited):
        classify_relevance(_rate_limited_client(), "RBI hikes repo rate", "c")


def test_classify_relevance_still_fails_open_on_every_other_error():
    # Load-bearing: only the rate-limit case changed. A transient 500 or a
    # malformed response must still admit the article.
    assert classify_relevance(_raising_client(), "t", "c") is True


def test_rate_limited_article_stays_new(db_session):
    article = Article(source="test", url="https://example.com/1", title="Modi seeks sweeping tax cuts", content="c")
    db_session.add(article)
    db_session.commit()

    filter_new_articles(db_session, _rate_limited_client())

    db_session.refresh(article)
    assert article.status == "NEW", "a rate-limited article must be neither filtered nor admitted"


def test_rate_limit_stops_further_llm_calls_in_the_same_run(db_session):
    for n in range(4):
        db_session.add(Article(source="test", url=f"https://example.com/{n}", title=f"Bank raises rate {n}", content="c"))
    db_session.commit()

    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        raise _rate_limit_error()
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    filter_new_articles(db_session, client)

    assert len(calls) == 1, "once quota is gone the run must stop spending calls"
    assert [a.status for a in db_session.query(Article).all()] == ["NEW"] * 4


def test_rate_limited_run_does_not_reprocess_within_the_same_run(db_session, monkeypatch):
    # The loop iterates a materialised snapshot, so an article left as NEW
    # is not picked up again by this run -- guards against an infinite loop
    # if the query were ever made live.
    db_session.add(Article(source="test", url="https://example.com/1", title="Bank raises rate", content="c"))
    db_session.commit()

    seen = []
    def classify(client, title, content):
        seen.append(title)
        raise RelevanceRateLimited("quota exhausted")
    monkeypatch.setattr("app.filtering.relevance.classify_relevance", classify)

    filter_new_articles(db_session, client=object())

    assert seen == ["Bank raises rate"]


def test_rate_limit_does_not_stop_the_free_deterministic_gates(db_session, monkeypatch):
    # Junk still costs nothing to reject, so a dead provider is no reason to
    # carry it into the next tick.
    junk = Article(source="test", url="https://example.com/1", title="Form 8.3 - [ACME PLC - 04 08 2026] - (CGWL)", content="Ordinary Shares.")
    real = Article(source="test", url="https://example.com/2", title="Bank raises rate", content="c")
    db_session.add_all([junk, real])
    db_session.commit()

    filter_new_articles(db_session, _rate_limited_client())

    db_session.refresh(junk)
    db_session.refresh(real)
    assert junk.status == "FILTERED"
    assert real.status == "NEW"


def test_filter_new_articles_throttles_between_articles(db_session, monkeypatch):
    a1 = Article(source="test", url="https://example.com/1", title="t1", content="c")
    a2 = Article(source="test", url="https://example.com/2", title="t2", content="c")
    db_session.add_all([a1, a2])
    db_session.commit()

    sleep_calls = []
    monkeypatch.setattr("app.filtering.relevance.time.sleep", lambda s: sleep_calls.append(s))

    filter_new_articles(db_session, client=object(), throttle_seconds=0.01)

    assert sleep_calls == [0.01, 0.01]
