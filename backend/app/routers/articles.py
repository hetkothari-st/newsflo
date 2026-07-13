from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.i18n import get_lang
from app.models import Article
from app.translation.lookup import bulk_article_titles, bulk_category_labels

router = APIRouter(prefix="/api/articles", tags=["articles"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("")
def list_articles(db: Session = Depends(get_db), lang: str = Depends(get_lang)):
    articles = db.query(Article).order_by(Article.fetched_at.desc()).all()
    titles = bulk_article_titles(db, [a.id for a in articles], lang)
    categories = {a.category for a in articles if a.category is not None}
    category_labels = bulk_category_labels(db, list(categories), lang)
    return [{
        "id": a.id, "source": a.source, "title": titles.get(a.id, a.title), "url": a.url,
        "status": a.status, "category": a.category,
        "category_label": category_labels.get(a.category, a.category) if a.category else None,
        "image_url": a.image_url,
        "fetched_at": a.fetched_at.isoformat() if a.fetched_at else None,
    } for a in articles]
