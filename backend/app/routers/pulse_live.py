"""Raw Pulse-by-Zerodha live feed: the pulse_zerodha articles exactly as
ingested, newest first. NO LLM anywhere in this path -- no relevance
gate, no analysis, no Gemini, no Groq: a plain DB read over rows the
ingestion collector already wrote. Curation is Pulse's own; dedup against
the other sources already happened at ingestion (collector idempotency
tiers)."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.models import Article
from app.routers.articles import get_db

router = APIRouter(prefix="/api/pulse-live", tags=["pulse-live"])


@router.get("")
def pulse_live(
    limit: int = Query(default=60, ge=1, le=200),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(Article)
        .filter(Article.provider == "pulse_zerodha")
        .order_by(Article.published_at.desc().nullslast(), Article.id.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": row.id,
            "title": row.title,
            "url": row.url,
            "summary": (row.content or "")[:300],
            "published_at": row.published_at.isoformat() if row.published_at else None,
            "fetched_at": row.fetched_at.isoformat() if row.fetched_at else None,
            "image_url": row.image_url or None,  # "" = scrape attempted, no image found
        }
        for row in rows
    ]
