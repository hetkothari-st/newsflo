from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.models import Alert
from app.routers.articles import get_db

router = APIRouter(prefix="/api/categories", tags=["categories"])


@router.get("")
def list_categories(db: Session = Depends(get_db)):
    # Alert.category is free text (whatever the LLM returned), so the list of
    # selectable categories must come from the DB, not a hardcoded enum.
    rows = db.query(Alert.category).distinct().all()
    return sorted(row[0] for row in rows)
