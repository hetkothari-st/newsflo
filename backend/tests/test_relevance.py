from types import SimpleNamespace

from app.filtering.relevance import classify_relevance


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
