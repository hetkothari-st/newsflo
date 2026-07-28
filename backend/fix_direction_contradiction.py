"""One-off backfill: for the N most recently created alerts, reconcile each
AlertCompany.direction with its already-stored MarketMove.excess_move_pct
sign (same rule app.pipeline._persist_alert now applies going forward to
every new alert, added in commit 17ec32a), then regenerate AlertCompany.why
for every measured company on any alert that had a mismatch, so the
prose no longer contradicts the corrected direction (e.g. "positively
impacting the stock" next to a direction now flipped to bearish).

Only alerts with at least one real mismatch get touched at all -- an
alert whose stored direction already matches its measured sign is
skipped entirely (zero LLM calls, zero writes). This only ever fixes
existing AlertCompany rows already measured "ok"; it never adds/removes
companies, never re-runs sector-cascade analysis, and deliberately does
NOT call refine_alert (which would insert duplicate TimelineEffect rows
and regenerate the event summary) -- it calls generate_impact_whys
directly instead, scoped to only what this bug affects.

Prints the old/new direction and old/new why for every row it touches
before committing, so there is a console record of what changed.

Not part of the test suite and not imported by the app.

Usage (from the backend/ directory, against whichever DATABASE_URL is
active in the environment -- e.g. `railway run python fix_direction_contradiction.py`
to run against production):
    .venv/Scripts/python fix_direction_contradiction.py [N]
"""
import sys

from app.analysis.claude_client import build_client
from app.analysis.refinement import generate_impact_whys
from app.config import settings
from app.db import SessionLocal, init_db
from app.models import Alert, Company, MarketMove


def main(limit: int) -> None:
    init_db()
    session = SessionLocal()
    client = build_client(settings.groq_api_keys, settings.gemini_api_key or None)

    alerts = session.query(Alert).order_by(Alert.created_at.desc()).limit(limit).all()

    for alert in alerts:
        article = alert.article
        moves = session.query(MarketMove).filter_by(alert_id=alert.id).all()
        moves_by_company_id = {m.company_id: m for m in moves}

        measured = []
        mismatches = []
        for ac in alert.companies:
            move = moves_by_company_id.get(ac.company_id)
            if move is None or move.measurement_status != "ok" or move.excess_move_pct is None:
                continue
            correct_direction = "bullish" if move.excess_move_pct >= 0 else "bearish"
            company = session.get(Company, ac.company_id)
            if company is None:
                continue
            measured.append({
                "ticker": company.ticker, "name": company.name,
                "direction": correct_direction, "excess_move_pct": move.excess_move_pct,
                "_alert_company": ac,
            })
            if ac.direction != correct_direction:
                mismatches.append((ac, ac.direction, correct_direction))

        if not mismatches:
            continue

        print(f"\n=== Alert {alert.id}: {article.title} ===")
        for ac, old_direction, correct_direction in mismatches:
            print(f"  {ac.company.name} ({ac.company.ticker}): direction {old_direction} -> {correct_direction}")
            print(f"    OLD why: {ac.why}")
            ac.direction = correct_direction

        text = article.full_content or article.content
        whys = generate_impact_whys(client, article.title, text, [
            {k: v for k, v in m.items() if k != "_alert_company"} for m in measured
        ])
        for m in measured:
            why = whys.get(m["ticker"])
            if why:
                m["_alert_company"].why = why
                print(f"    NEW why ({m['ticker']}): {why}")

        session.commit()

    session.close()


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    main(limit)
