import logging
import threading

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.config import settings
from app.i18n import get_lang
from app.models import Alert, Article, ArticleTranslation
from app.routers.articles import get_db
from app.translation.groq_translator import build_translation_client
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
# a full backlog is hundreds of alerts, which even on Anthropic would take
# minutes, defeating the point of an "instant" on-demand switch. The rest
# of the backlog keeps getting covered by the periodic scheduler job at its
# own pace. /status reports progress against this same bounded count so the
# progress bar can actually reach 100%.
ON_DEMAND_ALERT_LIMIT = 40


def _drain_language(lang: str) -> None:
    from app.db import SessionLocal  # local import: avoids import cost when unused

    session = SessionLocal()
    try:
        client = build_translation_client(settings.groq_api_keys, settings.anthropic_api_key or None)
        # Categories first (cheap, unblocks category_label everywhere at
        # once) -- one call for this language's whole pending-category
        # batch, then a single bounded pass over the most recent alerts.
        # No artificial throttle here -- translate_pending_alerts already
        # runs its calls concurrently (MAX_CONCURRENT_TRANSLATIONS), and this
        # is Anthropic (not Groq's free-tier per-minute wall), so there's no
        # rate-limit reason to add serial delay on top on this path.
        translate_pending_categories(session, client, batch_size=25, max_langs=1, lang=lang)
        translate_pending_alerts(session, client, limit=ON_DEMAND_ALERT_LIMIT, lang=lang)
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
