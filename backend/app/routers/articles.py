from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Article

router = APIRouter(prefix="/api/articles", tags=["articles"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("")
def list_articles(db: Session = Depends(get_db)):
    articles = db.query(Article).order_by(Article.fetched_at.desc()).all()
    return [{
        "id": a.id, "source": a.source, "title": a.title, "url": a.url,
        "status": a.status, "category": a.category, "image_url": a.image_url,
        "fetched_at": a.fetched_at.isoformat() if a.fetched_at else None,
    } for a in articles]
