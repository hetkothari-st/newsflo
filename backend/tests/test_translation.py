import json
import threading
from types import SimpleNamespace

import pytest

from app.models import (
    Alert,
    AlertCompany,
    AlertCompanyTranslation,
    Article,
    ArticleTranslation,
    CategoryTranslation,
    TranslationFailure,
)
from app.translation import groq_translator, nllb_translator
from app.translation.groq_translator import translate_alert, translate_categories
from app.translation.job import (
    MAX_TRANSLATION_ATTEMPTS,
    translate_pending_alerts,
    translate_pending_categories,
)
from app.translation.languages import SCRIPT_RANGES, TARGET_LANGS, normalize_lang
from app.translation.lookup import (
    bulk_alert_company_translations,
    bulk_article_titles,
    bulk_category_labels,
)


@pytest.fixture(autouse=True)
def _force_groq_provider(monkeypatch):
    """Every test in this file below exercises the Groq/Anthropic
    tool-calling mechanics via a fake client -- force TRANSLATION_PROVIDER
    back to "groq" for the duration of each test regardless of the
    production default (see nllb dispatch tests further down, which
    explicitly set it to "nllb" themselves)."""
    monkeypatch.setattr(groq_translator, "TRANSLATION_PROVIDER", "groq")

# One sample character from every target language's native script, so a
# single canned fake-client payload passes job.py's has_expected_script
# guard no matter which of the 9 languages it's used to "translate" into --
# tests here care about persistence/resumption/failure-handling logic, not
# script-content realism (that's exercised for real in production, not with
# a fake client returning the same string for every call).
_ALL_SCRIPTS_MARKER = "".join(chr(lo + 1) for lo, _hi in SCRIPT_RANGES.values())


def _payload(num_companies: int, suffix: str) -> dict:
    return {
        "title": f"title-{suffix} {_ALL_SCRIPTS_MARKER}",
        "content": f"content-{suffix} {_ALL_SCRIPTS_MARKER}",
        "companies": [
            {"rationale": f"rationale-{suffix}-{i}", "key_points": [f"kp-{suffix}-{i}"]}
            for i in range(num_companies)
        ],
    }


class FakeToolCallClient:
    """Mirrors test_claude_client.py's FakeClient/FakeCompletions shape.
    Returns the SAME canned response for every call -- fine for most tests
    since translate_alert/translate_categories now take an explicit `lang`
    argument per call rather than returning a dict keyed by every language
    at once.

    translate_pending_alerts now fans its calls out across a thread pool
    (see MAX_CONCURRENT_TRANSLATIONS in job.py), so this fake's own state
    must be thread-safe too -- a bare `self.call_count += 1` is a
    read-modify-write that can lose increments under real concurrency.
    """

    def __init__(self, tool_name: str, arguments: dict):
        self._tool_name = tool_name
        self._arguments = arguments
        self.last_kwargs = None
        self.call_count = 0
        self._lock = threading.Lock()

    def _create(self, **kwargs):
        with self._lock:
            self.last_kwargs = kwargs
            self.call_count += 1
        tool_call = SimpleNamespace(
            function=SimpleNamespace(name=self._tool_name, arguments=json.dumps(self._arguments))
        )
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[tool_call]))])

    @property
    def chat(self):
        return SimpleNamespace(completions=SimpleNamespace(create=self._create))


class SequentialToolCallClient:
    """Returns a different canned response on each successive call, in
    order -- for tests where per-call output must vary (e.g. one language
    succeeds, the next is malformed)."""

    def __init__(self, tool_name: str, responses: list[dict]):
        self._tool_name = tool_name
        self._responses = list(responses)
        self.call_count = 0

    def _create(self, **kwargs):
        arguments = self._responses[self.call_count]
        self.call_count += 1
        tool_call = SimpleNamespace(
            function=SimpleNamespace(name=self._tool_name, arguments=json.dumps(arguments))
        )
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[tool_call]))])

    @property
    def chat(self):
        return SimpleNamespace(completions=SimpleNamespace(create=self._create))


class BoomClient:
    def _create(self, **kwargs):
        raise RuntimeError("groq down")

    @property
    def chat(self):
        return SimpleNamespace(completions=SimpleNamespace(create=self._create))


# --- languages.py -----------------------------------------------------------

def test_normalize_lang_passes_through_supported():
    assert normalize_lang("hi") == "hi"


def test_normalize_lang_falls_back_to_english_for_unknown():
    assert normalize_lang("xx") == "en"
    assert normalize_lang(None) == "en"


# --- groq_translator.py ------------------------------------------------------

def test_translate_alert_returns_one_language():
    client = FakeToolCallClient("record_translation", _payload(1, "hi"))

    result = translate_alert(
        client, lang="hi", title="US strikes Iran oil sites", content="crude reacts",
        companies=[{"rationale": "refiner margin", "key_points": ["a"]}],
    )

    assert result["title"] == f"title-hi {_ALL_SCRIPTS_MARKER}"
    assert result["companies"][0]["rationale"] == "rationale-hi-0"


def test_translate_alert_raises_on_missing_tool_call():
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **kw: SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[]))])
    )))
    try:
        translate_alert(client, lang="hi", title="t", content="c", companies=[])
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "t" in str(exc)


def test_translate_categories_returns_labels_for_one_language():
    client = FakeToolCallClient("record_category_translations", {"labels": ["label-a", "label-b"]})

    result = translate_categories(client, "hi", ["oil_energy", "banking"])

    assert result == ["label-a", "label-b"]


# --- lookup.py ----------------------------------------------------------------

def test_bulk_lookups_return_empty_for_english(db_session):
    assert bulk_article_titles(db_session, [1, 2], "en") == {}
    assert bulk_alert_company_translations(db_session, [1, 2], "en") == {}
    assert bulk_category_labels(db_session, ["oil_energy"], "en") == {}


def test_bulk_lookups_fall_back_silently_when_row_missing(db_session):
    # No ArticleTranslation/AlertCompanyTranslation/CategoryTranslation rows
    # exist at all -- callers get an empty dict and must fall back to English
    # themselves (that's what routers do via `.get(id, english_value)`).
    assert bulk_article_titles(db_session, [1], "hi") == {}
    assert bulk_category_labels(db_session, ["oil_energy"], "hi") == {}


def test_bulk_lookups_return_translated_rows_when_present(db_session):
    article = Article(source="test", url="https://example.com/tr", title="English title")
    db_session.add(article)
    db_session.commit()
    db_session.add(ArticleTranslation(article_id=article.id, lang="hi", title="हिंदी शीर्षक", content=""))
    db_session.add(CategoryTranslation(category="oil_energy", lang="hi", label="तेल और ऊर्जा"))
    db_session.commit()

    titles = bulk_article_titles(db_session, [article.id], "hi")
    labels = bulk_category_labels(db_session, ["oil_energy"], "hi")

    assert titles[article.id] == "हिंदी शीर्षक"
    assert labels["oil_energy"] == "तेल और ऊर्जा"


# --- job.py ---------------------------------------------------------------

def _seed_alert(db_session) -> Alert:
    article = Article(source="test", url="https://example.com/job", title="English title", content="body")
    db_session.add(article)
    db_session.commit()
    alert = Alert(article_id=article.id, category="oil_energy")
    db_session.add(alert)
    db_session.commit()
    db_session.add(AlertCompany(
        alert_id=alert.id, company_id=1, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="english rationale",
        key_points_json='["point one"]', basis="direct_mention",
    ))
    db_session.commit()
    db_session.refresh(alert)
    return alert


def test_translate_pending_alerts_persists_all_languages(db_session):
    alert = _seed_alert(db_session)
    client = FakeToolCallClient("record_translation", _payload(1, "x"))

    # limit >= len(TARGET_LANGS) so every (alert, language) pair for this
    # one alert fits in a single call.
    completed = translate_pending_alerts(db_session, client, limit=len(TARGET_LANGS))

    assert completed == len(TARGET_LANGS)
    rows = db_session.query(ArticleTranslation).filter_by(article_id=alert.article_id).all()
    assert {r.lang for r in rows} == set(TARGET_LANGS)
    ac = db_session.query(AlertCompany).filter_by(alert_id=alert.id).one()
    company_rows = db_session.query(AlertCompanyTranslation).filter_by(alert_company_id=ac.id).all()
    assert {r.lang for r in company_rows} == set(TARGET_LANGS)


def test_translate_pending_alerts_splits_work_across_multiple_clients(db_session):
    # Passing a list of clients (e.g. one per independent-account Groq key)
    # must round-robin pending pairs across all of them, not just use the
    # first -- this is how a second account's quota bucket actually gets
    # used instead of sitting idle.
    _seed_alert(db_session)
    client_a = FakeToolCallClient("record_translation", _payload(1, "a"))
    client_b = FakeToolCallClient("record_translation", _payload(1, "b"))

    completed = translate_pending_alerts(db_session, [client_a, client_b], limit=len(TARGET_LANGS))

    assert completed == len(TARGET_LANGS)
    assert client_a.call_count > 0
    assert client_b.call_count > 0
    assert client_a.call_count + client_b.call_count == len(TARGET_LANGS)


def test_translate_pending_alerts_handles_two_alerts_sharing_one_article(db_session):
    # Article.alerts is a list relationship -- the schema allows more than
    # one Alert row to point at the same article_id (confirmed in
    # production). Both alerts' own AlertCompany rows must still get
    # translated, and persisting the (identical) article title/content
    # twice must not raise a unique-constraint error.
    article = Article(source="test", url="https://example.com/shared", title="English title", content="body")
    db_session.add(article)
    db_session.commit()

    first_alert = Alert(article_id=article.id, category="oil_energy")
    second_alert = Alert(article_id=article.id, category="oil_energy")
    db_session.add_all([first_alert, second_alert])
    db_session.commit()
    db_session.add(AlertCompany(
        alert_id=first_alert.id, company_id=1, direction="bullish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="first alert rationale",
        key_points_json='["a"]', basis="direct_mention",
    ))
    db_session.add(AlertCompany(
        alert_id=second_alert.id, company_id=2, direction="bearish",
        magnitude_low=1.0, magnitude_high=2.0, rationale="second alert rationale",
        key_points_json='["b"]', basis="direct_mention",
    ))
    db_session.commit()

    client = FakeToolCallClient("record_translation", _payload(1, "x"))
    # limit big enough to cover both alerts' full language sets in one call.
    completed = translate_pending_alerts(db_session, client, limit=2 * len(TARGET_LANGS))

    assert completed == 2 * len(TARGET_LANGS)
    # Only ever one ArticleTranslation row per (article, lang) -- no
    # IntegrityError, no duplicate.
    article_rows = db_session.query(ArticleTranslation).filter_by(article_id=article.id).all()
    assert len(article_rows) == len(TARGET_LANGS)

    first_ac = db_session.query(AlertCompany).filter_by(alert_id=first_alert.id).one()
    second_ac = db_session.query(AlertCompany).filter_by(alert_id=second_alert.id).one()
    first_company_langs = {
        r.lang for r in db_session.query(AlertCompanyTranslation).filter_by(alert_company_id=first_ac.id)
    }
    second_company_langs = {
        r.lang for r in db_session.query(AlertCompanyTranslation).filter_by(alert_company_id=second_ac.id)
    }
    assert first_company_langs == set(TARGET_LANGS)
    assert second_company_langs == set(TARGET_LANGS)


def test_translate_pending_alerts_resumes_from_missing_languages_only(db_session):
    alert = _seed_alert(db_session)
    client = FakeToolCallClient("record_translation", _payload(1, "x"))

    # Translate just one language first...
    first = translate_pending_alerts(db_session, client, limit=1)
    assert first == 1
    assert client.call_count == 1

    # ...then finish the rest -- only the remaining (len(TARGET_LANGS) - 1)
    # languages should need a call, not all of them again.
    second = translate_pending_alerts(db_session, client, limit=len(TARGET_LANGS))
    assert second == len(TARGET_LANGS) - 1
    assert client.call_count == len(TARGET_LANGS)

    rows = db_session.query(ArticleTranslation).filter_by(article_id=alert.article_id).all()
    assert {r.lang for r in rows} == set(TARGET_LANGS)


def test_translate_pending_alerts_skips_already_translated(db_session):
    _seed_alert(db_session)
    client = FakeToolCallClient("record_translation", _payload(1, "x"))
    translate_pending_alerts(db_session, client, limit=len(TARGET_LANGS))

    # Second run should find nothing pending -- article already has translations.
    second_count = translate_pending_alerts(db_session, client, limit=len(TARGET_LANGS))

    assert second_count == 0


def test_translate_pending_alerts_records_failure_on_company_count_mismatch(db_session):
    # A response whose companies array doesn't match the input count must
    # never be zipped positionally onto the wrong AlertCompany row -- it
    # should be treated as a failure like any other malformed response.
    _seed_alert(db_session)
    client = FakeToolCallClient("record_translation", _payload(0, "x"))  # 0 companies, expected 1

    completed = translate_pending_alerts(db_session, client, limit=1)

    assert completed == 0
    assert db_session.query(ArticleTranslation).count() == 0
    assert db_session.query(AlertCompanyTranslation).count() == 0
    failure = db_session.query(TranslationFailure).one()
    assert "expected 1" in failure.last_error


def test_translate_pending_alerts_records_failure_and_retries_next_run(db_session):
    _seed_alert(db_session)
    client = BoomClient()

    translate_pending_alerts(db_session, client, limit=1)
    failure = db_session.query(TranslationFailure).one()
    assert failure.attempts == 1
    assert "groq down" in failure.last_error

    translate_pending_alerts(db_session, client, limit=1)
    db_session.refresh(failure)
    assert failure.attempts == 2


def test_translate_pending_alerts_stops_retrying_after_max_attempts(db_session):
    alert = _seed_alert(db_session)
    db_session.add(TranslationFailure(alert_id=alert.id, attempts=MAX_TRANSLATION_ATTEMPTS))
    db_session.commit()
    client = BoomClient()

    completed = translate_pending_alerts(db_session, client, limit=10)

    assert completed == 0
    # BoomClient would have raised if it were called -- attempts unchanged
    # confirms the exhausted alert was excluded from the pending query, not
    # retried and re-failed.
    failure = db_session.query(TranslationFailure).filter_by(alert_id=alert.id).one()
    assert failure.attempts == MAX_TRANSLATION_ATTEMPTS


def test_translate_pending_alerts_can_restrict_to_one_language(db_session):
    alert = _seed_alert(db_session)
    client = FakeToolCallClient("record_translation", _payload(1, "x"))

    completed = translate_pending_alerts(db_session, client, limit=len(TARGET_LANGS), lang="hi")

    assert completed == 1
    rows = db_session.query(ArticleTranslation).filter_by(article_id=alert.article_id).all()
    assert {r.lang for r in rows} == {"hi"}


def test_translate_pending_categories_persists_one_language_at_a_time(db_session):
    article = Article(source="test", url="https://example.com/cat-job", title="t")
    db_session.add(article)
    db_session.commit()
    db_session.add(Alert(article_id=article.id, category="oil_energy"))
    db_session.commit()

    client = FakeToolCallClient("record_category_translations", {"labels": ["तेल"]})

    # Default max_langs=2 -- only the first 2 pending languages get a call.
    count = translate_pending_categories(db_session, client, batch_size=10)

    assert count == 2
    rows = db_session.query(CategoryTranslation).filter_by(category="oil_energy").all()
    assert len(rows) == 2
    assert {r.lang for r in rows} == set(TARGET_LANGS[:2])


def test_translate_pending_categories_one_bad_language_does_not_block_a_good_one(db_session):
    article = Article(source="test", url="https://example.com/cat-mismatch", title="t")
    db_session.add(article)
    db_session.commit()
    db_session.add(Alert(article_id=article.id, category="oil_energy"))
    db_session.commit()

    # First pending language (TARGET_LANGS[0]) gets a correct single-label
    # response; the second gets a malformed (wrong count) response.
    client = SequentialToolCallClient(
        "record_category_translations", [{"labels": ["तेल"]}, {"labels": []}]
    )

    count = translate_pending_categories(db_session, client, batch_size=10)

    # Only the first (good) language's row persists -- the failing language
    # doesn't roll it back, and doesn't stop translate_pending_categories
    # from having made progress.
    assert count == 1
    rows = db_session.query(CategoryTranslation).filter_by(category="oil_energy").all()
    assert [r.lang for r in rows] == [TARGET_LANGS[0]]


def test_translate_pending_categories_no_op_when_nothing_pending(db_session):
    client = BoomClient()  # would raise if called -- proves it's never called
    assert translate_pending_categories(db_session, client, batch_size=10) == 0


def test_translate_pending_categories_can_restrict_to_one_language(db_session):
    article = Article(source="test", url="https://example.com/cat-restrict", title="t")
    db_session.add(article)
    db_session.commit()
    db_session.add(Alert(article_id=article.id, category="oil_energy"))
    db_session.commit()

    client = FakeToolCallClient("record_category_translations", {"labels": ["तेल"]})

    count = translate_pending_categories(db_session, client, batch_size=10, lang="mr")

    assert count == 1
    rows = db_session.query(CategoryTranslation).filter_by(category="oil_energy").all()
    assert [r.lang for r in rows] == ["mr"]


# --- nllb provider dispatch (groq_translator.py) -----------------------------

def test_translate_alert_dispatches_to_nllb_when_provider_is_nllb(monkeypatch):
    monkeypatch.setattr(groq_translator, "TRANSLATION_PROVIDER", "nllb")
    captured = {}

    def fake_translate_alert(*, lang, title, content, companies):
        captured["kwargs"] = dict(lang=lang, title=title, content=content, companies=companies)
        return {"title": "translated", "content": "translated", "companies": []}

    monkeypatch.setattr(nllb_translator, "translate_alert", fake_translate_alert)

    result = translate_alert(
        None, lang="hi", title="T", content="C", companies=[{"rationale": "r", "key_points": ["k"]}]
    )

    assert result == {"title": "translated", "content": "translated", "companies": []}
    assert captured["kwargs"] == {
        "lang": "hi", "title": "T", "content": "C",
        "companies": [{"rationale": "r", "key_points": ["k"]}],
    }


def test_translate_categories_dispatches_to_nllb_and_expands_underscores(monkeypatch):
    monkeypatch.setattr(groq_translator, "TRANSLATION_PROVIDER", "nllb")
    captured = {}

    def fake_translate_categories(phrases, lang):
        captured["phrases"] = phrases
        captured["lang"] = lang
        return ["translated-a", "translated-b"]

    monkeypatch.setattr(nllb_translator, "translate_categories", fake_translate_categories)

    result = translate_categories(None, "hi", ["oil_energy", "banking"])

    assert result == ["translated-a", "translated-b"]
    assert captured["phrases"] == ["Oil Energy", "Banking"]
    assert captured["lang"] == "hi"


# --- nllb_translator.py -------------------------------------------------------

def test_nllb_split_sentences_splits_on_boundary_before_capital():
    text = "HDFC Bank posted 18% growth. Kotak Mahindra Bank also gained 3.5%."
    assert nllb_translator._split_sentences(text) == [
        "HDFC Bank posted 18% growth.", "Kotak Mahindra Bank also gained 3.5%.",
    ]


def test_nllb_split_sentences_returns_empty_for_blank_text():
    assert nllb_translator._split_sentences("") == []
    assert nllb_translator._split_sentences("   ") == []


def test_nllb_translate_alert_reassembles_fields_in_flattened_order(monkeypatch):
    # Stub out the actual model call and just echo back a marker for every
    # input sentence, in order -- this test is about translate_alert's
    # flatten/take bookkeeping (title, content, each company's rationale
    # sentences, each company's key_points) being sliced back onto the
    # right field in the right order, not about real translation quality.
    def fake_translate_sentences(sentences, lang_code):
        assert lang_code == "hin_Deva"
        return [f"[{s}]" for s in sentences]

    monkeypatch.setattr(nllb_translator, "_translate_sentences", fake_translate_sentences)

    result = nllb_translator.translate_alert(
        lang="hi",
        title="Title sentence.",
        content="First content sentence. Second content sentence.",
        companies=[
            {"rationale": "Rationale one. Rationale two.", "key_points": ["kp1", "kp2"]},
            {"rationale": "Only rationale.", "key_points": ["kp3"]},
        ],
    )

    assert result["title"] == "[Title sentence.]"
    assert result["content"] == "[First content sentence.] [Second content sentence.]"
    assert result["companies"][0]["rationale"] == "[Rationale one.] [Rationale two.]"
    assert result["companies"][0]["key_points"] == ["[kp1]", "[kp2]"]
    assert result["companies"][1]["rationale"] == "[Only rationale.]"
    assert result["companies"][1]["key_points"] == ["[kp3]"]


def test_nllb_translate_categories_translates_batch_without_splitting(monkeypatch):
    def fake_translate_sentences(sentences, lang_code):
        assert lang_code == "mar_Deva"
        return [f"[{s}]" for s in sentences]

    monkeypatch.setattr(nllb_translator, "_translate_sentences", fake_translate_sentences)

    result = nllb_translator.translate_categories(["Oil Energy", "Banking"], "mr")

    assert result == ["[Oil Energy]", "[Banking]"]
