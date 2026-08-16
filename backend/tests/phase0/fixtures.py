"""Shared Phase 0 fixture loading.

Everything here reads `tests/fixtures/phase0/crude_shock_event.json`, whose
every numeral-bearing object carries `"_fixture": true` (master context's
fabrication guard). No production module may import this file -- pinned by
`test_field_separation.py::test_no_production_module_imports_the_fixtures`.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "phase0"
CRUDE_SHOCK = FIXTURE_DIR / "crude_shock_event.json"

# One frozen instant for every fixture signal: the reducer must never read a
# clock, so the only timestamps in play are the ones the caller supplies.
FIXTURE_CREATED_AT = datetime(2026, 8, 17, 3, 30, tzinfo=timezone.utc)

PRIMARY_COMPANY_ID = 9001
REMOTE_COMPANY_ID = 9002

EVENT_ID = "fixture:crude-shock-1"
ANALYSIS_VERSION = "v3:fixture:pol-x:prompt-x:schema-x:kr-x:1:deadbeef"


def load_raw() -> dict:
    return json.loads(CRUDE_SHOCK.read_text(encoding="utf-8"))


def signals(company_id: int | None = None):
    """The fixture's Signal objects, optionally narrowed to one company."""
    from app.core.signals import make_signal

    raw = load_raw()
    out = []
    for item in raw["signals"]:
        if company_id is not None and item["company_id"] != company_id:
            continue
        out.append(make_signal(
            event_id=raw["event_id"],
            company_id=item["company_id"],
            stage=item["stage"],
            kind=item["kind"],
            payload=item["payload"],
            created_by=item["created_by"],
            analysis_version=raw["analysis_version"],
            created_at=FIXTURE_CREATED_AT,
        ))
    return out


def claims(company_id: int | None = None):
    from app.core.claims import Claim

    raw = load_raw()
    out = []
    for item in raw["claims"]:
        if company_id is not None and item["company_id"] != company_id:
            continue
        out.append(Claim(
            claim_id=item["claim_id"],
            event_id=raw["event_id"],
            company_id=item["company_id"],
            claim_type=item["claim_type"],
            fact_class=item["fact_class"],
            structured=item["structured"],
            evidence_ids=tuple(item["evidence_ids"]),
            created_by=item["created_by"],
        ))
    return out


def evidence():
    from app.core.claims import Evidence

    raw = load_raw()
    return [
        Evidence(
            evidence_id=item["evidence_id"],
            source_type=item["source_type"],
            source_name=item["source_name"],
            source_date=item["source_date"],
            company_ids=tuple(item["company_ids"]),
            quoted_text=item["quoted_text"],
            fact_text=item["fact_text"],
        )
        for item in raw["evidence"]
    ]


def reducer_config():
    """The DEPLOYED gate policy (backend/config/gates.yaml) plus the
    fixture's own event context -- fixtures must exercise the real policy,
    never a test-local copy of it."""
    from app.core.config_loader import load_gate_config
    from app.core.reducer import EventContext, ReducerConfig

    context = load_raw()["event_context"]
    return ReducerConfig(
        gate_config=load_gate_config(),
        event_context=EventContext(
            event_status=context["event_status"],
            shock_magnitude_confidence=context["shock_magnitude_confidence"],
            exposure_stale=context["exposure_stale"]))
