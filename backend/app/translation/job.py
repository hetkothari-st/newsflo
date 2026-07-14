import json
import logging
import queue
import threading
import time
from dataclasses import dataclass

from sqlalchemy import func
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
from app.translation.languages import TARGET_LANGS, has_expected_script

logger = logging.getLogger(__name__)

# A row that keeps failing (bad content, model keeps refusing the schema)
# stops being retried after this many attempts -- the silent English
# fallback in app/translation/lookup.py serves it indefinitely regardless.
MAX_TRANSLATION_ATTEMPTS = 5


@dataclass
class _AlertSnapshot:
    alert_id: int
    article_id: int
    title: str
    content: str
    companies: list[dict]  # [{"id": int, "rationale": str, "key_points": list[str]}]


def _snapshot_alert(alert: Alert) -> _AlertSnapshot:
    return _AlertSnapshot(
        alert_id=alert.id,
        article_id=alert.article_id,
        title=alert.article.title,
        content=alert.article.content,
        companies=[
            {"id": ac.id, "rationale": ac.rationale, "key_points": decode_key_points(ac)}
            for ac in alert.companies
        ],
    )


def _missing_langs(session: Session, alert: Alert) -> list[str]:
    """Languages this specific alert still needs. Checked per-ALERT, not
    per-article: `Article.alerts` is a list relationship, so the schema
    allows more than one Alert row to share the same article_id (confirmed
    in production: two distinct alerts pointing at article_id=410, each
    with their own AlertCompany rows). Checking only "does the article have
    a translation" would let one alert's translation count as done for a
    sibling alert's entirely different AlertCompany rows, permanently
    skipping their company translations since this function is the sole
    definition of "pending"."""
    article_translated_langs = {
        row[0] for row in session.query(ArticleTranslation.lang).filter_by(article_id=alert.article_id)
    }
    company_ids = [ac.id for ac in alert.companies]
    if not company_ids:
        return [lang for lang in TARGET_LANGS if lang not in article_translated_langs]
    fully_translated_company_langs = {
        row[0]
        for row in (
            session.query(AlertCompanyTranslation.lang)
            .filter(AlertCompanyTranslation.alert_company_id.in_(company_ids))
            .group_by(AlertCompanyTranslation.lang)
            .having(func.count(AlertCompanyTranslation.alert_company_id) >= len(company_ids))
        )
    }
    fully_done_langs = article_translated_langs & fully_translated_company_langs
    return [lang for lang in TARGET_LANGS if lang not in fully_done_langs]


def _pending_alert_lang_pairs(
    session: Session, max_pairs: int, lang: str | None = None
) -> list[tuple[_AlertSnapshot, str]]:
    """Every (alert, language) translation still outstanding, newest alert
    first (a live feed cares more about recent stories), each alert
    contributing its still-missing languages in TARGET_LANGS order -- or,
    when `lang` is given, only that one language's missing pairs (used by
    the on-demand translate-now trigger to drain exactly the language a
    viewer just switched to, instead of spreading calls across every
    language they aren't looking at).

    Alerts are snapshotted into plain data here, on the caller's thread,
    while the ORM objects are still safe to touch -- callers must never pass
    a raw `Alert` into a worker thread (see translate_pending_alerts).

    Capped at `max_pairs` TRANSLATION CALLS, not alerts -- translation is one
    call per (alert, language) (see groq_translator.translate_alert's
    docstring for why a combined multi-language call doesn't fit a
    rate-limited provider's per-minute token budget), so this is what
    actually bounds token usage, regardless of how that work happens to be
    distributed across alerts.
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
    pairs: list[tuple[_AlertSnapshot, str]] = []
    for alert in alerts:
        missing = [
            missing_lang
            for missing_lang in _missing_langs(session, alert)
            if lang is None or missing_lang == lang
        ]
        if not missing:
            continue
        snapshot = _snapshot_alert(alert)
        for missing_lang in missing:
            pairs.append((snapshot, missing_lang))
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


def _fetch_translation(client, snapshot: _AlertSnapshot, lang: str) -> dict:
    """Pure network I/O, safe to run concurrently on a worker thread -- reads
    only the plain-data snapshot, never the ORM Alert/AlertCompany objects
    and never touches the SQLAlchemy session."""
    return translate_alert(
        client,
        lang=lang,
        title=snapshot.title,
        content=snapshot.content,
        companies=[{"rationale": c["rationale"], "key_points": c["key_points"]} for c in snapshot.companies],
    )


def _validate_and_persist(session: Session, snapshot: _AlertSnapshot, lang: str, translated: dict) -> None:
    # A non-trivial title translated byte-identical to the English source is
    # essentially never correct across a different script -- confirmed in
    # production this model occasionally just echoes the input through a
    # forced tool call instead of actually translating it (about 1 in 4
    # calls before the system prompt was strengthened to explicitly forbid
    # it; residual risk still exists). Treat it as a failure so it's
    # retried next run rather than permanently caching untranslated text.
    title = snapshot.title
    if "title" not in translated or "companies" not in translated:
        raise ValueError(f"lang={lang} response missing required field(s): {translated.keys()}")
    if len(title.strip()) > 3 and translated["title"].strip() == title.strip():
        raise ValueError(f"lang={lang} returned an untranslated (English-identical) title")
    # A response that isn't byte-identical to the English source can still be
    # wrong in a different way -- confirmed in production the model
    # sometimes returns Romanized/Hinglish transliteration (no native-script
    # characters at all) or, once, an entirely different language (Japanese)
    # when asked for Hindi. Both pass the identity check above but are not a
    # real translation into the requested language either.
    if len(title.strip()) > 3 and not has_expected_script(lang, translated["title"]):
        raise ValueError(f"lang={lang} returned text with no characters in the expected script")
    translated_companies = translated["companies"]
    # The model is only asked (via prompt + schema minItems/maxItems) to
    # keep this array the same length/order as the input -- that is not
    # enforced by tool-calling the way a schema `const`/index binding
    # would be, especially on FALLBACK_MODEL (documented in
    # groq_translator.py as less schema-reliable at scale). A silent length
    # mismatch would zip translated text onto the WRONG AlertCompany row
    # with no error -- raise instead, so it's caught by the caller and
    # recorded as an ordinary translation failure.
    if len(translated_companies) != len(snapshot.companies):
        raise ValueError(
            f"lang={lang} returned {len(translated_companies)} companies, expected {len(snapshot.companies)}"
        )
    # Two Alert rows can share one article_id (see _missing_langs) and both
    # be queued for the same lang in the same batch -- each independently
    # translates the (identical) article title/content, but only the first
    # to commit should persist it; a second INSERT would violate the
    # (article_id, lang) unique constraint.
    already_has_article_translation = (
        session.query(ArticleTranslation.id)
        .filter_by(article_id=snapshot.article_id, lang=lang)
        .first()
        is not None
    )
    if not already_has_article_translation:
        session.add(ArticleTranslation(
            article_id=snapshot.article_id,
            lang=lang,
            title=translated["title"],
            content=translated["content"],
        ))
    # Company translations need the same check-before-insert guard: the
    # on-demand translate-now endpoint (routers/translation.py) and the
    # periodic scheduler job can both decide this (alert_company_id, lang)
    # pair is still missing and race to insert it -- confirmed in
    # production (a UniqueViolation on uq_alert_company_translation_lang
    # aborted the whole pair's commit, including the article title/content
    # that would otherwise have persisted fine, permanently stalling that
    # alert's translation until TranslationFailure attempts ran out).
    existing_company_langs = {
        row[0]
        for row in session.query(AlertCompanyTranslation.alert_company_id).filter(
            AlertCompanyTranslation.alert_company_id.in_([c["id"] for c in snapshot.companies]),
            AlertCompanyTranslation.lang == lang,
        )
    }
    for company, tc in zip(snapshot.companies, translated_companies):
        if company["id"] in existing_company_langs:
            continue
        session.add(AlertCompanyTranslation(
            alert_company_id=company["id"],
            lang=lang,
            rationale=tc["rationale"],
            key_points_json=json.dumps(tc["key_points"]),
        ))
    session.commit()


def translate_pending_alerts(
    session: Session,
    clients,
    limit: int = 15,
    throttle_seconds: float = 0,
    lang: str | None = None,
) -> int:
    """Make up to `limit` (alert, language) translation calls, resuming each
    alert from whichever languages it's still missing. Used by the
    recurring scheduler job (small `limit`, `lang=None` to cover every
    language), the one-time historical backfill script (looped with a
    larger `limit` until it returns 0), and the on-demand translate-now
    endpoint (`lang` set to whichever language a viewer just switched to,
    so that language finishes first instead of competing with the other
    8) -- "pending" is defined identically in every case, so there is no
    separate code path for "new" vs "historical" vs "on-demand" alerts.

    `clients` is a single client OR a list -- see
    groq_translator.build_translation_clients. Each entry becomes its own
    LANE: pending pairs are split round-robin across lanes, and each lane
    runs its share sequentially in its own thread (with `throttle_seconds`
    slept between that lane's own calls, so a rate-limited provider's
    per-minute budget is respected PER LANE). Lanes run concurrently with
    each other. On Groq, pass one key per lane from a genuinely SEPARATE
    account (separate quota bucket) or lanes just fight over the same
    budget instead of adding real throughput. On Anthropic, all lanes share
    one client/account safely (no per-minute wall at this scale).

    Every lane only performs the network call (translate_alert) -- ORM
    objects and the SQLAlchemy session are NOT thread-safe, so DB writes for
    every lane's results happen back on THIS thread only, consumed off a
    shared queue as they arrive. Each (alert, language) call commits
    independently, so a failure on one language never discards progress
    already made on that alert's other languages -- the next run picks up
    exactly where this one left off.
    """
    if not isinstance(clients, list):
        clients = [clients]
    pairs = _pending_alert_lang_pairs(session, limit, lang=lang)
    if not pairs:
        return 0

    lanes = [pairs[i::len(clients)] for i in range(len(clients))]
    results: queue.Queue = queue.Queue()

    def _run_lane(client, lane_pairs):
        for snapshot, alert_lang in lane_pairs:
            try:
                translated = _fetch_translation(client, snapshot, alert_lang)
                results.put((snapshot, alert_lang, translated, None))
            except Exception as exc:
                results.put((snapshot, alert_lang, None, exc))
            if throttle_seconds:
                time.sleep(throttle_seconds)

    threads = [
        threading.Thread(target=_run_lane, args=(clients[i], lane_pairs), daemon=True)
        for i, lane_pairs in enumerate(lanes)
        if lane_pairs
    ]
    for t in threads:
        t.start()

    completed = 0
    for _ in range(len(pairs)):
        snapshot, alert_lang, translated, fetch_error = results.get()
        try:
            if fetch_error is not None:
                raise fetch_error
            _validate_and_persist(session, snapshot, alert_lang, translated)
            completed += 1
        except Exception as exc:
            session.rollback()
            _record_failure(session, snapshot.alert_id, exc)
            logger.exception("Translation failed for alert_id=%s lang=%s", snapshot.alert_id, alert_lang)

    for t in threads:
        t.join()
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
