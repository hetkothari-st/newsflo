"""Per-source ingestion health -- reads the IngestionSource rows the
collector runner maintains (app/ingestion/collector.py). Auth posture
matches every other router: any logged-in user (this app has no
admin/staff tier)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.ingestion.collector import _as_aware_utc
from app.models import IngestionSource, User, utcnow
from app.routers.articles import get_db

router = APIRouter(prefix="/api/source-health", tags=["source-health"])


@router.get("")
def list_source_health(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    now = utcnow()
    rows = db.query(IngestionSource).order_by(IngestionSource.slug).all()
    return [
        {
            "slug": row.slug,
            "display_name": row.display_name,
            "enabled": bool(row.enabled),
            "poll_interval_minutes": row.poll_interval_minutes,
            "breaker_open": bool(row.breaker_open_until and _as_aware_utc(row.breaker_open_until) > now),
            "breaker_open_until": row.breaker_open_until.isoformat() if row.breaker_open_until else None,
            "consecutive_failures": row.consecutive_failures,
            "last_run_at": row.last_run_at.isoformat() if row.last_run_at else None,
            "last_success_at": row.last_success_at.isoformat() if row.last_success_at else None,
            "last_fetched_count": row.last_fetched_count,
            "last_inserted_count": row.last_inserted_count,
            "avg_publish_to_fetch_latency_seconds": row.avg_publish_to_fetch_latency_seconds,
            "last_error": row.last_error,
            "last_error_at": row.last_error_at.isoformat() if row.last_error_at else None,
        }
        for row in rows
    ]
