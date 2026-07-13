from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.i18n import get_lang
from app.models import Alert
from app.routers.articles import get_db
from app.translation.lookup import bulk_category_labels

router = APIRouter(prefix="/api/categories", tags=["categories"])


@router.get("")
def list_categories(db: Session = Depends(get_db), lang: str = Depends(get_lang)):
    # Alert.category is free text (whatever the LLM returned), so the list of
    # selectable categories must come from the DB, not a hardcoded enum.
    #
    # `category` stays the raw canonical slug -- WatchlistSettings sends it
    # straight back through PUT /api/watchlist and it's matched against
    # Alert.category server-side, so it must never be replaced by translated
    # text. `label` is the additive, display-only translated field.
    categories = sorted(row[0] for row in db.query(Alert.category).distinct().all())
    labels = bulk_category_labels(db, categories, lang)
    return [{"category": c, "label": labels.get(c, c)} for c in categories]
