"""TASK 0.7 -- historical backfill of `company_impact` from `alert_companies`.

COMMITTED, NOT EXECUTED. Nothing runs on import; the whole job is behind
`if __name__ == "__main__"`, and this autonomous Phase 0 run did NOT execute
it against any database (controller adaptation: no bulk data mutation).
Running it is a deliberate act by the repo owner.

WHY A SCRIPT AND NOT A DATA MIGRATION
The V5 canonical record is keyed by (event_id, company_id, analysis_version).
Legacy `alert_companies` rows have no analysis_version at all -- the content
key (`alerts.content_key`) only exists from migration 0008 onward, and the
pre-0008 corpus is the majority. A migration that invented an identity for
those rows would be fabricating exactly the provenance V5 exists to
guarantee, so the backfill is opt-in, restartable and reports what it could
not map.

THE MAPPING, IN FULL (nothing outside this table is ever inferred):

  V4 column                      -> V5 column          rule
  ------------------------------------------------------------------------
  alert_companies.causal_directness -> directness       DIRECT|INDIRECT|REMOTE
                                                        pass through; any
                                                        other value -> NULL
  alert_companies.causal_distance   -> graph_distance   int pass-through;
                                                        NULL stays NULL
  alert_companies.discovery_source  -> discovery_source ARTICLE_MENTION ->
                                                        MENTION,
                                                        MECHANISM_MAPPING ->
                                                        MECHANISM,
                                                        everything else ->
                                                        NULL
  alert_companies.display_tier      -> publication_tier primary -> PRIMARY,
                                                        secondary_ripple (and
                                                        its two dead legacy
                                                        spellings) ->
                                                        SECONDARY_RIPPLE,
                                                        macro_context ->
                                                        REJECTED*, anything
                                                        else -> NULL row is
                                                        skipped

  * MACRO_CONTEXT may never carry a company (master context invariant 6), so
    a legacy macro_context ROW cannot become a company_impact row at that
    tier. It is written as REJECTED with rejection_reason
    MACRO_CONTEXT_HAS_NO_COMPANIES.

WHAT IS DELIBERATELY NOT MAPPED
  EXPOSURE_RULE, RIPPLE_DISCOVERY, ESCALATION, COMPLETENESS, CURATED and
  every unstamped/NULL discovery source have no V5 twin that is not a guess:
  a curated exposure rule is not a MENTION, and it is not necessarily a
  SUPPLY_CHAIN either. Those rows get discovery_source = NULL and
  needs_reanalysis = 1. The phase file is explicit: "Do not resolve the
  backfill ambiguity by guessing. NULL + needs_reanalysis is correct."

Usage:
    python backend/scripts/backfill_company_impact.py --dry-run
    python backend/scripts/backfill_company_impact.py --apply
"""
import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logger = logging.getLogger("backfill_company_impact")

DIRECTNESS_VALUES = ("DIRECT", "INDIRECT", "REMOTE")

DISCOVERY_SOURCE_MAP = {
    "ARTICLE_MENTION": "MENTION",
    "MECHANISM_MAPPING": "MECHANISM",
}

# Ruling R3 / migration 0008: two dead spellings of the same tier survive in
# restored-from-backup databases and must still be READ.
TIER_MAP = {
    "primary": "PRIMARY",
    "secondary_ripple": "SECONDARY_RIPPLE",
    "secondary_deep_dive": "SECONDARY_RIPPLE",
    "secondary": "SECONDARY_RIPPLE",
    "macro_context": "REJECTED",
}


def map_directness(value):
    """DIRECT | INDIRECT | REMOTE, or None. Never derived from distance --
    §11 is explicit that directness is NOT readable off causal_distance."""
    return value if value in DIRECTNESS_VALUES else None


def map_graph_distance(value):
    """An int, or None. Booleans are excluded explicitly: `isinstance(True,
    int)` is True in Python, so a boolean column value would otherwise be
    backfilled as distance 1 (fix round 1)."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def map_discovery_source(value):
    """V4 §22 discovery vocabulary -> the V5 four-value vocabulary.
    Unmappable -> None, which the caller pairs with needs_reanalysis = 1."""
    return DISCOVERY_SOURCE_MAP.get(str(value or "").strip().upper())


def map_publication_tier(value):
    """Returns (tier, rejection_reason). A tier this table does not know is
    (None, None) and the row is SKIPPED, not guessed into existence."""
    tier = TIER_MAP.get(str(value or "").strip().lower())
    if tier is None:
        return None, None
    if str(value).strip().lower() == "macro_context":
        return tier, "MACRO_CONTEXT_HAS_NO_COMPANIES"
    return tier, None


def build_row(alert_company, alert, reducer_version: str) -> dict | None:
    """One legacy AlertCompany -> one company_impact row payload, or None
    when the row cannot be mapped without guessing."""
    tier, rejection_reason = map_publication_tier(alert_company.display_tier)
    if tier is None:
        return None
    analysis_version = getattr(alert, "content_key", None)
    if not analysis_version:
        # No identity, no canonical row. Reported, never invented.
        return None

    directness = map_directness(alert_company.causal_directness)
    graph_distance = map_graph_distance(alert_company.causal_distance)
    discovery_source = map_discovery_source(alert_company.discovery_source)
    return {
        "event_id": f"article:{alert.article_id}",
        "company_id": alert_company.company_id,
        "analysis_version": analysis_version,
        "reducer_version": reducer_version,
        # Legacy rows are older than every fresh reduction by construction,
        # so a run seq of 0 guarantees they can never overwrite a real one.
        "reducer_run_seq": 0,
        "net_effect": (alert_company.economic_effect or "").upper() or None,
        "materiality_bucket": alert_company.materiality_grade,
        "directness": directness,
        "graph_distance": graph_distance,
        "discovery_source": discovery_source,
        "publication_tier": tier,
        "rejection_reason": rejection_reason,
        "needs_reanalysis": 1 if (directness is None or graph_distance is None
                                  or discovery_source is None) else 0,
        "gate_trace_json": json.dumps([]),
    }


def run(apply: bool) -> dict:
    from app.core.impact_writer import reducer_session, upsert_impact_row
    from app.core.reducer import REDUCER_VERSION
    from app.db import SessionLocal
    from app.models import Alert, AlertCompany

    session = SessionLocal()
    stats = {"seen": 0, "written": 0, "skipped_no_identity": 0,
             "skipped_unmappable_tier": 0, "needs_reanalysis": 0}
    try:
        rows = (session.query(AlertCompany, Alert)
                .join(Alert, AlertCompany.alert_id == Alert.id).all())
        for alert_company, alert in rows:
            stats["seen"] += 1
            payload = build_row(alert_company, alert, REDUCER_VERSION)
            if payload is None:
                key = ("skipped_unmappable_tier"
                       if map_publication_tier(alert_company.display_tier)[0] is None
                       else "skipped_no_identity")
                stats[key] += 1
                continue
            stats["needs_reanalysis"] += payload["needs_reanalysis"]
            if apply:
                with reducer_session(session):
                    upsert_impact_row(session, payload)
                stats["written"] += 1
        if apply:
            session.commit()
    finally:
        session.close()
    return stats


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true",
                       help="report what would be written, change nothing")
    group.add_argument("--apply", action="store_true",
                       help="write the mapped rows")
    args = parser.parse_args()

    stats = run(apply=args.apply)
    logger.info("backfill %s: %s", "APPLIED" if args.apply else "DRY RUN", stats)
    logger.info(
        "rows with a NULL separation field carry needs_reanalysis=1; they are "
        "honestly unmapped, not guessed (see this file's docstring)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
