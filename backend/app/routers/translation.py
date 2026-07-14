import logging
import threading

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.config import settings
from app.i18n import get_lang
from app.models import Alert, Article, ArticleTranslation
from app.routers.articles import get_db
from app.translation.groq_translator import (
    RECOMMENDED_THROTTLE_SECONDS,
    TRANSLATION_PROVIDER,
    build_translation_client,
    build_translation_clients,
)
from app.translation.job import translate_pending_alerts, translate_pending_categories

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/translation", tags=["translation"])

# In-memory only -- "is a drain already running for this language" is a
# same-process concern (one dev/single-instance deployment, matches the
# rest of the app's assumptions), not something that needs to survive a
# restart. A GET /status poll racing a POST /run that hasn't updated this
# set yet just means one extra harmless duplicate drain gets kicked off.
_running_langs: set[str] = set()
_lock = threading.Lock()

# On-demand translation targets only the most recent ON_DEMAND_ALERT_LIMIT
# alerts (newest-first, same ordering translate_pending_alerts already
# uses) rather than draining the entire historical backlog synchronously --
# a full backlog is hundreds of alerts, which would take way too long,
# defeating the point of an on-demand switch. The rest of the backlog keeps
# getting covered by the periodic scheduler job at its own pace. /status
# reports progress against this same bounded count so the progress bar can
# actually reach 100%.
#
# Bounded much lower on Groq: each lane is sequential with a ~20s throttle
# between calls (see RECOMMENDED_THROTTLE_SECONDS) -- 40 alerts on ONE lane
# would take 13+ minutes. Scales with the number of independent-account
# lanes available (see translate_pending_alerts/build_translation_clients),
# so adding another separate-account Groq key raises this bound too.
# Anthropic's real single-account concurrency affords a bigger batch outright.
# NLLB has no per-minute cap and each (alert, lang) call completes in a few
# seconds on CPU, so a viewer switching languages can wait for a much
# bigger slice of the backlog to finish without the progress bar taking
# unreasonably long.
if TRANSLATION_PROVIDER == "nllb":
    ON_DEMAND_ALERT_LIMIT = 150
elif TRANSLATION_PROVIDER == "groq":
    ON_DEMAND_ALERT_LIMIT = 10 * max(1, len(settings.translation_groq_api_keys))
else:
    ON_DEMAND_ALERT_LIMIT = 40


def _drain_language(lang: str) -> None:
    from app.db import SessionLocal  # local import: avoids import cost when unused

    session = SessionLocal()
    try:
        client = build_translation_client(settings.groq_api_keys, settings.anthropic_api_key or None)
        # Categories first (cheap, unblocks category_label everywhere at
        # once) -- one call for this language's whole pending-category
        # batch, then a single bounded pass over the most recent alerts.
        # RECOMMENDED_THROTTLE_SECONDS is 0 on Anthropic (real concurrency
        # already caps the rate) and a real per-call delay on Groq (its
        # free-tier per-minute cap can't tolerate a burst).
        translate_pending_categories(
            session, client, batch_size=25, max_langs=1, throttle_seconds=RECOMMENDED_THROTTLE_SECONDS, lang=lang
        )
        clients = build_translation_clients(
            settings.translation_groq_api_keys, settings.anthropic_api_key or None
        )
        translate_pending_alerts(
            session, clients, limit=ON_DEMAND_ALERT_LIMIT, throttle_seconds=RECOMMENDED_THROTTLE_SECONDS, lang=lang
        )
    except Exception:
        logger.exception("On-demand translation drain failed for lang=%s", lang)
    finally:
        with _lock:
            _running_langs.discard(lang)
        session.close()


@router.post("/run")
def run_translation(lang: str, background_tasks: BackgroundTasks):
    if lang == "en":
        return {"started": False}
    with _lock:
        already_running = lang in _running_langs
        if not already_running:
            _running_langs.add(lang)
    if not already_running:
        background_tasks.add_task(_drain_language, lang)
    return {"started": True}


@router.get("/status")
def translation_status(db: Session = Depends(get_db), lang: str = Depends(get_lang)):
    recent_alert_ids = [
        row[0]
        for row in db.query(Alert.id).order_by(Alert.created_at.desc()).limit(ON_DEMAND_ALERT_LIMIT).all()
    ]
    total = len(recent_alert_ids)
    if lang == "en":
        return {"total": total, "translated": total, "running": False}
    translated = (
        db.query(Alert)
        .join(Article, Alert.article_id == Article.id)
        .join(
            ArticleTranslation,
            (ArticleTranslation.article_id == Article.id) & (ArticleTranslation.lang == lang),
        )
        .filter(Alert.id.in_(recent_alert_ids))
        .count()
    )
    with _lock:
        running = lang in _running_langs
    return {"total": total, "translated": translated, "running": running}
