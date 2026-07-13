import json
import logging
import time

from sqlalchemy.orm import Session

from app.models import (
    Alert,
    AlertCompanyTranslation,
    Article,
    ArticleTranslation,
    CategoryTranslation,
    TranslationFailure,
    utcnow,
)
from app.pipeline import decode_key_points
from app.translation.groq_translator import translate_alert, translate_categories
from app.translation.languages import TARGET_LANGS

logger = logging.getLogger(__name__)

# A row that keeps failing (bad content, model keeps refusing the schema)
# stops being retried after this many attempts -- the silent English
# fallback in app/translation/lookup.py serves it indefinitely regardless.
MAX_TRANSLATION_ATTEMPTS = 5


def _missing_langs(session: Session, article_id: int) -> list[str]:
    existing = {
        row[0] for row in session.query(ArticleTranslation.lang).filter_by(article_id=article_id)
    }
    return [lang for lang in TARGET_LANGS if lang not in existing]


def _pending_alert_lang_pairs(
    session: Session, max_pairs: int, lang: str | None = None
) -> list[tuple[Alert, str]]:
    """Every (alert, language) translation still outstanding, newest alert
    first (a live feed cares more about recent stories), each alert
    contributing its still-missing languages in TARGET_LANGS order -- or,
    when `lang` is given, only that one language's missing pairs (used by
    the on-demand translate-now trigger to drain exactly the language a
    viewer just switched to, instead of spreading calls across every
    language they aren't looking at).

    Capped at `max_pairs` GROQ CALLS, not alerts -- translation is one call
    per (alert, language) (see groq_translator.translate_alert's docstring
    for why a combined multi-language call doesn't fit Groq's per-minute
    token budget), so this is what actually bounds token usage, regardless
    of how that work happens to be distributed across alerts.
    """
    exhausted_alert_ids = session.query(TranslationFailure.alert_id).filter(
        TranslationFailure.attempts >= MAX_TRANSLATION_ATTEMPTS
    )
    alerts = (
        session.query(Alert)
        .join(Article, Alert.article_id == Article.id)
        .filter(~Alert.id.in_(exhausted_alert_ids))
        .order_by(Alert.created_at.desc())
        .all()
    )
    pairs: list[tuple[Alert, str]] = []
    for alert in alerts:
        for missing_lang in _missing_langs(session, alert.article_id):
            if lang is not None and missing_lang != lang:
                continue
            pairs.append((alert, missing_lang))
            if len(pairs) >= max_pairs:
                return pairs
    return pairs


def _record_failure(session: Session, alert_id: int, error: Exception) -> None:
    failure = session.query(TranslationFailure).filter_by(alert_id=alert_id).first()
    if failure is None:
        failure = TranslationFailure(alert_id=alert_id, attempts=0)
        session.add(failure)
    failure.attempts += 1
    failure.last_error = str(error)
    failure.last_attempted_at = utcnow()
    session.commit()


def _translate_one_alert_lang(session: Session, alert: Alert, lang: str, client) -> None:
    companies = alert.companies
    title = alert.article.title
    translated = translate_alert(
        client,
        lang=lang,
        title=title,
        content=alert.article.content,
        companies=[
            {"rationale": ac.rationale, "key_points": decode_key_points(ac)} for ac in companies
        ],
    )
    # A non-trivial title translated byte-identical to the English source is
    # essentially never correct across a different script -- confirmed in
    # production this model occasionally just echoes the input through a
    # forced tool call instead of actually translating it (about 1 in 4
    # calls before the system prompt was strengthened to explicitly forbid
    # it; residual risk still exists). Treat it as a failure so it's
    # retried next run rather than permanently caching untranslated text.
    if len(title.strip()) > 3 and translated["title"].strip() == title.strip():
        raise ValueError(f"lang={lang} returned an untranslated (English-identical) title")
    translated_companies = translated["companies"]
    # The model is only asked (via prompt + schema minItems/maxItems) to
    # keep this array the same length/order as the input -- that is not
    # enforced by tool-calling the way a schema `const`/index binding
    # would be, especially on FALLBACK_MODEL (documented in
    # groq_translator.py as less schema-reliable at scale). A silent length
    # mismatch would zip translated text onto the WRONG AlertCompany row
    # with no error -- raise instead, so it's caught by the caller and
    # recorded as an ordinary translation failure.
    if len(translated_companies) != len(companies):
        raise ValueError(
            f"lang={lang} returned {len(translated_companies)} companies, expected {len(companies)}"
        )
    session.add(ArticleTranslation(
        article_id=alert.article_id,
        lang=lang,
        title=translated["title"],
        content=translated["content"],
    ))
    for ac, tc in zip(companies, translated_companies):
        session.add(AlertCompanyTranslation(
            alert_company_id=ac.id,
            lang=lang,
            rationale=tc["rationale"],
            key_points_json=json.dumps(tc["key_points"]),
        ))
    session.commit()


def translate_pending_alerts(
    session: Session, client, limit: int = 15, throttle_seconds: float = 0, lang: str | None = None
) -> int:
    """Make up to `limit` (alert, language) Groq translation calls, resuming
    each alert from whichever languages it's still missing. Used by the
    recurring scheduler job (small `limit`, `lang=None` to cover every
    language), the one-time historical backfill script (looped with a
    larger `limit` until it returns 0), and the on-demand translate-now
    endpoint (`lang` set to whichever language a viewer just switched to,
    so that language finishes first instead of competing with the other
    8) -- "pending" is defined identically in every case, so there is no
    separate code path for "new" vs "historical" vs "on-demand" alerts.

    Each (alert, language) call commits independently, so a failure on one
    language never discards progress already made on that alert's other
    languages -- the next run picks up exactly where this one left off.
    """
    completed = 0
    for alert, alert_lang in _pending_alert_lang_pairs(session, limit, lang=lang):
        try:
            _translate_one_alert_lang(session, alert, alert_lang, client)
            completed += 1
        except Exception as exc:
            session.rollback()
            _record_failure(session, alert.id, exc)
            logger.exception("Translation failed for alert_id=%s lang=%s", alert.id, alert_lang)
        time.sleep(throttle_seconds)
    return completed


def _pending_categories_for_lang(session: Session, lang: str, limit: int) -> list[str]:
    translated = session.query(CategoryTranslation.category).filter(CategoryTranslation.lang == lang)
    rows = (
        session.query(Alert.category)
        .filter(~Alert.category.in_(translated))
        .distinct()
        .limit(limit)
        .all()
    )
    return [row[0] for row in rows]


def translate_pending_categories(
    session: Session,
    client,
    batch_size: int = 25,
    max_langs: int = 2,
    throttle_seconds: float = 0,
    lang: str | None = None,
) -> int:
    """Translate any category strings not yet covered, one language at a
    time, up to `max_langs` GROQ CALLS per invocation -- or, when `lang` is
    given, only that one language (used by the on-demand translate-now
    endpoint). Category translations are keyed by the category string
    itself (shared across every alert with that category), so in steady
    state this fires almost never -- distinct category strings rarely
    change once the historical backlog is drained. Batching multiple
    categories into one call per language (rather than one call per
    category) stays well under Groq's per-minute token cap since category
    strings are short, unlike per-alert translation which needed splitting
    to one call per language.

    `max_langs` bounds how many of these (cheap, but still real) Groq calls
    happen in a single invocation -- right after a fresh deploy every
    language is simultaneously pending for every existing category, so
    without a cap this would fire one call per TARGET_LANGS language back to
    back and risk the same TPM rejection per-alert translation hit before
    being split (see groq_translator.translate_alert's docstring).
    """
    total = 0
    calls_made = 0
    langs_to_check = [lang] if lang is not None else TARGET_LANGS
    for lang_code in langs_to_check:
        if calls_made >= max_langs:
            break
        categories = _pending_categories_for_lang(session, lang_code, batch_size)
        if not categories:
            continue
        calls_made += 1
        try:
            labels = translate_categories(client, lang_code, categories)
        except Exception:
            logger.exception(
                "Category translation failed for lang=%s, batch of %s categories", lang_code, len(categories)
            )
            time.sleep(throttle_seconds)
            continue
        if len(labels) != len(categories):
            logger.error(
                "Category translation lang=%s returned %s labels, expected %s -- skipping batch",
                lang_code, len(labels), len(categories),
            )
            time.sleep(throttle_seconds)
            continue
        for category, label in zip(categories, labels):
            session.add(CategoryTranslation(category=category, lang=lang_code, label=label))
        session.commit()
        total += len(categories)
        time.sleep(throttle_seconds)
    return total
