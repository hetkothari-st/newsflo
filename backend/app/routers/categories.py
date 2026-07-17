from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.analysis.schemas import CATEGORIES
from app.i18n import get_lang
from app.routers.articles import get_db
from app.translation.lookup import bulk_category_labels

router = APIRouter(prefix="/api/categories", tags=["categories"])


@router.get("")
def list_categories(db: Session = Depends(get_db), lang: str = Depends(get_lang)):
    # The fixed taxonomy (CATEGORIES), not whatever distinct strings happen
    # to be in the DB -- Alert.category used to be unconstrained free text,
    # so deriving this list from the DB meant it mirrored whatever garbage
    # (including, once, a full sentence) the LLM had ever emitted. A
    # category is selectable here as soon as it exists in the taxonomy, not
    # only once some alert has actually used it.
    #
    # `category` stays the raw canonical slug -- WatchlistSettings sends it
    # straight back through PUT /api/watchlist and it's matched against
    # Alert.category server-side, so it must never be replaced by translated
    # text. `label` is the additive, display-only translated field.
    labels = bulk_category_labels(db, CATEGORIES, lang)
    return [{"category": c, "label": labels.get(c, c)} for c in CATEGORIES]
