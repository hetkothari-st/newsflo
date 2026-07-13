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

# All TARGET_LANGS languages are always written atomically together for one alert (a
# single successful translate_alert call fans out into 7 ArticleTranslation +
# 7*N AlertCompanyTranslation rows in one go) -- so checking whether ONE
# language's row exists is a reliable, cheap proxy for "this alert is fully
# translated", not just partially.
CANARY_LANG = TARGET_LANGS[0]

# A row that keeps failing (bad content, model keeps refusing the schema)
# stops being retried after this many attempts -- the silent English
# fallback in app/translation/lookup.py serves it indefinitely regardless.
MAX_TRANSLATION_ATTEMPTS = 5


def _pending_alerts(session: Session, limit: int) -> list[Alert]:
    translated_article_ids = session.query(ArticleTranslation.article_id).filter(
        ArticleTranslation.lang == CANARY_LANG
    )
    exhausted_alert_ids = session.query(TranslationFailure.alert_id).filter(
        TranslationFailure.attempts >= MAX_TRANSLATION_ATTEMPTS
    )
    return (
        session.query(Alert)
        .join(Article, Alert.article_id == Article.id)
        .filter(~Article.id.in_(translated_article_ids))
        .filter(~Alert.id.in_(exhausted_alert_ids))
        .order_by(Alert.created_at.desc())
        .limit(limit)
        .all()
    )


def _record_failure(session: Session, alert_id: int, error: Exception) -> None:
    failure = session.query(TranslationFailure).filter_by(alert_id=alert_id).first()
    if failure is None:
        failure = TranslationFailure(alert_id=alert_id, attempts=0)
        session.add(failure)
    failure.attempts += 1
    failure.last_error = str(error)
    failure.last_attempted_at = utcnow()
    session.commit()


def _translate_one_alert(session: Session, alert: Alert, client) -> None:
    companies = alert.companies
    result = translate_alert(
        client,
        title=alert.article.title,
        content=alert.article.content,
        companies=[
            {"rationale": ac.rationale, "key_points": decode_key_points(ac)} for ac in companies
        ],
    )
    for lang in TARGET_LANGS:
        per_lang = result[lang]
        session.add(ArticleTranslation(
            article_id=alert.article_id,
            lang=lang,
            title=per_lang["title"],
            content=per_lang["content"],
        ))
        translated_companies = per_lang["companies"]
        # The model is only asked (via prompt + schema minItems/maxItems) to
        # keep this array the same length/order as the input -- that is not
        # enforced by tool-calling the way a schema `const`/index binding
        # would be, especially on FALLBACK_MODEL (documented elsewhere as
        # less schema-reliable). A silent length mismatch would zip
        # translated text onto the WRONG AlertCompany row with no error --
        # raise instead, so it's caught and recorded as an ordinary
        # translation failure like any other malformed response.
        if len(translated_companies) != len(companies):
            raise ValueError(
                f"lang={lang} returned {len(translated_companies)} companies, expected {len(companies)}"
            )
        for ac, translated in zip(companies, translated_companies):
            session.add(AlertCompanyTranslation(
                alert_company_id=ac.id,
                lang=lang,
                rationale=translated["rationale"],
                key_points_json=json.dumps(translated["key_points"]),
            ))
    session.commit()


def translate_pending_alerts(session: Session, client, limit: int = 15, throttle_seconds: float = 0) -> int:
    """Translate up to `limit` alerts that don't have full translation
    coverage yet. Used by both the recurring scheduler job (small `limit`,
    ongoing coverage of newly-ingested alerts) and the one-time historical
    backfill script (looped with a larger `limit` until it returns 0) --
    "pending" is defined identically for both: an alert whose article has no
    translation rows yet, so there is no separate code path for "new" vs
    "historical" alerts.
    """
    translated = 0
    for alert in _pending_alerts(session, limit):
        try:
            _translate_one_alert(session, alert, client)
            translated += 1
        except Exception as exc:
            session.rollback()
            _record_failure(session, alert.id, exc)
            logger.exception("Translation failed for alert_id=%s", alert.id)
        time.sleep(throttle_seconds)
    return translated


def _pending_categories(session: Session, limit: int) -> list[str]:
    translated = session.query(CategoryTranslation.category).filter(
        CategoryTranslation.lang == CANARY_LANG
    )
    rows = (
        session.query(Alert.category)
        .filter(~Alert.category.in_(translated))
        .distinct()
        .limit(limit)
        .all()
    )
    return [row[0] for row in rows]


def translate_pending_categories(session: Session, client, batch_size: int = 25) -> int:
    """Translate any category strings not yet covered in all of TARGET_LANGS.
    Category translations are keyed by the category string itself (shared
    across every alert with that category), so in steady state this fires
    almost never -- distinct category strings rarely change once the
    historical backlog is drained."""
    categories = _pending_categories(session, batch_size)
    if not categories:
        return 0
    try:
        result = translate_categories(client, categories)
    except Exception:
        logger.exception("Category translation failed for batch of %s categories", len(categories))
        return 0
    for lang in TARGET_LANGS:
        translated_labels = result[lang]
        # Same order/count trust issue as translate_alert's companies array
        # (see the comment in _translate_one_alert) -- a silent length
        # mismatch would zip a label onto the wrong category.
        if len(translated_labels) != len(categories):
            session.rollback()  # discard any earlier-language rows already added this batch
            logger.error(
                "Category translation lang=%s returned %s labels, expected %s -- skipping batch",
                lang, len(translated_labels), len(categories),
            )
            return 0
        for category, label in zip(categories, translated_labels):
            session.add(CategoryTranslation(category=category, lang=lang, label=label))
    session.commit()
    return len(categories)
