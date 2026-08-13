"""Internal decision-record read path (corrective-v4 Task 18, spec sec54).

`company_decision_records` is the durable audit trail every v3 candidate
that reaches the publication boundary leaves behind -- accepted or
rejected, duplicate or excluded, unresolved ticker or ambiguous entity (see
app.pipeline._persist_alert / app.models.CompanyDecisionRecord). This
router is the ONLY read path for it: no frontend surface reads this table,
it exists purely so a maintainer (or backend/tools/generate_audit_report.py)
can answer "why was this shown / hidden" for one alert without re-running
paid analysis.

Mounted unconditionally in app.main -- the endpoint itself 404s when
settings.debug_audit_api is off, so the router's mere presence never
signals whether the feature is enabled (no information leak via route
existence). Default off: these rows carry gate_inputs_json/candidate_json
snapshots (full CandidateInput dumps, rationale text, mechanism prose) not
meant for casual/production exposure.

TWO conditions, both required (final-review finding I11): the flag AND an
authenticated user. The flag alone was the whole protection, so anyone who
knew the path could read the full audit trail of every alert on any
deployment that had ever turned it on -- an unauthenticated data-exposure
hole, not merely a debug convenience.
"""
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user_optional
from app.config import settings
from app.models import CompanyDecisionRecord, User
from app.routers.articles import get_db

router = APIRouter(prefix="/api/internal", tags=["internal"])


def _parse_json(raw: str | None):
    """Best-effort JSON parse for a *_json column. A row written before a
    column existed (or a manually-inserted test fixture) may carry NULL or
    malformed JSON -- neither should 500 the whole listing; both surface as
    None, honestly indistinguishable from "nothing recorded"."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def _serialize(record: CompanyDecisionRecord) -> dict:
    return {
        "id": record.id,
        "alert_id": record.alert_id,
        "company_id": record.company_id,
        "ticker": record.ticker,
        "final_state": record.final_state,
        "display_tier": record.display_tier,
        "rejection_reason": record.rejection_reason,
        "gates_passed": _parse_json(record.gates_passed_json),
        "evidence_class": record.evidence_class,
        "materiality_grade": record.materiality_grade,
        "candidate": _parse_json(record.candidate_json),
        "analysis_version": record.analysis_version,
        "discovery_sources": _parse_json(record.discovery_sources_json),
        "gate_inputs": _parse_json(record.gate_inputs_json),
        "evidence_ids": _parse_json(record.evidence_ids_json),
        "provider": record.provider,
        "model": record.model,
        "analysis_quality": record.analysis_quality,
        "correction": _parse_json(record.correction_json),
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


@router.get("/decisions/{alert_id}")
def get_decisions(
    alert_id: int,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    # ORDER IS LOAD-BEARING. Fails closed as a 404, not a 403: the flag
    # being off must read identically to the route not existing at all, so
    # nothing about this feature's deployment status leaks from the
    # response code alone -- which is exactly why the auth check below is
    # written by hand instead of declared as Depends(get_current_user).
    # FastAPI resolves declared dependencies BEFORE the handler body, so a
    # required-auth dependency would answer 401 on a flag-OFF deployment
    # and hand an unauthenticated caller the one bit this router is built
    # not to leak. `get_current_user_optional` never raises; it only
    # resolves a bearer token when one is present.
    if not settings.debug_audit_api:
        raise HTTPException(status_code=404, detail="not found")
    # Flag ON is not authorization (final-review finding I11): these rows
    # are full CandidateInput dumps, rationale text and mechanism prose.
    # Past this point the endpoint's existence is already admitted, so a
    # plain 401 is the honest answer.
    if user is None:
        raise HTTPException(
            status_code=401, detail="authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    records = (
        db.query(CompanyDecisionRecord)
        .filter_by(alert_id=alert_id)
        .order_by(CompanyDecisionRecord.final_state, CompanyDecisionRecord.ticker)
        .all()
    )
    return {"alert_id": alert_id, "decisions": [_serialize(r) for r in records]}
