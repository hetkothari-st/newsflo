"""STEP 4 - import the sourced rows into company_exposure.

THE ONLY WRITE PATH IS THE REVIEW PATH. This script inserts an
`exposure_proposal` per row and then calls
`app.ledger.review.approve_proposal`, which is the single function in the
codebase permitted to write `company_exposure`. It does not touch that table
itself and could not: migration 0012's triggers refuse any connection without
a review session, which only `approve_proposal` opens.

WHAT EVERY ROW IS CLASSIFIED AS, and why (owner ruling 2026-08-17):

  measurement = ESTIMATED
      Not FILED. A FILED row means the filing states the share. None of
      these do: every one is a ratio COMPUTED from two filing figures, and
      several exclude a line the filing leaves ambiguous. ESTIMATED is the
      honest measurement for "computed from disclosed components".
      Consequence, and the point of the choice: with
      `exposure_measurement_grade_cap.ESTIMATED = D` in
      config/materiality.yaml, every channel resting on one of these rows is
      capped at evidence grade D, and gates.yaml gives PRIMARY
      `evidence_grades: [A, B, C]`. These rows CANNOT lead a publication.
      They can support SECONDARY_RIPPLE, which admits D.

  source_type = ANNUAL_REPORT, source_url = the exchange-hosted PDF
  created_by = the extractor run · reviewed_by = the approving human

  MARKERS live on the proposal's `raw_payload`, joinable from
  `company_exposure.proposal_id`. `company_exposure` has no free-text column
  and this script does not add one (a SQLite batch_alter_table on a
  triggered table silently drops its triggers -- 0008's warning). So a FLOOR
  marker is DOCUMENTATION AND NOT AN ENFORCED CAP: nothing in Phase 2 reads
  it. What is enforced is the grade D above. Recorded here rather than
  implied.

Usage:
    python scripts/ripple_bootstrap/import_ledger.py --reviewer "NAME"
    python scripts/ripple_bootstrap/import_ledger.py --reviewer "NAME" --dry-run
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import create_engine, text  # noqa: E402

from app.ledger.review import approve_proposal  # noqa: E402
from roster import BASE_KIND  # noqa: E402

FILINGS = REPO / "data" / "filings"

MEASUREMENT = "ESTIMATED"
SOURCE_TYPE = "ANNUAL_REPORT"
EXTRACTOR = "ingest:ripple_bootstrap/build_csv.py@v1"

# The extraction confidence carried onto `company_exposure.confidence`. It is
# the EXTRACTOR's confidence that it read the page correctly -- not a claim
# about the world and not a probability that the exposure is right. It is set
# low and uniformly rather than varied per row, because varying it would be
# inventing a per-company number nobody measured.
EXTRACTION_CONFIDENCE = 0.5


def db_url() -> str:
    return f"sqlite:///{(BACKEND / 'newsflo.db').as_posix()}"


def load_sourced() -> list[dict]:
    out = []
    for path in sorted(FILINGS.glob("*/finding.json")):
        for f in json.loads(path.read_text(encoding="utf-8")):
            if not f.get("unsourced"):
                out.append(f)
    return out


def share_of(f: dict) -> float:
    """Recompute the share here too. The importer must not trust a number
    it did not derive from the components."""
    def dec(raw):
        return float(str(raw).replace(",", "").strip())
    num = sum(dec(c["value"]) for c in f["numerator"])
    return num / dec(f["denominator"]["value"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reviewer", required=True,
                    help="the human approving these rows; recorded on every row")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    findings = load_sourced()
    engine = create_engine(db_url(), future=True)
    written, skipped = [], []

    with engine.begin() as conn:
        for f in findings:
            isin = f["isin"]
            company = conn.execute(
                text("SELECT id, ticker, name FROM companies WHERE isin = :isin"),
                {"isin": isin}).mappings().first()
            if company is None:
                skipped.append((isin, f["exposure_tag"], "no company row for ISIN"))
                continue

            meta = json.loads((FILINGS / isin / "source.json").read_text())
            share = share_of(f)
            base_value_inr = (float(str(f["denominator"]["value"]).replace(",", ""))
                              * float(f["unit_multiplier"]))
            num_page = str(f["source_page"])
            den_page = str(f["denominator"].get("page") or num_page)
            source_page = (num_page if den_page == num_page
                           else f"{num_page} + {den_page}")

            already = conn.execute(text(
                "SELECT count(*) FROM company_exposure "
                "WHERE company_id = :cid AND exposure_tag = :tag "
                "  AND as_of_date = :as_of"),
                {"cid": company["id"], "tag": f["exposure_tag"],
                 "as_of": f["as_of_date"]}).scalar_one()
            if already:
                skipped.append((isin, f["exposure_tag"],
                                "an identical (company, tag, as_of) row exists"))
                continue

            proposal_id = str(uuid.uuid4())
            payload = {
                "markers": f.get("markers") or [],
                "family": f["family"],
                "computed_from": f["computed_from"],
                "numerator": f["numerator"],
                "denominator": f["denominator"],
                "unit": f["unit"],
                "unit_multiplier": f["unit_multiplier"],
                "denominator_excerpt": f.get("denominator_excerpt"),
                "run": EXTRACTOR,
            }
            conn.execute(text(
                "INSERT INTO exposure_proposal ("
                " proposal_id, company_id, exposure_kind, exposure_tag,"
                " share_of_base, base_kind, base_value_inr, measurement,"
                " source_type, source_url, source_page, excerpt,"
                " extraction_confidence, model_id, created_by,"
                " extractor_version, document_sha256, as_of_date, raw_payload,"
                " status) VALUES ("
                " :proposal_id, :company_id, :exposure_kind, :exposure_tag,"
                " :share_of_base, :base_kind, :base_value_inr, :measurement,"
                " :source_type, :source_url, :source_page, :excerpt,"
                " :extraction_confidence, :model_id, :created_by,"
                " :extractor_version, :document_sha256, :as_of_date,"
                " :raw_payload, 'PENDING_REVIEW')"), {
                    "proposal_id": proposal_id,
                    "company_id": int(company["id"]),
                    "exposure_kind": f["exposure_kind"],
                    "exposure_tag": f["exposure_tag"],
                    "share_of_base": share,
                    "base_kind": BASE_KIND[f["family"]],
                    "base_value_inr": base_value_inr,
                    "measurement": MEASUREMENT,
                    "source_type": SOURCE_TYPE,
                    "source_url": meta["source_url"],
                    "source_page": source_page,
                    "excerpt": f["verbatim_excerpt"],
                    "extraction_confidence": EXTRACTION_CONFIDENCE,
                    "model_id": None,
                    "created_by": EXTRACTOR,
                    "extractor_version": EXTRACTOR,
                    "document_sha256": meta["sha256"],
                    "as_of_date": f["as_of_date"],
                    "raw_payload": json.dumps(payload, ensure_ascii=False),
                })

            if args.dry_run:
                conn.execute(text(
                    "UPDATE exposure_proposal SET status = 'REJECTED', "
                    "reject_reason = 'dry run' WHERE proposal_id = :id"),
                    {"id": proposal_id})
                written.append((company["ticker"], f["exposure_tag"], share,
                                base_value_inr, "DRY-RUN (proposal only)"))
                continue

            exposure_id = approve_proposal(conn, proposal_id,
                                           reviewed_by=args.reviewer)
            written.append((company["ticker"], f["exposure_tag"], share,
                            base_value_inr, exposure_id))

    print(f"{'ticker':<13}{'tag':<34}{'share':>8}  {'base_value_inr':>18}  id")
    for ticker, tag, share, base, eid in written:
        print(f"{ticker:<13}{tag:<34}{share:>8.4f}  {base:>18,.0f}  {eid}")
    print(f"\nimported: {len(written)}   skipped: {len(skipped)}")
    for isin, tag, why in skipped:
        print(f"  SKIP {isin} {tag}: {why}")

    if not args.dry_run:
        with engine.begin() as conn:
            rows = conn.execute(text(
                "SELECT e.exposure_tag, c.ticker, e.share_of_base, e.measurement,"
                "       e.as_of_date, e.freshness_days, e.reviewed_by,"
                "       julianday(:today) - julianday(e.as_of_date) AS age_days "
                "FROM company_exposure e JOIN companies c ON c.id = e.company_id "
                "ORDER BY c.ticker, e.exposure_tag"),
                {"today": date.today().isoformat()}).mappings().all()
        print(f"\ncompany_exposure now holds {len(rows)} rows "
              f"(checked {datetime.now(timezone.utc).isoformat(timespec='seconds')})")
        stale = [r for r in rows if r["age_days"] > r["freshness_days"]]
        print(f"of which already STALE by freshness policy: {len(stale)}")
        for r in stale:
            print(f"  STALE {r['ticker']:<12}{r['exposure_tag']:<34}"
                  f"{int(r['age_days'])}d old vs {r['freshness_days']}d policy")


if __name__ == "__main__":
    main()
