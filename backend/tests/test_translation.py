import json
from types import SimpleNamespace

from app.models import (
    Alert,
    AlertCompany,
    AlertCompanyTranslation,
    Article,
    ArticleTranslation,
    CategoryTranslation,
    TranslationFailure,
)
from app.translation.groq_translator import translate_alert, translate_categories
from app.translation.job import (
    MAX_TRANSLATION_ATTEMPTS,
    translate_pending_alerts,
    translate_pending_categories,
)
from app.translation.languages import TARGET_LANGS, normalize_lang
from app.translation.lookup import (
    bulk_alert_company_translations,
    bulk_article_titles,
    bulk_category_labels,
)


def _per_lang_payload(num_companies: int, suffix: str) -> dict:
    return {
        "title": f"title-{suffix}",
        "content": f"content-{suffix}",
        "companies": [
            {"rationale": f"rationale-{suffix}-{i}", "key_points": [f"kp-{suffix}-{i}"]}
            for i in range(num_companies)
        ],
    }


class FakeToolCallClient:
    """Mirrors test_claude_client.py's FakeClient/FakeCompletions shape."""

    def __init__(self, tool_name: str, arguments: dict):
        self._tool_name = tool_name
        self._arguments = arguments
        self.last_kwargs = None

    def _create(self, **kwargs):
        self.last_kwargs = kwargs
        tool_call = SimpleNamespace(
            function=SimpleNamespace(name=self._tool_name, arguments=json.dumps(self._arguments))
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

def test_translate_alert_returns_all_target_languages():
    arguments = {lang: _per_lang_payload(1, lang) for lang in TARGET_LANGS}
    client = FakeToolCallClient("record_translations", arguments)

    result = translate_alert(
        client, title="US strikes Iran oil sites", content="crude reacts",
        companies=[{"rationale": "refiner margin", "key_points": ["a"]}],
    )

    assert set(result.keys()) == set(TARGET_LANGS)
    assert result["hi"]["title"] == "title-hi"
    assert result["hi"]["companies"][0]["rationale"] == "rationale-hi-0"


def test_translate_alert_raises_on_missing_tool_call():
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **kw: SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[]))])
    )))
    try:
        translate_alert(client, title="t", content="c", companies=[])
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "t" in str(exc)


def test_translate_categories_returns_all_target_languages():
    arguments = {lang: [f"label-{lang}-a", f"label-{lang}-b"] for lang in TARGET_LANGS}
    client = FakeToolCallClient("record_category_translations", arguments)

    result = translate_categories(client, ["oil_energy", "banking"])

    assert result["hi"] == ["label-hi-a", "label-hi-b"]


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
    arguments = {lang: _per_lang_payload(1, lang) for lang in TARGET_LANGS}
    client = FakeToolCallClient("record_translations", arguments)

    translated = translate_pending_alerts(db_session, client, limit=10)

    assert translated == 1
    rows = db_session.query(ArticleTranslation).filter_by(article_id=alert.article_id).all()
    assert {r.lang for r in rows} == set(TARGET_LANGS)
    ac = db_session.query(AlertCompany).filter_by(alert_id=alert.id).one()
    company_rows = db_session.query(AlertCompanyTranslation).filter_by(alert_company_id=ac.id).all()
    assert {r.lang for r in company_rows} == set(TARGET_LANGS)


def test_translate_pending_alerts_skips_already_translated(db_session):
    alert = _seed_alert(db_session)
    arguments = {lang: _per_lang_payload(1, lang) for lang in TARGET_LANGS}
    client = FakeToolCallClient("record_translations", arguments)
    translate_pending_alerts(db_session, client, limit=10)

    # Second run should find nothing pending -- article already has translations.
    second_count = translate_pending_alerts(db_session, client, limit=10)

    assert second_count == 0
    assert not hasattr(alert, "_unused")  # no-op assertion just to use `alert`


def test_translate_pending_alerts_records_failure_on_company_count_mismatch(db_session):
    # A response whose per-language companies array doesn't match the input
    # count must never be zipped positionally onto the wrong AlertCompany
    # row -- it should be treated as a failure like any other malformed
    # response, not silently persisted.
    _seed_alert(db_session)
    arguments = {lang: _per_lang_payload(0, lang) for lang in TARGET_LANGS}  # 0 companies, expected 1
    client = FakeToolCallClient("record_translations", arguments)

    translated = translate_pending_alerts(db_session, client, limit=10)

    assert translated == 0
    assert db_session.query(ArticleTranslation).count() == 0
    assert db_session.query(AlertCompanyTranslation).count() == 0
    failure = db_session.query(TranslationFailure).one()
    assert "expected 1" in failure.last_error


def test_translate_pending_alerts_records_failure_and_retries_next_run(db_session):
    _seed_alert(db_session)
    client = BoomClient()

    translated = translate_pending_alerts(db_session, client, limit=10)

    assert translated == 0
    failure = db_session.query(TranslationFailure).one()
    assert failure.attempts == 1
    assert "groq down" in failure.last_error


def test_translate_pending_alerts_stops_retrying_after_max_attempts(db_session):
    alert = _seed_alert(db_session)
    db_session.add(TranslationFailure(alert_id=alert.id, attempts=MAX_TRANSLATION_ATTEMPTS))
    db_session.commit()
    client = BoomClient()

    translated = translate_pending_alerts(db_session, client, limit=10)

    assert translated == 0
    # BoomClient would have raised if it were called -- attempts unchanged
    # confirms the exhausted alert was excluded from the pending query, not
    # retried and re-failed.
    failure = db_session.query(TranslationFailure).filter_by(alert_id=alert.id).one()
    assert failure.attempts == MAX_TRANSLATION_ATTEMPTS


def test_translate_pending_categories_discards_batch_on_label_count_mismatch(db_session):
    article = Article(source="test", url="https://example.com/cat-mismatch", title="t")
    db_session.add(article)
    db_session.commit()
    db_session.add(Alert(article_id=article.id, category="oil_energy"))
    db_session.commit()

    # hi returns 1 label as expected, but mr returns 0 -- the whole batch
    # must be discarded rather than persisting hi's labels alone (which
    # would make _pending_categories's canary-lang check inconsistent with
    # what's actually fully translated).
    arguments = {lang: (["तेल"] if lang == "hi" else []) for lang in TARGET_LANGS}
    client = FakeToolCallClient("record_category_translations", arguments)

    count = translate_pending_categories(db_session, client, batch_size=10)

    assert count == 0
    assert db_session.query(CategoryTranslation).count() == 0


def test_translate_pending_categories_persists_all_languages(db_session):
    article = Article(source="test", url="https://example.com/cat-job", title="t")
    db_session.add(article)
    db_session.commit()
    db_session.add(Alert(article_id=article.id, category="oil_energy"))
    db_session.commit()

    arguments = {lang: ["तेल"] for lang in TARGET_LANGS}
    client = FakeToolCallClient("record_category_translations", arguments)

    count = translate_pending_categories(db_session, client, batch_size=10)

    assert count == 1
    rows = db_session.query(CategoryTranslation).filter_by(category="oil_energy").all()
    assert {r.lang for r in rows} == set(TARGET_LANGS)


def test_translate_pending_categories_no_op_when_nothing_pending(db_session):
    client = BoomClient()  # would raise if called -- proves it's never called
    assert translate_pending_categories(db_session, client, batch_size=10) == 0
