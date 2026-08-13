"""Offline decision-record audit report (corrective-v4 Task 18, spec sec54).

Prints a markdown table of every CompanyDecisionRecord for one alert --
ticker, final_state, tier, rejection_reason, evidence_class, materiality_
grade, analysis_version, discovery sources -- plus a per-record gate_inputs
detail block. Read-only DB access via app.db.SessionLocal; no LLM call, no
network -- this is a postmortem tool for "why was this shown / hidden" on
an alert that already ran, not a re-analysis.

    python tools/generate_audit_report.py <alert_id>

Run from the `backend/` directory (matches every other root-level script in
this repo, e.g. cost_optimization_report.py); a small sys.path fix below
also makes `python backend/tools/generate_audit_report.py <alert_id>` work
from the repo root.
"""
import json
import os
import sys

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from app.db import SessionLocal  # noqa: E402
from app.models import CompanyDecisionRecord  # noqa: E402


def _parse_json(raw: str | None):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return f"<unparseable JSON: {raw[:80]!r}>"


def _md_escape(value) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ") if value is not None else ""


def _table(records: list[CompanyDecisionRecord]) -> str:
    header = (
        "| ticker | final_state | tier | rejection_reason | evidence_class | "
        "materiality_grade | analysis_version | discovery_sources |"
    )
    sep = "|---|---|---|---|---|---|---|---|"
    rows = []
    for r in records:
        sources = _parse_json(r.discovery_sources_json)
        sources_str = ", ".join(sources) if isinstance(sources, list) else _md_escape(sources)
        rows.append(
            f"| {_md_escape(r.ticker)} | {_md_escape(r.final_state)} | "
            f"{_md_escape(r.display_tier)} | {_md_escape(r.rejection_reason)} | "
            f"{_md_escape(r.evidence_class)} | {_md_escape(r.materiality_grade)} | "
            f"{_md_escape(r.analysis_version)} | {sources_str} |"
        )
    return "\n".join([header, sep, *rows])


def _detail(records: list[CompanyDecisionRecord]) -> str:
    blocks = []
    for r in records:
        gate_inputs = _parse_json(r.gate_inputs_json)
        candidate = _parse_json(r.candidate_json)
        correction = _parse_json(r.correction_json)
        lines = [f"### {r.ticker} (record #{r.id})"]
        lines.append(f"- provider/model: {r.provider or '-'} / {r.model or '-'}")
        lines.append(f"- analysis_quality: {r.analysis_quality or '-'}")
        lines.append(f"- company_id: {r.company_id if r.company_id is not None else 'NULL (unresolved)'}")
        lines.append("- gate_inputs (CandidateInput snapshot):")
        lines.append(f"  ```json\n  {json.dumps(gate_inputs, indent=2) if gate_inputs else '{}'}\n  ```")
        if candidate:
            lines.append("- candidate_json:")
            lines.append(f"  ```json\n  {json.dumps(candidate, indent=2)}\n  ```")
        if correction:
            lines.append("- verifier correction applied:")
            lines.append(f"  ```json\n  {json.dumps(correction, indent=2)}\n  ```")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def generate_report(alert_id: int) -> str:
    session = SessionLocal()
    try:
        records = (
            session.query(CompanyDecisionRecord)
            .filter_by(alert_id=alert_id)
            .order_by(CompanyDecisionRecord.final_state, CompanyDecisionRecord.ticker)
            .all()
        )
        if not records:
            return f"# Decision-record audit: alert {alert_id}\n\nNo CompanyDecisionRecord rows found for this alert."
        parts = [
            f"# Decision-record audit: alert {alert_id}",
            "",
            f"{len(records)} decision(s) recorded.",
            "",
            _table(records),
            "",
            "## Detail",
            "",
            _detail(records),
        ]
        return "\n".join(parts)
    finally:
        session.close()


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python tools/generate_audit_report.py <alert_id>", file=sys.stderr)
        sys.exit(2)
    try:
        alert_id = int(sys.argv[1])
    except ValueError:
        print(f"alert_id must be an integer, got {sys.argv[1]!r}", file=sys.stderr)
        sys.exit(2)
    print(generate_report(alert_id))


if __name__ == "__main__":
    main()
